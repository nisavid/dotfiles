from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import scripts.privacy_age_integrity_gate as _gate
from scripts.privacy_age_admission import (
    ADMISSION_NAMESPACE,
    ADMISSION_PRINCIPAL,
    ADMISSION_VERSION,
    canonical_payload_bytes,
    encode_receipt,
)
from scripts.privacy_age_admission_result import body_digest, make_snapshot
from scripts.privacy_age_integrity_gate import (
    ACTIVE_REQUIRED_PATHS,
    ADMISSION_ACTIVATION_MARKER,
    BOOTSTRAP_REVIEWED_AUTHORITY_ENTRIES,
    BOOTSTRAP_REVIEWED_SIGNER_ENTRY,
    BOOTSTRAP_REVIEWED_SUPPORT_ENTRIES,
    evaluate_integrity_boundary,
    verify_integrity_boundary,
)

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts/privacy_age_integrity_gate.py"
WORKFLOW = ROOT / ".github/workflows/privacy-age-integrity.yml"
LEGACY_FIXTURE_ROOT = ROOT / "tests/fixtures/privacy-age-integrity"
LEGACY_FIXTURE_MANIFEST = LEGACY_FIXTURE_ROOT / "legacy-active-base-v1.json"

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
    ".github/age-admission/privacy-scan-reviewed-findings-v1.json",
    "scripts/admit-age-envelopes",
    "scripts/privacy-scan",
    "scripts/privacy_scan_review.py",
    "scripts/create-age-admission-receipt",
    "scripts/privacy_age_admission.py",
    "scripts/privacy_age_envelopes.py",
    "scripts/run-trusted-age-admission",
    "scripts/privacy_age_integrity_gate.py",
    "scripts/privacy_age_admission_result.py",
    "scripts/privacy_age_pr_snapshot.py",
    "scripts/privacy_age_admission_publisher.py",
    ".github/workflows/platform-portability.yml",
    ".github/workflows/privacy-age-integrity.yml",
    "docs/ENCRYPTION.md",
)
BOOTSTRAP_REQUIRED_MODES = {
    ".github/age-admission/allowed_signers": 0o644,
    ".github/workflows/privacy-age-integrity.yml": 0o644,
    "scripts/admit-age-envelopes": 0o755,
    "scripts/privacy-scan": 0o755,
    "scripts/privacy_scan_review.py": 0o644,
    ".github/age-admission/privacy-scan-reviewed-findings-v1.json": 0o644,
    "scripts/create-age-admission-receipt": 0o755,
    "scripts/run-trusted-age-admission": 0o755,
    "scripts/privacy_age_admission.py": 0o644,
    "scripts/privacy_age_envelopes.py": 0o644,
    "scripts/privacy_age_integrity_gate.py": 0o755,
    "scripts/privacy_age_admission_result.py": 0o644,
    "scripts/privacy_age_pr_snapshot.py": 0o644,
    "scripts/privacy_age_admission_publisher.py": 0o644,
}
ADMISSION_INFRASTRUCTURE_FIXTURE_PATHS = (
    ".github/age-admission/allowed_signers",
    ".github/age-admission/privacy-scan-reviewed-findings-v1.json",
    "scripts/create-age-admission-receipt",
    "scripts/run-trusted-age-admission",
    "scripts/privacy_age_admission.py",
    "scripts/privacy_scan_review.py",
    "scripts/privacy_age_admission_result.py",
    "scripts/privacy_age_pr_snapshot.py",
    "scripts/privacy_age_admission_publisher.py",
)
LEGACY_ADMISSION_INFRASTRUCTURE_FIXTURE_PATHS = tuple(
    relative
    for relative in ADMISSION_INFRASTRUCTURE_FIXTURE_PATHS
    if relative
    not in {
        ".github/age-admission/privacy-scan-reviewed-findings-v1.json",
        "scripts/privacy_scan_review.py",
    }
)
REVIEW_INFRASTRUCTURE_ADDITIONS = (
    ".github/age-admission/privacy-scan-reviewed-findings-v1.json",
    "scripts/privacy_scan_review.py",
)


