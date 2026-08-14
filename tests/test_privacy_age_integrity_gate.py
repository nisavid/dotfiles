from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.privacy_age_integrity_gate import verify_integrity_boundary

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts/privacy_age_integrity_gate.py"
WORKFLOW = ROOT / ".github/workflows/privacy-age-integrity.yml"

PROTECTED_FILES = {
    ".github/workflows/platform-portability.yml": "name: platform\n",
    ".github/workflows/privacy-age-integrity.yml": "name: boundary\n",
    ".privacy-age-envelopes.json": "{}\n",
    "docs/ENCRYPTION.md": "# Encryption\n",
    "home/.chezmoi.toml.tmpl": "recipient = 'fixture'\n",
    "home/private.age": "ciphertext fixture\n",
    "scripts/admit-age-envelopes": "#!/bin/sh\n",
    "scripts/agent_equipment_public_data.py": "# policy\n",
    "scripts/privacy-scan": "#!/usr/bin/env python3\n",
    "scripts/privacy_age_envelopes.py": "# inventory\n",
    "scripts/privacy_age_integrity_gate.py": "# gate\n",
}


def run(*command: str, cwd: Path) -> str:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )
    return result.stdout.strip()


def write_files(root: Path) -> None:
    for relative, contents in PROTECTED_FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")


def commit_all(root: Path, message: str) -> str:
    run("git", "add", "--all", cwd=root)
    run(
        "git",
        "-c",
        "commit.gpgsign=false",
        "-c",
        f"core.hooksPath={os.devnull}",
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-m",
        message,
        cwd=root,
    )
    return run("git", "rev-parse", "HEAD", cwd=root)


