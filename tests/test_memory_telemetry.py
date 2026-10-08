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

    def process(self, pid: int, exe: str | None, ppid: int, anon: int, swap: int) -> None:
        folder = self.proc / str(pid)
        write(folder / "status", (
            f"Name:\tCOMM-SENTINEL\nPid:\t{pid}\nPPid:\t{ppid}\nVmRSS:\t{anon + 10} kB\n"
            f"RssAnon:\t{anon} kB\nRssFile:\t10 kB\nRssShmem:\t0 kB\nVmSwap:\t{swap} kB\n"
        ))
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

    def sources(self):
        return mt.Sources(self.proc, self.sys, self.config, UID)

    def options(self, *extra: str) -> list[str]:
        return ["--proc-root", str(self.proc), "--sys-root", str(self.sys), "--config-root", str(self.config), *extra]


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
            self.assertEqual(mt.oomd_swap_used_limit(config), (0.9, "default"))
            write(config / "usr/lib/systemd/oomd.conf", "[OOM]\nSwapUsedLimit=50%\n")
            write(config / "etc/systemd/oomd.conf", "[OOM]\nSwapUsedLimit=80%\n[Other]\nSwapUsedLimit=10%\n")
            self.assertEqual(mt.oomd_swap_used_limit(config), (0.8, "etc/systemd/oomd.conf"))
            # A drop-in in /etc masks the same name in /usr/lib; later names win.
            write(config / "usr/lib/systemd/oomd.conf.d/50-a.conf", "[OOM]\nSwapUsedLimit=60%\n")
            write(config / "etc/systemd/oomd.conf.d/50-a.conf", "[OOM]\nSwapUsedLimit=70%\n")
            self.assertEqual(mt.oomd_swap_used_limit(config), (0.7, "etc/systemd/oomd.conf.d/50-a.conf"))
            write(config / "run/systemd/oomd.conf.d/60-b.conf", "[OOM]\nSwapUsedLimit=65%\n")
            self.assertEqual(mt.oomd_swap_used_limit(config), (0.65, "run/systemd/oomd.conf.d/60-b.conf"))
            write(config / "run/systemd/oomd.conf.d/70-c.conf", "[OOM]\nSwapUsedLimit=\n")
            self.assertEqual(mt.oomd_swap_used_limit(config), (0.9, "default"))

    def test_kernel_oom_lines_lose_the_task_name(self) -> None:
        lines = {
            "COMM-SENTINEL x invoked oom-killer: gfp_mask=0x140cca, order=0, oom_score_adj=300":
                "(task) invoked oom-killer: gfp_mask=0x140cca, order=0, oom_score_adj=300",
            "Out of memory: Killed process 4242 (COMM-SENTINEL) total-vm:10kB, anon-rss:5kB, oom_score_adj:300":
                "Out of memory: Killed process 4242 (task) total-vm:10kB, anon-rss:5kB, oom_score_adj:300",
            "oom-kill:constraint=CONSTRAINT_MEMCG,task_memcg=/user.slice/x.scope,task=COMM-SENTINEL,pid=4242,uid=1000":
                "oom-kill:constraint=CONSTRAINT_MEMCG,task_memcg=/user.slice/x.scope,task=(task),pid=4242,uid=1000",
            "oom_reaper: reaped process 4242 (COMM-SENTINEL), now anon-rss:0kB":
                "oom_reaper: reaped process 4242 (task), now anon-rss:0kB",
        }
        for line, expected in lines.items():
            self.assertEqual(mt.redact_kernel(line), expected)
        # The rest of the kernel's OOM report lists every task by name; it is dropped.
        self.assertIsNone(mt.redact_kernel("[   4242]  1000  4242  1234  567  0  300 COMM-SENTINEL"))


