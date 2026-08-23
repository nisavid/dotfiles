from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.privacy_age_admission import (
    ADMISSION_NAMESPACE,
    ADMISSION_PRINCIPAL,
    ADMISSION_VERSION,
    canonical_payload_bytes,
    encode_receipt,
)
from scripts.privacy_age_integrity_gate import (
    ACTIVE_REQUIRED_PATHS,
    ADMISSION_ACTIVATION_MARKER,
    BOOTSTRAP_REVIEWED_AUTHORITY_ENTRIES,
    BOOTSTRAP_REVIEWED_SIGNER_ENTRY,
    BOOTSTRAP_REVIEWED_SUPPORT_ENTRIES,
    verify_integrity_boundary,
)

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts/privacy_age_integrity_gate.py"
WORKFLOW = ROOT / ".github/workflows/privacy-age-integrity.yml"

UNTRUSTED_HEAD_EXECUTION = re.compile(
    r"(?mx)^\s*(?:"
    r"(?:uses|working-directory):\s*(?:\./)?untrusted-head(?:/|$)"
    r"|(?:run:\s*)?(?:\./)?untrusted-head/"
    r"|(?:run:\s*)?[^\n]*(?:\b(?:cd|source)\s+|\.\s+)"
    r"(?:[\"']?[^\s\"']*/)?(?:\./)?untrusted-head(?:/|[\"']?(?:\s|$))"
    r"|(?:run:\s*)?[^\n]*\b(?:python[0-9.]*|bash|sh|zsh|ruby|perl|node|make|npm|npx)"
    r"\b[^\n]*\buntrusted-head/"
    r"|(?:run:\s*)?[^\n]*(?:&&|\|\||;)\s*(?:\./)?untrusted-head/"
    r")"
)

