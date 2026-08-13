"""Pure validation for agent-equipment execution and release authority records."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from agent_equipment_json_schema import validate_document as _validate_schema
except ModuleNotFoundError:  # Loaded as a repo module rather than an executable.
    from scripts.agent_equipment_json_schema import (
        validate_document as _validate_schema,
    )
try:
    from agent_equipment_public_data import contains_literal_credential
except ModuleNotFoundError:  # Loaded as a repo module rather than an executable.
    from scripts.agent_equipment_public_data import contains_literal_credential


SCHEMA_DIRECTORY = Path(__file__).resolve().parent.parent / "docs/agent-equipment"
SCHEMA_NAME = "execution-authority-v1.schema.json"
MAX_EXECUTION_AUTHORITY_BYTES = 262_144
_UTC_TIMESTAMP_PATTERN = re.compile(
    r"^(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"[Tt](?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
    r"(?:[.,](?P<fraction>[0-9]{1,9}))?Z$"
)
_CHECKPOINT_BINDING_FIELDS = frozenset(
    {
        "step_id",
        "action_identity",
        "ordinal",
        "run_identity",
        "execution_domain_identity",
        "candidate_digest",
        "implementation_manifest_digest",
        "catalog_digest",
        "lock_digest",
        "plan_digest",
        "capability_set_digest",
        "captured_state_identity",
        "captured_state_digest",
        "route_capability_binding",
        "route_digest",
        "operation_digest",
        "compensation_operation",
        "pre_state_digest",
        "expected_post_state_digest",
        "pre_state",
        "expected_post_state",
        "surface",
    }
)
_CHECKPOINT_FIELDS = _CHECKPOINT_BINDING_FIELDS | {
    "phase",
    "phase_history",
    "invocation_state",
}
_CHECKPOINT_TRUSTED_BINDING_FIELDS = frozenset(
    {
        "candidate_digest",
        "implementation_manifest_digest",
        "catalog_digest",
        "lock_digest",
        "plan_digest",
        "capability_set_digest",
        "captured_state_identity",
        "captured_state_digest",
    }
)
_CHECKPOINT_PHASE_HISTORIES = frozenset(
    {
        ("prepared",),
        ("prepared", "completed"),
        ("prepared", "compensating"),
        ("prepared", "completed", "compensating"),
        ("prepared", "compensating", "compensated"),
        ("prepared", "completed", "compensating", "compensated"),
        ("prepared", "compensation_blocked"),
        ("prepared", "completed", "compensation_blocked"),
        ("prepared", "compensating", "compensation_blocked"),
        ("prepared", "completed", "compensating", "compensation_blocked"),
    }
)


@dataclass(frozen=True, order=True)
class Diagnostic:
    """One deterministic, secret-free authority validation failure."""

    path: str
    code: str
    message: str


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_digest(value: object) -> str:
    """Return the canonical SHA-256 digest used by v1 authority records."""

    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _diagnostic(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(path=path, code=code, message=message)


def _schema_valid(document: object) -> bool:
    return _validate_schema(
        document,
        schema_directory=SCHEMA_DIRECTORY,
        root_schema_name=SCHEMA_NAME,
        allowed_schema_names=frozenset({SCHEMA_NAME}),
    )


class _AmbiguousJson(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise _AmbiguousJson("duplicate JSON object member")
        document[key] = value
    return document


def _finite_number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise _AmbiguousJson("non-finite JSON number")
    return number


def _reject_constant(value: str) -> object:
    del value
    raise _AmbiguousJson("non-JSON numeric constant")


def parse_execution_authority_bytes(
    raw_bytes: object,
) -> tuple[object | None, tuple[Diagnostic, ...]]:
    """Strictly parse one bounded public authority record from raw bytes."""

    if type(raw_bytes) is not bytes or len(raw_bytes) > MAX_EXECUTION_AUTHORITY_BYTES:
        return None, (
            _diagnostic(
                "EXECUTION_AUTHORITY_BYTES_INVALID",
                "$",
                "The authority input is not one bounded raw byte stream.",
            ),
        )
    try:
        text = raw_bytes.decode("utf-8", errors="strict")
        document = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_float=_finite_number,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _AmbiguousJson, ValueError):
        return None, (
            _diagnostic(
                "EXECUTION_AUTHORITY_JSON_INVALID",
                "$",
                "The authority bytes are not unambiguous strict UTF-8 JSON.",
            ),
        )
    if not _schema_valid(document):
        return None, (
            _diagnostic(
                "EXECUTION_AUTHORITY_SCHEMA_INVALID",
                "$",
                "The authority document does not satisfy the checked-in closed schema.",
            ),
        )
    if contains_literal_credential(document):
        return None, (
            _diagnostic(
                "EXECUTION_AUTHORITY_LITERAL_SECRET",
                "$",
                "The authority document contains credential-shaped literal material.",
            ),
        )
    return document, ()


def _authorization_identity(document: Mapping[str, object]) -> str:
    payload = {
        key: value for key, value in document.items() if key != "authorization_identity"
    }
    return "apply-authorization:" + canonical_digest(payload)


def _compensation_authorization_identity(document: Mapping[str, object]) -> str:
    payload = {
        key: value
        for key, value in document.items()
        if key != "compensation_authorization_identity"
    }
    return "compensation-authorization:" + canonical_digest(payload)


def _checkpoint_set_identity(document: Mapping[str, object]) -> str:
    payload = {
        key: value
        for key, value in document.items()
        if key not in {"checkpoint_set_identity", "checkpoint_set_digest"}
    }
    return "checkpoint-set:" + canonical_digest(payload)


def _checkpoint_set_digest(document: Mapping[str, object]) -> str:
    return _artifact_digest(document, "checkpoint_set_digest")


def _checkpoint_entry(snapshot: object) -> dict[str, object] | None:
    if not isinstance(snapshot, Mapping) or set(snapshot) != {
        "durable_generation",
        "record_version",
        "record",
    }:
        return None
    generation = snapshot["durable_generation"]
    record_version = snapshot["record_version"]
    record = snapshot["record"]
    if (
        type(generation) is not int
        or generation < 1
        or record_version != "agent-equipment-checkpoint/v1"
        or not isinstance(record, Mapping)
    ):
        return None
    history = record.get("phase_history")
    phase = record.get("phase")
    intent = record.get("invocation_state")
    try:
        canonical_digest(record)
    except (TypeError, ValueError):
        return None
    if (
        set(record) != _CHECKPOINT_FIELDS
        or not isinstance(history, list)
        or any(type(item) is not str for item in history)
        or tuple(history) not in _CHECKPOINT_PHASE_HISTORIES
        or history[-1] != phase
        or type(intent) is not str
        or intent not in {"not_started", "started"}
        or (phase == "completed" and intent != "started")
        or type(record.get("ordinal")) is not int
        or record["ordinal"] < 0
    ):
        return None
    immutable_record = dict(record)
    for field in ("phase", "phase_history", "invocation_state"):
        immutable_record.pop(field)
    return {
        "checkpoint_identity": "checkpoint:"
        + canonical_digest(
            {
                "record_version": record_version,
                "immutable_record": immutable_record,
            }
        ),
        "durable_generation": generation,
        "record_version": record_version,
        "phase": record["phase"],
        "invocation_state": record["invocation_state"],
        "action_identity": record["action_identity"],
        "ordinal": record["ordinal"],
        "checkpoint_record_digest": canonical_digest(record),
    }


def _project_checkpoint_entries(snapshots: object) -> list[dict[str, object]] | None:
    if not isinstance(snapshots, Sequence) or isinstance(snapshots, (str, bytes)):
        return None
    entries: list[dict[str, object]] = []
    for snapshot in snapshots:
        entry = _checkpoint_entry(snapshot)
        if entry is None:
            return None
        entries.append(entry)
    return entries


def _checkpoint_record(snapshot: object) -> Mapping[str, object] | None:
    if not isinstance(snapshot, Mapping):
        return None
    record = snapshot.get("record")
    return record if isinstance(record, Mapping) else None


def _checkpoint_action(record: Mapping[str, object]) -> dict[str, object]:
    fields = (
        "action_identity",
        "ordinal",
        "step_id",
        "surface",
        "route_capability_binding",
        "route_digest",
        "operation_digest",
        "compensation_operation",
        "pre_state_digest",
        "expected_post_state_digest",
        "pre_state",
        "expected_post_state",
    )
    return {field: record.get(field) for field in fields}


def authorization_ledger_claim_identity(
    execution_domain_identity: str,
    execution_nonce: str,
) -> str:
    """Return the single claim identity inside one trusted ledger domain."""

    return "authorization-ledger-claim:" + canonical_digest(
        {
            "execution_domain_identity": execution_domain_identity,
            "execution_nonce": execution_nonce,
        }
    )


def compensation_ledger_claim_identity(
    execution_domain_identity: str,
    compensation_nonce: str,
) -> str:
    """Return the single compensation claim inside one trusted ledger domain."""

    return "compensation-ledger-claim:" + canonical_digest(
        {
            "execution_domain_identity": execution_domain_identity,
            "compensation_nonce": compensation_nonce,
        }
    )


def _archive_identity(payload: object) -> str:
    return "release-archive:" + canonical_digest(payload)


def _artifact_digest(document: Mapping[str, object], digest_member: str) -> str:
    return canonical_digest(
        {key: value for key, value in document.items() if key != digest_member}
    )


def _document_utc_instant(value: object) -> tuple[tuple[int, ...], str] | None:
    if not isinstance(value, str):
        return None
    match = _UTC_TIMESTAMP_PATTERN.fullmatch(value)
    if match is None:
        return None
    fraction = (match.group("fraction") or "").rstrip("0")
    return (
        (
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
            int(match.group("second")),
        ),
        fraction,
    )


def _trusted_utc_instant(value: datetime) -> tuple[tuple[int, ...], str]:
    normalized = value.astimezone(timezone.utc)
    return (
        (
            normalized.year,
            normalized.month,
            normalized.day,
            normalized.hour,
            normalized.minute,
            normalized.second,
        ),
        f"{normalized.microsecond:06d}".rstrip("0"),
    )


def _compare_utc_instants(
    left: tuple[tuple[int, ...], str],
    right: tuple[tuple[int, ...], str],
) -> int:
    if left[0] != right[0]:
        return -1 if left[0] < right[0] else 1
    width = max(len(left[1]), len(right[1]))
    left_fraction = left[1].ljust(width, "0")
    right_fraction = right[1].ljust(width, "0")
    if left_fraction == right_fraction:
        return 0
    return -1 if left_fraction < right_fraction else 1


def _time_window_is_valid(
    document: Mapping[str, object], trusted_now: datetime
) -> bool:
    issued_at = _document_utc_instant(document["issued_at"])
    not_before = _document_utc_instant(document["not_before"])
    expires_at = _document_utc_instant(document["expires_at"])
    if issued_at is None or not_before is None or expires_at is None:
        return False
    now = _trusted_utc_instant(trusted_now)
    return (
        _compare_utc_instants(issued_at, not_before) <= 0
        and _compare_utc_instants(not_before, now) <= 0
        and _compare_utc_instants(now, expires_at) < 0
    )


def validate_apply_authorization(
    document: object,
    *,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_apply_authorization_identity: str,
    expected_apply_authorization_digest: str,
    expected_execution_domain_identity: str,
    expected_execution_nonce: str,
    expected_run_identity: str,
    expected_operator_review_package_digest: str,
    expected_issuer_identity: str,
    trusted_now: datetime,
    expected_bindings: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    """Validate one externally issued apply authorization against trusted inputs."""

    if (
        not isinstance(document, Mapping)
        or document.get("schema_version") != "agent-equipment-apply-authorization/v1"
        or not _schema_valid(document)
    ):
        return (
            _diagnostic(
                "APPLY_AUTHORIZATION_SCHEMA_INVALID",
                "$",
                "The apply authorization does not satisfy the checked-in closed schema.",
            ),
        )
    if contains_literal_credential(document):
        return (
            _diagnostic(
                "APPLY_AUTHORIZATION_LITERAL_SECRET",
                "$",
                "The apply authorization contains credential-shaped literal material.",
            ),
        )
    if (
        not isinstance(trusted_now, datetime)
        or trusted_now.tzinfo is None
        or trusted_now.utcoffset() is None
    ):
        return (
            _diagnostic(
                "TRUSTED_CLOCK_INVALID",
                "$.trusted_clock",
                "The executor must supply a timezone-aware trusted clock.",
            ),
        )

    diagnostics: list[Diagnostic] = []
    bindings = document["bindings"]
    assert isinstance(bindings, Mapping)
    if document["authorization_identity"] != _authorization_identity(document):
        diagnostics.append(
            _diagnostic(
                "APPLY_AUTHORIZATION_IDENTITY_INVALID",
                "$.authorization_identity",
                "The apply-authorization identity does not match its canonical payload.",
            )
        )
    if document["authorization_identity"] != expected_apply_authorization_identity:
        diagnostics.append(
            _diagnostic(
                "APPLY_AUTHORIZATION_TRUST_MISMATCH",
                "$.authorization_identity",
                "The apply authorization does not match the independently trusted identity.",
            )
        )
    if canonical_digest(document) != expected_apply_authorization_digest:
        diagnostics.append(
            _diagnostic(
                "APPLY_AUTHORIZATION_DIGEST_MISMATCH",
                "$",
                "The apply authorization does not match the independently trusted digest.",
            )
        )
    if document["issuer_identity"] != expected_issuer_identity:
        diagnostics.append(
            _diagnostic(
                "APPLY_AUTHORIZATION_BINDING_MISMATCH",
                "$.issuer_identity",
                "The apply authorization does not match the trusted issuer.",
            )
        )
    if document["execution_domain_identity"] != expected_execution_domain_identity:
        diagnostics.append(
            _diagnostic(
                "EXECUTION_DOMAIN_MISMATCH",
                "$.execution_domain_identity",
                "The apply authorization does not match the independently trusted ledger domain.",
            )
        )
    if bindings != expected_bindings:
        diagnostics.append(
            _diagnostic(
                "APPLY_AUTHORIZATION_BINDING_MISMATCH",
                "$.bindings",
                "The apply authorization does not match the complete independently trusted binding tuple.",
            )
        )
    expected_fields = {
        "candidate_identity": expected_candidate_identity,
        "implementation_manifest_digest": expected_implementation_manifest_digest,
        "operator_review_package_digest": expected_operator_review_package_digest,
    }
    for field, expected in expected_fields.items():
        if bindings[field] != expected:
            diagnostics.append(
                _diagnostic(
                    (
                        "OPERATOR_REVIEW_PACKAGE_BINDING_MISMATCH"
                        if field == "operator_review_package_digest"
                        else "APPLY_AUTHORIZATION_BINDING_MISMATCH"
                    ),
                    f"$.bindings.{field}",
                    "The apply authorization does not match the independently trusted execution material.",
                )
            )
    if (
        document["execution_nonce"] != expected_execution_nonce
        or document["run_identity"] != expected_run_identity
    ):
        diagnostics.append(
            _diagnostic(
                "EXECUTION_BINDING_MISMATCH",
                "$",
                "The apply authorization does not match the trusted nonce and run.",
            )
        )
    if not _time_window_is_valid(document, trusted_now):
        diagnostics.append(
            _diagnostic(
                "APPLY_AUTHORIZATION_TIME_INVALID",
                "$",
                "The trusted clock is outside the authorization's ordered validity window.",
            )
        )
    return tuple(sorted(diagnostics))


def validate_checkpoint_set_manifest(
    document: object,
    *,
    expected_apply_authorization_identity: str,
    expected_apply_authorization_digest: str,
    expected_execution_domain_identity: str,
    expected_execution_nonce: str,
    expected_run_identity: str,
    expected_plan_action_set_digest: str,
    trusted_checkpoint_store_generation: int,
    trusted_checkpoint_records: Sequence[Mapping[str, object]],
    pretransition_checkpoint_store_generation: int,
    pretransition_checkpoint_records: Sequence[Mapping[str, object]],
    expected_checkpoint_bindings: Mapping[str, object],
    trusted_plan_actions: Sequence[Mapping[str, object]],
) -> tuple[Diagnostic, ...]:
    """Validate a closed checkpoint snapshot and its race-free store recheck."""

    if (
        not isinstance(document, Mapping)
        or document.get("schema_version") != "agent-equipment-checkpoint-set/v1"
        or not _schema_valid(document)
    ):
        return (
            _diagnostic(
                "CHECKPOINT_SET_SCHEMA_INVALID",
                "$",
                "The checkpoint-set manifest does not satisfy the checked-in closed schema.",
            ),
        )
    if contains_literal_credential(document):
        return (
            _diagnostic(
                "CHECKPOINT_SET_LITERAL_SECRET",
                "$",
                "The checkpoint-set manifest contains credential-shaped literal material.",
            ),
        )

    diagnostics: list[Diagnostic] = []
    if document["checkpoint_set_identity"] != _checkpoint_set_identity(document):
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_SET_IDENTITY_INVALID",
                "$.checkpoint_set_identity",
                "The checkpoint-set identity does not match its canonical payload.",
            )
        )
    if document["checkpoint_set_digest"] != _checkpoint_set_digest(document):
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_SET_DIGEST_INVALID",
                "$.checkpoint_set_digest",
                "The checkpoint-set digest does not match the complete manifest.",
            )
        )

    expected_bindings = {
        "apply_authorization_identity": expected_apply_authorization_identity,
        "apply_authorization_digest": expected_apply_authorization_digest,
        "execution_domain_identity": expected_execution_domain_identity,
        "execution_nonce": expected_execution_nonce,
        "run_identity": expected_run_identity,
        "plan_action_set_digest": expected_plan_action_set_digest,
    }
    if document["bindings"] != expected_bindings:
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_SET_BINDING_MISMATCH",
                "$.bindings",
                "The checkpoint set does not bind the exact independently trusted apply run.",
            )
        )

    trusted_snapshots: Sequence[Mapping[str, object]] = (
        trusted_checkpoint_records
        if isinstance(trusted_checkpoint_records, Sequence)
        and not isinstance(trusted_checkpoint_records, (str, bytes))
        else ()
    )
    projected = _project_checkpoint_entries(trusted_snapshots)
    manifest_entries = document["checkpoints"]
    assert isinstance(manifest_entries, list)
    if (
        projected is None
        or not projected
        or manifest_entries != projected
        or projected
        != sorted(
            projected,
            key=lambda entry: (entry["ordinal"], entry["checkpoint_identity"]),
        )
        or len({entry["checkpoint_identity"] for entry in projected}) != len(projected)
        or len({entry["ordinal"] for entry in projected}) != len(projected)
    ):
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_SET_MEMBERSHIP_MISMATCH",
                "$.checkpoints",
                "The manifest is not the ordered all-and-only projection of the trusted checkpoint store.",
            )
        )

    if (
        type(trusted_checkpoint_store_generation) is not int
        or document["checkpoint_store_generation"]
        != trusted_checkpoint_store_generation
    ):
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_STORE_GENERATION_MISMATCH",
                "$.checkpoint_store_generation",
                "The checkpoint manifest was not derived from the trusted store generation.",
            )
        )

    if (
        type(pretransition_checkpoint_store_generation) is not int
        or pretransition_checkpoint_store_generation
        != trusted_checkpoint_store_generation
        or _project_checkpoint_entries(pretransition_checkpoint_records) != projected
    ):
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_STORE_CONCURRENT_CHANGE",
                "$.checkpoints",
                "The checkpoint store changed after authorization validation and before transition.",
            )
        )

    trusted_actions = (
        list(trusted_plan_actions)
        if isinstance(trusted_plan_actions, Sequence)
        and not isinstance(trusted_plan_actions, (str, bytes))
        else []
    )
    records = [_checkpoint_record(snapshot) for snapshot in trusted_snapshots]
    if (
        any(record is None for record in records)
        or [_checkpoint_action(record) for record in records if record is not None]
        != trusted_actions
    ):
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_PLAN_ACTION_MISMATCH",
                "$.checkpoints",
                "A checkpoint does not match one independently validated plan action and ordinal.",
            )
        )

    if (
        not isinstance(expected_checkpoint_bindings, Mapping)
        or set(expected_checkpoint_bindings) != _CHECKPOINT_TRUSTED_BINDING_FIELDS
    ) or any(
        record.get("run_identity") != expected_run_identity
        or record.get("execution_domain_identity") != expected_execution_domain_identity
        or any(
            record.get(field) != expected_checkpoint_bindings[field]
            for field in _CHECKPOINT_TRUSTED_BINDING_FIELDS
        )
        for record in records
        if record is not None
    ):
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_BINDING_MISMATCH",
                "$.checkpoints",
                "A checkpoint does not bind the complete independently trusted run material.",
            )
        )
    return tuple(sorted(diagnostics))


def validate_compensation_authorization(
    document: object,
    *,
    expected_compensation_authorization_identity: str,
    expected_compensation_authorization_digest: str,
    expected_apply_authorization_identity: str,
    expected_apply_authorization_digest: str,
    expected_execution_domain_identity: str,
    expected_execution_nonce: str,
    expected_run_identity: str,
    checkpoint_set_manifest: object,
    trusted_checkpoint_store_generation: int,
    trusted_checkpoint_records: Sequence[Mapping[str, object]],
    pretransition_checkpoint_store_generation: int,
    pretransition_checkpoint_records: Sequence[Mapping[str, object]],
    expected_checkpoint_bindings: Mapping[str, object],
    trusted_plan_actions: Sequence[Mapping[str, object]],
    expected_plan_action_set_digest: str,
    expected_compensation_nonce: str,
    expected_issuer_identity: str,
    trusted_now: datetime,
) -> tuple[Diagnostic, ...]:
    """Validate authority for a fresh public compensation invocation."""

    if (
        not isinstance(document, Mapping)
        or document.get("schema_version")
        != "agent-equipment-compensation-authorization/v1"
        or not _schema_valid(document)
    ):
        return (
            _diagnostic(
                "COMPENSATION_AUTHORIZATION_SCHEMA_INVALID",
                "$",
                "The compensation authorization does not satisfy the checked-in closed schema.",
            ),
        )
    if contains_literal_credential(document):
        return (
            _diagnostic(
                "COMPENSATION_AUTHORIZATION_LITERAL_SECRET",
                "$",
                "The compensation authorization contains credential-shaped literal material.",
            ),
        )
    if (
        not isinstance(trusted_now, datetime)
        or trusted_now.tzinfo is None
        or trusted_now.utcoffset() is None
    ):
        return (
            _diagnostic(
                "TRUSTED_CLOCK_INVALID",
                "$.trusted_clock",
                "The compensation executor must supply a timezone-aware trusted clock.",
            ),
        )

    checkpoint_diagnostics = validate_checkpoint_set_manifest(
        checkpoint_set_manifest,
        expected_apply_authorization_identity=expected_apply_authorization_identity,
        expected_apply_authorization_digest=expected_apply_authorization_digest,
        expected_execution_domain_identity=expected_execution_domain_identity,
        expected_execution_nonce=expected_execution_nonce,
        expected_run_identity=expected_run_identity,
        expected_plan_action_set_digest=expected_plan_action_set_digest,
        trusted_checkpoint_store_generation=trusted_checkpoint_store_generation,
        trusted_checkpoint_records=trusted_checkpoint_records,
        pretransition_checkpoint_store_generation=pretransition_checkpoint_store_generation,
        pretransition_checkpoint_records=pretransition_checkpoint_records,
        expected_checkpoint_bindings=expected_checkpoint_bindings,
        trusted_plan_actions=trusted_plan_actions,
    )
    diagnostics: list[Diagnostic] = list(checkpoint_diagnostics)
    if document["compensation_authorization_identity"] != (
        _compensation_authorization_identity(document)
    ):
        diagnostics.append(
            _diagnostic(
                "COMPENSATION_AUTHORIZATION_IDENTITY_INVALID",
                "$.compensation_authorization_identity",
                "The compensation-authorization identity does not match its canonical payload.",
            )
        )
    if document["compensation_authorization_identity"] != (
        expected_compensation_authorization_identity
    ):
        diagnostics.append(
            _diagnostic(
                "COMPENSATION_AUTHORIZATION_TRUST_MISMATCH",
                "$.compensation_authorization_identity",
                "The compensation authorization does not match the independently trusted identity.",
            )
        )
    if canonical_digest(document) != expected_compensation_authorization_digest:
        diagnostics.append(
            _diagnostic(
                "COMPENSATION_AUTHORIZATION_DIGEST_MISMATCH",
                "$",
                "The compensation authorization does not match the independently trusted digest.",
            )
        )

    trusted_checkpoint_set_digest = (
        checkpoint_set_manifest.get("checkpoint_set_digest")
        if not checkpoint_diagnostics and isinstance(checkpoint_set_manifest, Mapping)
        else None
    )
    expected_bindings = {
        "apply_authorization_identity": expected_apply_authorization_identity,
        "apply_authorization_digest": expected_apply_authorization_digest,
        "execution_domain_identity": expected_execution_domain_identity,
        "execution_nonce": expected_execution_nonce,
        "run_identity": expected_run_identity,
        "checkpoint_set_digest": trusted_checkpoint_set_digest,
        "plan_action_set_digest": expected_plan_action_set_digest,
    }
    if (
        document["bindings"] != expected_bindings
        or document["compensation_nonce"] != expected_compensation_nonce
        or document["issuer_identity"] != expected_issuer_identity
    ):
        diagnostics.append(
            _diagnostic(
                "COMPENSATION_AUTHORIZATION_BINDING_MISMATCH",
                "$.bindings",
                "The compensation authorization does not match the exact trusted original run, checkpoint set, action set, issuer, and fresh nonce.",
            )
        )
    if not _time_window_is_valid(document, trusted_now):
        diagnostics.append(
            _diagnostic(
                "COMPENSATION_AUTHORIZATION_TIME_INVALID",
                "$",
                "The trusted clock is outside the compensation authorization's ordered validity window.",
            )
        )
    return tuple(sorted(diagnostics))


def validate_release_archive_manifest(
    document: object,
    *,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_execution_binding: Mapping[str, object],
    expected_checkpoint_set_digest: str,
    expected_run_terminal_state: str,
    expected_launcher_identity: str,
    expected_launcher_manifest_digest: str,
    expected_store_identity: str,
    expected_store_key: str,
    expected_archived_document_byte_digests: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    """Validate one closed archive manifest without touching the archive store."""

    if (
        not isinstance(document, Mapping)
        or document.get("schema_version")
        != "agent-equipment-release-archive-manifest/v1"
        or not _schema_valid(document)
    ):
        return (
            _diagnostic(
                "RELEASE_ARCHIVE_SCHEMA_INVALID",
                "$",
                "The release archive manifest does not satisfy the checked-in closed schema.",
            ),
        )
    if contains_literal_credential(document):
        return (
            _diagnostic(
                "RELEASE_ARCHIVE_LITERAL_SECRET",
                "$",
                "The release archive manifest contains credential-shaped literal material.",
            ),
        )

    diagnostics: list[Diagnostic] = []
    payload = document["payload"]
    assert isinstance(payload, Mapping)
    destination = payload["archive_destination"]
    assert isinstance(destination, Mapping)
    if document["archive_identity"] != _archive_identity(payload):
        diagnostics.append(
            _diagnostic(
                "RELEASE_ARCHIVE_IDENTITY_INVALID",
                "$.archive_identity",
                "The archive identity does not match its canonical payload.",
            )
        )
    if document["archive_manifest_digest"] != _artifact_digest(
        document, "archive_manifest_digest"
    ):
        diagnostics.append(
            _diagnostic(
                "RELEASE_ARCHIVE_DIGEST_INVALID",
                "$.archive_manifest_digest",
                "The archive manifest digest does not match the complete manifest.",
            )
        )
    expected_fields = {
        "candidate_identity": expected_candidate_identity,
        "implementation_manifest_digest": expected_implementation_manifest_digest,
        "checkpoint_set_digest": expected_checkpoint_set_digest,
        "run_terminal_state": expected_run_terminal_state,
        "launcher_identity": expected_launcher_identity,
        "launcher_manifest_digest": expected_launcher_manifest_digest,
    }
    if any(payload[field] != expected for field, expected in expected_fields.items()):
        diagnostics.append(
            _diagnostic(
                "RELEASE_ARCHIVE_AUTHORITY_MISMATCH",
                "$.payload",
                "The archive manifest does not match the trusted candidate and launcher authority.",
            )
        )
    if payload["execution_binding"] != expected_execution_binding:
        diagnostics.append(
            _diagnostic(
                "EXECUTION_BINDING_MISMATCH",
                "$.payload.execution_binding",
                "The archive manifest does not bind the exact trusted execution tuple.",
            )
        )
    if (
        destination["store_identity"] != expected_store_identity
        or destination["store_key"] != expected_store_key
    ):
        diagnostics.append(
            _diagnostic(
                "RELEASE_ARCHIVE_DESTINATION_MISMATCH",
                "$.payload.archive_destination",
                "The archive manifest does not name the trusted store and key.",
            )
        )
    archived_digests = payload["archived_document_byte_digests"]
    assert isinstance(archived_digests, Mapping)
    if archived_digests != expected_archived_document_byte_digests:
        diagnostics.append(
            _diagnostic(
                "ARCHIVED_DOCUMENT_BYTES_MISMATCH",
                "$.payload.archived_document_byte_digests",
                "The archive manifest does not bind the exact independently supplied document bytes.",
            )
        )
    return tuple(sorted(diagnostics))


def validate_release_receipt(
    document: object,
    *,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_execution_binding: Mapping[str, object],
    expected_checkpoint_set_digest: str,
    expected_run_terminal_state: str,
    expected_launcher_identity: str,
    expected_launcher_manifest_digest: str,
    expected_archive_identity: str,
    expected_archive_manifest_digest: str,
    expected_store_identity: str,
    expected_store_key: str,
) -> tuple[Diagnostic, ...]:
    """Validate a terminal receipt against one already committed archive manifest."""

    if (
        not isinstance(document, Mapping)
        or document.get("schema_version") != "agent-equipment-release-receipt/v1"
        or not _schema_valid(document)
    ):
        return (
            _diagnostic(
                "RELEASE_RECEIPT_SCHEMA_INVALID",
                "$",
                "The release receipt does not satisfy the checked-in closed schema.",
            ),
        )
    if contains_literal_credential(document):
        return (
            _diagnostic(
                "RELEASE_RECEIPT_LITERAL_SECRET",
                "$",
                "The release receipt contains credential-shaped literal material.",
            ),
        )

    diagnostics: list[Diagnostic] = []
    payload = document["payload"]
    assert isinstance(payload, Mapping)
    destination = payload["archive_destination"]
    assert isinstance(destination, Mapping)
    if document["receipt_identity"] != "release-receipt:" + canonical_digest(payload):
        diagnostics.append(
            _diagnostic(
                "RELEASE_RECEIPT_IDENTITY_INVALID",
                "$.receipt_identity",
                "The release receipt identity does not match its canonical payload.",
            )
        )
    expected_fields = {
        "candidate_identity": expected_candidate_identity,
        "implementation_manifest_digest": expected_implementation_manifest_digest,
        "checkpoint_set_digest": expected_checkpoint_set_digest,
        "run_terminal_state": expected_run_terminal_state,
        "launcher_identity": expected_launcher_identity,
        "launcher_manifest_digest": expected_launcher_manifest_digest,
        "archive_identity": expected_archive_identity,
        "archive_manifest_digest": expected_archive_manifest_digest,
    }
    if any(payload[field] != expected for field, expected in expected_fields.items()):
        diagnostics.append(
            _diagnostic(
                "RELEASE_RECEIPT_AUTHORITY_MISMATCH",
                "$.payload",
                "The release receipt does not match the trusted candidate, launcher, and archive.",
            )
        )
    if payload["execution_binding"] != expected_execution_binding:
        diagnostics.append(
            _diagnostic(
                "EXECUTION_BINDING_MISMATCH",
                "$.payload.execution_binding",
                "The release receipt does not bind the exact trusted execution tuple.",
            )
        )
    if (
        destination["store_identity"] != expected_store_identity
        or destination["store_key"] != expected_store_key
    ):
        diagnostics.append(
            _diagnostic(
                "RELEASE_RECEIPT_DESTINATION_MISMATCH",
                "$.payload.archive_destination",
                "The release receipt does not name the trusted archive store and key.",
            )
        )
    return tuple(sorted(diagnostics))


__all__ = (
    "MAX_EXECUTION_AUTHORITY_BYTES",
    "Diagnostic",
    "authorization_ledger_claim_identity",
    "canonical_digest",
    "compensation_ledger_claim_identity",
    "parse_execution_authority_bytes",
    "validate_apply_authorization",
    "validate_checkpoint_set_manifest",
    "validate_compensation_authorization",
    "validate_release_archive_manifest",
    "validate_release_receipt",
)
