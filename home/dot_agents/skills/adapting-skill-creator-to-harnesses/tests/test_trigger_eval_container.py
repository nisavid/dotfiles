"""Real kernel and CLI canaries; CI explicitly enables this Docker-only suite."""

from __future__ import annotations

import errno
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
from isolated_codex_runtime import DEFAULT_IMAGE, IsolatedCodexRuntime  # noqa: E402


ENABLED = os.environ.get("TRIGGER_EVAL_CONTAINER_TESTS") == "1"
TEST_IMAGE = DEFAULT_IMAGE + "-test"
SENTINEL = "CONTAINER_CANARY_SENTINEL"


class FixtureRuntime(IsolatedCodexRuntime):
    broker_command = ["python3", "-I", "/opt/trigger/container_fixture_broker.py"]


@unittest.skipUnless(ENABLED, "set TRIGGER_EVAL_CONTAINER_TESTS=1 to exercise real Docker isolation")
class TriggerEvalContainerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # An explicitly requested integration run must fail, not skip, when its
        # required kernel/runtime surface or prebuilt images are unavailable.
        if not shutil.which("docker"):
            raise AssertionError("TRIGGER_EVAL_CONTAINER_TESTS=1 requires Docker")
        for args in (["info"], ["image", "inspect", DEFAULT_IMAGE], ["image", "inspect", TEST_IMAGE]):
            result = subprocess.run(["docker", *args], text=True, capture_output=True, timeout=30)
            if result.returncode:
                raise AssertionError(f"Required Docker preflight failed: {' '.join(args)}\n{result.stderr}")

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="trigger-eval-canary-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.codex_home = self.root / "private-host-codex"
        self.codex_home.mkdir()
        self.credential = "fixture/broker-credential-" + self.root.name
        (self.codex_home / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": self.credential}), encoding="utf-8")
        self.host_file = self.root / "private-host-file"
        self.host_file.write_text("fixture/host-file-secret", encoding="utf-8")
        self.skill_path = self.root / "container-canary" / "SKILL.md"
        self.skill_path.parent.mkdir()
        self.skill_path.write_text(
            "---\nname: container-canary\ndescription: Use for the container canary.\n---\n"
            f"Read this body and answer exactly {SENTINEL}.\n",
            encoding="utf-8",
        )

    def runtime(self, *, fixture: bool = False) -> IsolatedCodexRuntime:
        cls = FixtureRuntime if fixture else IsolatedCodexRuntime
        return cls(codex_home=self.codex_home, skill_path=self.skill_path, image=TEST_IMAGE if fixture else DEFAULT_IMAGE)

    def assert_removed(self, runtime: IsolatedCodexRuntime) -> None:
        for kind, name in (("container", runtime.worker_name), ("container", runtime.broker_name), ("volume", runtime.volume_name)):
            result = subprocess.run(["docker", kind, "inspect", name], text=True, capture_output=True, timeout=15)
            self.assertNotEqual(result.returncode, 0, f"Leaked {kind}: {name}")

    def inspect(self, runtime: IsolatedCodexRuntime) -> dict:
        result = subprocess.run(["docker", "inspect", runtime.worker_name], text=True, capture_output=True, check=True, timeout=15)
        return json.loads(result.stdout)[0]

    def test_kernel_boundary_keeps_skill_readable_and_host_credentials_inaccessible(self) -> None:
        runtime = self.runtime()
        ambient = "fixture/ambient-credential-" + self.root.name
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ambient, "GH_TOKEN": ambient, "TRIGGER_CANARY_SECRET": ambient}):
            with runtime:
                inspected = self.inspect(runtime)
                host_config = inspected["HostConfig"]
                self.assertEqual(host_config["NetworkMode"], "none")
                self.assertTrue(host_config["ReadonlyRootfs"])
                self.assertFalse(host_config["Privileged"])
                self.assertNotEqual(host_config.get("PidMode"), "host")
                self.assertEqual(inspected["Config"]["User"], "1000:1000")
                self.assertIn("ALL", host_config["CapDrop"])
                self.assertIn("no-new-privileges", " ".join(host_config["SecurityOpt"]))
                self.assertFalse(any(mount["Type"] == "bind" for mount in inspected["Mounts"]))
                socket_mount = next(mount for mount in inspected["Mounts"] if mount["Destination"] == "/broker-socket")
                self.assertFalse(socket_mount["RW"])
                code = """
import errno, json, os, pathlib, socket, sys
proc = {}
for path in pathlib.Path('/proc').glob('[0-9]*/environ'):
    try:
        proc[str(path)] = path.read_bytes().decode(errors='replace')
    except OSError:
        pass
network_errno = None
with socket.socket() as sock:
    sock.settimeout(2)
    try:
        sock.connect(('1.1.1.1', 443))
    except OSError as exc:
        network_errno = exc.errno
try:
    pathlib.Path('/opt/trigger/should-not-write').write_text('blocked')
    root_write_blocked = False
except OSError:
    root_write_blocked = True
print(json.dumps({
    'uid': os.getuid(), 'environment': dict(os.environ), 'proc': proc,
    'skill': pathlib.Path('/home/test/.codex/skills/container-canary/SKILL.md').read_text(),
    'host_file_visible': pathlib.Path(sys.argv[1]).exists(),
    'host_auth_visible': pathlib.Path(sys.argv[2]).exists(),
    'runtime_auth_present': pathlib.Path('/home/test/.codex/auth.json').exists(),
    'interfaces': sorted(p.name for p in pathlib.Path('/sys/class/net').iterdir()),
    'network_errno': network_errno, 'root_write_blocked': root_write_blocked,
}))
"""
                result = runtime.run(["python3", "-c", code, str(self.host_file), str(self.codex_home / "auth.json")], timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                observed = json.loads(result.stdout)
                self.assertEqual(observed["uid"], 1000)
                self.assertIn(SENTINEL, observed["skill"])
                self.assertFalse(observed["host_file_visible"])
                self.assertFalse(observed["host_auth_visible"])
                self.assertFalse(observed["runtime_auth_present"])
                self.assertTrue(observed["root_write_blocked"])
                self.assertEqual(observed["interfaces"], ["lo"])
                self.assertIn(observed["network_errno"], (errno.ENETUNREACH, errno.EHOSTUNREACH))
                self.assertNotIn(self.credential, result.stdout)
                self.assertNotIn(ambient, result.stdout)
                self.assertNotIn("TRIGGER_CANARY_SECRET", observed["environment"])
        self.assert_removed(runtime)

    def test_exception_removes_all_runtime_resources(self) -> None:
        runtime = self.runtime()
        with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
            with runtime:
                raise RuntimeError("synthetic failure")
        self.assert_removed(runtime)

    def test_timeout_kills_tool_descendants_and_removes_all_runtime_resources(self) -> None:
        runtime = self.runtime()
        with self.assertRaises(subprocess.TimeoutExpired):
            with runtime:
                runtime.run(["python3", "-c", "import subprocess,time; subprocess.Popen(['sleep','300']); time.sleep(300)"], timeout=1)
        self.assert_removed(runtime)

    def test_sigterm_of_controller_removes_live_tools_broker_and_volume(self) -> None:
        runtime = self.runtime()
        code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from isolated_codex_runtime import IsolatedCodexRuntime
runtime = IsolatedCodexRuntime(codex_home=Path(sys.argv[2]), skill_path=Path(sys.argv[3]))
runtime.worker_name, runtime.broker_name, runtime.volume_name = sys.argv[4:7]
with runtime:
    runtime.run(['python3', '-c', "import subprocess,time; from pathlib import Path; subprocess.Popen(['sleep','300']); Path('/work/tool-started').touch(); time.sleep(300)"], timeout=300)
"""
        child = subprocess.Popen([
            sys.executable, "-B", "-c", code, str(SKILL_DIR / "scripts"),
            str(self.codex_home), str(self.skill_path), runtime.worker_name,
            runtime.broker_name, runtime.volume_name,
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and child.poll() is None:
                started = subprocess.run([
                    "docker", "exec", runtime.worker_name, "test", "-f", "/work/tool-started",
                ], capture_output=True, timeout=5)
                if started.returncode == 0:
                    break
                time.sleep(0.1)
            else:
                self.fail("Controller did not start the real tool and descendant")
            child.send_signal(signal.SIGTERM)
            stdout, stderr = child.communicate(timeout=60)
            self.assertEqual(child.returncode, 128 + signal.SIGTERM, stdout + stderr)
            self.assert_removed(runtime)
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)
            # Keep a failed regression from leaking fixtures on the CI host.
            subprocess.run(["docker", "rm", "--force", runtime.worker_name, runtime.broker_name], capture_output=True, timeout=15)
            subprocess.run(["docker", "volume", "rm", runtime.volume_name], capture_output=True, timeout=15)

    def test_next_probe_has_no_previous_session_files(self) -> None:
        first = self.runtime()
        with first:
            result = first.run(["python3", "-c", "from pathlib import Path; Path('/home/test/stale-session').write_text('previous')"], timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_removed(first)
        second = self.runtime()
        with second:
            result = second.run(["python3", "-c", "from pathlib import Path; assert not Path('/home/test/stale-session').exists()"], timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_removed(second)

    def test_native_codex_really_reads_skill_body_through_a_shell_tool(self) -> None:
        runtime = self.runtime(fixture=True)
        with runtime:
            result = runtime.run([
                "codex", "exec", "--json", "--ephemeral", "--skip-git-repo-check",
                "--sandbox", "danger-full-access", "-m", "gpt-6.1-sol",
                "Use the container-canary skill and report its marker.",
            ], timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
            commands = [event.get("item", {}) for event in events if event.get("item", {}).get("type") == "command_execution"]
            self.assertTrue(commands, result.stdout)
            self.assertTrue(any("SKILL.md" in item.get("command", "") and SENTINEL in item.get("aggregated_output", "") for item in commands), result.stdout)
            self.assertTrue(any(event.get("item", {}).get("type") == "agent_message" and SENTINEL in event["item"].get("text", "") for event in events), result.stdout)
        self.assert_removed(runtime)

    def test_acpx_codex_really_reads_skill_body_through_a_shell_tool(self) -> None:
        from acpx_trigger_eval import parse_acpx_output
        from trigger_eval_core import tool_call_diagnostic

        runtime = self.runtime(fixture=True)
        base = ["acpx", "--cwd", "/work", "--deny-all", "--non-interactive-permissions", "fail", "--no-terminal", "--format", "json", "--timeout", "60", "--model", "gpt-6.1-sol"]
        with runtime:
            setup = runtime.run([*base, "codex", "sessions", "new", "--name", "canary"], timeout=60)
            self.assertEqual(setup.returncode, 0, setup.stderr + setup.stdout)
            result = runtime.run([*base, "codex", "prompt", "-s", "canary", "Use the container-canary skill and report its marker."], timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            events, messages = parse_acpx_output(result.stdout)
            diagnostic = tool_call_diagnostic(events, ["/home/test/.codex/skills/container-canary/SKILL.md"])
            self.assertGreater(diagnostic["allowed_skill_read_count"], 0, result.stdout)
            self.assertEqual(diagnostic["disallowed_count"], 0, result.stdout)
            self.assertIn(SENTINEL, "".join(messages))
            closed = runtime.run([*base, "codex", "sessions", "close", "canary"], timeout=15)
            self.assertEqual(closed.returncode, 0, closed.stderr + closed.stdout)
        self.assert_removed(runtime)


if __name__ == "__main__":
    unittest.main()