class SampleTests(FixtureCase):
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
                         [f"user-{UID}.slice", "app.slice", "app-com.anthropic.Claude-100.scope"])
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
        sample, watched = mt.slow_sample(sources, list(mt.DEFAULT_WATCH),
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
        self.assertEqual(trees, {"claude[110]": 3, "codex[113]": 2, "(no agent)": 4})
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
        first, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH), roots, 50.0, "boot", None)
        shutil.rmtree(self.fixture.chromium)
        second, watched = mt.slow_sample(sources, list(mt.DEFAULT_WATCH), roots, 110.0, "boot", first)
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
        slow, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH), ["system.slice"], 2.0, None, None)
        self.assertEqual(slow["unavailable"]["proc:meminfo"], "FileNotFoundError")
        self.assertEqual(slow["unavailable"]["sys:fs/cgroup/system.slice"], "FileNotFoundError")
        self.assertEqual(slow["swap_holders"]["candidates"], 0)
        # A process that exits between the listing and its status read is skipped.
        shutil.rmtree(self.fixture.proc / "111")
        self.assertEqual(slow["t9"]["app-com.anthropic.Claude-100.scope"]["processes"], len(CLAUDE_PROCESSES))
        slow, _ = mt.slow_sample(sources, list(mt.DEFAULT_WATCH), [], 3.0, None, None)
        self.assertEqual(slow["t9"]["app-com.anthropic.Claude-100.scope"]["processes"], len(CLAUDE_PROCESSES) - 1)

    def test_ranked_folds_the_tail(self) -> None:
        processes = [mt.Process(pid, 0, f"tool{pid}", f"/bin/tool{pid}", pid, 0, 0, 0)
                     for pid in range(1, mt.TOP_ENTRIES + 6)]
        result = mt.attribute(processes)
        self.assertEqual(len(result["classes"]), mt.TOP_ENTRIES + 1)
        rest = result["classes"][-1]
        self.assertEqual((rest["exe"], rest["groups"], rest["processes"]), ("(rest)", 5, 5))
        self.assertEqual(result["classes"][0]["exe"], f"tool{mt.TOP_ENTRIES + 5}")


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


def journal_entry(t: float, message: str, **fields: str) -> dict:
    return {"__REALTIME_TIMESTAMP": str(int(t * 1e6)), "__CURSOR": f"s=fixture;t={int(t * 1e6)}",
            "MESSAGE": message, "_CMDLINE": "/usr/lib/systemd/systemd-oomd CMDLINE-SENTINEL-55d0",
            "_COMM": "COMM-SENTINEL", **fields}


OOMD_KILL_KINDS = ["oomd-kill", "oomd", "oomd-kill", "unit-oomd-kill"]


