#!/usr/bin/env python3
"""Evaluate the frozen Git object fixtures for one admission transition."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any, Callable


TRANSITION_SCHEMA = "privacy-age-admission-transition/v1"
OBJECT_FIXTURE_SCHEMA = "privacy-age-admission-transition-object-fixture/v1"
PREDECESSOR_FIXTURE_SCHEMA = "privacy-age-integrity-predecessor-fixture/v1"

_OBJECT_ID = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ROLE_ORDER = {"pr_base": 0, "predecessor": 1, "target": 2}
_EXPECTED_REPOSITORY = "nisavid/dotfiles"
_EXPECTED_PULL_REQUEST = 172
_EXPECTED_MIGRATION = "one-time-transition-pr-172-v1"
_EXPECTED_SNAPSHOTS = {
    "pr_base": (
        "7fbe8e520cf85c16de4ba05b9b016b153340ed05",
        "40e4f9ff2373527400e2c7bbc2ffdf879cf5fa7b",
    ),
    "predecessor": (
        "0e981202824a76043083039a407dd165e243d544",
        "ac2898cd79618f85d527e62c83537555f360be83",
    ),
    "target": (
        "d2c15543baddd922b2ce1f087ea38ada29f323fd",
        "d902f2ae6c53e53ce0983a95415727f3a5b11e9b",
    ),
}
_EXPECTED_FIXTURE_ROLES = {
    "active-predecessor": ("predecessor",),
    "pr-base-and-target": ("pr_base", "target"),
}
_EXPECTED_ACTIVE_AUTHORITY = (
    ".github/age-admission/allowed_signers",
    ".github/age-admission/privacy-scan-reviewed-findings-v1.json",
    "scripts/create-age-admission-receipt",
    "scripts/run-trusted-age-admission",
    "scripts/privacy_age_admission.py",
    "scripts/privacy_age_admission_result.py",
    "scripts/privacy_age_pr_snapshot.py",
    "scripts/privacy_age_admission_publisher.py",
    "scripts/privacy_scan_review.py",
)
_EXPECTED_TRANSITIONS = {
    "owner_receipt": (
        "predecessor",
        "target",
        (
            ".github/age-admission/privacy-scan-reviewed-findings-v1.json",
            ".github/workflows/platform-portability.yml",
            "docs/ENCRYPTION.md",
            "scripts/privacy-scan",
            "scripts/privacy_age_integrity_gate.py",
            "scripts/privacy_scan_review.py",
        ),
    ),
    "app_result": (
        "pr_base",
        "target",
        (
            ".github/age-admission/privacy-scan-reviewed-findings-v1.json",
            ".github/workflows/platform-portability.yml",
            ".github/workflows/privacy-age-integrity.yml",
            "docs/ENCRYPTION.md",
            "scripts/privacy-scan",
            "scripts/privacy_age_admission_publisher.py",
            "scripts/privacy_age_admission_result.py",
            "scripts/privacy_age_integrity_gate.py",
            "scripts/privacy_age_pr_snapshot.py",
            "scripts/privacy_scan_review.py",
        ),
    ),
}
_EXPECTED_STRUCTURAL_ENTRY_PATHS = {
    "pr_base": frozenset(
        {
            ".github/workflows/platform-portability.yml",
            ".github/workflows/privacy-age-integrity.yml",
            "docs/ENCRYPTION.md",
            "scripts/privacy-scan",
            "scripts/privacy_age_integrity_gate.py",
        }
    ),
    "predecessor": frozenset(
        {
            ".github/workflows/platform-portability.yml",
            "docs/ENCRYPTION.md",
            "scripts/privacy-scan",
            "scripts/privacy_age_integrity_gate.py",
        }
    ),
    "target": frozenset(
        set(_EXPECTED_ACTIVE_AUTHORITY)
        | set(_EXPECTED_TRANSITIONS["owner_receipt"][2])
        | set(_EXPECTED_TRANSITIONS["app_result"][2])
    ),
}
_PROTECTED_EXACT_PATHS = frozenset(
    {
        ".github/age-admission/allowed_signers",
        ".github/age-admission/privacy-scan-reviewed-findings-v1.json",
        ".privacy-age-envelopes.json",
        "docs/ENCRYPTION.md",
        "home/.chezmoi.toml.tmpl",
        "home/private_dot_local/lib/agent-equipment/agent_equipment/secrets.py",
        "scripts/admit-age-envelopes",
        "scripts/agent_equipment_public_data.py",
        "scripts/create-age-admission-receipt",
        "scripts/run-trusted-age-admission",
        "scripts/privacy-scan",
        "scripts/privacy_scan_review.py",
        "scripts/privacy_age_admission.py",
        "scripts/privacy_age_envelopes.py",
        "scripts/privacy_age_integrity_gate.py",
        "scripts/privacy_age_admission_result.py",
        "scripts/privacy_age_pr_snapshot.py",
        "scripts/privacy_age_admission_publisher.py",
    }
)
_PROTECTED_OPTIONAL_PATHS = frozenset({".gitattributes", ".gitmodules"})
_PROTECTED_PREFIXES = (".github/actions/", ".github/workflows/")
_REVIEW_RECORD_PATH = (
    ".github/age-admission/privacy-scan-reviewed-findings-v1.json"
)
_REVIEW_RECORD_SIZE = 2_990
_REVIEW_RECORD_SHA256 = (
    "e216f5da8acc5ec1e3f1bd383dfbb2170ba385988f2824002f1047129f863bcf"
)
_MAX_REVIEW_RECORD_BYTES = 512 * 1024
_MAX_FINDING_INPUT_BYTES = 4 * 1024 * 1024
_FINDING_VALIDATION_TIMEOUT_SECONDS = 30.0
_EXPECTED_FINDING_IDENTITIES = (
    (
        ".github/workflows/privacy-age-integrity.yml",
        0,
        "provider-token",
        "runtime_action_output_reference",
        "sha256:fc988d046c322bc5974da1d2025db0cba6e2a6d64466d2b1f705fb355e0a7c41",
        "100644",
        "ac6d1610d245bac428b56504d7872b3424e4523f",
        28_304,
    ),
    (
        "scripts/privacy_age_admission_publisher.py",
        163,
        "provider-token",
        "runtime_checks_bearer_header",
        "sha256:8c4caac7ac5e8cd87623b6b53dba33f2c07f06a20d2539abc36009e5be8d7eeb",
        "100644",
        "42fc7887c8cb59625db8e103131eb089611fa90f",
        23_420,
    ),
    (
        "scripts/privacy_age_pr_snapshot.py",
        83,
        "provider-token",
        "runtime_pr_read_bearer_header",
        "sha256:f2c9a7cfd2ff2be9d99085d46f0b274d7b913a9fcd8b01729e7823294f119d49",
        "100644",
        "06ff19944db5ff83ca32044fb7f0c52d10626682",
        11_309,
    ),
    (
        "tests/test_privacy_age_admission_app.py",
        444,
        "provider-token",
        "mocked_test_canary",
        "sha256:603e0ba78e3055609b7f3469c769f88d8eba3fbe837f956d52ef3b19e3bd7e7d",
        "100644",
        "690b3534e3322919d65c67a8b035fa84841aaf79",
        18_479,
    ),
    (
        "tests/test_privacy_age_admission_app.py",
        479,
        "provider-token",
        "mocked_test_canary",
        "sha256:603e0ba78e3055609b7f3469c769f88d8eba3fbe837f956d52ef3b19e3bd7e7d",
        "100644",
        "690b3534e3322919d65c67a8b035fa84841aaf79",
        18_479,
    ),
)
_EXPECTED_POLICY_IDENTITIES = (
    (
        "home/private_dot_local/lib/agent-equipment/agent_equipment/secrets.py",
        "sha256:d0f16da2ee64172cc277d1156e2ec19028c828c8f3bcd9a0c240c8ea8dcdf358",
        "100644",
        "05d838b88cf32f56feda5b803a97c5a8b68516d0",
        155_106,
    ),
    (
        "scripts/agent_equipment_public_data.py",
        "sha256:8b896e011ebf82a61ed457a07a3a13bd6b4b80d98537de99ed13f4363591ce4d",
        "100644",
        "840b7aa365be48307699a273250eeb044e3ade63",
        648,
    ),
    (
        "scripts/privacy-scan",
        "sha256:a6c4ff4e7bb41c1a1aef5fadd92ba39a5733d4ec62f2025f591ae3cf25365b91",
        "100755",
        "685da1a66cc6b427af4a4d99bb97ac02d02d4e6b",
        29_799,
    ),
    (
        "scripts/privacy_scan_review.py",
        "sha256:7a04892d1f01dc51d71a616864fa198e421588f14b1f19e120ba3685cc5aa9e5",
        "100644",
        "c60312be9feeecaf8698b09f93481fb2ba8919b4",
        16_983,
    ),
)
_FINDING_INPUT_PATHS = frozenset(
    identity[0] for identity in _EXPECTED_FINDING_IDENTITIES
)
_POLICY_INPUT_PATHS = frozenset(
    identity[0] for identity in _EXPECTED_POLICY_IDENTITIES
)
_REVIEW_BLOB_LIMITS = {
    _REVIEW_RECORD_PATH: _MAX_REVIEW_RECORD_BYTES,
    **{
        path: _MAX_FINDING_INPUT_BYTES
        for path in _FINDING_INPUT_PATHS | _POLICY_INPUT_PATHS
    },
}


class TransitionEvaluationError(RuntimeError):
    """The frozen transition input did not match its closed contract."""


@dataclass(frozen=True)
class EvaluatedSnapshot:
    role: str
    commit: str
    root_tree: str
    entries: tuple[EvaluatedTreeEntry, ...] = field(default=(), compare=False)


@dataclass(frozen=True)
class EvaluatedTreeEntry:
    path: str
    kind: str
    mode: str
    object_id: str
    size: int | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class EvaluatedTransitionEntry:
    path: str
    base: EvaluatedTreeEntry | None
    head: EvaluatedTreeEntry | None


@dataclass(frozen=True)
class EvaluatedProtectedTransition:
    name: str
    base_role: str
    head_role: str
    entries: tuple[EvaluatedTransitionEntry, ...]


@dataclass(frozen=True)
class EvaluatedFinding:
    path: str
    line: int
    rule: str
    category: str
    content_sha256: str
    mode: str
    object_id: str
    file_size: int
    file_sha256: str


@dataclass(frozen=True)
class EvaluatedPolicyFile:
    path: str
    content_sha256: str
    mode: str
    object_id: str
    file_size: int
    file_sha256: str


@dataclass(frozen=True)
class EvaluatedFixture:
    name: str
    pack_sha256: str
    object_count: int
    snapshots: tuple[EvaluatedSnapshot, ...]


@dataclass(frozen=True)
class TransitionEvaluation:
    repository: str
    pull_request: int
    migration: str
    snapshots: tuple[EvaluatedSnapshot, ...]
    fixtures: tuple[EvaluatedFixture, ...]
    active_authority: tuple[EvaluatedTreeEntry, ...]
    transitions: tuple[EvaluatedProtectedTransition, ...]
    findings: tuple[EvaluatedFinding, ...]
    review_policy: tuple[EvaluatedPolicyFile, ...]


def _closed_object(value: Any, keys: set[str], *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise TransitionEvaluationError(f"{label} does not match its closed schema")
    return value


def _closed_array(value: Any, *, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise TransitionEvaluationError(f"{label} must be an array")
    return value


def _string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TransitionEvaluationError(f"{label} must be a nonempty string")
    return value


def _positive_integer(value: Any, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise TransitionEvaluationError(f"{label} must be a positive integer")
    return value


def _object_id(value: Any, *, label: str) -> str:
    object_id = _string(value, label=label)
    if _OBJECT_ID.fullmatch(object_id) is None:
        raise TransitionEvaluationError(f"{label} must be a SHA-1 object ID")
    return object_id


def _digest(value: Any, *, label: str) -> str:
    digest = _string(value, label=label)
    if _DIGEST.fullmatch(digest) is None:
        raise TransitionEvaluationError(f"{label} must be a SHA-256 digest")
    return digest


def _content_digest(value: Any, *, label: str) -> str:
    digest = _string(value, label=label)
    if not digest.startswith("sha256:") or _DIGEST.fullmatch(digest[7:]) is None:
        raise TransitionEvaluationError(f"{label} must be a SHA-256 content identity")
    return digest


def _nonnegative_integer(value: Any, *, label: str) -> int:
    if type(value) is not int or value < 0:
        raise TransitionEvaluationError(f"{label} must be a nonnegative integer")
    return value


def _canonical_path(value: Any, *, label: str) -> str:
    path = _string(value, label=label)
    relative = PurePosixPath(path)
    if (
        relative.is_absolute()
        or relative.as_posix() != path
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise TransitionEvaluationError(f"{label} must be a canonical repository path")
    return path


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TransitionEvaluationError("JSON contains a duplicate key")
        result[key] = value
    return result


def _load_json_bytes(contents: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            contents.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as error:
        if isinstance(error, TransitionEvaluationError):
            raise
        raise TransitionEvaluationError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise TransitionEvaluationError(f"{label} must be a JSON object")
    return value


def _parse_review_record(
    contents: bytes,
) -> tuple[
    tuple[tuple[str, int, str, str, str, str, str], ...],
    tuple[tuple[str, str], ...],
]:
    try:
        record = _closed_object(
            _load_json_bytes(contents, label="review record"),
            {
                "entries",
                "policy",
                "record_id",
                "reviewed_commit",
                "reviewer",
                "version",
            },
            label="review record",
        )
        _string(record["version"], label="review record.version")
        _string(record["record_id"], label="review record.record_id")
        _object_id(
            record["reviewed_commit"],
            label="review record.reviewed_commit",
        )
        _string(record["reviewer"], label="review record.reviewer")
        policy = _closed_object(
            record["policy"],
            {"files", "version"},
            label="review record.policy",
        )
        _string(policy["version"], label="review record.policy.version")
        policy_files = policy["files"]
        if not isinstance(policy_files, dict) or not policy_files:
            raise TransitionEvaluationError(
                "review record.policy.files must be a nonempty object"
            )
        parsed_policy = tuple(
            (
                _canonical_path(
                    raw_path,
                    label="review record.policy.files path",
                ),
                _content_digest(
                    raw_digest,
                    label="review record.policy.files digest",
                ),
            )
            for raw_path, raw_digest in policy_files.items()
        )

        parsed: list[tuple[str, int, str, str, str, str, str]] = []
        for index, raw_entry in enumerate(
            _closed_array(record["entries"], label="review record.entries")
        ):
            label = f"review record.entries[{index}]"
            entry = _closed_object(
                raw_entry,
                {
                    "category",
                    "content_sha256",
                    "evidence",
                    "git_blob_sha1",
                    "line",
                    "mode",
                    "path",
                    "rule",
                },
                label=label,
            )
            category = _string(entry["category"], label=f"{label}.category")
            evidence = _closed_object(
                entry["evidence"],
                {"claims", "kind", "reviewed_lines"},
                label=f"{label}.evidence",
            )
            evidence_kind = _string(
                evidence["kind"],
                label=f"{label}.evidence.kind",
            )
            if evidence_kind != category:
                raise TransitionEvaluationError(
                    "review record evidence kind does not match its category"
                )
            claims = tuple(
                _string(claim, label=f"{label}.evidence.claims[{claim_index}]")
                for claim_index, claim in enumerate(
                    _closed_array(
                        evidence["claims"],
                        label=f"{label}.evidence.claims",
                    )
                )
            )
            if not claims or len(set(claims)) != len(claims):
                raise TransitionEvaluationError(
                    "review record evidence claims must be nonempty and unique"
                )
            reviewed_lines = tuple(
                _nonnegative_integer(
                    line,
                    label=f"{label}.evidence.reviewed_lines[{line_index}]",
                )
                for line_index, line in enumerate(
                    _closed_array(
                        evidence["reviewed_lines"],
                        label=f"{label}.evidence.reviewed_lines",
                    )
                )
            )
            if not reviewed_lines:
                raise TransitionEvaluationError(
                    "review record evidence lines must be nonempty"
                )
            parsed.append(
                (
                    _canonical_path(entry["path"], label=f"{label}.path"),
                    _nonnegative_integer(entry["line"], label=f"{label}.line"),
                    _string(entry["rule"], label=f"{label}.rule"),
                    category,
                    _content_digest(
                        entry["content_sha256"],
                        label=f"{label}.content_sha256",
                    ),
                    _string(entry["mode"], label=f"{label}.mode"),
                    _object_id(
                        entry["git_blob_sha1"],
                        label=f"{label}.git_blob_sha1",
                    ),
                )
            )
    except TransitionEvaluationError as error:
        raise TransitionEvaluationError("review record is malformed") from error

    expected = tuple(identity[:-1] for identity in _EXPECTED_FINDING_IDENTITIES)
    if tuple(parsed) != expected:
        raise TransitionEvaluationError(
            "review record findings do not match the one-time migration"
        )
    expected_policy = tuple(
        identity[:2] for identity in _EXPECTED_POLICY_IDENTITIES
    )
    if parsed_policy != expected_policy:
        raise TransitionEvaluationError(
            "review record policy does not match the one-time migration"
        )
    if (
        len(contents) != _REVIEW_RECORD_SIZE
        or hashlib.sha256(contents).hexdigest() != _REVIEW_RECORD_SHA256
    ):
        raise TransitionEvaluationError(
            "review record bytes do not match the one-time migration"
        )
    return tuple(parsed), parsed_policy


def _repository_path(repository_root: Path, raw: Any, *, label: str) -> Path:
    value = _canonical_path(raw, label=label)
    relative = PurePosixPath(value)
    root = repository_root.resolve(strict=True)
    try:
        resolved = root.joinpath(*relative.parts).resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise TransitionEvaluationError(f"{label} is unavailable") from error
    if not resolved.is_file():
        raise TransitionEvaluationError(f"{label} must name a regular file")
    return resolved


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for variable in tuple(environment):
        if variable.startswith("GIT_"):
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


def _git(
    *arguments: str,
    cwd: Path,
    input_bytes: bytes | None = None,
) -> bytes:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=cwd,
            input=input_bytes,
            check=True,
            capture_output=True,
            env=_git_environment(),
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise TransitionEvaluationError("Git object fixture evaluation failed") from error
    return completed.stdout


def _parse_snapshot(value: Any, *, label: str) -> EvaluatedSnapshot:
    item = _closed_object(
        value,
        {"role", "commit", "root_tree"},
        label=label,
    )
    role = _string(item["role"], label=f"{label}.role")
    if role not in _ROLE_ORDER:
        raise TransitionEvaluationError(f"{label}.role is not recognized")
    return EvaluatedSnapshot(
        role=role,
        commit=_object_id(item["commit"], label=f"{label}.commit"),
        root_tree=_object_id(item["root_tree"], label=f"{label}.root_tree"),
    )


def _parse_structural_entry(value: Any, *, label: str) -> EvaluatedTreeEntry:
    if not isinstance(value, list) or len(value) != 4:
        raise TransitionEvaluationError(f"{label} must be a four-field entry")
    path = _canonical_path(value[0], label=f"{label}.path")
    kind = _string(value[1], label=f"{label}.kind")
    mode = _string(value[2], label=f"{label}.mode")
    if kind != "blob" or mode not in {"100644", "100755"}:
        raise TransitionEvaluationError(f"{label} must describe a regular blob")
    return EvaluatedTreeEntry(
        path=path,
        kind=kind,
        mode=mode,
        object_id=_object_id(value[3], label=f"{label}.object_id"),
    )


def _parse_structure(
    value: Any,
) -> tuple[
    dict[str, dict[str, EvaluatedTreeEntry]],
    tuple[str, ...],
    tuple[tuple[str, str, str, tuple[str, ...]], ...],
]:
    structure = _closed_object(
        value,
        {"entries", "active_authority", "transitions"},
        label="transition.structure",
    )
    raw_entries = _closed_object(
        structure["entries"],
        set(_ROLE_ORDER),
        label="transition.structure.entries",
    )
    entries_by_role: dict[str, dict[str, EvaluatedTreeEntry]] = {}
    for role in _ROLE_ORDER:
        entries: dict[str, EvaluatedTreeEntry] = {}
        for index, raw_entry in enumerate(
            _closed_array(
                raw_entries[role],
                label=f"transition.structure.entries.{role}",
            )
        ):
            entry = _parse_structural_entry(
                raw_entry,
                label=f"transition.structure.entries.{role}[{index}]",
            )
            if entry.path in entries:
                raise TransitionEvaluationError("structural entry paths must be unique")
            entries[entry.path] = entry
        if frozenset(entries) != _EXPECTED_STRUCTURAL_ENTRY_PATHS[role]:
            raise TransitionEvaluationError(
                "structural entry paths do not match the one-time migration"
            )
        entries_by_role[role] = entries

    active_authority = tuple(
        _canonical_path(path, label=f"transition.structure.active_authority[{index}]")
        for index, path in enumerate(
            _closed_array(
                structure["active_authority"],
                label="transition.structure.active_authority",
            )
        )
    )
    if active_authority != _EXPECTED_ACTIVE_AUTHORITY:
        raise TransitionEvaluationError(
            "active authority paths do not match the one-time migration"
        )

    transitions: list[tuple[str, str, str, tuple[str, ...]]] = []
    seen_names: set[str] = set()
    for index, raw_transition in enumerate(
        _closed_array(
            structure["transitions"],
            label="transition.structure.transitions",
        )
    ):
        label = f"transition.structure.transitions[{index}]"
        transition = _closed_object(
            raw_transition,
            {"name", "base_role", "head_role", "paths"},
            label=label,
        )
        name = _string(transition["name"], label=f"{label}.name")
        base_role = _string(transition["base_role"], label=f"{label}.base_role")
        head_role = _string(transition["head_role"], label=f"{label}.head_role")
        paths = tuple(
            _canonical_path(path, label=f"{label}.paths[{path_index}]")
            for path_index, path in enumerate(
                _closed_array(transition["paths"], label=f"{label}.paths")
            )
        )
        expected = _EXPECTED_TRANSITIONS.get(name)
        if name in seen_names or expected != (base_role, head_role, paths):
            raise TransitionEvaluationError(
                "protected transition does not match the one-time migration"
            )
        seen_names.add(name)
        transitions.append((name, base_role, head_role, paths))
    if seen_names != set(_EXPECTED_TRANSITIONS):
        raise TransitionEvaluationError(
            "protected transitions do not match the one-time migration"
        )
    return entries_by_role, active_authority, tuple(transitions)


def _parse_pack(value: Any, *, label: str) -> dict[str, Any]:
    pack = _closed_object(
        value,
        {"path", "sha256", "size", "object_count"},
        label=label,
    )
    return {
        "path": _string(pack["path"], label=f"{label}.path"),
        "sha256": _digest(pack["sha256"], label=f"{label}.sha256"),
        "size": _positive_integer(pack["size"], label=f"{label}.size"),
        "object_count": _positive_integer(
            pack["object_count"],
            label=f"{label}.object_count",
        ),
    }


def _parse_fixture_manifest(
    contents: bytes,
    *,
    expected_snapshots: tuple[EvaluatedSnapshot, ...],
) -> tuple[dict[str, Any], tuple[EvaluatedSnapshot, ...]]:
    value = _load_json_bytes(contents, label="object fixture manifest")
    schema = value.get("schema")
    if schema == PREDECESSOR_FIXTURE_SCHEMA:
        item = _closed_object(value, {"schema", "pack", "snapshot"}, label="fixture")
        snapshot = _closed_object(
            item["snapshot"],
            {
                "commit",
                "shallow_boundary",
                "omitted_parent",
                "root_tree",
                "integrity_gate_blob",
            },
            label="fixture.snapshot",
        )
        commit = _object_id(snapshot["commit"], label="fixture.snapshot.commit")
        if _object_id(
            snapshot["shallow_boundary"],
            label="fixture.snapshot.shallow_boundary",
        ) != commit:
            raise TransitionEvaluationError("predecessor shallow boundary is not its commit")
        _object_id(snapshot["omitted_parent"], label="fixture.snapshot.omitted_parent")
        _object_id(
            snapshot["integrity_gate_blob"],
            label="fixture.snapshot.integrity_gate_blob",
        )
        snapshots = (
            EvaluatedSnapshot(
                role="predecessor",
                commit=commit,
                root_tree=_object_id(
                    snapshot["root_tree"],
                    label="fixture.snapshot.root_tree",
                ),
            ),
        )
    elif schema == OBJECT_FIXTURE_SCHEMA:
        item = _closed_object(value, {"schema", "pack", "snapshots"}, label="fixture")
        snapshots = tuple(
            _parse_snapshot(snapshot, label=f"fixture.snapshots[{index}]")
            for index, snapshot in enumerate(
                _closed_array(item["snapshots"], label="fixture.snapshots")
            )
        )
    else:
        raise TransitionEvaluationError("object fixture schema is not recognized")

    if snapshots != expected_snapshots:
        raise TransitionEvaluationError("object fixture snapshots do not match the transition")
    return _parse_pack(item["pack"], label="fixture.pack"), snapshots


def _indexed_objects(repository: Path) -> set[str]:
    git_dir = Path(
        _git("rev-parse", "--git-dir", cwd=repository).decode("ascii").strip()
    )
    if not git_dir.is_absolute():
        git_dir = repository / git_dir
    indexes = tuple((git_dir / "objects/pack").glob("*.idx"))
    if len(indexes) != 1:
        raise TransitionEvaluationError("object fixture did not produce one pack index")
    try:
        with indexes[0].open("rb") as index:
            completed = subprocess.run(
                ("git", "show-index"),
                cwd=repository,
                stdin=index,
                check=True,
                capture_output=True,
                env=_git_environment(),
                timeout=30,
            )
    except (OSError, subprocess.SubprocessError) as error:
        raise TransitionEvaluationError("Git object fixture evaluation failed") from error
    try:
        return {
            line.split(maxsplit=2)[1].decode("ascii")
            for line in completed.stdout.splitlines()
        }
    except (IndexError, UnicodeDecodeError) as error:
        raise TransitionEvaluationError("object fixture index is malformed") from error


def _materialize_tree_entries(
    repository: Path,
    snapshot: EvaluatedSnapshot,
    *,
    structural_paths: frozenset[str],
    retained_paths: frozenset[str],
    blob_limits: dict[str, int],
) -> tuple[tuple[EvaluatedTreeEntry, ...], dict[str, bytes]]:
    raw_entries = _git(
        "ls-tree",
        "-r",
        "-t",
        "-z",
        "--full-tree",
        snapshot.root_tree,
        cwd=repository,
    )
    entries: list[EvaluatedTreeEntry] = []
    retained: dict[str, bytes] = {}
    for index, record in enumerate(raw_entries.split(b"\0")):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, raw_object_id = metadata.split()
            path = raw_path.decode("utf-8")
            object_id = raw_object_id.decode("ascii")
            mode_text = mode.decode("ascii")
            kind_text = kind.decode("ascii")
        except (UnicodeDecodeError, ValueError) as error:
            raise TransitionEvaluationError(
                f"snapshot tree entry {index} is malformed"
            ) from error
        size: int | None = None
        sha256: str | None = None
        if path in structural_paths | retained_paths and kind_text == "blob":
            expected_size: int | None = None
            if path in blob_limits:
                try:
                    expected_size = int(
                        _git("cat-file", "-s", object_id, cwd=repository).strip()
                    )
                except ValueError as error:
                    raise TransitionEvaluationError(
                        "finding input size is unavailable"
                    ) from error
                if expected_size > blob_limits[path]:
                    raise TransitionEvaluationError(
                        "finding validation resource limit exceeded"
                    )
            contents = _git("cat-file", "blob", object_id, cwd=repository)
            if expected_size is not None and len(contents) != expected_size:
                raise TransitionEvaluationError(
                    "finding input size changed during materialization"
                )
            git_object_id = hashlib.sha1(
                b"blob " + str(len(contents)).encode("ascii") + b"\0" + contents
            ).hexdigest()
            if git_object_id != object_id:
                raise TransitionEvaluationError(
                    "structural blob bytes do not match their Git object ID"
                )
            size = len(contents)
            sha256 = hashlib.sha256(contents).hexdigest()
            if path in retained_paths:
                retained[path] = contents
        entries.append(
            EvaluatedTreeEntry(
                path=path,
                kind=kind_text,
                mode=mode_text,
                object_id=object_id,
                size=size,
                sha256=sha256,
            )
        )
    return tuple(entries), retained


def _evaluate_pack(
    *,
    fixture_manifest: Path,
    pack_spec: dict[str, Any],
    snapshots: tuple[EvaluatedSnapshot, ...],
    structural_paths: frozenset[str],
    retained_paths: frozenset[str],
    blob_limits: dict[str, int],
) -> tuple[
    str,
    int,
    tuple[EvaluatedSnapshot, ...],
    dict[str, dict[str, bytes]],
]:
    pack_path = _repository_path(
        fixture_manifest.parent,
        pack_spec["path"],
        label="fixture.pack.path",
    )
    pack_bytes = pack_path.read_bytes()
    if len(pack_bytes) != pack_spec["size"]:
        raise TransitionEvaluationError("object fixture pack size does not match")
    pack_digest = hashlib.sha256(pack_bytes).hexdigest()
    if pack_digest != pack_spec["sha256"]:
        raise TransitionEvaluationError("object fixture pack digest does not match")

    with TemporaryDirectory(prefix="privacy-age-transition-") as temporary:
        repository = Path(temporary) / "objects"
        repository.mkdir()
        _git("init", "--quiet", "--object-format=sha1", cwd=repository)
        _git("index-pack", "--stdin", "--fix-thin", cwd=repository, input_bytes=pack_bytes)
        indexed = _indexed_objects(repository)
        if len(indexed) != pack_spec["object_count"]:
            raise TransitionEvaluationError("object fixture pack count does not match")

        expected_objects: set[str] = set()
        materialized_snapshots: list[EvaluatedSnapshot] = []
        retained_by_role: dict[str, dict[str, bytes]] = {}
        for snapshot in snapshots:
            if _git("cat-file", "-t", snapshot.commit, cwd=repository).strip() != b"commit":
                raise TransitionEvaluationError("snapshot commit object is unavailable")
            commit_lines = _git("cat-file", "-p", snapshot.commit, cwd=repository).splitlines()
            tree_lines = [line for line in commit_lines if line.startswith(b"tree ")]
            if len(tree_lines) != 1:
                raise TransitionEvaluationError("snapshot commit does not name one root tree")
            observed_tree = tree_lines[0].split(maxsplit=1)[1].decode("ascii")
            if observed_tree != snapshot.root_tree:
                raise TransitionEvaluationError("snapshot root tree does not match its commit")
            if _git("cat-file", "-t", snapshot.root_tree, cwd=repository).strip() != b"tree":
                raise TransitionEvaluationError("snapshot root tree object is unavailable")
            closure = _git(
                "rev-list",
                "--objects",
                "--no-object-names",
                snapshot.root_tree,
                cwd=repository,
            )
            try:
                expected_objects.update(
                    line.decode("ascii") for line in closure.splitlines() if line
                )
            except UnicodeDecodeError as error:
                raise TransitionEvaluationError("object fixture closure is malformed") from error
            expected_objects.add(snapshot.commit)
            entries, retained = _materialize_tree_entries(
                repository,
                snapshot,
                structural_paths=structural_paths,
                retained_paths=(
                    retained_paths
                    if snapshot.role == "target"
                    else frozenset()
                ),
                blob_limits=(blob_limits if snapshot.role == "target" else {}),
            )
            materialized_snapshots.append(
                EvaluatedSnapshot(
                    role=snapshot.role,
                    commit=snapshot.commit,
                    root_tree=snapshot.root_tree,
                    entries=entries,
                )
            )
            if retained:
                retained_by_role[snapshot.role] = retained

        if indexed != expected_objects:
            raise TransitionEvaluationError("object fixture pack is not the exact object closure")

    return (
        pack_digest,
        len(indexed),
        tuple(materialized_snapshots),
        retained_by_role,
    )


def _entry_identity(entry: EvaluatedTreeEntry) -> tuple[str, str, str]:
    return (entry.kind, entry.mode, entry.object_id)


def _is_protected(path: str) -> bool:
    return (
        path in _PROTECTED_EXACT_PATHS
        or path in _PROTECTED_OPTIONAL_PATHS
        or any(path.startswith(prefix) for prefix in _PROTECTED_PREFIXES)
        or path.rsplit("/", 1)[-1].lower().endswith(".age")
    )


def _validate_structure(
    snapshots: tuple[EvaluatedSnapshot, ...],
    *,
    expected_entries: dict[str, dict[str, EvaluatedTreeEntry]],
    active_authority_paths: tuple[str, ...],
    transition_specs: tuple[tuple[str, str, str, tuple[str, ...]], ...],
) -> tuple[
    tuple[EvaluatedTreeEntry, ...],
    tuple[EvaluatedProtectedTransition, ...],
]:
    snapshots_by_role = {snapshot.role: snapshot for snapshot in snapshots}
    if set(snapshots_by_role) != set(_ROLE_ORDER):
        raise TransitionEvaluationError("transition must contain exactly three snapshots")
    entries_by_role = {
        role: {entry.path: entry for entry in snapshot.entries}
        for role, snapshot in snapshots_by_role.items()
    }

    for role, expected_by_path in expected_entries.items():
        actual_by_path = entries_by_role[role]
        for path, expected in expected_by_path.items():
            actual = actual_by_path.get(path)
            if actual is None or _entry_identity(actual) != _entry_identity(expected):
                raise TransitionEvaluationError(
                    "structural Git entry does not match the one-time migration"
                )
            if actual.kind != "blob" or actual.size is None or actual.sha256 is None:
                raise TransitionEvaluationError(
                    "structural Git entry bytes are not a verified regular blob"
                )

    target_entries = entries_by_role["target"]
    active_authority = tuple(target_entries[path] for path in active_authority_paths)
    evaluated_transitions: list[EvaluatedProtectedTransition] = []
    for name, base_role, head_role, paths in transition_specs:
        base_entries = entries_by_role[base_role]
        head_entries = entries_by_role[head_role]
        changed = {
            path
            for path in base_entries.keys() | head_entries.keys()
            if _is_protected(path)
            and (
                path not in base_entries
                or path not in head_entries
                or _entry_identity(base_entries[path]) != _entry_identity(head_entries[path])
            )
        }
        if changed != set(paths):
            raise TransitionEvaluationError(
                "protected Git delta does not match the one-time migration"
            )
        entries: list[EvaluatedTransitionEntry] = []
        for path in paths:
            base = base_entries.get(path)
            head = head_entries.get(path)
            expected_base = expected_entries[base_role].get(path)
            expected_head = expected_entries[head_role].get(path)
            if (
                (base is None) != (expected_base is None)
                or (head is None) != (expected_head is None)
                or (
                    base is not None
                    and expected_base is not None
                    and _entry_identity(base) != _entry_identity(expected_base)
                )
                or (
                    head is not None
                    and expected_head is not None
                    and _entry_identity(head) != _entry_identity(expected_head)
                )
            ):
                raise TransitionEvaluationError(
                    "protected transition entry does not match the one-time migration"
                )
            if any(
                entry is not None
                and (entry.kind != "blob" or entry.size is None or entry.sha256 is None)
                for entry in (base, head)
            ):
                raise TransitionEvaluationError(
                    "protected transition bytes are not verified regular blobs"
                )
            entries.append(EvaluatedTransitionEntry(path=path, base=base, head=head))
        evaluated_transitions.append(
            EvaluatedProtectedTransition(
                name=name,
                base_role=base_role,
                head_role=head_role,
                entries=tuple(entries),
            )
        )
    return active_authority, tuple(evaluated_transitions)


def _finding_time(clock: Callable[[], float]) -> float:
    try:
        value = clock()
    except Exception as error:
        raise TransitionEvaluationError(
            "finding validation time is unavailable"
        ) from error
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TransitionEvaluationError("finding validation time is unavailable")
    observed = float(value)
    if not math.isfinite(observed):
        raise TransitionEvaluationError("finding validation time is unavailable")
    return observed


def _require_finding_time(
    clock: Callable[[], float],
    *,
    started: float,
) -> None:
    elapsed = _finding_time(clock) - started
    if elapsed < 0 or elapsed > _FINDING_VALIDATION_TIMEOUT_SECONDS:
        raise TransitionEvaluationError("finding validation timed out")


def _validate_findings(
    snapshots: tuple[EvaluatedSnapshot, ...],
    *,
    retained_by_role: dict[str, dict[str, bytes]],
    clock: Callable[[], float],
    started: float,
) -> tuple[tuple[EvaluatedFinding, ...], tuple[EvaluatedPolicyFile, ...]]:
    _require_finding_time(clock, started=started)
    target = next(
        (snapshot for snapshot in snapshots if snapshot.role == "target"),
        None,
    )
    if target is None:
        raise TransitionEvaluationError("target finding snapshot is unavailable")
    target_entries = {entry.path: entry for entry in target.entries}
    retained = retained_by_role.get("target", {})
    record_bytes = retained.get(_REVIEW_RECORD_PATH)
    if record_bytes is None:
        raise TransitionEvaluationError("review record bytes are unavailable")
    _parsed_findings, _parsed_policy = _parse_review_record(record_bytes)
    _require_finding_time(clock, started=started)

    review_policy: list[EvaluatedPolicyFile] = []
    for identity in _EXPECTED_POLICY_IDENTITIES:
        (
            path,
            content_sha256,
            mode,
            object_id,
            file_size,
        ) = identity
        entry = target_entries.get(path)
        contents = retained.get(path)
        if (
            entry is None
            or entry.kind != "blob"
            or entry.mode != mode
            or entry.object_id != object_id
            or entry.size != file_size
            or contents is None
            or len(contents) != file_size
        ):
            raise TransitionEvaluationError(
                "review policy file does not match the one-time migration"
            )
        file_sha256 = hashlib.sha256(contents).hexdigest()
        git_object_id = hashlib.sha1(
            b"blob " + str(len(contents)).encode("ascii") + b"\0" + contents
        ).hexdigest()
        if (
            file_sha256 != content_sha256[7:]
            or entry.sha256 != file_sha256
            or git_object_id != object_id
        ):
            raise TransitionEvaluationError(
                "review policy bytes do not match the one-time migration"
            )
        review_policy.append(
            EvaluatedPolicyFile(
                path=path,
                content_sha256=content_sha256,
                mode=mode,
                object_id=object_id,
                file_size=file_size,
                file_sha256=file_sha256,
            )
        )
        _require_finding_time(clock, started=started)

    findings: list[EvaluatedFinding] = []
    for identity in _EXPECTED_FINDING_IDENTITIES:
        (
            path,
            line,
            rule,
            category,
            content_sha256,
            mode,
            object_id,
            file_size,
        ) = identity
        entry = target_entries.get(path)
        contents = retained.get(path)
        if (
            entry is None
            or entry.kind != "blob"
            or entry.mode != mode
            or entry.object_id != object_id
            or entry.size != file_size
            or contents is None
            or len(contents) != file_size
        ):
            raise TransitionEvaluationError(
                "reviewed finding file does not match the one-time migration"
            )
        file_sha256 = hashlib.sha256(contents).hexdigest()
        git_object_id = hashlib.sha1(
            b"blob " + str(len(contents)).encode("ascii") + b"\0" + contents
        ).hexdigest()
        if (
            file_sha256 != content_sha256[7:]
            or entry.sha256 != file_sha256
            or git_object_id != object_id
        ):
            raise TransitionEvaluationError(
                "reviewed finding bytes do not match the one-time migration"
            )
        findings.append(
            EvaluatedFinding(
                path=path,
                line=line,
                rule=rule,
                category=category,
                content_sha256=content_sha256,
                mode=mode,
                object_id=object_id,
                file_size=file_size,
                file_sha256=file_sha256,
            )
        )
        _require_finding_time(clock, started=started)
    return tuple(findings), tuple(review_policy)


def evaluate_transition(
    manifest_path: Path,
    *,
    repository_root: Path,
    after_structure: Callable[[TransitionEvaluation], None] | None = None,
    finding_clock: Callable[[], float] | None = None,
) -> TransitionEvaluation:
    """Validate and evaluate the closed, network-free transition fixtures."""

    clock = finding_clock if finding_clock is not None else time.monotonic
    finding_started = _finding_time(clock)
    root = repository_root.resolve(strict=True)
    transition_path = manifest_path.resolve(strict=True)
    try:
        transition_path.relative_to(root)
    except ValueError as error:
        raise TransitionEvaluationError("transition manifest is outside the repository") from error

    transition = _closed_object(
        _load_json_bytes(transition_path.read_bytes(), label="transition manifest"),
        {"schema", "migration", "repository", "pull_request", "fixtures", "structure"},
        label="transition manifest",
    )
    if transition["schema"] != TRANSITION_SCHEMA:
        raise TransitionEvaluationError("transition manifest schema is not recognized")
    migration = _string(transition["migration"], label="transition.migration")
    repository = _string(transition["repository"], label="transition.repository")
    pull_request = _positive_integer(
        transition["pull_request"],
        label="transition.pull_request",
    )
    if (
        repository != _EXPECTED_REPOSITORY
        or pull_request != _EXPECTED_PULL_REQUEST
        or migration != _EXPECTED_MIGRATION
    ):
        raise TransitionEvaluationError("transition identity does not match the one-time migration")
    expected_entries, active_authority_paths, transition_specs = _parse_structure(
        transition["structure"]
    )
    structural_paths = frozenset(
        path
        for entries in expected_entries.values()
        for path in entries
    )

    evaluated_fixtures: list[EvaluatedFixture] = []
    all_snapshots: list[EvaluatedSnapshot] = []
    retained_by_role: dict[str, dict[str, bytes]] = {}
    fixture_names: set[str] = set()
    for index, raw_fixture in enumerate(
        _closed_array(transition["fixtures"], label="transition.fixtures")
    ):
        label = f"transition.fixtures[{index}]"
        fixture = _closed_object(
            raw_fixture,
            {
                "name",
                "manifest",
                "manifest_sha256",
                "manifest_size",
                "snapshots",
            },
            label=label,
        )
        name = _string(fixture["name"], label=f"{label}.name")
        if name in fixture_names:
            raise TransitionEvaluationError("transition fixture names must be unique")
        fixture_names.add(name)
        expected_snapshots = tuple(
            _parse_snapshot(snapshot, label=f"{label}.snapshots[{snapshot_index}]")
            for snapshot_index, snapshot in enumerate(
                _closed_array(fixture["snapshots"], label=f"{label}.snapshots")
            )
        )
        if tuple(snapshot.role for snapshot in expected_snapshots) != _EXPECTED_FIXTURE_ROLES.get(
            name
        ):
            raise TransitionEvaluationError("snapshot roles do not match the one-time migration")
        fixture_manifest = _repository_path(
            root,
            fixture["manifest"],
            label=f"{label}.manifest",
        )
        fixture_bytes = fixture_manifest.read_bytes()
        if len(fixture_bytes) != _positive_integer(
            fixture["manifest_size"],
            label=f"{label}.manifest_size",
        ):
            raise TransitionEvaluationError("object fixture manifest size does not match")
        if hashlib.sha256(fixture_bytes).hexdigest() != _digest(
            fixture["manifest_sha256"],
            label=f"{label}.manifest_sha256",
        ):
            raise TransitionEvaluationError("object fixture manifest digest does not match")
        pack_spec, snapshots = _parse_fixture_manifest(
            fixture_bytes,
            expected_snapshots=expected_snapshots,
        )
        (
            pack_digest,
            object_count,
            materialized_snapshots,
            fixture_retained,
        ) = _evaluate_pack(
            fixture_manifest=fixture_manifest,
            pack_spec=pack_spec,
            snapshots=snapshots,
            structural_paths=structural_paths,
            retained_paths=(
                frozenset({_REVIEW_RECORD_PATH})
                | _FINDING_INPUT_PATHS
                | _POLICY_INPUT_PATHS
            ),
            blob_limits=_REVIEW_BLOB_LIMITS,
        )
        evaluated_fixtures.append(
            EvaluatedFixture(
                name=name,
                pack_sha256=pack_digest,
                object_count=object_count,
                snapshots=materialized_snapshots,
            )
        )
        all_snapshots.extend(materialized_snapshots)
        for role, contents in fixture_retained.items():
            if role in retained_by_role:
                raise TransitionEvaluationError(
                    "transition contains duplicate retained snapshot data"
                )
            retained_by_role[role] = contents

    roles = [snapshot.role for snapshot in all_snapshots]
    if sorted(roles) != sorted(_ROLE_ORDER):
        raise TransitionEvaluationError("transition must contain exactly three snapshot roles")
    ordered_snapshots = tuple(
        sorted(all_snapshots, key=lambda snapshot: _ROLE_ORDER[snapshot.role])
    )
    active_authority, evaluated_transitions = _validate_structure(
        ordered_snapshots,
        expected_entries=expected_entries,
        active_authority_paths=active_authority_paths,
        transition_specs=transition_specs,
    )
    evaluated_findings, evaluated_review_policy = _validate_findings(
        ordered_snapshots,
        retained_by_role=retained_by_role,
        clock=clock,
        started=finding_started,
    )
    if any(
        (snapshot.commit, snapshot.root_tree) != _EXPECTED_SNAPSHOTS[snapshot.role]
        for snapshot in ordered_snapshots
    ):
        raise TransitionEvaluationError("snapshot identities do not match the one-time migration")
    evaluation = TransitionEvaluation(
        repository=repository,
        pull_request=pull_request,
        migration=migration,
        snapshots=ordered_snapshots,
        fixtures=tuple(evaluated_fixtures),
        active_authority=active_authority,
        transitions=evaluated_transitions,
        findings=evaluated_findings,
        review_policy=evaluated_review_policy,
    )
    if after_structure is not None:
        after_structure(evaluation)
    return evaluation