class PrivacyAgeIntegrityGateTests(TestCase):
    def make_checkouts(self) -> tuple[TemporaryDirectory[str], Path, Path, str]:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name) / "base"
        head = Path(temporary.name) / "head"
        base.mkdir()
        run("git", "init", "--quiet", cwd=base)
        write_files(base)
        base_commit = commit_all(base, "base")
        run(
            "git",
            "clone",
            "--quiet",
            "--no-local",
            os.fspath(base),
            os.fspath(head),
            cwd=Path(temporary.name),
        )
        return temporary, base, head, base_commit

    def verify(
        self, base: Path, head: Path, base_commit: str, head_commit: str
    ) -> None:
        verify_integrity_boundary(
            base_repository=base,
            base_commit=base_commit,
            head_repository=head,
            head_commit=head_commit,
        )

    def test_unrelated_candidate_changes_are_allowed(self) -> None:
        _, base, head, base_commit = self.make_checkouts()
        (head / "README.md").write_text("candidate docs\n", encoding="utf-8")
        head_commit = commit_all(head, "unrelated")

        self.verify(base, head, base_commit, head_commit)

    def test_workflow_rechecks_retargets_and_treats_fork_head_as_data(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn(
            "pull_request_target:\n    branches:\n      - main\n    types:\n",
            source,
        )
        self.assertIn("      - edited\n", source)
        self.assertIn(
            "PRIVACY_BASE_REF: ${{ github.event.pull_request.base.ref }}", source
        )
        self.assertIn('test "$PRIVACY_BASE_REF" = "main"', source)
        self.assertIn("allow-unsafe-pr-checkout: true", source)
        self.assertIn(
            "python3 trusted-base/scripts/privacy_age_integrity_gate.py", source
        )
        self.assertIn("python3 trusted-base/scripts/privacy-scan", source)
        self.assertNotIn("python3 untrusted-head/", source)
        self.assertEqual(
            tuple(
                line.strip() for line in source.splitlines() if "untrusted-head" in line
            ),
            (
                "path: untrusted-head",
                'test "$(git -C untrusted-head rev-parse HEAD)" = "$PRIVACY_HEAD_SHA"',
                "--head-repository untrusted-head \\",
                '--root "$GITHUB_WORKSPACE/untrusted-head" \\',
            ),
        )
        self.assertIsNone(
            re.search(
                r"(?m)^\s*(?:uses|working-directory):\s*(?:\./)?untrusted-head(?:/|$)",
                source,
            )
        )
        self.assertIsNone(
            re.search(
                r"(?m)^\s*(?:bash|sh|zsh|make|npm|npx)\b[^\n]*\buntrusted-head/",
                source,
            )
        )

    def test_every_protected_surface_is_frozen(self) -> None:
        mutations = {
            "changed ciphertext": lambda root: (root / "home/private.age").write_text(
                "changed\n", encoding="utf-8"
            ),
            "new confusable ciphertext": lambda root: (
                root / "home/new.AGE"
            ).write_text("new\n", encoding="utf-8"),
            "deleted ciphertext": lambda root: (root / "home/private.age").unlink(),
            "changed manifest": lambda root: (
                root / ".privacy-age-envelopes.json"
            ).write_text('{"changed":true}\n', encoding="utf-8"),
            "changed recipient": lambda root: (
                root / "home/.chezmoi.toml.tmpl"
            ).write_text("recipient = 'changed'\n", encoding="utf-8"),
            "changed scanner": lambda root: (root / "scripts/privacy-scan").write_text(
                "changed\n", encoding="utf-8"
            ),
            "changed parser": lambda root: (
                root / "scripts/privacy_age_envelopes.py"
            ).write_text("changed\n", encoding="utf-8"),
            "changed classifier": lambda root: (
                root / "scripts/agent_equipment_public_data.py"
            ).write_text("changed\n", encoding="utf-8"),
            "changed gate": lambda root: (
                root / "scripts/privacy_age_integrity_gate.py"
            ).write_text("changed\n", encoding="utf-8"),
            "added workflow": lambda root: (
                root / ".github/workflows/spoof.yml"
            ).write_text("name: spoof\n", encoding="utf-8"),
            "added checkout attributes": lambda root: (
                root / ".gitattributes"
            ).write_text("* text\n", encoding="utf-8"),
            "added submodule policy": lambda root: (root / ".gitmodules").write_text(
                "[submodule 'candidate']\n", encoding="utf-8"
            ),
        }

        for label, mutate in mutations.items():
            with self.subTest(label):
                _, base, head, base_commit = self.make_checkouts()
                mutate(head)
                head_commit = commit_all(head, label)
                with self.assertRaisesRegex(RuntimeError, "protected path"):
                    self.verify(base, head, base_commit, head_commit)

        for relative in PROTECTED_FILES:
            with self.subTest(protected=relative):
                _, base, head, base_commit = self.make_checkouts()
                (head / relative).write_text(
                    "candidate mutation\n",
                    encoding="utf-8",
                )
                head_commit = commit_all(head, f"changed {relative}")
                with self.assertRaisesRegex(RuntimeError, "protected path"):
                    self.verify(base, head, base_commit, head_commit)

    def test_mode_and_symlink_transitions_are_rejected(self) -> None:
        _, base, head, base_commit = self.make_checkouts()
        scanner = head / "scripts/privacy-scan"
        scanner.chmod(scanner.stat().st_mode | stat.S_IXUSR)
        head_commit = commit_all(head, "mode")
        with self.assertRaisesRegex(RuntimeError, "protected path"):
            self.verify(base, head, base_commit, head_commit)

        _, base, head, base_commit = self.make_checkouts()
        age_path = head / "home/private.age"
        age_path.unlink()
        age_path.symlink_to("elsewhere")
        head_commit = commit_all(head, "symlink")
        with self.assertRaisesRegex(RuntimeError, "protected path"):
            self.verify(base, head, base_commit, head_commit)

    def test_exact_checkout_identities_are_required(self) -> None:
        _, base, head, _base_commit = self.make_checkouts()
        (head / "README.md").write_text("candidate\n", encoding="utf-8")
        head_commit = commit_all(head, "head")

        with self.assertRaisesRegex(RuntimeError, "expected commit"):
            self.verify(base, head, "0" * 40, head_commit)

    def test_cli_reports_only_the_boundary_failure(self) -> None:
        _, base, head, base_commit = self.make_checkouts()
        sensitive = "private-candidate-ciphertext"
        (head / "home/private.age").write_text(sensitive, encoding="utf-8")
        head_commit = commit_all(head, "changed")

        result = subprocess.run(
            [
                sys.executable,
                os.fspath(GATE),
                "--base-repository",
                os.fspath(base),
                "--base-commit",
                base_commit,
                "--head-repository",
                os.fspath(head),
                "--head-commit",
                head_commit,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("candidate changes 1 protected path", result.stderr)
        self.assertNotIn(sensitive, result.stdout + result.stderr)