def fixture_git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for variable in (
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_LOCAL",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_SYSTEM",
        "GIT_DEFAULT_HASH",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_WORK_TREE",
    ):
        environment.pop(variable, None)
    for variable in tuple(environment):
        if variable.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            environment.pop(variable, None)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    return environment


def run(*command: str, cwd: Path) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=fixture_git_environment(),
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


def materialize_legacy_fixture(root: Path) -> dict[str, object]:
    manifest = json.loads(LEGACY_FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema") != "privacy-age-integrity-predecessor-fixture/v1":
        raise AssertionError("legacy fixture manifest has an unexpected schema")
    pack_spec = manifest["pack"]
    snapshot = manifest["snapshot"]
    if not isinstance(pack_spec, dict) or not isinstance(snapshot, dict):
        raise AssertionError("legacy fixture manifest is malformed")

    pack = LEGACY_FIXTURE_ROOT / str(pack_spec["path"])
    pack_bytes = pack.read_bytes()
    if len(pack_bytes) != pack_spec["size"]:
        raise AssertionError("legacy fixture pack size does not match its manifest")
    if hashlib.sha256(pack_bytes).hexdigest() != pack_spec["sha256"]:
        raise AssertionError("legacy fixture pack digest does not match its manifest")

    root.mkdir()
    run("git", "init", "--quiet", "--object-format=sha1", cwd=root)
    environment = fixture_git_environment()
    subprocess.run(
        ["git", "index-pack", "--stdin", "--fix-thin"],
        cwd=root,
        input=pack_bytes,
        check=True,
        capture_output=True,
        env=environment,
        timeout=10,
    )
    commit = str(snapshot["commit"])
    if snapshot["shallow_boundary"] != commit:
        raise AssertionError("legacy fixture shallow boundary is not the commit")
    git_dir = root / run("git", "rev-parse", "--git-dir", cwd=root)
    (git_dir / "shallow").write_text(f"{commit}\n", encoding="ascii")
    run("git", "checkout", "--quiet", "--detach", commit, cwd=root)

    commit_data = run("git", "cat-file", "-p", commit, cwd=root)
    parents = [
        line.split(maxsplit=1)[1]
        for line in commit_data.splitlines()
        if line.startswith("parent ")
    ]
    if parents != [snapshot["omitted_parent"]]:
        raise AssertionError("legacy fixture omitted parent does not match its manifest")
    omitted_parent = subprocess.run(
        ["git", "cat-file", "-e", f'{snapshot["omitted_parent"]}^{{commit}}'],
        cwd=root,
        check=False,
        capture_output=True,
        env=environment,
        timeout=10,
    )
    if omitted_parent.returncode == 0:
        raise AssertionError("legacy fixture unexpectedly includes parent history")
    if run("git", "rev-parse", "HEAD^{tree}", cwd=root) != snapshot["root_tree"]:
        raise AssertionError("legacy fixture root tree does not match its manifest")
    gate_entry = run(
        "git",
        "ls-tree",
        commit,
        "scripts/privacy_age_integrity_gate.py",
        cwd=root,
    )
    if gate_entry.split()[2] != snapshot["integrity_gate_blob"]:
        raise AssertionError("legacy fixture gate blob does not match its manifest")
    indexes = tuple((git_dir / "objects/pack").glob("*.idx"))
    if len(indexes) != 1:
        raise AssertionError("legacy fixture did not produce one object index")
    with indexes[0].open("rb") as index:
        indexed = subprocess.run(
            ["git", "show-index"],
            cwd=root,
            stdin=index,
            check=True,
            capture_output=True,
            env=environment,
            timeout=10,
        )
    if len(indexed.stdout.splitlines()) != pack_spec["object_count"]:
        raise AssertionError("legacy fixture object count does not match its manifest")
    return manifest


def materialize_current_candidate(root: Path) -> tuple[str, str]:
    reviewed_commit = run("git", "rev-parse", "HEAD^{commit}", cwd=ROOT)
    reviewed_tree = run("git", "rev-parse", f"{reviewed_commit}^{{tree}}", cwd=ROOT)
    run(
        "git",
        "clone",
        "--quiet",
        "--no-local",
        "--no-checkout",
        os.fspath(ROOT),
        os.fspath(root),
        cwd=root.parent,
    )
    run("git", "checkout", "--quiet", "--detach", reviewed_commit, cwd=root)
    if run("git", "rev-parse", "HEAD^{commit}", cwd=root) != reviewed_commit:
        raise AssertionError("candidate fixture commit does not match the reviewed commit")
    if run("git", "rev-parse", "HEAD^{tree}", cwd=root) != reviewed_tree:
        raise AssertionError("candidate fixture tree does not match the reviewed tree")
    return reviewed_commit, reviewed_tree


def build_payload_in_subprocess(
    *,
    scripts: Path,
    base: Path,
    base_commit: str,
    head: Path,
    head_commit: str,
) -> dict[str, object]:
    program = textwrap.dedent(
        """
        import json
        import os
        import sys
        from datetime import datetime, timedelta, timezone
        from pathlib import Path

        sys.path.insert(0, sys.argv[1])
        import privacy_age_integrity_gate as gate

        now = datetime.now(timezone.utc).replace(microsecond=0)
        payload = gate.build_admission_payload(
            base_repository=Path(sys.argv[2]),
            base_commit=sys.argv[3],
            head_repository=Path(sys.argv[4]),
            head_commit=sys.argv[5],
            repository="nisavid/dotfiles",
            issued_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            expires_at=(now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            nonce="a" * 32,
        )
        print(json.dumps({
            "infrastructure": sorted(
                os.fsdecode(path) for path in gate.ADMISSION_INFRASTRUCTURE_PATHS
            ),
            "payload": payload,
        }, sort_keys=True))
        """
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            program,
            os.fspath(scripts),
            os.fspath(base),
            base_commit,
            os.fspath(head),
            head_commit,
        ],
        cwd=base.parent,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"isolated admission payload failed with {result.returncode}: {result.stderr}"
        )
    return json.loads(result.stdout)


