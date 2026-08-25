#!/usr/bin/env python3
"""Validate trusted-base owner dispositions for deterministic privacy findings.

The reviewed record is deliberately separate from the candidate checkout.  A
trusted caller supplies the record path, and this module binds each disposition
to the scanner rule, a closed semantic category, a canonical repository path,
the file mode, and the complete file bytes.  It is an admission record, not a
general scanner allowlist.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

RECORD_VERSION = "privacy-scan-reviewed-findings/v1"
POLICY_VERSION = "privacy-scan-policy/v1"
OWNER_REVIEWER = "ivan@nisavid.io"
MAX_RECORD_BYTES = 512 * 1024
MAX_ENTRIES = 256
MAX_POLICY_FILES = 16
MAX_EVIDENCE_CLAIMS = 16
COMMIT_ID = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)
GIT_BLOB_ID = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
PATH_COMPONENT = re.compile(r"[A-Za-z0-9._-]+\Z")

# These are the only semantic dispositions that this record format may carry.
# A new category requires a new reviewed schema rather than a broader bypass.
REVIEW_CATEGORIES = frozenset(
    {
        "runtime_action_output_reference",
        "runtime_checks_bearer_header",
        "runtime_pr_read_bearer_header",
        "mocked_test_canary",
    }
)


class ReviewRecordError(RuntimeError):
    """The trusted owner-review record cannot establish an exact disposition."""


Finding = tuple[str, int, str]


@dataclass(frozen=True)
class ReviewedFinding:
    path: str
    line: int
    rule: str
    category: str
    mode: str
    content_sha256: str
    git_blob_sha1: str
    evidence: Mapping[str, Any]

    @property
    def key(self) -> Finding:
        return (self.path, self.line, self.rule)


@dataclass(frozen=True)
class ReviewRecord:
    version: str
    reviewer: str
    reviewed_commit: str
    record_id: str
    policy_version: str
    policy_files: Mapping[str, str]
    entries: tuple[ReviewedFinding, ...]


def canonical_json_bytes(document: object) -> bytes:
    """Encode the record's closed JSON form without ambiguous whitespace."""

    try:
        return json.dumps(
            document,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise ReviewRecordError("owner-review record is not canonical JSON") from error


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ReviewRecordError("owner-review record contains duplicate keys")
        document[key] = value
    return document


def _object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ReviewRecordError(f"owner-review record {label} is not an object")
    return value


def _exact_keys(document: Mapping[str, object], expected: set[str], *, label: str) -> None:
    if set(document) != expected:
        raise ReviewRecordError(f"owner-review record {label} has unexpected fields")


def _string(value: object, *, label: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value:
        raise ReviewRecordError(f"owner-review record {label} is invalid")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ReviewRecordError(f"owner-review record {label} is invalid")
    return value


def _integer(value: object, *, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ReviewRecordError(f"owner-review record {label} is invalid")
    return value


def _canonical_path(value: object, *, label: str) -> str:
    path = _string(value, label=label)
    if (
        path.startswith("/")
        or "\\" in path
        or path.startswith("redacted-path:")
        or any(component in {"", ".", ".."} for component in path.split("/"))
        or any(PATH_COMPONENT.fullmatch(component) is None for component in path.split("/"))
    ):
        raise ReviewRecordError(f"owner-review record {label} is not canonical")
    return path


def _secure_read(path: Path) -> bytes:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    nonblocking = getattr(os, "O_NONBLOCK", None)
    if no_follow is None or nonblocking is None:
        raise ReviewRecordError("safe owner-review file reads are unavailable")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | no_follow | nonblocking
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ReviewRecordError("owner-review record file is unavailable") from error
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RECORD_BYTES:
            raise ReviewRecordError("owner-review record file is invalid")
        data = bytearray()
        while len(data) <= MAX_RECORD_BYTES:
            chunk = os.read(descriptor, min(64 * 1024, MAX_RECORD_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > MAX_RECORD_BYTES:
            raise ReviewRecordError("owner-review record file is oversized")
        return bytes(data)
    except OSError as error:
        raise ReviewRecordError("owner-review record file is unreadable") from error
    finally:
        os.close(descriptor)


def _safe_policy_path(root: Path, relative: str) -> Path:
    path = root.joinpath(*relative.split("/"))
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ReviewRecordError("owner-review policy file is unavailable") from error
    try:
        resolved.relative_to(root.resolve(strict=True))
    except ValueError as error:
        raise ReviewRecordError("owner-review policy path escapes trusted root") from error
    if path.is_symlink() or not path.is_file():
        raise ReviewRecordError("owner-review policy file is not a regular file")
    return resolved


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _validate_policy(document: object, *, policy_root: Path) -> tuple[str, dict[str, str]]:
    policy = _object(document, label="policy")
    _exact_keys(policy, {"version", "files"}, label="policy")
    version = _string(policy.get("version"), label="policy.version")
    if version != POLICY_VERSION:
        raise ReviewRecordError("owner-review policy version is unsupported")
    files = _object(policy.get("files"), label="policy.files")
    if not files or len(files) > MAX_POLICY_FILES:
        raise ReviewRecordError("owner-review policy file set is invalid")
    validated: dict[str, str] = {}
    for relative, digest in files.items():
        canonical = _canonical_path(relative, label="policy file path")
        expected = _string(digest, label=f"policy digest {canonical}", pattern=SHA256)
        data = _secure_read(_safe_policy_path(policy_root, canonical))
        if _sha256(data) != expected:
            raise ReviewRecordError("owner-review policy content changed")
        validated[canonical] = expected
    required = {
        "scripts/privacy-scan",
        "scripts/privacy_scan_review.py",
        "scripts/agent_equipment_public_data.py",
        "home/private_dot_local/lib/agent-equipment/agent_equipment/secrets.py",
    }
    if set(validated) != required:
        raise ReviewRecordError("owner-review policy file set is incomplete")
    return version, validated


def _validate_evidence(value: object, *, category: str) -> Mapping[str, Any]:
    evidence = _object(value, label="entry.evidence")
    _exact_keys(evidence, {"kind", "reviewed_lines", "claims"}, label="entry.evidence")
    if evidence.get("kind") != category:
        raise ReviewRecordError("owner-review evidence category mismatch")
    lines = evidence.get("reviewed_lines")
    if (
        not isinstance(lines, list)
        or not lines
        or any(isinstance(item, bool) or not isinstance(item, int) or item < 1 for item in lines)
        or lines != sorted(set(lines))
    ):
        raise ReviewRecordError("owner-review evidence lines are invalid")
    claims = evidence.get("claims")
    if (
        not isinstance(claims, list)
        or not claims
        or len(claims) > MAX_EVIDENCE_CLAIMS
        or any(not isinstance(item, str) or not item for item in claims)
        or claims != sorted(set(claims))
    ):
        raise ReviewRecordError("owner-review evidence claims are invalid")
    return evidence


def _validate_entry(value: object) -> ReviewedFinding:
    entry = _object(value, label="entry")
    _exact_keys(
        entry,
        {
            "path",
            "line",
            "rule",
            "category",
            "mode",
            "content_sha256",
            "git_blob_sha1",
            "evidence",
        },
        label="entry",
    )
    path = _canonical_path(entry.get("path"), label="entry.path")
    line = _integer(entry.get("line"), label="entry.line")
    rule = _string(entry.get("rule"), label="entry.rule")
    if rule != "provider-token":
        raise ReviewRecordError("owner-review rule is not supported by v1")
    category = _string(entry.get("category"), label="entry.category")
    if category not in REVIEW_CATEGORIES:
        raise ReviewRecordError("owner-review category is not supported")
    mode = _string(entry.get("mode"), label="entry.mode", pattern=re.compile(r"100[0-7]{3}\Z"))
    content_sha256 = _string(
        entry.get("content_sha256"),
        label="entry.content_sha256",
        pattern=SHA256,
    )
    git_blob_sha1 = _string(
        entry.get("git_blob_sha1"),
        label="entry.git_blob_sha1",
        pattern=GIT_BLOB_ID,
    )
    evidence = _validate_evidence(entry.get("evidence"), category=category)
    reviewed_lines = evidence["reviewed_lines"]
    assert isinstance(reviewed_lines, list)
    if line > 0 and line not in reviewed_lines:
        raise ReviewRecordError("owner-review evidence does not cover finding line")
    return ReviewedFinding(
        path=path,
        line=line,
        rule=rule,
        category=category,
        mode=mode,
        content_sha256=content_sha256,
        git_blob_sha1=git_blob_sha1,
        evidence=evidence,
    )


def load_review_record(path: Path, *, policy_root: Path) -> ReviewRecord:
    """Load and validate a canonical trusted-base record."""

    data = _secure_read(path)
    try:
        document = json.loads(
            data.decode("ascii"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ReviewRecordError("owner-review record is not valid JSON") from error
    canonical = canonical_json_bytes(document)
    if data not in {canonical, canonical + b"\n"}:
        raise ReviewRecordError("owner-review record is not canonical JSON")
    root = _object(document, label="root")
    _exact_keys(
        root,
        {"version", "reviewer", "reviewed_commit", "record_id", "policy", "entries"},
        label="root",
    )
    version = _string(root.get("version"), label="version")
    if version != RECORD_VERSION:
        raise ReviewRecordError("owner-review record version is unsupported")
    reviewer = _string(root.get("reviewer"), label="reviewer")
    if reviewer != OWNER_REVIEWER:
        raise ReviewRecordError("owner-review reviewer is not the configured owner")
    reviewed_commit = _string(root.get("reviewed_commit"), label="reviewed_commit", pattern=COMMIT_ID)
    record_id = _string(root.get("record_id"), label="record_id")
    policy_version, policy_files = _validate_policy(root.get("policy"), policy_root=policy_root)
    raw_entries = root.get("entries")
    if not isinstance(raw_entries, list) or len(raw_entries) > MAX_ENTRIES:
        raise ReviewRecordError("owner-review entries are invalid")
    entries = tuple(_validate_entry(value) for value in raw_entries)
    keys = [entry.key for entry in entries]
    if keys != sorted(set(keys)):
        raise ReviewRecordError("owner-review entries are not unique and sorted")
    return ReviewRecord(
        version=version,
        reviewer=reviewer,
        reviewed_commit=reviewed_commit,
        record_id=record_id,
        policy_version=policy_version,
        policy_files=policy_files,
        entries=entries,
    )


def validate_reviewed_findings(
    findings: Iterable[Finding],
    *,
    root: Path,
    record: ReviewRecord,
) -> tuple[Finding, ...]:
    """Require exact finding/record equality and verify every file identity."""

    finding_values = tuple(sorted(set(findings)))
    entries = {entry.key: entry for entry in record.entries}
    if set(entries) != set(finding_values):
        raise ReviewRecordError("owner-review record does not exactly match findings")
    trusted_root = root.resolve(strict=True)
    for finding in finding_values:
        path, _line, _rule = finding
        if path.startswith("redacted-path:"):
            raise ReviewRecordError("owner-review record cannot bind a redacted path")
        entry = entries[finding]
        candidate = trusted_root.joinpath(*path.split("/"))
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(trusted_root)
        except (OSError, ValueError) as error:
            raise ReviewRecordError("owner-review finding path is unavailable") from error
        if candidate.is_symlink() or not candidate.is_file():
            raise ReviewRecordError("owner-review finding is not a regular file")
        data = _secure_read(candidate)
        actual_mode = f"100{stat.S_IMODE(candidate.stat().st_mode):03o}"
        if actual_mode != entry.mode:
            raise ReviewRecordError("owner-review finding file mode changed")
        if _sha256(data) != entry.content_sha256:
            raise ReviewRecordError("owner-review finding file content changed")
        if _git_blob_sha1(data) != entry.git_blob_sha1:
            raise ReviewRecordError("owner-review finding Git blob changed")
    return finding_values
