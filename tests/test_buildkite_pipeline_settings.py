"""Offline tests for scripts/buildkite-pipeline-settings.

A fake bk executable serves a pipeline fixture and its GitHub webhook
processing state from a state file and records each call, so no test reaches
Buildkite. PATH holds only the fake's directory, so a test can never run a
real bk.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/buildkite-pipeline-settings"
RECORD = ROOT / "scripts/buildkite-pipeline-settings.json"
FAKE_WEBHOOK_URL = "https://webhook.example.invalid/deliver/fixture-webhook-path"
FAKE_API_TOKEN = "fixture-api-token-value"
# Assembled at run time, so the source holds no token-shaped string.
FAKE_INJECTED_TOKEN = "bk" + "ua_" + "fixtureInjectedToken0"
# Provider settings the pipeline GET returns but provider_settings doesn't accept.
DERIVED = ("github_webhooks_disabled", "repository")

FAKE_BK = r'''
import json
import os
import sys

DERIVED = ("github_webhooks_disabled", "repository")
arguments = sys.argv[1:]
with open(os.environ["FAKE_BK_CALLS"], "a", encoding="utf-8") as calls:
    calls.write(json.dumps(arguments) + "\n")
mode = os.environ.get("FAKE_BK_MODE", "")
method, data, endpoint = "GET", None, None
rest = iter(arguments[1:])
for argument in rest:
    if argument in ("--method", "-X"):
        method = next(rest)
    elif argument in ("--data", "-d"):
        data = next(rest)
    elif not argument.startswith("-"):
        endpoint = argument
if arguments[:1] != ["api"] or endpoint is None:
    sys.exit(64)
with open(os.environ["FAKE_BK_STATE"], encoding="utf-8") as state_file:
    state = json.load(state_file)
pipeline, webhooks = state["pipeline"], state["github_webhooks"]


WRITTEN = os.environ["FAKE_BK_STATE"] + ".written"


def save(written=False):
    with open(os.environ["FAKE_BK_STATE"], "w", encoding="utf-8") as state_file:
        json.dump(state, state_file)
    if written:
        open(WRITTEN, "w").close()


if mode == "fail-readback" and method == "GET" and os.path.exists(WRITTEN):
    print("Error: 503 Service Unavailable", file=sys.stderr)
    sys.exit(1)
if mode == "inject-token":
    # Like the secret-exec shim, which gives bk a token the script never holds.
    print("Error: 401 Unauthorized for token " + os.environ["FAKE_BK_INJECTED"], file=sys.stderr)
    sys.exit(1)
if (
    mode == "fail"
    or (mode == "fail-patch" and method == "PATCH")
    or (mode == "fail-webhooks" and method in ("PUT", "DELETE"))
):
    # A careless error path could echo secrets; the script must redact them.
    print(
        "Error: 401 Unauthorized calling " + pipeline["provider"]["webhook_url"]
        + " with " + os.environ.get("BUILDKITE_API_TOKEN", ""),
        file=sys.stderr,
    )
    sys.exit(1)
print("Warning: using BUILDKITE_API_TOKEN environment variable for authentication.", file=sys.stderr)
if endpoint.endswith("/github-webhooks"):
    if method in ("PUT", "DELETE"):
        enabled = method == "PUT"
        webhooks["enabled"] = enabled
        webhooks["disabled_at"] = None if enabled else "2026-10-02T00:00:00.000Z"
        webhooks["disabled_by"] = None if enabled else "Fixture Owner"
        pipeline["provider"]["settings"]["github_webhooks_disabled"] = not enabled
        save(written=True)
    elif method != "GET":
        sys.exit(65)
    print(json.dumps({} if mode == "no-webhooks-state" else webhooks))
    sys.exit(0)
if method == "GET":
    if mode == "counters":
        # Builds start and finish between reads.
        pipeline["running_jobs_count"] += 1
        save()
    if mode == "malformed":
        print('{"slug": "dotfiles", "provider": {"webhook_url": "' + pipeline["provider"]["webhook_url"] + '"')
    elif mode == "other-slug":
        print(json.dumps({**pipeline, "slug": "other"}))
    elif mode == "other-org":
        print(json.dumps({**pipeline, "url": pipeline["url"].replace("/nisavid/", "/other-org/")}))
    elif mode == "no-provider":
        print(json.dumps({**pipeline, "provider": {"id": "github"}}))
    else:
        print(json.dumps(pipeline))
    sys.exit(0)
if method != "PATCH":
    sys.exit(65)
payload = json.loads(data)
if mode != "patch-ignored":
    for key, value in payload.items():
        if key == "provider_settings":
            # Like a write that resets every provider setting it omits. The
            # keys Buildkite derives or manages elsewhere are not inputs.
            current = pipeline["provider"]["settings"]
            pipeline["provider"]["settings"] = {
                **{name: sent for name, sent in value.items() if name not in DERIVED},
                **{name: current[name] for name in DERIVED if name in current},
            }
        else:
            pipeline[key] = value
    if "configuration" in payload:
        # Buildkite derives steps and the top-level env from the YAML.
        lines = payload["configuration"].splitlines()
        env = {}
        if "env:" in lines:
            for line in lines[lines.index("env:") + 1:]:
                if not line.startswith("  "):
                    break
                name, _, value = line.strip().partition(": ")
                env[name] = value
        pipeline["steps"] = [{"type": "script", "command": "parsed from the new configuration"}]
        pipeline["env"] = env
settings = pipeline["provider"]["settings"]
if mode == "patch-extra":
    settings["build_tags"] = not settings["build_tags"]
elif mode == "patch-top":
    pipeline["default_branch"] = "trunk"
elif mode == "patch-webhook":
    pipeline["provider"]["webhook_url"] += "-rotated"
elif mode in ("drop-key", "drop-keys"):
    del settings["publish_blocked_as_pending"]
    if mode == "drop-keys":
        del settings["use_step_key_as_commit_status"]
save(written=True)
print(json.dumps(pipeline))
'''


def load_record() -> dict[str, Any]:
    return json.loads(RECORD.read_text(encoding="utf-8"))


def setting_count(record: dict[str, Any]) -> int:
    return sum(len(record.get(section, {})) for section in ("pipeline_settings", "provider_settings", "github_webhooks"))


def live_state(record: dict[str, Any]) -> dict[str, Any]:
    """Return a live pipeline and webhook state that match the record, plus unrecorded fields."""

    enabled = record["github_webhooks"]["enabled"]
    settings: dict[str, Any] = {
        "build_tags": False,
        "github_webhooks_disabled": not enabled,
        "repository": "example/dotfiles",
        "skip_builds_for_closed_pull_requests": True,
        "use_step_key_as_commit_status": False,
    }
    settings.update(record["provider_settings"])
    url = f"https://api.example.invalid/v2/organizations/{record['organization']}/pipelines/{record['pipeline']}"
    pipeline: dict[str, Any] = {
        "id": "fixture-pipeline",
        "slug": record["pipeline"],
        "name": record["pipeline"],
        "url": url,
        "repository": "git@example.invalid:example/dotfiles.git",
        "default_branch": "main",
        "allow_rebuilds": True,
        "env": None,
        "skip_queued_branch_builds": True,
        "skip_queued_branch_builds_filter": "!main",
        "running_builds_count": 1,
        "running_jobs_count": 7,
        "steps": [{"type": "script", "command": "parsed from the configuration"}],
        "provider": {"id": "github", "webhook_url": FAKE_WEBHOOK_URL, "settings": settings},
    }
    pipeline.update(record["pipeline_settings"])
    webhooks = {"url": f"{url}/github-webhooks", "enabled": enabled, "disabled_at": None, "disabled_by": None}
    return {"pipeline": pipeline, "github_webhooks": webhooks}


def method_of(call: list[str]) -> str:
    return call[call.index("--method") + 1] if "--method" in call else "GET"


class BuildkitePipelineSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.scratch = Path(directory.name)
        self.bin = self.scratch / "bin"
        self.bin.mkdir()
        self.fake_bk = self.bin / "bk"
        self.fake_bk.write_text(f"#!{sys.executable}\n{FAKE_BK}", encoding="utf-8")
        self.fake_bk.chmod(0o755)
        self.state = self.scratch / "state.json"
        self.calls_log = self.scratch / "calls.jsonl"
        self.record = load_record()
        self.count = setting_count(self.record)
        self.live = live_state(self.record)
        self.pipeline = self.live["pipeline"]
        self.settings = self.pipeline["provider"]["settings"]
        self.webhooks = self.live["github_webhooks"]

    def run_script(
        self,
        *arguments: str,
        mode: str = "",
        env: dict[str, str] | None = None,
        unset: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        self.state.write_text(json.dumps(self.live), encoding="utf-8")
        self.state.with_name(f"{self.state.name}.written").unlink(missing_ok=True)
        environment = {
            "PATH": str(self.bin),
            "HOME": str(self.scratch),
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "BUILDKITE_API_TOKEN": FAKE_API_TOKEN,
            "FAKE_BK_STATE": str(self.state),
            "FAKE_BK_CALLS": str(self.calls_log),
            "FAKE_BK_MODE": mode,
            **(env or {}),
        }
        for name in unset:
            environment.pop(name)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        for secret in (FAKE_WEBHOOK_URL, "fixture-webhook-path", FAKE_API_TOKEN, FAKE_INJECTED_TOKEN):
            self.assertNotIn(secret, result.stdout)
            self.assertNotIn(secret, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def calls(self) -> list[list[str]]:
        if not self.calls_log.exists():
            return []
        return [json.loads(line) for line in self.calls_log.read_text(encoding="utf-8").splitlines()]

    def requests(self) -> list[tuple[str, str]]:
        return [(method_of(call), call[-1]) for call in self.calls()]

    def patches(self) -> list[dict[str, Any]]:
        payloads = []
        for call in self.calls():
            if method_of(call) == "PATCH":
                data = call[call.index("--data") + 1]
                self.assertNotIn(FAKE_WEBHOOK_URL, data)
                self.assertNotIn("webhook_url", data)
                payload = json.loads(data)
                for key in DERIVED:
                    self.assertNotIn(key, payload.get("provider_settings", {}))
                payloads.append(payload)
        return payloads

    def final_state(self) -> dict[str, Any]:
        return json.loads(self.state.read_text(encoding="utf-8"))

    def test_record_holds_the_gate_settings(self) -> None:
        provider = self.record["provider_settings"]
        for key in (
            "publish_blocked_as_pending",
            "publish_commit_status",
            "publish_commit_status_per_step",
            "build_pull_requests",
        ):
            with self.subTest(key=key):
                self.assertIs(provider[key], True)
        self.assertIn(
            "buildkite-agent pipeline upload",
            self.record["pipeline_settings"]["configuration"],
        )
        self.assertEqual(self.record["github_webhooks"], {"enabled": True})
        self.assertEqual((self.record["organization"], self.record["pipeline"]), ("nisavid", "dotfiles"))
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_check_passes_when_live_matches(self) -> None:
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f"pipeline dotfiles matches scripts/buildkite-pipeline-settings.json ({self.count} settings)",
            result.stdout,
        )
        self.assertEqual(
            self.calls(),
            [
                ["api", "--no-pager", "-q", "/pipelines/dotfiles"],
                ["api", "--no-pager", "-q", "/pipelines/dotfiles/github-webhooks"],
            ],
        )

    def test_check_ignores_unrecorded_settings(self) -> None:
        self.settings["build_tags"] = True
        self.pipeline["default_branch"] = "trunk"
        self.pipeline["skip_queued_branch_builds"] = False
        self.webhooks["disabled_by"] = "Someone Else"
        result = self.run_script("check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_check_reports_each_drifted_setting(self) -> None:
        self.settings["publish_blocked_as_pending"] = False
        self.pipeline["branch_configuration"] = "main"
        self.pipeline["configuration"] = self.pipeline["configuration"].replace("linux-small", "linux-large")
        self.webhooks["enabled"] = False
        result = self.run_script("check")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(
            f"differs from scripts/buildkite-pipeline-settings.json in 4 of {self.count} settings:\n",
            result.stdout,
        )
        for line in (
            "  provider_settings.publish_blocked_as_pending: committed true, live false\n",
            '  pipeline_settings.branch_configuration: committed null, live "main"\n',
            "  pipeline_settings.configuration: committed and live differ:\n",
            "    -      queue: linux-small\n",
            "    +      queue: linux-large\n",
            "  github_webhooks.enabled: committed true, live false\n",
        ):
            with self.subTest(line=line):
                self.assertIn(line, result.stdout)
        self.assertIn("apply --yes", result.stdout)
        self.assertEqual(self.patches(), [])

    def test_check_shows_line_ending_differences(self) -> None:
        committed = self.pipeline["configuration"]
        cases = {
            "no trailing newline": (
                committed.rstrip("\n"),
                ("    -      fi\n    +      fi\n    \\ No newline at end of value\n",),
            ),
            "CRLF": (committed.replace("\n", "\r\n"), ("    -steps:\n", "    +steps:\\r\n")),
        }
        for name, (live, expected) in cases.items():
            with self.subTest(case=name):
                self.pipeline["configuration"] = live
                result = self.run_script()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("  pipeline_settings.configuration: committed and live differ:\n", result.stdout)
                for line in expected:
                    self.assertIn(line, result.stdout)

    def test_check_escapes_control_characters(self) -> None:
        self.pipeline["configuration"] = self.pipeline["configuration"].replace("Upload", "Upload\x1b[2J")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('    +  - label: \\":pipeline: Upload\\u001b[2J\\"\n', result.stdout)
        self.assertNotIn("\x1b", result.stdout)

    def test_check_redacts_live_values(self) -> None:
        self.pipeline["configuration"] = (
            "env:\n"
            f"  DEPLOY_TOKEN: {FAKE_INJECTED_TOKEN}\n"
            "  DEPLOY_PASSWORD: fixture-password-value\n"
            "  MIRROR: https://mirror.example.invalid/fixture-mirror-path\n"
            + self.pipeline["configuration"]
        )
        self.settings["trigger_mode"] = "https://hook.example.invalid/fixture-hook-path"
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stderr)
        for line in (
            "    +  DEPLOY_TOKEN: <redacted>\n",
            "    +  DEPLOY_PASSWORD: <redacted>\n",
            "    +  MIRROR: <url>\n",
            '  provider_settings.trigger_mode: committed "code", live "<url>"\n',
        ):
            with self.subTest(line=line):
                self.assertIn(line, result.stdout)
        for secret in ("fixture-password-value", "fixture-mirror-path", "fixture-hook-path"):
            self.assertNotIn(secret, result.stdout + result.stderr)

    def test_check_tells_a_number_from_a_boolean(self) -> None:
        self.settings["publish_commit_status"] = 1
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("publish_commit_status: committed true, live 1", result.stdout)

    def test_missing_live_setting_is_an_error(self) -> None:
        del self.settings["publish_blocked_as_pending"]
        result = self.run_script()
        self.assertEqual(result.returncode, 2)
        self.assertIn("has no provider_settings.publish_blocked_as_pending", result.stderr)

    def test_bk_failure_is_an_error_without_secrets(self) -> None:
        for command in ("check", "apply"):
            with self.subTest(command=command):
                arguments = [command] + (["--yes"] if command == "apply" else [])
                result = self.run_script(*arguments, mode="fail")
                self.assertEqual(result.returncode, 2)
                self.assertIn("cannot read pipeline dotfiles: bk exited with status 1", result.stderr)
                self.assertIn("401 Unauthorized calling <url> with <token>", result.stderr)

    def test_bk_failure_redacts_a_token_only_bk_holds(self) -> None:
        result = self.run_script(
            mode="inject-token", env={"FAKE_BK_INJECTED": FAKE_INJECTED_TOKEN}, unset=("BUILDKITE_API_TOKEN",)
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("401 Unauthorized for token <token>", result.stderr)

    def test_malformed_json_is_an_error(self) -> None:
        result = self.run_script(mode="malformed")
        self.assertEqual(result.returncode, 2)
        self.assertIn("bk api /pipelines/dotfiles returned malformed JSON", result.stderr)

    def test_unexpected_responses_are_errors(self) -> None:
        cases = {
            "other-slug": "bk api /pipelines/dotfiles returned a different pipeline",
            "other-org": (
                'bk api /pipelines/dotfiles returned pipeline dotfiles of organization "other-org", not nisavid;'
                " select organization nisavid in bk"
            ),
            "no-provider": "bk api /pipelines/dotfiles returned no provider settings",
            "no-webhooks-state": "bk api /pipelines/dotfiles/github-webhooks returned no webhook processing state",
        }
        self.settings["publish_blocked_as_pending"] = False
        for mode, message in cases.items():
            for command in ("check", "apply"):
                with self.subTest(mode=mode, command=command):
                    self.calls_log.unlink(missing_ok=True)
                    arguments = [command] + (["--yes"] if command == "apply" else [])
                    result = self.run_script(*arguments, mode=mode)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(message, result.stderr)
                    self.assertEqual({method for method, _ in self.requests()}, {"GET"})

    def test_pipeline_without_an_organization_is_an_error(self) -> None:
        del self.pipeline["url"]
        result = self.run_script()
        self.assertEqual(result.returncode, 2)
        self.assertIn("returned pipeline dotfiles of no organization, not nisavid", result.stderr)

    def test_missing_bk_is_an_error(self) -> None:
        self.fake_bk.unlink()
        result = self.run_script()
        self.assertEqual(result.returncode, 2)
        self.assertIn("bk not found", result.stderr)

    def test_bk_variable_selects_the_executable(self) -> None:
        other = self.scratch / "other"
        other.mkdir()
        self.fake_bk.rename(other / "fake-bk")
        result = self.run_script(env={"BK": str(other / "fake-bk")})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls()), 2)

    def test_apply_refuses_without_yes(self) -> None:
        self.settings["publish_blocked_as_pending"] = False
        result = self.run_script("apply")
        self.assertEqual(result.returncode, 2)
        self.assertIn("rerun with --yes", result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertIs(self.final_state()["pipeline"]["provider"]["settings"]["publish_blocked_as_pending"], False)

    def test_apply_without_drift_writes_nothing(self) -> None:
        result = self.run_script("apply", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already matches", result.stdout)
        self.assertEqual({method for method, _ in self.requests()}, {"GET"})

    def test_apply_changes_only_differing_settings(self) -> None:
        expected = copy.deepcopy(self.live)
        self.settings["publish_blocked_as_pending"] = False
        self.pipeline["branch_configuration"] = "main"
        drifted_settings = copy.deepcopy(self.settings)
        result = self.run_script("apply", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.requests(),
            [
                ("GET", "/pipelines/dotfiles"),
                ("GET", "/pipelines/dotfiles/github-webhooks"),
                ("PATCH", "/pipelines/dotfiles"),
                ("GET", "/pipelines/dotfiles"),
                ("GET", "/pipelines/dotfiles/github-webhooks"),
            ],
        )
        # The full provider settings go out, with only the drifted one changed
        # and without the keys provider_settings doesn't accept, so the fake's
        # reset of omitted settings changes nothing else.
        sent = {key: value for key, value in drifted_settings.items() if key not in DERIVED}
        self.assertEqual(
            self.patches(),
            [
                {
                    "provider_settings": {**sent, "publish_blocked_as_pending": True},
                    "branch_configuration": None,
                }
            ],
        )
        self.assertEqual(self.final_state(), expected)
        self.assertIn("  provider_settings.publish_blocked_as_pending: false -> true\n", result.stdout)
        self.assertIn('  pipeline_settings.branch_configuration: "main" -> null\n', result.stdout)
        self.assertIn(
            "matches scripts/buildkite-pipeline-settings.json, and nothing else differs from what apply read before writing",
            result.stdout,
        )

    def test_apply_of_pipeline_fields_leaves_provider_settings_alone(self) -> None:
        committed = self.pipeline["configuration"]
        self.pipeline["configuration"] = "steps: []\n"
        result = self.run_script("apply", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.patches(), [{"configuration": committed}])
        self.assertIn("pipeline_settings.configuration: set to the committed value", result.stdout)
        self.assertEqual(self.final_state()["pipeline"]["configuration"], committed)

    def test_apply_of_configuration_lets_env_follow_it(self) -> None:
        committed = self.pipeline["configuration"]
        self.pipeline["configuration"] = "env:\n  FIXTURE_FLAG: on\n" + committed
        self.pipeline["env"] = {"FIXTURE_FLAG": "on"}
        result = self.run_script("apply", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        final = self.final_state()["pipeline"]
        self.assertEqual((final["configuration"], final["env"]), (committed, {}))

    def test_apply_restores_webhook_processing_through_its_endpoint(self) -> None:
        self.settings["github_webhooks_disabled"] = True
        self.webhooks.update(enabled=False, disabled_at="2026-10-01T00:00:00.000Z", disabled_by="Fixture Owner")
        self.settings["publish_blocked_as_pending"] = False
        result = self.run_script("apply", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            [request for request in self.requests() if request[0] != "GET"],
            [("PATCH", "/pipelines/dotfiles"), ("PUT", "/pipelines/dotfiles/github-webhooks")],
        )
        self.assertEqual(len(self.patches()), 1)
        self.assertIn("  github_webhooks.enabled: false -> true\n", result.stdout)
        final = self.final_state()
        self.assertIs(final["github_webhooks"]["enabled"], True)
        self.assertIs(final["pipeline"]["provider"]["settings"]["github_webhooks_disabled"], False)
        self.assertIs(final["pipeline"]["provider"]["settings"]["publish_blocked_as_pending"], True)

    def test_apply_of_webhook_processing_alone_sends_no_patch(self) -> None:
        self.settings["github_webhooks_disabled"] = True
        self.webhooks["enabled"] = False
        result = self.run_script("apply", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            [request for request in self.requests() if request[0] != "GET"],
            [("PUT", "/pipelines/dotfiles/github-webhooks")],
        )

    def test_apply_can_disable_webhook_processing(self) -> None:
        record = load_record()
        record["github_webhooks"]["enabled"] = False
        path = self.scratch / "record.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        result = self.run_script("--record", str(path), "apply", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            [request for request in self.requests() if request[0] != "GET"],
            [("DELETE", "/pipelines/dotfiles/github-webhooks")],
        )
        self.assertIs(self.final_state()["github_webhooks"]["enabled"], False)

    def test_apply_fails_when_read_back_still_differs(self) -> None:
        self.settings["publish_blocked_as_pending"] = False
        result = self.run_script("apply", "--yes", mode="patch-ignored")
        self.assertEqual(result.returncode, 1)
        self.assertIn("did not verify after apply", result.stderr)
        self.assertIn("provider_settings.publish_blocked_as_pending: committed true, live false", result.stderr)

    def test_apply_fails_when_another_setting_changes(self) -> None:
        cases = {
            "patch-extra": "provider_settings.build_tags",
            "patch-top": "pipeline_settings.default_branch",
            "patch-webhook": "provider.webhook_url",
        }
        self.settings["publish_blocked_as_pending"] = False
        for mode, name in cases.items():
            with self.subTest(mode=mode):
                result = self.run_script("apply", "--yes", mode=mode)
                self.assertEqual(result.returncode, 1)
                self.assertIn("did not verify after apply:\n", result.stderr)
                self.assertIn(f"  {name} changed, though apply did not set it\n", result.stderr)
                self.assertNotIn("committed true, live false", result.stderr)

    def test_apply_verifies_while_builds_run(self) -> None:
        self.settings["publish_blocked_as_pending"] = False
        result = self.run_script("apply", "--yes", mode="counters")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertGreater(self.final_state()["pipeline"]["running_jobs_count"], self.pipeline["running_jobs_count"])
        self.assertIn("nothing else differs from what apply read before writing", result.stdout)

    def test_apply_reports_a_setting_missing_after_the_write(self) -> None:
        self.settings["publish_blocked_as_pending"] = False
        unexpected = "  provider_settings.use_step_key_as_commit_status changed, though apply did not set it\n"
        for mode in ("drop-key", "drop-keys"):
            with self.subTest(mode=mode):
                result = self.run_script("apply", "--yes", mode=mode)
                self.assertEqual(result.returncode, 1)
                self.assertIn("did not verify after apply:\n", result.stderr)
                self.assertIn("  provider_settings.publish_blocked_as_pending: missing after apply\n", result.stderr)
                if mode == "drop-keys":
                    self.assertIn(unexpected, result.stderr)
                else:
                    self.assertNotIn(unexpected, result.stderr)

    def test_apply_reports_a_failed_read_back(self) -> None:
        self.settings["publish_blocked_as_pending"] = False
        result = self.run_script("apply", "--yes", mode="fail-readback")
        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "wrote pipeline dotfiles, but could not read it back: cannot read pipeline dotfiles", result.stderr
        )

    def test_apply_reports_a_failed_write(self) -> None:
        cases = {
            "fail-patch": "cannot update pipeline dotfiles (run check to see its current settings)",
            "fail-webhooks": (
                "cannot enable GitHub webhook processing of pipeline dotfiles after updating its other settings"
            ),
        }
        self.settings["publish_blocked_as_pending"] = False
        self.webhooks["enabled"] = False
        for mode, message in cases.items():
            with self.subTest(mode=mode):
                result = self.run_script("apply", "--yes", mode=mode)
                self.assertEqual(result.returncode, 2)
                self.assertIn(message, result.stderr)
                self.assertIn("<url>", result.stderr)

    def test_apply_refuses_to_send_the_webhook_url(self) -> None:
        self.settings["fixture_notification_target"] = FAKE_WEBHOOK_URL
        self.settings["publish_blocked_as_pending"] = False
        result = self.run_script("apply", "--yes")
        self.assertEqual(result.returncode, 2)
        self.assertIn("refusing to send the pipeline's webhook URL", result.stderr)
        self.assertEqual({method for method, _ in self.requests()}, {"GET"})

    def test_invalid_records_are_errors(self) -> None:
        def empty(record: dict[str, Any]) -> None:
            record.update(pipeline_settings={}, provider_settings={})
            del record["github_webhooks"]

        cases: dict[str, tuple[Callable[[dict[str, Any]], object], str]] = {
            "webhook URL": (
                lambda record: record["provider_settings"].update(webhook_url=FAKE_WEBHOOK_URL),
                "provider_settings.webhook_url must not be recorded",
            ),
            "identifier": (
                lambda record: record["pipeline_settings"].update(id="fixture-pipeline"),
                "pipeline_settings.id must not be recorded",
            ),
            "env": (
                lambda record: record["pipeline_settings"].update(env=None),
                "pipeline_settings.env must not be recorded",
            ),
            "clone mirror URL": (
                lambda record: record["pipeline_settings"].update(clone_mirror_url=None),
                "pipeline_settings.clone_mirror_url must not be recorded",
            ),
            "template": (
                lambda record: record["pipeline_settings"].update(pipeline_template_uuid=None),
                "pipeline_settings.pipeline_template_uuid must not be recorded",
            ),
            "counter": (
                lambda record: record["pipeline_settings"].update(running_jobs_count=0),
                "pipeline_settings.running_jobs_count must not be recorded",
            ),
            "webhook processing as a provider setting": (
                lambda record: record["provider_settings"].update(github_webhooks_disabled=False),
                "record webhook processing as github_webhooks.enabled",
            ),
            "nested value": (
                lambda record: record["provider_settings"].update(trigger_mode={"mode": "code"}),
                "provider_settings.trigger_mode must be null, a boolean, a number or a string",
            ),
            "webhook processing value": (
                lambda record: record.update(github_webhooks={"enabled": "yes"}),
                'github_webhooks must be {"enabled": true} or {"enabled": false}',
            ),
            "unknown key": (lambda record: record.update(extra=True), "has unknown keys: extra"),
            "bad slug": (lambda record: record.update(pipeline="../dotfiles"), "must name the pipeline slug"),
            "no organization": (lambda record: record.pop("organization"), "must name the organization slug"),
            "description": (lambda record: record.update(description=5), "description must be a string"),
            "empty": (empty, "records no settings"),
            "NaN": (
                lambda record: record["provider_settings"].update(trigger_mode=float("nan")),
                "non-standard JSON constant NaN",
            ),
        }
        for name, (change, message) in cases.items():
            with self.subTest(case=name):
                record = load_record()
                change(record)
                path = self.scratch / "record.json"
                path.write_text(json.dumps(record), encoding="utf-8")
                self.calls_log.unlink(missing_ok=True)
                result = self.run_script("--record", str(path), "check")
                self.assertEqual(result.returncode, 2)
                self.assertIn(str(path), result.stderr)
                self.assertIn(message, result.stderr)
                self.assertEqual(self.calls(), [])
        path = self.scratch / "duplicate.json"
        path.write_text('{"pipeline": "dotfiles", "pipeline": "other"}', encoding="utf-8")
        result = self.run_script("--record", str(path))
        self.assertEqual(result.returncode, 2)
        self.assertIn('duplicate key "pipeline"', result.stderr)


if __name__ == "__main__":
    unittest.main()