class PrivacyAgeIntegrityGateTests(TestCase):
    def make_checkouts(self) -> tuple[TemporaryDirectory[str], Path, Path, str]:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name) / "base"
        head = Path(temporary.name) / "head"
        base.mkdir()
        run("git", "init", "--quiet", "--object-format=sha1", cwd=base)
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

    def test_bootstrap_support_allowlist_matches_reviewed_fixture(self) -> None:
        reviewed_fixture = {
            b".github/workflows/privacy-age-integrity.yml": (
                b"blob",
                b"100644",
                b"ac6d1610d245bac428b56504d7872b3424e4523f",
            ),
            b".github/workflows/platform-portability.yml": (
                b"blob",
                b"100644",
                b"fea93f6a2805d1899722f806ecd11d40c6c259c6",
            ),
            b"docs/ENCRYPTION.md": (
                b"blob",
                b"100644",
                b"b2ec72a28224c69d1aa8e326118c0ed79a187fb4",
            ),
        }
        self.assertEqual(BOOTSTRAP_REVIEWED_SUPPORT_ENTRIES, reviewed_fixture)
        for raw_path, (kind, mode, object_id) in BOOTSTRAP_REVIEWED_SUPPORT_ENTRIES.items():
            path = ROOT / os.fsdecode(raw_path)
            self.assertEqual(kind, b"blob")
            self.assertRegex(object_id.decode("ascii"), r"\A[0-9a-f]{40}\Z")
            tree_entry = run(
                "git",
                "ls-tree",
                "HEAD",
                "--",
                os.fspath(path.relative_to(ROOT)),
                cwd=ROOT,
            )
            self.assertTrue(tree_entry, f"reviewed support path is not tracked: {path}")
            metadata, tracked_path = tree_entry.split("\t", maxsplit=1)
            tracked_mode, tracked_kind, tracked_object_id = metadata.split()
            self.assertEqual(tracked_path, os.fspath(path.relative_to(ROOT)))
            self.assertEqual(mode, tracked_mode.encode())
            self.assertEqual(kind, tracked_kind.encode())
            if raw_path == b"docs/ENCRYPTION.md":
                self.assertEqual(object_id, tracked_object_id.encode())

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
            # Deliberately hash candidate bytes so a precommit run detects an
            # unstaged reviewed-blob change before the manifest can be rebuilt.
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

    def test_legacy_active_base_pin_matches_the_reviewed_predecessor(self) -> None:
        self.assertEqual(
            _gate.LEGACY_ACTIVE_BASE_COMMIT,
            "0e981202824a76043083039a407dd165e243d544",
        )
        self.assertEqual(
            set(_gate.LEGACY_ADMISSION_INFRASTRUCTURE_ENTRIES),
            {path.encode("ascii") for path in LEGACY_ADMISSION_INFRASTRUCTURE_FIXTURE_PATHS},
        )

    def test_actual_predecessor_cannot_install_the_nine_path_boundary(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name) / "base"
        head = Path(temporary.name) / "head"
        manifest = materialize_legacy_fixture(base)
        base_commit = str(manifest["snapshot"]["commit"])
        self.assertEqual(base_commit, "0e981202824a76043083039a407dd165e243d544")
        self.assertEqual(
            manifest["snapshot"]["omitted_parent"],
            "7fbe8e520cf85c16de4ba05b9b016b153340ed05",
        )
        head_commit, head_tree = materialize_current_candidate(head)
        self.assertEqual(
            head_tree,
            run("git", "rev-parse", f"{head_commit}^{{tree}}", cwd=ROOT),
        )

        predecessor = build_payload_in_subprocess(
            scripts=base / "scripts",
            base=base,
            base_commit=base_commit,
            head=head,
            head_commit=head_commit,
        )
        current = build_payload_in_subprocess(
            scripts=head / "scripts",
            base=base,
            base_commit=base_commit,
            head=head,
            head_commit=head_commit,
        )

        expected_predecessor_infrastructure = [
            ".github/age-admission/allowed_signers",
            "scripts/create-age-admission-receipt",
            "scripts/privacy_age_admission.py",
            "scripts/privacy_age_admission_publisher.py",
            "scripts/privacy_age_admission_result.py",
            "scripts/privacy_age_pr_snapshot.py",
            "scripts/run-trusted-age-admission",
        ]
        expected_review_additions = [
            ".github/age-admission/privacy-scan-reviewed-findings-v1.json",
            "scripts/privacy_scan_review.py",
        ]
        expected_predecessor_paths = [
            ".github/workflows/platform-portability.yml",
            "docs/ENCRYPTION.md",
            "scripts/privacy-scan",
            "scripts/privacy_age_integrity_gate.py",
        ]
        expected_current_paths = sorted(
            expected_predecessor_paths + expected_review_additions
        )
        self.assertEqual(
            predecessor["infrastructure"],
            expected_predecessor_infrastructure,
        )
        self.assertEqual(
            current["infrastructure"],
            sorted(expected_predecessor_infrastructure + expected_review_additions),
        )
        self.assertEqual(
            [entry["path"] for entry in predecessor["payload"]["paths"]],
            expected_predecessor_paths,
        )
        self.assertEqual(
            [entry["path"] for entry in current["payload"]["paths"]],
            expected_current_paths,
        )

        predecessor_receipt = encode_receipt(
            predecessor["payload"],
            b"not-a-signature",
        )
        with patch.object(_gate, "verify_receipt_signature") as verify_signature:
            with self.assertRaisesRegex(
                RuntimeError,
                "admission receipt is not authorized",
            ):
                self.verify(
                    base,
                    head,
                    base_commit,
                    head_commit,
                    admission_body=predecessor_receipt,
                    allowed_signers=base / ".github/age-admission/allowed_signers",
                    repository="nisavid/dotfiles",
                )
        verify_signature.assert_not_called()

        for relative in expected_review_additions:
            with self.subTest(missing=relative):
                run("git", "reset", "--hard", head_commit, cwd=head)
                (head / relative).unlink()
                incomplete_commit = commit_all(head, f"omit {relative}")
                with self.assertRaisesRegex(
                    RuntimeError,
                    "active admission infrastructure must remain complete",
                ):
                    _gate.build_admission_payload(
                        base_repository=base,
                        base_commit=base_commit,
                        head_repository=head,
                        head_commit=incomplete_commit,
                        repository="nisavid/dotfiles",
                        issued_at="2026-08-25T00:00:00Z",
                        expires_at="2026-08-25T01:00:00Z",
                        nonce="b" * 32,
                    )

    def test_unpinned_legacy_tree_is_not_reusable(self) -> None:
        _, base, head, _ = self.make_checkouts()
        for relative in REVIEW_INFRASTRUCTURE_ADDITIONS:
            (base / relative).unlink()
        base_commit = commit_all(base, "unrecognized legacy-shaped boundary")
        head_commit = run("git", "rev-parse", "HEAD", cwd=head)

        with self.assertRaisesRegex(RuntimeError, "invalid admission boundary"):
            self.verify(base, head, base_commit, head_commit)

    def test_partial_malformed_and_marker_inconsistent_bases_are_rejected(self) -> None:
        def seven_minus_one(root: Path) -> None:
            (root / ".github/age-admission/allowed_signers").unlink()

        def seven_plus_one_new(root: Path) -> None:
            relative = REVIEW_INFRASTRUCTURE_ADDITIONS[0]
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())

        def nine_minus_one(root: Path) -> None:
            for relative in REVIEW_INFRASTRUCTURE_ADDITIONS:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            (root / "scripts/privacy_age_admission_result.py").unlink()

        def wrong_mode(root: Path) -> None:
            (root / "scripts/privacy_age_admission_result.py").chmod(0o755)

        def wrong_kind(root: Path) -> None:
            target = root / "scripts/privacy_age_admission_result.py"
            target.unlink()
            target.mkdir()
            (target / "nested").write_text("not a blob\n", encoding="ascii")

        def symlink(root: Path) -> None:
            target = root / "scripts/privacy_age_admission_result.py"
            target.unlink()
            target.symlink_to("privacy_age_admission.py")

        def marker_mismatch(root: Path) -> None:
            (root / ".github/workflows/privacy-age-integrity.yml").write_text(
                "name: boundary\n",
                encoding="ascii",
            )

        mutations = {
            "seven-minus-one": seven_minus_one,
            "seven-plus-one-new": seven_plus_one_new,
            "nine-minus-one": nine_minus_one,
            "wrong-mode": wrong_mode,
            "wrong-kind": wrong_kind,
            "symlink": symlink,
            "marker-mismatch": marker_mismatch,
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                _, base, head, _ = self.make_checkouts()
                for relative in REVIEW_INFRASTRUCTURE_ADDITIONS:
                    (base / relative).unlink()
                mutate(base)
                base_commit = commit_all(base, label)
                head_commit = run("git", "rev-parse", "HEAD", cwd=head)
                with (
                    patch.object(_gate, "LEGACY_ACTIVE_BASE_COMMIT", base_commit),
                    patch.object(
                        _gate,
                        "_verify_admission",
                        side_effect=AssertionError("receipt parser was reached"),
                    ),
                    self.assertRaisesRegex(RuntimeError, "invalid admission boundary"),
                ):
                    self.verify(
                        base,
                        head,
                        base_commit,
                        head_commit,
                        admission_body=b"not a receipt",
                        repository="nisavid/dotfiles",
                    )

    def test_current_boundary_cannot_delete_review_infrastructure(self) -> None:
        for deleted in (
            REVIEW_INFRASTRUCTURE_ADDITIONS[:1],
            REVIEW_INFRASTRUCTURE_ADDITIONS[1:],
            REVIEW_INFRASTRUCTURE_ADDITIONS,
        ):
            with self.subTest(deleted=deleted):
                _, base, head, base_commit = self.make_checkouts()
                for relative in deleted:
                    (head / relative).unlink()
                head_commit = commit_all(head, "delete review infrastructure")
                with (
                    patch.object(
                        _gate,
                        "_verify_admission",
                        side_effect=AssertionError("receipt parser was reached"),
                    ),
                    self.assertRaisesRegex(
                        RuntimeError,
                        "active admission infrastructure must remain complete",
                    ),
                ):
                    self.verify(
                        base,
                        head,
                        base_commit,
                        head_commit,
                        admission_body=b"not a receipt",
                        repository="nisavid/dotfiles",
                    )

    def test_prebootstrap_preseeded_infrastructure_does_not_activate_the_gate(self) -> None:
        _, base, head, _ = self.make_checkouts()
        for relative in ADMISSION_INFRASTRUCTURE_FIXTURE_PATHS:
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
            "invalid admission boundary",
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
        for relative in ADMISSION_INFRASTRUCTURE_FIXTURE_PATHS:
            (base / relative).unlink()
        base_commit = commit_all(base, "pre-bootstrap base")
        for relative, mode in BOOTSTRAP_REQUIRED_MODES.items():
            path = head / relative
            path.write_bytes((ROOT / relative).read_bytes())
            path.chmod(mode)
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

    def test_bootstrap_support_pins_apply_only_to_changed_paths(self) -> None:
        cases = (
            ("unchanged non-pinned support", "unchanged", "bootstrap owner exception"),
            ("changed pinned support", "pinned", "bootstrap owner exception"),
            ("changed non-pinned support", "non-pinned", "not limited"),
            ("deleted support", "deleted", "not limited"),
        )
        for name, mutation, expected_error in cases:
            with self.subTest(name=name):
                _, base, head, _ = self.make_checkouts()
                reviewed_support_entries = dict(BOOTSTRAP_REVIEWED_SUPPORT_ENTRIES)
                # These cases deliberately exercise a historical reviewed
                # support pin so the test can distinguish unchanged collateral
                # from a changed, non-pinned support blob. Production pins use
                # the current reviewed bootstrap revision above.
                reviewed_support_entries[b"docs/ENCRYPTION.md"] = (
                    b"blob",
                    b"100644",
                    b"0" * 40,
                )
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
                    (base / relative).write_text(
                        "legacy bootstrap seam\n",
                        encoding="ascii",
                    )
                for relative in ADMISSION_INFRASTRUCTURE_FIXTURE_PATHS:
                    (base / relative).unlink()
                for relative, mode in BOOTSTRAP_REQUIRED_MODES.items():
                    path = head / relative
                    path.write_bytes((ROOT / relative).read_bytes())
                    path.chmod(mode)

                if mutation == "unchanged":
                    support_path = "docs/ENCRYPTION.md"
                    expected_object = reviewed_support_entries[
                        os.fsencode(support_path)
                    ][2].decode("ascii")
                    current_object = run(
                        "git",
                        "hash-object",
                        "--",
                        support_path,
                        cwd=head,
                    )
                    self.assertNotEqual(expected_object, current_object)
                    self.assertEqual(
                        current_object,
                        run("git", "hash-object", "--", support_path, cwd=base),
                    )
                elif mutation == "pinned":
                    support_path = ".github/workflows/platform-portability.yml"
                    current_object = run(
                        "git",
                        "hash-object",
                        "--",
                        support_path,
                        cwd=head,
                    )
                    reviewed_support_entries = dict(BOOTSTRAP_REVIEWED_SUPPORT_ENTRIES)
                    reviewed_support_entries[os.fsencode(support_path)] = (
                        b"blob",
                        b"100644",
                        current_object.encode("ascii"),
                    )
                    (base / support_path).write_text(
                        "name: legacy platform workflow\n",
                        encoding="ascii",
                    )
                elif mutation == "non-pinned":
                    support_path = "docs/ENCRYPTION.md"
                    expected_object = reviewed_support_entries[
                        os.fsencode(support_path)
                    ][2].decode("ascii")
                    self.assertNotEqual(
                        expected_object,
                        run("git", "hash-object", "--", support_path, cwd=head),
                    )
                    (base / support_path).write_text(
                        "legacy encryption policy\n",
                        encoding="ascii",
                    )

                base_commit = commit_all(base, f"pre-bootstrap {name}")
                if mutation == "deleted":
                    (head / ".github/workflows/platform-portability.yml").unlink()
                (head / "bootstrap-fixture.txt").write_text(
                    "unprotected bootstrap fixture\n",
                    encoding="ascii",
                )
                head_commit = commit_all(head, f"bootstrap {name}")

                with patch(
                    "scripts.privacy_age_integrity_gate.BOOTSTRAP_REVIEWED_SUPPORT_ENTRIES",
                    reviewed_support_entries,
                ), self.assertRaisesRegex(RuntimeError, expected_error):
                    self.verify(base, head, base_commit, head_commit)

    def test_bootstrap_requires_regular_entries_with_expected_modes(self) -> None:
        for malformed in ("mode", "symlink"):
            with self.subTest(malformed=malformed):
                _, base, head, _ = self.make_checkouts()
                for relative in ADMISSION_INFRASTRUCTURE_FIXTURE_PATHS:
                    (base / relative).unlink()
                (base / ".github/workflows/privacy-age-integrity.yml").write_text(
                    "name: boundary\n",
                    encoding="ascii",
                )
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
        for relative in ADMISSION_INFRASTRUCTURE_FIXTURE_PATHS:
            (base / relative).unlink()
        (base / ".github/workflows/privacy-age-integrity.yml").write_text(
            "name: boundary\n",
            encoding="ascii",
        )
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
            env=fixture_git_environment(),
            timeout=10,
        ).stdout
        head_bytes = subprocess.run(
            ["git", "show", f"{head_commit}:home/private.age"],
            cwd=head,
            check=True,
            capture_output=True,
            env=fixture_git_environment(),
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

        foreign = dict(payload)
        foreign["repository"] = "attacker/dotfiles"
        foreign_message_file = Path(temporary.name) / "foreign-payload"
        foreign_message_file.write_bytes(canonical_payload_bytes(foreign))
        subprocess.run(
            [
                "ssh-keygen",
                "-Y",
                "sign",
                "-f",
                str(key),
                "-n",
                ADMISSION_NAMESPACE,
                str(foreign_message_file),
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
                    foreign,
                    (foreign_message_file.with_suffix(".sig")).read_bytes(),
                ),
                allowed_signers=base / ".github/age-admission/allowed_signers",
                repository="nisavid/dotfiles",
            )

    def test_unrelated_candidate_changes_are_allowed(self) -> None:
        _, base, head, base_commit = self.make_checkouts()
        (head / "README.md").write_text("candidate docs\n", encoding="utf-8")
        head_commit = commit_all(head, "unrelated")

        self.verify(base, head, base_commit, head_commit)

    def test_result_mode_empty_transition_never_reads_or_parses_receipt(self) -> None:
        temporary, base, head, base_commit = self.make_checkouts()
        (head / "unprotected.txt").write_text("candidate data\n", encoding="utf-8")
        head_commit = commit_all(head, "unprotected change")
        snapshot = make_snapshot(
            repository="nisavid/dotfiles",
            pull_request=166,
            state="open",
            base_ref="main",
            base_commit=base_commit,
            head_repository="nisavid/dotfiles",
            head_commit=head_commit,
            body_sha256=body_digest(b"not a receipt"),
        )
        with patch(
            "scripts.privacy_age_integrity_gate._verify_admission",
            side_effect=AssertionError("receipt parser was reached"),
        ):
            result = evaluate_integrity_boundary(
                base_repository=base,
                base_commit=base_commit,
                head_repository=head,
                head_commit=head_commit,
                admission_body=b"not a receipt",
                repository="nisavid/dotfiles",
            )
        self.assertEqual(result["outcome"], "no_protected_paths_changed")
        self.assertFalse(result["receipt_required"])

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
            "PRIVACY_BASE_REF: ${{ needs.begin.outputs.base_ref }}", source
        )
        self.assertIn('test "$PRIVACY_BASE_REF" = "main"', source)
        self.assertIn("allow-unsafe-pr-checkout: true", source)
        self.assertIn(
            "python3 -I trusted-base/scripts/privacy_age_integrity_gate.py", source
        )
        self.assertIn('PRIVACY_REPOSITORY: ${{ needs.begin.outputs.repository }}', source)
        self.assertIn("trusted-tools/scripts/privacy_age_pr_snapshot.py", source)
        self.assertIn("trusted_tools_sha", source)
        self.assertIn("ref: ${{ github.sha }}", source)
        self.assertIn('test "$trusted_sha" = "$GITHUB_SHA"', source)
        self.assertIn('test "$(git -C trusted-tools rev-parse --verify HEAD)" = "$TRUSTED_TOOLS_SHA"', source)
        self.assertIn("needs.begin.outputs.trusted_tools_sha || github.sha", source)
        self.assertIn("FALLBACK_TRUSTED_SHA", source)
        for line in source.splitlines():
            if line.strip().startswith("uses:"):
                self.assertRegex(line.strip(), r"uses:\s+[^\s@]+@[0-9a-f]{40}\Z")
        self.assertIn('--body-output "$RUNNER_TEMP/privacy-age-verify/body"', source)
        self.assertNotIn('python3 -I - "$GITHUB_EVENT_PATH"', source)
        self.assertIn("verify_filesystem_entries", source)
        self.assertIn(
            '--allowed-signers trusted-base/.github/age-admission/allowed_signers',
            source,
        )
        self.assertIn('--admission-body "$RUNNER_TEMP/privacy-age-verify/body"', source)
        self.assertIn('--snapshot-file "$RUNNER_TEMP/privacy-age-verify/snapshot.json"', source)
        self.assertIn('--state-file "$RUNNER_TEMP/privacy-age-verify/state.json"', source)
        self.assertIn('--repository "$PRIVACY_REPOSITORY"', source)
        self.assertIn("python3 -I trusted-base/scripts/privacy-scan", source)
        self.assertIn("snapshot_b64", source)
        self.assertIn("state_b64", source)
        self.assertIn("if: ${{ !cancelled() && always() }}", source)
        self.assertIn("actions/create-github-app-token@064492a9a1762067169d50c792a7dc02bc3d1254", source)
        self.assertIn("permission-checks: write", source)
        self.assertIn("PRIVACY_AGE_ADMISSION_APP_PRIVATE_KEY", source)
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
            "expected checkout and handoff verifier heredocs",
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
            "changed scanner review policy": lambda root: (
                root / "scripts/privacy_scan_review.py"
            ).write_text("changed\n", encoding="utf-8"),
            "changed scanner review record": lambda root: (
                root / ".github/age-admission/privacy-scan-reviewed-findings-v1.json"
            ).write_text("changed\n", encoding="utf-8"),
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
        for relative in (
            "scripts/privacy-scan",
            "scripts/privacy_scan_review.py",
            ".github/age-admission/privacy-scan-reviewed-findings-v1.json",
        ):
            with self.subTest(mode=relative):
                _, base, head, base_commit = self.make_checkouts()
                expected_mode = BOOTSTRAP_REQUIRED_MODES[relative]
                (head / relative).chmod(0o644 if expected_mode == 0o755 else 0o755)
                head_commit = commit_all(head, f"mode {relative}")
                with self.assertRaisesRegex(
                    RuntimeError,
                    "active admission infrastructure must remain complete",
                ):
                    self.verify(base, head, base_commit, head_commit)

        for relative in (
            "scripts/privacy_scan_review.py",
            ".github/age-admission/privacy-scan-reviewed-findings-v1.json",
        ):
            with self.subTest(symlink=relative):
                _, base, head, base_commit = self.make_checkouts()
                path = head / relative
                path.unlink()
                path.symlink_to("../missing")
                head_commit = commit_all(head, f"symlink {relative}")
                with self.assertRaisesRegex(
                    RuntimeError,
                    "active admission infrastructure must remain complete",
                ):
                    self.verify(base, head, base_commit, head_commit)

        _, base, head, base_commit = self.make_checkouts()
        age_path = head / "home/private.age"
        age_path.unlink()
        age_path.symlink_to("elsewhere")
        head_commit = commit_all(head, "symlink ciphertext")
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
