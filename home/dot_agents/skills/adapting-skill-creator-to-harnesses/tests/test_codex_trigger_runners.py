"""Runner contracts using a synthetic body-reading runtime, never a live model."""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import acpx_trigger_eval as acpx
import codex_trigger_eval as native
from isolated_codex_runtime import IsolationError, PROBE_CODEX_HOME
from trigger_eval_core import write_probe_skill


class BodyReadingRuntime:
    instances: list["BodyReadingRuntime"] = []
    failure: Exception | None = None
    setup_returncode = 0

    def __init__(self, **kwargs) -> None:
        self.options = kwargs
        self.commands: list[list[str]] = []
        self.entered = False
        self.exited = False
        self.exit_type = None
        self.instances.append(self)

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, kind, *_):
        self.exited = True
        self.exit_type = kind

    def run(self, argv: list[str], *, timeout: int):
        self.commands.append(list(argv))
        if self.failure is not None:
            raise self.failure
        if argv[0] == "codex":
            text = self.response_for_prompt(argv[-1])
            output = {"type": "item.completed", "item": {"type": "agent_message", "text": text}}
            return subprocess.CompletedProcess(argv, 0, json.dumps(output) + "\n", "")
        events = []
        if "--model" in argv:
            events.append({"id": "model", "currentValue": argv[argv.index("--model") + 1]})
        if "reasoning_effort" in argv:
            events.append({"id": "reasoning_effort", "currentValue": argv[argv.index("reasoning_effort") + 1]})
        if "prompt" in argv:
            prompt = argv[-1]
            text = self.response_for_prompt(prompt)
            path = self.options["skill_path"]
            if path is not None and text != "SKILL_NOT_TRIGGERED":
                events.append({"method": "session/update", "params": {"update": {
                    "sessionUpdate": "tool_call", "kind": "read", "title": "Read synthetic skill",
                    "locations": [{"path": str(PROBE_CODEX_HOME / "skills" / path.parent.name / "SKILL.md")}],
                }}})
            events.append({"method": "session/update", "params": {"update": {
                "sessionUpdate": "agent_message", "content": {"type": "text", "text": text},
            }}})
        return subprocess.CompletedProcess(argv, self.setup_returncode, "\n".join(map(json.dumps, events)) + "\n", "")

    def response_for_prompt(self, prompt: str) -> str:
        path = self.options["skill_path"]
        if path is None:
            return "/work"
        if "fixture-negative" in prompt:
            return "SKILL_NOT_TRIGGERED"
        # The marker is deliberately obtained only from the generated body.
        text = path.read_text(encoding="utf-8")
        marker = re.search(r"exactly `([^`]+)`", text)
        if marker is None:
            raise AssertionError("synthetic skill body has no sentinel")
        return marker.group(1)


class CodexTriggerRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="trigger-runners-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source-codex-home"
        self.source.mkdir()
        fixture_auth = "fixture/source-auth-canary"
        self.auth_text = json.dumps({"OPENAI_API_KEY": fixture_auth})
        (self.source / "auth.json").write_text(self.auth_text, encoding="utf-8")
        BodyReadingRuntime.instances = []
        BodyReadingRuntime.failure = None
        BodyReadingRuntime.setup_returncode = 0
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(native, "IsolatedCodexRuntime", BodyReadingRuntime))
        self.stack.enter_context(mock.patch.object(acpx, "IsolatedCodexRuntime", BodyReadingRuntime))
        self.host_run = self.stack.enter_context(mock.patch.object(subprocess, "run", side_effect=AssertionError("runner attempted host subprocess")))

    def common(self, **overrides) -> dict:
        values = {
            "codex_home": self.source, "workspace": self.root / "results",
            "skill_name": "fixture-skill", "description": "Use when testing fixture-positive requests.",
            "effort": "high", "model": "fixture/model", "query_index": 0,
            "query": "fixture-positive request", "should_trigger": True,
            "timeout": 2, "keep_home": False,
            "container_runtime": "fixture/engine", "runtime_image": "fixture/image",
        }
        values.update(overrides)
        return values

    def run_native(self, **overrides):
        return native.run_one(codex_bin="codex", sandbox="read-only", **self.common(**overrides))

    def run_acpx(self, **overrides):
        return acpx.run_one(acpx_bin="acpx", strict_json=True, preflight={"ok": True}, **self.common(**overrides))

    def assert_safe_artifacts(self) -> None:
        self.assertEqual((self.source / "auth.json").read_text(encoding="utf-8"), self.auth_text)
        for path in (self.root / "results").rglob("*"):
            self.assertFalse(path.is_symlink(), str(path))
            if path.is_file():
                self.assertNotIn("fixture/source-auth-canary", path.read_text(encoding="utf-8"))
                self.assertNotEqual(path.name, "auth.json")

    def test_native_positive_and_negative_preserve_body_sentinel_and_effort(self) -> None:
        for positive in (True, False):
            with self.subTest(positive=positive):
                result = self.run_native(query="fixture-positive" if positive else "fixture-negative", should_trigger=positive)
                self.assertTrue(result["passed"])
                self.assertEqual(result["triggered"], positive)
                self.assertEqual(result["effort"], "high")
                self.assertNotIn(result["marker"], result["probe_prompt"])
                probe = BodyReadingRuntime.instances[-1]
                self.assertIn("model_reasoning_effort=high", probe.commands[0])
                self.assertIn("fixture/model", probe.commands[0])
                self.assertEqual(probe.options["engine"], "fixture/engine")
                self.assertEqual(probe.options["image"], "fixture/image")
                self.assertTrue(probe.exited)
                self.assertFalse((Path(result["run_dir"]) / "home").exists())
        self.assert_safe_artifacts()

    def test_acpx_positive_and_negative_preserve_body_read_and_config_contract(self) -> None:
        for positive in (True, False):
            with self.subTest(positive=positive):
                result = self.run_acpx(query="fixture-positive" if positive else "fixture-negative", should_trigger=positive)
                self.assertTrue(result["passed"], result)
                self.assertEqual(result["triggered"], positive)
                self.assertEqual(result["tool_calls"]["allowed_skill_read_count"], int(positive))
                self.assertEqual(result["tool_calls"]["disallowed_count"], 0)
                self.assertEqual(result["applied_config"], {"model": "fixture/model", "reasoning_effort": "high"})
                self.assertNotIn(result["marker"], result["probe_prompt"])
                self.assertFalse(result["codex_home"]["auth_linked"])
                self.assertTrue(BodyReadingRuntime.instances[-1].exited)
        self.assert_safe_artifacts()

    def test_acpx_default_effort_still_exits_runtime(self) -> None:
        result = self.run_acpx(effort=None)
        self.assertTrue(result["passed"])
        probe = BodyReadingRuntime.instances[-1]
        self.assertTrue(probe.exited)
        self.assertFalse(any("reasoning_effort" in command for command in probe.commands))

    def test_acpx_preflights_use_same_boundary_and_no_host_subprocess(self) -> None:
        result = acpx.run_preflight(
            acpx_bin="acpx", workspace=self.root / "results" / "preflight", skill_name="fixture-skill",
            description="Use when merging a PR.", timeout=2, model="fixture/model", effort="high",
            strict_json=True, codex_home=self.source, require_file_trace=False,
            container_runtime="fixture/engine", runtime_image="fixture/image",
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(BodyReadingRuntime.instances), 2)
        self.assertIsNotNone(BodyReadingRuntime.instances[0].options["skill_path"])
        self.assertIsNone(BodyReadingRuntime.instances[1].options["skill_path"])
        for probe in BodyReadingRuntime.instances:
            self.assertEqual(probe.options["engine"], "fixture/engine")
            self.assertEqual(probe.options["image"], "fixture/image")
            self.assertTrue(probe.exited)
        self.host_run.assert_not_called()
        self.assert_safe_artifacts()

    def test_unsafe_native_sandbox_modes_are_rejected_before_runtime_creation(self) -> None:
        for sandbox in ("workspace-write", "danger-full-access"):
            with self.subTest(sandbox=sandbox):
                with self.assertRaises(IsolationError):
                    native.run_one(codex_bin="codex", sandbox=sandbox, **self.common())
        self.assertEqual(BodyReadingRuntime.instances, [])
        self.assertFalse((self.root / "results").exists())

    def test_unsafe_native_sandbox_mode_is_also_rejected_by_cli(self) -> None:
        argv = ["codex_trigger_eval.py", "--skill-dir", str(self.root), "--workspace", str(self.root / "results"), "--sandbox", "danger-full-access"]
        with mock.patch.object(sys, "argv", argv), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                native.main()
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(BodyReadingRuntime.instances, [])

    def test_both_runners_exit_context_after_launch_exception(self) -> None:
        for runner in (self.run_native, self.run_acpx):
            with self.subTest(runner=runner.__name__):
                BodyReadingRuntime.failure = OSError("synthetic launch failure")
                with self.assertRaisesRegex(OSError, "synthetic launch failure"):
                    runner()
                probe = BodyReadingRuntime.instances[-1]
                self.assertTrue(probe.exited)
                self.assertIs(probe.exit_type, OSError)
        self.assert_safe_artifacts()

    def test_timeout_is_not_counted_as_a_success_and_exits_context(self) -> None:
        for runner in (self.run_native, self.run_acpx):
            with self.subTest(runner=runner.__name__):
                BodyReadingRuntime.failure = subprocess.TimeoutExpired(["synthetic"], 2, output=b"partial fixture")
                result = runner()
                self.assertTrue(result["timed_out"])
                self.assertFalse(result["passed"])
                self.assertTrue(BodyReadingRuntime.instances[-1].exited)
        self.assert_safe_artifacts()

    def test_acpx_nonzero_session_setup_is_recorded_as_failure_and_exits_context(self) -> None:
        BodyReadingRuntime.setup_returncode = 1
        result = self.run_acpx()
        self.assertFalse(result["passed"])
        self.assertEqual(result["returncode"], 1)
        probe = BodyReadingRuntime.instances[-1]
        self.assertTrue(probe.exited)
        self.assertEqual(len(probe.commands), 1)
        self.assertNotIn("prompt", probe.commands[0])
        self.assert_safe_artifacts()

    def test_keep_probe_homes_preserves_only_synthetic_skill_material(self) -> None:
        for runner in (self.run_native, self.run_acpx):
            with self.subTest(runner=runner.__name__):
                result = runner(keep_home=True)
                home = Path(result["run_dir"]) / "home"
                self.assertTrue(home.is_dir())
                files = [path.relative_to(home) for path in home.rglob("*") if path.is_file()]
                self.assertEqual(files, [Path(".agents/skills/fixture-skill/SKILL.md")])
        self.assert_safe_artifacts()

    def test_repeated_query_gets_fresh_host_probe_directory(self) -> None:
        for runner in (self.run_native, self.run_acpx):
            with self.subTest(runner=runner.__name__):
                first = runner(keep_home=True)
                second = runner(keep_home=True)
                self.assertNotEqual(first["run_dir"], second["run_dir"])

    def test_probe_skill_names_reject_traversal_and_invalid_slugs_before_writes(self) -> None:
        for name in ("../escape", "/absolute", "bad/name", "bad\\name", "bad_name", "Uppercase", ".", "..", "a" * 65, "-leading", "trailing-", "two--hyphens", ""):
            with self.subTest(name=name):
                home = self.root / "invalid-name-home"
                with self.assertRaisesRegex(ValueError, "lowercase slug"):
                    write_probe_skill(home, name=name, description="fixture", marker="marker", harness_label="fixture")
                self.assertFalse(home.exists())


if __name__ == "__main__":
    unittest.main()
