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

ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "scripts/privacy-scan"
sys.path.insert(0, os.fspath(ROOT / "scripts"))

from privacy_scan_review import (  # noqa: E402
    OWNER_REVIEWER,
    POLICY_VERSION,
    RECORD_VERSION,
    canonical_json_bytes,
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
def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def _policy() -> dict[str, object]:
    return {
        "version": POLICY_VERSION,
        "files": {
            relative: _sha256((ROOT / relative).read_bytes())
            for relative in POLICY_FILES
        },
    }


def _record(
    root: Path,
    findings: tuple[tuple[str, int, str], ...],
    *,
    category: str = "mocked_test_canary",
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
        "policy": _policy(),
        "record_id": "fixture-owner-review-v1",
        "reviewed_commit": "0" * 40,
        "reviewer": OWNER_REVIEWER,
        "version": RECORD_VERSION,
    }
    path = root / "review-record.json"
    path.write_bytes(canonical_json_bytes(document))
    return path


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
    )


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
    prefix = bytes.fromhex("417574686f72697a74696f6e3a2042656172657220").decode()
    return prefix + token


class PrivacyScanReviewTests(TestCase):
    def test_exact_content_bound_record_admits_the_complete_finding_set(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "client.py").write_text(_runtime_canary_source(), encoding="utf-8")
            findings = (("client.py", 1, "provider-token"),)
            result = _run_scan(root, _record(root, findings))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("accepted 1 owner-reviewed finding", result.stderr)

    def test_default_record_admits_unchanged_reviewed_findings(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".github/age-admission").mkdir(parents=True)
            (root / ".github/age-admission/privacy-scan-reviewed-findings-v1.json").write_text(
                '{"entries":[]}\n',
                encoding="ascii",
            )
            (root / ".github/workflows").mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "tests").mkdir()
            (root / ".github/workflows/privacy-age-integrity.yml").write_bytes(
                (ROOT / ".github/workflows/privacy-age-integrity.yml").read_bytes()
            )
            (root / "scripts/privacy_age_admission_publisher.py").write_bytes(
                (ROOT / "scripts/privacy_age_admission_publisher.py").read_bytes()
            )
            (root / "scripts/privacy_age_pr_snapshot.py").write_bytes(
                (ROOT / "scripts/privacy_age_pr_snapshot.py").read_bytes()
            )
            (root / "tests/test_privacy_age_admission_app.py").write_bytes(
                (ROOT / "tests/test_privacy_age_admission_app.py").read_bytes()
            )
            result = _run_scan(root, None)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("accepted 5 owner-reviewed finding", result.stderr)

    def test_default_record_does_not_block_an_unrelated_clean_candidate(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".github/age-admission").mkdir(parents=True)
            (root / ".github/age-admission/privacy-scan-reviewed-findings-v1.json").write_text(
                "{}\n",
                encoding="ascii",
            )
            (root / "clean.py").write_text("print('clean')\n", encoding="utf-8")
            result = _run_scan(root, None)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

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

    def test_literal_provider_tokens_still_fail_without_a_review_record(self) -> None:
        token = _generated_provider_token()
        sources = {
            "workflow.yml": f"token: {token}\n",
            "publisher.py": f"{_generated_bearer_header(token)}\n",
            "test.py": f'Client(token="{token}")\n',
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, source in sources.items():
                (root / relative).write_text(source, encoding="utf-8")
            denylist = _scanner.ExactSubstringMatcher(())
            findings = []
            for relative, source in sources.items():
                syntax = _scanner.serialized_syntax(relative)
                line_syntax = "line-invariants" if syntax is not None else None
                for line_number, line in enumerate(source.splitlines(), start=1):
                    findings.extend(
                        _scanner.sensitive_file_text_rules(
                            relative,
                            line,
                            denylist,
                            age_shaped=False,
                            syntax=line_syntax,
                        )
                    )

        self.assertEqual(
            findings,
            [
                "provider-token",
                "provider-token",
                "provider-token",
            ],
        )
