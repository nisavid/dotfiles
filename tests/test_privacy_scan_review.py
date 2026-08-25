from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "scripts/privacy-scan"
sys.path.insert(0, os.fspath(ROOT / "scripts"))

import privacy_scan_review as _review  # noqa: E402
from privacy_scan_review import (  # noqa: E402
    OWNER_REVIEWER,
    POLICY_VERSION,
    RECORD_VERSION,
    ReviewRecordError,
    canonical_json_bytes,
    load_review_record,
    validate_reviewed_findings,
)

_scanner_loader = importlib.machinery.SourceFileLoader(
    "privacy_scan_impl",
    os.fspath(SCANNER),
)
_scanner_spec = importlib.util.spec_from_loader(
    _scanner_loader.name,
    _scanner_loader,
)
assert _scanner_spec is not None
_scanner = importlib.util.module_from_spec(_scanner_spec)
sys.modules[_scanner_loader.name] = _scanner
_scanner_loader.exec_module(_scanner)


POLICY_FILES = (
    "scripts/privacy-scan",
    "scripts/privacy_scan_review.py",
    "scripts/agent_equipment_public_data.py",
    "home/private_dot_local/lib/agent-equipment/agent_equipment/secrets.py",
)
TRUSTED_REVIEW_RECORD = (
    ROOT / ".github/age-admission/privacy-scan-reviewed-findings-v1.json"
)
TRUSTED_FINDING_KEYS = (
    (".github/workflows/privacy-age-integrity.yml", 0, "provider-token"),
    ("scripts/privacy_age_admission_publisher.py", 163, "provider-token"),
    ("scripts/privacy_age_pr_snapshot.py", 83, "provider-token"),
    ("tests/test_privacy_age_admission_app.py", 444, "provider-token"),
    ("tests/test_privacy_age_admission_app.py", 479, "provider-token"),
)


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(  # noqa: S324 -- Git object identity requires SHA-1.
        f"blob {len(data)}\0".encode() + data
    ).hexdigest()


def _policy(policy_root: Path = ROOT) -> dict[str, object]:
    return {
        "version": POLICY_VERSION,
        "files": {
            relative: _sha256((policy_root / relative).read_bytes())
            for relative in POLICY_FILES
        },
    }


def _record(
    root: Path,
    findings: tuple[tuple[str, int, str], ...],
    *,
    category: str = "mocked_test_canary",
    policy_root: Path = ROOT,
) -> Path:
    entries = []
    for relative, line, rule in findings:
        data = (root / relative).read_bytes()
        mode = f"100{(root / relative).stat().st_mode & 0o777:03o}"
        entries.append(
            {
                "category": category,
                "content_sha256": _sha256(data),
                "evidence": {
                    "claims": ["content-bound", "owner-reviewed"],
                    "kind": category,
                    "reviewed_lines": [max(line, 1)],
                },
                "git_blob_sha1": _git_blob_sha1(data),
                "line": line,
                "mode": mode,
                "path": relative,
                "rule": rule,
            }
        )
    entries.sort(key=lambda entry: (entry["path"], entry["line"], entry["rule"]))
    document = {
        "entries": entries,
        "policy": _policy(policy_root),
        "record_id": "fixture-owner-review-v1",
        "reviewed_commit": "0" * 40,
        "reviewer": OWNER_REVIEWER,
        "version": RECORD_VERSION,
    }
    path = root / "review-record.json"
    path.write_bytes(canonical_json_bytes(document))
    return path


def _resize_canonical_record(path: Path, target_bytes: int) -> None:
    document = json.loads(path.read_text(encoding="ascii"))
    document["record_id"] = "x"
    baseline = canonical_json_bytes(document)
    assert len(baseline) <= target_bytes
    document["record_id"] = "x" * (1 + target_bytes - len(baseline))
    data = canonical_json_bytes(document)
    assert len(data) == target_bytes
    path.write_bytes(data)


def _write_policy_fixture(root: Path, *, large_file_bytes: int) -> None:
    for relative in POLICY_FILES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = b"policy\n"
        if relative == "scripts/agent_equipment_public_data.py":
            data += b"#" * (large_file_bytes - len(data))
        target.write_bytes(data)


def _run_scan(
    root: Path,
    record: Path | None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [
        sys.executable,
        "-I",
        os.fspath(SCANNER),
        "--root",
        os.fspath(root),
    ]
    if record is not None:
        command.extend(["--review-record", os.fspath(record)])
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
    )


