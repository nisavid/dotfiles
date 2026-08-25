#!/usr/bin/env python3
"""Typed records shared by the trusted verifier and App publisher.

The records in this module are deliberately small and closed.  They carry
repository transition metadata only; they never carry an admission receipt,
private key material, or candidate-controlled text.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any

RESULT_VERSION = "privacy-age-admission-result/v1"
CHECK_NAME = "Owner-signed age admission"
RESULT_KEYS = frozenset(
    {
        "version",
        "repository",
        "base_commit",
        "head_commit",
        "protected_paths",
        "outcome",
        "receipt_required",
    }
)
SNAPSHOT_VERSION = "privacy-age-admission-snapshot/v1"
SNAPSHOT_KEYS = frozenset(
    {
        "version",
        "repository",
        "pull_request",
        "state",
        "base_ref",
        "base_commit",
        "head_repository",
        "head_commit",
        "body_sha256",
    }
)
STATE_KEYS = frozenset({"version", "state", "snapshot", "result", "error_code"})
STATE_VERSION = "privacy-age-admission-state/v1"
ERROR_CODES = frozenset(
    {
        "live_snapshot_unavailable",
        "live_snapshot_mismatch",
        "verifier_failed",
        "missing_verifier_result",
        "invalid_verifier_result",
        "publication_conflict",
        "publication_unavailable",
    }
)
COMMIT_ID = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
BODY_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z", re.ASCII)
BASE_REF = re.compile(r"[A-Za-z0-9_.:/-]+\Z", re.ASCII)
SAFE_PATH = re.compile(r"[ -~]+\Z", re.ASCII)
MAX_RECORD_BYTES = 256 * 1024
MAX_BODY_BYTES = 256 * 1024
MAX_PROTECTED_PATHS = 4096


class AdmissionResultError(ValueError):
    """A result, snapshot, or state envelope violates its closed contract."""


def _reject_constant(_: str) -> None:
    raise AdmissionResultError("record contains a non-finite JSON number")


def _object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AdmissionResultError("record contains a duplicate JSON member")
        result[key] = value
    return result


def canonical_json_bytes(document: Mapping[str, Any]) -> bytes:
    """Return bounded canonical JSON suitable for a digest or API identity."""

    try:
        data = json.dumps(
            document,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, UnicodeError, ValueError, OverflowError, RecursionError) as error:
        raise AdmissionResultError("record is not canonical JSON") from error
    if len(data) > MAX_RECORD_BYTES:
        raise AdmissionResultError("record is oversized")
    return data


def parse_canonical_json(data: bytes) -> object:
    """Parse one bounded, duplicate-free canonical JSON handoff."""

    if not isinstance(data, bytes) or len(data) > MAX_RECORD_BYTES:
        raise AdmissionResultError("record is oversized")
    try:
        source = data.decode("ascii")
        document = json.loads(
            source,
            object_pairs_hook=_object_from_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise AdmissionResultError("record is not valid canonical JSON") from error
    if not isinstance(document, Mapping):
        raise AdmissionResultError("record is not a JSON object")
    try:
        canonical = canonical_json_bytes(document)
    except AdmissionResultError:
        raise
    encoded_source = source.encode("ascii")
    if encoded_source.endswith(b"\n"):
        encoded_source = encoded_source[:-1]
    if encoded_source != canonical:
        raise AdmissionResultError("record is not canonical JSON")
    return document


def sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def body_digest(body: str | bytes | None) -> str:
    if body is None:
        body = ""
    if isinstance(body, str):
        body = body.encode("utf-8")
    if not isinstance(body, bytes):
        raise AdmissionResultError("pull request body is not text")
    if len(body) > MAX_BODY_BYTES:
        raise AdmissionResultError("pull request body is oversized")
    return sha256_digest(body)


def _require_repository(value: object) -> str:
    if not isinstance(value, str) or REPOSITORY.fullmatch(value) is None:
        raise AdmissionResultError("repository identity is invalid")
    return value


def _require_commit(value: object, field: str) -> str:
    if not isinstance(value, str) or COMMIT_ID.fullmatch(value) is None:
        raise AdmissionResultError(f"{field} is not an exact commit")
    return value


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or BODY_DIGEST.fullmatch(value) is None:
        raise AdmissionResultError(f"{field} is not a sha256 digest")
    return value


@dataclass(frozen=True)
class PullRequestSnapshot:
    repository: str
    pull_request: int
    state: str
    base_ref: str
    base_commit: str
    head_repository: str
    head_commit: str
    body_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "base_commit": self.base_commit,
            "base_ref": self.base_ref,
            "body_sha256": self.body_sha256,
            "head_commit": self.head_commit,
            "head_repository": self.head_repository,
            "pull_request": self.pull_request,
            "repository": self.repository,
            "state": self.state,
            "version": SNAPSHOT_VERSION,
        }


def validate_snapshot(document: Mapping[str, object]) -> PullRequestSnapshot:
    if not isinstance(document, Mapping):
        raise AdmissionResultError("snapshot is not an object")
    if set(document) != SNAPSHOT_KEYS or document["version"] != SNAPSHOT_VERSION:
        raise AdmissionResultError("snapshot fields are not the closed v1 set")
    repository = _require_repository(document["repository"])
    pull_request = document["pull_request"]
    if not isinstance(pull_request, int) or isinstance(pull_request, bool) or pull_request <= 0:
        raise AdmissionResultError("pull request number is invalid")
    state = document["state"]
    if state not in {"open", "closed"}:
        raise AdmissionResultError("pull request state is invalid")
    base_ref = document["base_ref"]
    if (
        not isinstance(base_ref, str)
        or len(base_ref) > 256
        or BASE_REF.fullmatch(base_ref) is None
    ):
        raise AdmissionResultError("base ref is invalid")
    head_repository = _require_repository(document["head_repository"])
    return PullRequestSnapshot(
        repository=repository,
        pull_request=pull_request,
        state=state,
        base_ref=base_ref,
        base_commit=_require_commit(document["base_commit"], "base_commit"),
        head_repository=head_repository,
        head_commit=_require_commit(document["head_commit"], "head_commit"),
        body_sha256=_require_digest(document["body_sha256"], "body_sha256"),
    )


def make_snapshot(
    *,
    repository: str,
    pull_request: int,
    state: str,
    base_ref: str,
    base_commit: str,
    head_repository: str,
    head_commit: str,
    body_sha256: str,
) -> dict[str, object]:
    snapshot = PullRequestSnapshot(
        repository=repository,
        pull_request=pull_request,
        state=state,
        base_ref=base_ref,
        base_commit=base_commit,
        head_repository=head_repository,
        head_commit=head_commit,
        body_sha256=body_sha256,
    )
    return validate_snapshot(snapshot.as_dict()).as_dict()


def validate_result(document: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(document, Mapping):
        raise AdmissionResultError("result is not an object")
    if set(document) != RESULT_KEYS:
        raise AdmissionResultError("result fields are not the closed v1 set")
    if document["version"] != RESULT_VERSION:
        raise AdmissionResultError("result version is invalid")
    repository = _require_repository(document["repository"])
    base_commit = _require_commit(document["base_commit"], "base_commit")
    head_commit = _require_commit(document["head_commit"], "head_commit")
    paths = document["protected_paths"]
    if (
        not isinstance(paths, list)
        or len(paths) > MAX_PROTECTED_PATHS
        or any(
            not isinstance(path, str)
            or len(path) > 512
            or SAFE_PATH.fullmatch(path) is None
            or any(segment in {"", ".", ".."} for segment in path.split("/"))
            or path.startswith("/")
            or "\\" in path
            for path in paths
        )
    ):
        raise AdmissionResultError("protected path list is invalid")
    if paths != sorted(set(paths)):
        raise AdmissionResultError("protected path list is not sorted and unique")
    outcome = document["outcome"]
    receipt_required = document["receipt_required"]
    if outcome == "no_protected_paths_changed":
        if paths or receipt_required is not False:
            raise AdmissionResultError("empty result carries protected admission")
    elif outcome == "owner_admission_verified":
        if not paths or receipt_required is not True:
            raise AdmissionResultError("verified result lacks protected admission")
    else:
        raise AdmissionResultError("result outcome is invalid")
    return {
        "base_commit": base_commit,
        "head_commit": head_commit,
        "outcome": outcome,
        "protected_paths": list(paths),
        "receipt_required": receipt_required,
        "repository": repository,
        "version": RESULT_VERSION,
    }


def make_result(
    *,
    repository: str,
    base_commit: str,
    head_commit: str,
    protected_paths: list[str] | tuple[str, ...],
) -> dict[str, object]:
    paths = list(protected_paths)
    outcome = (
        "no_protected_paths_changed"
        if not paths
        else "owner_admission_verified"
    )
    return validate_result(
        {
            "base_commit": base_commit,
            "head_commit": head_commit,
            "outcome": outcome,
            "protected_paths": paths,
            "receipt_required": bool(paths),
            "repository": repository,
            "version": RESULT_VERSION,
        }
    )


def validate_result_for_snapshot(
    result: Mapping[str, object], snapshot: PullRequestSnapshot
) -> dict[str, object]:
    snapshot = validate_snapshot(snapshot.as_dict())
    validated = validate_result(result)
    if (
        validated["repository"] != snapshot.repository
        or validated["base_commit"] != snapshot.base_commit
        or validated["head_commit"] != snapshot.head_commit
    ):
        raise AdmissionResultError("result is bound to a different pull request snapshot")
    if snapshot.state != "open":
        raise AdmissionResultError("result is bound to a closed pull request")
    if snapshot.base_ref != "main":
        raise AdmissionResultError("result is bound to a non-main base")
    return validated


def make_state(
    *,
    snapshot: Mapping[str, object] | None,
    result: Mapping[str, object] | None = None,
    error_code: str | None = None,
) -> dict[str, object]:
    if isinstance(snapshot, PullRequestSnapshot):
        snapshot = snapshot.as_dict()
    elif snapshot is not None and not isinstance(snapshot, Mapping):
        raise AdmissionResultError("state snapshot is not an object")
    if result is not None:
        if snapshot is None:
            raise AdmissionResultError("verified state lacks a snapshot")
        parsed_snapshot = validate_snapshot(snapshot)
        parsed_result = validate_result_for_snapshot(result, parsed_snapshot)
        if error_code is not None:
            raise AdmissionResultError("verified state carries an error")
        state = "verified"
        canonical_result = parsed_result
    else:
        if not isinstance(error_code, str) or error_code not in ERROR_CODES:
            raise AdmissionResultError("failure state has an invalid error code")
        if snapshot is not None:
            validate_snapshot(snapshot)
        state = "failed"
        canonical_result = None
    return {
        "error_code": error_code,
        "result": canonical_result,
        "snapshot": dict(snapshot) if snapshot is not None else None,
        "state": state,
        "version": STATE_VERSION,
    }


def validate_state(document: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(document, Mapping):
        raise AdmissionResultError("state is not an object")
    if set(document) != STATE_KEYS or document["version"] != STATE_VERSION:
        raise AdmissionResultError("state envelope is not the closed v1 set")
    raw_snapshot = document["snapshot"]
    snapshot = None if raw_snapshot is None else validate_snapshot(raw_snapshot)
    state = document["state"]
    result = document["result"]
    error_code = document["error_code"]
    if state == "verified":
        if snapshot is None or not isinstance(result, Mapping) or error_code is not None:
            raise AdmissionResultError("verified state is incomplete")
        canonical_result = validate_result_for_snapshot(result, snapshot)
    elif state == "failed":
        if result is not None or not isinstance(error_code, str) or error_code not in ERROR_CODES:
            raise AdmissionResultError("failed state is incomplete")
        canonical_result = None
    else:
        raise AdmissionResultError("state outcome is invalid")
    return {
        "error_code": error_code,
        "result": canonical_result,
        "snapshot": snapshot.as_dict() if snapshot is not None else None,
        "state": state,
        "version": STATE_VERSION,
    }


def external_id(snapshot: PullRequestSnapshot) -> str:
    """Build audit metadata; it is never used as authorization by itself."""

    snapshot = validate_snapshot(snapshot.as_dict())

    identity = {
        "base_commit": snapshot.base_commit,
        "base_ref": snapshot.base_ref,
        "body_sha256": snapshot.body_sha256,
        "head_commit": snapshot.head_commit,
        "head_repository": snapshot.head_repository,
        "pull_request": snapshot.pull_request,
        "repository": snapshot.repository,
        "state": snapshot.state,
        "version": RESULT_VERSION,
    }
    encoded = canonical_json_bytes(identity).decode("ascii")
    value = f"{RESULT_VERSION}:{encoded}"
    if len(value.encode("ascii")) > 1024:
        raise AdmissionResultError("external identity is oversized")
    return value


def parse_external_id(value: object) -> PullRequestSnapshot:
    """Parse and validate one publisher reconciliation identity."""

    prefix = f"{RESULT_VERSION}:"
    if not isinstance(value, str) or not value.startswith(prefix):
        raise AdmissionResultError("external identity is not v1")
    try:
        encoded_value = value.encode("ascii")
    except UnicodeError as error:
        raise AdmissionResultError("external identity is not ASCII") from error
    if len(encoded_value) > 1024:
        raise AdmissionResultError("external identity is oversized")
    encoded = encoded_value[len(prefix) :]
    document = parse_canonical_json(encoded)
    if not isinstance(document, Mapping) or set(document) != {
        "base_commit",
        "base_ref",
        "body_sha256",
        "head_commit",
        "head_repository",
        "pull_request",
        "repository",
        "state",
        "version",
    }:
        raise AdmissionResultError("external identity fields are invalid")
    if document["version"] != RESULT_VERSION:
        raise AdmissionResultError("external identity version is invalid")
    snapshot_document = dict(document)
    snapshot_document["version"] = SNAPSHOT_VERSION
    snapshot = validate_snapshot(snapshot_document)
    if external_id(snapshot) != value:
        raise AdmissionResultError("external identity is not canonical")
    return snapshot
