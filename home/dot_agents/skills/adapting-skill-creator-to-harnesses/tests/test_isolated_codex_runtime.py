"""Deterministic controller-boundary checks; no engine or credentials required."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import isolated_codex_runtime as runtime
from trigger_eval_core import write_probe_skill


class RetainedInput(io.StringIO):
    def close(self) -> None:
        self.saved = self.getvalue()
        super().close()


class EngineFixture:
    """Capture the actual subprocess boundary without executing any command."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.launches: list[tuple[list[str], dict]] = []
        self.broker = mock.Mock()
        self.broker.stdin = RetainedInput()
        self.broker.stdout = io.StringIO("READY\n")
        self.broker.wait.return_value = 0
        self.failure = None

    def run(self, argv: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.calls.append((list(argv), dict(kwargs)))
        if self.failure:
            result = self.failure(argv, kwargs)
            if result is not None:
                return result
        return subprocess.CompletedProcess(argv, 0, "", "")

    def popen(self, argv: list[str], **kwargs):
        self.launches.append((list(argv), dict(kwargs)))
        return self.broker

    def install(self, stack: ExitStack) -> None:
        stack.enter_context(mock.patch.object(runtime.shutil, "which", return_value="/trusted/docker"))
        stack.enter_context(mock.patch.object(runtime.subprocess, "run", side_effect=self.run))
        stack.enter_context(mock.patch.object(runtime.subprocess, "Popen", side_effect=self.popen))
        stack.enter_context(mock.patch.object(runtime.select, "select", return_value=([self.broker.stdout], [], [])))


class IsolatedCodexRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="trigger-runtime-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source-codex-home"
        self.source.mkdir()
        (self.source / "auth.json").write_text(json.dumps({
            "tokens": {
                "access_token": "synthetic-access-canary",
                "refresh_token": "synthetic-refresh-canary",
                "id_token": "synthetic-id-canary",
                "account_id": "synthetic-account",
            },
        }), encoding="utf-8")
        self.skill_path = write_probe_skill(
            self.root / "probe-home", name="fixture-skill", description="Use when testing a fixture.",
            marker="SYNTHETIC_SENTINEL", harness_label="test",
        )
        self.engine = EngineFixture()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.dict(os.environ, {
            "PATH": "/trusted/bin", "HOME": str(self.root / "operator-home"),
            "OPENAI_API_KEY": "ambient-key-canary", "GH_TOKEN": "ambient-github-canary",
            "SSH_AUTH_SOCK": "/synthetic/agent.sock", "NODE_OPTIONS": "ambient-node-canary",
        }, clear=True))
        self.engine.install(self.stack)

    def create_runtime(self, **kwargs) -> runtime.IsolatedCodexRuntime:
        return runtime.IsolatedCodexRuntime(
            codex_home=self.source, skill_path=self.skill_path, timeout=2, **kwargs,
        )

    def assert_resources_removed(self, probe: runtime.IsolatedCodexRuntime) -> None:
        commands = [argv[1:] for argv, _ in self.engine.calls]
        self.assertIn(["rm", "--force", probe.worker_name], commands)
        self.assertIn(["rm", "--force", probe.broker_name], commands)
        self.assertIn(["volume", "rm", probe.volume_name], commands)

    def test_worker_is_confined_and_has_no_host_mounts_or_ambient_credentials(self) -> None:
        with self.create_runtime() as probe:
            probe.run(["codex", "exec", "synthetic prompt"], timeout=2)
        worker = next(argv for argv, _ in self.engine.calls if "--detach" in argv)
        for option in ("--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user=1000:1000"):
            self.assertIn(option, worker)
        self.assertNotIn("--privileged", worker)
        self.assertNotIn("--network=host", worker)
        for argv, kwargs in self.engine.calls + self.engine.launches:
            self.assertNotIn("--volume", argv)
            self.assertNotIn("-v", argv)
            for index, arg in enumerate(argv):
                if arg == "--mount":
                    self.assertEqual(argv[index + 1].split(",")[0], "type=volume")
                    self.assertIn("src=" + probe.volume_name, argv[index + 1])
            serialized = json.dumps([argv, kwargs])
            for forbidden in ("ambient-key-canary", "ambient-github-canary", "ambient-node-canary", "/synthetic/agent.sock", "synthetic-access-canary", "synthetic-refresh-canary"):
                self.assertNotIn(forbidden, serialized)
            self.assertNotIn(str(self.source), json.dumps(argv))
        self.assert_resources_removed(probe)

    def test_only_access_credential_is_sent_over_broker_stdin(self) -> None:
        with self.create_runtime():
            pass
        credential = json.loads(self.engine.broker.stdin.saved)
        self.assertEqual(credential, {
            "kind": "chatgpt", "token": "synthetic-access-canary", "account_id": "synthetic-account",
        })
        self.assertNotIn("synthetic-refresh-canary", self.engine.broker.stdin.saved)
        self.assertNotIn("synthetic-id-canary", self.engine.broker.stdin.saved)
        self.assertEqual(len(self.engine.launches), 1)
        _, options = self.engine.launches[0]
        self.assertEqual(options["stdin"], subprocess.PIPE)
        self.assertEqual(options["stderr"], subprocess.DEVNULL)

    def test_api_key_authentication_never_exports_other_auth_fields(self) -> None:
        (self.source / "auth.json").write_text(json.dumps({
            "OPENAI_API_KEY": "synthetic-api-key", "irrelevant": "private-other-canary",
        }), encoding="utf-8")
        with self.create_runtime():
            pass
        self.assertEqual(json.loads(self.engine.broker.stdin.saved), {"kind": "api_key", "token": "synthetic-api-key"})

    def test_init_transfers_only_selected_probe_body_and_generated_config(self) -> None:
        (self.source / "config.toml").write_text("stale-source-config-canary", encoding="utf-8")
        stale_skill = self.skill_path.parent.parent / "stale-other-skill"
        stale_skill.mkdir()
        (stale_skill / "SKILL.md").write_text("stale-skill-canary", encoding="utf-8")
        (self.skill_path.parents[3] / "auth.json").write_text("stale-probe-auth-canary", encoding="utf-8")
        with self.create_runtime():
            pass
        init = next(kwargs["input"] for argv, kwargs in self.engine.calls if argv[-1] == "init")
        payload = json.loads(init)
        self.assertEqual(payload["skills"], [{"name": "fixture-skill", "content": self.skill_path.read_text(encoding="utf-8")}])
        self.assertIn("/home/probe/.codex/skills/fixture-skill/SKILL.md", payload["config"])
        for forbidden in ("stale-source-config-canary", "stale-skill-canary", "stale-probe-auth-canary", str(self.source)):
            self.assertNotIn(forbidden, init)

    def test_setup_failure_removes_worker_broker_and_volume(self) -> None:
        def fail_worker(argv, kwargs):
            if "--detach" in argv:
                return subprocess.CompletedProcess(argv, 125, "", "synthetic runtime failure")
        self.engine.failure = fail_worker
        probe = self.create_runtime()
        with self.assertRaises(runtime.IsolationError):
            probe.__enter__()
        self.assert_resources_removed(probe)
        self.engine.broker.wait.assert_called()

    def test_broker_readiness_timeout_does_not_launch_worker_and_cleans_up(self) -> None:
        probe = self.create_runtime()
        with mock.patch.object(runtime.select, "select", return_value=([], [], [])):
            with self.assertRaisesRegex(runtime.IsolationError, "did not become ready"):
                probe.__enter__()
        self.assertFalse(any("--detach" in argv for argv, _ in self.engine.calls))
        self.assert_resources_removed(probe)

    def test_command_timeout_destroys_runtime_before_propagating(self) -> None:
        def timeout_command(argv, kwargs):
            if "--workdir=/work" in argv:
                raise subprocess.TimeoutExpired(argv, 2, output="synthetic partial output")
        self.engine.failure = timeout_command
        with self.create_runtime() as probe:
            with self.assertRaises(subprocess.TimeoutExpired):
                probe.run(["codex", "exec", "fixture"], timeout=2)
            self.assert_resources_removed(probe)
            with self.assertRaisesRegex(runtime.IsolationError, "not active"):
                probe.run(["codex", "exec", "another fixture"], timeout=2)

    def test_nonzero_container_removal_is_reported_while_other_cleanup_continues(self) -> None:
        probe = self.create_runtime()
        probe.__enter__()
        def reject_worker_removal(argv, kwargs):
            if argv[1:] == ["rm", "--force", probe.worker_name]:
                return subprocess.CompletedProcess(argv, 1, "", "synthetic removal failure")
        self.engine.failure = reject_worker_removal
        with self.assertRaisesRegex(runtime.IsolationError, "cleanup failed") as caught:
            probe.close()
        self.assertIn(probe.worker_name, str(caught.exception))
        self.assert_resources_removed(probe)

    def test_command_is_unavailable_before_entering_or_after_exiting_runtime(self) -> None:
        probe = self.create_runtime()
        with self.assertRaisesRegex(runtime.IsolationError, "not active"):
            probe.run(["codex", "exec", "fixture"], timeout=2)
        with probe:
            pass
        count = len(self.engine.calls)
        with self.assertRaisesRegex(runtime.IsolationError, "not active"):
            probe.run(["codex", "exec", "fixture"], timeout=2)
        self.assertEqual(len(self.engine.calls), count)

    def test_missing_engine_fails_without_any_host_execution(self) -> None:
        with mock.patch.object(runtime.shutil, "which", return_value=None):
            with self.assertRaisesRegex(runtime.IsolationError, "will not fall back"):
                with self.create_runtime():
                    self.fail("unavailable engine must not enter runtime")
        self.assertEqual(self.engine.calls, [])
        self.assertEqual(self.engine.launches, [])

    def test_invalid_auth_errors_do_not_disclose_source_data(self) -> None:
        for invalid in (b'{"private":"sensitive-parser-canary",broken}', b'[]', b'{}', b'\xffinvalid-sensitive-canary'):
            with self.subTest(invalid=invalid):
                (self.source / "auth.json").write_bytes(invalid)
                with self.assertRaises(runtime.IsolationError) as caught:
                    runtime.load_credentials(self.source)
                self.assertNotIn("canary", str(caught.exception))
                self.assertNotIn(str(self.source), str(caught.exception))
        (self.source / "auth.json").unlink()
        with self.assertRaises(runtime.IsolationError):
            runtime.load_credentials(self.source)

    def test_invalid_runtime_skill_slug_is_rejected_before_credentials_or_startup(self) -> None:
        bad_skill = self.root / "bad_name" / "SKILL.md"
        bad_skill.parent.mkdir()
        bad_skill.write_text("invalid fixture", encoding="utf-8")
        with mock.patch.object(runtime, "load_credentials") as credentials:
            with self.assertRaisesRegex(runtime.IsolationError, "lowercase slug"):
                with runtime.IsolatedCodexRuntime(codex_home=self.source, skill_path=bad_skill):
                    self.fail("invalid slug accepted")
        credentials.assert_not_called()
        self.assertFalse(any("run" in argv or "create" in argv for argv, _ in self.engine.calls))


if __name__ == "__main__":
    unittest.main()
