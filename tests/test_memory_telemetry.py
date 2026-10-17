"""memory-telemetry against fake /proc, /sys, oomd configuration and journalctl trees.

Nothing here reads the live host or the live journal, starts a unit, or signals
any process other than the collector and fake journalctl the tests start.
"""

from __future__ import annotations

import gzip
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "home/private_dot_local/bin/executable_memory-telemetry"
UNIT = ROOT / "home/dot_config/systemd/user/memory-telemetry.service"
WANTS = ROOT / "home/dot_config/systemd/user/default.target.wants/symlink_memory-telemetry.service"
UID = os.getuid()
# Strings that must never reach the record: argv, environment, comm and
# journal fields outside the allowlist.
SECRETS = ("ARGV-SENTINEL-7f3a", "ENVIRON-SENTINEL-91c2", "COMM-SENTINEL", "CMDLINE-SENTINEL-55d0")


def load_module():
    sys.dont_write_bytecode = True
    loader = importlib.machinery.SourceFileLoader("memory_telemetry", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


mt = load_module()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def psi(some_total: int, full_total: int) -> str:
    return (f"some avg10=0.10 avg60=0.20 avg300=0.30 total={some_total}\n"
            f"full avg10=0.01 avg60=0.02 avg300=0.03 total={full_total}\n")


GIB_KIB = 1024 * 1024
MEMINFO = {
    "MemTotal": 100 * GIB_KIB,
    "MemAvailable": 30 * GIB_KIB,
    "SwapTotal": 40 * GIB_KIB,
    "SwapFree": 1 * GIB_KIB,
    "Zswap": 8 * GIB_KIB,
    "Zswapped": 30 * GIB_KIB,
    "GPUActive": 2 * GIB_KIB,
    "GPUReclaim": 1024,
}

# pid: (exe path or None for unreadable, ppid, RssAnon, VmSwap) in the Claude scope.
CLAUDE_PROCESSES = {
    100: ("/usr/lib/claude-desktop/claude", 1, 400_000, 100_000),
    101: ("/usr/lib/claude-desktop/claude", 100, 300_000, 50_000),
    110: ("/var/lib/fixture/claude-code/2.1/abc/claude", 100, 500_000, 200_000),
    111: ("/usr/bin/node", 110, 900_000, 700_000),
    112: ("/usr/bin/zsh", 110, 5_000, 1_000),
    113: ("/opt/codex/bin/codex", 112, 200_000, 10_000),
    114: ("/usr/bin/node", 113, 150_000, 0),
    120: ("/usr/bin/zsh", 1, 4_000, 9_000),
    130: (None, 100, 1_000, 0),
}


class Fixture:
    """A fake host: /proc, /sys/fs/cgroup, /sys/class/drm and oomd.conf under one directory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.proc = root / "proc"
        self.sys = root / "sys"
        self.config = root / "config"
        self.cgroup = self.sys / "fs/cgroup"
        self.user = self.cgroup / "user.slice" / f"user-{UID}.slice"
        self.apps = self.user / f"user@{UID}.service" / "app.slice"
        self.claude = self.apps / "app-com.anthropic.Claude-100.scope"
        self.chromium = self.apps / "app-org.chromium.Chromium-200.scope"
        self.indexer = self.user / f"user@{UID}.service" / "background.slice" / "indexer.service"
        self.builds = self.user / f"user@{UID}.service" / "builds.slice"
        self.system_service = self.cgroup / "system.slice" / "inference.service"
        self.build()

    def meminfo(self, **values: int) -> None:
        merged = MEMINFO | values
        write(self.proc / "meminfo", "".join(f"{key}: {value} kB\n" for key, value in merged.items()))

    def vmstat(self, **values: int) -> None:
        base = {"pswpin": 10, "pswpout": 20, "zswpin": 300, "zswpout": 400, "zswpwb": 20,
                "workingset_refault_anon": 50, "pgmajfault": 60, "oom_kill": 0,
                "allocstall_normal": 1, "allocstall_movable": 2, "nr_free_pages": 7}
        write(self.proc / "vmstat", "".join(f"{key} {value}\n" for key, value in (base | values).items()))

    def cgroup_files(self, path: Path, current: int, swap: int, procs: list[int] = ()) -> None:
        write(path / "memory.current", f"{current}\n")
        write(path / "memory.peak", f"{current * 2}\n")
        write(path / "memory.swap.current", f"{swap}\n")
        write(path / "memory.swap.peak", f"{swap}\n")
        write(path / "memory.stat", f"anon {current // 2}\nfile 10\nzswapped {swap - 5}\nzswpin 7\npgscan 9\n")
        write(path / "memory.events.local",
              "low 0\nhigh 4\nmax 0\noom 0\noom_kill 0\noom_group_kill 0\nsock_throttled 0\n")
        write(path / "memory.swap.events", "high 0\nmax 0\nfail 1234\n")
        write(path / "memory.pressure", psi(1_000_000, 500_000))
        write(path / "memory.oom.group", "0\n")
        write(path / "pids.current", "42\n")
        write(path / "pids.peak", "50\n")
        write(path / "pids.max", "max\n" if not procs else "152824\n")
        write(path / "pids.events", "max 0\n")
        write(path / "cgroup.events", "populated 1\nfrozen 0\n")
        write(path / "cgroup.procs", "".join(f"{pid}\n" for pid in procs))

    def status(self, pid: int, ppid: int, anon: int, swap: int, name: str = "COMM-SENTINEL") -> None:
        write(self.proc / str(pid) / "status", (
            f"Name:\t{name}\nPid:\t{pid}\nPPid:\t{ppid}\nVmRSS:\t{anon + 10} kB\n"
            f"RssAnon:\t{anon} kB\nRssFile:\t10 kB\nRssShmem:\t0 kB\nVmSwap:\t{swap} kB\n"
        ))

    def process(self, pid: int, exe: str | None, ppid: int, anon: int, swap: int, name: str = "COMM-SENTINEL") -> None:
        folder = self.proc / str(pid)
        self.status(pid, ppid, anon, swap, name)
        write(folder / "cmdline", f"{exe}\0--token\0ARGV-SENTINEL-7f3a\0")
        write(folder / "environ", "MEMORY_TELEMETRY_FIXTURE=ENVIRON-SENTINEL-91c2\0")
        write(folder / "comm", "COMM-SENTINEL\n")
        if exe is not None:
            os.symlink(exe, folder / "exe")

    def build(self) -> None:
        self.meminfo()
        self.vmstat()
        write(self.proc / "pressure/memory", psi(10_000_000, 4_000_000))
        write(self.proc / "pressure/io", psi(20_000_000, 8_000_000))
        write(self.proc / "sys/kernel/random/boot_id", "0123abcd-0000-4000-8000-00000000beef\n")
        self.cgroup_files(self.user, 60 << 30, 35 << 30)
        self.cgroup_files(self.apps, 50 << 30, 30 << 30)
        self.cgroup_files(self.claude, 20 << 30, 12 << 30, list(CLAUDE_PROCESSES))
        for pid, (exe, ppid, anon, swap) in CLAUDE_PROCESSES.items():
            self.process(pid, exe, ppid, anon, swap)
        self.cgroup_files(self.chromium, 10 << 30, 1 << 30, [200, 201])
        self.process(200, "/opt/ChatGPT/ChatGPT", 1, 100_000, 0)
        self.process(201, "/opt/codex/bin/codex", 200, 300_000, 0)
        # Not matched by the watch patterns, but an oomd swap candidate in this user's slice.
        self.cgroup_files(self.indexer, 8 << 30, 15 << 30, [300])
        self.process(300, "/usr/bin/indexer", 1, 50_000, 900_000)
        # The #366 build jobs' slice; MemorySwapMax=0 keeps it out of swap.
        self.cgroup_files(self.builds, 2 << 30, 0)
        # Another user's service: ranked by swap, never attributed.
        self.cgroup_files(self.system_service, 5 << 30, 3 << 30)
        device = self.sys / "devices/pci0000:00/0000:c5:00.0"
        memory = {"gtt_used": 7 << 30, "gtt_total": 112 << 30, "vram_used": 1 << 29, "vram_total": 1 << 30}
        for key, value in memory.items():
            write(device / f"mem_info_{key}", f"{value}\n")
        drm = self.sys / "class/drm"
        for name in ("card0", "card0-DP-1", "renderD128"):  # only cardN holds memory counters
            (drm / name).mkdir(parents=True)
        os.symlink(device, drm / "card0/device")
        write(self.config / "etc/systemd/oomd.conf", "[OOM]\n#SwapUsedLimit=50%\nSwapUsedLimit=90%\n")
        self.oomctl = self.root / "fake-oomctl"
        write(self.oomctl, f"#!{sys.executable}\nprint('''Dry Run: no\nSwap Used Limit: 90.00%\n"
              "Default Memory Pressure Limit: 60.00%\nDefault Memory Pressure Duration: 30s\n"
              "Swap Monitored CGroups:\n  Path: /system.slice\nMemory Pressure Monitored CGroups:\n"
              "  Path: /system.slice\n    Memory Pressure Limit: 80.00%\n"
              "    Memory Pressure Duration: 30s\nUNRELATED-SENTINEL\n''')\n")
        self.oomctl.chmod(0o755)

    def sources(self):
        return mt.Sources(self.proc, self.sys, self.config, UID)

    def options(self, *extra: str) -> list[str]:
        return ["--proc-root", str(self.proc), "--sys-root", str(self.sys), "--config-root", str(self.config),
                "--oomctl", str(self.oomctl), *extra]


class FixtureCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.fixture = Fixture(self.base / "host")
        self.state = self.base / "state"


class ParserTests(unittest.TestCase):
    def test_parsers_ignore_malformed_lines(self) -> None:
        self.assertEqual(mt.parse_meminfo("MemTotal: 10 kB\nbogus\nHugePages_Total: 0\nX: y kB\n"),
                         {"MemTotal": 10, "HugePages_Total": 0})
        self.assertEqual(mt.parse_keyed("a 1\nb x\nc -2\nd 1 2\n\n"), {"a": 1, "c": -2})
        parsed = mt.parse_psi("some avg10=1.50 avg60=0.00 avg300=0.00 total=99\nfull broken\n\n")
        self.assertEqual(parsed, {"some": {"avg10": 1.5, "avg60": 0.0, "avg300": 0.0, "total_us": 99}})
        self.assertIsNone(mt.parse_psi(None))
        self.assertIsNone(mt.parse_psi("garbage\n"))

    def test_fractions_follow_systemd_percent_forms(self) -> None:
        self.assertEqual(mt.parse_fraction("90%"), 0.9)
        self.assertEqual(mt.parse_fraction("905‰"), 0.905)
        self.assertEqual(mt.parse_fraction("9050‱"), 0.905)
        for bad in ("90", "abc%", "150%", "-1%"):
            self.assertIsNone(mt.parse_fraction(bad), bad)

    def test_oomd_limit_reads_main_file_and_drop_ins_in_systemd_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary)
            self.assertEqual(mt.oomd_swap_used_limit(config), (0.9, "default", {}))
            write(config / "usr/lib/systemd/oomd.conf", "[OOM]\nSwapUsedLimit=50%\n")
            write(config / "etc/systemd/oomd.conf", "[OOM]\nSwapUsedLimit=80%\n[Other]\nSwapUsedLimit=10%\n")
            self.assertEqual(mt.oomd_swap_used_limit(config), (0.8, "etc/systemd/oomd.conf", {}))
            # A drop-in in /etc masks the same name in /usr/lib; later names win.
            write(config / "usr/lib/systemd/oomd.conf.d/50-a.conf", "[OOM]\nSwapUsedLimit=60%\n")
            write(config / "etc/systemd/oomd.conf.d/50-a.conf", "[OOM]\nSwapUsedLimit=70%\n")
            self.assertEqual(mt.oomd_swap_used_limit(config), (0.7, "etc/systemd/oomd.conf.d/50-a.conf", {}))
            write(config / "run/systemd/oomd.conf.d/60-b.conf", "[OOM]\nSwapUsedLimit=65%\n")
            self.assertEqual(mt.oomd_swap_used_limit(config), (0.65, "run/systemd/oomd.conf.d/60-b.conf", {}))
            write(config / "run/systemd/oomd.conf.d/70-c.conf", "[OOM]\nSwapUsedLimit=\n")
            self.assertEqual(mt.oomd_swap_used_limit(config), (0.9, "default", {}))

    def test_unreadable_oomd_configuration_is_named_not_assumed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary)
            (config / "etc/systemd/oomd.conf.d/80-unreadable.conf").mkdir(parents=True)  # unreadable even for root
            limit, source, errors = mt.oomd_swap_used_limit(config)
            self.assertEqual((limit, source), (0.9, "default (configuration unreadable)"))
            self.assertEqual(errors, {"config:etc/systemd/oomd.conf.d/80-unreadable.conf": "IsADirectoryError"})
            write(config / "etc/systemd/oomd.conf", "[OOM]\nSwapUsedLimit=85%\n")
            self.assertEqual(mt.oomd_swap_used_limit(config)[:2], (0.85, "etc/systemd/oomd.conf"))

    def test_oomd_configuration_that_cannot_be_looked_up_is_named_not_raised(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary)
            write(config / "usr/lib/systemd/oomd.conf", "[OOM]\nSwapUsedLimit=50%\n")
            (config / "etc").mkdir()
            os.symlink("systemd", config / "etc/systemd")  # a loop: every lookup through it fails, even for root
            self.assertEqual(mt.oomd_swap_used_limit(config), (0.5, "usr/lib/systemd/oomd.conf", {
                "config:etc/systemd/oomd.conf": "OSError", "config:etc/systemd/oomd.conf.d": "OSError"}))
            (config / "etc/systemd").unlink()
            if os.geteuid() == 0:
                return  # permission bits do not bind root
            write(config / "etc/systemd/oomd.conf.d/70-a.conf", "[OOM]\nSwapUsedLimit=70%\n")
            try:
                (config / "etc/systemd/oomd.conf.d").chmod(0)  # the drop-in it hides is named, not skipped
                self.assertEqual(mt.oomd_swap_used_limit(config), (0.5, "usr/lib/systemd/oomd.conf", {
                    "config:etc/systemd/oomd.conf.d": "PermissionError"}))
                (config / "etc/systemd").chmod(0)  # unsearchable: Path.is_file raised here on Python 3.12
                self.assertEqual(mt.oomd_swap_used_limit(config), (0.5, "usr/lib/systemd/oomd.conf", {
                    "config:etc/systemd/oomd.conf": "PermissionError",
                    "config:etc/systemd/oomd.conf.d": "PermissionError"}))
            finally:
                (config / "etc/systemd").chmod(0o700)
                (config / "etc/systemd/oomd.conf.d").chmod(0o700)

    def test_kernel_oom_lines_lose_the_task_name_and_fail_closed(self) -> None:
        gfp = "gfp_mask=0x140cca(GFP_HIGHUSER_MOVABLE|__GFP_COMP), order=0, oom_score_adj=300"
        lines = {
            f"COMM-SENTINEL x invoked oom-killer: {gfp}": (f"(task) invoked oom-killer: {gfp}", True),
            "oom-kill:constraint=CONSTRAINT_MEMCG,nodemask=(null),cpuset=/,mems_allowed=0,oom_memcg=/u.slice,"
            "task_memcg=/user.slice/x.scope,task=COMM-SENTINEL,pid=4242,uid=1000":
                ("oom-kill:constraint=CONSTRAINT_MEMCG,nodemask=(null),cpuset=/,mems_allowed=0,oom_memcg=/u.slice,"
                 "task_memcg=/user.slice/x.scope,task=(task),pid=4242,uid=1000", True),
            "Out of memory: Killed process 4242 (COMM-SENTINEL) total-vm:10kB, anon-rss:5kB, file-rss:0kB, "
            "shmem-rss:0kB, UID:1000 pgtables:8kB oom_score_adj:300":
                ("Out of memory: Killed process 4242 (task) total-vm:10kB, anon-rss:5kB, file-rss:0kB, "
                 "shmem-rss:0kB, UID:1000 pgtables:8kB oom_score_adj:300", True),
            "Memory cgroup out of memory: Killed process 4242 (COMM-SENTINEL) total-vm:1kB":
                ("Memory cgroup out of memory: Killed process 4242 (task) total-vm:1kB", True),
            "oom_reaper: reaped process 4242 (COMM-SENTINEL), now anon-rss:0kB, file-rss:0kB, shmem-rss:0kB":
                ("oom_reaper: reaped process 4242 (task), now anon-rss:0kB, file-rss:0kB, shmem-rss:0kB", False),
            "oom_reaper: unable to reap pid:4242 (COMM-SENTINEL)":
                ("oom_reaper: unable to reap pid:4242 (task)", False),
        }
        for line, expected in lines.items():
            self.assertEqual(mt.kernel_oom_line(line), expected)
        # Task names can hold spaces, parentheses, commas, the format's own words, and newlines.
        for name in ("a b) total-vm:1kB, (c", "x,pid=1,uid=2", "COMM\nSENTINEL", "(task) invoked"):
            for line in (f"{name} invoked oom-killer: {gfp}",
                         f"oom-kill:constraint=CONSTRAINT_NONE,task={name},pid=4242,uid=1000",
                         f"Out of memory: Killed process 4242 ({name}) total-vm:10kB, anon-rss:5kB",
                         f"oom_reaper: reaped process 4242 ({name}), now anon-rss:0kB",
                         f"oom_reaper: unable to reap pid:4242 ({name})"):
                message, _ = mt.kernel_oom_line(line)
                for fragment in ("SENTINEL", "a b)", "x,pid=1", "(c"):
                    self.assertNotIn(fragment, message, line)
        # The rest of the OOM report lists every task by name, and other kernel messages mention
        # memory; none of them opens a record or keeps its text.
        self.assertIsNone(mt.kernel_oom_line("[   4242]  1000  4242  1234  567  0  300 COMM-SENTINEL"))
        for line in ("JBD2: Out of memory during recovery.",
                     "oom-kill:[4242]: segfault at 0 ip 0 sp 0 error 4 in COMM-SENTINEL[1000+1000]",
                     f"x[1]: segfault at 0 error 4 in y invoked oom-killer: {gfp}[7f00+10]"):
            self.assertEqual(mt.kernel_oom_line(line), (mt.KERNEL_OOM_UNRECOGNIZED, False), line)


class SampleTests(FixtureCase):
    def test_reserves_preserve_zones_buddy_orders_and_metadata_counts(self) -> None:
        write(self.fixture.proc / "zoneinfo", "Node 0, zone DMA\n  pages free 12\n min 2\n low 3\n high 4\n"
              " boost 5\n managed 100\n protection: (0, 1)\nNode 1, zone Normal\n pages free 120\n min 20\n")
        write(self.fixture.proc / "buddyinfo", "Node 0, zone DMA 1 2 3 4\nNode 1, zone Normal 5 6 7 8\nbad\n")
        write(self.fixture.proc / "sys/fs/dentry-state", "100 50 45 0 7 -1\n")
        write(self.fixture.proc / "sys/fs/inode-state", "200 100 0 0 0 0 0\n")
        sources = self.fixture.sources()
        sample, _, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH), [], 100.0, "boot", None)
        self.assertEqual(sample["reserves"], {
            "zones": {"0:DMA": {"free": 12, "min": 2, "low": 3, "high": 4, "boost": 5, "managed": 100},
                      "1:Normal": {"free": 120, "min": 20}},
            "buddy": {"0:DMA": [1, 2, 3, 4], "1:Normal": [5, 6, 7, 8]},
            "dentry_state": [100, 50, 45, 0, 7, -1], "inode_state": [200, 100, 0, 0, 0, 0, 0],
        })
        for name in ("zoneinfo", "buddyinfo", "sys/fs/dentry-state", "sys/fs/inode-state"):
            (self.fixture.proc / name).unlink()
        missing, _, _ = mt.slow_sample(sources, [], [], 160.0, "boot", sample)
        self.assertEqual(missing["reserves"], {"zones": None, "buddy": None,
                         "dentry_state": None, "inode_state": None})

    def test_holder_union_adds_detail_without_expanding_process_attribution(self) -> None:
        root = self.fixture.cgroup / "system.slice"
        for number in range(6):
            self.fixture.cgroup_files(root / f"resident-{number}.service", (50 + number) << 30, 0)
            self.fixture.cgroup_files(root / f"swapped-{number}.service", 1 << 30, (30 + number) << 30)
        inference = root / "ollama.service"
        self.fixture.cgroup_files(inference, 1, 0)
        # Include an inference parent even when the existing walk descends into its children.
        self.fixture.cgroup_files(inference / "runner", 1, 0)
        jobs = self.fixture.builds.with_name("jobs.slice")
        self.fixture.cgroup_files(jobs, 1, 0)
        sources = self.fixture.sources()
        read = sources.text

        def no_added_process_scan(path, required=False):
            if path.name == "cgroup.procs" and (path.is_relative_to(root) or path.is_relative_to(jobs)):
                self.fail(f"new process scan: {path}")
            return read(path, required)

        with mock.patch.object(sources, "text", no_added_process_scan):
            sample, watched, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH),
                ["system.slice", f"user.slice/user-{UID}.slice"], 100.0, "boot", None)
        recorded = {block["path"] for block in sample["cgroups"].values()}
        for number in range(1, 6):
            self.assertIn(f"system.slice/resident-{number}.service", recorded)
            self.assertIn(f"system.slice/swapped-{number}.service", recorded)
        self.assertNotIn("system.slice/resident-0.service", recorded)
        self.assertNotIn("system.slice/swapped-0.service", recorded)
        self.assertIn("system.slice/ollama.service", recorded)
        self.assertIn(sources.cgroup_name(jobs), recorded)
        self.assertEqual(set(sample["t9"]), set(watched))
        self.assertFalse(any("resident-" in name or "swapped-" in name or "ollama" in name for name in watched))
        self.assertEqual(sample["swap_holders"]["top_by_memory"][0]["cgroup"], "system.slice/resident-5.service")

    def test_cgroup_detail_retains_complete_stats_pressure_and_ancestor_limits(self) -> None:
        group = self.fixture.claude
        for path in (group, *group.parents):
            if path == self.fixture.cgroup:
                break
            for name in ("memory.high", "memory.max", "memory.swap.high", "memory.swap.max", "memory.zswap.max"):
                write(path / name, "max\n")
        write(group / "memory.max", "500\n")
        write(group.parent / "memory.high", "300\n")
        write(group.parent / "memory.swap.max", "0\n")
        write(group.parent / "memory.zswap.max", "80\n")
        write(group / "memory.zswap.current", "12\n")
        write(group / "memory.stat", "anon 11\nfile 22\npgscan 33\nfuture_counter 44\n")
        write(group / "cpu.stat", "usage_usec 100\nuser_usec 60\nsystem_usec 40\nnr_throttled 2\n"
              "throttled_usec 30\nextra 999\n")
        write(group / "io.stat", "259:0 rbytes=10 wbytes=20 rios=3 wios=4 dbytes=99\n"
              "253:0 rbytes=5 wbytes=6 rios=7 wios=8\nmalformed\n")
        write(group / "io.pressure", psi(200, 100))
        write(group / "cpu.pressure", psi(300, 20))
        sources = self.fixture.sources()
        first, _, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH),
                                     [f"user.slice/user-{UID}.slice"], 100.0, "boot", None)
        block = first["cgroups"][group.name]
        self.assertEqual(block["stat"], {"anon": 11, "file": 22, "pgscan": 33, "future_counter": 44})
        self.assertEqual(block["zswap_bytes"], 12)
        self.assertEqual(block["effective_limits"], {"memory.high": 300, "memory.max": 500,
                         "memory.swap.high": "max", "memory.swap.max": 0, "memory.zswap.max": 80})
        self.assertEqual(block["limits"]["memory.max"], 500)
        self.assertEqual(block["limits"]["memory.high"], "max")
        self.assertEqual(block["cpu_stat"], {"usage_usec": 100, "user_usec": 60, "system_usec": 40,
                         "nr_throttled": 2, "throttled_usec": 30})
        self.assertEqual(block["io_stat"]["259:0"], {"rbytes": 10, "wbytes": 20, "rios": 3, "wios": 4})
        self.assertEqual(block["pressure"]["memory"]["some"]["total_us"], 1_000_000)
        self.assertEqual(block["pressure"]["io"]["full"]["total_us"], 100)
        self.assertEqual(block["pressure"]["cpu"]["some"]["total_us"], 300)
        self.assertEqual(len(block["identity"]), 2)
        (group / "memory.zswap.current").unlink()
        (group / "cpu.stat").unlink()
        (group / "io.stat").unlink()
        (group / "cpu.pressure").unlink()
        (group.parent / "memory.max").unlink()
        second, _, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH),
                                      [f"user.slice/user-{UID}.slice"], 160.0, "boot", first)
        missing = second["cgroups"][group.name]
        self.assertIsNone(missing["zswap_bytes"])
        self.assertEqual(missing["cpu_stat"], {})
        self.assertEqual(missing["io_stat"], {})
        self.assertIsNone(missing["pressure"]["cpu"])
        self.assertIsNone(missing["effective_limits"]["memory.max"])
        self.assertIn(sources.cgroup_name(group.parent) + "/memory.max", missing["limits_unavailable"])
        group.rename(group.with_name("old.scope"))
        self.fixture.cgroup_files(group, 1, 0)
        recreated, _, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH),
                                         [f"user.slice/user-{UID}.slice"], 220.0, "boot", second)
        self.assertNotEqual(recreated["cgroups"][group.name]["identity"], block["identity"])

    def test_storage_keeps_layers_and_omits_rates_after_reset_or_replacement(self) -> None:
        disks = self.fixture.proc / "diskstats"
        write(disks, "259 0 nvme0n1 10 2 30 40 50 6 70 80 9 100 110\n"
              "253 0 dm-0 20 0 60 80 100 0 140 160 0 200 220\n"
              "9 0 md0 1 0 3 4 5 0 7 8 0 10 11\n7 0 loop0 1 0 3 4 5 0 7 8 0 10 11\n"
              "259 1 nvme0n1p1 1 0 3 4 5 0 7 8 0 10 11\nmalformed\n")
        write(self.fixture.sys / "class/block/nvme0n1/diskseq", "42\n")
        sources = self.fixture.sources()
        first = mt.fast_sample(sources, 0.9, {}, 100.0, "boot", None)
        self.assertEqual(set(first["diskstats"]), {"nvme0n1", "dm-0", "md0"})
        disk = first["diskstats"]["nvme0n1"]
        self.assertEqual(disk["device"], "259:0")
        self.assertEqual(disk["diskseq"], 42)
        self.assertEqual(disk["counters"], {"reads": 10, "read_sectors": 30, "read_ms": 40,
                         "writes": 50, "write_sectors": 70, "write_ms": 80, "io_ms": 100, "weighted_io_ms": 110})
        self.assertEqual(disk["in_flight"], 9)
        write(disks, "259 0 nvme0n1 20 2 50 60 40 6 90 100 0 120 130\n")
        second = mt.fast_sample(sources, 0.9, {}, 110.0, "boot", first)
        self.assertEqual(second["diskstats"]["nvme0n1"]["per_s"]["read_sectors"], 2.0)
        self.assertNotIn("writes", second["diskstats"]["nvme0n1"]["per_s"])
        self.assertNotIn("in_flight", second["diskstats"]["nvme0n1"]["per_s"])
        write(self.fixture.sys / "class/block/nvme0n1/diskseq", "43\n")
        replaced = mt.fast_sample(sources, 0.9, {}, 120.0, "boot", second)
        self.assertNotIn("per_s", replaced["diskstats"]["nvme0n1"])
        disks.unlink()
        missing = mt.fast_sample(sources, 0.9, {}, 130.0, "boot", replaced)
        self.assertIsNone(missing["diskstats"])
        write(disks, "259 0 nvme0n1 30 0 60 70 50 0 100 110 0 130 140\n")
        resumed = mt.fast_sample(sources, 0.9, {}, 140.0, "boot", missing)
        self.assertNotIn("per_s", resumed["diskstats"]["nvme0n1"])

    def test_cpu_observations_use_some_pressure_and_reset_aware_time_deltas(self) -> None:
        write(self.fixture.proc / "pressure/cpu", psi(1_000_000, 0))
        write(self.fixture.proc / "stat", "cpu 100 20 30 400 50 6 7 8 9 10\ncpu0 1 2 3 4\n")
        sources = self.fixture.sources()
        first = mt.fast_sample(sources, 0.9, {}, 100.0, "boot", None)
        self.assertEqual(first["cpu"]["time_ticks"], {"user": 100, "nice": 20, "system": 30, "idle": 400,
                         "iowait": 50, "irq": 6, "softirq": 7, "steal": 8, "guest": 9, "guest_nice": 10})
        self.assertEqual(list(first["t2"]["cpu"]), ["some"])
        write(self.fixture.proc / "stat", "cpu 130 20 40 500 40\n")
        write(self.fixture.proc / "pressure/cpu", psi(3_000_000, 0))
        second = mt.fast_sample(sources, 0.9, {}, 110.0, "boot", first)
        self.assertEqual(second["cpu"]["per_s"], {"user": 3.0, "nice": 0.0, "system": 1.0, "idle": 10.0})
        self.assertEqual(second["t2"]["cpu"]["stall_fraction"], {"some": 0.2})
        (self.fixture.proc / "stat").unlink()
        (self.fixture.proc / "pressure/cpu").unlink()
        missing = mt.fast_sample(sources, 0.9, {}, 120.0, "boot", second)
        self.assertEqual(missing["cpu"], {"time_ticks": {}, "per_s": {}})
        self.assertIsNone(missing["t2"]["cpu"])
        write(self.fixture.proc / "stat", "cpu 160\n")
        resumed = mt.fast_sample(sources, 0.9, {}, 130.0, "boot", missing)
        self.assertEqual(resumed["cpu"]["per_s"], {})
        rebooted = mt.fast_sample(sources, 0.9, {}, 140.0, "other-boot", resumed)
        self.assertNotIn("per_s", rebooted["cpu"])
        unknown = mt.fast_sample(sources, 0.9, {}, 150.0, None, None)
        self.assertNotIn("per_s", mt.fast_sample(sources, 0.9, {}, 160.0, None, unknown)["cpu"])

    def test_capacity_keeps_meminfo_and_each_swap_area_separate(self) -> None:
        capacity = {"MemFree": 101, "Cached": 102, "SwapCached": 103, "SReclaimable": 104,
                    "SUnreclaim": 105, "Unevictable": 106, "Mlocked": 107, "Committed_AS": 108,
                    "CommitLimit": 109, "AnonHugePages": 110}
        self.fixture.meminfo(**capacity)
        write(self.fixture.proc / "swaps", "Filename Type Size Used Priority\n"
              "/dev/dm-0 partition 16384 1234 10\n/var/swap\\040file file 32768 2345 -2\nmalformed\n")
        sources = self.fixture.sources()
        sample = mt.fast_sample(sources, 0.9, {}, 100.0, "boot", None)
        self.assertEqual(sample["capacity_kib"], capacity)
        self.assertEqual(sample["swap_areas"], [
            {"path": "/dev/dm-0", "type": "partition", "size_kib": 16384, "used_kib": 1234, "priority": 10},
            {"path": "/var/swap\\040file", "type": "file", "size_kib": 32768, "used_kib": 2345, "priority": -2},
        ])
        (self.fixture.proc / "swaps").unlink()
        self.fixture.meminfo()
        missing = mt.fast_sample(sources, 0.9, {}, 110.0, "boot", sample)
        self.assertEqual(missing["capacity_kib"], {})
        self.assertIsNone(missing["swap_areas"])
        write(self.fixture.proc / "swaps", "Filename Type Size Used Priority\n")
        self.assertEqual(mt.fast_sample(sources, 0.9, {}, 120.0, "boot", missing)["swap_areas"], [])

    def test_reclaim_compaction_and_thp_counters_keep_individual_stalls(self) -> None:
        counters = {
            "workingset_refault_file": 100, "workingset_activate_anon": 2, "workingset_activate_file": 3,
            "workingset_restore_anon": 4, "workingset_restore_file": 5,
            "pgscan_anon": 6, "pgscan_file": 7, "pgsteal_anon": 8, "pgsteal_file": 9,
            "pgscan_kswapd": 10, "pgscan_direct": 11, "pgsteal_kswapd": 12, "pgsteal_direct": 13,
            "kswapd_low_wmark_hit_quickly": 14, "kswapd_high_wmark_hit_quickly": 15,
            "swap_ra": 16, "swap_ra_hit": 17, "swpin_zero": 18, "swpout_zero": 19,
            "compact_stall": 20, "compact_fail": 21, "compact_success": 22,
            "compact_migrate_scanned": 23, "compact_free_scanned": 24,
            "thp_fault_alloc": 25, "thp_fault_fallback": 26, "thp_fault_fallback_charge": 27,
            "thp_collapse_alloc": 28, "thp_collapse_alloc_failed": 29, "thp_split_page": 30,
            "thp_split_page_failed": 31, "thp_deferred_split_page": 32, "thp_split_pmd": 33,
            "thp_swpout": 34, "thp_swpout_fallback": 35, "allocstall_device": 36,
        }
        self.fixture.vmstat(**counters)
        sources = self.fixture.sources()
        first = mt.fast_sample(sources, 0.9, {}, 100.0, "boot", None)
        self.assertEqual(first["schema"], "memory-telemetry/v1")
        self.assertEqual(first["schema_revision"], 2)
        self.assertEqual({key: first["t3"]["counters"][key] for key in counters}, counters)
        self.assertEqual(first["t3"]["counters"]["allocstall_normal"], 1)
        self.assertEqual(first["t3"]["counters"]["allocstall"], 39)
        self.fixture.vmstat(workingset_refault_file=130, compact_stall=10)
        second = mt.fast_sample(sources, 0.9, {}, 115.0, "boot", first)
        self.assertEqual(second["t3"]["per_s"]["workingset_refault_file"], 2.0)
        self.assertNotIn("compact_stall", second["t3"]["per_s"])
        self.assertNotIn("thp_fault_alloc", second["t3"]["counters"])

    def test_fast_sample_records_the_shared_counters(self) -> None:
        sources = self.fixture.sources()
        sample = mt.fast_sample(sources, 0.9, {"app-com.anthropic.Claude-100.scope": self.fixture.claude},
                                1_000.0, "boot", None)
        self.assertEqual(sample["kind"], "fast")
        self.assertNotIn("unavailable", sample)
        line = round(0.1 * 100 * GIB_KIB)
        self.assertEqual(sample["t1"], {"mem_total_kib": 100 * GIB_KIB, "mem_available_kib": 30 * GIB_KIB,
                                        "oomd_line_kib": line, "headroom_kib": 30 * GIB_KIB - line})
        self.assertEqual(sample["t2"]["memory"]["full"]["total_us"], 4_000_000)
        self.assertEqual(list(sample["t2"]["cgroups"]),
                         [f"user-{UID}.slice", "app.slice", "builds.slice", "app-com.anthropic.Claude-100.scope"])
        self.assertEqual(sample["t2"]["cgroups"]["builds.slice"]["full"]["total_us"], 500_000)
        self.assertEqual(sample["t3"]["counters"]["allocstall"], 3)
        self.assertNotIn("nr_free_pages", sample["t3"]["counters"])
        t4 = sample["t4"]
        self.assertTrue(t4["oomd_swap_gate_armed"])
        self.assertEqual(t4["swap_used_kib"], 39 * GIB_KIB)
        self.assertEqual(t4["disk_resident_upper_kib"], 9 * GIB_KIB)
        t8 = sample["t8"]
        self.assertEqual(t8["gtt_used_bytes"], 7 << 30)
        self.assertEqual([device["card"] for device in t8["devices"]], ["card0"])
        self.assertEqual(t8["gpu_active_kib"], 2 * GIB_KIB)

    def test_shared_counters_take_their_documented_forms_when_sources_are_missing(self) -> None:
        # docs/MEMORY_TELEMETRY.md, "When a source cannot be read", promises #403 exactly these forms.
        sources = self.fixture.sources()
        (self.fixture.root / "sys/devices/pci0000:00/0000:c5:00.0/mem_info_gtt_used").unlink()
        (self.fixture.builds / "memory.pressure").unlink()
        sample = mt.fast_sample(sources, 0.9, {}, 100.0, "boot", None)
        self.assertNotIn("unavailable", sample)  # optional sources are never listed
        self.assertIsNone(sample["t8"]["gtt_used_bytes"])
        self.assertNotIn("gtt_used_bytes", sample["t8"]["devices"][0])
        self.assertNotIn("builds.slice", sample["t2"]["cgroups"])

        previous = sample
        for name in ("meminfo", "vmstat", "pressure/memory", "pressure/io"):
            (self.fixture.proc / name).unlink()
        (self.fixture.user / "memory.pressure").unlink()
        (self.fixture.apps / "memory.pressure").unlink()
        shutil.rmtree(self.fixture.sys / "class/drm")
        sample = mt.fast_sample(sources, 0.9, {}, 110.0, "boot", previous)
        self.assertIsNone(sample["t1"])
        self.assertEqual(sample["t2"], {"memory": None, "io": None, "cpu": None, "cgroups": {}})
        self.assertEqual(sample["t3"], {"counters": {}, "per_s": {}})
        self.assertIsNone(sample["t4"])
        self.assertEqual(sample["t8"], {"gtt_used_bytes": None, "gpu_active_kib": None, "gpu_reclaim_kib": None,
                                        "devices": []})
        user = f"sys:fs/cgroup/user.slice/user-{UID}.slice"
        self.assertEqual(sample["unavailable"], {
            "proc:meminfo": "FileNotFoundError",
            "proc:pressure/io": "FileNotFoundError",
            "proc:pressure/memory": "FileNotFoundError",
            "proc:vmstat": "FileNotFoundError",
            "sys:class/drm": "FileNotFoundError",
            f"{user}/memory.pressure": "FileNotFoundError",
            f"{user}/user@{UID}.service/app.slice/memory.pressure": "FileNotFoundError",
        })

    def test_gate_follows_oomds_limit_and_absent_swap(self) -> None:
        sources = self.fixture.sources()
        self.fixture.meminfo(SwapFree=5 * GIB_KIB)  # 87.5% used
        self.assertFalse(mt.fast_sample(sources, 0.9, {}, 1.0, None, None)["t4"]["oomd_swap_gate_armed"])
        self.assertTrue(mt.fast_sample(sources, 0.8, {}, 1.0, None, None)["t4"]["oomd_swap_gate_armed"])
        self.fixture.meminfo(SwapTotal=0, SwapFree=0)
        t4 = mt.fast_sample(sources, 0.9, {}, 1.0, None, None)["t4"]
        self.assertFalse(t4["oomd_swap_gate_armed"])
        self.assertIsNone(t4["swap_used_fraction"])

    def test_rates_use_deltas_and_skip_resets_and_reboots(self) -> None:
        sources = self.fixture.sources()
        first = mt.fast_sample(sources, 0.9, {}, 100.0, "boot", None)
        self.fixture.vmstat(zswpin=330, pswpin=5)  # pswpin went down: a reset
        write(self.fixture.proc / "pressure/memory", psi(12_000_000, 4_500_000))
        second = mt.fast_sample(sources, 0.9, {}, 110.0, "boot", first)
        self.assertEqual(second["interval_s"], 10.0)
        self.assertEqual(second["t3"]["per_s"]["zswpin"], 3.0)
        self.assertNotIn("pswpin", second["t3"]["per_s"])
        self.assertEqual(second["t2"]["memory"]["stall_fraction"], {"some": 0.2, "full": 0.05})
        rebooted = mt.fast_sample(sources, 0.9, {}, 120.0, "other-boot", second)
        self.assertNotIn("per_s", rebooted["t3"])

    def test_slow_sample_attributes_processes_and_mirrors_oomds_choice(self) -> None:
        sources = self.fixture.sources()
        sample, watched, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH),
                                            ["system.slice", f"user.slice/user-{UID}.slice"], 50.0, "boot", None)
        self.assertNotIn("unavailable", sample)
        self.assertEqual(sorted(watched), ["app-com.anthropic.Claude-100.scope",
                                           "app-org.chromium.Chromium-200.scope", "indexer.service"])
        holders = sample["swap_holders"]
        # 40 GiB of swap: oomd ranks cgroups above 2 GiB and picks the largest.
        self.assertEqual(holders["candidates"], 3)
        self.assertTrue(holders["swap_mode_choice"].endswith("background.slice/indexer.service"))
        self.assertEqual(holders["top_by_swap"][2]["cgroup"], "system.slice/inference.service")
        self.assertFalse(any(name.startswith("inference") for name in sample["t9"]))

        claude = sample["t9"]["app-com.anthropic.Claude-100.scope"]
        self.assertEqual(claude["processes"], len(CLAUDE_PROCESSES))
        self.assertEqual(claude["app_exe"], "claude")
        roles = {(entry["exe"], entry["role"]): entry["processes"] for entry in claude["classes"]}
        self.assertEqual(roles, {
            ("claude", "app"): 2, ("claude", "agent"): 1, ("node", "agent-child"): 2,
            ("zsh", "agent-shell"): 1, ("codex", "nested-agent"): 1, ("zsh", "detached"): 1,
            ("(unreadable)", "app-child"): 1,
        })
        trees = {entry["tree"]: entry["processes"] for entry in claude["trees"]}
        # A Claude Code session is one tree; a codex agent's direct children each start their own.
        self.assertEqual(trees, {"claude[110]": 3, "codex[113]": 1, "codex[113]/node[114]": 1, "(no agent)": 4})
        self.assertEqual(claude["totals"]["swap_kib"], sum(item[3] for item in CLAUDE_PROCESSES.values()))

        block = sample["cgroups"]["app-com.anthropic.Claude-100.scope"]
        self.assertEqual(block["processes"], len(CLAUDE_PROCESSES))
        self.assertEqual(block["pids"], {"threads": 42, "threads_peak": 50, "threads_max": 152824, "max_events": 0})
        self.assertEqual(block["memory_swap_events"]["fail"], 1234)
        self.assertEqual(block["memory_events_local"]["high"], 4)
        self.assertNotIn("sock_throttled", block["memory_events_local"])
        self.assertEqual(sample["cgroups"][f"user-{UID}.slice"]["pids"]["threads_max"], "max")

    def test_removed_cgroups_keep_their_last_counters(self) -> None:
        sources = self.fixture.sources()
        roots = [f"user.slice/user-{UID}.slice"]
        first, _, paths = mt.slow_sample(sources, list(mt.DEFAULT_WATCH), roots, 50.0, "boot", None)
        shutil.rmtree(self.fixture.chromium)
        second, watched, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH), roots, 110.0, "boot", first, paths)
        self.assertNotIn("app-org.chromium.Chromium-200.scope", watched)
        removed = second["removed"]["app-org.chromium.Chromium-200.scope"]
        self.assertEqual(removed["last_seen"], 50.0)
        self.assertEqual(removed["memory_swap_events"]["fail"], 1234)

    def test_missing_and_unreadable_sources_are_listed_not_fatal(self) -> None:
        sources = self.fixture.sources()
        shutil.rmtree(self.fixture.proc / "pressure")
        shutil.rmtree(self.fixture.sys / "class/drm")
        (self.fixture.proc / "vmstat").unlink()
        (self.fixture.proc / "vmstat").mkdir()  # unreadable even for root
        (self.fixture.user / "memory.pressure").unlink()
        sample = mt.fast_sample(sources, 0.9, {"gone.scope": self.fixture.apps / "gone.scope"}, 1.0, None, None)
        self.assertIsNone(sample["t2"]["memory"])
        self.assertIsNone(sample["t2"]["io"])
        self.assertEqual(sample["t3"]["counters"], {})
        self.assertEqual(sample["t8"]["devices"], [])
        self.assertIsNotNone(sample["t1"])
        unavailable = sample["unavailable"]
        self.assertEqual(unavailable["proc:pressure/memory"], "FileNotFoundError")
        self.assertEqual(unavailable["proc:vmstat"], "IsADirectoryError")
        self.assertEqual(unavailable["sys:class/drm"], "FileNotFoundError")
        self.assertIn(f"sys:fs/cgroup/user.slice/user-{UID}.slice/memory.pressure", unavailable)
        self.assertNotIn("gone.scope", json.dumps(unavailable))

        (self.fixture.proc / "meminfo").unlink()
        shutil.rmtree(self.fixture.cgroup / "system.slice")
        slow, _, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH), ["system.slice"], 2.0, None, None)
        self.assertEqual(slow["unavailable"]["proc:meminfo"], "FileNotFoundError")
        self.assertEqual(slow["unavailable"]["sys:fs/cgroup/system.slice"], "FileNotFoundError")
        self.assertEqual(slow["swap_holders"]["candidates"], 0)
        # A process that exits between the listing and its status read is skipped.
        shutil.rmtree(self.fixture.proc / "111")
        self.assertEqual(slow["t9"]["app-com.anthropic.Claude-100.scope"]["processes"], len(CLAUDE_PROCESSES))
        slow, _, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH), [], 3.0, None, None)
        self.assertEqual(slow["t9"]["app-com.anthropic.Claude-100.scope"]["processes"], len(CLAUDE_PROCESSES) - 1)

    def test_native_claude_code_counts_as_an_agent(self) -> None:
        native = "/var/lib/fixture/.local/share/claude/versions/2.1.292"
        self.fixture.process(115, native, 112, 70_000, 0)  # started from claude[110]'s shell
        self.fixture.process(116, "/usr/bin/node", 115, 30_000, 0)
        self.fixture.process(202, native, 200, 40_000, 0)  # started by the ChatGPT app itself
        write(self.fixture.claude / "cgroup.procs", "".join(f"{pid}\n" for pid in [*CLAUDE_PROCESSES, 115, 116]))
        write(self.fixture.chromium / "cgroup.procs", "200\n201\n202\n")
        sample, _, _ = mt.slow_sample(self.fixture.sources(), list(mt.DEFAULT_WATCH), [], 1.0, None, None)
        claude = sample["t9"]["app-com.anthropic.Claude-100.scope"]
        roles = {(entry["exe"], entry["role"]): entry["processes"] for entry in claude["classes"]}
        self.assertEqual(roles[("claude", "nested-agent")], 1)
        self.assertEqual(roles[("node", "agent-child")], 3)
        trees = {entry["tree"]: entry["processes"] for entry in claude["trees"]}
        self.assertEqual(trees["claude[115]"], 2)
        chatgpt = sample["t9"]["app-org.chromium.Chromium-200.scope"]
        self.assertIn(("claude", "agent"), {(entry["exe"], entry["role"]) for entry in chatgpt["classes"]})
        self.assertNotIn("2.1.292", json.dumps(sample))

    def test_removed_means_gone_and_parent_events_include_children(self) -> None:
        sources = self.fixture.sources()
        roots = [f"user.slice/user-{UID}.slice"]
        write(self.fixture.user / "memory.events", "low 0\nhigh 9\nmax 0\noom 1\noom_kill 2\noom_group_kill 0\n")
        first, watched, paths = mt.slow_sample(sources, list(mt.DEFAULT_WATCH), roots, 50.0, "boot", None)
        self.assertIn("indexer.service", watched)
        user = first["cgroups"][f"user-{UID}.slice"]
        self.assertEqual((user["memory_events"]["oom_kill"], user["memory_events_local"]["oom_kill"]), (2, 0))
        write(self.fixture.indexer / "memory.swap.current", f"{1 << 30}\n")  # below oomd's 5% floor
        second, watched, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH), roots, 110.0, "boot", first, paths)
        self.assertNotIn("indexer.service", watched)
        self.assertNotIn("removed", second)

    @unittest.skipUnless(sys.platform == "linux", "creates directories with control characters in their names")
    def test_removal_is_decided_on_real_paths_not_recorded_names(self) -> None:
        sources = self.fixture.sources()
        roots = [f"user.slice/user-{UID}.slice"]
        # 218 bytes as a directory name, over 800 once escaped: too long for any lookup.
        long_name = "app-chatgpt@" + "\x01" * 200 + ".scope"
        self.fixture.cgroup_files(self.fixture.apps / long_name, 1 << 30, 0)
        # An oomd swap candidate whose recorded name names no directory.
        odd = self.fixture.indexer.parent / "odd\x02.service"
        self.fixture.cgroup_files(odd, 1 << 30, 4 << 30)
        first, _, paths = mt.slow_sample(sources, list(mt.DEFAULT_WATCH), roots, 50.0, "boot", None)
        escaped = mt.clean_text(long_name)
        self.assertEqual({escaped, "odd\\x02.service"} - set(first["cgroups"]), set())
        shutil.rmtree(self.fixture.apps / long_name)
        write(odd / "memory.swap.current", "0\n")  # below oomd's floor: no longer watched, but still there
        second, _, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH), roots, 110.0, "boot", first, paths)
        self.assertEqual(list(second["removed"]), [escaped])
        self.assertEqual(second["removed"][escaped]["last_seen"], 50.0)
        # Without the real paths the recorded ones are tried, and one too long to look up does not raise.
        third, _, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH), roots, 120.0, "boot", first)
        self.assertIn(escaped, third["removed"])

    def test_names_chosen_by_processes_are_recorded_safely(self) -> None:
        self.fixture.process(140, "/usr/bin/evil\x1b]0;TITLE\x07name", 110, 9_000_000, 0)
        write(self.fixture.claude / "cgroup.procs", "".join(f"{pid}\n" for pid in [*CLAUDE_PROCESSES, 140]))
        sample, _, _ = mt.slow_sample(self.fixture.sources(), list(mt.DEFAULT_WATCH), [], 1.0, None, None)
        top = sample["t9"]["app-com.anthropic.Claude-100.scope"]["classes"][0]
        self.assertEqual(top["exe"], "evil\\x1b]0;TITLE\\x07name")
        self.assertEqual(mt.clean_text("a\udcffb\nc\x9b"), "a\\udcffb\\x0ac\\x9b")

    def test_fields_forged_in_a_task_name_are_not_read(self) -> None:
        # The kernel escapes only "\n" and "\\" in a task name, so other line breaks and digits reach the status.
        forged = "x\rRssAnon:\t\u00b2 kB\x1cVmSwap: \u00b9\u2028PPid:\t1\x85RssAnon:\t999999999 kB"
        self.fixture.process(140, "/usr/bin/forged", 110, 7_000, 3_000, name=forged)
        self.fixture.process(141, "/usr/bin/garbled", 110, 5_000, 0)
        write(self.fixture.proc / "141/status", "Name:\tgarbled\nPPid:\t\u00b9\nRssAnon:\t5000 kB\n")
        write(self.fixture.claude / "cgroup.procs", "".join(f"{pid}\n" for pid in [*CLAUDE_PROCESSES, 140, 141]))
        sources = self.fixture.sources()
        processes = {process.pid: process for process in mt.cgroup_processes(sources, self.fixture.claude) or []}
        self.assertEqual((processes[140].ppid, processes[140].rss_anon, processes[140].swap), (110, 7_000, 3_000))
        self.assertNotIn(141, processes)  # a status that does not parse is skipped, not fatal
        sample, _, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH), [], 1.0, None, None)
        self.assertEqual(sample["t9"]["app-com.anthropic.Claude-100.scope"]["processes"], len(CLAUDE_PROCESSES) + 1)

    def test_a_codex_agent_splits_into_a_tree_per_direct_child(self) -> None:
        # A Codex app-server (201) under the ChatGPT app (200), with tool and MCP server children.
        children = {
            210: ("/usr/bin/node", 201, 50_000), 211: ("/usr/bin/node", 210, 900_000),
            220: ("/usr/bin/node", 201, 40_000), 230: ("/usr/bin/python3.14", 201, 30_000),
            240: ("/opt/codex/bin/codex", 201, 20_000), 241: ("/usr/bin/zsh", 240, 1_000),
        }
        for pid, (exe, ppid, anon) in children.items():
            self.fixture.process(pid, exe, ppid, anon, 0)
        write(self.fixture.chromium / "cgroup.procs", "".join(f"{pid}\n" for pid in [200, 201, *children]))
        sources = self.fixture.sources()
        first, _, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH), [], 60.0, "boot", None)
        self.fixture.status(211, 210, 1_400_000, 0)  # one MCP server grows
        second, _, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH), [], 120.0, "boot", first)
        scope = "app-org.chromium.Chromium-200.scope"
        trees = {entry["tree"]: entry["processes"] for entry in second["t9"][scope]["trees"]}
        self.assertEqual(trees, {
            "(no agent)": 1, "codex[201]": 1, "codex[201]/node[210]": 2, "codex[201]/node[220]": 1,
            "codex[201]/python3.14[230]": 1, "codex[240]": 1, "codex[240]/zsh[241]": 1,
        })
        claude = {entry["tree"] for entry in second["t9"]["app-com.anthropic.Claude-100.scope"]["trees"]}
        self.assertIn("claude[110]", claude)
        self.assertFalse(any(tree.startswith("claude[110]/") for tree in claude))
        grown = [item for item in mt.t9_growth([first, second])["growth"] if item["section"] == "trees"]
        self.assertEqual((grown[0]["tree"], grown[0]["growth_kib"]), ("codex[201]/node[210]", 500_000))

    def test_ranked_folds_the_tail(self) -> None:
        processes = [mt.Process(pid, 0, f"tool{pid}", f"/bin/tool{pid}", pid, 0, 0, 0)
                     for pid in range(1, mt.TOP_ENTRIES + 6)]
        result = mt.attribute(processes)
        self.assertEqual(len(result["classes"]), mt.TOP_ENTRIES + 1)
        rest = result["classes"][-1]
        self.assertEqual((rest["exe"], rest["groups"], rest["processes"]), ("(rest)", 5, 5))
        self.assertEqual(result["classes"][0]["exe"], f"tool{mt.TOP_ENTRIES + 5}")


class ScheduleTests(unittest.TestCase):
    def test_a_late_tick_skips_the_slots_it_missed_and_leaves_room_before_the_next(self) -> None:
        due = mt.next_tick_time
        self.assertEqual(due(100.0, 10.0, 100.002), 110.0)  # on time: the cadence holds
        self.assertEqual(due(100.0, 10.0, 104.0), 110.0)  # a slow tick that still finishes within its slot
        self.assertAlmostEqual(due(110.0, 10.0, 125.0), 130.0)  # a stall past two slots skips them
        self.assertAlmostEqual(due(110.0, 10.0, 119.99), 124.99)  # even one that ends just before the next slot


class CollectorTests(FixtureCase):
    def test_policy_snapshots_record_start_each_utc_day_and_graceful_end(self) -> None:
        write(self.fixture.proc / "sys/kernel/osrelease", "fixture-kernel\n")
        write(self.fixture.proc / "sys/vm/swappiness", "100\n")
        write(self.fixture.sys / "module/zswap/parameters/enabled", "Y\n")
        write(self.fixture.sys / "kernel/mm/lru_gen/min_ttl_ms", "100\n")
        write(self.fixture.sys / "kernel/mm/transparent_hugepage/enabled", "always [madvise] never\n")
        start = 1_791_590_400.0  # a UTC midnight
        with mock.patch.object(mt.time, "time", return_value=start):
            collector = self.collector()
            collector.tick(0.0)
        with mock.patch.object(mt.time, "time", return_value=start + 10):
            collector.tick(0.0)
        write(self.fixture.proc / "sys/vm/swappiness", "101\n")
        with mock.patch.object(mt.time, "time", return_value=start + 86400):
            collector.tick(0.0)
        with mock.patch.object(mt.time, "time", return_value=start + 86410):
            collector.close()
        records = mt.read_samples(self.state / "samples", start, start + 90000)
        snapshots = [record for record in records if record["kind"] == "metadata"]
        self.assertEqual([record["reason"] for record in snapshots], ["start", "daily", "end"])
        first = snapshots[0]
        self.assertEqual(first["schema_revision"], 2)
        self.assertEqual(first["kernel"], "fixture-kernel")
        self.assertEqual(first["boot"], "0123abcd00004000800000000000beef")
        self.assertEqual(first["recorder_sha256"], hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
        self.assertEqual(first["vm"]["swappiness"], "100")
        self.assertEqual(snapshots[1]["vm"]["swappiness"], "101")
        self.assertEqual(first["zswap"]["enabled"], "Y")
        self.assertEqual(first["mglru"]["min_ttl_ms"], "100")
        self.assertEqual(first["thp"]["enabled"], "always [madvise] never")
        self.assertIsNone(first["vm"]["overcommit_memory"])
        self.assertEqual(first["oomd"]["effective"]["global"]["Swap Used Limit"], "90.00%")
        self.assertEqual(first["oomd"]["effective"]["pressure_monitored"]["/system.slice"],
                         {"Memory Pressure Limit": "80.00%", "Memory Pressure Duration": "30s"})
        self.assertNotIn("UNRELATED-SENTINEL", json.dumps(snapshots))
        self.assertIn("proc:sys/vm/overcommit_memory", first["unavailable"])
        self.assertGreaterEqual(first["oomd"]["effective"]["cpu_s"], 0)
        fast = [record for record in records if record["kind"] == "fast"]
        self.assertGreaterEqual(fast[0]["collector"]["oomctl_cpu_s"], 0)

    def collector(self, *extra: str):
        options = mt.parse_arguments(["run", "--state-dir", str(self.state), *self.fixture.options(), *extra])
        journal = mt.Journal(str(self.base / "no-journalctl"), self.state / "journal.cursor")  # never started
        collector = mt.Collector(options, mt.make_sources(options), self.state, journal)
        self.addCleanup(collector.store.close)
        return collector

    def test_a_slow_scan_does_not_skew_the_rates_of_the_fast_samples(self) -> None:
        # The fixture's memory PSI totals and pswpout grow with the clock, by 1 s of stall and 1,000 pages per
        # second, so every stall fraction is 1 and every pswpout rate 1,000. The clock moves on by a whole 1 s
        # interval between ticks and by 0.6 s during each slow scan, as a long scan under memory pressure would.
        start = 1_791_000_000.0
        clock = [start]
        proc = self.fixture.proc
        read = mt.Sources.text

        def text(sources, path: Path, required: bool = False) -> str | None:
            if path == proc / "pressure/memory":
                return psi(round(clock[0] * 1e6), round(clock[0] * 1e6))
            if path == proc / "vmstat":
                return f"pswpin 10\npswpout {round(clock[0] * 1000)}\n"
            return read(sources, path, required)

        scan = mt.slow_sample

        def slow_scan(*args, **kwargs):
            result = scan(*args, **kwargs)
            clock[0] += 0.6
            return result

        with (mock.patch.object(mt.Sources, "text", text), mock.patch.object(mt, "slow_sample", slow_scan),
              mock.patch.object(mt.time, "time", lambda: clock[0])):
            collector = self.collector("--interval", "1", "--slow-every", "3")
            for tick in range(7):
                clock[0] = start + tick
                collector.tick(0.0)
        fast = [sample for sample in mt.read_samples(self.state / "samples", start, start + 60)
                if sample["kind"] == "fast" and "interval_s" in sample]
        self.assertEqual(len(fast), 6)
        for sample in fast:
            stalled = sample["t2"]["memory"]["stall_fraction"]
            self.assertAlmostEqual(stalled["some"], 1.0, places=3, msg=sample["t"] - start)
            self.assertAlmostEqual(stalled["full"], 1.0, places=3, msg=sample["t"] - start)
            self.assertAlmostEqual(sample["t3"]["per_s"]["pswpout"], 1000.0, delta=1.0, msg=sample["t"] - start)

    def test_an_entry_is_marked_handled_only_once_its_record_change_is_written(self) -> None:
        collector = self.collector()
        journal, incidents = collector.journal, self.state / "incidents"
        collector.tick(0.0)
        entries = [entry | {"__CURSOR": f"s=e{index}"}
                   for index, entry in enumerate(oomd_kill_entries(time.time(), "a.scope"))]

        def written() -> list[int]:
            return [len(mt.load_json(path)["events"]) for path in sorted(incidents.glob("*.json"))]

        collector.handle(entries[0])  # opens a record, written at once
        self.assertEqual((journal.handled, written()), ("s=e0", [1]))
        collector.handle(entries[1])
        collector.handle(entries[2])  # both join the record in memory
        journal.save_cursor()
        self.assertEqual((journal.handled, written()), ("s=e0", [1]))
        self.assertEqual((self.state / "journal.cursor").read_text().strip(), "s=e0")
        collector.tick(0.0)  # writes the record once, then marks the entries the write covers and saves
        self.assertEqual((journal.handled, written()), ("s=e2", [3]))
        self.assertEqual((self.state / "journal.cursor").read_text().strip(), "s=e2")
        if os.geteuid() == 0:
            return  # permission bits do not bind root
        collector.handle(entries[3])
        incidents.chmod(0o500)  # the next write of the record fails
        self.addCleanup(incidents.chmod, 0o700)
        with self.assertRaises(PermissionError):
            collector.tick(0.0)
        self.assertEqual((journal.handled, written()), ("s=e2", [3]))

    def test_an_entry_whose_record_the_cap_deleted_does_not_hold_the_saved_position_back(self) -> None:
        collector = self.collector("--max-incidents", "1")
        journal, incidents = collector.journal, self.state / "incidents"
        t0 = time.time() - 600
        kill = "x.scope: A process of this unit has been killed by the OOM killer."

        def stored() -> list[tuple[float, int]]:
            records = [json.loads(path.read_text()) for path in sorted(incidents.glob("*.json"))]
            return [(round(record["opened"] - t0, 3), len(record["events"])) for record in records]

        collector.handle(journal_entry(t0, kill, MESSAGE_ID=mt.MESSAGE_UNIT_OOM, **SYSTEM_MANAGER)
                         | {"__CURSOR": "s=e0"})
        collector.tick(0.0)  # the record's grace period has passed, so this finalizes it
        collector.handle(journal_entry(t0 + 1, "a late detail", _SYSTEMD_UNIT="systemd-oomd.service")
                         | {"__CURSOR": "s=e1"})  # joins the finalized record in memory
        self.assertTrue(collector.incidents.unwritten)
        self.assertEqual((journal.handled, stored()), ("s=e0", [(0.0, 1)]))
        # The next kill's record is the one the cap keeps. The older record is deleted with the event that was
        # waiting to be written, so nothing is left to write and the position moves past both entries.
        collector.handle(journal_entry(t0 + 240, kill, MESSAGE_ID=mt.MESSAGE_UNIT_OOM, **SYSTEM_MANAGER)
                         | {"__CURSOR": "s=e2"})
        self.assertFalse(collector.incidents.unwritten)
        self.assertEqual((journal.handled, stored()), ("s=e2", [(240.0, 1)]))
        collector.tick(0.0)
        self.assertEqual((self.state / "journal.cursor").read_text().strip(), "s=e2")
        self.assertEqual(stored(), [(240.0, 1)])  # and the tick's write did not bring the deleted record back


def fast_record(t: float, available: int = 30) -> dict:
    return {"schema": mt.SCHEMA, "kind": "fast", "t": t, "t1": {"mem_available_kib": available}}


def slow_record(t: float, node_kib: int) -> dict:
    return {"schema": mt.SCHEMA, "kind": "slow", "t": t, "t9": {"app.scope": {
        "classes": [{"exe": "node", "role": "agent-child", "rss_anon_kib": node_kib, "swap_kib": 0}],
        "trees": [{"tree": "claude[7]", "rss_anon_kib": node_kib, "swap_kib": 0},
                  {"tree": "(rest)", "rss_anon_kib": 99, "swap_kib": 0}],
    }}}


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / "samples"
        self.hour = 1_791_000_000 - 1_791_000_000 % 3600

    def test_segments_rotate_compress_and_read_back_in_order(self) -> None:
        store = mt.SampleStore(self.directory, 86400, 1 << 30)
        times = (self.hour + 10, self.hour + 3500, self.hour + 3610, self.hour + 3620)
        for t in times:
            store.append(fast_record(t))
        store.close()
        self.assertEqual(store.bytes_written,
                         sum(len(json.dumps(fast_record(t), separators=(",", ":"))) + 1 for t in times))
        names = sorted(path.name for path in self.directory.iterdir())
        first, second = (mt.datetime.fromtimestamp(t, mt.timezone.utc).strftime(mt.SEGMENT_FORMAT)
                         for t in (self.hour, self.hour + 3600))
        self.assertEqual(names, [f"{first}.jsonl.gz", f"{second}.jsonl"])
        records = mt.read_samples(self.directory, self.hour + 3000, self.hour + 3615)
        self.assertEqual([record["t"] for record in records], [self.hour + 3500, self.hour + 3610])

    def test_reopened_segment_survives_a_cut_line(self) -> None:
        store = mt.SampleStore(self.directory, 86400, 1 << 30)
        store.append(fast_record(self.hour + 1))
        store.handle.write('{"kind":"fast","t":')  # a crash mid-write
        store.close()
        store = mt.SampleStore(self.directory, 86400, 1 << 30)
        store.append(fast_record(self.hour + 2))
        store.close()
        records = mt.read_samples(self.directory, self.hour, self.hour + 3600)
        self.assertEqual([record["t"] for record in records], [self.hour + 1, self.hour + 2])

    def test_retention_bounds_age_and_size_but_keeps_the_open_segment(self) -> None:
        self.directory.mkdir()
        for days_old in range(40, 0, -1):
            stamp = mt.datetime.fromtimestamp(self.hour - days_old * 86400, mt.timezone.utc).strftime(mt.SEGMENT_FORMAT)
            with gzip.open(self.directory / f"{stamp}.jsonl.gz", "wb") as handle:
                handle.write(os.urandom(4096))  # incompressible, so each segment is about 4 KiB
        store = mt.SampleStore(self.directory, 30 * 86400, 1 << 30)
        store.append(fast_record(self.hour))
        ages = sorted(self.hour - (mt.segment_start(path.name) or 0) for path in self.directory.iterdir())
        self.assertEqual(len(ages), 31)
        self.assertLessEqual(max(ages), 30 * 86400)
        store.max_bytes = 10 * 4200
        store.prune(self.hour)
        remaining = mt.segments(self.directory)
        self.assertLessEqual(sum(path.stat().st_size for _, path in remaining), store.max_bytes)
        self.assertIn(f"{store.current}.jsonl", [path.name for _, path in remaining])
        self.assertEqual([path.name for _, path in remaining][-1], f"{store.current}.jsonl")
        store.max_bytes = 1
        store.prune(self.hour)
        self.assertEqual([path.name for _, path in mt.segments(self.directory)], [f"{store.current}.jsonl"])
        store.close()


class GrowthTests(unittest.TestCase):
    @staticmethod
    def slow(t: float, trees: dict[str, int], rest: int | None) -> dict:
        entries = [{"tree": tree, "rss_anon_kib": kib, "swap_kib": 0} for tree, kib in trees.items()]
        if rest is not None:
            entries.append({"tree": "(rest)", "rss_anon_kib": rest, "swap_kib": 0, "groups": 1})
        return {"kind": "slow", "t": t, "t9": {"app.scope": {"classes": [], "trees": entries}}}

    def test_growth_is_never_invented_for_an_entry_that_crossed_the_fold(self) -> None:
        before = {f"claude[{pid}]": 1_100_000 for pid in range(100, 120)}
        after = dict(before) | {"claude[105]": 1_100_500, "claude[119]": 1_080_000}
        del after["claude[118]"]
        after["claude[120]"] = 1_100_240  # was the 21st tree, folded into (rest)
        growth = mt.t9_growth([self.slow(1, before, 1_090_000), self.slow(2, after, 1_100_000)])
        self.assertEqual((growth["growth"][0]["tree"], growth["growth"][0]["growth_kib"]), ("claude[105]", 500))
        self.assertTrue(all(item["growth_kib"] < 1000 for item in growth["growth"]))
        self.assertEqual([item["tree"] for item in growth["entered"]], ["claude[120]"])
        self.assertNotIn("growth_kib", growth["entered"][0])

    def test_an_entry_missing_from_a_complete_list_is_new(self) -> None:
        growth = mt.t9_growth([self.slow(1, {"claude[1]": 10}, None),
                               self.slow(2, {"claude[1]": 10, "codex[2]": 7}, None)])
        self.assertEqual(growth["growth"][0], {"cgroup": "app.scope", "section": "trees", "tree": "codex[2]",
                                               "anon_swap_kib": 7, "growth_kib": 7, "since": 1, "new": True})
        self.assertEqual(growth["entered"], [])

    @staticmethod
    def window(*samples: dict[str, tuple[dict[str, int], bool]]) -> list[dict]:
        """Slow samples at t = 1, 2, ...; each maps a cgroup to its trees and whether its list folded a tail."""
        records = []
        for t, cgroups in enumerate(samples, 1):
            t9 = {}
            for cgroup, (trees, folded) in cgroups.items():
                entries = [{"tree": tree, "rss_anon_kib": kib, "swap_kib": 0} for tree, kib in trees.items()]
                if folded:
                    entries.append({"tree": "(rest)", "rss_anon_kib": 1, "swap_kib": 0, "groups": 1})
                t9[cgroup] = {"classes": [], "trees": entries}
            records.append({"kind": "slow", "t": t, "t9": t9})
        return records

    def test_each_entry_is_measured_from_the_first_sample_that_knows_its_size(self) -> None:
        growth = mt.t9_growth(self.window(
            {"app.scope": ({"claude[1]": 100}, False), "folded.scope": ({"a[1]": 10}, True)},
            {"app.scope": ({"claude[1]": 150}, True), "folded.scope": ({"a[1]": 10, "b[2]": 20}, True),
             "late.service": ({"(no agent)": 4_000_000}, False)},
            {"app.scope": ({"claude[1]": 600, "codex[2]": 70}, False),
             "folded.scope": ({"a[1]": 10, "b[2]": 50, "c[3]": 9}, True),
             "late.service": ({"(no agent)": 4_000_100}, False), "last.service": ({"(no agent)": 3_000_000}, False)},
        ))
        found = {(item["cgroup"], item["tree"]): (item["growth_kib"], item["since"], item["new"])
                 for item in growth["growth"]}
        self.assertEqual(found, {
            ("app.scope", "claude[1]"): (500, 1, False),
            ("app.scope", "codex[2]"): (70, 1, True),  # missing from a complete list: it had nothing
            ("folded.scope", "a[1]"): (0, 1, False),
            ("folded.scope", "b[2]"): (30, 2, False),  # folded into (rest) first, listed later
            ("late.service", "(no agent)"): (100, 2, False),  # its cgroup was not in the first sample
        })
        self.assertEqual(growth["growth"][0]["tree"], "claude[1]")
        # Never known before the latest sample: still folded, or the cgroup appeared only now.
        self.assertEqual(sorted((item["cgroup"], item["tree"]) for item in growth["entered"]),
                         [("folded.scope", "c[3]"), ("last.service", "(no agent)")])

    def test_growth_is_measured_within_the_latest_samples_boot(self) -> None:
        window = self.window({"app.service": ({"claude[1]": 100}, False)},
                             {"app.service": ({"claude[1]": 700}, False)},
                             {"app.service": ({"claude[1]": 700, "codex[2]": 5}, False)})
        for record, boot in zip(window, ("before", "after", "after")):
            record["boot"] = boot
        growth = mt.t9_growth(window)
        self.assertEqual((growth["from"], growth["to"]), (2, 3))
        self.assertEqual({item["tree"]: (item["growth_kib"], item["since"], item["new"]) for item in growth["growth"]},
                         {"claude[1]": (0, 2, False), "codex[2]": (5, 2, True)})
        # Only the latest sample is from this boot: nothing earlier knows any size.
        growth = mt.t9_growth(window[:2])
        self.assertEqual((growth["from"], growth["growth"]), (2, []))
        self.assertEqual([item["tree"] for item in growth["entered"]], ["claude[1]"])

    def test_report_marks_new_and_entered_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            now = time.time()
            store = mt.SampleStore(state / "samples", 86400, 1 << 30)
            window = self.window(
                {"app.scope": ({"claude[1]": 100}, False)},
                {"app.scope": ({"claude[1]": 150}, False)},
                {"app.scope": ({"claude[1]": 600 << 10, "codex[2]": 70 << 10}, False),
                 "last.service": ({"(no agent)": 3 << 20}, False)},
            )
            for offset, record in zip((-120, -60, -1), window):
                store.append(record | {"t": now + offset})
            store.close()
            mt.write_json_atomic(state / "latest.json", {"schema": mt.SCHEMA, "kind": "fast", "t": now - 1})
            result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "report", "--state-dir", str(state)],
                                    text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        claude = next(line for line in lines if line.endswith("app.scope  claude[1]"))
        codex = next(line for line in lines if line.endswith("app.scope  codex[2]"))
        self.assertIn("+600 MiB over 119 s  ", claude)
        self.assertIn("+70 MiB over 119 s, new  ", codex)
        entered = lines.index("T9 entered with an unknown earlier size:")
        self.assertRegex(lines[entered + 1], r"^ +3072 MiB now  last\.service  \(no agent\)$")


def journal_entry(t: float, message: str, **fields: str) -> dict:
    return {"__REALTIME_TIMESTAMP": str(int(t * 1e6)), "__CURSOR": f"s=fixture;t={int(t * 1e6)}",
            "MESSAGE": message, "_CMDLINE": "/usr/lib/systemd/systemd-oomd CMDLINE-SENTINEL-55d0",
            "_COMM": "COMM-SENTINEL", **fields}


# What journald itself records about the senders of systemd's kill messages (the underscore fields a
# client cannot set), as seen in this host's journal: PID 1, and the user manager in its init.scope.
SYSTEM_MANAGER = {"_PID": "1", "_UID": "0", "_SYSTEMD_UNIT": "init.scope"}
USER_MANAGER = {"_PID": "4344", "_UID": str(UID), "_SYSTEMD_UNIT": f"user@{UID}.service",
                "_SYSTEMD_USER_UNIT": "init.scope"}

OOMD_KILL_KINDS = ["oomd-kill", "oomd", "oomd-kill", "unit-oomd-kill"]


def oomd_kill_entries(t0: float, scope: str) -> list[dict]:
    oomd = {"_SYSTEMD_UNIT": "systemd-oomd.service", "_TRANSPORT": "journal", "_BOOT_ID": "b" * 32}
    return [
        journal_entry(t0, "Considered 159 cgroups for killing, top candidates were:", **oomd),
        journal_entry(t0, f"        Path: /user.slice/{scope}", **oomd),
        journal_entry(t0 + 0.05, f"Marked /user.slice/{scope} for killing due to memory used (1) / total (2) and "
                                 "swap used (3) / total (4) being more than 90.00%", **oomd),
        journal_entry(t0 + 1.1, f"{scope}: systemd-oomd killed some process(es) in this unit.",
                      MESSAGE_ID=mt.MESSAGE_UNIT_OOMD_KILL, USER_UNIT=scope, **USER_MANAGER),
    ]


class IncidentTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.t0 = 1_791_000_000.0
        store = mt.SampleStore(self.root / "samples", 86400 * 30, 1 << 30)
        for offset in range(-1800, 121, 10):  # 30 minutes before to 2 minutes after
            store.append(fast_record(self.t0 + offset, available=1000 + offset))
            if offset % 60 == 0:
                store.append(slow_record(self.t0 + offset, node_kib=100_000 + 10 * (offset + 1800)))
        store.close()

    def incidents(self, max_files: int = 10):
        return mt.Incidents(self.root / "incidents", self.root / "samples", 900.0, 60.0, max_files)

    def test_kill_record_keeps_the_preceding_window_and_top_contributors(self) -> None:
        incidents = self.incidents()
        incidents.handle(journal_entry(self.t0 - 5, "unrelated oomd note", _SYSTEMD_UNIT="systemd-oomd.service"))
        incidents.handle(journal_entry(self.t0 - 4, "a normal kernel line", _TRANSPORT="kernel"))
        self.assertEqual(list((self.root / "incidents").iterdir()), [])
        for entry in oomd_kill_entries(self.t0, "app-org.chromium.Chromium-1.scope"):
            incidents.handle(entry)
        files = list((self.root / "incidents").glob("*.json"))
        self.assertEqual(len(files), 1)
        # The record is written when it opens; the events that join it wait in memory for the tick's write.
        self.assertEqual(len(json.loads(files[0].read_text())["events"]), 1)
        self.assertTrue(incidents.unwritten)
        incidents.flush()
        self.assertFalse(incidents.unwritten)
        record = json.loads(files[0].read_text())
        self.assertTrue(record["id"].endswith("Z-oomd-kill"))
        self.assertEqual(record["dropped_events"], 0)
        self.assertFalse(record["finalized"])
        self.assertEqual([event["kind"] for event in record["events"]], OOMD_KILL_KINDS)
        self.assertEqual(record["events"][3]["user_unit"], "app-org.chromium.Chromium-1.scope")
        window = record["window"]
        fast_times = [sample["t"] for sample in window["fast"]]
        self.assertEqual((fast_times[0], fast_times[-1], len(fast_times)), (self.t0 - 900, self.t0, 91))
        self.assertEqual(len(window["slow"]), 16)
        growth = record["t9"]["growth"]
        self.assertEqual({item["section"] for item in growth}, {"classes", "trees"})
        self.assertTrue(all(item["growth_kib"] == 9000 for item in growth))
        self.assertNotIn("(rest)", json.dumps(growth))
        self.assertEqual(record["t9"]["latest"]["app.scope"]["classes"][0]["rss_anon_kib"], 100_000 + 18000)

        incidents.finalize_due(self.t0 + 30)
        self.assertFalse(json.loads(files[0].read_text())["finalized"])
        incidents.finalize_due(self.t0 + 61)
        record = json.loads(files[0].read_text())
        self.assertTrue(record["finalized"])
        following = [sample["t"] for sample in record["following"]["fast"]]
        self.assertEqual((following[0], following[-1]), (self.t0 + 10, self.t0 + 60))
        text = files[0].read_text()
        for secret in SECRETS:
            self.assertNotIn(secret, text)

    def test_replayed_events_do_not_duplicate_a_record(self) -> None:
        for _ in range(2):  # a restart replays the journal from the saved cursor
            incidents = self.incidents()
            for entry in oomd_kill_entries(self.t0, "a.scope"):
                incidents.handle(entry)
            incidents.finalize()
        files = list((self.root / "incidents").glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(len(json.loads(files[0].read_text())["events"]), 4)

    def records(self) -> list[dict]:
        return [json.loads(path.read_text()) for path in sorted((self.root / "incidents").glob("*.json"))]

    def kill_message(self, t: float, message_id: str, **sender: str) -> dict:
        return journal_entry(t, "x.scope: killed some process(es) in this unit.",
                             **({"MESSAGE_ID": message_id, "USER_UNIT": "x.scope"} | sender))

    def test_kill_messages_are_taken_only_from_the_system_manager_and_this_users_manager(self) -> None:
        for sender in (SYSTEM_MANAGER, USER_MANAGER):
            for message_id in (mt.MESSAGE_UNIT_OOMD_KILL, mt.MESSAGE_UNIT_OOM):
                shutil.rmtree(self.root / "incidents", ignore_errors=True)
                incidents = self.incidents()
                incidents.handle(self.kill_message(self.t0, message_id, **sender))
                self.assertEqual(len(self.records()), 1, (sender, message_id))
                self.assertEqual(incidents.ignored, 0)

        # MESSAGE_ID is set by the sender; only journald's own fields say who the sender was.
        foreign = {
            "another user's service": {"_PID": "812", "_UID": str(UID + 1), "_SYSTEMD_UNIT": "dynamic.service"},
            "another user's manager": {"_PID": "4400", "_UID": str(UID + 1), "_SYSTEMD_UNIT": f"user@{UID + 1}.service",
                                       "_SYSTEMD_USER_UNIT": "init.scope"},
            "an app of this user": USER_MANAGER | {"_SYSTEMD_USER_UNIT": "app-forger.scope"},
            "a login session of this user": {"_PID": "900", "_UID": str(UID), "_SYSTEMD_UNIT": "session-2.scope"},
            "a process of init.scope that is not PID 1": SYSTEM_MANAGER | {"_PID": "2"},
            "PID 1 of another user": SYSTEM_MANAGER | {"_UID": "1001"},
            "fields chosen by the sender": {"PID": "1", "UID": "0", "SYSTEMD_UNIT": "init.scope", "UNIT": "init.scope",
                                            "USER_UNIT": "init.scope"},
            "no origin at all": {},
        }
        shutil.rmtree(self.root / "incidents")
        incidents = self.incidents()
        for name, sender in foreign.items():
            for message_id in (mt.MESSAGE_UNIT_OOMD_KILL, mt.MESSAGE_UNIT_OOM):
                incidents.handle(self.kill_message(self.t0, message_id, **sender))
        self.assertEqual(list((self.root / "incidents").iterdir()), [])
        self.assertEqual((incidents.ignored, incidents.bytes_written), (2 * len(foreign), 0))

        # A flood of them neither joins a genuine record nor costs a write.
        incidents.handle(self.kill_message(self.t0, mt.MESSAGE_UNIT_OOMD_KILL, **USER_MANAGER))
        written = incidents.bytes_written
        for index in range(2000):
            incidents.handle(journal_entry(self.t0 + 0.5 + index / 4000, f"forged {index}",
                                           MESSAGE_ID=mt.MESSAGE_UNIT_OOM, **foreign["another user's service"]))
        self.assertEqual((incidents.ignored, incidents.bytes_written), (2 * len(foreign) + 2000, written))
        self.assertEqual([len(record["events"]) for record in self.records()], [1])

    def test_a_kill_read_in_pieces_or_across_restarts_makes_one_record(self) -> None:
        entries = oomd_kill_entries(self.t0, "a.scope")
        # Closed on a tick between two journal reads.
        incidents = self.incidents()
        incidents.handle(entries[0])
        incidents.finalize_due(self.t0 + 61)
        for entry in entries[1:]:
            incidents.handle(entry)
        incidents.flush()
        self.assertEqual([len(record["events"]) for record in self.records()], [4])
        self.assertTrue(self.records()[0]["finalized"])
        shutil.rmtree(self.root / "incidents")
        # Left open by a collector that stopped mid-burst; the next one resumes it when it starts (recover). Without
        # that, the rest of the burst still joins the one stored record, which waits for a start to be finalized.
        for recover in (False, True):
            first = self.incidents()
            first.handle(entries[0])
            second = self.incidents()
            if recover:
                second.recover(self.t0 + 1)
            for entry in entries[1:]:
                second.handle(entry)
            second.finalize_due(self.t0 + 61)
            second.flush()
            records = self.records()
            self.assertEqual([len(record["events"]) for record in records], [4])
            self.assertEqual(records[0]["finalized"], recover)
            shutil.rmtree(self.root / "incidents")

    def test_a_record_left_open_is_finalized_by_the_next_collector(self) -> None:
        first = self.incidents()
        for entry in oomd_kill_entries(self.t0, "a.scope"):
            first.handle(entry)
        first.flush()
        self.assertFalse(self.records()[0]["finalized"])
        # Every write of the record counts toward the collector's written bytes: one when it opened, with its first
        # event, and one for the three events that joined it.
        size = max(path.stat().st_size for path in (self.root / "incidents").iterdir())
        self.assertGreater(first.bytes_written, size)
        self.assertLess(first.bytes_written, 2 * size)
        self.incidents().recover(self.t0 + 120)
        record = self.records()[0]
        self.assertTrue(record["finalized"])
        self.assertEqual([event["kind"] for event in record["events"]], OOMD_KILL_KINDS)
        following = [sample["t"] for sample in record["following"]["fast"]]
        self.assertEqual((following[0], following[-1]), (self.t0 + 10, self.t0 + 60))

    def test_a_damaged_segment_keeps_what_it_can_and_the_record_is_written(self) -> None:
        segments = mt.segments(self.root / "samples")
        damaged = next(path for start, path in segments if path.name.endswith(".gz") and start <= self.t0 - 600)
        data = bytearray(damaged.read_bytes())
        data[len(data) // 2: len(data) // 2 + 64] = bytes(64)  # valid header, corrupt deflate stream
        damaged.write_bytes(bytes(data))
        try:
            gzip.decompress(bytes(data))
        except mt.zlib.error:
            pass
        else:
            self.fail("the fixture did not damage the stream")
        incidents = mt.Incidents(self.root / "incidents", self.root / "samples", 3600.0, 60.0, 10)
        for entry in oomd_kill_entries(self.t0, "a.scope"):
            incidents.handle(entry)
        record = self.records()[0]
        self.assertTrue(record["window"]["fast"])
        self.assertEqual(record["window"]["fast"][-1]["t"], self.t0)

    def test_kernel_oom_opens_a_redacted_record_and_records_are_bounded(self) -> None:
        incidents = self.incidents(max_files=2)
        for index in range(4):
            t = self.t0 - 600 + index * 120
            incidents.handle(journal_entry(t, "COMM-SENTINEL invoked oom-killer: gfp_mask=0x0(none), order=0, "
                                              "oom_score_adj=0", _TRANSPORT="kernel"))
            incidents.handle(journal_entry(t + 0.1, "[ 4242] 1000 4242 COMM-SENTINEL", _TRANSPORT="kernel"))
            incidents.handle(journal_entry(t + 0.2, "Memory cgroup out of memory: Killed process 4242 (COMM-SENTINEL) "
                                                    "total-vm:1kB", _TRANSPORT="kernel"))
            incidents.handle(journal_entry(
                t + 0.3, "x.scope: A process of this unit has been killed by the OOM killer.",
                MESSAGE_ID=mt.MESSAGE_UNIT_OOM, USER_UNIT="x.scope", **SYSTEM_MANAGER))
        incidents.finalize()
        files = sorted((self.root / "incidents").glob("*.json"))
        self.assertEqual(len(files), 2)
        record = json.loads(files[-1].read_text())
        self.assertEqual([event["kind"] for event in record["events"]], ["kernel-oom", "kernel-oom", "unit-oom-kill"])
        for path in files:
            for secret in SECRETS:
                self.assertNotIn(secret, path.read_text())

    def test_a_repeated_kill_message_id_is_counted_and_dropped_whatever_the_sender(self) -> None:
        # journalctl prints a field that an entry repeats as a list, and its MESSAGE_ID= match selects the entry when
        # any value matches. The managers never repeat MESSAGE_ID, so such an entry is never theirs.
        senders = {
            "another process of this user": {"_PID": "4242", "_UID": str(UID), "_SYSTEMD_UNIT": "app-x.scope"},
            "this user's manager": USER_MANAGER,
            "the system manager": SYSTEM_MANAGER,
        }
        repeated = ([mt.MESSAGE_UNIT_OOMD_KILL, mt.MESSAGE_UNIT_OOM], ["0" * 32, mt.MESSAGE_UNIT_OOM],
                    [mt.MESSAGE_UNIT_OOMD_KILL, mt.MESSAGE_UNIT_OOMD_KILL])
        incidents = self.incidents()
        for sender in senders.values():
            for message_id in repeated:
                incidents.handle(journal_entry(self.t0, "x.scope: killed some process(es) in this unit.",
                                               MESSAGE_ID=message_id, USER_UNIT="x.scope", **sender))
        self.assertEqual(list((self.root / "incidents").iterdir()), [])
        self.assertEqual((incidents.ignored, incidents.bytes_written), (len(senders) * len(repeated), 0))
        # Repeated values without a kill ID are not a kill message at all.
        incidents.handle(journal_entry(self.t0, "a note", MESSAGE_ID=["0" * 32, "1" * 32], **USER_MANAGER))
        self.assertEqual(incidents.ignored, len(senders) * len(repeated))

    def test_task_names_with_oom_words_cannot_multiply_a_records_writes(self) -> None:
        # Any process can put an OOM word in its task name, and the kernel prints that name at the end of the
        # process's row in every OOM report's task table and at the start of each of its segfault lines.
        names = ("oom-killer-test", "oom_reaper_test", "out of memory!")
        kernel = {"_TRANSPORT": "kernel", "_BOOT_ID": "b" * 32}
        memcg = f"/user.slice/user-{UID + 1}.slice/user@{UID + 1}.service/app.slice/probe.scope"
        recognized = [
            journal_entry(self.t0, f"{names[0]} invoked oom-killer: gfp_mask=0xcc0(GFP_KERNEL), order=0, "
                                   "oom_score_adj=200", **kernel),
            journal_entry(self.t0 + 0.5, "oom-kill:constraint=CONSTRAINT_MEMCG,nodemask=(null),cpuset=probe.scope,"
                                         f"mems_allowed=0,oom_memcg={memcg},task_memcg={memcg},task={names[1]},"
                                         "pid=500000,uid=1001", **kernel),
            journal_entry(self.t0 + 0.6, f"Memory cgroup out of memory: Killed process 500000 ({names[2]}) "
                                         "total-vm:302232kB, anon-rss:261536kB, file-rss:9336kB, shmem-rss:0kB, "
                                         "UID:1001 pgtables:580kB oom_score_adj:200", **kernel),
            journal_entry(self.t0 + 0.7, f"oom_reaper: reaped process 500000 ({names[2]}), now anon-rss:0kB, "
                                         "file-rss:0kB, shmem-rss:0kB", **kernel),
            journal_entry(self.t0 + 0.8, "probe.scope: A process of this unit has been killed by the OOM killer.",
                          MESSAGE_ID=mt.MESSAGE_UNIT_OOM, USER_UNIT="probe.scope", **SYSTEM_MANAGER),
        ]
        rows = [journal_entry(self.t0 + 1e-4 * (index + 1),
                              f"[{pid:7d}]  1001 {pid:7d}    75558    67718    65384     2334         0   593920"
                              f"        0           200 {names[index % 3]}", **kernel)
                for index, pid in enumerate(range(500001, 502001))]
        crashes = [journal_entry(self.t0 + 0.9 + index / 100,
                                 f"{name}[{600000 + index}]: segfault at 0 ip 0000562ec0a62679 sp 00007ffdbc4368c0 "
                                 f"error 4 in {name}[2a679,562ec0a48000+f1000] likely on CPU 3 (core 0, socket 0)",
                                 **kernel)
                   for index, name in enumerate(names * 10)]
        incidents = self.incidents()
        for entry in [recognized[0], *rows, *recognized[1:4], *crashes, recognized[4]]:
            incidents.handle(entry)
        incidents.finalize()
        [record] = self.records()
        size = next((self.root / "incidents").glob("*.json")).stat().st_size
        # Written when it opened and when it was finalized, not once per line.
        self.assertLessEqual(incidents.bytes_written, 2 * size)
        messages = [event["message"] for event in record["events"]]
        kept = [message for message in messages if message != mt.KERNEL_OOM_UNRECOGNIZED]
        self.assertEqual(kept, [*(mt.kernel_oom_line(entry["MESSAGE"])[0] for entry in recognized[:4]),
                                recognized[4]["MESSAGE"]])
        unrecognized = len(rows) + len(crashes)
        self.assertEqual(messages.count(mt.KERNEL_OOM_UNRECOGNIZED), mt.MAX_UNRECOGNIZED_EVENTS)
        self.assertEqual(record["dropped_events"], unrecognized - mt.MAX_UNRECOGNIZED_EVENTS)
        self.assertLessEqual(len(messages), mt.MAX_RECORD_EVENTS)
        text = json.dumps(record)
        for name in names:
            self.assertNotIn(name, text)

    def test_a_record_keeps_at_most_its_cap_of_events_and_counts_the_rest(self) -> None:
        # An oom.group kill prints a "Killed process" line for every task of the cgroup.
        kills = [journal_entry(self.t0 + index / 1000, f"Memory cgroup out of memory: Killed process {4000 + index} "
                                                        "(x) total-vm:1kB, anon-rss:1kB", _TRANSPORT="kernel")
                 for index in range(mt.MAX_RECORD_EVENTS + 100)]
        incidents = self.incidents()
        for entry in kills:
            incidents.handle(entry)
        incidents.flush()
        [record] = self.records()
        self.assertEqual(len(record["events"]), mt.MAX_RECORD_EVENTS)
        self.assertEqual(record["dropped_events"], 100)
        last_kept = mt.kernel_oom_line(kills[mt.MAX_RECORD_EVENTS - 1]["MESSAGE"])[0]
        self.assertEqual(record["events"][-1]["message"], last_kept)
        # De-duplication runs first: the kept events, read again, change nothing and cost no write.
        written = incidents.bytes_written
        for entry in kills[: mt.MAX_RECORD_EVENTS]:
            incidents.handle(entry)
        self.assertFalse(incidents.unwritten)
        incidents.flush()
        self.assertEqual((incidents.bytes_written, self.records()[0]["dropped_events"]), (written, 100))
        # An event that was dropped is not remembered, so reading it again, as after a restart, counts it again.
        incidents.handle(kills[-1])
        incidents.flush()
        self.assertEqual(self.records()[0]["dropped_events"], 101)

    def test_a_record_too_large_to_read_is_left_alone(self) -> None:
        entries = oomd_kill_entries(self.t0, "a.scope")
        self.incidents().handle(entries[0])
        [path] = (self.root / "incidents").glob("*.json")
        size = path.stat().st_size
        self.assertIsNotNone(mt.load_json(path, size))
        self.assertIsNone(mt.load_json(path, size - 1))
        before = path.read_bytes()
        with mock.patch.object(mt, "MAX_RECORD_BYTES", size - 1):
            incidents = self.incidents()
            incidents.recover(self.t0 + 1)  # neither resumed nor finalized
            incidents.handle(entries[0])  # its own opening entry, read again, opens nothing in its place
            self.assertEqual((path.read_bytes(), incidents.bytes_written), (before, 0))
            incidents.handle(entries[1])  # nothing to join
            for entry in entries[2:]:  # the next opener opens a record of its own
                incidents.handle(entry)
            incidents.finalize()
        self.assertEqual(path.read_bytes(), before)
        records = self.records()
        self.assertEqual([[event["kind"] for event in record["events"]] for record in records],
                         [["oomd-kill"], ["oomd-kill", "unit-oomd-kill"]])
        self.assertEqual([record["finalized"] for record in records], [False, True])

    def opener(self, offset: float) -> dict:
        return self.kill_message(self.t0 + offset, mt.MESSAGE_UNIT_OOM, **SYSTEM_MANAGER)

    def joiner(self, offset: float) -> dict:
        return journal_entry(self.t0 + offset, "a late detail", _SYSTEMD_UNIT="systemd-oomd.service")

    def stored(self) -> list[tuple[float, int, bool]]:
        """Each stored record's first-event time after t0, its number of events, and whether it is finalized."""
        return [(record["opened"] - self.t0, len(record["events"]), record["finalized"]) for record in self.records()]

    def test_the_record_cap_counts_a_record_that_is_still_open(self) -> None:
        offsets = [0.0, 120.0, 240.0, 360.0]
        for cap in (1, 2):
            with self.subTest(cap=cap):
                shutil.rmtree(self.root / "incidents", ignore_errors=True)
                incidents = self.incidents(max_files=cap)
                for index, offset in enumerate(offsets):
                    incidents.handle(self.opener(offset))  # the record it opens is not finalized until the next one
                    newest = offsets[: index + 1][-cap:]
                    self.assertEqual(self.stored(), [(kept, 1, kept != offset) for kept in newest])
                incidents.flush()  # as a stopping collector does
                self.assertEqual([opened for opened, _, _ in self.stored()], offsets[-cap:])
                restarted = self.incidents(max_files=cap)
                restarted.recover(self.t0 + 600)
                restarted.finalize_due(self.t0 + 600)
                self.assertEqual(self.stored(), [(kept, 1, True) for kept in offsets[-cap:]])

    def test_a_record_the_cap_deletes_is_not_written_back_by_what_was_held_in_memory(self) -> None:
        # With room for one record, a kill older than the stored one opens a record that is deleted at once.
        incidents = self.incidents(max_files=1)
        incidents.handle(self.opener(0))
        incidents.handle(self.opener(120))
        self.assertEqual(self.stored(), [(120.0, 1, False)])
        incidents.handle(self.opener(1))  # too late to join the first record, which is gone
        self.assertIsNotNone(incidents.open_record)  # the newer record stays open
        self.assertFalse(incidents.unwritten)
        self.assertEqual(self.stored(), [(120.0, 1, False)])
        incidents.handle(self.opener(240))
        self.assertFalse(incidents.unwritten)
        self.assertEqual(self.stored(), [(240.0, 1, False)])
        incidents.flush()
        self.assertEqual(self.stored(), [(240.0, 1, False)])

        # With room for two, a late event joins the older finalized record in memory; the next kill's record then
        # pushes that record out, with the event that was waiting to be written.
        shutil.rmtree(self.root / "incidents")
        incidents = self.incidents(max_files=2)
        incidents.handle(self.opener(0))
        incidents.handle(self.opener(120))
        incidents.handle(self.joiner(1))
        self.assertTrue(incidents.unwritten)
        self.assertEqual(self.stored(), [(0.0, 1, True), (120.0, 1, False)])
        incidents.handle(self.opener(240))
        self.assertFalse(incidents.unwritten)
        self.assertEqual(self.stored(), [(120.0, 1, True), (240.0, 1, False)])
        incidents.flush()
        incidents.handle(self.joiner(2))  # nothing is left for a later event to join either
        incidents.flush()
        self.assertEqual(self.stored(), [(120.0, 1, True), (240.0, 1, False)])

    def test_a_late_joined_record_among_the_newest_keeps_its_unwritten_events(self) -> None:
        incidents = self.incidents(max_files=2)
        incidents.handle(self.opener(0))
        incidents.handle(self.opener(120))
        incidents.finalize_due(self.t0 + 181)
        incidents.handle(self.joiner(121))  # joins the newest record, finalized, in memory
        incidents.handle(self.opener(240))  # the cap deletes the oldest record, not the one that is held
        self.assertTrue(incidents.unwritten)
        self.assertEqual(self.stored(), [(120.0, 1, True), (240.0, 1, False)])
        incidents.flush()
        self.assertFalse(incidents.unwritten)
        self.assertEqual(self.stored(), [(120.0, 2, True), (240.0, 1, False)])

    def test_a_record_that_could_not_be_deleted_stays_held_until_the_next_prune(self) -> None:
        incidents = self.incidents(max_files=2)
        incidents.handle(self.opener(0))
        incidents.handle(self.opener(120))
        incidents.handle(self.joiner(1))  # held in memory with the oldest record, which the next kill pushes out
        with mock.patch.object(Path, "unlink", side_effect=PermissionError):
            incidents.handle(self.opener(240))
        self.assertTrue(incidents.unwritten)  # the record is still there, and so is its change
        incidents.flush()
        self.assertEqual(self.stored(), [(0.0, 2, True), (120.0, 1, True), (240.0, 1, False)])
        incidents.handle(self.opener(360))
        self.assertEqual(self.stored(), [(240.0, 1, True), (360.0, 1, False)])

    def test_a_start_enforces_the_record_cap_before_it_recovers_records(self) -> None:
        # A lowered --max-incidents, or an earlier version, can leave more records than the cap allows.
        def leave_three_open() -> None:
            shutil.rmtree(self.root / "incidents", ignore_errors=True)
            for offset in (0.0, 120.0, 240.0):
                self.incidents(max_files=3).handle(self.opener(offset))  # each by a collector that then stopped
            self.assertEqual(self.stored(), [(0.0, 1, False), (120.0, 1, False), (240.0, 1, False)])

        leave_three_open()
        finalizing = self.incidents(max_files=1)
        finalizing.recover(self.t0 + 600)  # every grace period has passed
        self.assertEqual(self.stored(), [(240.0, 1, True)])
        [kept] = (self.root / "incidents").glob("*.json")
        self.assertEqual(finalizing.bytes_written, kept.stat().st_size)  # the deleted records were not finalized first

        leave_three_open()
        resuming = self.incidents(max_files=1)
        resuming.recover(self.t0 + 250)  # the newest record is still in its grace period
        self.assertEqual((self.stored(), resuming.bytes_written), ([(240.0, 1, False)], 0))
        resuming.handle(self.joiner(241))  # joins the record that was resumed
        resuming.flush()
        self.assertEqual(self.stored(), [(240.0, 2, False)])

    def files(self) -> dict[str, bytes]:
        return {path.name: path.read_bytes() for path in sorted((self.root / "incidents").glob("*.json"))}

    def events(self) -> list[list[float]]:
        """Each stored record's event times after t0."""
        return [[round(event["t"] - self.t0, 6) for event in record["events"]] for record in self.records()]

    def assert_each_event_is_in_the_record_it_opened_or_followed(self) -> None:
        """No event is in two records, and every record's first event is the one it is named and opened for."""
        records = self.records()
        keys = [mt.event_key(event) for record in records for event in record["events"]]
        self.assertEqual(len(keys), len(set(keys)))
        for record in records:
            self.assertEqual((record["events"][0]["t"], mt.record_opened(record["id"])),
                             (record["opened"], record["opened"]))

    def two_close_kills(self) -> tuple[list[dict], dict[str, bytes]]:
        """The entries of two kills 61 s apart with a line of the first one 2 s before the second, which is within
        the grace period of both first events, after one and before the other; and the record files that one read
        of them leaves."""
        entries = [self.opener(0), self.joiner(3), self.joiner(59), self.opener(61), self.joiner(62)]
        once = self.incidents()
        for entry in entries:
            once.handle(entry)
        once.flush()
        once.finalize_due(self.t0 + 122)
        self.assertEqual((self.events(), [record["finalized"] for record in self.records()]),
                         ([[0.0, 3.0, 59.0], [61.0, 62.0]], [True, True]))
        self.assert_each_event_is_in_the_record_it_opened_or_followed()
        return entries, self.files()

    def test_entries_read_again_leave_two_close_kills_as_they_were_read_once(self) -> None:
        entries, control = self.two_close_kills()
        # Read again from the start by a later collector, with a tick's write after every entry.
        again = self.incidents()
        again.recover(self.t0 + 300)
        for entry in entries:
            again.handle(entry)
            again.flush()
        self.assertEqual((self.files(), again.bytes_written), (control, 0))

    def test_entries_read_again_after_a_stop_without_the_last_write_change_no_other_record(self) -> None:
        entries, control = self.two_close_kills()
        first, second = control
        # The position was saved after the second entry; the later ones changed the records, in memory and on
        # disk, and the collector died before its next write. It restarts 30 s into the second record's grace
        # period and reads again every entry after the saved position.
        shutil.rmtree(self.root / "incidents")
        stopped = self.incidents()
        for entry in entries[:2]:
            stopped.handle(entry)
        stopped.flush()
        for entry in entries[2:]:
            stopped.handle(entry)
        left = self.files()
        self.assertEqual(self.events(), [[0.0, 3.0, 59.0], [61.0]])
        restarted = self.incidents()
        restarted.recover(self.t0 + 91)
        for entry in entries[2:]:
            restarted.handle(entry)
        restarted.flush()
        self.assertEqual(self.files()[first], left[first])
        self.assertEqual(self.events(), [[0.0, 3.0, 59.0], [61.0, 62.0]])
        self.assert_each_event_is_in_the_record_it_opened_or_followed()
        restarted.finalize_due(self.t0 + 122)
        self.assertEqual(self.files(), control)

    def test_a_line_before_a_kill_is_no_more_part_of_its_record_when_read_again(self) -> None:
        # A line that opens nothing, 5 s before a kill, belongs to no record. Read again once the kill's record
        # exists, it still belongs to none: the record's first event is after it.
        entries = [self.joiner(-5), self.opener(0), self.joiner(2)]
        for restart in (10, 300):  # inside the record's grace period, where it is resumed, and after it
            with self.subTest(restart=restart):
                shutil.rmtree(self.root / "incidents", ignore_errors=True)
                once = self.incidents()
                for entry in entries:
                    once.handle(entry)
                once.flush()
                once.finalize_due(self.t0 + restart)
                before = self.files()
                self.assertEqual(self.events(), [[0.0, 2.0]])
                again = self.incidents()
                again.recover(self.t0 + restart)
                for entry in entries:
                    again.handle(entry)
                    again.flush()
                self.assertEqual(self.files(), before)

    def test_entries_read_again_do_not_move_an_event_of_a_deleted_record_into_the_kept_one(self) -> None:
        # Room for one record, two kills 94 s apart, and a line of the first one 44 s before the second. The second
        # kill's record is the one kept.
        entries = [self.opener(0), self.joiner(50), self.opener(94)]
        once = self.incidents(max_files=1)
        for entry in entries:
            once.handle(entry)
        once.flush()
        once.finalize_due(self.t0 + 155)
        before = self.files()
        self.assertEqual(self.stored(), [(94.0, 1, True)])
        again = self.incidents(max_files=1)
        again.recover(self.t0 + 300)
        for entry in entries:
            again.handle(entry)
            again.flush()
        self.assertEqual(self.files(), before)

    def add_fast_samples(self, *offsets: float) -> None:
        store = mt.SampleStore(self.root / "samples", 86400 * 30, 1 << 30)
        for offset in offsets:
            store.append(fast_record(self.t0 + offset))
        store.close()

    def test_a_kill_older_than_every_kept_record_read_again_does_not_close_the_open_record(self) -> None:
        # Room for one record. The collector stops 10 s after a kill and restarts 2 s later, with the kill's record
        # still in its grace period. With `replayed`, it then reads again, from a position older than every kept
        # record, the opener of an earlier kill whose record the cap deleted.
        def following(kill: int, replayed: bool) -> list[float]:
            """When, after the kill at t0 + kill, the fast samples in its finalized record were taken."""
            shutil.rmtree(self.root / "incidents", ignore_errors=True)
            stopped = self.incidents(max_files=1)
            stopped.handle(self.opener(0))
            stopped.handle(self.opener(kill))
            self.add_fast_samples(kill + 10)
            restarted = self.incidents(max_files=1)
            restarted.recover(self.t0 + kill + 12)
            if replayed:
                restarted.handle(self.opener(0))  # its record is written, finalized, and deleted at once
                self.assertEqual(self.stored(), [(kill, 1, False)])
                self.assertEqual(restarted.open_record.data["opened"], self.t0 + kill)
            self.add_fast_samples(*range(kill + 20, kill + 61, 10))
            restarted.finalize_due(self.t0 + kill + 59)
            self.assertEqual(self.stored(), [(kill, 1, False)])  # open until its grace period has passed
            restarted.finalize_due(self.t0 + kill + 61)
            [record] = self.records()
            self.assertTrue(record["finalized"])
            return [sample["t"] - record["opened"] for sample in record["following"]["fast"]]

        control = following(200, replayed=False)
        self.assertEqual(control, [10, 20, 30, 40, 50, 60])
        self.assertEqual(following(400, replayed=True), control)

    def test_the_grace_period_is_exact_to_the_microsecond_for_held_and_stored_records(self) -> None:
        def at(microseconds: int, entry: dict) -> dict:
            return entry | {"__REALTIME_TIMESTAMP": str(int(self.t0) * 1_000_000 + microseconds)}

        # A kill whose first event is not on a whole second, a line exactly 60 s after it, a line one microsecond
        # later, which belongs to no record, and a second kill 40 s after that.
        first, last, late, second = 333_881, 60_333_881, 60_333_882, 100_333_882
        entries = [at(first, self.opener(0)), at(last, self.joiner(0)), at(late, self.joiner(0)),
                   at(second, self.opener(0))]
        expected = [[0.333881, 60.333881], [100.333882]]
        once = self.incidents()
        for entry in entries:  # the first record is the open one, held, as its two lines are read
            once.handle(entry)
        once.flush()
        once.finalize_due(self.t0 + 200)
        before = self.files()
        self.assertEqual(self.events(), expected)
        self.assert_each_event_is_in_the_record_it_opened_or_followed()

        # Read again with both records stored and neither held: the opener's own entry and the line at exactly
        # 60 s find their record and change nothing, and the line after it still belongs to none.
        again = self.incidents()
        again.recover(self.t0 + 300)
        for entry in entries:
            again.handle(entry)
            self.assertFalse(again.unwritten)
            again.flush()
        self.assertEqual((self.files(), again.bytes_written), (before, 0))

        # A line not seen before, stamped exactly 60 s after the first event, joins the stored first record.
        detail = journal_entry(self.t0, "another late detail", _SYSTEMD_UNIT="systemd-oomd.service")
        again.handle(at(last, detail))
        again.handle(at(late, detail))
        again.flush()
        self.assertEqual([len(record["events"]) for record in self.records()], [3, 1])
        self.assertEqual(self.events(), [[0.333881, 60.333881, 60.333881], [100.333882]])
        self.assert_each_event_is_in_the_record_it_opened_or_followed()

    def test_an_entry_stamped_before_a_record_it_arrives_after_does_not_join_that_record(self) -> None:
        # journalctl delivers entries in the order journald received them, and the collector goes by the time
        # journald received them, so only a wall clock that stepped back delivers an entry stamped before the first
        # event of a record that exists already. The rule treats it as it treats the same entry read again in a
        # replay; it does not make one record of a kill whose entries the clock stepped back between.
        incidents = self.incidents()
        incidents.handle(self.opener(0))
        incidents.handle(self.joiner(-5))  # a line that opens nothing, stamped before the first event: not kept
        incidents.flush()
        self.assertEqual(self.events(), [[0.0]])
        incidents.handle(self.opener(-3))  # an opener stamped before it: a record of its own, finalized at once
        self.assertEqual(self.stored(), [(-3.0, 1, True), (0.0, 1, False)])
        self.assertEqual(incidents.open_record.data["opened"], self.t0)  # and the open record stays open
        incidents.handle(self.joiner(-1))  # after the older record's first event and before the open record's
        incidents.handle(self.joiner(2))
        incidents.flush()
        self.assertEqual(self.events(), [[-3.0, -1.0], [0.0, 2.0]])
        self.assertEqual(self.stored(), [(-3.0, 2, True), (0.0, 2, False)])
        self.assert_each_event_is_in_the_record_it_opened_or_followed()


# A follow call (--follow) prints FAKE_JOURNAL_ENTRIES after FAKE_JOURNAL_DELAY and lingers for
# FAKE_JOURNAL_LINGER; a catch-up call prints FAKE_JOURNAL_CATCH_UP and exits. FAKE_JOURNAL_PLAN can set a
# call's "entries", "tail" (text printed last, without a newline), "delay" and "linger", by call number.
# Entries without a timestamp or cursor get fresh ones.
FAKE_JOURNALCTL = r'''#!{python}
import json, os, sys, time
argv = sys.argv[1:]
log = os.environ["FAKE_JOURNAL_LOG"]
with open(log, "a") as handle:
    handle.write(json.dumps({{"pid": os.getpid(), "argv": argv}}) + "\n")
with open(log) as handle:
    call = len(handle.readlines()) - 1
if "--after-cursor" in argv and not argv[argv.index("--after-cursor") + 1].startswith("s="):
    sys.stderr.write("Failed to seek to cursor: Invalid argument\n")  # journalctl 262's own words
    sys.exit(1)  # like journalctl, refuse a malformed cursor at once and print nothing
follow = "--follow" in argv
plans = json.loads(os.environ.get("FAKE_JOURNAL_PLAN", "[]"))
plan = plans[call] if call < len(plans) else {{}}
if "fail" in plan:  # end at once without output: a signal number below zero, an exit status otherwise
    sys.stderr.write(plan.get("stderr", ""))
    sys.stderr.flush()
    if plan["fail"] < 0:
        os.kill(os.getpid(), -plan["fail"])
    sys.exit(plan["fail"])
time.sleep(plan.get("delay", float(os.environ.get("FAKE_JOURNAL_DELAY", "1.0")) if follow else 0))
t = int(time.time() * 1e6)
entries = plan.get("entries", json.loads(os.environ.get("FAKE_JOURNAL_ENTRIES" if follow else "FAKE_JOURNAL_CATCH_UP",
                                                        "[]")))
for offset, fields in enumerate(entries):
    fields.setdefault("__REALTIME_TIMESTAMP", str(t + offset))
    fields.setdefault("__CURSOR", "s=fake;i=%d" % (t + offset))
    print(json.dumps(fields), flush=True)
sys.stdout.write(plan.get("tail", ""))
sys.stdout.flush()
time.sleep(plan.get("linger", float(os.environ.get("FAKE_JOURNAL_LINGER", "60")) if follow else 0))
'''


def tree_digest(root: Path) -> dict[str, str]:
    digest = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            digest[relative] = "link:" + os.readlink(path)
        elif path.is_file():
            stat = path.stat()
            digest[relative] = hashlib.sha256(path.read_bytes()).hexdigest() + f":{stat.st_mtime_ns}:{stat.st_mode}"
        else:
            digest[relative] = "dir"
    return digest


class RunTests(FixtureCase):
    def setUp(self) -> None:
        super().setUp()
        self.fake = self.base / "fake-journalctl"
        self.fake.write_text(FAKE_JOURNALCTL.format(python=sys.executable))
        self.fake.chmod(0o755)
        self.log = self.base / "journal.log"
        scope = "app-org.chromium.Chromium-200.scope"
        # The fake stamps each entry with the time it prints it.
        entries = [{key: value for key, value in entry.items() if not key.startswith("__")}
                   for entry in oomd_kill_entries(0, scope)]
        entries.append({"_TRANSPORT": "kernel", "MESSAGE": "[ 4242] 1000 COMM-SENTINEL ARGV-SENTINEL-7f3a"})
        # Any process can log a message with systemd's MESSAGE_ID; the collector must not take it for systemd's.
        entries.insert(0, {"MESSAGE_ID": mt.MESSAGE_UNIT_OOM, "MESSAGE": "FORGED-SENTINEL: killed by the OOM killer",
                           "_UID": str(UID + 1), "_SYSTEMD_UNIT": "forger.service"})
        self.environment = os.environ | {
            "FAKE_JOURNAL_LOG": str(self.log),
            "FAKE_JOURNAL_ENTRIES": json.dumps(entries),
            "PYTHONDONTWRITEBYTECODE": "1",
            "MEMORY_TELEMETRY_FIXTURE": "ENVIRON-SENTINEL-91c2",
        }

    def command(self, *extra: str) -> list[str]:
        return [sys.executable, "-I", "-B", str(SCRIPT), "run", "--state-dir", str(self.state),
                *self.fixture.options(), "--interval", "0.2", "--slow-every", "2", "--window", "30",
                "--grace", "2", "--journalctl", str(self.fake), *extra]

    def journal_calls(self) -> list[dict]:
        try:
            text = self.log.read_text()
        except FileNotFoundError:
            return []
        return [json.loads(line) for line in text.split("\n")[:-1]]  # complete lines only

    def records(self) -> list[dict]:
        return [record for path in sorted((self.state / "incidents").glob("*.json"))
                if (record := mt.load_json(path)) is not None]

    def journal_state(self) -> str | None:
        return ((mt.load_json(self.state / "latest.json") or {}).get("collector") or {}).get("journal")

    def assert_child_gone(self, pid: int) -> None:
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)  # existence probe; sends no signal

    # Run tests start the collector without --duration, wait for what they check to appear in its record,
    # and then stop it with SIGTERM, so a slow or loaded host only makes them take longer.

    def start(self, command: list[str] | None = None, environment: dict | None = None) -> subprocess.Popen:
        process = subprocess.Popen(command or self.command(), env=environment or self.environment,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.addCleanup(self.stop, process, False)
        return process

    def wait_for(self, process: subprocess.Popen, condition, what: str, timeout: float = 180) -> None:
        deadline = time.monotonic() + timeout
        while not condition():
            if process.poll() is not None:
                self.fail(f"the collector exited while waiting for {what}: {process.communicate()[1]!r}")
            if time.monotonic() > deadline:
                self.fail(f"no {what} after {timeout:.0f} s")
            time.sleep(0.05)

    def stop(self, process: subprocess.Popen, check: bool = True) -> None:
        if process.stderr is None or process.stderr.closed:
            return  # already stopped and reaped
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
        _, errors = process.communicate(timeout=60)
        if check:
            self.assertEqual(process.returncode, 0, errors)

    def test_run_records_samples_and_a_kill_record_without_touching_sources(self) -> None:
        before = tree_digest(self.fixture.root)
        process = self.start()

        def recorded() -> bool:
            kinds = [sample["kind"] for sample in mt.read_samples(self.state / "samples", 0, time.time() + 60)]
            records = self.records()
            ignored = ((mt.load_json(self.state / "latest.json") or {}).get("collector") or {}).get("journal_ignored")
            return (self.journal_state() == "following" and kinds.count("fast") >= 3 and kinds.count("slow") >= 2
                    and len(records) == 1 and len(records[0]["events"]) == len(OOMD_KILL_KINDS) and ignored == 1)

        self.wait_for(process, recorded, "samples and a complete kill record")
        self.stop(process)
        self.assertEqual(tree_digest(self.fixture.root), before)

        latest = json.loads((self.state / "latest.json").read_text())
        self.assertEqual((latest["schema"], latest["kind"]), (mt.SCHEMA, "fast"))
        self.assertEqual(latest["oomd"], {"swap_used_limit": 0.9, "source": "etc/systemd/oomd.conf"})
        self.assertEqual(latest["collector"]["journal"], "following")
        self.assertEqual(latest["collector"]["journal_ignored"], 1)  # the forged kill message
        self.assertIn("per_s", latest["t3"])
        samples = mt.read_samples(self.state / "samples", 0, time.time() + 60)
        fast = [sample for sample in samples if sample["kind"] == "fast"]
        slow = [sample for sample in samples if sample["kind"] == "slow"]
        self.assertEqual(set(fast[-1]["collector"]), {"cpu_s", "oomctl_cpu_s", "rss_anon_kib", "rss_file_kib", "hwm_kib",
                                                     "bytes_written", "lag_ms", "journal", "journal_ignored",
                                                     "journal_cpu_s", "journal_rss_anon_kib",
                                                     "journal_rss_file_kib"}
                         if sys.platform == "linux" else
                         {"cpu_s", "oomctl_cpu_s", "rss_anon_kib", "rss_file_kib", "hwm_kib", "bytes_written", "lag_ms", "journal",
                          "journal_ignored"})
        self.assertTrue(all("collector_cgroup" in sample and "collector" not in sample for sample in slow))
        # Rates need an earlier sample from the same boot, so the first sample after a start has none.
        self.assertFalse({"interval_s", "per_s"} & (set(fast[0]) | set(fast[0]["t3"])))
        self.assertTrue({"interval_s"} <= set(fast[1]) and "per_s" in fast[1]["t3"])
        self.assertEqual(oct(self.state.stat().st_mode & 0o777), "0o700")
        for path in (self.state / "latest.json", *(self.state / "samples").iterdir()):
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600", path)

        records = list((self.state / "incidents").glob("*.json"))
        self.assertEqual(len(records), 1)
        record = json.loads(records[0].read_text())
        self.assertEqual([event["kind"] for event in record["events"]], OOMD_KILL_KINDS)
        # The first tick, a slow one, runs before journalctl starts, so the window always has samples.
        self.assertGreaterEqual(len(record["window"]["fast"]), 1)
        self.assertGreaterEqual(len(record["window"]["slow"]), 1)
        self.assertIn("app-com.anthropic.Claude-100.scope", record["t9"]["latest"])

        calls = self.journal_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["argv"], ["--follow", "--output=json", "--no-pager", "--quiet", "--lines=0",
                                            *mt.JOURNAL_MATCHES])
        self.assert_child_gone(calls[0]["pid"])  # SIGTERM (self.stop above) exited 0 and reaped its journalctl
        cursor = (self.state / "journal.cursor").read_text().strip()
        self.assertTrue(cursor.startswith("s=fake;i="))

        everything = "".join(path.read_text(errors="replace") for path in self.state.rglob("*")
                             if path.is_file() and not path.name.endswith(".gz"))
        everything += "".join(gzip.open(path, "rt").read() for path in self.state.rglob("*.gz"))
        for secret in (*SECRETS, "FORGED-SENTINEL"):
            self.assertNotIn(secret, everything)
        self.assertNotIn("/usr/lib/claude-desktop", everything)

        # A restart reads every entry after the saved cursor, from every boot, then follows; it finalizes the
        # record once its grace has passed, whether or not the first run lived that long. IncidentTests
        # check the following samples.
        while time.time() <= record["opened"] + 2.2:
            time.sleep(0.1)
        process = self.start(environment=self.environment | {"FAKE_JOURNAL_ENTRIES": "[]"})
        self.wait_for(process, lambda: len(self.journal_calls()) >= 3, "catch-up and follow calls")
        self.stop(process)
        calls = self.journal_calls()
        self.assertEqual(calls[1]["argv"], ["--output=json", "--no-pager", "--quiet", "--after-cursor", cursor,
                                            *mt.JOURNAL_MATCHES])
        self.assertEqual(calls[2]["argv"], ["--follow", "--output=json", "--no-pager", "--quiet",
                                            "--after-cursor", cursor, *mt.JOURNAL_MATCHES])
        for call in calls[1:]:
            self.assert_child_gone(call["pid"])
        record = json.loads(records[0].read_text())
        self.assertTrue(record["finalized"])
        self.assertIsInstance(record["following"]["fast"], list)
        self.assertEqual(len(list((self.state / "incidents").glob("*.json"))), 1)

    def fast_samples(self) -> list[dict]:
        samples = mt.read_samples(self.state / "samples", 0, time.time() + 60)
        return [sample for sample in samples if sample["kind"] == "fast"]

    def test_a_stall_is_followed_by_a_pause_not_by_a_sample_over_a_few_milliseconds(self) -> None:
        process = self.start(environment=self.environment | {"FAKE_JOURNAL_ENTRIES": "[]"})
        self.addCleanup(process.send_signal, signal.SIGCONT)  # a stopped collector would not see the SIGTERM
        self.wait_for(process, lambda: len(self.fast_samples()) >= 3, "the first fast samples")
        process.send_signal(signal.SIGSTOP)
        stopped = time.monotonic()
        while time.monotonic() - stopped < 1.0:  # five intervals pass while it cannot run
            time.sleep(0.05)
        process.send_signal(signal.SIGCONT)
        before = len(self.fast_samples())
        self.wait_for(process, lambda: len(self.fast_samples()) >= before + 4, "fast samples after the stall")
        self.stop(process)
        intervals = [sample["interval_s"] for sample in self.fast_samples() if "interval_s" in sample]
        self.assertGreater(max(intervals), 1.0)  # the sample that ran late covers the stall
        # The missed ticks are skipped, and the next sample waits half an interval (0.1 s) after the late one.
        self.assertGreaterEqual(min(intervals), 0.09, intervals)

    @unittest.skipIf(os.geteuid() == 0, "root can write where a directory refuses writes")
    def test_a_kill_whose_record_cannot_be_written_is_read_again_after_a_restart(self) -> None:
        self.state.mkdir()
        (self.state / "journal.cursor").write_text("s=saved\n")
        incidents = self.state / "incidents"
        incidents.mkdir(mode=0o700)
        incidents.chmod(0o500)  # readable, not writable
        self.addCleanup(incidents.chmod, 0o700)  # so the temporary directory can be removed
        entries = [entry | {"__CURSOR": f"s=kill;i={index}"}
                   for index, entry in enumerate(oomd_kill_entries(time.time() - 1, "a.scope"))]
        # Every catch-up call delivers the kill, as journalctl does for entries after the position it is given.
        plan = [{"entries": entries}, {"entries": entries}, {"entries": []}]
        environment = self.environment | {"FAKE_JOURNAL_PLAN": json.dumps(plan), "FAKE_JOURNAL_ENTRIES": "[]"}

        process = self.start(environment=environment)
        _, errors = process.communicate(timeout=180)  # it fails as soon as it handles the first kill entry
        self.assertEqual(process.returncode, 1, errors)
        self.assertIn(b"PermissionError", errors)
        self.assertEqual(self.records(), [])
        self.assertEqual((self.state / "journal.cursor").read_text().strip(), "s=saved")  # not past the kill

        incidents.chmod(0o700)
        process = self.start(environment=environment)

        def recorded() -> bool:
            records = self.records()
            return bool(records) and records[0]["events"][-1]["kind"] == "unit-oomd-kill"

        self.wait_for(process, recorded, "the kill record after the restart")
        self.stop(process)
        self.assertEqual(self.journal_calls()[1]["argv"][3:5], ["--after-cursor", "s=saved"])
        self.assertEqual([[event["kind"] for event in record["events"]] for record in self.records()],
                         [OOMD_KILL_KINDS])
        self.assertEqual((self.state / "journal.cursor").read_text().strip(), "s=kill;i=3")

    def test_a_restart_catches_up_before_following_and_handles_overlap_once(self) -> None:
        self.state.mkdir()
        (self.state / "journal.cursor").write_text("s=saved\n")
        entries = [entry | {"__CURSOR": f"s=kill;i={index}"}
                   for index, entry in enumerate(oomd_kill_entries(time.time() - 1, "a.scope"))]
        # The catch-up call reads the first three entries; the follow call delivers the third again.
        plan = [{"entries": entries[:3]}, {"entries": entries[2:], "delay": 0}]
        process = self.start(environment=self.environment | {"FAKE_JOURNAL_PLAN": json.dumps(plan)})

        def followed() -> bool:
            records = self.records()
            return len(self.journal_calls()) >= 2 and bool(records) and records[0]["events"][-1]["kind"] == (
                "unit-oomd-kill")

        self.wait_for(process, followed, "the followed kill message")
        self.stop(process)
        calls = self.journal_calls()
        self.assertEqual(calls[0]["argv"], ["--output=json", "--no-pager", "--quiet", "--after-cursor", "s=saved",
                                            *mt.JOURNAL_MATCHES])
        self.assertEqual(calls[1]["argv"], ["--follow", "--output=json", "--no-pager", "--quiet",
                                            "--after-cursor", "s=kill;i=2", *mt.JOURNAL_MATCHES])
        self.assertEqual([[event["kind"] for event in record["events"]] for record in self.records()],
                         [OOMD_KILL_KINDS])
        self.assertEqual((self.state / "journal.cursor").read_text().strip(), "s=kill;i=3")

    def drain(self, journal, calls: int, handle: bool = True) -> list[dict]:
        """Poll until journalctl has been started `calls` times in all and the latest child has ended.

        Like the run loop, it marks each entry handled once it has the entry, unless told not to."""
        entries: list[dict] = []
        deadline = time.monotonic() + 60
        while not (len(self.journal_calls()) >= calls and journal.process is None):
            if time.monotonic() > deadline:
                self.fail(f"journalctl was not started {calls} times")
            for entry in journal.poll(0.2):
                entries.append(entry)
                if handle:
                    journal.mark_handled(entry)
        return entries

    def journal_environment(self, **values: str) -> None:
        """Journal starts journalctl with this process's environment."""
        environment = mock.patch.dict(os.environ, self.environment | {"FAKE_JOURNAL_DELAY": "0",
                                                                      "FAKE_JOURNAL_LINGER": "0", **values})
        environment.start()
        self.addCleanup(environment.stop)

    def test_journal_catches_up_from_its_cursor_and_drops_only_a_rejected_one(self) -> None:
        self.state.mkdir()
        cursor_path = self.state / "journal.cursor"
        self.journal_environment(FAKE_JOURNAL_CATCH_UP=self.environment["FAKE_JOURNAL_ENTRIES"],
                                 FAKE_JOURNAL_ENTRIES="[]")
        cursor_path.write_text("s=old\n")
        journal = mt.Journal(str(self.fake), cursor_path)
        self.assertEqual(len(self.drain(journal, calls=2)), len(json.loads(self.environment["FAKE_JOURNAL_ENTRIES"])))
        self.assertTrue(journal.cursor.startswith("s=fake;i="))
        calls = self.journal_calls()
        self.assertEqual(calls[0]["argv"][:5], ["--output=json", "--no-pager", "--quiet", "--after-cursor", "s=old"])
        self.assertEqual(calls[1]["argv"][:6], ["--follow", "--output=json", "--no-pager", "--quiet",
                                                "--after-cursor", journal.cursor])
        journal.save_cursor()
        self.assertEqual(cursor_path.read_text().strip(), journal.cursor)

        # Nothing after the saved position: the catch-up exits at once without output, and the cursor stays.
        os.environ["FAKE_JOURNAL_CATCH_UP"] = "[]"
        saved = journal.cursor
        journal = mt.Journal(str(self.fake), cursor_path)
        self.assertEqual(self.drain(journal, calls=4), [])
        self.assertEqual(journal.cursor, saved)
        self.assertEqual(self.journal_calls()[3]["argv"][:6], ["--follow", "--output=json", "--no-pager", "--quiet",
                                                               "--after-cursor", saved])

        # journalctl refuses a malformed cursor at once with an error; the next start follows from the end.
        cursor_path.write_text("bogus\n")
        journal = mt.Journal(str(self.fake), cursor_path)
        self.assertEqual(self.drain(journal, calls=5), [])
        self.assertIsNone(journal.cursor)
        self.assertEqual(journal.state, "exited: 1")

    def test_a_catch_up_that_fails_for_another_reason_keeps_its_cursor(self) -> None:
        self.state.mkdir()
        cursor_path = self.state / "journal.cursor"
        entries = [{"MESSAGE": "after the failures", "__CURSOR": "s=new"}]
        failures = [{"fail": 1, "stderr": "Failed to open journal: Too many open files\n"},
                    {"fail": -signal.SIGKILL}, {"fail": 127}, {"fail": 1}]
        self.journal_environment(FAKE_JOURNAL_PLAN=json.dumps(failures + [{"entries": entries}, {"entries": []}]))
        cursor_path.write_text("s=old\n")
        with mock.patch.object(mt, "JOURNAL_RESTART_DELAY", 0.0):
            journal = mt.Journal(str(self.fake), cursor_path)
            states = []
            for calls in range(1, len(failures) + 1):
                self.assertEqual(self.drain(journal, calls=calls), [])
                states.append(journal.state)
                self.assertEqual(journal.cursor, "s=old")
            self.assertEqual(states, ["exited: 1", "exited: -9", "exited: 127", "exited: 1"])
            self.assertEqual([entry["MESSAGE"] for entry in self.drain(journal, calls=len(failures) + 2)],
                             ["after the failures"])
        calls = self.journal_calls()
        for call in calls[:len(failures) + 1]:  # every catch-up starts from the saved position
            self.assertEqual(call["argv"][:5], ["--output=json", "--no-pager", "--quiet", "--after-cursor", "s=old"])
        self.assertEqual(calls[-1]["argv"][:6], ["--follow", "--output=json", "--no-pager", "--quiet",
                                                 "--after-cursor", "s=new"])
        self.assertEqual(list(self.state.iterdir()), [cursor_path])  # the error output leaves no file

    def test_the_saved_position_never_passes_an_entry_that_was_not_handled(self) -> None:
        self.state.mkdir()
        cursor_path = self.state / "journal.cursor"
        cursor_path.write_text("s=saved\n")
        entries = [{"MESSAGE": message, "__CURSOR": f"s=c{index}", "__REALTIME_TIMESTAMP": str(index)}
                   for index, message in enumerate(("first", "second", "third"), 1)]
        self.journal_environment(FAKE_JOURNAL_PLAN=json.dumps([{"entries": entries}, {"entries": []}]))
        journal = mt.Journal(str(self.fake), cursor_path)
        received = self.drain(journal, calls=2, handle=False)
        self.assertEqual(len(received), 3)
        # The child continues after the last entry read, but a restart resumes after the last one handled.
        self.assertEqual(self.journal_calls()[1]["argv"][4:6], ["--after-cursor", "s=c3"])
        journal.save_cursor()
        self.assertEqual(cursor_path.read_text().strip(), "s=saved")
        journal.mark_handled(received[0])
        journal.mark_handled(received[1])
        journal.save_cursor()
        self.assertEqual(cursor_path.read_text().strip(), "s=c2")

    def test_a_line_cut_short_by_a_dying_journalctl_loses_no_entry(self) -> None:
        self.state.mkdir()
        entries = [{"MESSAGE": message, "__CURSOR": f"s=c{index}", "__REALTIME_TIMESTAMP": str(index)}
                   for index, message in enumerate(("first", "second", "third"), 1)]
        plan = [
            {"entries": entries[:1], "tail": json.dumps(entries[1])[:20]},  # dies in the middle of a line
            {"entries": entries[1:]},  # the catch-up from the last complete entry
            {"entries": []},  # the follow call
        ]
        self.journal_environment(FAKE_JOURNAL_PLAN=json.dumps(plan))
        with mock.patch.object(mt, "JOURNAL_RESTART_DELAY", 0):
            journal = mt.Journal(str(self.fake), self.state / "journal.cursor")
            received = self.drain(journal, calls=3)
        self.assertEqual([entry["MESSAGE"] for entry in received], ["first", "second", "third"])
        calls = self.journal_calls()
        self.assertEqual(calls[1]["argv"][3:5], ["--after-cursor", "s=c1"])  # the catch-up
        self.assertEqual(calls[2]["argv"][4:6], ["--after-cursor", "s=c3"])  # the follow

    def test_missing_journalctl_still_samples(self) -> None:
        command = self.command()
        command[command.index("--journalctl") + 1] = str(self.base / "no-such-journalctl")
        process = self.start(command)
        self.wait_for(process, lambda: self.journal_state() == "unavailable: FileNotFoundError",
                      "a sample reporting journalctl unavailable")
        self.stop(process)
        self.assertEqual(list((self.state / "incidents").iterdir()), [])

    def test_an_empty_journalctl_command_is_reported_like_a_missing_one(self) -> None:
        command = self.command()
        command[command.index("--journalctl") + 1] = ""
        process = self.start(command)
        self.wait_for(process, lambda: (self.journal_state() or "").startswith("unavailable: "),
                      "a sample reporting journalctl unavailable")
        self.stop(process)

    def test_unavailable_or_unrecognized_oomd_snapshot_does_not_prevent_sampling(self) -> None:
        for command, output, expected in (
            (str(self.base / "no-oomctl"), None, "FileNotFoundError"),
            (str(self.fixture.oomctl), "raise SystemExit(7)\n", "exit: 7"),
            (str(self.fixture.oomctl), "print('UNRELATED-SENTINEL')\n", "unrecognized oomctl output"),
        ):
            with self.subTest(expected=expected):
                if output is not None:
                    write(self.fixture.oomctl, f"#!{sys.executable}\n" + output)
                result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "sample",
                    *self.fixture.options("--oomctl", command)], text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                sample = json.loads(result.stdout)
                self.assertEqual(sample["metadata"]["oomd"]["effective"]["unavailable"], expected)
                self.assertEqual(sample["fast"]["kind"], "fast")
                self.assertNotIn("UNRELATED-SENTINEL", result.stdout)
                self.assertFalse(self.state.exists())

    def test_sample_and_report_commands(self) -> None:
        result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "sample", *self.fixture.options()],
                                env=self.environment, text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        sample = json.loads(result.stdout)
        self.assertEqual((sample["fast"]["kind"], sample["slow"]["kind"]), ("fast", "slow"))
        self.assertEqual(sample["metadata"]["reason"], "sample")
        for secret in SECRETS:
            self.assertNotIn(secret, result.stdout)
        self.assertFalse(self.state.exists())

        report = [sys.executable, "-I", "-B", str(SCRIPT), "report", "--state-dir", str(self.state)]
        result = subprocess.run(report, text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 1)
        process = self.start(environment=self.environment | {"FAKE_JOURNAL_ENTRIES": "[]"})
        self.wait_for(process, (self.state / "latest.json").exists, "a first sample")  # after the first slow one
        self.stop(process)
        result = subprocess.run(report, text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("oomd swap gate armed", result.stdout)
        self.assertIn("swap-mode choice now: user.slice/", result.stdout)
        self.assertIn("T7 kill records: 0", result.stdout)

    def test_report_and_record_stay_clean_with_hostile_names(self) -> None:
        target: str | bytes = "/usr/bin/evil\x1b]0;TITLE\x07\x1b[2J"
        if sys.platform == "linux":
            target = os.fsencode(target) + b"\xff"
            hostile = self.fixture.apps / "app-com.anthropic.Claude-\x1b[2J.scope"
            self.fixture.cgroup_files(hostile, 1 << 30, 30 << 30, [150])
        else:
            write(self.fixture.claude / "cgroup.procs", "".join(f"{pid}\n" for pid in [*CLAUDE_PROCESSES, 150]))
        self.fixture.process(150, None, 1, 9_000_000, 0)
        os.symlink(target, self.fixture.proc / "150" / "exe")
        process = self.start(environment=self.environment | {"FAKE_JOURNAL_ENTRIES": "[]"})
        self.wait_for(process, (self.state / "latest.json").exists, "a first sample")  # after the first slow one
        self.stop(process)
        result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "report", "--state-dir", str(self.state)],
                                capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"evil\\x1b]0;TITLE\\x07", result.stdout)
        for byte in (b"\x1b", b"\x07", b"\x9b"):
            self.assertNotIn(byte, result.stdout)

        def strings(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    yield key
                    yield from strings(item)
            elif isinstance(value, list):
                for item in value:
                    yield from strings(item)
            elif isinstance(value, str):
                yield value

        records = [json.loads((self.state / "latest.json").read_text()),
                   *mt.read_samples(self.state / "samples", 0, time.time() + 60)]
        for text in strings(records):
            self.assertFalse(any("\ud800" <= character <= "\udfff" for character in text), repr(text))

    def test_invalid_options_are_refused(self) -> None:
        for option in ("--interval", "--slow-every", "--retention-days", "--max-incidents"):
            result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "run", option, "0"],
                                    text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 2, option)


