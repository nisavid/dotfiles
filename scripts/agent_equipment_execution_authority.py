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
try:
    from agent_equipment_acceptance_evidence import (
        validate_acceptance_evidence as _validate_acceptance_evidence,
    )
except ModuleNotFoundError:  # Loaded as a repo module rather than an executable.
    from scripts.agent_equipment_acceptance_evidence import (
        validate_acceptance_evidence as _validate_acceptance_evidence,
    )
try:
    from agent_equipment_captured_state import (
        plan_action_digest as _plan_action_digest,
    )
    from agent_equipment_captured_state import (
        plan_action_identity as _plan_action_identity,
    )
    from agent_equipment_captured_state import (
        plan_action_set_digest as _plan_action_set_digest,
    )
    from agent_equipment_captured_state import (
        validate_captured_state as _validate_captured_state,
    )
except ModuleNotFoundError:  # Loaded as a repo module rather than an executable.
    from scripts.agent_equipment_captured_state import (
        plan_action_digest as _plan_action_digest,
    )
    from scripts.agent_equipment_captured_state import (
        plan_action_identity as _plan_action_identity,
    )
    from scripts.agent_equipment_captured_state import (
        plan_action_set_digest as _plan_action_set_digest,
    )
    from scripts.agent_equipment_captured_state import (
        validate_captured_state as _validate_captured_state,
    )


SCHEMA_DIRECTORY = Path(__file__).resolve().parent.parent / "docs/agent-equipment"
SCHEMA_NAME = "execution-authority-v1.schema.json"
PLAN_ACTION_SET_SCHEMA_NAME = "plan-action-set-v1.schema.json"
CAPTURED_STATE_SCHEMA_NAME = "captured-state-v1.schema.json"
MAX_EXECUTION_AUTHORITY_BYTES = 262_144
MAX_PLAN_ACTION_SET_BYTES = 16 * 1024 * 1024
MAX_CAPTURED_STATE_BYTES = 16 * 1024 * 1024
MAX_CHECKPOINT_STORE_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_RELEASE_ACCEPTANCE_BYTES = 16 * 1024 * 1024
_UTC_TIMESTAMP_PATTERN = re.compile(
    r"^(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"[Tt](?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
    r"(?:[.,](?P<fraction>[0-9]{1,9}))?Z$"
)
_CHECKPOINT_BINDING_FIELDS = frozenset(
    {
        "checkpoint_identity",
        "apply_authorization_identity",
        "apply_authorization_digest",
        "execution_nonce",
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
        "prepared_action_authority_set_identity",
        "prepared_action_authority_set_digest",
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
    "compensation_authority_kind",
    "compensation_transition_claim",
}
_CAPTURE_OBSERVATION_FIELDS = frozenset(
    {
        "action_identity",
        "ordinal",
        "captured_state_identity",
        "captured_state_digest",
        "surface",
        "controlled_equipment_identities",
        "normalized_pre_state",
        "normalized_pre_state_digest",
    }
)
_CHECKPOINT_PHASE_MATRIX = frozenset(
    {
        (("prepared",), "prepared", "not_started"),
        (("prepared",), "prepared", "started"),
        (("prepared", "completed"), "completed", "started"),
        (("prepared", "compensating"), "compensating", "not_started"),
        (("prepared", "compensating"), "compensating", "started"),
        (("prepared", "completed", "compensating"), "compensating", "started"),
        (("prepared", "compensating", "compensated"), "compensated", "not_started"),
        (("prepared", "compensating", "compensated"), "compensated", "started"),
        (
            ("prepared", "completed", "compensating", "compensated"),
            "compensated",
            "started",
        ),
        (("prepared", "compensation_blocked"), "compensation_blocked", "not_started"),
        (("prepared", "compensation_blocked"), "compensation_blocked", "started"),
        (
            ("prepared", "completed", "compensation_blocked"),
            "compensation_blocked",
            "started",
        ),
        (
            ("prepared", "compensating", "compensation_blocked"),
            "compensation_blocked",
            "not_started",
        ),
        (
            ("prepared", "compensating", "compensation_blocked"),
            "compensation_blocked",
            "started",
        ),
        (
            ("prepared", "completed", "compensating", "compensation_blocked"),
            "compensation_blocked",
            "started",
        ),
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


def _schema_valid(
    document: object,
    schema_name: str = SCHEMA_NAME,
    *,
    maximum_bytes: int | None = None,
) -> bool:
    if maximum_bytes is None:
        if schema_name != SCHEMA_NAME:
            return False
        maximum_bytes = MAX_EXECUTION_AUTHORITY_BYTES
    try:
        if len(_canonical_bytes(document)) > maximum_bytes:
            return False
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
        return False
    return _validate_schema(
        document,
        schema_directory=SCHEMA_DIRECTORY,
        root_schema_name=schema_name,
        allowed_schema_names=frozenset({schema_name}),
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


def _parse_bounded_json_bytes(
    raw_bytes: object,
    *,
    maximum_bytes: int,
) -> object | None:
    if type(raw_bytes) is not bytes or len(raw_bytes) > maximum_bytes:
        return None
    try:
        text = raw_bytes.decode("utf-8", errors="strict")
        document = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_float=_finite_number,
            parse_constant=_reject_constant,
        )
        if len(_canonical_bytes(document)) > maximum_bytes:
            return None
        return document
    except (
        RecursionError,
        UnicodeDecodeError,
        UnicodeEncodeError,
        json.JSONDecodeError,
        _AmbiguousJson,
        ValueError,
    ):
        return None


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
    document = _parse_bounded_json_bytes(
        raw_bytes,
        maximum_bytes=MAX_EXECUTION_AUTHORITY_BYTES,
    )
    if document is None:
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


def _checkpoint_store_snapshot_identity(document: Mapping[str, object]) -> str:
    payload = {
        key: value
        for key, value in document.items()
        if key not in {"snapshot_identity", "snapshot_digest"}
    }
    return "checkpoint-store-snapshot:" + canonical_digest(payload)


def _checkpoint_store_snapshot_digest(document: Mapping[str, object]) -> str:
    return _artifact_digest(document, "snapshot_digest")


def checkpoint_identity(
    record_version: str,
    record: Mapping[str, object],
) -> str:
    immutable_record = {
        key: value
        for key, value in record.items()
        if key
        not in {
            "checkpoint_identity",
            "phase",
            "phase_history",
            "invocation_state",
            "compensation_authority_kind",
            "compensation_transition_claim",
        }
    }
    return "checkpoint:" + canonical_digest(
        {
            "record_version": record_version,
            "immutable_record": immutable_record,
        }
    )


def _compensation_transition_claim_identity(
    claim: Mapping[str, object],
) -> str:
    payload = {
        key: value
        for key, value in claim.items()
        if key not in {"transition_claim_identity", "transition_claim_digest"}
    }
    return "compensation-transition:" + canonical_digest(payload)


def _compensation_transition_claim_digest(
    claim: Mapping[str, object],
) -> str:
    return _artifact_digest(claim, "transition_claim_digest")


def _compensation_transition_claim_valid(
    claim: object,
    checkpoint_identity: object,
) -> bool:
    if claim is None:
        return True
    if not isinstance(claim, Mapping) or set(claim) != {
        "schema_version",
        "checkpoint_identity",
        "compensation_authorization_identity",
        "compensation_authorization_digest",
        "compensation_nonce",
        "transition_claim_identity",
        "transition_claim_digest",
    }:
        return False
    patterns = {
        "checkpoint_identity": r"^checkpoint:sha256:[0-9a-f]{64}$",
        "compensation_authorization_identity": (
            r"^compensation-authorization:sha256:[0-9a-f]{64}$"
        ),
        "compensation_authorization_digest": r"^sha256:[0-9a-f]{64}$",
        "compensation_nonce": r"^compensation-nonce:sha256:[0-9a-f]{64}$",
        "transition_claim_identity": (r"^compensation-transition:sha256:[0-9a-f]{64}$"),
        "transition_claim_digest": r"^sha256:[0-9a-f]{64}$",
    }
    return (
        claim.get("schema_version")
        == "agent-equipment-compensation-transition-claim/v1"
        and all(
            isinstance(claim.get(field), str)
            and re.fullmatch(pattern, claim[field]) is not None
            for field, pattern in patterns.items()
        )
        and claim.get("checkpoint_identity") == checkpoint_identity
        and claim.get("transition_claim_identity")
        == _compensation_transition_claim_identity(claim)
        and claim.get("transition_claim_digest")
        == _compensation_transition_claim_digest(claim)
    )


def _validated_plan_action_index(
    document: object,
    *,
    expected_action_set_digest: str,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_plan_digest: str,
) -> tuple[dict[tuple[str, int], Mapping[str, object]], tuple[Diagnostic, ...]]:
    if (
        not isinstance(document, Mapping)
        or document.get("schema_version") != "agent-equipment-plan-action-set/v1"
        or not _schema_valid(
            document,
            PLAN_ACTION_SET_SCHEMA_NAME,
            maximum_bytes=MAX_PLAN_ACTION_SET_BYTES,
        )
    ):
        return {}, (
            _diagnostic(
                "PLAN_ACTION_SET_SCHEMA_INVALID",
                "$.authoritative_plan_action_set",
                "The authoritative plan-action set does not satisfy the checked-in closed schema.",
            ),
        )
    if contains_literal_credential(document):
        return {}, (
            _diagnostic(
                "PLAN_ACTION_SET_LITERAL_SECRET",
                "$.authoritative_plan_action_set",
                "The authoritative plan-action set contains credential-shaped literal material.",
            ),
        )

    diagnostics: list[Diagnostic] = []
    actions = document["actions"]
    assert isinstance(actions, list)
    if actions:
        first_payload = actions[0]["action_payload"]
        assert isinstance(first_payload, Mapping)

        expected_action_authority = {
            "candidate_identity": expected_candidate_identity,
            "implementation_manifest_digest": expected_implementation_manifest_digest,
            "catalog_digest": first_payload.get("catalog_digest"),
            "lock_digest": first_payload.get("lock_digest"),
            "plan_digest": expected_plan_digest,
        }

        def action_authority_binding_valid(payload: object) -> bool:
            if not isinstance(payload, Mapping):
                return False
            preconditions = payload.get("preconditions")
            expected_preconditions = {
                "candidate_identity": expected_candidate_identity,
                "implementation_manifest_digest": (
                    expected_implementation_manifest_digest
                ),
                "catalog_digest": first_payload.get("catalog_digest"),
                "lock_digest": first_payload.get("lock_digest"),
                "plan_digest": expected_plan_digest,
                "route_digest": payload.get("route_digest"),
                "capability_digest": payload.get("capability_digest"),
                "manager_version_evidence_digest": payload.get(
                    "manager_version_evidence_digest"
                ),
                "adapter_identity": payload.get("adapter_identity"),
                "adapter_version": payload.get("adapter_version"),
                "control_owner": "reconciler_owned",
                "activation_group": payload.get("activation_group"),
                "surface_scope": payload.get("surface_scope"),
                "prepared_checkpoint_required": True,
                "compare_before_mutate": True,
            }
            return (
                all(
                    payload.get(field) == expected
                    for field, expected in expected_action_authority.items()
                )
                and preconditions == expected_preconditions
            )

        if any(
            not isinstance(evidence, Mapping)
            or not action_authority_binding_valid(evidence.get("action_payload"))
            for evidence in actions
        ):
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_SET_BINDING_MISMATCH",
                    "$.authoritative_plan_action_set.actions",
                    "Every plan action must bind the independently trusted plan authority and its exact precondition projection.",
                )
            )
    try:
        computed_set_digest = _plan_action_set_digest(
            str(document["candidate_identity"]),
            str(document["implementation_manifest_digest"]),
            str(document["plan_digest"]),
            actions,
        )
    except (TypeError, ValueError):
        computed_set_digest = None
    if (
        computed_set_digest is None
        or document["action_set_digest"] != computed_set_digest
        or computed_set_digest != expected_action_set_digest
    ):
        diagnostics.append(
            _diagnostic(
                "PLAN_ACTION_SET_DIGEST_MISMATCH",
                "$.authoritative_plan_action_set.action_set_digest",
                "The complete plan-action-set artifact does not match the independently trusted digest.",
            )
        )
    if (
        document["candidate_identity"] != expected_candidate_identity
        or document["implementation_manifest_digest"]
        != expected_implementation_manifest_digest
        or document["plan_digest"] != expected_plan_digest
    ):
        diagnostics.append(
            _diagnostic(
                "PLAN_ACTION_SET_BINDING_MISMATCH",
                "$.authoritative_plan_action_set",
                "The plan-action set does not match the independently trusted candidate and plan bindings.",
            )
        )

    index: dict[tuple[str, int], Mapping[str, object]] = {}
    ordered_keys: list[tuple[int, str]] = []
    for action_index, evidence in enumerate(actions):
        assert isinstance(evidence, Mapping)
        payload = evidence["action_payload"]
        assert isinstance(payload, Mapping)
        try:
            valid = evidence["action_digest"] == _plan_action_digest(
                payload
            ) and payload["action_identity"] == _plan_action_identity(payload)
        except (TypeError, ValueError):
            valid = False
        identity = payload.get("action_identity")
        ordinal = payload.get("ordinal")
        if not valid or not isinstance(identity, str) or type(ordinal) is not int:
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_INVALID",
                    f"$.authoritative_plan_action_set.actions[{action_index}]",
                    "A plan action does not match its canonical identity and digest.",
                )
            )
            continue
        key = (identity, ordinal)
        if key in index:
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_SET_MEMBERSHIP_INVALID",
                    "$.authoritative_plan_action_set.actions",
                    "The complete plan-action set contains duplicate action coordinates.",
                )
            )
        index[key] = payload
        ordered_keys.append((ordinal, identity))
    ordinals = [ordinal for ordinal, _ in ordered_keys]
    if (
        ordered_keys != sorted(ordered_keys)
        or ordinals != list(range(len(actions)))
        or len(index) != len(actions)
    ):
        diagnostics.append(
            _diagnostic(
                "PLAN_ACTION_SET_MEMBERSHIP_INVALID",
                "$.authoritative_plan_action_set.actions",
                "The complete plan-action set is not uniquely and contiguously ordered from ordinal zero.",
            )
        )
    return index, tuple(sorted(set(diagnostics)))