def oomd_kill_entries(t0: float, scope: str) -> list[dict]:
    oomd = {"_SYSTEMD_UNIT": "systemd-oomd.service", "_TRANSPORT": "journal", "_BOOT_ID": "b" * 32}
    return [
        journal_entry(t0, "Considered 159 cgroups for killing, top candidates were:", **oomd),
        journal_entry(t0, f"        Path: /user.slice/{scope}", **oomd),
        journal_entry(t0 + 0.05, f"Marked /user.slice/{scope} for killing due to memory used (1) / total (2) and "
                                 "swap used (3) / total (4) being more than 90.00%", **oomd),
        journal_entry(t0 + 1.1, f"{scope}: systemd-oomd killed some process(es) in this unit.",
                      MESSAGE_ID=mt.MESSAGE_UNIT_OOMD_KILL, USER_UNIT=scope, _SYSTEMD_UNIT=f"user@{UID}.service"),
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
        record = json.loads(files[0].read_text())
        self.assertTrue(record["id"].endswith("Z-oomd-kill"))
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

    def test_kernel_oom_opens_a_redacted_record_and_records_are_bounded(self) -> None:
        incidents = self.incidents(max_files=2)
        for index in range(4):
            t = self.t0 - 600 + index * 120
            incidents.handle(journal_entry(t, "COMM-SENTINEL invoked oom-killer: gfp_mask=0x0", _TRANSPORT="kernel"))
            incidents.handle(journal_entry(t + 0.1, "[ 4242] 1000 4242 COMM-SENTINEL", _TRANSPORT="kernel"))
            incidents.handle(journal_entry(t + 0.2, "Memory cgroup out of memory: Killed process 4242 (COMM-SENTINEL) "
                                                    "total-vm:1kB", _TRANSPORT="kernel"))
            incidents.handle(journal_entry(
                t + 0.3, "x.scope: A process of this unit has been killed by the OOM killer.",
                MESSAGE_ID=mt.MESSAGE_UNIT_OOM, USER_UNIT="x.scope"))
        incidents.finalize()
        files = sorted((self.root / "incidents").glob("*.json"))
        self.assertEqual(len(files), 2)
        record = json.loads(files[-1].read_text())
        self.assertEqual([event["kind"] for event in record["events"]], ["kernel-oom", "kernel-oom", "unit-oom-kill"])
        for path in files:
            for secret in SECRETS:
                self.assertNotIn(secret, path.read_text())


FAKE_JOURNALCTL = r'''#!{python}
import json, os, sys, time
log = os.environ["FAKE_JOURNAL_LOG"]
with open(log, "a") as handle:
    handle.write(json.dumps({{"pid": os.getpid(), "argv": sys.argv[1:]}}) + "\n")
time.sleep(float(os.environ.get("FAKE_JOURNAL_DELAY", "1.0")))
t = int(time.time() * 1e6)
for offset, fields in enumerate(json.loads(os.environ.get("FAKE_JOURNAL_ENTRIES", "[]"))):
    fields["__REALTIME_TIMESTAMP"] = str(t + offset)
    fields["__CURSOR"] = "s=fake;i=%d" % (t + offset)
    print(json.dumps(fields), flush=True)
time.sleep(float(os.environ.get("FAKE_JOURNAL_LINGER", "60")))
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
        entries = [entry | {"__REALTIME_TIMESTAMP": "0"} for entry in oomd_kill_entries(0, scope)]
        entries.append({"_TRANSPORT": "kernel", "MESSAGE": "[ 4242] 1000 COMM-SENTINEL ARGV-SENTINEL-7f3a"})
        self.environment = os.environ | {
            "FAKE_JOURNAL_LOG": str(self.log),
            "FAKE_JOURNAL_ENTRIES": json.dumps(entries),
            "PYTHONDONTWRITEBYTECODE": "1",
            "MEMORY_TELEMETRY_FIXTURE": "ENVIRON-SENTINEL-91c2",
        }

    def command(self, *extra: str) -> list[str]:
        return [sys.executable, "-I", "-B", str(SCRIPT), "run", "--state-dir", str(self.state),
                *self.fixture.options(), "--interval", "0.2", "--slow-every", "2", "--window", "30",
                "--grace", "0.5", "--journalctl", str(self.fake), *extra]

    def journal_calls(self) -> list[dict]:
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def assert_child_gone(self, pid: int) -> None:
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)  # existence probe; sends no signal

    def test_run_records_samples_and_a_kill_record_without_touching_sources(self) -> None:
        before = tree_digest(self.fixture.root)
        result = subprocess.run(self.command("--duration", "3"), env=self.environment, text=True,
                                capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(tree_digest(self.fixture.root), before)

        latest = json.loads((self.state / "latest.json").read_text())
        self.assertEqual((latest["schema"], latest["kind"]), (mt.SCHEMA, "fast"))
        self.assertEqual(latest["oomd"], {"swap_used_limit": 0.9, "source": "etc/systemd/oomd.conf"})
        self.assertEqual(latest["collector"]["journal"], "following")
        self.assertIn("per_s", latest["t3"])
        samples = mt.read_samples(self.state / "samples", 0, time.time() + 60)
        kinds = [sample["kind"] for sample in samples]
        self.assertGreaterEqual(kinds.count("fast"), 10)
        self.assertGreaterEqual(kinds.count("slow"), 5)
        self.assertEqual(oct(self.state.stat().st_mode & 0o777), "0o700")
        for path in (self.state / "latest.json", *(self.state / "samples").iterdir()):
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600", path)

        records = list((self.state / "incidents").glob("*.json"))
        self.assertEqual(len(records), 1)
        record = json.loads(records[0].read_text())
        self.assertTrue(record["finalized"])
        self.assertEqual([event["kind"] for event in record["events"]], OOMD_KILL_KINDS)
        self.assertGreaterEqual(len(record["window"]["fast"]), 3)
        self.assertGreaterEqual(len(record["window"]["slow"]), 1)
        self.assertIn("app-com.anthropic.Claude-100.scope", record["t9"]["latest"])
        self.assertTrue(record["following"]["fast"])

        calls = self.journal_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["argv"], ["--follow", "--output=json", "--no-pager", "--quiet", "--lines=0",
                                            *mt.JOURNAL_MATCHES])
        self.assert_child_gone(calls[0]["pid"])
        cursor = (self.state / "journal.cursor").read_text().strip()
        self.assertTrue(cursor.startswith("s=fake;i="))

        everything = "".join(path.read_text(errors="replace") for path in self.state.rglob("*")
                             if path.is_file() and not path.name.endswith(".gz"))
        everything += "".join(gzip.open(path, "rt").read() for path in self.state.rglob("*.gz"))
        for secret in SECRETS:
            self.assertNotIn(secret, everything)
        self.assertNotIn("/usr/lib/claude-desktop", everything)

        # A restart resumes after the saved cursor.
        result = subprocess.run(self.command("--duration", "0.5"),
                                env=self.environment | {"FAKE_JOURNAL_ENTRIES": "[]"},
                                text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.journal_calls()
        self.assertEqual(calls[1]["argv"][4:6], ["--after-cursor", cursor])
        self.assert_child_gone(calls[1]["pid"])

    def test_sigterm_stops_the_collector_and_its_journalctl(self) -> None:
        process = subprocess.Popen(self.command(), env=self.environment | {"FAKE_JOURNAL_ENTRIES": "[]"},
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 30
        while not (self.log.exists() and (self.state / "latest.json").exists()) and time.monotonic() < deadline:
            time.sleep(0.05)
        process.send_signal(signal.SIGTERM)
        _, errors = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 0, errors)
        self.assert_child_gone(self.journal_calls()[0]["pid"])

    def test_journal_keeps_its_cursor_unless_journalctl_exits_silently(self) -> None:
        self.state.mkdir()
        cursor_path = self.state / "journal.cursor"
        # Journal starts journalctl with this process's environment.
        environment = mock.patch.dict(os.environ, self.environment | {"FAKE_JOURNAL_DELAY": "0",
                                                                      "FAKE_JOURNAL_LINGER": "0"})
        environment.start()
        self.addCleanup(environment.stop)

        def drain(journal) -> list[dict]:
            entries: list[dict] = []
            deadline = time.monotonic() + 20
            while not journal.state.startswith("exited") and time.monotonic() < deadline:
                entries += journal.poll(0.2)
            return entries

        cursor_path.write_text("s=old\n")
        journal = mt.Journal(str(self.fake), cursor_path)
        entries = drain(journal)
        self.assertEqual(len(entries), 5)
        self.assertTrue(journal.cursor.startswith("s=fake;i="))
        journal.save_cursor()
        self.assertEqual(cursor_path.read_text().strip(), journal.cursor)

        os.environ["FAKE_JOURNAL_ENTRIES"] = "[]"
        journal = mt.Journal(str(self.fake), cursor_path)
        self.assertEqual(drain(journal), [])
        self.assertIsNone(journal.cursor)  # resumes from the journal's end next time
        self.assertEqual([call["argv"][4] for call in self.journal_calls()], ["--after-cursor", "--after-cursor"])

    def test_missing_journalctl_still_samples(self) -> None:
        command = self.command("--duration", "0.6")
        command[command.index("--journalctl") + 1] = str(self.base / "no-such-journalctl")
        result = subprocess.run(command, env=self.environment, text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        latest = json.loads((self.state / "latest.json").read_text())
        self.assertEqual(latest["collector"]["journal"], "unavailable: FileNotFoundError")
        self.assertEqual(list((self.state / "incidents").iterdir()), [])

    def test_sample_and_report_commands(self) -> None:
        result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "sample", *self.fixture.options()],
                                env=self.environment, text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        sample = json.loads(result.stdout)
        self.assertEqual((sample["fast"]["kind"], sample["slow"]["kind"]), ("fast", "slow"))
        for secret in SECRETS:
            self.assertNotIn(secret, result.stdout)
        self.assertFalse(self.state.exists())

        report = [sys.executable, "-I", "-B", str(SCRIPT), "report", "--state-dir", str(self.state)]
        result = subprocess.run(report, text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 1)
        subprocess.run(self.command("--duration", "1"), env=self.environment | {"FAKE_JOURNAL_ENTRIES": "[]"},
                       check=True, capture_output=True, timeout=60)
        result = subprocess.run(report, text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("oomd swap gate armed", result.stdout)
        self.assertIn("swap-mode choice now: user.slice/", result.stdout)
        self.assertIn("T7 kill records: 0", result.stdout)

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
