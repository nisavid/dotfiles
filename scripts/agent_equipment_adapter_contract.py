"""Pure semantic validation for one adapter-contract record sequence.

Canonical digests are recomputed for every payload embedded in the sequence,
including each RuntimeObservation normalized state payload.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

JsonObject = Mapping[str, Any]
MUTATING_OPERATIONS = frozenset(
    {
        "install",
        "configure",
        "enable",
        "disable",
        "remove",
        "restore",
        "suppress_native_update",
    }
)


@dataclass(frozen=True, order=True)
class Diagnostic:
    code: str
    path: str
    message: str


def canonical_json_sha256(document: Any) -> str:
    payload = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def plan_action_identity(action: JsonObject) -> str:
    """Derive the plan-action v1 identity from its execution coordinates."""

    identity_payload = {
        "plan_digest": action.get("plan_digest"),
        "ordinal": action.get("ordinal"),
        "route_id": action.get("route_identity"),
        "operation": action.get("operation"),
        "desired_state_digest": action.get("desired_state_digest"),
    }
    return f"action:{canonical_json_sha256(identity_payload)}"


def validate_sequence(
    document: JsonObject,
    *,
    trusted_candidate_identity: str,
    trusted_implementation_manifest_digest: str,
) -> tuple[Diagnostic, ...]:
    """Validate one closed ApplySequence against the installed implementation."""

    diagnostics: list[Diagnostic] = []
    unpacked = _apply_sequence(document, diagnostics)
    if unpacked is None:
        return tuple(sorted(set(diagnostics)))
    (
        authority,
        capability_discovery,
        pre_request_document,
        pre_observation_document,
        action_document,
        receipt_document,
        post_request_document,
        post_observation_document,
    ) = unpacked
    pre_request = _record(pre_request_document, "ObserveRequest", diagnostics)
    pre_observation = _record(
        pre_observation_document, "RuntimeObservation", diagnostics
    )
    action = _record(action_document, "PlannedAction", diagnostics)
    receipt = _record(receipt_document, "MutationReceipt", diagnostics)
    post_request = _record(post_request_document, "ObserveRequest", diagnostics)
    post_observation = _record(
        post_observation_document, "RuntimeObservation", diagnostics
    )
    requested_capability_identity = (
        authority.get("capability_identity") if isinstance(authority, dict) else None
    )
    capability = _capability_record(
        capability_discovery,
        requested_capability_identity,
        diagnostics,
    )
    records = (
        authority,
        capability,
        pre_request,
        pre_observation,
        action,
        receipt,
        post_request,
        post_observation,
    )
    if any(record is None for record in records):
        return tuple(sorted(set(diagnostics)))

    assert authority is not None
    assert capability is not None
    assert pre_request is not None
    assert pre_observation is not None
    assert action is not None
    assert receipt is not None
    assert post_request is not None
    assert post_observation is not None

    _expect_equal(
        diagnostics,
        "TRUSTED_CANDIDATE_MISMATCH",
        "ApplySequence.sequence.authority.candidate_identity",
        authority.get("candidate_identity"),
        trusted_candidate_identity,
    )
    _expect_equal(
        diagnostics,
        "TRUSTED_IMPLEMENTATION_MANIFEST_MISMATCH",
        "ApplySequence.sequence.authority.implementation_manifest_digest",
        authority.get("implementation_manifest_digest"),
        trusted_implementation_manifest_digest,
    )

    _validate_canonical_capability(diagnostics, capability)
    for label, record in (
        ("PreStateRequest", pre_request),
        ("PlannedAction", action),
        ("PostStateRequest", post_request),
    ):
        _validate_route_binding(diagnostics, label, capability, record)
        _validate_surface_scope(diagnostics, label, capability, record)

    _validate_action_authorization(diagnostics, capability, action)
    _validate_desired_state(diagnostics, capability, action)
    _expect_equal(
        diagnostics,
        "ACTION_IDENTITY_MISMATCH",
        "PlannedAction.record.action_identity",
        action.get("action_identity"),
        plan_action_identity(action),
    )
    _validate_capability_echoes(
        diagnostics,
        capability,
        (
            ("PreStateRequest", pre_request),
            ("PreStateObservation", pre_observation),
            ("PlannedAction", action),
            ("MutationReceipt", receipt),
            ("PostStateRequest", post_request),
            ("PostStateObservation", post_observation),
        ),
    )
    phase = authority.get("phase")
    expected_pre_purpose = "capture_pre_state" if phase == "apply" else "recovery"
    expected_pre_request_digest = (
        None if phase == "apply" else authority.get("expected_pre_state_digest")
    )
    _validate_request_observation(
        diagnostics,
        "PreState",
        capability,
        pre_request,
        pre_observation,
        expected_purpose=expected_pre_purpose,
        expected_state_digest=expected_pre_request_digest,
        captured_state_required=True,
    )
    expected_verified_state = authority.get("expected_post_state_digest")
    expected_verify_purpose = (
        "verify_post_state" if phase == "apply" else "verify_compensation"
    )
    _validate_request_observation(
        diagnostics,
        "PostState",
        capability,
        post_request,
        post_observation,
        expected_purpose=expected_verify_purpose,
        expected_state_digest=expected_verified_state,
        captured_state_required=False,
    )
    if phase == "apply":
        _validate_verified_state_fragment(diagnostics, action, post_observation)
    else:
        _validate_verified_state_fragment(diagnostics, action, pre_observation)
    _validate_action_echoes(diagnostics, pre_request, action)
    _validate_action_preconditions(diagnostics, action)
    _validate_receipt_echoes(diagnostics, action, receipt)
    _validate_apply_authority(
        diagnostics,
        authority,
        pre_request,
        pre_observation,
        action,
        receipt,
        post_request,
        post_observation,
    )
    _expect_not_equal(
        diagnostics,
        "REQUEST_IDENTITY_REUSE",
        "ApplySequence.sequence.post_state_request.record.request_identity",
        post_request.get("request_identity"),
        pre_request.get("request_identity"),
    )
    _validate_receipt_result(diagnostics, authority, receipt)
    _validate_sequence_timestamps(
        diagnostics, pre_observation, receipt, post_observation
    )

    return tuple(sorted(set(diagnostics)))


def _apply_sequence(
    document: JsonObject,
    diagnostics: list[Diagnostic],
) -> (
    tuple[
        JsonObject,
        JsonObject,
        JsonObject,
        JsonObject,
        JsonObject,
        JsonObject,
        JsonObject,
        JsonObject,
    ]
    | None
):
    expected_keys = {
        "authority",
        "capability_discovery",
        "pre_state_request",
        "pre_state_observation",
        "planned_action",
        "mutation_receipt",
        "post_state_request",
        "post_state_observation",
    }
    sequence = document.get("sequence")
    if (
        document.get("record_type") != "ApplySequence"
        or not isinstance(sequence, dict)
        or set(sequence) != expected_keys
        or not all(isinstance(sequence[key], dict) for key in expected_keys)
    ):
        diagnostics.append(
            Diagnostic(
                "APPLY_SEQUENCE_INVALID",
                "ApplySequence",
                "Mutation authority requires one complete, closed ApplySequence.",
            )
        )
        return None
    authority = sequence["authority"]
    return (
        authority,
        sequence["capability_discovery"],
        sequence["pre_state_request"],
        sequence["pre_state_observation"],
        sequence["planned_action"],
        sequence["mutation_receipt"],
        sequence["post_state_request"],
        sequence["post_state_observation"],
    )


def _validate_canonical_capability(
    diagnostics: list[Diagnostic],
    capability: JsonObject,
) -> None:
    manager_evidence = capability.get("manager_version_evidence")
    if isinstance(manager_evidence, dict):
        evidence_without_digest = deepcopy(manager_evidence)
        evidence_digest = evidence_without_digest.pop("evidence_digest", None)
        _expect_equal(
            diagnostics,
            "CANONICAL_DIGEST_MISMATCH",
            "CapabilityDiscovery.result.records[].manager_version_evidence.evidence_digest",
            evidence_digest,
            canonical_json_sha256(evidence_without_digest),
        )
        provider_match = capability.get("provider_match")
        expected_manager = _manager_for_provider(provider_match)
        _expect_equal(
            diagnostics,
            "PROVIDER_MANAGER_MISMATCH",
            "CapabilityDiscovery.result.records[].manager_version_evidence.manager",
            manager_evidence.get("manager"),
            expected_manager,
        )
    capability_without_digest = deepcopy(capability)
    capability_digest = capability_without_digest.pop("capability_digest", None)
    _expect_equal(
        diagnostics,
        "CANONICAL_DIGEST_MISMATCH",
        "CapabilityDiscovery.result.records[].capability_digest",
        capability_digest,
        canonical_json_sha256(capability_without_digest),
    )


def _validate_route_binding(
    diagnostics: list[Diagnostic],
    label: str,
    capability: JsonObject,
    record: JsonObject,
) -> None:
    route_record = record.get("route_record")
    if not isinstance(route_record, dict):
        diagnostics.append(
            Diagnostic(
                "ROUTE_BINDING_MISMATCH",
                f"{label}.record.route_record",
                "The complete selected route is required.",
            )
        )
        return
    _expect_equal(
        diagnostics,
        "CANONICAL_DIGEST_MISMATCH",
        f"{label}.record.route_digest",
        record.get("route_digest"),
        canonical_json_sha256(route_record),
    )
    for field, route_field in (
        ("route_identity", "identity"),
        ("activation_group", "activation_group"),
        ("secret_references", "secret_references"),
    ):
        _expect_equal(
            diagnostics,
            "ROUTE_BINDING_MISMATCH",
            f"{label}.record.{field}",
            record.get(field),
            route_record.get(route_field),
        )
    route_controls = route_record.get("component_controls")
    controlled_identities = (
        sorted(
            control.get("equipment_identity")
            for control in route_controls
            if isinstance(control, dict)
        )
        if isinstance(route_controls, list)
        else None
    )
    _expect_equal(
        diagnostics,
        "ROUTE_BINDING_MISMATCH",
        f"{label}.record.controlled_equipment_identities",
        record.get("controlled_equipment_identities"),
        controlled_identities,
    )
    active_identities = record.get("equipment_identities")
    _expect_equal(
        diagnostics,
        "ROUTE_BINDING_MISMATCH",
        f"{label}.record.equipment_identities",
        active_identities,
        sorted(active_identities) if isinstance(active_identities, list) else None,
    )
    native_manager = _native_provider_manager(route_record)
    if native_manager is not None:
        _expect_equal(
            diagnostics,
            "ROUTE_BINDING_MISMATCH",
            f"{label}.record.harness",
            record.get("harness"),
            native_manager,
        )
    if not _provider_selector_matches(
        capability.get("provider_match"),
        route_record.get("provider"),
        record.get("harness"),
    ):
        diagnostics.append(
            Diagnostic(
                "CAPABILITY_ROUTE_MISMATCH",
                f"{label}.record.route_record.provider",
                "The route provider does not match the selected capability provider.",
            )
        )


def _validate_desired_state(
    diagnostics: list[Diagnostic],
    capability: JsonObject,
    action: JsonObject,
) -> None:
    desired_state = action.get("desired_state")
    if not isinstance(desired_state, dict):
        return
    _expect_equal(
        diagnostics,
        "CANONICAL_DIGEST_MISMATCH",
        "PlannedAction.record.desired_state_digest",
        action.get("desired_state_digest"),
        canonical_json_sha256(desired_state),
    )
    _validate_unique_component_identities(
        diagnostics,
        "PlannedAction.record.desired_state.component_states",
        desired_state.get("component_states"),
    )
    _validate_desired_component_controls(
        diagnostics,
        capability,
        action,
        desired_state.get("component_states"),
    )


def _validate_capability_echoes(
    diagnostics: list[Diagnostic],
    capability: JsonObject,
    records: tuple[tuple[str, JsonObject], ...],
) -> None:
    manager_evidence = capability.get("manager_version_evidence")
    manager_digest = (
        manager_evidence.get("evidence_digest")
        if isinstance(manager_evidence, dict)
        else None
    )
    for label, record in records:
        _echo(
            diagnostics,
            label,
            record,
            capability,
            ("capability_identity", "capability_digest", "harness"),
        )
        _expect_equal(
            diagnostics,
            "ECHO_BINDING_MISMATCH",
            f"{label}.record.manager_version_evidence_digest",
            record.get("manager_version_evidence_digest"),
            manager_digest,
        )
    for label, record in records:
        if label in {"PlannedAction", "MutationReceipt"}:
            _echo(
                diagnostics,
                label,
                record,
                capability,
                ("adapter_identity", "adapter_version"),
            )


def _validate_request_observation(
    diagnostics: list[Diagnostic],
    label: str,
    capability: JsonObject,
    request: JsonObject,
    observation: JsonObject,
    *,
    expected_purpose: str,
    expected_state_digest: Any,
    captured_state_required: bool,
) -> None:
    _expect_equal(
        diagnostics,
        "COMMAND_BOUNDARY_MISMATCH",
        f"{label}Request.record.command",
        request.get("command"),
        "apply",
    )
    _expect_equal(
        diagnostics,
        "COMMAND_BOUNDARY_MISMATCH",
        f"{label}Request.record.purpose",
        request.get("purpose"),
        expected_purpose,
    )
    _expect_equal(
        diagnostics,
        "VERIFICATION_STATE_MISMATCH",
        f"{label}Request.record.expected_state_digest",
        request.get("expected_state_digest"),
        expected_state_digest,
    )
    _echo(
        diagnostics,
        f"{label}Observation",
        observation,
        request,
        (
            "request_identity",
            "correlation_identity",
            "candidate_identity",
            "implementation_manifest_digest",
            "catalog_digest",
            "lock_digest",
            "plan_digest",
            "capability_identity",
            "capability_digest",
            "manager_version_evidence_digest",
            "harness",
            "route_identity",
            "route_digest",
            "equipment_identities",
            "controlled_equipment_identities",
            "activation_group",
            "surface_scope",
        ),
    )
    _expect_equal(
        diagnostics,
        "ECHO_BINDING_MISMATCH",
        f"{label}Observation.record.control_owner",
        observation.get("control_owner"),
        _nested(request, "route_record", "control_owner"),
    )
    result = observation.get("result")
    if not isinstance(result, dict) or result.get("status") != "ok":
        diagnostics.append(
            Diagnostic(
                "OBSERVATION_NOT_SUCCESSFUL",
                f"{label}Observation.record.result",
                "Apply authority requires a successful observation.",
            )
        )
        return
    normalized_state = result.get("normalized_state")
    if not isinstance(normalized_state, dict):
        diagnostics.append(
            Diagnostic(
                "NORMALIZED_STATE_INVALID",
                f"{label}Observation.record.result.normalized_state",
                "A successful observation requires one closed normalized state payload.",
            )
        )
        return
    _expect_equal(
        diagnostics,
        "CANONICAL_STATE_DIGEST_MISMATCH",
        f"{label}Observation.record.result.state_digest",
        result.get("state_digest"),
        canonical_json_sha256(normalized_state),
    )
    _validate_unique_component_identities(
        diagnostics,
        f"{label}Observation.record.result.normalized_state.component_states",
        normalized_state.get("component_states"),
    )
    component_identities = _component_identities(
        normalized_state.get("component_states")
    )
    _expect_equal(
        diagnostics,
        "OBSERVATION_COVERAGE_MISMATCH",
        f"{label}Observation.record.result.normalized_state.component_states",
        component_identities,
        request.get("controlled_equipment_identities"),
    )
    evidence_identities = _evidence_identities(result.get("surface_evidence"))
    _expect_equal(
        diagnostics,
        "OBSERVATION_COVERAGE_MISMATCH",
        f"{label}Observation.record.result.surface_evidence",
        evidence_identities,
        request.get("surface_scope"),
    )
    _validate_evidence_kinds(
        diagnostics,
        "OBSERVATION_EVIDENCE_KIND_MISMATCH",
        f"{label}Observation.record.result.surface_evidence",
        result.get("surface_evidence"),
        frozenset({"manager", "surface"}),
    )
    route_control = _nested3(
        request, "route_record", "restore", "native_update_control"
    )
    capability_control = _nested(
        capability, "native_update_support", "native_update_control"
    )
    _expect_equal(
        diagnostics,
        "NATIVE_UPDATE_CLASSIFICATION_MISMATCH",
        f"{label}Observation.record.result.normalized_state.native_update_control",
        normalized_state.get("native_update_control"),
        route_control,
    )
    _expect_equal(
        diagnostics,
        "NATIVE_UPDATE_CLASSIFICATION_MISMATCH",
        "CapabilityDiscovery.result.records[].native_update_support.native_update_control",
        capability_control,
        route_control,
    )
    captured_state = result.get("captured_state")
    expected_capture_status = (
        "captured" if captured_state_required else "not_applicable"
    )
    _expect_equal(
        diagnostics,
        "CAPTURE_BINDING_MISMATCH",
        f"{label}Observation.record.result.captured_state.status",
        captured_state.get("status") if isinstance(captured_state, dict) else None,
        expected_capture_status,
    )
    if expected_state_digest is not None:
        _expect_equal(
            diagnostics,
            "VERIFICATION_STATE_MISMATCH",
            f"{label}Observation.record.result.state_digest",
            result.get("state_digest"),
            expected_state_digest,
        )


def _validate_action_echoes(
    diagnostics: list[Diagnostic],
    request: JsonObject,
    action: JsonObject,
) -> None:
    _echo(
        diagnostics,
        "PlannedAction",
        action,
        request,
        (
            "correlation_identity",
            "candidate_identity",
            "implementation_manifest_digest",
            "catalog_digest",
            "lock_digest",
            "plan_digest",
            "capability_identity",
            "capability_digest",
            "manager_version_evidence_digest",
            "harness",
            "route_identity",
            "route_digest",
            "route_record",
            "equipment_identities",
            "controlled_equipment_identities",
            "activation_group",
            "surface_scope",
            "secret_references",
        ),
    )


def _validate_verified_state_fragment(
    diagnostics: list[Diagnostic],
    action: JsonObject,
    observation: JsonObject,
) -> None:
    desired_state = action.get("desired_state")
    result = observation.get("result")
    if not isinstance(desired_state, dict) or not isinstance(result, dict):
        return
    normalized_state = result.get("normalized_state")
    if not isinstance(normalized_state, dict):
        return

    for field in ("route_presence", "enablement", "native_update_suppression_state"):
        if field in desired_state:
            _expect_equal(
                diagnostics,
                "VERIFIED_STATE_FRAGMENT_MISMATCH",
                f"PostStateObservation.record.result.{field}",
                normalized_state.get(field),
                desired_state.get(field),
            )

    desired_configuration = desired_state.get("configuration")
    observed_configuration = normalized_state.get("configuration")
    if isinstance(desired_configuration, dict):
        expected_configuration = deepcopy(desired_configuration)
        if expected_configuration.get("status") == "desired":
            expected_configuration["status"] = "observed"
        _expect_equal(
            diagnostics,
            "VERIFIED_STATE_FRAGMENT_MISMATCH",
            "PostStateObservation.record.result.configuration",
            observed_configuration,
            expected_configuration,
        )

    desired_components = _component_state_map(desired_state.get("component_states"))
    observed_components = _component_state_map(normalized_state.get("component_states"))
    if desired_components is not None and isinstance(observed_components, dict):
        for identity, state in desired_components.items():
            _expect_equal(
                diagnostics,
                "VERIFIED_STATE_FRAGMENT_MISMATCH",
                (f"PostStateObservation.record.result.component_states[{identity}]"),
                observed_components.get(identity),
                state,
            )


def _validate_action_preconditions(
    diagnostics: list[Diagnostic],
    action: JsonObject,
) -> None:
    preconditions = action.get("preconditions")
    if not isinstance(preconditions, dict):
        return
    for field in (
        "candidate_identity",
        "implementation_manifest_digest",
        "catalog_digest",
        "lock_digest",
        "plan_digest",
        "route_digest",
        "capability_digest",
        "manager_version_evidence_digest",
        "adapter_identity",
        "adapter_version",
        "activation_group",
        "surface_scope",
    ):
        _expect_equal(
            diagnostics,
            "ECHO_BINDING_MISMATCH",
            f"PlannedAction.record.preconditions.{field}",
            preconditions.get(field),
            action.get(field),
        )
    _expect_equal(
        diagnostics,
        "ECHO_BINDING_MISMATCH",
        "PlannedAction.record.preconditions.control_owner",
        preconditions.get("control_owner"),
        _nested(action, "route_record", "control_owner"),
    )


def _validate_receipt_echoes(
    diagnostics: list[Diagnostic],
    action: JsonObject,
    receipt: JsonObject,
) -> None:
    _echo(
        diagnostics,
        "MutationReceipt",
        receipt,
        action,
        (
            "action_identity",
            "correlation_identity",
            "ordinal",
            "candidate_identity",
            "implementation_manifest_digest",
            "catalog_digest",
            "lock_digest",
            "plan_digest",
            "capability_identity",
            "capability_digest",
            "manager_version_evidence_digest",
            "adapter_identity",
            "adapter_version",
            "harness",
            "route_identity",
            "route_digest",
            "equipment_identities",
            "controlled_equipment_identities",
            "activation_group",
            "surface_scope",
            "operation",
            "operation_disposition",
            "secret_references",
        ),
    )
    _expect_equal(
        diagnostics,
        "ECHO_BINDING_MISMATCH",
        "MutationReceipt.record.control_owner",
        receipt.get("control_owner"),
        _nested(action, "route_record", "control_owner"),
    )


def _validate_apply_authority(
    diagnostics: list[Diagnostic],
    authority: JsonObject,
    request: JsonObject,
    observation: JsonObject,
    action: JsonObject,
    receipt: JsonObject,
    verification_request: JsonObject,
    verification_observation: JsonObject,
) -> None:
    _expect_equal(
        diagnostics,
        "COMMAND_BOUNDARY_MISMATCH",
        "ApplySequence.sequence.authority.command",
        authority.get("command"),
        "apply",
    )
    _expect_equal(
        diagnostics,
        "COMMAND_BOUNDARY_MISMATCH",
        "ApplySequence.sequence.authority.purpose",
        authority.get("purpose"),
        "capture_pre_state" if authority.get("phase") == "apply" else "recovery",
    )
    for field in (
        "action_identity",
        "correlation_identity",
        "candidate_identity",
        "implementation_manifest_digest",
        "catalog_digest",
        "lock_digest",
        "plan_digest",
        "capability_identity",
        "capability_digest",
        "manager_version_evidence_digest",
        "adapter_identity",
        "adapter_version",
        "harness",
        "route_identity",
        "route_digest",
        "equipment_identities",
        "controlled_equipment_identities",
        "activation_group",
        "operation",
    ):
        _expect_equal(
            diagnostics,
            "AUTHORITY_BINDING_MISMATCH",
            f"ApplySequence.sequence.authority.{field}",
            authority.get(field),
            action.get(field),
        )
    for field in ("command", "purpose", "request_identity"):
        _expect_equal(
            diagnostics,
            "AUTHORITY_BINDING_MISMATCH",
            f"ApplySequence.sequence.authority.{field}",
            authority.get(field),
            request.get(field),
        )
    _expect_equal(
        diagnostics,
        "AUTHORITY_BINDING_MISMATCH",
        "ApplySequence.sequence.authority.phase",
        authority.get("phase"),
        receipt.get("phase"),
    )
    _expect_equal(
        diagnostics,
        "AUTHORITY_BINDING_MISMATCH",
        "ApplySequence.sequence.authority.read_surface_scope",
        authority.get("read_surface_scope"),
        request.get("surface_scope"),
    )
    _expect_equal(
        diagnostics,
        "AUTHORITY_BINDING_MISMATCH",
        "ApplySequence.sequence.authority.write_surface_scope",
        authority.get("write_surface_scope"),
        action.get("surface_scope"),
    )
    _expect_equal(
        diagnostics,
        "AUTHORITY_BINDING_MISMATCH",
        "ApplySequence.sequence.authority.selected_component_controls",
        authority.get("selected_component_controls"),
        _nested(action, "route_record", "component_controls"),
    )
    for field in (
        "correlation_identity",
        "candidate_identity",
        "implementation_manifest_digest",
        "catalog_digest",
        "lock_digest",
        "plan_digest",
        "capability_identity",
        "capability_digest",
        "manager_version_evidence_digest",
        "harness",
        "route_identity",
        "route_digest",
        "equipment_identities",
        "controlled_equipment_identities",
        "activation_group",
    ):
        _expect_equal(
            diagnostics,
            "AUTHORITY_BINDING_MISMATCH",
            f"PostStateRequest.record.{field}",
            verification_request.get(field),
            authority.get(field),
        )
    _expect_equal(
        diagnostics,
        "AUTHORITY_BINDING_MISMATCH",
        "PostStateRequest.record.surface_scope",
        verification_request.get("surface_scope"),
        authority.get("write_surface_scope"),
    )
    for field in ("route_record", "secret_references"):
        _expect_equal(
            diagnostics,
            "AUTHORITY_BINDING_MISMATCH",
            f"PostStateRequest.record.{field}",
            verification_request.get(field),
            action.get(field),
        )
    observation_result = observation.get("result")
    captured_state = (
        observation_result.get("captured_state")
        if isinstance(observation_result, dict)
        else None
    )
    for field in ("identity", "digest"):
        authority_field = f"captured_state_{field}"
        _expect_equal(
            diagnostics,
            "CAPTURE_BINDING_MISMATCH",
            f"ApplySequence.sequence.authority.{authority_field}",
            authority.get(authority_field),
            captured_state.get(field) if isinstance(captured_state, dict) else None,
        )
    expected_pre_state = (
        observation_result.get("state_digest")
        if isinstance(observation_result, dict)
        else None
    )
    _expect_equal(
        diagnostics,
        "CAPTURE_BINDING_MISMATCH",
        "ApplySequence.sequence.authority.expected_pre_state_digest",
        authority.get("expected_pre_state_digest"),
        expected_pre_state,
    )
    captured_pre_state = authority.get("captured_pre_state")
    _expect_equal(
        diagnostics,
        "CANONICAL_STATE_DIGEST_MISMATCH",
        "ApplySequence.sequence.authority.captured_pre_state_digest",
        authority.get("captured_pre_state_digest"),
        canonical_json_sha256(captured_pre_state)
        if isinstance(captured_pre_state, dict)
        else None,
    )
    expected_post_state = authority.get("expected_post_state")
    _expect_equal(
        diagnostics,
        "CANONICAL_STATE_DIGEST_MISMATCH",
        "ApplySequence.sequence.authority.expected_post_state_digest",
        authority.get("expected_post_state_digest"),
        canonical_json_sha256(expected_post_state)
        if isinstance(expected_post_state, dict)
        else None,
    )
    verification_result = verification_observation.get("result")
    verified_state = (
        verification_result.get("normalized_state")
        if isinstance(verification_result, dict)
        else None
    )
    _expect_equal(
        diagnostics,
        "POST_STATE_MISMATCH",
        "ApplySequence.sequence.authority.expected_post_state",
        authority.get("expected_post_state"),
        verified_state,
    )
    if authority.get("phase") == "apply":
        _expect_equal(
            diagnostics,
            "CAPTURE_BINDING_MISMATCH",
            "ApplySequence.sequence.authority.captured_pre_state_digest",
            authority.get("captured_pre_state_digest"),
            expected_pre_state,
        )
        observation_state = (
            observation_result.get("normalized_state")
            if isinstance(observation_result, dict)
            else None
        )
        _expect_equal(
            diagnostics,
            "CAPTURE_BINDING_MISMATCH",
            "ApplySequence.sequence.authority.captured_pre_state",
            authority.get("captured_pre_state"),
            observation_state,
        )
        _expect_equal(
            diagnostics,
            "FORWARD_POST_STATE_MISMATCH",
            "ApplySequence.sequence.authority.forward_post_state_digest",
            authority.get("forward_post_state_digest"),
            authority.get("expected_post_state_digest"),
        )
    else:
        _expect_equal(
            diagnostics,
            "COMPENSATION_GUARD_MISMATCH",
            "ApplySequence.sequence.authority.forward_post_state_digest",
            authority.get("forward_post_state_digest"),
            authority.get("expected_pre_state_digest"),
        )
        _expect_equal(
            diagnostics,
            "COMPENSATION_RESTORE_MISMATCH",
            "ApplySequence.sequence.authority.expected_post_state",
            authority.get("expected_post_state"),
            authority.get("captured_pre_state"),
        )
    _expect_equal(
        diagnostics,
        "CHECKPOINT_BINDING_MISMATCH",
        "ApplySequence.sequence.authority.prepared_checkpoint_reference",
        authority.get("prepared_checkpoint_reference"),
        receipt.get("prepared_checkpoint_reference"),
    )


def _validate_receipt_result(
    diagnostics: list[Diagnostic],
    authority: JsonObject,
    receipt: JsonObject,
) -> None:
    result = receipt.get("result")
    if not isinstance(result, dict) or result.get("status") != "ok":
        diagnostics.append(
            Diagnostic(
                "MUTATION_NOT_SUCCESSFUL",
                "MutationReceipt.record.result",
                "A successful ApplySequence requires one successful mutation receipt.",
            )
        )
        return
    for field in ("expected_pre_state_digest", "observed_pre_state_digest"):
        _expect_equal(
            diagnostics,
            "PRE_STATE_MISMATCH",
            f"MutationReceipt.record.result.{field}",
            result.get(field),
            authority.get("expected_pre_state_digest"),
        )
    for field in ("expected_post_state_digest", "observed_post_state_digest"):
        _expect_equal(
            diagnostics,
            "POST_STATE_MISMATCH",
            f"MutationReceipt.record.result.{field}",
            result.get(field),
            authority.get("expected_post_state_digest"),
        )
    _expect_equal(
        diagnostics,
        "MUTATION_EVIDENCE_MISMATCH",
        "MutationReceipt.record.result.surface_evidence",
        _evidence_identities(result.get("surface_evidence")),
        authority.get("write_surface_scope"),
    )
    _validate_evidence_kinds(
        diagnostics,
        "MUTATION_EVIDENCE_KIND_MISMATCH",
        "MutationReceipt.record.result.surface_evidence",
        result.get("surface_evidence"),
        frozenset({"surface"}),
    )
    compensation = result.get("compensation_evidence")
    if not isinstance(compensation, dict):
        return
    for field in ("captured_state_identity", "captured_state_digest"):
        _expect_equal(
            diagnostics,
            "COMPENSATION_BINDING_MISMATCH",
            f"MutationReceipt.record.result.compensation_evidence.{field}",
            compensation.get(field),
            authority.get(field),
        )
    if authority.get("phase") == "apply":
        _expect_equal(
            diagnostics,
            "COMPENSATION_BINDING_MISMATCH",
            "MutationReceipt.record.result.compensation_evidence.expected_post_state_digest",
            compensation.get("expected_post_state_digest"),
            authority.get("expected_post_state_digest"),
        )
    else:
        _expect_equal(
            diagnostics,
            "COMPENSATION_RESTORE_MISMATCH",
            "MutationReceipt.record.result.compensation_evidence.restored_state_digest",
            compensation.get("restored_state_digest"),
            authority.get("captured_pre_state_digest"),
        )


def _capability_record(
    document: JsonObject,
    requested_identity: Any,
    diagnostics: list[Diagnostic],
) -> JsonObject | None:
    if document.get("record_type") != "CapabilityDiscovery":
        diagnostics.append(
            Diagnostic(
                "RECORD_TYPE_INVALID",
                "CapabilityDiscovery.record_type",
                "The sequence begins with one capability-discovery result.",
            )
        )
        return None
    result = document.get("result")
    if not isinstance(result, dict) or result.get("status") != "ok":
        diagnostics.append(
            Diagnostic(
                "CAPABILITY_DISCOVERY_FAILED",
                "CapabilityDiscovery.result",
                "A failed discovery cannot authorize an adapter sequence.",
            )
        )
        return None
    records = result.get("records")
    matches = (
        [
            record
            for record in records
            if isinstance(record, dict)
            and record.get("capability_identity") == requested_identity
        ]
        if isinstance(records, list)
        else []
    )
    if len(matches) != 1:
        diagnostics.append(
            Diagnostic(
                "CAPABILITY_SELECTION_AMBIGUOUS",
                "CapabilityDiscovery.result.records",
                "Discovery must contain exactly one record matching the request capability identity.",
            )
        )
        return None
    return matches[0]


def _record(
    document: JsonObject,
    record_type: str,
    diagnostics: list[Diagnostic],
) -> JsonObject | None:
    if document.get("record_type") != record_type or not isinstance(
        document.get("record"), dict
    ):
        diagnostics.append(
            Diagnostic(
                "RECORD_TYPE_INVALID",
                f"{record_type}.record_type",
                f"The sequence requires one {record_type} record.",
            )
        )
        return None
    return document["record"]


def _echo(
    diagnostics: list[Diagnostic],
    label: str,
    actual: JsonObject,
    expected: JsonObject,
    fields: tuple[str, ...],
) -> None:
    for field in fields:
        _expect_equal(
            diagnostics,
            "ECHO_BINDING_MISMATCH",
            f"{label}.record.{field}",
            actual.get(field),
            expected.get(field),
        )


def _expect_equal(
    diagnostics: list[Diagnostic],
    code: str,
    path: str,
    actual: Any,
    expected: Any,
) -> None:
    if actual != expected:
        diagnostics.append(
            Diagnostic(code, path, "The value does not match its canonical binding.")
        )


def _expect_not_equal(
    diagnostics: list[Diagnostic],
    code: str,
    path: str,
    actual: Any,
    forbidden: Any,
) -> None:
    if actual == forbidden:
        diagnostics.append(
            Diagnostic(code, path, "The value must identify a distinct call.")
        )


def _validate_sequence_timestamps(
    diagnostics: list[Diagnostic],
    pre_observation: JsonObject,
    receipt: JsonObject,
    post_observation: JsonObject,
) -> None:
    values = (
        ("PreStateObservation.record.observed_at", pre_observation.get("observed_at")),
        ("MutationReceipt.record.started_at", receipt.get("started_at")),
        ("MutationReceipt.record.finished_at", receipt.get("finished_at")),
        (
            "PostStateObservation.record.observed_at",
            post_observation.get("observed_at"),
        ),
    )
    parsed = tuple(_parse_utc_timestamp(value) for _, value in values)
    if any(value is None for value in parsed):
        diagnostics.append(
            Diagnostic(
                "TIMESTAMP_ORDER_INVALID",
                next(
                    path
                    for (path, _), parsed_value in zip(values, parsed, strict=True)
                    if parsed_value is None
                ),
                "Sequence timestamps must be parseable RFC 3339 UTC values ending in Z.",
            )
        )
        return
    assert all(value is not None for value in parsed)
    if list(parsed) != sorted(parsed):
        diagnostics.append(
            Diagnostic(
                "TIMESTAMP_ORDER_INVALID",
                "ApplySequence.sequence",
                "Pre-state observation, invocation start, receipt completion, and post-state observation must be nondecreasing.",
            )
        )


def _parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError:
        return None
    offset = parsed.utcoffset()
    return parsed if offset is not None and offset.total_seconds() == 0 else None


def _manager_for_provider(provider_match: Any) -> Any:
    if not isinstance(provider_match, dict):
        return None
    kind = provider_match.get("kind")
    if kind == "native_plugin":
        return provider_match.get("manager")
    if kind == "standalone_skill":
        return "standalone_skills"
    if kind == "direct_mcp":
        return "direct_mcp"
    return None


def _nested(document: JsonObject, first: str, second: str) -> Any:
    nested = document.get(first)
    return nested.get(second) if isinstance(nested, dict) else None


def _nested3(document: JsonObject, first: str, second: str, third: str) -> Any:
    first_value = document.get(first)
    if not isinstance(first_value, dict):
        return None
    second_value = first_value.get(second)
    return second_value.get(third) if isinstance(second_value, dict) else None


def _component_identities(component_states: Any) -> list[str] | None:
    if not isinstance(component_states, list):
        return None
    identities = []
    for component in component_states:
        identity = (
            component.get("equipment_identity") if isinstance(component, dict) else None
        )
        if not isinstance(identity, str):
            return None
        identities.append(identity)
    return identities


def _evidence_identities(evidence: Any) -> list[str] | None:
    if not isinstance(evidence, list):
        return None
    identities = []
    for item in evidence:
        identity = item.get("identity") if isinstance(item, dict) else None
        if not isinstance(identity, str):
            return None
        identities.append(identity)
    return identities


def _validate_evidence_kinds(
    diagnostics: list[Diagnostic],
    code: str,
    path: str,
    evidence: Any,
    allowed_kinds: frozenset[str],
) -> None:
    if not isinstance(evidence, list):
        return
    for index, item in enumerate(evidence):
        kind = item.get("kind") if isinstance(item, dict) else None
        if kind not in allowed_kinds:
            diagnostics.append(
                Diagnostic(
                    code,
                    f"{path}[{index}].kind",
                    "Evidence kind does not prove the named surface access.",
                )
            )


def _native_provider_manager(route_record: JsonObject) -> Any:
    provider = route_record.get("provider")
    if isinstance(provider, dict) and provider.get("kind") == "native_plugin":
        return provider.get("manager")
    return None


def _provider_selector_matches(
    capability_provider: Any,
    route_provider: Any,
    harness: Any,
) -> bool:
    if not isinstance(capability_provider, dict) or not isinstance(
        route_provider, dict
    ):
        return False
    kind = capability_provider.get("kind")
    if route_provider.get("kind") != kind:
        return False
    if kind == "standalone_skill":
        canonical_root = capability_provider.get("canonical_root")
        return canonical_root is not None and canonical_root == route_provider.get(
            "canonical_root"
        )
    if kind == "native_plugin":
        selector = tuple(
            capability_provider.get(field) for field in ("manager", "scope")
        )
        return None not in selector and selector == tuple(
            route_provider.get(field) for field in ("manager", "scope")
        )
    if kind == "direct_mcp":
        overlays = {
            "claude": "claude_json",
            "codex": "codex_toml",
            "cursor": "cursor_json",
        }
        transport = capability_provider.get("transport")
        expected_overlay = overlays.get(harness)
        return (
            transport is not None
            and transport == route_provider.get("transport")
            and expected_overlay is not None
            and capability_provider.get("overlay_family") == expected_overlay
        )
    return False


def _validate_unique_component_identities(
    diagnostics: list[Diagnostic],
    path: str,
    component_states: Any,
) -> None:
    if not isinstance(component_states, list):
        return
    identities = []
    for component in component_states:
        identity = (
            component.get("equipment_identity") if isinstance(component, dict) else None
        )
        if isinstance(identity, str):
            identities.append(identity)
    if len(identities) != len(set(identities)):
        diagnostics.append(
            Diagnostic(
                "COMPONENT_IDENTITY_CONFLICT",
                path,
                "Each equipment identity may have only one component state.",
            )
        )


def _validate_action_authorization(
    diagnostics: list[Diagnostic],
    capability: JsonObject,
    action: JsonObject,
) -> None:
    operation = action.get("operation")
    if operation not in MUTATING_OPERATIONS:
        diagnostics.append(
            Diagnostic(
                "ACTION_OPERATION_UNAUTHORIZED",
                "PlannedAction.record.operation",
                "A planned action requires one known mutating operation.",
            )
        )
        return

    if action.get("operation_disposition") != "automated":
        diagnostics.append(
            Diagnostic(
                "ACTION_OPERATION_UNAUTHORIZED",
                "PlannedAction.record.operation_disposition",
                "A planned action requires an automated action disposition.",
            )
        )

    route_record = action.get("route_record")
    route_operations = (
        route_record.get("operations") if isinstance(route_record, dict) else None
    )
    route_support = (
        route_operations.get(operation) if isinstance(route_operations, dict) else None
    )
    if (
        not isinstance(route_support, dict)
        or route_support.get("disposition") != "automated"
    ):
        diagnostics.append(
            Diagnostic(
                "ACTION_OPERATION_UNAUTHORIZED",
                f"PlannedAction.record.route_record.operations.{operation}",
                "The selected route must authorize the operation as automated.",
            )
        )

    operation_support = capability.get("operation_support")
    capability_support = (
        operation_support.get(operation)
        if isinstance(operation_support, dict)
        else None
    )
    if (
        not isinstance(capability_support, dict)
        or capability_support.get("mode") != "automated"
    ):
        diagnostics.append(
            Diagnostic(
                "ACTION_OPERATION_UNAUTHORIZED",
                f"CapabilityDiscovery.result.records[].operation_support.{operation}",
                "The selected capability must implement the operation as automated.",
            )
        )

    provider = route_record.get("provider") if isinstance(route_record, dict) else None
    restore = route_record.get("restore") if isinstance(route_record, dict) else None
    if (
        operation == "remove"
        and isinstance(provider, dict)
        and provider.get("kind") == "native_plugin"
        and isinstance(restore, dict)
        and restore.get("class") == "native_rolling"
    ):
        diagnostics.append(
            Diagnostic(
                "NATIVE_ROLLING_REMOVE_UNSAFE",
                "PlannedAction.record.operation",
                "A native-rolling plugin cannot authorize general automated removal.",
            )
        )


def _validate_surface_scope(
    diagnostics: list[Diagnostic],
    label: str,
    capability: JsonObject,
    record: JsonObject,
) -> None:
    expected = _derive_surface_scope(
        capability.get("surface_identity_rule"),
        record.get("route_identity"),
        _surface_equipment_identities(record),
    )
    if expected is None or record.get("surface_scope") != expected:
        diagnostics.append(
            Diagnostic(
                "SURFACE_SCOPE_MISMATCH",
                f"{label}.record.surface_scope",
                "Surface scope must be exactly derived from the selected capability rule.",
            )
        )


def _derive_surface_scope(
    identity_rule: Any,
    route_identity: Any,
    equipment_identities: Any,
) -> list[str] | None:
    if (
        not isinstance(identity_rule, dict)
        or identity_rule.get("version") != 1
        or not isinstance(route_identity, str)
        or not isinstance(equipment_identities, list)
        or not all(isinstance(identity, str) for identity in equipment_identities)
    ):
        return None
    rule = identity_rule.get("rule")
    if rule == "shared_equipment_identity":
        return sorted(f"surface:shared/{identity}" for identity in equipment_identities)
    if rule == "route_and_equipment_identity":
        return sorted(
            f"surface:{route_identity}/{identity}" for identity in equipment_identities
        )
    if rule == "route_identity":
        return [f"surface:{route_identity}"]
    return None


def _surface_equipment_identities(record: JsonObject) -> list[str] | None:
    active = record.get("equipment_identities")
    controlled = record.get("controlled_equipment_identities")
    if not isinstance(active, list) or not isinstance(controlled, list):
        return None
    identities = active + controlled
    if not all(isinstance(identity, str) for identity in identities):
        return None
    return sorted(set(identities))


def _validate_desired_component_controls(
    diagnostics: list[Diagnostic],
    capability: JsonObject,
    action: JsonObject,
    desired_components: Any,
) -> None:
    route_record = action.get("route_record")
    route_components = (
        route_record.get("component_controls")
        if isinstance(route_record, dict)
        else None
    )
    route_controls = _component_state_map(route_components)
    desired_controls = (
        _component_state_map(desired_components)
        if isinstance(desired_components, list)
        else {}
    )
    if route_controls is None or desired_controls != route_controls:
        diagnostics.append(
            Diagnostic(
                "COMPONENT_CONTROL_UNAUTHORIZED",
                "PlannedAction.record.desired_state.component_states",
                "Desired component states must exactly equal the selected route controls.",
            )
        )
    desired_identities = _component_identities(desired_components)
    _expect_equal(
        diagnostics,
        "COMPONENT_CONTROL_UNAUTHORIZED",
        "PlannedAction.record.desired_state.component_states",
        desired_identities if desired_identities is not None else [],
        action.get("controlled_equipment_identities"),
    )

    support = capability.get("component_control_support")
    supported_identities = (
        support.get("supported_equipment_identities")
        if isinstance(support, dict)
        else None
    )
    supported_states = (
        support.get("supported_states") if isinstance(support, dict) else None
    )
    selected_identities = action.get("controlled_equipment_identities")
    capability_automates_controls = (
        isinstance(support, dict)
        and support.get("mode") == "automated"
        and support.get("selector_granularity") == "equipment_identity"
        and support.get("mutation_boundary") == "selected_component"
        and isinstance(supported_identities, list)
        and isinstance(supported_states, list)
    )
    components_to_validate = (
        route_components if isinstance(route_components, list) else []
    )
    for index, component in enumerate(components_to_validate):
        identity = (
            component.get("equipment_identity") if isinstance(component, dict) else None
        )
        state = component.get("state") if isinstance(component, dict) else None
        authorized = (
            isinstance(identity, str)
            and isinstance(state, str)
            and route_controls is not None
            and route_controls.get(identity) == state
            and isinstance(selected_identities, list)
            and identity in selected_identities
            and capability_automates_controls
            and identity in supported_identities
            and state in supported_states
        )
        if not authorized:
            diagnostics.append(
                Diagnostic(
                    "COMPONENT_CONTROL_UNAUTHORIZED",
                    f"PlannedAction.record.desired_state.component_states[{index}]",
                    "The desired component state exceeds the selected route or capability.",
                )
            )


def _component_state_map(component_states: Any) -> dict[str, Any] | None:
    if not isinstance(component_states, list):
        return None
    result: dict[str, Any] = {}
    for component in component_states:
        if not isinstance(component, dict):
            return None
        identity = component.get("equipment_identity")
        if not isinstance(identity, str) or identity in result:
            return None
        result[identity] = component.get("state")
    return result