class DeploymentTests(unittest.TestCase):
    def test_unit_runs_the_collector_and_only_the_collector(self) -> None:
        unit = UNIT.read_text()
        lines = [line for line in unit.splitlines() if line and not line.startswith("#")]
        self.assertIn('ExecStart="%h/.local/bin/memory-telemetry" run', lines)
        self.assertEqual([line for line in lines if line.startswith("Exec")],
                         ['ExecStart="%h/.local/bin/memory-telemetry" run'])
        for line in ("StateDirectory=memory-telemetry", "StateDirectoryMode=0700", "WantedBy=default.target",
                     "NoNewPrivileges=yes", "MemorySwapMax=0"):
            self.assertIn(line, lines)
        self.assertEqual(WANTS.read_text().strip(), "../memory-telemetry.service")
        source = SCRIPT.read_text()
        # The collector opens no argv, environment or comm file and signals no process by PID.
        self.assertIsNone(re.search(r"[\"'/](cmdline|environ|comm)[\"']", source))
        self.assertNotIn("os.kill", source)

    @unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
    def test_chezmoi_installs_an_executable_and_an_enabled_unit_without_starting_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, home = root / "source", root / "home"
            home.mkdir()
            (root / "chezmoi.toml").write_text("")
            for path in (SCRIPT, UNIT, WANTS):
                target = source / path.relative_to(ROOT / "home")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            environment = os.environ | {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")}
            result = subprocess.run(
                [shutil.which("chezmoi"), "--source", str(source), "--destination", str(home),
                 "--config", str(root / "chezmoi.toml"), "--cache", str(root / "cache"),
                 "--persistent-state", str(root / "state.boltdb"), "--no-tty", "apply", "--force"],
                env=environment, text=True, capture_output=True, timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = home / ".local/bin/memory-telemetry"
            self.assertTrue(os.access(installed, os.X_OK))
            self.assertEqual(installed.read_bytes(), SCRIPT.read_bytes())
            wants = home / ".config/systemd/user/default.target.wants/memory-telemetry.service"
            self.assertEqual(os.readlink(wants), "../memory-telemetry.service")
            self.assertEqual(wants.resolve(), (home / ".config/systemd/user/memory-telemetry.service").resolve())
            self.assertFalse((home / ".local/state/memory-telemetry").exists())


if __name__ == "__main__":
    unittest.main()