PROTECTED_FILES = {
    # These are placeholders for fixture-only paths. REAL_SOURCE_FILES below
    # is copied directly from the reviewed repository.
    ".github/actions/privacy-boundary/action.yml": "name: boundary action\n",
    ".privacy-age-envelopes.json": "{}\n",
    "home/.chezmoi.toml.tmpl": "recipient = 'fixture'\n",
    "home/private_dot_local/lib/agent-equipment/agent_equipment/secrets.py": (
        "# classifier implementation\n"
    ),
    "home/private.age": "ciphertext fixture\n",
    "scripts/agent_equipment_public_data.py": "# policy\n",
}
REAL_SOURCE_FILES = (
    ".github/age-admission/allowed_signers",
    "scripts/admit-age-envelopes",
    "scripts/privacy-scan",
    "scripts/create-age-admission-receipt",
    "scripts/privacy_age_admission.py",
    "scripts/privacy_age_envelopes.py",
    "scripts/run-trusted-age-admission",
    "scripts/privacy_age_integrity_gate.py",
    ".github/workflows/platform-portability.yml",
    ".github/workflows/privacy-age-integrity.yml",
    "docs/ENCRYPTION.md",
)
BOOTSTRAP_REQUIRED_MODES = {
    ".github/age-admission/allowed_signers": 0o644,
    ".github/workflows/privacy-age-integrity.yml": 0o644,
    "scripts/admit-age-envelopes": 0o755,
    "scripts/privacy-scan": 0o755,
    "scripts/create-age-admission-receipt": 0o755,
    "scripts/run-trusted-age-admission": 0o755,
    "scripts/privacy_age_admission.py": 0o644,
    "scripts/privacy_age_envelopes.py": 0o644,
    "scripts/privacy_age_integrity_gate.py": 0o755,
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
    for relative in REAL_SOURCE_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / relative).read_bytes())
    for relative, mode in BOOTSTRAP_REQUIRED_MODES.items():
        (root / relative).chmod(mode)


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
        self,
        base: Path,
        head: Path,
        base_commit: str,
        head_commit: str,
        *,
        admission_body: bytes | None = None,
        allowed_signers: Path | None = None,
        repository: str | None = None,
    ) -> None:
        verify_integrity_boundary(
            base_repository=base,
            base_commit=base_commit,
            head_repository=head,
            head_commit=head_commit,
            admission_body=admission_body,
            allowed_signers=allowed_signers,
            repository=repository,
        )

    def test_bootstrap_support_allowlist_matches_reviewed_tree(self) -> None:
        self.assertTrue(BOOTSTRAP_REVIEWED_SUPPORT_ENTRIES)
        for raw_path, (kind, mode, object_id) in BOOTSTRAP_REVIEWED_SUPPORT_ENTRIES.items():
            path = ROOT / os.fsdecode(raw_path)
            self.assertEqual(kind, b"blob")
            staged = run(
                "git",
                "ls-files",
                "--stage",
                "--",
                os.fspath(path.relative_to(ROOT)),
                cwd=ROOT,
            )
            self.assertTrue(staged, f"reviewed support path is not tracked: {path}")
            tracked_mode = staged.split(maxsplit=1)[0].encode()
            self.assertEqual(
                mode,
                tracked_mode,
            )
            self.assertEqual(
                object_id.decode("ascii"),
                run("git", "hash-object", "--", os.fspath(path), cwd=ROOT),
            )

    def test_bootstrap_signer_allowlist_matches_reviewed_tree(self) -> None:
        path = ROOT / ".github/age-admission/allowed_signers"
        self.assertEqual(
            BOOTSTRAP_REVIEWED_SIGNER_ENTRY[2].decode("ascii"),
            run("git", "hash-object", "--", os.fspath(path), cwd=ROOT),
        )
        staged = run(
            "git",
            "ls-files",
            "--stage",
            "--",
            os.fspath(path.relative_to(ROOT)),
            cwd=ROOT,
        )
        self.assertTrue(staged, f"reviewed signer path is not tracked: {path}")
        self.assertEqual(
            BOOTSTRAP_REVIEWED_SIGNER_ENTRY[:2],
            (b"blob", staged.split(maxsplit=1)[0].encode()),
        )

    def test_bootstrap_authority_allowlist_matches_reviewed_tree(self) -> None:
        self.assertTrue(BOOTSTRAP_REVIEWED_AUTHORITY_ENTRIES)
        for raw_path, (kind, mode, object_id) in BOOTSTRAP_REVIEWED_AUTHORITY_ENTRIES.items():
            path = ROOT / os.fsdecode(raw_path)
            staged = run(
                "git",
                "ls-files",
                "--stage",
                "--",
                os.fspath(path.relative_to(ROOT)),
                cwd=ROOT,
            )
            self.assertTrue(staged, f"reviewed authority path is not tracked: {path}")
            self.assertEqual((kind, mode), (b"blob", staged.split(maxsplit=1)[0].encode()))
            self.assertEqual(
                object_id.decode("ascii"),
                run("git", "hash-object", "--", os.fspath(path), cwd=ROOT),
            )

    def test_bootstrap_required_modes_match_reviewed_tree(self) -> None:
        for relative, expected_mode in BOOTSTRAP_REQUIRED_MODES.items():
            with self.subTest(relative=relative):
                staged = run("git", "ls-files", "--stage", "--", relative, cwd=ROOT)
                self.assertTrue(staged, f"required path is not tracked: {relative}")
                self.assertEqual(
                    expected_mode,
                    int(staged.split(maxsplit=1)[0], 8) & 0o777,
                )

    def test_activation_marker_is_present_in_the_protected_workflow(self) -> None:
        workflow = WORKFLOW.read_bytes()
        self.assertIn(ADMISSION_ACTIVATION_MARKER, workflow.splitlines(keepends=True))

    def test_prebootstrap_preseeded_infrastructure_does_not_activate_the_gate(self) -> None:
        _, base, head, _ = self.make_checkouts()
        for relative in (
            ".github/age-admission/allowed_signers",
            "scripts/create-age-admission-receipt",
            "scripts/run-trusted-age-admission",
            "scripts/privacy_age_admission.py",
        ):
            (base / relative).write_text("attacker-controlled placeholder\n", encoding="ascii")
        (base / ".github/workflows/privacy-age-integrity.yml").write_text(
            "name: boundary\n",
            encoding="ascii",
        )
        base_commit = commit_all(base, "pre-seeded admission placeholders")
        (head / "home/private.age").write_text("candidate transition\n", encoding="ascii")
        head_commit = commit_all(head, "candidate protected transition")

        with self.assertRaisesRegex(
            RuntimeError,
            "bootstrap candidate is not limited to admission infrastructure",
        ):
            self.verify(base, head, base_commit, head_commit)

    def test_active_boundary_cannot_remove_its_activation_marker(self) -> None:
        _, base, head, base_commit = self.make_checkouts()
        workflow = head / ".github/workflows/privacy-age-integrity.yml"
        workflow.write_text("name: boundary\n", encoding="ascii")
        (head / "home/private.age").write_text("candidate transition\n", encoding="ascii")
        head_commit = commit_all(head, "remove activation marker")

        with self.assertRaisesRegex(RuntimeError, "activation sentinel"):
            self.verify(base, head, base_commit, head_commit)

    def test_active_boundary_cannot_remove_admission_infrastructure(self) -> None:
        _, base, head, base_commit = self.make_checkouts()
        (head / "scripts/run-trusted-age-admission").unlink()
        (head / "home/private.age").write_text("candidate transition\n", encoding="ascii")
        head_commit = commit_all(head, "remove admission launcher")

        with self.assertRaisesRegex(RuntimeError, "infrastructure must remain complete"):
            self.verify(base, head, base_commit, head_commit)

    def test_active_boundary_cannot_remove_any_trusted_enforcement_seam(self) -> None:
        self.assertTrue(ACTIVE_REQUIRED_PATHS)
        for raw_relative in sorted(ACTIVE_REQUIRED_PATHS):
            relative = os.fsdecode(raw_relative)
            with self.subTest(relative=relative):
                _, base, head, base_commit = self.make_checkouts()
                self.assertTrue(
                    (head / relative).is_file(),
                    f"fixture does not create the active seam: {relative}",
                )
                (head / relative).unlink()
                (head / "home/private.age").write_text(
                    "candidate transition\n",
                    encoding="utf-8",
                )
                head_commit = commit_all(head, f"remove active seam {relative}")
                with self.assertRaisesRegex(RuntimeError, "infrastructure must remain complete"):
                    self.verify(base, head, base_commit, head_commit)

    def test_prebootstrap_base_requires_the_explicit_owner_exception(self) -> None:
        _, base, head, _ = self.make_checkouts()
        (base / ".github/workflows/privacy-age-integrity.yml").write_text(
            "name: boundary\n",
            encoding="ascii",
        )
        for relative in (
            "scripts/admit-age-envelopes",
            "scripts/privacy-scan",
            "scripts/privacy_age_envelopes.py",
            "scripts/privacy_age_integrity_gate.py",
        ):
            (base / relative).write_text("legacy bootstrap seam\n", encoding="ascii")
        for relative in (
            ".github/age-admission/allowed_signers",
            "scripts/create-age-admission-receipt",
            "scripts/run-trusted-age-admission",
            "scripts/privacy_age_admission.py",
        ):
            (base / relative).unlink()
        base_commit = commit_all(base, "pre-bootstrap base")
        (head / "bootstrap-fixture.txt").write_text(
            "unprotected bootstrap fixture\n",
            encoding="ascii",
        )
        head_commit = commit_all(head, "complete bootstrap candidate")

        with self.assertRaisesRegex(RuntimeError, "bootstrap owner exception"):
            self.verify(base, head, base_commit, head_commit)

        (head / "scripts/admit-age-envelopes").write_text("#!/bin/sh\n", encoding="ascii")
        (head / "scripts/admit-age-envelopes").chmod(0o755)
        stale_head_commit = commit_all(head, "stale bootstrap candidate")
        with self.assertRaisesRegex(RuntimeError, "complete admission infrastructure"):
            self.verify(base, head, base_commit, stale_head_commit)

        (head / "scripts/create-age-admission-receipt").unlink()
        incomplete_head_commit = commit_all(head, "incomplete bootstrap candidate")
        with self.assertRaisesRegex(RuntimeError, "complete admission infrastructure"):
            self.verify(base, head, base_commit, incomplete_head_commit)

    def test_bootstrap_requires_regular_entries_with_expected_modes(self) -> None:
        for malformed in ("mode", "symlink"):
            with self.subTest(malformed=malformed):
                _, base, head, _ = self.make_checkouts()
                for relative in (
                    ".github/age-admission/allowed_signers",
                    "scripts/create-age-admission-receipt",
                    "scripts/run-trusted-age-admission",
                    "scripts/privacy_age_admission.py",
                ):
                    (base / relative).unlink()
                base_commit = commit_all(base, f"pre-bootstrap {malformed}")
                for relative, mode in BOOTSTRAP_REQUIRED_MODES.items():
                    path = head / relative
                    path.write_bytes((ROOT / relative).read_bytes())
                    path.chmod(mode)
                malformed_path = head / "scripts/create-age-admission-receipt"
                if malformed == "mode":
                    malformed_path.chmod(0o644)
                else:
                    malformed_path.unlink()
                    malformed_path.symlink_to("admit-age-envelopes")
                head_commit = commit_all(head, f"malformed bootstrap {malformed}")
                with self.assertRaisesRegex(RuntimeError, "complete admission infrastructure"):
                    self.verify(base, head, base_commit, head_commit)

    def test_bootstrap_rejects_collateral_protected_changes(self) -> None:
        _, base, head, _ = self.make_checkouts()
        for relative in (
            ".github/age-admission/allowed_signers",
            "scripts/create-age-admission-receipt",
            "scripts/run-trusted-age-admission",
            "scripts/privacy_age_admission.py",
        ):
            (base / relative).unlink()
        base_commit = commit_all(base, "pre-bootstrap collateral base")
        for relative, mode in BOOTSTRAP_REQUIRED_MODES.items():
            path = head / relative
            path.write_text("bootstrap replacement\n", encoding="utf-8")
            path.chmod(mode)
        (head / "home/private.age").write_text(
            "collateral ciphertext\n",
            encoding="utf-8",
        )
        head_commit = commit_all(head, "bootstrap with collateral protected change")
        with self.assertRaisesRegex(RuntimeError, "not limited"):
            self.verify(base, head, base_commit, head_commit)

    def test_signed_admission_accepts_only_the_exact_transition(self) -> None:
        temporary, base, head, base_commit = self.make_checkouts()
        key = Path(temporary.name) / "admission-key"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
            check=True,
            capture_output=True,
            timeout=10,
        )
        public_key = (Path(f"{key}.pub")).read_text(encoding="ascii").split()
        (base / ".github/age-admission/allowed_signers").write_text(
            f'{ADMISSION_PRINCIPAL} namespaces="{ADMISSION_NAMESPACE}" '
            f"{public_key[0]} {public_key[1]}\n",
            encoding="ascii",
        )
        base_commit = commit_all(base, "signer")
        (head / ".github/age-admission/allowed_signers").write_text(
            f'{ADMISSION_PRINCIPAL} namespaces="{ADMISSION_NAMESPACE}" '
            f"{public_key[0]} {public_key[1]}\n",
            encoding="ascii",
        )
        (head / "home/private.age").write_text(
            "candidate ciphertext\n",
            encoding="utf-8",
        )
        head_commit = commit_all(head, "protected transition")

        base_bytes = subprocess.run(
            ["git", "show", f"{base_commit}:home/private.age"],
            cwd=base,
            check=True,
            capture_output=True,
            timeout=10,
        ).stdout
        head_bytes = subprocess.run(
            ["git", "show", f"{head_commit}:home/private.age"],
            cwd=head,
            check=True,
            capture_output=True,
            timeout=10,
        ).stdout
        now = datetime.now(timezone.utc).replace(microsecond=0)
        payload = {
            "base_commit": base_commit,
            "expires_at": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "head_commit": head_commit,
            "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "nonce": "b" * 32,
            "paths": [
                {
                    "base": {
                        "kind": "blob",
                        "mode": "100644",
                        "sha256": "sha256:" + hashlib.sha256(base_bytes).hexdigest(),
                    },
                    "head": {
                        "kind": "blob",
                        "mode": "100644",
                        "sha256": "sha256:" + hashlib.sha256(head_bytes).hexdigest(),
                    },
                    "path": "home/private.age",
                }
            ],
            "repository": "nisavid/dotfiles",
            "version": ADMISSION_VERSION,
        }
        message = canonical_payload_bytes(payload)
        message_file = Path(temporary.name) / "payload"
        message_file.write_bytes(message)
        subprocess.run(
            [
                "ssh-keygen",
                "-Y",
                "sign",
                "-f",
                str(key),
                "-n",
                ADMISSION_NAMESPACE,
                str(message_file),
            ],
            check=True,
            capture_output=True,
            timeout=10,
        )
        receipt = encode_receipt(payload, (message_file.with_suffix(".sig")).read_bytes())

        self.verify(
            base,
            head,
            base_commit,
            head_commit,
            admission_body=receipt,
            allowed_signers=base / ".github/age-admission/allowed_signers",
            repository="nisavid/dotfiles",
        )

        tampered = dict(payload)
        tampered["head_commit"] = "f" * 40
        tampered_message_file = Path(temporary.name) / "tampered-payload"
        tampered_message_file.write_bytes(canonical_payload_bytes(tampered))
        subprocess.run(
            [
                "ssh-keygen",
                "-Y",
                "sign",
                "-f",
                str(key),
                "-n",
                ADMISSION_NAMESPACE,
                str(tampered_message_file),
            ],
            check=True,
            capture_output=True,
            timeout=10,
        )
        with self.assertRaisesRegex(RuntimeError, "admission receipt is not authorized"):
            self.verify(
                base,
                head,
                base_commit,
                head_commit,
                admission_body=encode_receipt(
                    tampered,
                    (tampered_message_file.with_suffix(".sig")).read_bytes(),
                ),
                allowed_signers=base / ".github/age-admission/allowed_signers",
                repository="nisavid/dotfiles",
            )

    def test_unrelated_candidate_changes_are_allowed(self) -> None:
        _, base, head, base_commit = self.make_checkouts()
        (head / "README.md").write_text("candidate docs\n", encoding="utf-8")
        head_commit = commit_all(head, "unrelated")

        self.verify(base, head, base_commit, head_commit)

    def test_workflow_executables_start_in_isolated_mode(self) -> None:
        for executable in (GATE, ROOT / "scripts/privacy-scan"):
            with self.subTest(executable=os.fspath(executable)):
                result = subprocess.run(
                    [sys.executable, "-I", os.fspath(executable), "--help"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_workflow_rechecks_retargets_and_treats_fork_head_as_data(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('\nenv:\n  AGE_VERSION: "1.3.1"\n', source)
        self.assertEqual(source.count('AGE_VERSION: "1.3.1"'), 1)
        self.assertIn(
            'test "$("$AGE_TOOLING_DIRECTORY/age-inspect" --version)" '
            '= "v${AGE_VERSION}"',
            source,
        )
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
            "python3 -I trusted-base/scripts/privacy_age_integrity_gate.py", source
        )
        self.assertIn('PRIVACY_REPOSITORY: ${{ github.repository }}', source)
        self.assertIn('python3 -I - "$GITHUB_EVENT_PATH"', source)
        self.assertIn('privacy-age-admission-body', source)
        self.assertIn("pull request event is not an object", source)
        self.assertIn("os.O_EXCL", source)
        self.assertIn("0o600", source)
        self.assertRegex(
            source,
            r"(?s)destination,\s*os\.O_WRONLY\s*\|\s*os\.O_CREAT\s*\|\s*os\.O_EXCL\s*\|\s*no_follow,\s*0o600",
        )
        self.assertIn("verify_filesystem_entries", source)
        self.assertIn(
            '--allowed-signers trusted-base/.github/age-admission/allowed_signers',
            source,
        )
        self.assertIn('--admission-body "$RUNNER_TEMP/privacy-age-admission-body"', source)
        self.assertIn('--repository "$PRIVACY_REPOSITORY"', source)
        self.assertIn("python3 -I trusted-base/scripts/privacy-scan", source)
        self.assertNotIn("python3 untrusted-head/", source)
        untrusted_lines = tuple(
            line.strip() for line in source.splitlines() if "untrusted-head" in line
        )
        self.assertTrue(any(line.startswith("path: untrusted-head") for line in untrusted_lines))
        self.assertTrue(
            any(
                "git -C untrusted-head rev-parse HEAD" in line
                and "PRIVACY_HEAD_SHA" in line
                for line in untrusted_lines
            )
        )
        self.assertTrue(
            any("--head-repository untrusted-head" in line for line in untrusted_lines)
        )
        self.assertTrue(
            any('--root "$GITHUB_WORKSPACE/untrusted-head"' in line for line in untrusted_lines)
        )
        self.assertTrue(
            any(
                'python3 -I - "$PRIVACY_BASE_SHA" trusted-base "$PRIVACY_HEAD_SHA"' in line
                and "untrusted-head" in line
                for line in untrusted_lines
            )
        )
        self.assertIsNone(UNTRUSTED_HEAD_EXECUTION.search(source))

    def test_workflow_preimport_verifier_is_valid_python(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")
        matches = list(
            re.finditer(
                r"python3 -I - [^\n]*<<'PY'\n(?P<body>.*?)\n[ \t]+PY\n",
                source,
                re.DOTALL,
            )
        )
        self.assertEqual(
            len(matches),
            2,
            "expected the event extractor and checkout verifier heredocs",
        )
        for match in matches:
            compile(textwrap.dedent(match.group("body")), str(WORKFLOW), "exec")

    def test_untrusted_head_execution_guard_rejects_inline_shell_forms(self) -> None:
        for unsafe_line in (
            "run: cd untrusted-head && ./scripts/privacy-scan",
            "run: cd /tmp/work/untrusted-head && ./scripts/privacy-scan",
            "run: source untrusted-head/scripts/privacy-scan",
            "run: . untrusted-head/scripts/privacy-scan",
            "run: python3 untrusted-head/scripts/privacy-scan",
            "run: /usr/bin/python3.12 untrusted-head/scripts/privacy-scan",
            "run: printf ready && untrusted-head/scripts/privacy-scan",
        ):
            with self.subTest(unsafe_line=unsafe_line):
                self.assertIsNotNone(UNTRUSTED_HEAD_EXECUTION.search(unsafe_line))

        for safe_line in (
            "run: echo cpython3 untrusted-head/data",
            "run: echo shell untrusted-head/data",
        ):
            with self.subTest(safe_line=safe_line):
                self.assertIsNone(UNTRUSTED_HEAD_EXECUTION.search(safe_line))

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
                with self.assertRaisesRegex(RuntimeError, r"candidate changes .* protected path"):
                    self.verify(base, head, base_commit, head_commit)

        for relative in PROTECTED_FILES:
            with self.subTest(protected=relative):
                _, base, head, base_commit = self.make_checkouts()
                (head / relative).write_text(
                    "candidate mutation\n",
                    encoding="utf-8",
                )
                head_commit = commit_all(head, f"changed {relative}")
                with self.assertRaisesRegex(RuntimeError, r"candidate changes .* protected path"):
                    self.verify(base, head, base_commit, head_commit)

    def test_mode_and_symlink_transitions_are_rejected(self) -> None:
        _, base, head, base_commit = self.make_checkouts()
        scanner = head / "scripts/privacy-scan"
        scanner.chmod(0o644)
        head_commit = commit_all(head, "mode")
        with self.assertRaisesRegex(
            RuntimeError,
            "active admission infrastructure must remain complete",
        ):
            self.verify(base, head, base_commit, head_commit)

        _, base, head, base_commit = self.make_checkouts()
        age_path = head / "home/private.age"
        age_path.unlink()
        age_path.symlink_to("elsewhere")
        head_commit = commit_all(head, "symlink")
        with self.assertRaisesRegex(RuntimeError, r"candidate changes .* protected path"):
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
            timeout=10,
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("candidate changes 1 protected path", result.stderr)
        self.assertNotIn(sensitive, result.stdout + result.stderr)
