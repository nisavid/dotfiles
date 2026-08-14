from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

CREATE_MODULE = (
    "literal_create_reviewable_pr"
    if (SCRIPTS / "literal_create_reviewable_pr.py").is_file()
    else "create_reviewable_pr"
)
create_reviewable_pr = importlib.import_module(CREATE_MODULE)
update_reviewable_pr = importlib.import_module("update_reviewable_pr")


BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
REPOSITORY = "owner/repository"
PR_NUMBER = 42


class ValidationIdentityTests(unittest.TestCase):
    def assert_validator_receives_identity(self, module, function_name: str) -> None:
        with patch.object(module, "_run") as run:
            getattr(module, function_name)(
                "body",
                REPOSITORY,
                PR_NUMBER,
                BASE_SHA,
                HEAD_SHA,
            )

        run.assert_called_once_with(
            [
                sys.executable,
                str(module.VALIDATOR),
                "/dev/stdin",
                "--repository",
                REPOSITORY,
                "--pr",
                str(PR_NUMBER),
                "--base-sha",
                BASE_SHA,
                "--head-sha",
                HEAD_SHA,
            ],
            input_text="body",
        )

    def test_create_validation_passes_immutable_identity(self) -> None:
        self.assert_validator_receives_identity(create_reviewable_pr, "_validate")

    def test_update_validation_passes_immutable_identity(self) -> None:
        self.assert_validator_receives_identity(update_reviewable_pr, "_validate_body")


if __name__ == "__main__":
    unittest.main()