def _copy_default_reviewed_candidate(root: Path) -> None:
    document = json.loads(TRUSTED_REVIEW_RECORD.read_text(encoding="ascii"))
    reviewed_paths = sorted(
        {entry["path"] for entry in document["entries"]}
    )
    for relative in reviewed_paths:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
        target.chmod(0o644)


def _runtime_canary_source() -> str:
    # Build the inert finding only inside the temporary fixture.  No token-like
    # value is stored in this repository's source tree.
    field = bytes((116, 111, 107, 101, 110)).decode()
    return f'Client({field}="checks")\n'


def _generated_provider_token() -> str:
    # A deterministic test-only value; it never leaves the temporary fixture.
    return bytes.fromhex("6768705f").decode() + "A" * 24


def _generated_bearer_header(token: str) -> str:
    # Keep the credential-shaped fixture out of this repository while testing
    # the scanner against the complete runtime header in a temporary file.
    prefix = bytes.fromhex("417574686f72697a6174696f6e3a2042656172657220").decode()
    return prefix + token


class PrivacyScanReviewTests(TestCase):
    def test_scanner_and_reviewer_share_the_public_file_size_limit(self) -> None:
        self.assertEqual(_review.MAX_PUBLIC_FILE_BYTES, 4 * 1024 * 1024)
        self.assertIs(
            _scanner.MAX_PUBLIC_FILE_BYTES,
            _review.MAX_PUBLIC_FILE_BYTES,
        )

    def test_review_record_uses_its_compact_inclusive_size_limit(self) -> None:
        maximum = 512 * 1024
        self.assertEqual(_review.MAX_REVIEW_RECORD_BYTES, maximum)

        for size in (maximum - 1, maximum):
            with self.subTest(size=size), TemporaryDirectory() as directory:
                root = Path(directory)
                record_path = _record(root, ())
                _resize_canonical_record(record_path, size)

                record = load_review_record(record_path, policy_root=ROOT)

                self.assertEqual(record_path.stat().st_size, size)
                self.assertTrue(record.record_id)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            record_path = _record(root, ())
            _resize_canonical_record(record_path, maximum + 1)

            with self.assertRaisesRegex(
                ReviewRecordError,
                "owner-review record file is oversized",
            ):
                load_review_record(record_path, policy_root=ROOT)

    def test_explicit_record_is_diagnostic_for_the_complete_finding_set(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "client.py").write_text(_runtime_canary_source(), encoding="utf-8")
            findings = (("client.py", 1, "provider-token"),)
            result = _run_scan(root, _record(root, findings))

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("explicit record is non-authoritative", result.stderr)
        self.assertIn("client.py:1: [provider-token] review required", result.stdout)

    def test_default_record_admits_unchanged_reviewed_findings(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _copy_default_reviewed_candidate(root)
            result = _run_scan(root, None)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f"accepted {len(TRUSTED_FINDING_KEYS)} owner-reviewed finding",
            result.stderr,
        )

    def test_review_fixture_produces_the_exact_reviewed_finding_keys(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _copy_default_reviewed_candidate(root)
            diagnostic = _run_scan(root, TRUSTED_REVIEW_RECORD)

        self.assertEqual(
            diagnostic.stdout.splitlines(),
            [
                f"{path}:{line}: [{rule}] review required"
                for path, line, rule in TRUSTED_FINDING_KEYS
            ],
        )

    def test_explicit_trusted_record_is_diagnostic_only(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _copy_default_reviewed_candidate(root)
            result = _run_scan(root, TRUSTED_REVIEW_RECORD)

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("explicit record is non-authoritative", result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                f"{path}:{line}: [{rule}] review required"
                for path, line, rule in TRUSTED_FINDING_KEYS
            ],
        )

    def test_default_record_does_not_block_an_unrelated_clean_candidate(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "clean.py").write_text("print('clean')\n", encoding="utf-8")
            result = _run_scan(root, None)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_default_record_leaves_an_unrelated_finding_unresolved(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "client.py").write_text(_runtime_canary_source(), encoding="utf-8")
            result = _run_scan(root, None)

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("owner review record invalid", result.stderr)
        self.assertIn("client.py:1: [provider-token] review required", result.stdout)

    def test_default_record_partial_intersection_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "scripts/privacy_age_pr_snapshot.py"
            target.parent.mkdir(parents=True)
            target.write_bytes((ROOT / "scripts/privacy_age_pr_snapshot.py").read_bytes())
            target.chmod(0o644)
            result = _run_scan(root, None)

        self.assertEqual(result.returncode, 1)
        self.assertIn("owner review record invalid", result.stderr)
        self.assertIn(
            "scripts/privacy_age_pr_snapshot.py:83: [provider-token] review required",
            result.stdout,
        )

    def test_candidate_authored_default_record_cannot_suppress_findings(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "client.py"
            source.write_text(_runtime_canary_source(), encoding="utf-8")
            candidate_record = _record(root, (("client.py", 1, "provider-token"),))
            candidate_default = (
                root / ".github/age-admission/privacy-scan-reviewed-findings-v1.json"
            )
            candidate_default.parent.mkdir(parents=True)
            candidate_record.replace(candidate_default)
            result = _run_scan(root, None)

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("accepted 1 owner-reviewed finding", result.stderr)
        self.assertIn("client.py:1: [provider-token] review required", result.stdout)

    def test_changed_file_bytes_fail_the_same_record(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "client.py"
            source.write_text(_runtime_canary_source(), encoding="utf-8")
            record = _record(root, (("client.py", 1, "provider-token"),))
            source.write_text(_runtime_canary_source() + "# changed\n", encoding="utf-8")
            result = _run_scan(root, record)

        self.assertEqual(result.returncode, 1)
        self.assertIn("owner review record invalid", result.stderr)
        self.assertIn("client.py:1: [provider-token] review required", result.stdout)

    def test_file_mode_and_bytes_are_bound_to_the_same_descriptor(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "client.py"
            source.write_text(_runtime_canary_source(), encoding="utf-8")
            source.chmod(0o644)
            record_path = _record(root, (("client.py", 1, "provider-token"),))
            record = load_review_record(record_path, policy_root=ROOT)
            source.chmod(0o600)
            replacement = root / "replacement.py"
            replacement.write_text("print('replacement')\n", encoding="utf-8")
            replacement.chmod(0o644)
            real_open = os.open
            replacement_observed = False

            def open_then_replace(path: os.PathLike[str] | str, flags: int) -> int:
                nonlocal replacement_observed
                descriptor = real_open(path, flags)
                if Path(path).resolve() == source.resolve():
                    os.replace(replacement, source)
                    replacement_observed = True
                return descriptor

            with (
                self.assertRaisesRegex(
                    ReviewRecordError,
                    "owner-review finding file mode changed",
                ),
                patch.object(_review.os, "open", side_effect=open_then_replace),
            ):
                validate_reviewed_findings(
                    (("client.py", 1, "provider-token"),),
                    root=root,
                    record=record,
                )

            self.assertTrue(replacement_observed)

    def test_reviewed_candidates_use_the_inclusive_public_file_size_limit(self) -> None:
        source_prefix = _runtime_canary_source().encode()
        for size in (
            512 * 1024 + 1,
            4 * 1024 * 1024 - 1,
            4 * 1024 * 1024,
        ):
            with self.subTest(size=size), TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "client.py"
                source.write_bytes(
                    source_prefix + b"#" * (size - len(source_prefix))
                )
                findings = (("client.py", 1, "provider-token"),)
                record_path = _record(root, findings)
                record = load_review_record(record_path, policy_root=ROOT)

                scanner_data, scanner_finding = _scanner.read_public_file(source)
                validated = validate_reviewed_findings(
                    findings,
                    root=root,
                    record=record,
                )

                self.assertIsNone(scanner_finding)
                self.assertEqual(len(scanner_data or b""), size)
                self.assertEqual(validated, findings)

    def test_policy_files_use_the_inclusive_public_file_size_limit(self) -> None:
        maximum = 4 * 1024 * 1024
        with TemporaryDirectory() as directory:
            root = Path(directory)
            policy_root = root / "policy"
            _write_policy_fixture(policy_root, large_file_bytes=maximum)
            record_path = _record(root, (), policy_root=policy_root)

            record = load_review_record(record_path, policy_root=policy_root)

            self.assertEqual(set(record.policy_files), set(POLICY_FILES))

        with TemporaryDirectory() as directory:
            root = Path(directory)
            policy_root = root / "policy"
            _write_policy_fixture(policy_root, large_file_bytes=maximum + 1)
            record_path = _record(root, (), policy_root=policy_root)

            with self.assertRaisesRegex(
                ReviewRecordError,
                "owner-review policy file is oversized",
            ):
                load_review_record(record_path, policy_root=policy_root)

    def test_oversized_public_file_cannot_be_owner_dispositioned(self) -> None:
        maximum = 4 * 1024 * 1024
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "client.py"
            source_prefix = _runtime_canary_source().encode()
            source.write_bytes(
                source_prefix + b"#" * (maximum + 1 - len(source_prefix))
            )
            findings = (("client.py", 1, "provider-token"),)
            record_path = _record(root, findings)
            record = load_review_record(record_path, policy_root=ROOT)

            with self.assertRaisesRegex(
                ReviewRecordError,
                "owner-review finding file is oversized",
            ):
                validate_reviewed_findings(
                    findings,
                    root=root,
                    record=record,
                )

            result = _run_scan(root, record_path)

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn("owner review record invalid", result.stderr)
        self.assertNotIn("owner-reviewed finding", result.stderr)
        self.assertEqual(
            result.stdout,
            "client.py:0: [oversized-public-file] review required\n",
        )

    def test_new_finding_cannot_hide_behind_an_old_record(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "client.py"
            source.write_text(
                _runtime_canary_source() + _runtime_canary_source(),
                encoding="utf-8",
            )
            record = _record(root, (("client.py", 1, "provider-token"),))
            result = _run_scan(root, record)

        self.assertEqual(result.returncode, 1)
        self.assertIn("owner review record invalid", result.stderr)

    def test_stale_extra_record_cannot_admit_a_clean_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "client.py"
            source.write_text("print('clean')\n", encoding="utf-8")
            record = _record(root, (("client.py", 1, "provider-token"),))
            result = _run_scan(root, record)

        self.assertEqual(result.returncode, 1)
        self.assertIn("owner review record invalid", result.stderr)

    def test_duplicate_record_keys_fail_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "client.py"
            source.write_text(_runtime_canary_source(), encoding="utf-8")
            record = _record(root, (("client.py", 1, "provider-token"),))
            raw = record.read_text(encoding="ascii")
            record.write_text(raw.replace('"version":', '"version": "bad", "version":', 1))
            result = _run_scan(root, record)

        self.assertEqual(result.returncode, 1)
        self.assertIn("owner review record invalid", result.stderr)

    def test_category_mismatch_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "client.py"
            source.write_text(_runtime_canary_source(), encoding="utf-8")
            record = _record(root, (("client.py", 1, "provider-token"),))
            document = json.loads(record.read_text(encoding="ascii"))
            document["entries"][0]["evidence"]["kind"] = "runtime_checks_bearer_header"
            record.write_bytes(canonical_json_bytes(document))
            result = _run_scan(root, record)

        self.assertEqual(result.returncode, 1)
        self.assertIn("owner review record invalid", result.stderr)

    def test_unknown_owner_attestation_category_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "client.py"
            source.write_text(_runtime_canary_source(), encoding="utf-8")
            record = _record(root, (("client.py", 1, "provider-token"),))
            document = json.loads(record.read_text(encoding="ascii"))
            document["entries"][0]["category"] = "unknown_owner_attestation"
            document["entries"][0]["evidence"]["kind"] = (
                "unknown_owner_attestation"
            )
            record.write_bytes(canonical_json_bytes(document))
            result = _run_scan(root, record)

        self.assertEqual(result.returncode, 1)
        self.assertIn("owner review record invalid", result.stderr)

    def test_sensitive_file_text_rules_detect_literal_provider_tokens(self) -> None:
        token = _generated_provider_token()
        sources = {
            "workflow.yml": f"token: {token}\n",
            "publisher.py": f"{_generated_bearer_header('checks')}\n",
            "test.py": f'Client(token="{token}")\n',
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, source in sources.items():
                (root / relative).write_text(source, encoding="utf-8")
            denylist = _scanner.ExactSubstringMatcher(())
            rules_by_path: dict[str, list[str]] = {}
            for relative, source in sources.items():
                syntax = _scanner.serialized_syntax(relative)
                line_syntax = "line-invariants" if syntax is not None else None
                for _line_number, line in enumerate(source.splitlines(), start=1):
                    rules_by_path.setdefault(relative, []).extend(
                        _scanner.sensitive_file_text_rules(
                            relative,
                            line,
                            denylist,
                            age_shaped=False,
                            syntax=line_syntax,
                        )
                    )

        self.assertEqual(
            rules_by_path,
            {
                "workflow.yml": ["provider-token"],
                "publisher.py": ["provider-token"],
                "test.py": ["provider-token"],
            },
        )