def validate_plan_action_set(
    document: object,
    *,
    expected_action_set_digest: str,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_plan_digest: str,
) -> tuple[Diagnostic, ...]:
    """Validate one complete authoritative plan-action-set artifact."""

    _, diagnostics = _validated_plan_action_index(
        document,
        expected_action_set_digest=expected_action_set_digest,
        expected_candidate_identity=expected_candidate_identity,
        expected_implementation_manifest_digest=(
            expected_implementation_manifest_digest
        ),
        expected_plan_digest=expected_plan_digest,
    )
    return diagnostics


def _capture_observation_authority_set_identity(
    document: Mapping[str, object],
) -> str:
    payload = {
        key: value
        for key, value in document.items()
        if key not in {"authority_set_identity", "authority_set_digest"}
    }
    return "capture-observation-authority-set:" + canonical_digest(payload)


def _capture_observation_authority_set_digest(
    document: Mapping[str, object],
) -> str:
    return _artifact_digest(document, "authority_set_digest")


def _validated_capture_observation_authority_index(
    document: object,
    *,
    expected_authority_set_identity: str,
    expected_authority_set_digest: str,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_plan_digest: str,
    expected_plan_action_set_digest: str,
    expected_capability_set_digest: str,
    expected_captured_state_identity: str,
    expected_captured_state_digest: str,
    plan_action_index: Mapping[tuple[str, int], Mapping[str, object]],
) -> tuple[
    dict[tuple[str, int], Mapping[str, object]],
    tuple[Diagnostic, ...],
]:
    """Validate the closed, apply-bound normalized capture authority set."""

    if (
        not isinstance(document, Mapping)
        or document.get("schema_version")
        != "agent-equipment-capture-observation-authority-set/v1"
        or not _schema_valid(document)
    ):
        return {}, (
            _diagnostic(
                "CAPTURE_OBSERVATION_AUTHORITY_SCHEMA_INVALID",
                "$.capture_observation_authority_set",
                "The capture-observation authority set does not satisfy the checked-in closed schema.",
            ),
        )
    if contains_literal_credential(document):
        return {}, (
            _diagnostic(
                "CAPTURE_OBSERVATION_AUTHORITY_LITERAL_SECRET",
                "$.capture_observation_authority_set",
                "The capture-observation authority set contains credential-shaped literal material.",
            ),
        )

    diagnostics: list[Diagnostic] = []
    bindings = document["bindings"]
    observations = document["observations"]
    assert isinstance(bindings, Mapping)
    assert isinstance(observations, list)
    if document[
        "authority_set_identity"
    ] != _capture_observation_authority_set_identity(document) or document[
        "authority_set_digest"
    ] != _capture_observation_authority_set_digest(document):
        diagnostics.append(
            _diagnostic(
                "CAPTURE_OBSERVATION_AUTHORITY_SEAL_INVALID",
                "$.capture_observation_authority_set",
                "The capture-observation authority identity or digest does not match its canonical content.",
            )
        )
    if (
        document["authority_set_identity"] != expected_authority_set_identity
        or document["authority_set_digest"] != expected_authority_set_digest
    ):
        diagnostics.append(
            _diagnostic(
                "CAPTURE_OBSERVATION_AUTHORITY_TRUST_MISMATCH",
                "$.capture_observation_authority_set",
                "The capture-observation authority set does not match the identity and digest bound by apply authority.",
            )
        )
    expected_bindings = {
        "candidate_identity": expected_candidate_identity,
        "implementation_manifest_digest": expected_implementation_manifest_digest,
        "plan_digest": expected_plan_digest,
        "plan_action_set_digest": expected_plan_action_set_digest,
        "capability_set_digest": expected_capability_set_digest,
        "captured_state_identity": expected_captured_state_identity,
        "captured_state_digest": expected_captured_state_digest,
    }
    if bindings != expected_bindings:
        diagnostics.append(
            _diagnostic(
                "CAPTURE_OBSERVATION_AUTHORITY_BINDING_MISMATCH",
                "$.capture_observation_authority_set.bindings",
                "The capture-observation authority set does not match the complete trusted capture and plan tuple.",
            )
        )

    result: dict[tuple[str, int], Mapping[str, object]] = {}
    ordered_keys: list[tuple[int, str]] = []
    valid = True
    for observation in observations:
        if not isinstance(observation, Mapping) or set(observation) != (
            _CAPTURE_OBSERVATION_FIELDS
        ):
            valid = False
            continue
        identity = observation.get("action_identity")
        ordinal = observation.get("ordinal")
        pre_state = observation.get("normalized_pre_state")
        if not isinstance(identity, str) or type(ordinal) is not int:
            valid = False
            continue
        key = (identity, ordinal)
        action = plan_action_index.get(key)
        controlled_identities = (
            action.get("controlled_equipment_identities")
            if isinstance(action, Mapping)
            else None
        )
        if (
            action is None
            or key in result
            or observation.get("captured_state_identity")
            != expected_captured_state_identity
            or observation.get("captured_state_digest")
            != expected_captured_state_digest
            or observation.get("surface") != action.get("surface_scope")
            or observation.get("controlled_equipment_identities")
            != controlled_identities
            or not isinstance(controlled_identities, list)
            or _normalized_component_identities(pre_state)
            != tuple(controlled_identities)
            or observation.get("normalized_pre_state_digest")
            != canonical_digest(pre_state)
        ):
            valid = False
            continue
        result[key] = observation
        ordered_keys.append((ordinal, identity))
    if (
        set(result) != set(plan_action_index)
        or ordered_keys != sorted(ordered_keys)
        or [ordinal for ordinal, _ in ordered_keys] != list(range(len(observations)))
        or len(observations) != len(plan_action_index)
    ):
        valid = False
    if not valid:
        diagnostics.append(
            _diagnostic(
                "CAPTURE_OBSERVATION_AUTHORITY_MEMBERSHIP_INVALID",
                "$.capture_observation_authority_set.observations",
                "The capture-observation authority set is not an exact, ordered projection of the authoritative plan and capture.",
            )
        )
    return result, tuple(sorted(set(diagnostics)))


def validate_capture_observation_authority_set(
    document: object,
    *,
    authoritative_plan_action_set: object,
    expected_authority_set_identity: str,
    expected_authority_set_digest: str,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_plan_digest: str,
    expected_plan_action_set_digest: str,
    expected_capability_set_digest: str,
    expected_captured_state_identity: str,
    expected_captured_state_digest: str,
) -> tuple[Diagnostic, ...]:
    """Validate one closed capture-observation authority set."""

    plan_action_index, plan_diagnostics = _validated_plan_action_index(
        authoritative_plan_action_set,
        expected_action_set_digest=expected_plan_action_set_digest,
        expected_candidate_identity=expected_candidate_identity,
        expected_implementation_manifest_digest=(
            expected_implementation_manifest_digest
        ),
        expected_plan_digest=expected_plan_digest,
    )
    _, observation_diagnostics = _validated_capture_observation_authority_index(
        document,
        expected_authority_set_identity=expected_authority_set_identity,
        expected_authority_set_digest=expected_authority_set_digest,
        expected_candidate_identity=expected_candidate_identity,
        expected_implementation_manifest_digest=(
            expected_implementation_manifest_digest
        ),
        expected_plan_digest=expected_plan_digest,
        expected_plan_action_set_digest=expected_plan_action_set_digest,
        expected_capability_set_digest=expected_capability_set_digest,
        expected_captured_state_identity=expected_captured_state_identity,
        expected_captured_state_digest=expected_captured_state_digest,
        plan_action_index=plan_action_index,
    )
    return tuple(sorted(set(plan_diagnostics + observation_diagnostics)))


