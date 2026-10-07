"""Offline CLI tests for read-only Buildkite retirement verification."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/buildkite-pipeline-settings"
RECORD = ROOT / "scripts/buildkite-pipeline-settings.json"
FAKE_TOKEN = "fixture-api-token-value"
FAKE_WEBHOOK = "https://webhook.example.invalid/fixture-webhook-path"
FAKE_BK = r'''
import json
import os
import sys
from pathlib import Path
arguments = sys.argv[1:]
with open(os.environ["FAKE_BK_CALLS"], "a") as output:
    output.write(json.dumps(arguments) + "\n")
if arguments != ["api", "--no-pager", "-q", "/pipelines/dotfiles"]:
    raise SystemExit("only the read-only pipeline request is supported")
state = json.loads(Path(os.environ["FAKE_BK_STATE"]).read_text())
if os.environ.get("FAKE_BK_MODE") == "fail":
    print("401 Unauthorized " + state["provider"]["webhook_url"] + " " + os.environ["BUILDKITE_API_TOKEN"], file=sys.stderr)
    raise SystemExit(1)
if os.environ.get("FAKE_BK_MODE") == "malformed":
    print('{"secret": "' + os.environ["BUILDKITE_API_TOKEN"])
else:
    print(json.dumps(state))
'''


class BuildkitePipelineSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.scratch = Path(directory.name)
        self.bin = self.scratch / "bin"
        self.bin.mkdir()
        self.fake_bk = self.bin / "bk"
        self.fake_bk.write_text(f"#!{sys.executable}\n{FAKE_BK}")
        self.fake_bk.chmod(0o755)
        self.calls_path = self.scratch / "calls.jsonl"
        self.state_path = self.scratch / "state.json"
        self.pipeline = {
            "slug": "dotfiles",
            "url": "https://api.example.invalid/v2/organizations/nisavid/pipelines/dotfiles",
            "archived_at": "2026-10-07T07:00:00Z",
            # Archiving preserves these historical flags; check must not
            # require reconfiguration of the archived pipeline to succeed.
            "provider": {"webhook_url": FAKE_WEBHOOK, "settings": {"build_branches": True, "build_pull_requests": True}},
        }

    def run_script(self, *arguments: str, mode: str = "", env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        self.state_path.write_text(json.dumps(self.pipeline))
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), *arguments],
            env={
                "PATH": str(self.bin), "HOME": str(self.scratch),
                "BUILDKITE_API_TOKEN": FAKE_TOKEN,
                "FAKE_BK_CALLS": str(self.calls_path), "FAKE_BK_STATE": str(self.state_path),
                "FAKE_BK_MODE": mode, **(env or {}),
            },
            capture_output=True, text=True, check=False,
        )

    def calls(self) -> list[list[str]]:
        if not self.calls_path.exists():
            return []
        return [json.loads(line) for line in self.calls_path.read_text().splitlines()]

    def test_archived_pipeline_passes_without_reconfiguring_historical_flags(self) -> None:
        result = self.run_script("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pipeline dotfiles is archived", result.stdout)
        self.assertIn("Queue state, active builds, and spending limits are not checked", result.stdout)
        self.assertEqual(self.calls(), [["api", "--no-pager", "-q", "/pipelines/dotfiles"]])

    def test_documented_utc_archive_timestamp_passes(self) -> None:
        self.pipeline["archived_at"] = "2021-06-01 08:23:35 UTC"
        result = self.run_script("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pipeline dotfiles is archived", result.stdout)
        self.assertEqual(self.calls(), [["api", "--no-pager", "-q", "/pipelines/dotfiles"]])

    def test_apply_is_retired_without_provider_access(self) -> None:
        for arguments in (("apply",), ("apply", "--yes")):
            with self.subTest(arguments=arguments):
                result = self.run_script(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertIn("apply is disabled", result.stderr)
                self.assertEqual(self.calls(), [])

    def test_alternate_record_cannot_restore_apply(self) -> None:
        record = self.scratch / "active.json"
        record.write_text(json.dumps({"provider_settings": {"build_branches": True}, "github_webhooks": {"enabled": True}}))
        result = self.run_script("--record", str(record), "apply", "--yes")
        self.assertEqual(result.returncode, 2)
        self.assertIn("apply is disabled", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_unarchived_pipeline_fails_without_repair(self) -> None:
        self.pipeline["archived_at"] = None
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("is not archived", result.stdout)
        self.assertNotIn("apply", result.stdout)
        self.assertEqual(self.calls(), [["api", "--no-pager", "-q", "/pipelines/dotfiles"]])

    def test_missing_or_malformed_archive_state_is_not_success(self) -> None:
        for value in (
            True, 1, "", "yesterday", "2026-10-07T07:00:00", [], {},
            "yesterday UTC", "2021-02-30 08:23:35 UTC", "2021-06-01 UTC",
        ):
            with self.subTest(value=value):
                self.pipeline["archived_at"] = value
                result = self.run_script()
                self.assertEqual(result.returncode, 2)
                self.assertIn("invalid archive state", result.stderr)
        self.pipeline.pop("archived_at")
        result = self.run_script()
        self.assertEqual(result.returncode, 2)
        self.assertIn("no archive state", result.stderr)

    def test_wrong_pipeline_or_organization_is_not_accepted(self) -> None:
        for key, value in (("slug", "other"), ("url", "https://api.example.invalid/v2/organizations/other/pipelines/dotfiles"), ("url", None)):
            with self.subTest(key=key, value=value):
                old = self.pipeline[key]
                self.pipeline[key] = value
                result = self.run_script()
                self.assertEqual(result.returncode, 2)
                self.pipeline[key] = old

    def test_invalid_or_active_record_fails_before_provider_access(self) -> None:
        default = json.loads(RECORD.read_text())
        variants = [
            {**default, "archived": False}, {**default, "archived": 1},
            {**default, "pipeline": "../other"}, {**default, "organization": ""},
            {**default, "provider_settings": {"build_branches": True}},
            {key: value for key, value in default.items() if key != "archived"},
            [],
        ]
        path = self.scratch / "record.json"
        for record in variants:
            with self.subTest(record=record):
                path.write_text(json.dumps(record))
                result = self.run_script("--record", str(path))
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.calls(), [])

    def test_duplicate_keys_and_nonstandard_json_are_rejected(self) -> None:
        path = self.scratch / "record.json"
        for value in ('{"archived": true, "archived": false}', '{"archived": NaN}', '{'):
            with self.subTest(value=value):
                path.write_text(value)
                result = self.run_script("--record", str(path))
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.calls(), [])

    def test_provider_failure_and_malformed_json_do_not_expose_secrets(self) -> None:
        for mode in ("fail", "malformed"):
            with self.subTest(mode=mode):
                result = self.run_script(mode=mode)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn(FAKE_TOKEN, result.stdout + result.stderr)
                self.assertNotIn(FAKE_WEBHOOK, result.stdout + result.stderr)

    def test_missing_provider_cli_is_an_error(self) -> None:
        self.fake_bk.unlink()
        result = self.run_script()
        self.assertEqual(result.returncode, 2)
        self.assertIn("bk not found", result.stderr)

    def test_explicit_provider_cli_remains_read_only(self) -> None:
        other = self.scratch / "fake-bk"
        self.fake_bk.rename(other)
        result = self.run_script(env={"BK": str(other)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [["api", "--no-pager", "-q", "/pipelines/dotfiles"]])


if __name__ == "__main__":
    unittest.main()
