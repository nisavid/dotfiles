from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import update_reviewable_pr
from reviewable_pr_state import PublicationError


BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
REPOSITORY = "owner/repository"
PR_NUMBER = 42
TITLE_DIGEST = "7e8cd2056da73a7fefb6cd91f4e5d199d08d9058c517b9a2476b1b520324d674"
BODY_DIGEST = "421dc617d921c24f41441973d8476605718a14a5c2228b8344cc1d6d816e8d39"


def stored_pr() -> dict[str, object]:
    return {
        "number": PR_NUMBER,
        "url": f"https://github.com/{REPOSITORY}/pull/{PR_NUMBER}",
        "title": "Title",
        "body": "Body\n",
        "baseRefName": "main",
        "baseRefOid": BASE_SHA,
        "headRefName": "feature",
        "headRefOid": HEAD_SHA,
        "headRepositoryOwner": {"login": "owner"},
        "isDraft": True,
        "state": "OPEN",
    }


class FakeGitHub:
    def __init__(self) -> None:
        self.state = stored_pr()
        self.fail_after_mutation = False

    def read_pr(self, repository: str, pr_number: int) -> dict[str, object]:
        if repository != REPOSITORY or pr_number != PR_NUMBER:
            raise PublicationError("unexpected PR identity reached GitHub")
        return deepcopy(self.state)

    def run(
        self, arguments: list[str], *, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        del input_text
        operation = arguments[4]
        if operation == "edit":
            title_index = arguments.index("--title") + 1
            body_index = arguments.index("--body-file") + 1
            self.state["title"] = arguments[title_index]
            self.state["body"] = Path(arguments[body_index]).read_text(encoding="utf-8")
        elif operation == "ready":
            self.state["isDraft"] = False
        else:
            raise AssertionError(f"unexpected gh operation: {operation}")
        if self.fail_after_mutation:
            raise PublicationError("simulated lost mutation response")
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")


def identity_arguments(*, head_oid: str = HEAD_SHA) -> list[str]:
    return [
        "--repository",
        REPOSITORY,
        "--pr",
        str(PR_NUMBER),
        "--base",
        "main",
        "--base-oid",
        BASE_SHA,
        "--head",
        "owner:feature",
        "--head-owner",
        "owner",
        "--head-oid",
        head_oid,
    ]


def accept_body(*_: object) -> None:
    pass


class UpdateReviewablePrTests(unittest.TestCase):
    def invoke_cli(
        self,
        github: FakeGitHub,
        arguments: list[str],
        *,
        validate_body: Callable[..., None] = accept_body,
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(update_reviewable_pr, "_stored_pr", new=github.read_pr),
            patch.object(update_reviewable_pr, "_run", new=github.run),
            patch.object(update_reviewable_pr, "_validate_body", new=validate_body),
            patch.object(sys, "argv", ["update_reviewable_pr.py", *arguments]),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            try:
                return_code = update_reviewable_pr.main()
            except SystemExit as error:
                return_code = int(error.code)
        return return_code, stdout.getvalue(), stderr.getvalue()

    def capture_preimage(self, github: FakeGitHub) -> dict[str, str]:
        return_code, stdout, stderr = self.invoke_cli(
            github,
            [
                "preimage",
                "--repository",
                REPOSITORY,
                "--pr",
                str(PR_NUMBER),
            ],
        )
        self.assertEqual(return_code, 0, stderr)
        return json.loads(stdout)

    def test_preimage_subcommand_preserves_trailing_newline_in_body_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            gh = Path(directory) / "gh"
            gh.write_text(
                "#!/usr/bin/env python3\n"
                "import json\n"
                "print(json.dumps({"
                "'title': 'Title', 'body': 'Body\\n', 'isDraft': True"
                "}))\n",
                encoding="utf-8",
            )
            gh.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{directory}:{environment['PATH']}"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "update_reviewable_pr.py"),
                    "preimage",
                    "--repository",
                    REPOSITORY,
                    "--pr",
                    str(PR_NUMBER),
                ],
                capture_output=True,
                text=True,
                check=False,
                env=environment,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "expected_body_sha256": BODY_DIGEST,
                "expected_state": "draft",
                "expected_title_sha256": TITLE_DIGEST,
            },
        )

    def test_preimage_rejects_nonpositive_pr_before_reading_github(self) -> None:
        return_code, _, stderr = self.invoke_cli(
            FakeGitHub(),
            [
                "preimage",
                "--repository",
                REPOSITORY,
                "--pr",
                "0",
            ],
        )

        self.assertEqual(return_code, 1)
        self.assertIn("PR number must be positive", stderr)

    def test_preimage_output_round_trips_through_text_cli(self) -> None:
        github = FakeGitHub()
        preimage = self.capture_preimage(github)
        with tempfile.TemporaryDirectory() as directory:
            body_path = Path(directory) / "body.md"
            body_path.write_text("Updated body\n", encoding="utf-8")
            return_code, stdout, stderr = self.invoke_cli(
                github,
                [
                    "text",
                    *identity_arguments(),
                    "--expected-title-sha256",
                    preimage["expected_title_sha256"],
                    "--expected-body-sha256",
                    preimage["expected_body_sha256"],
                    "--expected-state",
                    preimage["expected_state"],
                    "--title",
                    "Updated title",
                    "--body-file",
                    str(body_path),
                ],
            )

        self.assertEqual(return_code, 0, stderr)
        self.assertEqual(json.loads(stdout)["title"], "Updated title")
        self.assertEqual(github.state["body"], "Updated body\n")

    def test_preimage_output_round_trips_through_ready_cli(self) -> None:
        github = FakeGitHub()
        preimage = self.capture_preimage(github)
        return_code, stdout, stderr = self.invoke_cli(
            github,
            [
                "ready",
                *identity_arguments(),
                "--expected-title-sha256",
                preimage["expected_title_sha256"],
                "--expected-body-sha256",
                preimage["expected_body_sha256"],
                "--expected-state",
                preimage["expected_state"],
            ],
        )

        self.assertEqual(return_code, 0, stderr)
        self.assertFalse(json.loads(stdout)["isDraft"])
        self.assertEqual(
            self.capture_preimage(github)["expected_state"],
            "ready",
        )

    def test_ready_rechecks_preimage_after_body_validation(self) -> None:
        github = FakeGitHub()
        preimage = self.capture_preimage(github)

        def concurrent_body_edit(*_: object) -> None:
            github.state["body"] = "Concurrent body\n"

        return_code, _, stderr = self.invoke_cli(
            github,
            [
                "ready",
                *identity_arguments(),
                "--expected-title-sha256",
                preimage["expected_title_sha256"],
                "--expected-body-sha256",
                preimage["expected_body_sha256"],
                "--expected-state",
                preimage["expected_state"],
            ],
            validate_body=concurrent_body_edit,
        )

        self.assertEqual(return_code, 1)
        self.assertIn(
            "title/body digest does not match the captured preimage",
            stderr,
        )
        self.assertTrue(github.state["isDraft"])

    def test_ready_rejects_preimage_captured_after_pr_became_ready(self) -> None:
        github = FakeGitHub()
        github.state["isDraft"] = False
        preimage = self.capture_preimage(github)
        return_code, _, stderr = self.invoke_cli(
            github,
            [
                "ready",
                *identity_arguments(),
                "--expected-title-sha256",
                preimage["expected_title_sha256"],
                "--expected-body-sha256",
                preimage["expected_body_sha256"],
                "--expected-state",
                preimage["expected_state"],
            ],
        )

        self.assertEqual(return_code, 1)
        self.assertIn("ready mutation requires a draft preimage", stderr)

    def test_text_rejects_preimage_captured_before_draft_state_change(self) -> None:
        github = FakeGitHub()
        preimage = self.capture_preimage(github)
        github.state["isDraft"] = False
        with tempfile.TemporaryDirectory() as directory:
            body_path = Path(directory) / "body.md"
            body_path.write_text("Body\n", encoding="utf-8")
            return_code, _, stderr = self.invoke_cli(
                github,
                [
                    "text",
                    *identity_arguments(),
                    "--expected-title-sha256",
                    preimage["expected_title_sha256"],
                    "--expected-body-sha256",
                    preimage["expected_body_sha256"],
                    "--expected-state",
                    preimage["expected_state"],
                    "--title",
                    "Title",
                    "--body-file",
                    str(body_path),
                ],
            )

        self.assertEqual(return_code, 1)
        self.assertIn(
            "draft/ready state does not match the captured preimage",
            stderr,
        )

    def test_text_reports_closed_pr_separately_from_identity_change(self) -> None:
        github = FakeGitHub()
        preimage = self.capture_preimage(github)
        github.state["state"] = "CLOSED"
        with tempfile.TemporaryDirectory() as directory:
            body_path = Path(directory) / "body.md"
            body_path.write_text("Body\n", encoding="utf-8")
            return_code, _, stderr = self.invoke_cli(
                github,
                [
                    "text",
                    *identity_arguments(),
                    "--expected-title-sha256",
                    preimage["expected_title_sha256"],
                    "--expected-body-sha256",
                    preimage["expected_body_sha256"],
                    "--expected-state",
                    preimage["expected_state"],
                    "--title",
                    "Title",
                    "--body-file",
                    str(body_path),
                ],
            )

        self.assertEqual(return_code, 1)
        self.assertIn("PR is not open before mutation", stderr)

    def test_digest_mismatch_is_distinct_from_identity_change(self) -> None:
        github = FakeGitHub()
        preimage = self.capture_preimage(github)
        with tempfile.TemporaryDirectory() as directory:
            body_path = Path(directory) / "body.md"
            body_path.write_text("Body\n", encoding="utf-8")
            common = [
                "--expected-title-sha256",
                "c" * 64,
                "--expected-body-sha256",
                preimage["expected_body_sha256"],
                "--expected-state",
                preimage["expected_state"],
                "--title",
                "Title",
                "--body-file",
                str(body_path),
            ]
            return_code, _, digest_error = self.invoke_cli(
                github,
                ["text", *identity_arguments(), *common],
            )
            identity_common = common.copy()
            identity_common[1] = preimage["expected_title_sha256"]
            identity_code, _, identity_error = self.invoke_cli(
                github,
                [
                    "text",
                    *identity_arguments(head_oid="d" * 40),
                    *identity_common,
                ],
            )

        self.assertEqual(return_code, 1)
        self.assertIn(
            "title/body digest does not match the captured preimage",
            digest_error,
        )
        self.assertEqual(identity_code, 1)
        self.assertIn(
            "identity or pushed base/head changed before mutation",
            identity_error,
        )

    def test_text_surfaces_command_error_after_storing_intended_state(self) -> None:
        github = FakeGitHub()
        preimage = self.capture_preimage(github)
        github.fail_after_mutation = True
        with tempfile.TemporaryDirectory() as directory:
            body_path = Path(directory) / "body.md"
            body_path.write_text("Updated body\n", encoding="utf-8")
            return_code, stdout, stderr = self.invoke_cli(
                github,
                [
                    "text",
                    *identity_arguments(),
                    "--expected-title-sha256",
                    preimage["expected_title_sha256"],
                    "--expected-body-sha256",
                    preimage["expected_body_sha256"],
                    "--expected-state",
                    preimage["expected_state"],
                    "--title",
                    "Updated title",
                    "--body-file",
                    str(body_path),
                ],
            )

        self.assertEqual(return_code, 0, stderr)
        self.assertEqual(json.loads(stdout)["title"], "Updated title")
        self.assertIn("WARNING: PR text mutation has an ambiguous result", stderr)

    def test_ready_surfaces_command_error_after_storing_intended_state(self) -> None:
        github = FakeGitHub()
        preimage = self.capture_preimage(github)
        github.fail_after_mutation = True
        return_code, stdout, stderr = self.invoke_cli(
            github,
            [
                "ready",
                *identity_arguments(),
                "--expected-title-sha256",
                preimage["expected_title_sha256"],
                "--expected-body-sha256",
                preimage["expected_body_sha256"],
                "--expected-state",
                preimage["expected_state"],
            ],
        )

        self.assertEqual(return_code, 0, stderr)
        self.assertFalse(json.loads(stdout)["isDraft"])
        self.assertIn("WARNING: ready mutation has an ambiguous result", stderr)


if __name__ == "__main__":
    unittest.main()