def validate_prepared_action_authority_set(
    document: object,
    *,
    authoritative_captured_state: object,
    expected_captured_state_identity: str,
    expected_captured_state_digest: str,
    capture_observation_authority_set: object,
    expected_capture_observation_authority_set_identity: str,
    expected_capture_observation_authority_set_digest: str,
    authoritative_plan_action_set: object,
    expected_plan_action_set_digest: str,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_plan_digest: str,
    expected_prepared_action_authority_set_identity: str,
    expected_prepared_action_authority_set_digest: str,
) -> tuple[Diagnostic, ...]:
    """Validate the complete sealed action authority before apply issuance."""

    diagnostics: list[Diagnostic] = []
    plan_action_index, plan_diagnostics = _validated_plan_action_index(
        authoritative_plan_action_set,
        expected_action_set_digest=expected_plan_action_set_digest,
        expected_candidate_identity=expected_candidate_identity,
        expected_implementation_manifest_digest=(
            expected_implementation_manifest_digest
        ),
        expected_plan_digest=expected_plan_digest,
    )
    diagnostics.extend(plan_diagnostics)
    try:
        captured_state_diagnostics = _validate_captured_state(
            authoritative_captured_state,
            authoritative_plan_action_set,
            expected_candidate_identity=expected_candidate_identity,
            expected_implementation_manifest_digest=(
                expected_implementation_manifest_digest
            ),
        )
        captured_state_digest = canonical_digest(authoritative_captured_state)
    except (TypeError, ValueError):
        captured_state_diagnostics = (object(),)
        captured_state_digest = None
    captured_bindings = (
        authoritative_captured_state.get("bindings")
        if isinstance(authoritative_captured_state, Mapping)
        else None
    )
    if (
        captured_state_diagnostics
        or captured_state_digest != expected_captured_state_digest
        or not isinstance(captured_bindings, Mapping)
    ):
        diagnostics.append(
            _diagnostic(
                "CAPTURED_STATE_AUTHORITY_INVALID",
                "$.authoritative_captured_state",
                "The complete captured-state artifact is not valid for the independently trusted plan and digest.",
            )
        )
    capability_set_digest = (
        captured_bindings.get("capability_set_digest")
        if isinstance(captured_bindings, Mapping)
        else None
    )
    capture_observation_index, capture_observation_diagnostics = (
        _validated_capture_observation_authority_index(
            capture_observation_authority_set,
            expected_authority_set_identity=(
                expected_capture_observation_authority_set_identity
            ),
            expected_authority_set_digest=(
                expected_capture_observation_authority_set_digest
            ),
            expected_candidate_identity=expected_candidate_identity,
            expected_implementation_manifest_digest=(
                expected_implementation_manifest_digest
            ),
            expected_plan_digest=expected_plan_digest,
            expected_plan_action_set_digest=expected_plan_action_set_digest,
            expected_capability_set_digest=(
                capability_set_digest if isinstance(capability_set_digest, str) else ""
            ),
            expected_captured_state_identity=expected_captured_state_identity,
            expected_captured_state_digest=expected_captured_state_digest,
            plan_action_index=plan_action_index,
        )
    )
    diagnostics.extend(capture_observation_diagnostics)
    capture_observations_valid = not capture_observation_diagnostics
    prepared_index, prepared_valid = _validated_prepared_action_authority_index(
        document,
        expected_authority_set_identity=(
            expected_prepared_action_authority_set_identity
        ),
        expected_authority_set_digest=expected_prepared_action_authority_set_digest,
        expected_captured_state_identity=expected_captured_state_identity,
        expected_captured_state_digest=expected_captured_state_digest,
        expected_candidate_identity=expected_candidate_identity,
        expected_implementation_manifest_digest=(
            expected_implementation_manifest_digest
        ),
        expected_capability_set_digest=(
            capability_set_digest if isinstance(capability_set_digest, str) else ""
        ),
    )
    if (
        not prepared_valid
        or not capture_observations_valid
        or set(prepared_index) != set(plan_action_index)
        or any(
            key not in plan_action_index
            or key not in capture_observation_index
            or not _prepared_authority_matches_plan_action(
                authority, plan_action_index[key]
            )
            or authority.get("captured_pre_state")
            != capture_observation_index[key].get("normalized_pre_state")
            or authority.get("captured_pre_state_digest")
            != capture_observation_index[key].get("normalized_pre_state_digest")
            for key, authority in prepared_index.items()
        )
    ):
        diagnostics.append(
            _diagnostic(
                "PREPARED_ACTION_AUTHORITY_INVALID",
                "$.prepared_action_authority_set",
                "The sealed pre-invocation authority set is not complete and valid for the captured plan.",
            )
        )
    return tuple(sorted(set(diagnostics)))


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
    record_checkpoint_identity = record.get("checkpoint_identity")
    transition_claim = record.get("compensation_transition_claim")
    compensation_authority_kind = record.get("compensation_authority_kind")
    try:
        canonical_digest(record)
    except (TypeError, ValueError):
        return None
    if (
        set(record) != _CHECKPOINT_FIELDS
        or not isinstance(history, list)
        or any(type(item) is not str for item in history)
        or (tuple(history), phase, intent) not in _CHECKPOINT_PHASE_MATRIX
        or type(record.get("ordinal")) is not int
        or record["ordinal"] < 0
        or record_checkpoint_identity != checkpoint_identity(record_version, record)
        or not _compensation_transition_claim_valid(
            transition_claim, record_checkpoint_identity
        )
        or (transition_claim is not None and phase in {"prepared", "completed"})
        or (
            phase in {"prepared", "completed"} and compensation_authority_kind != "none"
        )
        or (
            phase in {"compensating", "compensated", "compensation_blocked"}
            and (
                compensation_authority_kind
                not in {"automatic_apply", "public_compensation"}
                or (transition_claim is None)
                != (compensation_authority_kind == "automatic_apply")
            )
        )
    ):
        return None
    return {
        "checkpoint_identity": record_checkpoint_identity,
        "durable_generation": generation,
        "record_version": record_version,
        "phase": record["phase"],
        "invocation_state": record["invocation_state"],
        "compensation_authority_kind": record["compensation_authority_kind"],
        "action_identity": record["action_identity"],
        "ordinal": record["ordinal"],
        "compensation_transition_claim_identity": (
            transition_claim["transition_claim_identity"]
            if isinstance(transition_claim, Mapping)
            else None
        ),
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


def _checkpoint_lifecycle_frontier_valid(
    records: Sequence[Mapping[str, object] | None],
) -> bool:
    compensation_phases = {
        "compensating",
        "compensated",
        "compensation_blocked",
    }
    phases = [record.get("phase") if record is not None else None for record in records]
    transitioned_indices = [
        index for index, phase in enumerate(phases) if phase in compensation_phases
    ]
    if not transitioned_indices:
        prepared_indices = [
            index for index, phase in enumerate(phases) if phase == "prepared"
        ]
        return (
            all(phase in {"prepared", "completed"} for phase in phases)
            and len(prepared_indices) <= 1
            and (not prepared_indices or prepared_indices[0] == len(phases) - 1)
            and all(phase == "completed" for phase in phases[: len(phases) - 1])
        )
    frontier = transitioned_indices[0]
    if transitioned_indices != list(range(frontier, len(records))) or any(
        phase != "completed" for phase in phases[:frontier]
    ):
        return False
    frontier_phase = phases[frontier]
    suffix_after_frontier = phases[frontier + 1 :]
    return frontier_phase in compensation_phases and all(
        phase == "compensated" for phase in suffix_after_frontier
    )


def _prepared_action_authority_set_identity(document: Mapping[str, object]) -> str:
    payload = {
        key: value
        for key, value in document.items()
        if key not in {"authority_set_identity", "authority_set_digest"}
    }
    return "prepared-action-authority-set:" + canonical_digest(payload)


def _prepared_action_authority_set_digest(document: Mapping[str, object]) -> str:
    return _artifact_digest(document, "authority_set_digest")


def _validated_prepared_action_authority_index(
    document: object,
    *,
    expected_authority_set_identity: str,
    expected_authority_set_digest: str,
    expected_captured_state_identity: str,
    expected_captured_state_digest: str,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_capability_set_digest: str,
) -> tuple[dict[tuple[str, int], Mapping[str, object]], bool]:
    """Validate and index one sealed complete pre-invocation authority set."""

    if (
        not isinstance(document, Mapping)
        or document.get("schema_version")
        != "agent-equipment-prepared-action-authority-set/v1"
        or not _schema_valid(document)
        or document.get("authority_set_identity")
        != _prepared_action_authority_set_identity(document)
        or document.get("authority_set_digest")
        != _prepared_action_authority_set_digest(document)
        or document.get("authority_set_identity") != expected_authority_set_identity
        or document.get("authority_set_digest") != expected_authority_set_digest
        or contains_literal_credential(document)
    ):
        return {}, False
    authorities = document.get("authorities")
    if not isinstance(authorities, list):
        return {}, False
    result: dict[tuple[str, int], Mapping[str, object]] = {}
    valid = True
    ordered_keys: list[tuple[int, str]] = []
    for authority in authorities:
        if not isinstance(authority, Mapping):
            valid = False
            continue
        identity = authority.get("action_identity")
        ordinal = authority.get("ordinal")
        pre_state = authority.get("captured_pre_state")
        post_state = authority.get("expected_post_state")
        if (
            not isinstance(identity, str)
            or type(ordinal) is not int
            or (identity, ordinal) in result
            or authority.get("candidate_identity") != expected_candidate_identity
            or authority.get("implementation_manifest_digest")
            != expected_implementation_manifest_digest
            or authority.get("captured_state_identity")
            != expected_captured_state_identity
            or authority.get("captured_state_digest") != expected_captured_state_digest
            or authority.get("capability_set_digest") != expected_capability_set_digest
            or authority.get("captured_pre_state_digest") != canonical_digest(pre_state)
            or authority.get("expected_post_state_digest")
            != canonical_digest(post_state)
            or authority.get("authority_digest")
            != canonical_digest(
                {
                    key: value
                    for key, value in authority.items()
                    if key != "authority_digest"
                }
            )
        ):
            valid = False
            continue
        result[(identity, ordinal)] = authority
        ordered_keys.append((ordinal, identity))
    if ordered_keys != sorted(ordered_keys) or [key[0] for key in ordered_keys] != list(
        range(len(authorities))
    ):
        valid = False
    return result, valid


def _prepared_authority_matches_plan_action(
    authority: Mapping[str, object],
    action: Mapping[str, object],
) -> bool:
    compensation = action.get("compensation")
    if not isinstance(compensation, Mapping):
        return False
    expected = {
        "action_identity": action.get("action_identity"),
        "ordinal": action.get("ordinal"),
        "candidate_identity": action.get("candidate_identity"),
        "implementation_manifest_digest": action.get("implementation_manifest_digest"),
        "catalog_digest": action.get("catalog_digest"),
        "lock_digest": action.get("lock_digest"),
        "plan_digest": action.get("plan_digest"),
        "route_capability_binding": {
            "capability_identity": action.get("capability_identity"),
            "capability_digest": action.get("capability_digest"),
            "manager_version_evidence_digest": action.get(
                "manager_version_evidence_digest"
            ),
        },
        "route_digest": action.get("route_digest"),
        "operation_digest": canonical_digest(action.get("operation")),
        "compensation_operation": compensation.get("kind"),
        "surface": action.get("surface_scope"),
        "expected_post_state_digest": action.get("expected_post_state_digest"),
    }
    controlled_identities = action.get("controlled_equipment_identities")
    return (
        isinstance(controlled_identities, list)
        and _normalized_component_identities(authority.get("captured_pre_state"))
        == tuple(controlled_identities)
        and _normalized_component_identities(authority.get("expected_post_state"))
        == tuple(controlled_identities)
        and all(authority.get(field) == value for field, value in expected.items())
        and _normalized_state_includes_desired_fragment(
            authority.get("expected_post_state"),
            action.get("desired_state"),
        )
    )


def _normalized_component_identities(
    normalized_state: object,
) -> tuple[str, ...] | None:
    if not isinstance(normalized_state, Mapping):
        return None
    components = normalized_state.get("component_states")
    if not isinstance(components, list):
        return None
    identities = [
        component.get("equipment_identity")
        for component in components
        if isinstance(component, Mapping)
    ]
    if (
        len(identities) != len(components)
        or any(not isinstance(identity, str) for identity in identities)
        or identities != sorted(set(identities))
    ):
        return None
    return tuple(identities)


def _normalized_state_includes_desired_fragment(
    normalized_state: object,
    desired_state: object,
) -> bool:
    if not isinstance(normalized_state, Mapping) or not isinstance(
        desired_state, Mapping
    ):
        return False
    for field in (
        "route_presence",
        "enablement",
        "native_update_suppression_state",
    ):
        if (
            field in desired_state
            and normalized_state.get(field) != desired_state[field]
        ):
            return False
    desired_configuration = desired_state.get("configuration")
    if isinstance(desired_configuration, Mapping):
        expected_configuration = dict(desired_configuration)
        if expected_configuration.get("status") == "desired":
            expected_configuration["status"] = "observed"
        if normalized_state.get("configuration") != expected_configuration:
            return False
    desired_components = desired_state.get("component_states")
    normalized_components = normalized_state.get("component_states")
    if isinstance(desired_components, list):
        if not isinstance(normalized_components, list):
            return False
        normalized_index = {
            item.get("equipment_identity"): item.get("state")
            for item in normalized_components
            if isinstance(item, Mapping)
        }
        if any(
            not isinstance(item, Mapping)
            or normalized_index.get(item.get("equipment_identity")) != item.get("state")
            for item in desired_components
        ):
            return False
    return True


def _checkpoint_matches_plan_action(
    record: Mapping[str, object],
    action: Mapping[str, object],
) -> bool:
    capability_binding = {
        "capability_identity": action.get("capability_identity"),
        "capability_digest": action.get("capability_digest"),
        "manager_version_evidence_digest": action.get(
            "manager_version_evidence_digest"
        ),
    }
    compensation = action.get("compensation")
    if not isinstance(compensation, Mapping):
        return False
    expected = {
        "step_id": f"step-{action.get('ordinal'):03d}",
        "action_identity": action.get("action_identity"),
        "ordinal": action.get("ordinal"),
        "candidate_digest": action.get("candidate_identity"),
        "implementation_manifest_digest": action.get("implementation_manifest_digest"),
        "catalog_digest": action.get("catalog_digest"),
        "lock_digest": action.get("lock_digest"),
        "plan_digest": action.get("plan_digest"),
        "route_capability_binding": capability_binding,
        "route_digest": action.get("route_digest"),
        "operation_digest": canonical_digest(action.get("operation")),
        "compensation_operation": compensation.get("kind"),
        "expected_post_state_digest": action.get("expected_post_state_digest"),
        "surface": action.get("surface_scope"),
    }
    return all(record.get(field) == value for field, value in expected.items())


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


def validate_checkpoint_store_snapshot(
    document: object,
    *,
    expected_apply_authorization_identity: str,
    expected_apply_authorization_digest: str,
    expected_execution_domain_identity: str,
    expected_execution_nonce: str,
    expected_run_identity: str,
    expected_plan_action_set_digest: str,
) -> tuple[Diagnostic, ...]:
    """Validate one sealed, complete checkpoint-store replay snapshot."""

    if (
        not isinstance(document, Mapping)
        or document.get("schema_version")
        != "agent-equipment-checkpoint-store-snapshot/v1"
        or not _schema_valid(
            document,
            maximum_bytes=MAX_CHECKPOINT_STORE_SNAPSHOT_BYTES,
        )
    ):
        return (
            _diagnostic(
                "CHECKPOINT_STORE_SNAPSHOT_SCHEMA_INVALID",
                "$.checkpoint_store_snapshot",
                "The checkpoint-store snapshot does not satisfy the checked-in closed schema and size bound.",
            ),
        )
    if contains_literal_credential(document):
        return (
            _diagnostic(
                "CHECKPOINT_STORE_SNAPSHOT_LITERAL_SECRET",
                "$.checkpoint_store_snapshot",
                "The checkpoint-store snapshot contains credential-shaped literal material.",
            ),
        )

    diagnostics: list[Diagnostic] = []
    if document["snapshot_identity"] != _checkpoint_store_snapshot_identity(document):
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_STORE_SNAPSHOT_IDENTITY_INVALID",
                "$.checkpoint_store_snapshot.snapshot_identity",
                "The checkpoint-store snapshot identity does not match its canonical payload.",
            )
        )
    if document["snapshot_digest"] != _checkpoint_store_snapshot_digest(document):
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_STORE_SNAPSHOT_DIGEST_INVALID",
                "$.checkpoint_store_snapshot.snapshot_digest",
                "The checkpoint-store snapshot digest does not match the complete snapshot.",
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
                "CHECKPOINT_STORE_SNAPSHOT_BINDING_MISMATCH",
                "$.checkpoint_store_snapshot.bindings",
                "The checkpoint-store snapshot does not bind the exact independently trusted apply run.",
            )
        )

    checkpoints = document["checkpoints"]
    assert isinstance(checkpoints, list)
    expected_record_bindings = {
        "apply_authorization_identity": expected_apply_authorization_identity,
        "apply_authorization_digest": expected_apply_authorization_digest,
        "execution_domain_identity": expected_execution_domain_identity,
        "execution_nonce": expected_execution_nonce,
        "run_identity": expected_run_identity,
    }
    if any(
        not isinstance(record := _checkpoint_record(checkpoint), Mapping)
        or any(
            record.get(field) != expected
            for field, expected in expected_record_bindings.items()
        )
        for checkpoint in checkpoints
    ):
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_STORE_SNAPSHOT_RECORD_BINDING_MISMATCH",
                "$.checkpoint_store_snapshot.checkpoints",
                "A full checkpoint record does not bind the snapshot's exact independently trusted apply run.",
            )
        )
    projected = _project_checkpoint_entries(checkpoints)
    store_generation = document["checkpoint_store_generation"]
    generations = [
        checkpoint.get("durable_generation")
        for checkpoint in checkpoints
        if isinstance(checkpoint, Mapping)
    ]
    if (
        projected is None
        or not projected
        or projected
        != sorted(
            projected,
            key=lambda entry: (entry["ordinal"], entry["checkpoint_identity"]),
        )
        or len({entry["checkpoint_identity"] for entry in projected}) != len(projected)
        or len({entry["ordinal"] for entry in projected}) != len(projected)
        or not generations
        or any(type(generation) is not int for generation in generations)
        or len(set(generations)) != len(generations)
        or store_generation != max(generations)
    ):
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_STORE_SNAPSHOT_MEMBERSHIP_INVALID",
                "$.checkpoint_store_snapshot.checkpoints",
                "The checkpoint-store snapshot is not one ordered, unique, complete durable-record sequence at its latest durable generation.",
            )
        )
    return tuple(sorted(set(diagnostics)))


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
    authoritative_captured_state: object,
    expected_captured_state_identity: str,
    expected_captured_state_digest: str,
    capture_observation_authority_set: object,
    expected_capture_observation_authority_set_identity: str,
    expected_capture_observation_authority_set_digest: str,
    prepared_action_authority_set: object,
    expected_prepared_action_authority_set_identity: str,
    expected_prepared_action_authority_set_digest: str,
    authoritative_plan_action_set: object,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_plan_digest: str,
    expected_compensation_authorization_identity: str | None = None,
    expected_compensation_authorization_digest: str | None = None,
    expected_compensation_nonce: str | None = None,
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
    if not isinstance(
        expected_prepared_action_authority_set_identity, str
    ) or not isinstance(expected_prepared_action_authority_set_digest, str):
        diagnostics.append(
            _diagnostic(
                "PREPARED_ACTION_AUTHORITY_TRUST_MISMATCH",
                "$.prepared_action_authority_set",
                "The executor must obtain the prepared-action authority identity and digest from validated apply bindings.",
            )
        )
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
        or projected is None
        or not projected
        or trusted_checkpoint_store_generation
        != max(entry["durable_generation"] for entry in projected)
    ):
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_STORE_GENERATION_MISMATCH",
                "$.checkpoint_store_generation",
                "The checkpoint manifest generation is not the latest durable generation represented by the complete trusted store records.",
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

    plan_action_index, plan_diagnostics = _validated_plan_action_index(
        authoritative_plan_action_set,
        expected_action_set_digest=expected_plan_action_set_digest,
        expected_candidate_identity=expected_candidate_identity,
        expected_implementation_manifest_digest=(
            expected_implementation_manifest_digest
        ),
        expected_plan_digest=expected_plan_digest,
    )
    diagnostics.extend(plan_diagnostics)
    captured_state_diagnostics = _validate_captured_state(
        authoritative_captured_state,
        authoritative_plan_action_set,
        expected_candidate_identity=expected_candidate_identity,
        expected_implementation_manifest_digest=(
            expected_implementation_manifest_digest
        ),
    )
    if captured_state_diagnostics:
        diagnostics.append(
            _diagnostic(
                "CAPTURED_STATE_AUTHORITY_INVALID",
                "$.authoritative_captured_state",
                "The complete captured-state artifact is not valid for the independently trusted plan-action set.",
            )
        )
    captured_bindings = (
        authoritative_captured_state.get("bindings")
        if isinstance(authoritative_captured_state, Mapping)
        else None
    )
    capture_observation_index, capture_observation_diagnostics = (
        _validated_capture_observation_authority_index(
            capture_observation_authority_set,
            expected_authority_set_identity=(
                expected_capture_observation_authority_set_identity
            ),
            expected_authority_set_digest=(
                expected_capture_observation_authority_set_digest
            ),
            expected_candidate_identity=expected_candidate_identity,
            expected_implementation_manifest_digest=(
                expected_implementation_manifest_digest
            ),
            expected_plan_digest=expected_plan_digest,
            expected_plan_action_set_digest=expected_plan_action_set_digest,
            expected_capability_set_digest=(
                captured_bindings.get("capability_set_digest", "")
                if isinstance(captured_bindings, Mapping)
                else ""
            ),
            expected_captured_state_identity=expected_captured_state_identity,
            expected_captured_state_digest=expected_captured_state_digest,
            plan_action_index=plan_action_index,
        )
    )
    diagnostics.extend(capture_observation_diagnostics)
    capture_observations_valid = not capture_observation_diagnostics
    prepared_authority_index, prepared_authorities_valid = (
        _validated_prepared_action_authority_index(
            prepared_action_authority_set,
            expected_authority_set_identity=(
                expected_prepared_action_authority_set_identity
            ),
            expected_authority_set_digest=expected_prepared_action_authority_set_digest,
            expected_captured_state_identity=expected_captured_state_identity,
            expected_captured_state_digest=expected_captured_state_digest,
            expected_candidate_identity=expected_candidate_identity,
            expected_implementation_manifest_digest=(
                expected_implementation_manifest_digest
            ),
            expected_capability_set_digest=(
                captured_bindings.get("capability_set_digest", "")
                if isinstance(captured_bindings, Mapping)
                else ""
            ),
        )
    )
    if (
        not prepared_authorities_valid
        or not capture_observations_valid
        or set(prepared_authority_index) != set(plan_action_index)
        or any(
            key not in capture_observation_index
            or authority.get("captured_pre_state")
            != capture_observation_index[key].get("normalized_pre_state")
            or authority.get("captured_pre_state_digest")
            != capture_observation_index[key].get("normalized_pre_state_digest")
            or not _prepared_authority_matches_plan_action(
                authority,
                plan_action_index[key],
            )
            for key, authority in prepared_authority_index.items()
            if key in plan_action_index
        )
    ):
        diagnostics.append(
            _diagnostic(
                "PREPARED_ACTION_AUTHORITY_INVALID",
                "$.prepared_action_authority_set",
                "The sealed pre-invocation authority set is not complete and valid for the plan.",
            )
        )
    records = [_checkpoint_record(snapshot) for snapshot in trusted_snapshots]
    checkpoint_action_keys = [
        (record.get("action_identity"), record.get("ordinal"))
        for record in records
        if record is not None
    ]
    canonical_plan_keys = list(plan_action_index)
    if (
        checkpoint_action_keys != canonical_plan_keys[: len(checkpoint_action_keys)]
        or any(record is None for record in records)
        or any(
            not isinstance(identity, str)
            or type(ordinal) is not int
            or (identity, ordinal) not in plan_action_index
            or not _checkpoint_matches_plan_action(
                record,
                plan_action_index[(identity, ordinal)],
            )
            for record, (identity, ordinal) in zip(
                (record for record in records if record is not None),
                checkpoint_action_keys,
                strict=True,
            )
        )
    ):
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_PLAN_ACTION_MISMATCH",
                "$.checkpoints",
                "A checkpoint does not map uniquely into the independently validated complete plan-action set.",
            )
        )

    captured_bindings = (
        authoritative_captured_state.get("bindings")
        if isinstance(authoritative_captured_state, Mapping)
        else None
    )
    try:
        actual_captured_state_digest = canonical_digest(authoritative_captured_state)
    except (TypeError, ValueError):
        actual_captured_state_digest = None
    if (
        not isinstance(captured_bindings, Mapping)
        or actual_captured_state_digest != expected_captured_state_digest
    ) or any(
        record.get("run_identity") != expected_run_identity
        or record.get("execution_domain_identity") != expected_execution_domain_identity
        or record.get("apply_authorization_identity")
        != expected_apply_authorization_identity
        or record.get("apply_authorization_digest")
        != expected_apply_authorization_digest
        or record.get("execution_nonce") != expected_execution_nonce
        or record.get("candidate_digest") != captured_bindings.get("candidate_identity")
        or record.get("implementation_manifest_digest")
        != captured_bindings.get("implementation_manifest_digest")
        or record.get("catalog_digest") != captured_bindings.get("catalog_digest")
        or record.get("lock_digest") != captured_bindings.get("lock_digest")
        or record.get("plan_digest") != captured_bindings.get("plan_digest")
        or record.get("prepared_action_authority_set_identity")
        != expected_prepared_action_authority_set_identity
        or record.get("prepared_action_authority_set_digest")
        != expected_prepared_action_authority_set_digest
        or record.get("capability_set_digest")
        != captured_bindings.get("capability_set_digest")
        or record.get("captured_state_identity") != expected_captured_state_identity
        or record.get("captured_state_digest") != expected_captured_state_digest
        or not isinstance(record.get("action_identity"), str)
        or (record["action_identity"], record.get("ordinal"))
        not in prepared_authority_index
        or record.get("captured_state_identity")
        != prepared_authority_index[
            (record["action_identity"], record.get("ordinal"))
        ].get("captured_state_identity")
        or record.get("captured_state_digest")
        != prepared_authority_index[
            (record["action_identity"], record.get("ordinal"))
        ].get("captured_state_digest")
        or record.get("pre_state")
        != prepared_authority_index[
            (record["action_identity"], record.get("ordinal"))
        ].get("captured_pre_state")
        or record.get("pre_state_digest")
        != prepared_authority_index[
            (record["action_identity"], record.get("ordinal"))
        ].get("captured_pre_state_digest")
        or record.get("expected_post_state")
        != prepared_authority_index[
            (record["action_identity"], record.get("ordinal"))
        ].get("expected_post_state")
        or record.get("expected_post_state_digest")
        != prepared_authority_index[
            (record["action_identity"], record.get("ordinal"))
        ].get("expected_post_state_digest")
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
    compensation_kinds = {
        record.get("compensation_authority_kind")
        for record in records
        if record is not None
        and record.get("phase")
        in {"compensating", "compensated", "compensation_blocked"}
    }
    if len(compensation_kinds) > 1:
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_COMPENSATION_PROVENANCE_MISMATCH",
                "$.checkpoints",
                "One checkpoint set cannot mix automatic and public compensation provenance.",
            )
        )
    if not _checkpoint_lifecycle_frontier_valid(records):
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_LIFECYCLE_FRONTIER_MISMATCH",
                "$.checkpoints",
                "Checkpoint phases do not form one reachable forward prefix or reverse-topological compensation frontier.",
            )
        )
    if any(
        isinstance(record.get("compensation_transition_claim"), Mapping)
        and (
            record["compensation_transition_claim"].get(
                "compensation_authorization_identity"
            )
            != expected_compensation_authorization_identity
            or record["compensation_transition_claim"].get(
                "compensation_authorization_digest"
            )
            != expected_compensation_authorization_digest
            or record["compensation_transition_claim"].get("compensation_nonce")
            != expected_compensation_nonce
        )
        for record in records
        if record is not None
    ):
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_COMPENSATION_CLAIM_MISMATCH",
                "$.checkpoints",
                "A public compensation transition claim does not match the independently validated compensation authority.",
            )
        )
    has_public_claim = any(
        isinstance(record.get("compensation_transition_claim"), Mapping)
        for record in records
        if record is not None
    )
    if has_public_claim and not all(
        isinstance(value, str)
        for value in (
            expected_compensation_authorization_identity,
            expected_compensation_authorization_digest,
            expected_compensation_nonce,
        )
    ):
        diagnostics.append(
            _diagnostic(
                "CHECKPOINT_COMPENSATION_AUTHORITY_REQUIRED",
                "$.checkpoints",
                "Public compensation claims require an independently validated non-null compensation-authority tuple.",
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
    authoritative_captured_state: object,
    expected_captured_state_identity: str,
    expected_captured_state_digest: str,
    capture_observation_authority_set: object,
    expected_capture_observation_authority_set_identity: str,
    expected_capture_observation_authority_set_digest: str,
    prepared_action_authority_set: object,
    expected_prepared_action_authority_set_identity: str,
    expected_prepared_action_authority_set_digest: str,
    authoritative_plan_action_set: object,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_plan_digest: str,
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

    trusted_snapshots: Sequence[Mapping[str, object]] = (
        trusted_checkpoint_records
        if isinstance(trusted_checkpoint_records, Sequence)
        and not isinstance(trusted_checkpoint_records, (str, bytes))
        else ()
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
        trusted_checkpoint_records=trusted_snapshots,
        pretransition_checkpoint_store_generation=pretransition_checkpoint_store_generation,
        pretransition_checkpoint_records=pretransition_checkpoint_records,
        authoritative_captured_state=authoritative_captured_state,
        expected_captured_state_identity=expected_captured_state_identity,
        expected_captured_state_digest=expected_captured_state_digest,
        capture_observation_authority_set=capture_observation_authority_set,
        expected_capture_observation_authority_set_identity=(
            expected_capture_observation_authority_set_identity
        ),
        expected_capture_observation_authority_set_digest=(
            expected_capture_observation_authority_set_digest
        ),
        prepared_action_authority_set=prepared_action_authority_set,
        expected_prepared_action_authority_set_identity=(
            expected_prepared_action_authority_set_identity
        ),
        expected_prepared_action_authority_set_digest=(
            expected_prepared_action_authority_set_digest
        ),
        authoritative_plan_action_set=authoritative_plan_action_set,
        expected_candidate_identity=expected_candidate_identity,
        expected_implementation_manifest_digest=(
            expected_implementation_manifest_digest
        ),
        expected_plan_digest=expected_plan_digest,
        expected_compensation_authorization_identity=(
            expected_compensation_authorization_identity
        ),
        expected_compensation_authorization_digest=(
            expected_compensation_authorization_digest
        ),
        expected_compensation_nonce=expected_compensation_nonce,
    )
    diagnostics: list[Diagnostic] = list(checkpoint_diagnostics)
    if any(
        isinstance(snapshot, Mapping)
        and isinstance(snapshot.get("record"), Mapping)
        and snapshot["record"].get("compensation_authority_kind") == "automatic_apply"
        and snapshot["record"].get("phase")
        in {"compensating", "compensated", "compensation_blocked"}
        for snapshot in trusted_snapshots
    ):
        diagnostics.append(
            _diagnostic(
                "COMPENSATION_AUTHORITY_TAKEOVER_FORBIDDEN",
                "$.trusted_checkpoint_store",
                "A public compensation invocation cannot replace durable automatic rollback intent.",
            )
        )
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


def validate_public_compensation_recovery(
    document: object,
    *,
    expected_compensation_authorization_identity: str,
    expected_compensation_authorization_digest: str,
    expected_apply_authorization_identity: str,
    expected_apply_authorization_digest: str,
    expected_execution_domain_identity: str,
    expected_execution_nonce: str,
    expected_run_identity: str,
    expected_plan_action_set_digest: str,
    expected_compensation_nonce: str,
    expected_issuer_identity: str,
    original_checkpoint_set_manifest: object,
    original_checkpoint_store_generation: int,
    original_checkpoint_records: Sequence[Mapping[str, object]],
    current_checkpoint_set_manifest: object,
    current_checkpoint_store_generation: int,
    current_checkpoint_records: Sequence[Mapping[str, object]],
    pretransition_checkpoint_store_generation: int,
    pretransition_checkpoint_records: Sequence[Mapping[str, object]],
    authoritative_captured_state: object,
    expected_captured_state_identity: str,
    expected_captured_state_digest: str,
    capture_observation_authority_set: object,
    expected_capture_observation_authority_set_identity: str,
    expected_capture_observation_authority_set_digest: str,
    prepared_action_authority_set: object,
    expected_prepared_action_authority_set_identity: str,
    expected_prepared_action_authority_set_digest: str,
    authoritative_plan_action_set: object,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_plan_digest: str,
    expected_compensation_ledger_claim_identity: str,
    trusted_compensation_ledger_claim_identity: str,
    trusted_compensation_ledger_authorization_identity: str,
    trusted_compensation_ledger_authorization_digest: str,
    trusted_compensation_ledger_generation: int,
) -> tuple[Diagnostic, ...]:
    """Validate restart under one previously claimed public compensation intent."""

    if (
        not isinstance(document, Mapping)
        or document.get("schema_version")
        != "agent-equipment-compensation-authorization/v1"
        or not _schema_valid(document)
    ):
        return (
            _diagnostic(
                "COMPENSATION_RECOVERY_AUTHORITY_INVALID",
                "$.compensation_authorization",
                "The archived compensation authorization does not satisfy the checked-in closed schema.",
            ),
        )
    if contains_literal_credential(document):
        return (
            _diagnostic(
                "COMPENSATION_RECOVERY_AUTHORITY_INVALID",
                "$.compensation_authorization",
                "The archived compensation authorization contains credential-shaped literal material.",
            ),
        )

    shared_checkpoint_inputs = {
        "expected_apply_authorization_identity": expected_apply_authorization_identity,
        "expected_apply_authorization_digest": expected_apply_authorization_digest,
        "expected_execution_domain_identity": expected_execution_domain_identity,
        "expected_execution_nonce": expected_execution_nonce,
        "expected_run_identity": expected_run_identity,
        "expected_plan_action_set_digest": expected_plan_action_set_digest,
        "authoritative_captured_state": authoritative_captured_state,
        "expected_captured_state_identity": expected_captured_state_identity,
        "expected_captured_state_digest": expected_captured_state_digest,
        "capture_observation_authority_set": capture_observation_authority_set,
        "expected_capture_observation_authority_set_identity": (
            expected_capture_observation_authority_set_identity
        ),
        "expected_capture_observation_authority_set_digest": (
            expected_capture_observation_authority_set_digest
        ),
        "prepared_action_authority_set": prepared_action_authority_set,
        "expected_prepared_action_authority_set_identity": (
            expected_prepared_action_authority_set_identity
        ),
        "expected_prepared_action_authority_set_digest": (
            expected_prepared_action_authority_set_digest
        ),
        "authoritative_plan_action_set": authoritative_plan_action_set,
        "expected_candidate_identity": expected_candidate_identity,
        "expected_implementation_manifest_digest": (
            expected_implementation_manifest_digest
        ),
        "expected_plan_digest": expected_plan_digest,
    }
    original_diagnostics = validate_checkpoint_set_manifest(
        original_checkpoint_set_manifest,
        trusted_checkpoint_store_generation=original_checkpoint_store_generation,
        trusted_checkpoint_records=original_checkpoint_records,
        pretransition_checkpoint_store_generation=(
            original_checkpoint_store_generation
        ),
        pretransition_checkpoint_records=original_checkpoint_records,
        **shared_checkpoint_inputs,
    )
    current_diagnostics = validate_checkpoint_set_manifest(
        current_checkpoint_set_manifest,
        trusted_checkpoint_store_generation=current_checkpoint_store_generation,
        trusted_checkpoint_records=current_checkpoint_records,
        pretransition_checkpoint_store_generation=(
            pretransition_checkpoint_store_generation
        ),
        pretransition_checkpoint_records=pretransition_checkpoint_records,
        expected_compensation_authorization_identity=(
            expected_compensation_authorization_identity
        ),
        expected_compensation_authorization_digest=(
            expected_compensation_authorization_digest
        ),
        expected_compensation_nonce=expected_compensation_nonce,
        **shared_checkpoint_inputs,
    )
    diagnostics: list[Diagnostic] = [*original_diagnostics, *current_diagnostics]

    original_checkpoint_set_digest = (
        original_checkpoint_set_manifest.get("checkpoint_set_digest")
        if isinstance(original_checkpoint_set_manifest, Mapping)
        else None
    )
    expected_bindings = {
        "apply_authorization_identity": expected_apply_authorization_identity,
        "apply_authorization_digest": expected_apply_authorization_digest,
        "execution_domain_identity": expected_execution_domain_identity,
        "execution_nonce": expected_execution_nonce,
        "run_identity": expected_run_identity,
        "checkpoint_set_digest": original_checkpoint_set_digest,
        "plan_action_set_digest": expected_plan_action_set_digest,
    }
    try:
        document_digest = canonical_digest(document)
        document_identity = _compensation_authorization_identity(document)
    except (TypeError, ValueError):
        document_digest = None
        document_identity = None
    if (
        document.get("compensation_authorization_identity") != document_identity
        or document.get("compensation_authorization_identity")
        != expected_compensation_authorization_identity
        or document_digest != expected_compensation_authorization_digest
        or document.get("bindings") != expected_bindings
        or document.get("compensation_nonce") != expected_compensation_nonce
        or document.get("issuer_identity") != expected_issuer_identity
    ):
        diagnostics.append(
            _diagnostic(
                "COMPENSATION_RECOVERY_AUTHORITY_INVALID",
                "$.compensation_authorization",
                "The archived compensation authorization does not match the independently trusted original invocation and checkpoint set.",
            )
        )

    derived_ledger_claim_identity = compensation_ledger_claim_identity(
        expected_execution_domain_identity, expected_compensation_nonce
    )
    if (
        expected_compensation_ledger_claim_identity != derived_ledger_claim_identity
        or trusted_compensation_ledger_claim_identity
        != expected_compensation_ledger_claim_identity
        or trusted_compensation_ledger_authorization_identity
        != expected_compensation_authorization_identity
        or trusted_compensation_ledger_authorization_digest
        != expected_compensation_authorization_digest
        or type(trusted_compensation_ledger_generation) is not int
        or trusted_compensation_ledger_generation < 1
    ):
        diagnostics.append(
            _diagnostic(
                "COMPENSATION_RECOVERY_LEDGER_MISMATCH",
                "$.trusted_compensation_ledger",
                "Recovery requires the original durable ledger claim for the exact compensation authorization and nonce.",
            )
        )

    original_snapshots = (
        original_checkpoint_records
        if isinstance(original_checkpoint_records, Sequence)
        and not isinstance(original_checkpoint_records, (str, bytes))
        else ()
    )
    current_snapshots = (
        current_checkpoint_records
        if isinstance(current_checkpoint_records, Sequence)
        and not isinstance(current_checkpoint_records, (str, bytes))
        else ()
    )
    original_by_identity = {
        record.get("checkpoint_identity"): (snapshot, record)
        for snapshot in original_snapshots
        if (record := _checkpoint_record(snapshot)) is not None
    }
    current_by_identity = {
        record.get("checkpoint_identity"): (snapshot, record)
        for snapshot in current_snapshots
        if (record := _checkpoint_record(snapshot)) is not None
    }
    allowed_descendant_phases = {
        "prepared": {
            "prepared",
            "compensating",
            "compensated",
            "compensation_blocked",
        },
        "completed": {
            "completed",
            "compensating",
            "compensated",
            "compensation_blocked",
        },
    }
    descendant_valid = (
        not original_diagnostics
        and not current_diagnostics
        and type(original_checkpoint_store_generation) is int
        and type(current_checkpoint_store_generation) is int
        and current_checkpoint_store_generation >= original_checkpoint_store_generation
        and len(original_by_identity) == len(original_snapshots)
        and len(current_by_identity) == len(current_snapshots)
        and set(original_by_identity) == set(current_by_identity)
    )
    store_changed = False
    blocked = False
    if descendant_valid:
        for identity, (
            original_snapshot,
            original_record,
        ) in original_by_identity.items():
            current_snapshot, current_record = current_by_identity[identity]
            original_phase = original_record.get("phase")
            current_phase = current_record.get("phase")
            snapshot_changed = current_snapshot != original_snapshot
            store_changed = store_changed or snapshot_changed
            if (
                original_phase not in allowed_descendant_phases
                or original_record.get("compensation_authority_kind") != "none"
                or original_record.get("compensation_transition_claim") is not None
                or current_phase not in allowed_descendant_phases[original_phase]
                or current_record.get("invocation_state")
                != original_record.get("invocation_state")
                or not isinstance(original_record.get("phase_history"), list)
                or not isinstance(current_record.get("phase_history"), list)
                or current_record["phase_history"][
                    : len(original_record["phase_history"])
                ]
                != original_record["phase_history"]
                or type(original_snapshot.get("durable_generation")) is not int
                or type(current_snapshot.get("durable_generation")) is not int
                or current_snapshot["durable_generation"]
                < original_snapshot["durable_generation"]
                or (
                    snapshot_changed
                    and current_snapshot["durable_generation"]
                    <= original_snapshot["durable_generation"]
                )
            ):
                descendant_valid = False
                break
            if current_phase in {
                "compensating",
                "compensated",
                "compensation_blocked",
            }:
                blocked = blocked or current_phase == "compensation_blocked"
                if current_record.get("compensation_authority_kind") != (
                    "public_compensation"
                ):
                    descendant_valid = False
                    break
        if store_changed and (
            current_checkpoint_store_generation <= original_checkpoint_store_generation
        ):
            descendant_valid = False
    if not descendant_valid:
        diagnostics.append(
            _diagnostic(
                "COMPENSATION_RECOVERY_DESCENDANT_MISMATCH",
                "$.current_checkpoint_store",
                "The current store is not an authorized monotonic descendant of the archived pretransition checkpoint set.",
            )
        )
    if blocked:
        diagnostics.append(
            _diagnostic(
                "COMPENSATION_RECOVERY_BLOCKED",
                "$.current_checkpoint_store",
                "A compensation-blocked checkpoint requires separate operator disposition and cannot be resumed.",
            )
        )
    return tuple(sorted(set(diagnostics)))


def _run_terminal_identity(document: Mapping[str, object]) -> str:
    payload = {
        key: value
        for key, value in document.items()
        if key not in {"run_terminal_identity", "run_terminal_digest"}
    }
    return "run-terminal:" + canonical_digest(payload)


def _run_terminal_digest(document: Mapping[str, object]) -> str:
    return _artifact_digest(document, "run_terminal_digest")


def _bytes_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def validate_run_terminal_record(
    document: object,
    *,
    checkpoint_set_manifest: object,
    expected_apply_authorization_identity: str,
    expected_apply_authorization_digest: str,
    expected_execution_domain_identity: str,
    expected_execution_nonce: str,
    expected_run_identity: str,
    authoritative_plan_action_set: object,
    expected_plan_action_set_digest: str,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_plan_digest: str,
    trusted_checkpoint_store_generation: int,
    trusted_checkpoint_records: Sequence[Mapping[str, object]],
    authoritative_captured_state: object,
    expected_captured_state_identity: str,
    expected_captured_state_digest: str,
    capture_observation_authority_set: object,
    expected_capture_observation_authority_set_identity: str,
    expected_capture_observation_authority_set_digest: str,
    prepared_action_authority_set: object,
    expected_prepared_action_authority_set_identity: str,
    expected_prepared_action_authority_set_digest: str,
) -> tuple[Diagnostic, ...]:
    """Validate terminal success from complete plan and checkpoint artifacts."""

    if (
        not isinstance(document, Mapping)
        or document.get("schema_version") != "agent-equipment-run-terminal-record/v1"
        or not _schema_valid(document)
    ):
        return (
            _diagnostic(
                "RUN_TERMINAL_SCHEMA_INVALID",
                "$.run_terminal_record",
                "The run-terminal record does not satisfy the checked-in closed schema.",
            ),
        )
    if contains_literal_credential(document):
        return (
            _diagnostic(
                "RUN_TERMINAL_LITERAL_SECRET",
                "$.run_terminal_record",
                "The run-terminal record contains credential-shaped literal material.",
            ),
        )

    trusted_snapshots: Sequence[Mapping[str, object]] = (
        trusted_checkpoint_records
        if isinstance(trusted_checkpoint_records, Sequence)
        and not isinstance(trusted_checkpoint_records, (str, bytes))
        else ()
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
        trusted_checkpoint_records=trusted_snapshots,
        pretransition_checkpoint_store_generation=(trusted_checkpoint_store_generation),
        pretransition_checkpoint_records=trusted_snapshots,
        authoritative_captured_state=authoritative_captured_state,
        expected_captured_state_identity=expected_captured_state_identity,
        expected_captured_state_digest=expected_captured_state_digest,
        capture_observation_authority_set=capture_observation_authority_set,
        expected_capture_observation_authority_set_identity=(
            expected_capture_observation_authority_set_identity
        ),
        expected_capture_observation_authority_set_digest=(
            expected_capture_observation_authority_set_digest
        ),
        prepared_action_authority_set=prepared_action_authority_set,
        expected_prepared_action_authority_set_identity=(
            expected_prepared_action_authority_set_identity
        ),
        expected_prepared_action_authority_set_digest=(
            expected_prepared_action_authority_set_digest
        ),
        authoritative_plan_action_set=authoritative_plan_action_set,
        expected_candidate_identity=expected_candidate_identity,
        expected_implementation_manifest_digest=(
            expected_implementation_manifest_digest
        ),
        expected_plan_digest=expected_plan_digest,
    )
    diagnostics: list[Diagnostic] = list(checkpoint_diagnostics)
    if document["run_terminal_identity"] != _run_terminal_identity(document):
        diagnostics.append(
            _diagnostic(
                "RUN_TERMINAL_IDENTITY_INVALID",
                "$.run_terminal_record.run_terminal_identity",
                "The run-terminal identity does not match its canonical payload.",
            )
        )
    if document["run_terminal_digest"] != _run_terminal_digest(document):
        diagnostics.append(
            _diagnostic(
                "RUN_TERMINAL_DIGEST_INVALID",
                "$.run_terminal_record.run_terminal_digest",
                "The run-terminal digest does not match the complete record.",
            )
        )

    execution_binding = {
        "apply_authorization_identity": expected_apply_authorization_identity,
        "apply_authorization_digest": expected_apply_authorization_digest,
        "execution_domain_identity": expected_execution_domain_identity,
        "execution_nonce": expected_execution_nonce,
        "run_identity": expected_run_identity,
    }
    checkpoint_identity = (
        checkpoint_set_manifest.get("checkpoint_set_identity")
        if isinstance(checkpoint_set_manifest, Mapping)
        else None
    )
    checkpoint_digest = (
        checkpoint_set_manifest.get("checkpoint_set_digest")
        if isinstance(checkpoint_set_manifest, Mapping)
        else None
    )
    expected_fields = {
        "execution_binding": execution_binding,
        "plan_action_set_digest": expected_plan_action_set_digest,
        "checkpoint_set_identity": checkpoint_identity,
        "checkpoint_set_digest": checkpoint_digest,
        "checkpoint_store_generation": trusted_checkpoint_store_generation,
        "state": "succeeded",
    }
    if any(document[field] != value for field, value in expected_fields.items()):
        diagnostics.append(
            _diagnostic(
                "RUN_TERMINAL_BINDING_MISMATCH",
                "$.run_terminal_record",
                "The terminal record does not bind the exact validated apply, plan, checkpoint set, and store generation.",
            )
        )
    trusted_records = [_checkpoint_record(snapshot) for snapshot in trusted_snapshots]
    plan_action_index, plan_diagnostics = _validated_plan_action_index(
        authoritative_plan_action_set,
        expected_action_set_digest=expected_plan_action_set_digest,
        expected_candidate_identity=expected_candidate_identity,
        expected_implementation_manifest_digest=(
            expected_implementation_manifest_digest
        ),
        expected_plan_digest=expected_plan_digest,
    )
    diagnostics.extend(plan_diagnostics)
    terminal_checkpoint_keys = {
        (record.get("action_identity"), record.get("ordinal"))
        for record in trusted_records
        if record is not None
    }
    terminal_checkpoint_generations = [
        snapshot.get("durable_generation") if isinstance(snapshot, Mapping) else None
        for snapshot in trusted_snapshots
    ]
    if (
        any(
            record is None or record.get("phase") != "completed"
            for record in trusted_records
        )
        or terminal_checkpoint_keys != set(plan_action_index)
        or len(terminal_checkpoint_keys) != len(trusted_records)
        or any(
            type(generation) is not int
            for generation in terminal_checkpoint_generations
        )
        or terminal_checkpoint_generations
        != sorted(set(terminal_checkpoint_generations))
    ):
        diagnostics.append(
            _diagnostic(
                "RUN_TERMINAL_CHECKPOINT_STATE_MISMATCH",
                "$.trusted_checkpoint_store",
                "A successful run requires one completed trusted checkpoint for every action in the complete plan-action set, with durable generations increasing in action order.",
            )
        )
    return tuple(sorted(set(diagnostics)))


def _archived_apply_authorization_diagnostics(
    document: object,
    *,
    authoritative_plan_action_set: object,
    authoritative_captured_state: object,
    expected_apply_authorization_identity: str,
    expected_apply_authorization_digest: str,
    expected_execution_domain_identity: str,
    expected_execution_nonce: str,
    expected_run_identity: str,
    expected_plan_action_set_digest: str,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_plan_digest: str,
    expected_captured_state_identity: str,
    expected_captured_state_digest: str,
    expected_capture_observation_authority_set_identity: str,
    expected_capture_observation_authority_set_digest: str,
    expected_prepared_action_authority_set_identity: str,
    expected_prepared_action_authority_set_digest: str,
    authorized_expected_case_manifest_digest: str,
) -> tuple[Diagnostic, ...]:
    """Revalidate archived apply authority without reapplying its time gate.

    Release authenticates the complete historical record through the independently
    trusted canonical digest, then checks every execution and artifact binding it
    can derive from the other exact replay streams. Expiry is an apply-time gate,
    not a reason to make a completed run unreleasable later.
    """

    if not isinstance(document, Mapping):
        return (
            _diagnostic(
                "RELEASE_APPLY_AUTHORIZATION_MISMATCH",
                "$.apply_authorization_bytes",
                "The archived apply authorization is not one validated authority record.",
            ),
        )
    plan_actions = (
        authoritative_plan_action_set.get("actions")
        if isinstance(authoritative_plan_action_set, Mapping)
        else None
    )
    first_action = (
        plan_actions[0].get("action_payload")
        if isinstance(plan_actions, list)
        and plan_actions
        and isinstance(plan_actions[0], Mapping)
        else None
    )
    captured_bindings = (
        authoritative_captured_state.get("bindings")
        if isinstance(authoritative_captured_state, Mapping)
        else None
    )
    bindings = document.get("bindings")
    expected_execution_fields = {
        "authorization_identity": expected_apply_authorization_identity,
        "execution_domain_identity": expected_execution_domain_identity,
        "execution_nonce": expected_execution_nonce,
        "run_identity": expected_run_identity,
    }
    expected_binding_fields = {
        "candidate_identity": expected_candidate_identity,
        "implementation_manifest_digest": expected_implementation_manifest_digest,
        "catalog_digest": (
            first_action.get("catalog_digest")
            if isinstance(first_action, Mapping)
            else None
        ),
        "lock_digest": (
            first_action.get("lock_digest")
            if isinstance(first_action, Mapping)
            else None
        ),
        "plan_digest": expected_plan_digest,
        "plan_action_set_digest": expected_plan_action_set_digest,
        "prepared_action_authority_set_identity": (
            expected_prepared_action_authority_set_identity
        ),
        "prepared_action_authority_set_digest": (
            expected_prepared_action_authority_set_digest
        ),
        "capability_set_digest": (
            captured_bindings.get("capability_set_digest")
            if isinstance(captured_bindings, Mapping)
            else None
        ),
        "captured_state_identity": expected_captured_state_identity,
        "captured_state_digest": expected_captured_state_digest,
        "capture_observation_authority_set_identity": (
            expected_capture_observation_authority_set_identity
        ),
        "capture_observation_authority_set_digest": (
            expected_capture_observation_authority_set_digest
        ),
        "expected_case_manifest_digest": authorized_expected_case_manifest_digest,
    }
    valid = (
        document.get("authorization_identity") == _authorization_identity(document)
        and canonical_digest(document) == expected_apply_authorization_digest
        and all(
            document.get(field) == expected
            for field, expected in expected_execution_fields.items()
        )
        and isinstance(bindings, Mapping)
        and all(
            bindings.get(field) == expected
            for field, expected in expected_binding_fields.items()
        )
    )
    if valid:
        return ()
    return (
        _diagnostic(
            "RELEASE_APPLY_AUTHORIZATION_MISMATCH",
            "$.apply_authorization_bytes",
            "The archived apply authorization does not match the independently trusted execution tuple and exact replay artifacts.",
        ),
    )


def _release_acceptance_diagnostics(
    expected_case_manifest: object,
    evidence_bundle: object,
    attestation_manifest: object,
    *,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    authorized_expected_case_manifest_digest: str,
    authorized_attestation_manifest_digest: str,
    expected_apply_authorization_identity: str,
    expected_apply_authorization_digest: str,
    expected_execution_domain_identity: str,
    expected_execution_nonce: str,
    expected_run_identity: str,
) -> tuple[Diagnostic, ...]:
    if any(
        document is None
        for document in (
            expected_case_manifest,
            evidence_bundle,
            attestation_manifest,
        )
    ):
        return (
            _diagnostic(
                "RELEASE_ACCEPTANCE_EVIDENCE_INVALID",
                "$.release_evidence_bytes",
                "The exact expected-case, evidence-bundle, and attestation bytes are not bounded strict JSON.",
            ),
        )
    try:
        source_diagnostics = _validate_acceptance_evidence(
            evidence_bundle,
            expected_case_manifest,
            attestation_manifest,
            expected_candidate_identity=expected_candidate_identity,
            expected_implementation_manifest_digest=(
                expected_implementation_manifest_digest
            ),
            expected_case_manifest_digest=(authorized_expected_case_manifest_digest),
            expected_attestation_manifest_digest=(
                authorized_attestation_manifest_digest
            ),
            expected_apply_authorization_identity=(
                expected_apply_authorization_identity
            ),
            expected_apply_authorization_digest=expected_apply_authorization_digest,
            expected_execution_domain_identity=expected_execution_domain_identity,
            expected_execution_nonce=expected_execution_nonce,
            expected_run_identity=expected_run_identity,
        )
    except (RecursionError, TypeError, ValueError):
        return (
            _diagnostic(
                "RELEASE_ACCEPTANCE_EVIDENCE_INVALID",
                "$.release_evidence_bytes",
                "The exact acceptance tuple could not be validated safely.",
            ),
        )
    return tuple(
        _diagnostic(
            str(diagnostic.code),
            "$.release_evidence" + str(diagnostic.path).removeprefix("$"),
            str(diagnostic.message),
        )
        for diagnostic in source_diagnostics
    )


def _release_expected_case_replay_diagnostics(
    expected_case_manifest: object,
    authoritative_plan_action_set: object,
    authoritative_captured_state: object,
    *,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_plan_digest: str,
    expected_plan_action_set_digest: str,
    expected_captured_state_identity: str,
    expected_captured_state_digest: str,
) -> tuple[Diagnostic, ...]:
    """Cross-check expected-case claims derivable from exact replay streams."""

    actions = (
        authoritative_plan_action_set.get("actions")
        if isinstance(authoritative_plan_action_set, Mapping)
        else None
    )
    if not isinstance(actions, list):
        return ()
    first_action = (
        actions[0].get("action_payload")
        if actions and isinstance(actions[0], Mapping)
        else None
    )
    captured_bindings = (
        authoritative_captured_state.get("bindings")
        if isinstance(authoritative_captured_state, Mapping)
        else None
    )
    expected_bindings = {
        "candidate_identity": expected_candidate_identity,
        "implementation_manifest_digest": expected_implementation_manifest_digest,
        "catalog_digest": (
            first_action.get("catalog_digest")
            if isinstance(first_action, Mapping)
            else None
        ),
        "lock_digest": (
            first_action.get("lock_digest")
            if isinstance(first_action, Mapping)
            else None
        ),
        "plan_digest": expected_plan_digest,
        "plan_action_set_digest": expected_plan_action_set_digest,
        "capability_set_digest": (
            captured_bindings.get("capability_set_digest")
            if isinstance(captured_bindings, Mapping)
            else None
        ),
        "captured_state_identity": expected_captured_state_identity,
        "captured_state_digest": expected_captured_state_digest,
    }
    diagnostics: list[Diagnostic] = []
    if (
        not isinstance(expected_case_manifest, Mapping)
        or expected_case_manifest.get("bindings") != expected_bindings
    ):
        diagnostics.append(
            _diagnostic(
                "EXPECTED_CASE_MANIFEST_BINDING_MISMATCH",
                "$.release_evidence.bindings",
                "The expected-case manifest does not bind the exact trusted and replayed plan and capture tuple.",
            )
        )

    expected_action_identities: list[object] = []
    for evidence in actions:
        payload = (
            evidence.get("action_payload") if isinstance(evidence, Mapping) else None
        )
        if not isinstance(payload, Mapping):
            return tuple(diagnostics)
        expected_action_identities.append(payload.get("action_identity"))
    expected_action_identities.sort(key=str)

    if (
        not isinstance(expected_case_manifest, Mapping)
        or expected_case_manifest.get("plan_action_identities")
        != expected_action_identities
    ):
        diagnostics.append(
            _diagnostic(
                "EXPECTED_CASE_MANIFEST_PLAN_ACTION_SET_MISMATCH",
                "$.release_evidence.plan_action_identities",
                "The expected-case manifest does not name all and only the exact replayed plan actions.",
            )
        )

    plan_routes: dict[str, dict[str, object]] = {}
    route_projection_is_valid = True
    overlay_by_harness = {
        "claude": "claude_json",
        "codex": "codex_toml",
        "cursor": "cursor_json",
    }
    for evidence in actions:
        assert isinstance(evidence, Mapping)
        action = evidence["action_payload"]
        assert isinstance(action, Mapping)
        provider = action.get("provider")
        harness = action.get("harness")
        route_identity = action.get("route_identity")
        if (
            not isinstance(provider, Mapping)
            or not isinstance(harness, str)
            or not isinstance(route_identity, str)
        ):
            route_projection_is_valid = False
            continue
        provider_kind = provider.get("kind")
        if provider_kind == "standalone_skill":
            provider_selector: object = {
                "kind": "standalone_skill",
                "canonical_root": provider.get("canonical_root"),
            }
            manager_identity: object = "manager:standalone_skills"
        elif provider_kind == "native_plugin":
            manager = provider.get("manager")
            provider_selector = {
                "kind": "native_plugin",
                "manager": manager,
                "plugin_id": provider.get("plugin_id"),
                "scope": provider.get("scope"),
            }
            manager_identity = f"manager:{manager}"
        elif provider_kind == "direct_mcp":
            provider_selector = {
                "kind": "direct_mcp",
                "transport": provider.get("transport"),
                "overlay_family": overlay_by_harness.get(harness),
            }
            manager_identity = "manager:direct_mcp"
        else:
            route_projection_is_valid = False
            continue
        projection = {
            "route_identity": route_identity,
            "route_digest": action.get("route_digest"),
            "harness": harness,
            "provider_selector": provider_selector,
            "manager_identity": manager_identity,
            "capability_identity": action.get("capability_identity"),
            "capability_digest": action.get("capability_digest"),
            "manager_version_evidence_digest": action.get(
                "manager_version_evidence_digest"
            ),
        }
        existing_projection = plan_routes.get(route_identity)
        if existing_projection is not None and existing_projection != projection:
            route_projection_is_valid = False
        plan_routes[route_identity] = projection

    captured_routes = (
        authoritative_captured_state.get("provider_routes")
        if isinstance(authoritative_captured_state, Mapping)
        else None
    )
    captured_route_projections: dict[str, dict[str, object]] = {}
    if not isinstance(captured_routes, list):
        route_projection_is_valid = False
    else:
        for route in captured_routes:
            capability_binding = (
                route.get("capability_binding") if isinstance(route, Mapping) else None
            )
            route_identity = (
                route.get("route_id") if isinstance(route, Mapping) else None
            )
            if not isinstance(route_identity, str) or not isinstance(
                capability_binding, Mapping
            ):
                route_projection_is_valid = False
                continue
            if (
                route.get("control_owner") == "operator_owned"
                and route.get("planned_actions") == []
            ):
                continue
            captured_projection = {
                "route_digest": route.get("route_digest"),
                "harness": route.get("harness"),
                "capability_identity": capability_binding.get("capability_identity"),
                "capability_digest": capability_binding.get("capability_digest"),
                "manager_version_evidence_digest": capability_binding.get(
                    "manager_version_evidence_digest"
                ),
            }
            if route_identity in captured_route_projections:
                route_projection_is_valid = False
            captured_route_projections[route_identity] = captured_projection

    if set(captured_route_projections) != set(plan_routes):
        route_projection_is_valid = False
    for route_identity, projection in plan_routes.items():
        expected_captured_projection = {
            field: projection[field]
            for field in (
                "route_digest",
                "harness",
                "capability_identity",
                "capability_digest",
                "manager_version_evidence_digest",
            )
        }
        if (
            captured_route_projections.get(route_identity)
            != expected_captured_projection
        ):
            route_projection_is_valid = False

    expected_route_bindings = sorted(
        plan_routes.values(),
        key=lambda binding: str(binding["route_identity"]),
    )
    if (
        not route_projection_is_valid
        or not isinstance(expected_case_manifest, Mapping)
        or expected_case_manifest.get("route_capability_bindings")
        != expected_route_bindings
    ):
        diagnostics.append(
            _diagnostic(
                "EXPECTED_CASE_MANIFEST_ROUTE_BINDING_MISMATCH",
                "$.release_evidence.route_capability_bindings",
                "The expected-case manifest does not bind every exact replayed plan and captured-state route capability tuple.",
            )
        )
    return tuple(diagnostics)


def _release_evidence_diagnostics(
    *,
    apply_authorization_bytes: object,
    plan_action_set_bytes: object,
    captured_state_bytes: object,
    checkpoint_store_snapshot_bytes: object,
    checkpoint_set_manifest: object,
    checkpoint_set_manifest_bytes: object,
    capture_observation_authority_set_bytes: object,
    prepared_action_authority_set_bytes: object,
    run_terminal_record: object,
    run_terminal_record_bytes: object,
    expected_case_manifest_bytes: object,
    evidence_bundle_bytes: object,
    attestation_manifest_bytes: object,
    expected_apply_authorization_identity: str,
    expected_apply_authorization_digest: str,
    expected_execution_domain_identity: str,
    expected_execution_nonce: str,
    expected_run_identity: str,
    expected_plan_action_set_digest: str,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_plan_digest: str,
    expected_captured_state_identity: str,
    expected_captured_state_digest: str,
    capture_observation_authority_set: object,
    expected_capture_observation_authority_set_identity: str,
    expected_capture_observation_authority_set_digest: str,
    prepared_action_authority_set: object,
    expected_prepared_action_authority_set_identity: str,
    expected_prepared_action_authority_set_digest: str,
    authorized_expected_case_manifest_digest: str,
    authorized_attestation_manifest_digest: str,
) -> tuple[Diagnostic, ...]:
    apply_authorization: object | None = None
    apply_parse_diagnostics: tuple[Diagnostic, ...] = ()
    if type(apply_authorization_bytes) is bytes:
        apply_authorization, apply_parse_diagnostics = parse_execution_authority_bytes(
            apply_authorization_bytes
        )
    authoritative_plan_action_set = _parse_bounded_json_bytes(
        plan_action_set_bytes,
        maximum_bytes=MAX_PLAN_ACTION_SET_BYTES,
    )
    authoritative_captured_state = _parse_bounded_json_bytes(
        captured_state_bytes,
        maximum_bytes=MAX_CAPTURED_STATE_BYTES,
    )
    checkpoint_store_snapshot = _parse_bounded_json_bytes(
        checkpoint_store_snapshot_bytes,
        maximum_bytes=MAX_CHECKPOINT_STORE_SNAPSHOT_BYTES,
    )
    expected_case_manifest = _parse_bounded_json_bytes(
        expected_case_manifest_bytes,
        maximum_bytes=MAX_RELEASE_ACCEPTANCE_BYTES,
    )
    evidence_bundle = _parse_bounded_json_bytes(
        evidence_bundle_bytes,
        maximum_bytes=MAX_RELEASE_ACCEPTANCE_BYTES,
    )
    attestation_manifest = _parse_bounded_json_bytes(
        attestation_manifest_bytes,
        maximum_bytes=MAX_RELEASE_ACCEPTANCE_BYTES,
    )

    plan_diagnostics = (
        validate_plan_action_set(
            authoritative_plan_action_set,
            expected_action_set_digest=expected_plan_action_set_digest,
            expected_candidate_identity=expected_candidate_identity,
            expected_implementation_manifest_digest=(
                expected_implementation_manifest_digest
            ),
            expected_plan_digest=expected_plan_digest,
        )
        if _schema_valid(
            authoritative_plan_action_set,
            PLAN_ACTION_SET_SCHEMA_NAME,
            maximum_bytes=MAX_PLAN_ACTION_SET_BYTES,
        )
        else (
            _diagnostic(
                "PLAN_ACTION_SET_SCHEMA_INVALID",
                "$.authoritative_plan_action_set",
                "The exact plan-action-set bytes do not satisfy the checked-in closed schema and size bound.",
            ),
        )
    )
    if (
        isinstance(authoritative_plan_action_set, Mapping)
        and authoritative_plan_action_set.get("actions") == []
    ):
        plan_diagnostics = plan_diagnostics + (
            _diagnostic(
                "RELEASE_PLAN_ACTION_SET_EMPTY",
                "$.authoritative_plan_action_set.actions",
                "Release requires at least one authenticated plan action and completed checkpoint.",
            ),
        )
    captured_state_diagnostics: tuple[object, ...] = ()
    captured_state_is_valid = False
    if _schema_valid(
        authoritative_captured_state,
        CAPTURED_STATE_SCHEMA_NAME,
        maximum_bytes=MAX_CAPTURED_STATE_BYTES,
    ):
        try:
            captured_state_diagnostics = _validate_captured_state(
                authoritative_captured_state,
                authoritative_plan_action_set,
                expected_candidate_identity=expected_candidate_identity,
                expected_implementation_manifest_digest=(
                    expected_implementation_manifest_digest
                ),
            )
        except (RecursionError, TypeError, ValueError):
            pass
        else:
            captured_state_is_valid = not captured_state_diagnostics
    snapshot_diagnostics = validate_checkpoint_store_snapshot(
        checkpoint_store_snapshot,
        expected_apply_authorization_identity=expected_apply_authorization_identity,
        expected_apply_authorization_digest=expected_apply_authorization_digest,
        expected_execution_domain_identity=expected_execution_domain_identity,
        expected_execution_nonce=expected_execution_nonce,
        expected_run_identity=expected_run_identity,
        expected_plan_action_set_digest=expected_plan_action_set_digest,
    )
    trusted_checkpoint_store_generation = (
        checkpoint_store_snapshot.get("checkpoint_store_generation")
        if isinstance(checkpoint_store_snapshot, Mapping)
        and type(checkpoint_store_snapshot.get("checkpoint_store_generation")) is int
        else -1
    )
    trusted_checkpoint_records = (
        checkpoint_store_snapshot.get("checkpoints")
        if isinstance(checkpoint_store_snapshot, Mapping)
        and isinstance(checkpoint_store_snapshot.get("checkpoints"), list)
        else ()
    )

    apply_diagnostics = (
        apply_parse_diagnostics
        if apply_parse_diagnostics
        else _archived_apply_authorization_diagnostics(
            apply_authorization,
            authoritative_plan_action_set=authoritative_plan_action_set,
            authoritative_captured_state=authoritative_captured_state,
            expected_apply_authorization_identity=(
                expected_apply_authorization_identity
            ),
            expected_apply_authorization_digest=expected_apply_authorization_digest,
            expected_execution_domain_identity=expected_execution_domain_identity,
            expected_execution_nonce=expected_execution_nonce,
            expected_run_identity=expected_run_identity,
            expected_plan_action_set_digest=expected_plan_action_set_digest,
            expected_candidate_identity=expected_candidate_identity,
            expected_implementation_manifest_digest=(
                expected_implementation_manifest_digest
            ),
            expected_plan_digest=expected_plan_digest,
            expected_captured_state_identity=expected_captured_state_identity,
            expected_captured_state_digest=expected_captured_state_digest,
            expected_capture_observation_authority_set_identity=(
                expected_capture_observation_authority_set_identity
            ),
            expected_capture_observation_authority_set_digest=(
                expected_capture_observation_authority_set_digest
            ),
            expected_prepared_action_authority_set_identity=(
                expected_prepared_action_authority_set_identity
            ),
            expected_prepared_action_authority_set_digest=(
                expected_prepared_action_authority_set_digest
            ),
            authorized_expected_case_manifest_digest=(
                authorized_expected_case_manifest_digest
            ),
        )
    )
    acceptance_diagnostics = _release_acceptance_diagnostics(
        expected_case_manifest,
        evidence_bundle,
        attestation_manifest,
        expected_candidate_identity=expected_candidate_identity,
        expected_implementation_manifest_digest=(
            expected_implementation_manifest_digest
        ),
        authorized_expected_case_manifest_digest=(
            authorized_expected_case_manifest_digest
        ),
        authorized_attestation_manifest_digest=(authorized_attestation_manifest_digest),
        expected_apply_authorization_identity=expected_apply_authorization_identity,
        expected_apply_authorization_digest=expected_apply_authorization_digest,
        expected_execution_domain_identity=expected_execution_domain_identity,
        expected_execution_nonce=expected_execution_nonce,
        expected_run_identity=expected_run_identity,
    )
    expected_case_replay_diagnostics = _release_expected_case_replay_diagnostics(
        expected_case_manifest,
        authoritative_plan_action_set,
        authoritative_captured_state,
        expected_candidate_identity=expected_candidate_identity,
        expected_implementation_manifest_digest=(
            expected_implementation_manifest_digest
        ),
        expected_plan_digest=expected_plan_digest,
        expected_plan_action_set_digest=expected_plan_action_set_digest,
        expected_captured_state_identity=expected_captured_state_identity,
        expected_captured_state_digest=expected_captured_state_digest,
    )

    diagnostics = list(plan_diagnostics)
    diagnostics.extend(apply_diagnostics)
    diagnostics.extend(acceptance_diagnostics)
    diagnostics.extend(expected_case_replay_diagnostics)
    diagnostics.extend(snapshot_diagnostics)
    diagnostics.extend(
        validate_run_terminal_record(
            run_terminal_record,
            checkpoint_set_manifest=checkpoint_set_manifest,
            expected_apply_authorization_identity=(
                expected_apply_authorization_identity
            ),
            expected_apply_authorization_digest=expected_apply_authorization_digest,
            expected_execution_domain_identity=expected_execution_domain_identity,
            expected_execution_nonce=expected_execution_nonce,
            expected_run_identity=expected_run_identity,
            authoritative_plan_action_set=authoritative_plan_action_set,
            expected_plan_action_set_digest=expected_plan_action_set_digest,
            expected_candidate_identity=expected_candidate_identity,
            expected_implementation_manifest_digest=(
                expected_implementation_manifest_digest
            ),
            expected_plan_digest=expected_plan_digest,
            trusted_checkpoint_store_generation=(trusted_checkpoint_store_generation),
            trusted_checkpoint_records=trusted_checkpoint_records,
            authoritative_captured_state=authoritative_captured_state,
            expected_captured_state_identity=expected_captured_state_identity,
            expected_captured_state_digest=expected_captured_state_digest,
            capture_observation_authority_set=capture_observation_authority_set,
            expected_capture_observation_authority_set_identity=(
                expected_capture_observation_authority_set_identity
            ),
            expected_capture_observation_authority_set_digest=(
                expected_capture_observation_authority_set_digest
            ),
            prepared_action_authority_set=prepared_action_authority_set,
            expected_prepared_action_authority_set_identity=(
                expected_prepared_action_authority_set_identity
            ),
            expected_prepared_action_authority_set_digest=(
                expected_prepared_action_authority_set_digest
            ),
        )
    )
    if not captured_state_is_valid:
        diagnostics.append(
            _diagnostic(
                "CAPTURED_STATE_AUTHORITY_INVALID",
                "$.authoritative_captured_state",
                "The exact captured-state bytes are not valid for the exact plan-action set.",
            )
        )
    exact_replay_artifacts = (
        (
            "apply authorization",
            type(apply_authorization_bytes) is bytes
            and apply_authorization is not None
            and not apply_diagnostics,
        ),
        (
            "plan action set",
            type(plan_action_set_bytes) is bytes
            and authoritative_plan_action_set is not None
            and not plan_diagnostics,
        ),
        (
            "captured state",
            type(captured_state_bytes) is bytes
            and authoritative_captured_state is not None
            and captured_state_is_valid,
        ),
        (
            "checkpoint store snapshot",
            type(checkpoint_store_snapshot_bytes) is bytes
            and checkpoint_store_snapshot is not None
            and not snapshot_diagnostics,
        ),
        (
            "expected-case manifest",
            type(expected_case_manifest_bytes) is bytes
            and expected_case_manifest is not None
            and not acceptance_diagnostics,
        ),
        (
            "evidence bundle",
            type(evidence_bundle_bytes) is bytes
            and evidence_bundle is not None
            and not acceptance_diagnostics,
        ),
        (
            "attestation manifest",
            type(attestation_manifest_bytes) is bytes
            and attestation_manifest is not None
            and not acceptance_diagnostics,
        ),
    )
    for label, valid in exact_replay_artifacts:
        if not valid:
            diagnostics.append(
                _diagnostic(
                    "RELEASE_EVIDENCE_BYTES_MISMATCH",
                    "$.release_evidence_bytes",
                    f"The exact {label} bytes do not decode to valid replay authority.",
                )
            )
    for label, artifact, raw_bytes in (
        (
            "capture observation authority set",
            capture_observation_authority_set,
            capture_observation_authority_set_bytes,
        ),
        (
            "prepared action authority set",
            prepared_action_authority_set,
            prepared_action_authority_set_bytes,
        ),
        ("checkpoint set", checkpoint_set_manifest, checkpoint_set_manifest_bytes),
        ("run terminal", run_terminal_record, run_terminal_record_bytes),
    ):
        parsed: object | None = None
        parse_diagnostics: tuple[Diagnostic, ...] = ()
        if type(raw_bytes) is bytes:
            parsed, parse_diagnostics = parse_execution_authority_bytes(raw_bytes)
        if type(raw_bytes) is not bytes or parse_diagnostics or parsed != artifact:
            diagnostics.append(
                _diagnostic(
                    "RELEASE_EVIDENCE_BYTES_MISMATCH",
                    "$.release_evidence_bytes",
                    f"The exact {label} bytes do not decode to the validated artifact.",
                )
            )
    return tuple(sorted(set(diagnostics)))


def validate_release_archive_manifest(
    document: object,
    *,
    apply_authorization_bytes: bytes,
    plan_action_set_bytes: bytes,
    captured_state_bytes: bytes,
    checkpoint_store_snapshot_bytes: bytes,
    checkpoint_set_manifest: object,
    checkpoint_set_manifest_bytes: bytes,
    capture_observation_authority_set_bytes: bytes,
    prepared_action_authority_set_bytes: bytes,
    run_terminal_record: object,
    run_terminal_record_bytes: bytes,
    expected_case_manifest_bytes: bytes,
    evidence_bundle_bytes: bytes,
    attestation_manifest_bytes: bytes,
    expected_apply_authorization_identity: str,
    expected_apply_authorization_digest: str,
    expected_execution_domain_identity: str,
    expected_execution_nonce: str,
    expected_run_identity: str,
    expected_plan_action_set_digest: str,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_plan_digest: str,
    expected_captured_state_identity: str,
    expected_captured_state_digest: str,
    capture_observation_authority_set: object,
    expected_capture_observation_authority_set_identity: str,
    expected_capture_observation_authority_set_digest: str,
    prepared_action_authority_set: object,
    expected_prepared_action_authority_set_identity: str,
    expected_prepared_action_authority_set_digest: str,
    authorized_expected_case_manifest_digest: str,
    authorized_attestation_manifest_digest: str,
    expected_launcher_identity: str,
    expected_launcher_manifest_digest: str,
    expected_store_identity: str,
    expected_store_key: str,
) -> tuple[Diagnostic, ...]:
    """Validate one archive from independently trusted execution artifacts."""

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

    diagnostics = list(
        _release_evidence_diagnostics(
            apply_authorization_bytes=apply_authorization_bytes,
            plan_action_set_bytes=plan_action_set_bytes,
            captured_state_bytes=captured_state_bytes,
            checkpoint_store_snapshot_bytes=checkpoint_store_snapshot_bytes,
            checkpoint_set_manifest=checkpoint_set_manifest,
            checkpoint_set_manifest_bytes=checkpoint_set_manifest_bytes,
            capture_observation_authority_set_bytes=(
                capture_observation_authority_set_bytes
            ),
            prepared_action_authority_set_bytes=(prepared_action_authority_set_bytes),
            run_terminal_record=run_terminal_record,
            run_terminal_record_bytes=run_terminal_record_bytes,
            expected_case_manifest_bytes=expected_case_manifest_bytes,
            evidence_bundle_bytes=evidence_bundle_bytes,
            attestation_manifest_bytes=attestation_manifest_bytes,
            expected_apply_authorization_identity=(
                expected_apply_authorization_identity
            ),
            expected_apply_authorization_digest=expected_apply_authorization_digest,
            expected_execution_domain_identity=expected_execution_domain_identity,
            expected_execution_nonce=expected_execution_nonce,
            expected_run_identity=expected_run_identity,
            expected_plan_action_set_digest=expected_plan_action_set_digest,
            expected_candidate_identity=expected_candidate_identity,
            expected_implementation_manifest_digest=(
                expected_implementation_manifest_digest
            ),
            expected_plan_digest=expected_plan_digest,
            expected_captured_state_identity=expected_captured_state_identity,
            expected_captured_state_digest=expected_captured_state_digest,
            capture_observation_authority_set=capture_observation_authority_set,
            expected_capture_observation_authority_set_identity=(
                expected_capture_observation_authority_set_identity
            ),
            expected_capture_observation_authority_set_digest=(
                expected_capture_observation_authority_set_digest
            ),
            prepared_action_authority_set=prepared_action_authority_set,
            expected_prepared_action_authority_set_identity=(
                expected_prepared_action_authority_set_identity
            ),
            expected_prepared_action_authority_set_digest=(
                expected_prepared_action_authority_set_digest
            ),
            authorized_expected_case_manifest_digest=(
                authorized_expected_case_manifest_digest
            ),
            authorized_attestation_manifest_digest=(
                authorized_attestation_manifest_digest
            ),
        )
    )
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

    execution_binding = {
        "apply_authorization_identity": expected_apply_authorization_identity,
        "apply_authorization_digest": expected_apply_authorization_digest,
        "execution_domain_identity": expected_execution_domain_identity,
        "execution_nonce": expected_execution_nonce,
        "run_identity": expected_run_identity,
    }
    evidence_fields = {
        "candidate_identity": expected_candidate_identity,
        "implementation_manifest_digest": expected_implementation_manifest_digest,
        "execution_binding": execution_binding,
        "plan_action_set_digest": expected_plan_action_set_digest,
        "checkpoint_set_identity": (
            checkpoint_set_manifest.get("checkpoint_set_identity")
            if isinstance(checkpoint_set_manifest, Mapping)
            else None
        ),
        "checkpoint_set_digest": (
            checkpoint_set_manifest.get("checkpoint_set_digest")
            if isinstance(checkpoint_set_manifest, Mapping)
            else None
        ),
        "run_terminal_identity": (
            run_terminal_record.get("run_terminal_identity")
            if isinstance(run_terminal_record, Mapping)
            else None
        ),
        "run_terminal_digest": (
            run_terminal_record.get("run_terminal_digest")
            if isinstance(run_terminal_record, Mapping)
            else None
        ),
        "launcher_identity": expected_launcher_identity,
        "launcher_manifest_digest": expected_launcher_manifest_digest,
    }
    if any(payload[field] != expected for field, expected in evidence_fields.items()):
        diagnostics.append(
            _diagnostic(
                "RELEASE_ARCHIVE_AUTHORITY_MISMATCH",
                "$.payload",
                "The archive manifest does not match the trusted candidate, execution evidence, and launcher authority.",
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
    computed_byte_digests: dict[str, str] = {}
    for field, raw_bytes, maximum_bytes in (
        (
            "apply_authorization_bytes_digest",
            apply_authorization_bytes,
            MAX_EXECUTION_AUTHORITY_BYTES,
        ),
        (
            "plan_action_set_bytes_digest",
            plan_action_set_bytes,
            MAX_PLAN_ACTION_SET_BYTES,
        ),
        (
            "captured_state_bytes_digest",
            captured_state_bytes,
            MAX_CAPTURED_STATE_BYTES,
        ),
        (
            "capture_observation_authority_set_bytes_digest",
            capture_observation_authority_set_bytes,
            MAX_EXECUTION_AUTHORITY_BYTES,
        ),
        (
            "prepared_action_authority_set_bytes_digest",
            prepared_action_authority_set_bytes,
            MAX_EXECUTION_AUTHORITY_BYTES,
        ),
        (
            "checkpoint_set_manifest_bytes_digest",
            checkpoint_set_manifest_bytes,
            MAX_EXECUTION_AUTHORITY_BYTES,
        ),
        (
            "checkpoint_store_snapshot_bytes_digest",
            checkpoint_store_snapshot_bytes,
            MAX_CHECKPOINT_STORE_SNAPSHOT_BYTES,
        ),
        (
            "run_terminal_record_bytes_digest",
            run_terminal_record_bytes,
            MAX_EXECUTION_AUTHORITY_BYTES,
        ),
        (
            "expected_case_manifest_bytes_digest",
            expected_case_manifest_bytes,
            MAX_RELEASE_ACCEPTANCE_BYTES,
        ),
        (
            "evidence_bundle_bytes_digest",
            evidence_bundle_bytes,
            MAX_RELEASE_ACCEPTANCE_BYTES,
        ),
        (
            "attestation_manifest_bytes_digest",
            attestation_manifest_bytes,
            MAX_RELEASE_ACCEPTANCE_BYTES,
        ),
    ):
        if (
            _parse_bounded_json_bytes(raw_bytes, maximum_bytes=maximum_bytes)
            is not None
        ):
            assert isinstance(raw_bytes, bytes)
            computed_byte_digests[field] = _bytes_digest(raw_bytes)
    if archived_digests != computed_byte_digests:
        diagnostics.append(
            _diagnostic(
                "ARCHIVED_DOCUMENT_BYTES_MISMATCH",
                "$.payload.archived_document_byte_digests",
                "The archive manifest does not bind the exact independently supplied document bytes.",
            )
        )
    return tuple(sorted(set(diagnostics)))


def validate_release_receipt(
    document: object,
    *,
    release_archive_manifest: object,
    apply_authorization_bytes: bytes,
    plan_action_set_bytes: bytes,
    captured_state_bytes: bytes,
    checkpoint_store_snapshot_bytes: bytes,
    checkpoint_set_manifest: object,
    checkpoint_set_manifest_bytes: bytes,
    capture_observation_authority_set_bytes: bytes,
    prepared_action_authority_set_bytes: bytes,
    run_terminal_record: object,
    run_terminal_record_bytes: bytes,
    expected_case_manifest_bytes: bytes,
    evidence_bundle_bytes: bytes,
    attestation_manifest_bytes: bytes,
    expected_apply_authorization_identity: str,
    expected_apply_authorization_digest: str,
    expected_execution_domain_identity: str,
    expected_execution_nonce: str,
    expected_run_identity: str,
    expected_plan_action_set_digest: str,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_plan_digest: str,
    expected_captured_state_identity: str,
    expected_captured_state_digest: str,
    capture_observation_authority_set: object,
    expected_capture_observation_authority_set_identity: str,
    expected_capture_observation_authority_set_digest: str,
    prepared_action_authority_set: object,
    expected_prepared_action_authority_set_identity: str,
    expected_prepared_action_authority_set_digest: str,
    authorized_expected_case_manifest_digest: str,
    authorized_attestation_manifest_digest: str,
    expected_launcher_identity: str,
    expected_launcher_manifest_digest: str,
    expected_store_identity: str,
    expected_store_key: str,
) -> tuple[Diagnostic, ...]:
    """Validate a receipt by revalidating its exact archived execution evidence."""

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

    archive_diagnostics = validate_release_archive_manifest(
        release_archive_manifest,
        apply_authorization_bytes=apply_authorization_bytes,
        plan_action_set_bytes=plan_action_set_bytes,
        captured_state_bytes=captured_state_bytes,
        checkpoint_store_snapshot_bytes=checkpoint_store_snapshot_bytes,
        checkpoint_set_manifest=checkpoint_set_manifest,
        checkpoint_set_manifest_bytes=checkpoint_set_manifest_bytes,
        capture_observation_authority_set_bytes=(
            capture_observation_authority_set_bytes
        ),
        prepared_action_authority_set_bytes=prepared_action_authority_set_bytes,
        run_terminal_record=run_terminal_record,
        run_terminal_record_bytes=run_terminal_record_bytes,
        expected_case_manifest_bytes=expected_case_manifest_bytes,
        evidence_bundle_bytes=evidence_bundle_bytes,
        attestation_manifest_bytes=attestation_manifest_bytes,
        expected_apply_authorization_identity=expected_apply_authorization_identity,
        expected_apply_authorization_digest=expected_apply_authorization_digest,
        expected_execution_domain_identity=expected_execution_domain_identity,
        expected_execution_nonce=expected_execution_nonce,
        expected_run_identity=expected_run_identity,
        expected_plan_action_set_digest=expected_plan_action_set_digest,
        expected_candidate_identity=expected_candidate_identity,
        expected_implementation_manifest_digest=(
            expected_implementation_manifest_digest
        ),
        expected_plan_digest=expected_plan_digest,
        expected_captured_state_identity=expected_captured_state_identity,
        expected_captured_state_digest=expected_captured_state_digest,
        capture_observation_authority_set=capture_observation_authority_set,
        expected_capture_observation_authority_set_identity=(
            expected_capture_observation_authority_set_identity
        ),
        expected_capture_observation_authority_set_digest=(
            expected_capture_observation_authority_set_digest
        ),
        prepared_action_authority_set=prepared_action_authority_set,
        expected_prepared_action_authority_set_identity=(
            expected_prepared_action_authority_set_identity
        ),
        expected_prepared_action_authority_set_digest=(
            expected_prepared_action_authority_set_digest
        ),
        authorized_expected_case_manifest_digest=(
            authorized_expected_case_manifest_digest
        ),
        authorized_attestation_manifest_digest=(authorized_attestation_manifest_digest),
        expected_launcher_identity=expected_launcher_identity,
        expected_launcher_manifest_digest=expected_launcher_manifest_digest,
        expected_store_identity=expected_store_identity,
        expected_store_key=expected_store_key,
    )
    diagnostics: list[Diagnostic] = list(archive_diagnostics)
    payload = document["payload"]
    assert isinstance(payload, Mapping)
    archive_payload = (
        release_archive_manifest.get("payload")
        if isinstance(release_archive_manifest, Mapping)
        else None
    )
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
        "execution_binding": (
            archive_payload.get("execution_binding")
            if isinstance(archive_payload, Mapping)
            else None
        ),
        "plan_action_set_digest": expected_plan_action_set_digest,
        "checkpoint_set_identity": (
            checkpoint_set_manifest.get("checkpoint_set_identity")
            if isinstance(checkpoint_set_manifest, Mapping)
            else None
        ),
        "checkpoint_set_digest": (
            checkpoint_set_manifest.get("checkpoint_set_digest")
            if isinstance(checkpoint_set_manifest, Mapping)
            else None
        ),
        "run_terminal_identity": (
            run_terminal_record.get("run_terminal_identity")
            if isinstance(run_terminal_record, Mapping)
            else None
        ),
        "run_terminal_digest": (
            run_terminal_record.get("run_terminal_digest")
            if isinstance(run_terminal_record, Mapping)
            else None
        ),
        "launcher_identity": expected_launcher_identity,
        "launcher_manifest_digest": expected_launcher_manifest_digest,
        "archive_identity": (
            release_archive_manifest.get("archive_identity")
            if isinstance(release_archive_manifest, Mapping)
            else None
        ),
        "archive_manifest_digest": (
            release_archive_manifest.get("archive_manifest_digest")
            if isinstance(release_archive_manifest, Mapping)
            else None
        ),
    }
    if any(payload[field] != expected for field, expected in expected_fields.items()):
        diagnostics.append(
            _diagnostic(
                "RELEASE_RECEIPT_AUTHORITY_MISMATCH",
                "$.payload",
                "The release receipt does not match the revalidated archive and execution evidence.",
            )
        )
    destination = payload["archive_destination"]
    assert isinstance(destination, Mapping)
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
    return tuple(sorted(set(diagnostics)))


__all__ = (
    "CAPTURED_STATE_SCHEMA_NAME",
    "MAX_CAPTURED_STATE_BYTES",
    "MAX_CHECKPOINT_STORE_SNAPSHOT_BYTES",
    "MAX_EXECUTION_AUTHORITY_BYTES",
    "MAX_PLAN_ACTION_SET_BYTES",
    "MAX_RELEASE_ACCEPTANCE_BYTES",
    "Diagnostic",
    "authorization_ledger_claim_identity",
    "canonical_digest",
    "checkpoint_identity",
    "compensation_ledger_claim_identity",
    "parse_execution_authority_bytes",
    "validate_apply_authorization",
    "validate_capture_observation_authority_set",
    "validate_checkpoint_set_manifest",
    "validate_checkpoint_store_snapshot",
    "validate_compensation_authorization",
    "validate_plan_action_set",
    "validate_prepared_action_authority_set",
    "validate_public_compensation_recovery",
    "validate_release_archive_manifest",
    "validate_release_receipt",
    "validate_run_terminal_record",
)
