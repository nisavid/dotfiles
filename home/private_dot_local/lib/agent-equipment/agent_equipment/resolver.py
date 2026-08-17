"""Pure deterministic resolution and plan-graph construction."""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass

from .canonical import canonical_json_sha256
from .inventory import admit_capability_discovery, admit_runtime_inventory
from .model import (
    AdapterError,
    CapabilityDiscovery,
    CapabilityRecord,
    Catalog,
    CoverageRecord,
    Diagnostic,
    FrozenJsonObject,
    PlanNode,
    Resolution,
    ResolvedLock,
    RuntimeInventory,
    RuntimeObservation,
    ValidatedCatalogLock,
    ValidatedPlan,
    _resolution_digest,
    freeze_json,
    thaw_json,
)
from .secrets import contains_literal_credential
from .validator import validate_catalog_lock

_PLAN_PREIMAGE_VERSION = "agent-equipment-plan-preimage/v1"
_CLAUDE_PROJECTOR_CONTROL_SURFACE = "surface:claude/standalone-skill-projector"
_VERIFICATION_PURPOSES = frozenset(
    {
        "projector_readiness",
        "winner_activation",
        "coalesced_route_state",
        "final_coverage",
    }
)

_OPERATIONS = (
    "inspect",
    "install",
    "configure",
    "enable",
    "disable",
    "remove",
    "restore",
    "suppress_native_update",
)


@dataclass(frozen=True, slots=True)
class _RouteGroup:
    """One active route after selective controls have been applied."""

    harness: str
    route_identity: str
    activation_group: str
    equipment_identities: tuple[str, ...]
    controlled_equipment_identities: tuple[str, ...]
    route: FrozenJsonObject


@dataclass(frozen=True, slots=True)
class _RetirementRouteGroup:
    """One reviewed catalog-owned losing surface."""

    retirement_identity: str
    harness: str
    route_identity: str
    activation_group: str
    equipment_identities: tuple[str, ...]
    controlled_equipment_identities: tuple[str, ...]
    desired_state: str
    route: FrozenJsonObject


_RouteLike = _RouteGroup | _RetirementRouteGroup


def _provider_selector_matches(
    capability_provider: object,
    route_provider: object,
    harness: str,
) -> bool:
    if not isinstance(capability_provider, FrozenJsonObject) or not isinstance(
        route_provider, FrozenJsonObject
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


def _matching_capability(
    group: _RouteLike,
    capabilities: tuple[CapabilityRecord, ...],
) -> CapabilityRecord | None:
    """Select exactly one capability by the closed provider-family selector."""

    route_provider = group.route.get("provider")
    matches = tuple(
        capability
        for capability in capabilities
        if capability.harness == group.harness
        and _provider_selector_matches(
            capability.document.get("provider_match"),
            route_provider,
            group.harness,
        )
    )
    return matches[0] if len(matches) == 1 else None


def _component_control_diagnostics(
    group: _RouteLike,
    capability: CapabilityRecord,
) -> tuple[Diagnostic, ...]:
    """Require exact selected-component support before group resolution."""

    if not group.controlled_equipment_identities:
        return ()
    support = capability.document.get("component_control_support")
    if not isinstance(support, FrozenJsonObject):
        supported: tuple[object, ...] = ()
        states: tuple[object, ...] = ()
        mode: object = None
    else:
        raw_supported = support.get("supported_equipment_identities")
        raw_states = support.get("supported_states")
        supported = raw_supported if type(raw_supported) is tuple else ()
        states = raw_states if type(raw_states) is tuple else ()
        mode = support.get("mode")
    selected_states: set[str] = set()
    selected_states_are_valid = True
    for control in _desired_component_states(group):
        state = control.get("state")
        if state not in {"enabled", "disabled"}:
            selected_states_are_valid = False
        elif isinstance(state, str):
            selected_states.add(state)
    route_operations = group.route.get("operations")
    mode_is_authorized = selected_states_are_valid and isinstance(
        route_operations, FrozenJsonObject
    )
    allowed_modes = {
        "automated": frozenset({"automated"}),
        "operator_action": frozenset({"operator_action", "inspect_only"}),
        "unavailable": frozenset({"inspect_only"}),
    }
    for state in selected_states:
        operation = "enable" if state == "enabled" else "disable"
        operation_record = (
            route_operations.get(operation)
            if isinstance(route_operations, FrozenJsonObject)
            else None
        )
        disposition = (
            operation_record.get("disposition")
            if isinstance(operation_record, FrozenJsonObject)
            else None
        )
        authorized_modes = (
            allowed_modes.get(disposition, frozenset())
            if isinstance(disposition, str)
            else frozenset()
        )
        mode_is_authorized = mode_is_authorized and mode in authorized_modes
    if (
        not mode_is_authorized
        or not set(group.controlled_equipment_identities).issubset(set(supported))
        or not selected_states.issubset(set(states))
    ):
        return (
            Diagnostic(
                "COMPONENT_CONTROL_UNAUTHORIZED",
                "Selected component controls lack exact adapter capability.",
                harness=group.harness,
                route_identity=group.route_identity,
            ),
        )
    return ()


def _operation_matrix(
    group: _RouteLike,
    capability: CapabilityRecord,
) -> tuple[FrozenJsonObject, tuple[Diagnostic, ...]]:
    """Intersect reviewed operation dispositions with one exact capability."""

    route_operations = group.route.get("operations")
    capability_operations = capability.document.get("operation_support")
    if not isinstance(route_operations, FrozenJsonObject) or not isinstance(
        capability_operations, FrozenJsonObject
    ):
        return (
            _empty_operation_matrix(group, capability),
            (
                Diagnostic(
                    "CAPABILITY_OPERATION_MATRIX_INVALID",
                    "The selected capability has no closed operation matrix.",
                    harness=group.harness,
                    route_identity=group.route_identity,
                ),
            ),
        )

    diagnostics: list[Diagnostic] = []
    restore = group.route.get("restore")
    native_support = capability.document.get("native_update_support")
    reviewed_native_control = (
        restore.get("native_update_control")
        if isinstance(restore, FrozenJsonObject)
        else None
    )
    capability_native_control = (
        native_support.get("native_update_control")
        if isinstance(native_support, FrozenJsonObject)
        else None
    )
    if (
        isinstance(restore, FrozenJsonObject)
        and restore.get("class") == "native_rolling"
        and (
            not isinstance(native_support, FrozenJsonObject)
            or native_support.get("version_observation")
            not in {"automated", "inspect_only"}
            or native_support.get("baseline_comparison")
            not in {"automated", "inspect_only"}
        )
    ):
        diagnostics.append(
            Diagnostic(
                "NATIVE_ROLLING_EVIDENCE_CAPABILITY_MISSING",
                "The selected capability cannot observe and compare native-rolling version evidence.",
                harness=group.harness,
                route_identity=group.route_identity,
                evidence_source="capability-discovery",
            )
        )
    if (
        reviewed_native_control
        not in {"unknown", "suppressible", "unsuppressible", "not_applicable"}
        or capability_native_control != reviewed_native_control
    ):
        diagnostics.append(
            Diagnostic(
                "NATIVE_UPDATE_CAPABILITY_MISMATCH",
                "The selected capability does not match the reviewed native-update classification.",
                harness=group.harness,
                route_identity=group.route_identity,
                evidence_source="capability-discovery",
            )
        )
    operation_suppression = capability_operations.get("suppress_native_update")
    native_suppression = (
        native_support.get("suppression")
        if isinstance(native_support, FrozenJsonObject)
        else None
    )
    if (
        not isinstance(operation_suppression, FrozenJsonObject)
        or native_suppression != operation_suppression
    ):
        diagnostics.append(
            Diagnostic(
                "NATIVE_UPDATE_SUPPRESSION_AUTHORITY_MISMATCH",
                "Native-update suppression does not have one exact capability authority.",
                harness=group.harness,
                route_identity=group.route_identity,
                evidence_source="capability-discovery",
            )
        )
    if isinstance(restore, FrozenJsonObject) and restore.get("class") == "immutable":
        inspect_support = capability_operations.get("inspect")
        normalized_fields = (
            inspect_support.get("normalized_fields")
            if isinstance(inspect_support, FrozenJsonObject)
            else None
        )
        if type(normalized_fields) is not tuple or "immutable_content" not in (
            normalized_fields
        ):
            diagnostics.append(
                Diagnostic(
                    "IMMUTABLE_CONTENT_CAPABILITY_MISSING",
                    "The selected capability cannot inspect immutable content evidence.",
                    harness=group.harness,
                    route_identity=group.route_identity,
                    evidence_source="capability-discovery",
                )
            )
    operations: dict[str, object] = {}
    for operation in (
        "inspect",
        "install",
        "configure",
        "enable",
        "disable",
        "remove",
        "restore",
        "suppress_native_update",
    ):
        disposition_record = route_operations.get(operation)
        support_record = capability_operations.get(operation)
        catalog_disposition = (
            disposition_record.get("disposition")
            if isinstance(disposition_record, FrozenJsonObject)
            else None
        )
        capability_mode = (
            support_record.get("mode")
            if isinstance(support_record, FrozenJsonObject)
            else None
        )
        effective_disposition = catalog_disposition
        invalid = False
        if catalog_disposition == "automated":
            invalid = capability_mode != "automated"
        elif catalog_disposition == "operator_action":
            invalid = capability_mode not in {"operator_action", "inspect_only"}
        elif catalog_disposition == "unavailable":
            effective_disposition = "unavailable"
        else:
            invalid = True
        if invalid:
            diagnostics.append(
                Diagnostic(
                    "ACTION_OPERATION_UNAUTHORIZED",
                    "A reviewed route operation lacks matching adapter capability.",
                    harness=group.harness,
                    route_identity=group.route_identity,
                )
            )
        operations[operation] = {
            "catalog_disposition": catalog_disposition,
            "capability_mode": capability_mode,
            "effective_disposition": effective_disposition,
        }

    component_support = capability.document.get("component_control_support")
    component_control_mode = (
        component_support.get("mode")
        if isinstance(component_support, FrozenJsonObject)
        else None
    )
    matrix = freeze_json(
        {
            "harness": group.harness,
            "route_identity": group.route_identity,
            "capability_identity": capability.capability_identity,
            "capability_digest": capability.capability_digest,
            "component_control_mode": component_control_mode,
            "operations": operations,
        }
    )
    assert isinstance(matrix, FrozenJsonObject)
    return matrix, tuple(diagnostics)


def _empty_operation_matrix(
    group: _RouteLike, capability: CapabilityRecord
) -> FrozenJsonObject:
    component_support = capability.document.get("component_control_support")
    component_control_mode = (
        component_support.get("mode")
        if isinstance(component_support, FrozenJsonObject)
        else None
    )
    matrix = freeze_json(
        {
            "harness": group.harness,
            "route_identity": group.route_identity,
            "capability_identity": capability.capability_identity,
            "capability_digest": capability.capability_digest,
            "component_control_mode": component_control_mode,
            "operations": {},
        }
    )
    assert isinstance(matrix, FrozenJsonObject)
    return matrix


def _provider_selection_records(
    validated: ValidatedCatalogLock,
) -> tuple[FrozenJsonObject, ...]:
    selections: list[FrozenJsonObject] = []
    for coverage in validated.coverage:
        selection = freeze_json(
            {
                "equipment_identity": coverage.equipment_identity,
                "harness": coverage.harness,
                "outcome": coverage.record.get("outcome"),
                "provider_selection": coverage.record.get("provider_selection"),
            }
        )
        assert isinstance(selection, FrozenJsonObject)
        selections.append(selection)
    return tuple(selections)


def _overlay_proposals(
    groups: tuple[_RouteGroup, ...],
) -> tuple[FrozenJsonObject, ...]:
    overlays: list[FrozenJsonObject] = []
    for group in groups:
        provider = group.route.get("provider")
        provenance = group.route.get("provenance")
        if (
            not isinstance(provider, FrozenJsonObject)
            or provider.get("kind") != "direct_mcp"
            or not isinstance(provenance, FrozenJsonObject)
            or provenance.get("owner") != f"overlay:{group.harness}/mcp"
        ):
            continue
        overlay = freeze_json(
            {
                "harness": group.harness,
                "route_identity": group.route_identity,
                "server_name": provider.get("server_name"),
                "transport": provider.get("transport"),
                "provider": provider,
                "secret_references": group.route.get("secret_references"),
            }
        )
        assert isinstance(overlay, FrozenJsonObject)
        overlays.append(overlay)
    return tuple(overlays)


def _surface_scope(
    capability: CapabilityRecord,
    group: _RouteLike,
) -> tuple[str, ...] | None:
    rule_record = capability.document.get("surface_identity_rule")
    if not isinstance(rule_record, FrozenJsonObject) or rule_record.get("version") != 1:
        return None
    identities = tuple(
        sorted(
            set(group.equipment_identities) | set(group.controlled_equipment_identities)
        )
    )
    rule = rule_record.get("rule")
    if rule == "shared_equipment_identity":
        return tuple(f"surface:shared/{identity}" for identity in identities)
    if rule == "route_and_equipment_identity":
        return tuple(
            f"surface:{group.route_identity}/{identity}" for identity in identities
        )
    if rule == "route_identity":
        return (f"surface:{group.route_identity}",)
    return None


def _observation_by_route(
    inventory: RuntimeInventory,
) -> tuple[dict[tuple[str, str], RuntimeObservation], tuple[Diagnostic, ...]]:
    observations: dict[tuple[str, str], RuntimeObservation] = {}
    diagnostics: list[Diagnostic] = []
    for observation in inventory.observations:
        key = (observation.harness, observation.route_identity)
        if key in observations:
            diagnostics.append(
                Diagnostic(
                    "RUNTIME_OBSERVATION_DUPLICATE",
                    "Runtime inventory contains a duplicate route observation.",
                    harness=observation.harness,
                    route_identity=observation.route_identity,
                    evidence_source="runtime-inventory",
                )
            )
        else:
            observations[key] = observation
    return observations, tuple(diagnostics)


def _observation_binding_diagnostics(
    group: _RouteLike,
    capability: CapabilityRecord,
    observation: RuntimeObservation,
) -> tuple[Diagnostic, ...]:
    """Require an observation to echo the exact route, capability, and scope."""

    expected_scope = _surface_scope(capability, group)
    result = observation.document.get("result")
    normalized = (
        result.get("normalized_state") if isinstance(result, FrozenJsonObject) else None
    )
    component_states = (
        normalized.get("component_states")
        if isinstance(normalized, FrozenJsonObject)
        else None
    )
    component_identities = (
        tuple(
            item.get("equipment_identity")
            for item in component_states
            if isinstance(item, FrozenJsonObject)
        )
        if type(component_states) is tuple
        else ()
    )
    evidence = (
        result.get("surface_evidence") if isinstance(result, FrozenJsonObject) else None
    )
    evidence_identities = (
        tuple(
            item.get("identity")
            for item in evidence
            if isinstance(item, FrozenJsonObject)
        )
        if type(evidence) is tuple
        else ()
    )
    restore = group.route.get("restore")
    expected_native_control = (
        restore.get("native_update_control")
        if isinstance(restore, FrozenJsonObject)
        else None
    )
    mismatched = (
        observation.capability_identity != capability.capability_identity
        or observation.capability_digest != capability.capability_digest
        or observation.manager_version_evidence_digest
        != capability.manager_version_evidence_digest
        or observation.document.get("route_digest")
        != canonical_json_sha256(group.route)
        or observation.document.get("control_owner") != group.route.get("control_owner")
        or observation.document.get("equipment_identities")
        != group.equipment_identities
        or observation.document.get("controlled_equipment_identities")
        != group.controlled_equipment_identities
        or observation.document.get("activation_group") != group.activation_group
        or expected_scope is None
        or observation.document.get("surface_scope") != expected_scope
        or component_identities != group.controlled_equipment_identities
        or evidence_identities != expected_scope
        or not isinstance(normalized, FrozenJsonObject)
        or normalized.get("native_update_control") != expected_native_control
    )
    if mismatched:
        return (
            Diagnostic(
                "RUNTIME_OBSERVATION_BINDING_MISMATCH",
                "Runtime observation does not bind the exact resolved route group.",
                harness=group.harness,
                route_identity=group.route_identity,
                evidence_source="runtime-inventory",
            ),
        )
    return ()


def _native_rolling_version_diagnostics(
    group: _RouteLike,
    observation: RuntimeObservation,
) -> tuple[Diagnostic, ...]:
    """Require exact version evidence for every reviewed rolling route state."""

    restore = group.route.get("restore")
    if (
        not isinstance(restore, FrozenJsonObject)
        or restore.get("class") != "native_rolling"
    ):
        return ()
    normalized = _normalized_state(observation)
    presence = normalized.get("route_presence")
    observed_version = normalized.get("observed_version")
    manager_drift = normalized.get("manager_drift")
    manager_binding_matches = (
        isinstance(manager_drift, FrozenJsonObject)
        and manager_drift.get("reviewed_baseline") == restore.get("reviewed_baseline")
        and manager_drift.get("observation_source") == restore.get("observation_source")
    )
    version_supports_classification = False
    if presence == "absent":
        expected_absence = freeze_json({"status": "route_absent"})
        version_supports_classification = observed_version == expected_absence
    elif presence == "present" and isinstance(observed_version, FrozenJsonObject):
        value = observed_version.get("value")
        expected_drift_status = (
            "none"
            if value == restore.get("reviewed_baseline")
            else "changed_from_reviewed_baseline"
        )
        version_supports_classification = (
            observed_version.get("status") == "observed"
            and type(value) is str
            and isinstance(manager_drift, FrozenJsonObject)
            and manager_drift.get("status") == expected_drift_status
        )
    if not version_supports_classification or not manager_binding_matches:
        return (
            Diagnostic(
                "NATIVE_ROLLING_VERSION_UNVERIFIED",
                "Native-rolling version evidence does not support the reviewed baseline and drift classification.",
                harness=group.harness,
                route_identity=group.route_identity,
                evidence_source="runtime-inventory",
            ),
        )
    return ()


def _route_state_coherence_diagnostics(
    group: _RouteLike,
    observation: RuntimeObservation,
) -> tuple[Diagnostic, ...]:
    """Require normalized evidence to match the reviewed restoration class."""

    restore = group.route.get("restore")
    if not isinstance(restore, FrozenJsonObject):
        return (
            Diagnostic(
                "IMMUTABLE_CONTENT_UNVERIFIED",
                "Runtime evidence does not match a reviewed restoration class.",
                harness=group.harness,
                route_identity=group.route_identity,
                evidence_source="runtime-inventory",
            ),
        )
    normalized = _normalized_state(observation)
    restore_class = restore.get("class")
    immutable_content = normalized.get("immutable_content")
    not_applicable = freeze_json({"status": "not_applicable"})
    coherent = False
    if restore_class == "native_rolling":
        coherent = immutable_content == not_applicable
    elif restore_class == "immutable":
        presence = normalized.get("route_presence")
        status = (
            immutable_content.get("status")
            if isinstance(immutable_content, FrozenJsonObject)
            else None
        )
        presence_coherent = (
            (presence == "present" and status in {"observed", "unknown"})
            or (presence == "absent" and status == "route_absent")
            or (presence in {"partial", "unknown"} and status == "unknown")
        )
        manager_drift = normalized.get("manager_drift")
        manager_not_applicable = freeze_json(
            {
                "status": "not_applicable",
                "reviewed_baseline": None,
                "observation_source": None,
            }
        )
        coherent = (
            presence_coherent
            and not (presence == "present" and status == "unknown")
            and normalized.get("observed_version") == not_applicable
            and normalized.get("native_update_control") == "not_applicable"
            and normalized.get("native_update_suppression_state") == "not_applicable"
            and manager_drift == manager_not_applicable
        )
    if coherent:
        return ()
    return (
        Diagnostic(
            "IMMUTABLE_CONTENT_UNVERIFIED",
            "Runtime evidence does not match the reviewed restoration class.",
            harness=group.harness,
            route_identity=group.route_identity,
            evidence_source="runtime-inventory",
        ),
    )


def _desired_component_states(group: _RouteLike) -> tuple[FrozenJsonObject, ...]:
    controls = group.route.get("component_controls")
    if type(controls) is not tuple:
        raise TypeError("validated route controls must be frozen JSON objects")
    typed_controls: list[FrozenJsonObject] = []
    for control in controls:
        if not isinstance(control, FrozenJsonObject):
            raise TypeError("validated route controls must be frozen JSON objects")
        typed_controls.append(control)
    return tuple(
        sorted(
            typed_controls,
            key=lambda control: str(control.get("equipment_identity")),
        )
    )


def _desired_configuration(group: _RouteLike) -> FrozenJsonObject:
    configuration = freeze_json(
        {
            "status": "observed",
            "digest": canonical_json_sha256(
                {
                    "provider": group.route.get("provider"),
                    "component_controls": group.route.get("component_controls"),
                }
            ),
        }
    )
    assert isinstance(configuration, FrozenJsonObject)
    return configuration


def _immutable_content_target(group: _RouteLike) -> FrozenJsonObject | None:
    """Return the reviewed immutable tuple, if this is an immutable route."""

    restore = group.route.get("restore")
    if not isinstance(restore, FrozenJsonObject) or restore.get("class") != "immutable":
        return None
    target = freeze_json(
        {
            "status": "observed",
            "revision": restore.get("revision"),
            "content_digest": restore.get("content_digest"),
        }
    )
    assert isinstance(target, FrozenJsonObject)
    return target


def _desired_state(operation: str, group: _RouteLike) -> FrozenJsonObject:
    if operation == "install":
        payload: object = {"route_presence": "present"}
    elif operation == "configure":
        payload = {
            "configuration": _desired_configuration(group),
            "component_states": _desired_component_states(group),
        }
    elif operation == "enable":
        payload = {"enablement": "enabled"}
    elif operation == "disable":
        payload = {"enablement": "disabled"}
    elif operation == "remove":
        payload = {"route_presence": "absent"}
    elif operation == "restore":
        payload = {"route_presence": "present"}
    else:
        raise ValueError("operation does not produce a Step 2 desired state")
    desired = freeze_json(payload)
    assert isinstance(desired, FrozenJsonObject)
    return desired


def _normalized_state(observation: RuntimeObservation) -> FrozenJsonObject:
    result = observation.document.get("result")
    normalized = (
        result.get("normalized_state") if isinstance(result, FrozenJsonObject) else None
    )
    if not isinstance(normalized, FrozenJsonObject):
        raise TypeError("admitted observation has no normalized state")
    return normalized


def _normalized_state_predicate(
    operator: str,
    expected: FrozenJsonObject,
) -> FrozenJsonObject:
    predicate = freeze_json({"operator": operator, "expected": expected})
    assert isinstance(predicate, FrozenJsonObject)
    return predicate


def _active_state_target(
    group: _RouteGroup,
    matrix: FrozenJsonObject,
) -> FrozenJsonObject:
    target: dict[str, object] = {
        "route_presence": "present",
        "component_states": _desired_component_states(group),
    }
    immutable_target = _immutable_content_target(group)
    if immutable_target is not None:
        target["immutable_content"] = immutable_target
    restore = group.route.get("restore")
    if (
        isinstance(restore, FrozenJsonObject)
        and restore.get("class") == "native_rolling"
    ):
        target["observed_version"] = {
            "status": "observed",
            "value": restore.get("reviewed_baseline"),
        }
        target["manager_drift"] = {
            "status": "none",
            "reviewed_baseline": restore.get("reviewed_baseline"),
            "observation_source": restore.get("observation_source"),
        }
    if _effective_disposition(matrix, "configure") != "unavailable":
        target["configuration"] = _desired_configuration(group)
    if _effective_disposition(matrix, "enable") != "unavailable":
        target["enablement"] = "enabled"
    frozen = freeze_json(target)
    assert isinstance(frozen, FrozenJsonObject)
    return frozen


def _effective_disposition(matrix: FrozenJsonObject, operation: str) -> str | None:
    operations = matrix.get("operations")
    if not isinstance(operations, FrozenJsonObject):
        return None
    record = operations.get(operation)
    if not isinstance(record, FrozenJsonObject):
        return None
    value = record.get("effective_disposition")
    return value if type(value) is str else None


def _action_operations(
    group: _RouteLike,
    observation: RuntimeObservation,
    matrix: FrozenJsonObject,
    *,
    retirement: bool,
) -> tuple[tuple[str, ...], tuple[Diagnostic, ...]]:
    result = observation.document.get("result")
    normalized = (
        result.get("normalized_state") if isinstance(result, FrozenJsonObject) else None
    )
    if not isinstance(normalized, FrozenJsonObject):
        return (), (
            Diagnostic(
                "RUNTIME_STATE_INDETERMINATE",
                "Runtime state cannot be classified from the admitted observation.",
                harness=group.harness,
                route_identity=group.route_identity,
                evidence_source="runtime-inventory",
            ),
        )
    manager_drift = normalized.get("manager_drift")
    if (
        isinstance(manager_drift, FrozenJsonObject)
        and manager_drift.get("status") == "changed_from_reviewed_baseline"
    ):
        return (), (
            Diagnostic(
                "MANAGER_DRIFT_REVIEW_REQUIRED",
                "Manager state changed from the reviewed route baseline.",
                harness=group.harness,
                route_identity=group.route_identity,
                evidence_source="runtime-inventory",
            ),
        )
    presence = normalized.get("route_presence")
    enablement = normalized.get("enablement")
    immutable_content = normalized.get("immutable_content")
    immutable_target = _immutable_content_target(group)
    desired_configuration = _desired_state("configure", group)
    configuration_matches = normalized.get(
        "configuration"
    ) == desired_configuration.get("configuration") and normalized.get(
        "component_states"
    ) == desired_configuration.get("component_states")
    if presence in {"partial", "unknown"}:
        return (), (
            Diagnostic(
                "RUNTIME_STATE_INDETERMINATE",
                "Runtime route presence is partial or unknown.",
                harness=group.harness,
                route_identity=group.route_identity,
                evidence_source="runtime-inventory",
            ),
        )
    operations: list[str] = []
    if retirement:
        if presence == "absent":
            if immutable_target is not None and immutable_content != freeze_json(
                {"status": "route_absent"}
            ):
                return (), (
                    Diagnostic(
                        "IMMUTABLE_CONTENT_UNVERIFIED",
                        "Immutable content evidence does not support the observed route presence.",
                        harness=group.harness,
                        route_identity=group.route_identity,
                        evidence_source="runtime-inventory",
                    ),
                )
            return (), ()
        if immutable_target is not None and immutable_content != immutable_target:
            return (), (
                Diagnostic(
                    "IMMUTABLE_CONTENT_UNVERIFIED",
                    "A reviewed immutable retirement may remove only its exact locked content.",
                    harness=group.harness,
                    route_identity=group.route_identity,
                    evidence_source="runtime-inventory",
                ),
            )
        if (
            enablement == "enabled"
            and _effective_disposition(matrix, "disable") == "automated"
        ):
            operations.append("disable")
        if _effective_disposition(matrix, "remove") == "automated":
            operations.append("remove")
        elif presence != "absent":
            return (), (
                Diagnostic(
                    "DESIRED_STATE_UNREACHABLE",
                    "A reviewed retirement cannot reach its absent state.",
                    harness=group.harness,
                    route_identity=group.route_identity,
                    evidence_source="operation-matrix",
                ),
            )
        return tuple(operations), ()

    if immutable_target is not None:
        if presence == "present":
            if immutable_content != immutable_target:
                if not (
                    isinstance(immutable_content, FrozenJsonObject)
                    and immutable_content.get("status") == "observed"
                ):
                    return (), (
                        Diagnostic(
                            "IMMUTABLE_CONTENT_UNVERIFIED",
                            "Immutable content cannot be reconciled without exact observed provenance and restore authority.",
                            harness=group.harness,
                            route_identity=group.route_identity,
                            evidence_source="runtime-inventory",
                        ),
                    )
                if _effective_disposition(matrix, "restore") != "automated":
                    return (), (
                        Diagnostic(
                            "DESIRED_STATE_UNREACHABLE",
                            "Immutable content repair is not automated by the reviewed operation matrix.",
                            harness=group.harness,
                            route_identity=group.route_identity,
                            evidence_source="operation-matrix",
                        ),
                    )
                operations.append("restore")
        elif presence == "absent" and immutable_content != freeze_json(
            {"status": "route_absent"}
        ):
            return (), (
                Diagnostic(
                    "IMMUTABLE_CONTENT_UNVERIFIED",
                    "Immutable content evidence does not support the observed route presence.",
                    harness=group.harness,
                    route_identity=group.route_identity,
                    evidence_source="runtime-inventory",
                ),
            )

    if (
        group.controlled_equipment_identities
        and matrix.get("component_control_mode") != "automated"
        and not configuration_matches
    ):
        return (), (
            Diagnostic(
                "DESIRED_STATE_UNREACHABLE",
                "Nonautomated selected component controls cannot reconcile configuration drift.",
                harness=group.harness,
                route_identity=group.route_identity,
                evidence_source="operation-matrix",
            ),
        )

    if presence == "absent":
        if _effective_disposition(matrix, "install") == "automated":
            operations.append("install")
        elif _effective_disposition(matrix, "configure") == "automated":
            operations.append("configure")
        else:
            return (), (
                Diagnostic(
                    "DESIRED_STATE_UNREACHABLE",
                    "An active route cannot reach its present state.",
                    harness=group.harness,
                    route_identity=group.route_identity,
                    evidence_source="operation-matrix",
                ),
            )
    if (
        not configuration_matches
        and "configure" not in operations
        and _effective_disposition(matrix, "configure") == "automated"
    ):
        operations.append("configure")
    if (
        enablement != "enabled"
        and _effective_disposition(matrix, "enable") == "automated"
    ):
        operations.append("enable")
    return tuple(operations), ()


def _logical_action(
    key: str,
    group: _RouteLike,
    capability: CapabilityRecord,
    inventory: RuntimeInventory,
    operation: str,
) -> _LogicalNode:
    desired_state = _desired_state(operation, group)
    desired_state_digest = canonical_json_sha256(desired_state)
    scope = _surface_scope(capability, group)
    if scope is None:
        raise ValueError("selected capability surface rule is invalid")
    definition = freeze_json(
        {
            "candidate_identity": inventory.candidate_identity,
            "implementation_manifest_digest": inventory.implementation_manifest_digest,
            "catalog_digest": inventory.catalog_digest,
            "lock_digest": inventory.lock_digest,
            "capability_identity": capability.capability_identity,
            "capability_digest": capability.capability_digest,
            "manager_version_evidence_digest": (
                capability.manager_version_evidence_digest
            ),
            "adapter_identity": capability.adapter_identity,
            "adapter_version": capability.adapter_version,
            "harness": group.harness,
            "route_identity": group.route_identity,
            "route_digest": canonical_json_sha256(group.route),
            "route_record": group.route,
            "equipment_identities": list(group.equipment_identities),
            "controlled_equipment_identities": list(
                group.controlled_equipment_identities
            ),
            "activation_group": group.activation_group,
            "surface_scope": list(scope),
            "operation": operation,
            "operation_disposition": "automated",
            "desired_state": desired_state,
            "desired_state_digest": desired_state_digest,
            "secret_references": group.route.get("secret_references"),
        }
    )
    assert isinstance(definition, FrozenJsonObject)
    return _LogicalNode(
        key=key,
        kind="mutation",
        semantic_key=(
            "\x1f".join(group.equipment_identities),
            group.harness,
            group.route_identity,
            operation,
            desired_state_digest,
        ),
        definition=definition,
    )


def _logical_verification(
    key: str,
    purpose: str,
    *,
    inventory: RuntimeInventory,
    predicate: FrozenJsonObject,
    group: _RouteLike | None = None,
    capability: CapabilityRecord | None = None,
    active_activation_membership: tuple[FrozenJsonObject, ...] = (),
    read_surface_scope: tuple[str, ...] | None = None,
) -> _LogicalNode:
    harness = group.harness if group is not None else ""
    route_identity = group.route_identity if group is not None else ""
    derived_scope = (
        _surface_scope(capability, group)
        if read_surface_scope is None and group is not None and capability is not None
        else read_surface_scope
        if read_surface_scope is not None
        else ()
    )
    if derived_scope is None:
        raise ValueError("selected capability surface rule is invalid")
    predicate_field = (
        "coverage_predicate"
        if purpose == "final_coverage"
        else "projector_policy_predicate"
        if purpose == "projector_readiness"
        else "normalized_state_predicate"
    )
    semantic_definition: dict[str, object] = {
        "purpose": purpose,
        "harness": harness,
        "route_identity": route_identity,
        "activation_group": group.activation_group if group is not None else "",
        "active_equipment_identities": (
            list(group.equipment_identities) if group is not None else []
        ),
        "controlled_equipment_identities": (
            list(group.controlled_equipment_identities) if group is not None else []
        ),
        "read_surface_scope": list(derived_scope),
        predicate_field: predicate,
    }
    if purpose == "final_coverage":
        semantic_definition["active_activation_membership"] = list(
            active_activation_membership
        )
    predicate_digest = canonical_json_sha256(predicate)
    definition = freeze_json(
        semantic_definition
        | {
            "candidate_identity": inventory.candidate_identity,
            "implementation_manifest_digest": inventory.implementation_manifest_digest,
            "catalog_digest": inventory.catalog_digest,
            "lock_digest": inventory.lock_digest,
            "inventory_digest": inventory.digest,
            "capability_identity": (
                capability.capability_identity if capability is not None else None
            ),
            "capability_digest": (
                capability.capability_digest if capability is not None else None
            ),
            "predicate_digest": predicate_digest,
        }
    )
    assert isinstance(definition, FrozenJsonObject)
    return _LogicalNode(
        key=key,
        kind="verification",
        semantic_key=(
            purpose,
            harness,
            route_identity,
            predicate_digest,
            canonical_json_sha256(definition),
        ),
        definition=definition,
    )


def _preferred_route_by_coverage(
    validated: ValidatedCatalogLock,
) -> dict[tuple[str, str], str]:
    preferred: dict[tuple[str, str], str] = {}
    for coverage in validated.coverage:
        selection = coverage.record.get("provider_selection")
        if not isinstance(selection, FrozenJsonObject):
            continue
        route_identity = selection.get("preferred_route")
        if type(route_identity) is str:
            preferred[(coverage.equipment_identity, coverage.harness)] = route_identity
    return preferred


def _activation_membership(
    active_groups: tuple[_RouteGroup, ...],
) -> tuple[FrozenJsonObject, ...]:
    records: list[FrozenJsonObject] = []
    for group in active_groups:
        record = freeze_json(
            {
                "harness": group.harness,
                "route_identity": group.route_identity,
                "activation_group": group.activation_group,
                "active_equipment_identities": list(group.equipment_identities),
                "controlled_equipment_identities": list(
                    group.controlled_equipment_identities
                ),
            }
        )
        assert isinstance(record, FrozenJsonObject)
        records.append(record)
    return tuple(records)


def _route_state_predicate_record(
    group: _RouteLike,
    capability: CapabilityRecord,
    matrix: FrozenJsonObject,
    *,
    retirement: bool,
) -> FrozenJsonObject:
    scope = _surface_scope(capability, group)
    if scope is None:
        raise ValueError("selected capability surface rule is invalid")
    if retirement:
        expected = freeze_json({"route_presence": "absent"})
        assert isinstance(expected, FrozenJsonObject)
    else:
        if not isinstance(group, _RouteGroup):
            raise TypeError("active route predicate requires an active route group")
        expected = _active_state_target(group, matrix)
    normalized_predicate = _normalized_state_predicate("contains", expected)
    record: dict[str, object] = {
        "disposition": "retirement" if retirement else "active",
        "harness": group.harness,
        "route_identity": group.route_identity,
        "route_digest": canonical_json_sha256(group.route),
        "activation_group": group.activation_group,
        "active_equipment_identities": list(group.equipment_identities),
        "controlled_equipment_identities": list(group.controlled_equipment_identities),
        "capability_identity": capability.capability_identity,
        "capability_digest": capability.capability_digest,
        "read_surface_scope": list(scope),
        "normalized_state_predicate": normalized_predicate,
        "normalized_state_predicate_digest": canonical_json_sha256(
            normalized_predicate
        ),
    }
    if isinstance(group, _RetirementRouteGroup):
        record["retirement_identity"] = group.retirement_identity
    frozen = freeze_json(record)
    assert isinstance(frozen, FrozenJsonObject)
    return frozen


def _preferred_provider_kind(coverage: CoverageRecord) -> str | None:
    selection = coverage.record.get("provider_selection")
    if not isinstance(selection, FrozenJsonObject):
        return None
    preferred_route = selection.get("preferred_route")
    routes = selection.get("routes")
    if type(preferred_route) is not str or type(routes) is not tuple:
        raise TypeError("validated coverage selection is unavailable")
    matching = tuple(
        route
        for route in routes
        if isinstance(route, FrozenJsonObject)
        and route.get("identity") == preferred_route
    )
    if len(matching) != 1:
        raise ValueError("validated coverage preferred route is ambiguous")
    provider = matching[0].get("provider")
    if not isinstance(provider, FrozenJsonObject):
        raise TypeError("validated coverage provider is unavailable")
    kind = provider.get("kind")
    if type(kind) is not str:
        raise TypeError("validated coverage provider kind is unavailable")
    return kind


def _projector_policy_predicate(
    validated: ValidatedCatalogLock,
    inventory: RuntimeInventory,
) -> FrozenJsonObject:
    included: list[str] = []
    excluded: list[str] = []
    for coverage in validated.coverage:
        if coverage.harness != "claude" or not coverage.equipment_identity.startswith(
            "skill:"
        ):
            continue
        target = (
            included
            if _preferred_provider_kind(coverage) == "standalone_skill"
            else excluded
        )
        target.append(coverage.equipment_identity)
    policy: dict[str, object] = {
        "mode": "catalog_driven",
        "harness": "claude",
        "control_surface": _CLAUDE_PROJECTOR_CONTROL_SURFACE,
        "included_skill_identities": sorted(included),
        "excluded_skill_identities": sorted(excluded),
        "implementation_manifest_digest": inventory.implementation_manifest_digest,
        "catalog_digest": validated.catalog.digest,
        "lock_digest": validated.lock.digest,
    }
    policy["policy_digest"] = canonical_json_sha256(policy)
    predicate = freeze_json({"operator": "equals", "desired_policy": policy})
    assert isinstance(predicate, FrozenJsonObject)
    return predicate


def _requires_catalog_projector(
    winner: _RouteGroup,
    losing_groups: list[_RetirementRouteGroup],
) -> bool:
    return winner.harness == "claude" and any(
        isinstance(provider := losing.route.get("provider"), FrozenJsonObject)
        and provider.get("kind") == "standalone_skill"
        for losing in losing_groups
    )


def _final_coverage_predicate(
    validated: ValidatedCatalogLock,
    active_groups: tuple[_RouteGroup, ...],
    retirement_groups: tuple[_RetirementRouteGroup, ...],
    selected_capabilities: dict[tuple[str, str], CapabilityRecord],
    matrices: dict[tuple[str, str], FrozenJsonObject],
) -> tuple[
    FrozenJsonObject,
    tuple[FrozenJsonObject, ...],
    tuple[str, ...],
]:
    membership = _activation_membership(active_groups)
    route_records: list[FrozenJsonObject] = []
    read_surfaces: set[str] = set()
    grouped_routes: list[tuple[str, str, bool, _RouteLike]] = [
        (group.harness, group.route_identity, False, group) for group in active_groups
    ] + [
        (group.harness, group.route_identity, True, group)
        for group in retirement_groups
    ]
    for harness, route_identity, retirement, group in sorted(grouped_routes):
        route_key = (harness, route_identity)
        record = _route_state_predicate_record(
            group,
            selected_capabilities[route_key],
            matrices[route_key],
            retirement=retirement,
        )
        route_records.append(record)
        scope = record.get("read_surface_scope")
        if type(scope) is not tuple:
            raise TypeError("route predicate read scope must be immutable")
        for surface in scope:
            if type(surface) is not str:
                raise TypeError("route predicate read scope must contain strings")
            read_surfaces.add(surface)
    complete_scope = tuple(sorted(read_surfaces))
    predicate = freeze_json(
        {
            "operator": "all",
            "coverage_membership": list(_provider_selection_records(validated)),
            "active_activation_membership": list(membership),
            "route_state_predicates": route_records,
            "read_surface_scope": list(complete_scope),
        }
    )
    assert isinstance(predicate, FrozenJsonObject)
    return predicate, membership, complete_scope


def _derive_logical_plan(
    validated: ValidatedCatalogLock,
    inventory: RuntimeInventory,
    active_groups: tuple[_RouteGroup, ...],
    retirement_groups: tuple[_RetirementRouteGroup, ...],
    selected_capabilities: dict[tuple[str, str], CapabilityRecord],
    matrices: dict[tuple[str, str], FrozenJsonObject],
    observations: dict[tuple[str, str], RuntimeObservation],
) -> tuple[
    tuple[_LogicalNode, ...],
    tuple[tuple[str, str], ...],
    tuple[Diagnostic, ...],
]:
    nodes: list[_LogicalNode] = []
    edges: list[tuple[str, str]] = []
    diagnostics: list[Diagnostic] = []
    action_keys: dict[tuple[str, str], tuple[str, ...]] = {}

    all_groups: tuple[_RouteLike, ...] = (*active_groups, *retirement_groups)
    active_keys = {(group.harness, group.route_identity) for group in active_groups}
    for group in all_groups:
        route_key = (group.harness, group.route_identity)
        observation = observations[route_key]
        matrix = matrices[route_key]
        operations, action_diagnostics = _action_operations(
            group,
            observation,
            matrix,
            retirement=route_key not in active_keys,
        )
        diagnostics.extend(action_diagnostics)
        capability = selected_capabilities[route_key]
        keys: list[str] = []
        for operation in operations:
            key = f"mutation:{group.harness}:{group.route_identity}:{operation}"
            nodes.append(
                _logical_action(
                    key,
                    group,
                    capability,
                    inventory,
                    operation,
                )
            )
            if keys:
                edges.append((keys[-1], key))
            keys.append(key)
        action_keys[route_key] = tuple(keys)

    if diagnostics:
        return (), (), tuple(diagnostics)

    active_by_key = {
        (group.harness, group.route_identity): group for group in active_groups
    }
    preferred = _preferred_route_by_coverage(validated)
    retirement_by_winner: dict[tuple[str, str], list[_RetirementRouteGroup]] = {}
    for retirement in retirement_groups:
        equipment_identity = retirement.equipment_identities[0]
        winner_identity = preferred.get((equipment_identity, retirement.harness))
        winner_key = (
            (retirement.harness, winner_identity)
            if winner_identity is not None
            else None
        )
        if winner_key is None or winner_key not in active_by_key:
            diagnostics.append(
                Diagnostic(
                    "PLAN_PROVIDER_SWITCH_INCOMPLETE",
                    "A losing route has no complete preferred-winner dependency.",
                    equipment_identity=equipment_identity,
                    harness=retirement.harness,
                    route_identity=retirement.route_identity,
                    evidence_source="resolved-coverage",
                )
            )
            continue
        retirement_by_winner.setdefault(winner_key, []).append(retirement)

    if diagnostics:
        return (), (), tuple(diagnostics)

    projector_winner_keys = {
        winner_key
        for winner_key, losing_groups in retirement_by_winner.items()
        if _requires_catalog_projector(active_by_key[winner_key], losing_groups)
    }
    projector_readiness_key = "verification:claude:projector-readiness"
    if projector_winner_keys:
        nodes.append(
            _logical_verification(
                projector_readiness_key,
                "projector_readiness",
                inventory=inventory,
                predicate=_projector_policy_predicate(validated, inventory),
                read_surface_scope=(_CLAUDE_PROJECTOR_CONTROL_SURFACE,),
            )
        )

    for winner_key, losing_groups in sorted(retirement_by_winner.items()):
        winner = active_by_key[winner_key]
        capability = selected_capabilities[winner_key]
        activation_key = (
            f"verification:{winner.harness}:{winner.route_identity}:winner-activation"
        )
        nodes.append(
            _logical_verification(
                activation_key,
                "winner_activation",
                inventory=inventory,
                predicate=_normalized_state_predicate(
                    "contains",
                    _active_state_target(winner, matrices[winner_key]),
                ),
                group=winner,
                capability=capability,
            )
        )
        winner_actions = action_keys[winner_key]
        if winner_actions:
            if winner_key in projector_winner_keys:
                edges.append((projector_readiness_key, winner_actions[0]))
            edges.append((winner_actions[-1], activation_key))
        elif winner_key in projector_winner_keys:
            edges.append((projector_readiness_key, activation_key))
        for losing in losing_groups:
            losing_actions = action_keys[(losing.harness, losing.route_identity)]
            if losing_actions:
                edges.append((activation_key, losing_actions[0]))

    coverage_predicate, activation_membership, complete_scope = (
        _final_coverage_predicate(
            validated,
            active_groups,
            retirement_groups,
            selected_capabilities,
            matrices,
        )
    )
    final_key = "verification:final-coverage"
    nodes.append(
        _logical_verification(
            final_key,
            "final_coverage",
            inventory=inventory,
            predicate=coverage_predicate,
            active_activation_membership=activation_membership,
            read_surface_scope=complete_scope,
        )
    )
    successor_keys = {predecessor for predecessor, _ in edges}
    node_keys = {node.key for node in nodes}
    for sink in sorted(node_keys - successor_keys - {final_key}):
        edges.append((sink, final_key))
    return tuple(nodes), tuple(edges), ()


def _make_resolution(
    *,
    command: str,
    diagnostics: tuple[Diagnostic, ...],
    coverage: tuple[CoverageRecord, ...],
    provider_selections: tuple[FrozenJsonObject, ...],
    operation_matrix: tuple[FrozenJsonObject, ...],
    overlays: tuple[FrozenJsonObject, ...],
    candidate_plan: ValidatedPlan | None,
) -> Resolution:
    mutation_plan = candidate_plan if command == "apply" else None
    digest = _resolution_digest(
        command,
        diagnostics,
        coverage,
        provider_selections,
        operation_matrix,
        overlays,
        candidate_plan,
        mutation_plan,
    )
    return Resolution(
        command=command,
        diagnostics=diagnostics,
        coverage=coverage,
        provider_selections=provider_selections,
        operation_matrix=operation_matrix,
        overlays=overlays,
        candidate_plan=candidate_plan,
        mutation_plan=mutation_plan,
        digest=digest,
    )


def resolve(
    command: str,
    catalog: Catalog,
    lock: ResolvedLock,
    inventory: RuntimeInventory,
    capabilities: CapabilityDiscovery,
) -> Resolution:
    """Resolve immutable desired and observed state without side effects."""

    if command not in {"audit", "apply"}:
        raise ValueError("resolver command must be audit or apply")
    if type(catalog) is not Catalog or type(lock) is not ResolvedLock:
        raise TypeError("resolver requires typed catalog and lock models")
    if type(inventory) is not RuntimeInventory:
        raise TypeError("resolver requires one typed runtime inventory")
    if type(capabilities) is not CapabilityDiscovery or capabilities.error is not None:
        raise TypeError("resolver requires one successful capability discovery")

    admitted_capabilities = admit_capability_discovery(
        thaw_json(capabilities.as_json())
    )
    if (
        isinstance(admitted_capabilities, AdapterError)
        or admitted_capabilities != capabilities
    ):
        diagnostic = (
            Diagnostic(
                admitted_capabilities.code,
                admitted_capabilities.message,
                evidence_source="capability-discovery",
            )
            if isinstance(admitted_capabilities, AdapterError)
            else Diagnostic(
                "CAPABILITY_DISCOVERY_INVALID",
                "Capability discovery failed admission.",
                evidence_source="capability-discovery",
            )
        )
        return _make_resolution(
            command=command,
            diagnostics=(diagnostic,),
            coverage=(),
            provider_selections=(),
            operation_matrix=(),
            overlays=(),
            candidate_plan=None,
        )

    admitted_inventory = admit_runtime_inventory(
        [thaw_json(inventory.capabilities.as_json())],
        [
            {
                "record_type": "RuntimeObservation",
                "record": thaw_json(observation.document),
            }
            for observation in inventory.observations
        ],
    )
    if isinstance(admitted_inventory, AdapterError) or admitted_inventory != inventory:
        diagnostic = (
            Diagnostic(
                admitted_inventory.code,
                admitted_inventory.message,
                evidence_source="runtime-inventory",
            )
            if isinstance(admitted_inventory, AdapterError)
            else Diagnostic(
                "RUNTIME_INVENTORY_INVALID",
                "Runtime inventory failed admission.",
                evidence_source="runtime-inventory",
            )
        )
        return _make_resolution(
            command=command,
            diagnostics=(diagnostic,),
            coverage=(),
            provider_selections=(),
            operation_matrix=(),
            overlays=(),
            candidate_plan=None,
        )

    validation = validate_catalog_lock(
        thaw_json(catalog.document),
        thaw_json(lock.document),
    )
    if validation.model is None:
        return _make_resolution(
            command=command,
            diagnostics=validation.diagnostics,
            coverage=(),
            provider_selections=(),
            operation_matrix=(),
            overlays=(),
            candidate_plan=None,
        )
    validated = validation.model
    provider_selections = _provider_selection_records(validated)
    active_groups = _active_route_groups(validated)
    retirement_groups = _retirement_route_groups(validated)
    overlays = _overlay_proposals(active_groups)
    diagnostics: list[Diagnostic] = []

    if (
        validated.catalog != catalog
        or validated.lock != lock
        or inventory.catalog_digest != catalog.digest
        or inventory.lock_digest != lock.digest
    ):
        diagnostics.append(
            Diagnostic(
                "RUNTIME_INVENTORY_BINDING_MISMATCH",
                "Runtime inventory does not bind the exact catalog and lock.",
                evidence_source="runtime-inventory",
            )
        )
    if inventory.capabilities != capabilities:
        diagnostics.append(
            Diagnostic(
                "CAPABILITY_SET_MISMATCH",
                "Runtime inventory and resolver capability sets differ.",
                evidence_source="capability-discovery",
            )
        )

    all_groups: tuple[_RouteLike, ...] = (*active_groups, *retirement_groups)
    selected_capabilities: dict[tuple[str, str], CapabilityRecord] = {}
    matrices: dict[tuple[str, str], FrozenJsonObject] = {}
    matrix_records: list[FrozenJsonObject] = []
    for group in all_groups:
        route_key = (group.harness, group.route_identity)
        capability = _matching_capability(group, capabilities.records)
        if capability is None:
            diagnostics.append(
                Diagnostic(
                    "CAPABILITY_SELECTION_AMBIGUOUS",
                    "A route does not have exactly one matching capability.",
                    harness=group.harness,
                    route_identity=group.route_identity,
                    evidence_source="capability-discovery",
                )
            )
            continue
        selected_capabilities[route_key] = capability
        diagnostics.extend(_component_control_diagnostics(group, capability))
        matrix, matrix_diagnostics = _operation_matrix(group, capability)
        matrices[route_key] = matrix
        matrix_records.append(matrix)
        diagnostics.extend(matrix_diagnostics)

    observations, observation_diagnostics = _observation_by_route(inventory)
    diagnostics.extend(observation_diagnostics)
    expected_keys = {(group.harness, group.route_identity) for group in all_groups}
    for harness, route_identity in sorted(expected_keys - set(observations)):
        diagnostics.append(
            Diagnostic(
                "RUNTIME_OBSERVATION_MISSING",
                "Runtime inventory is missing one required route observation.",
                harness=harness,
                route_identity=route_identity,
                evidence_source="runtime-inventory",
            )
        )
    for harness, route_identity in sorted(set(observations) - expected_keys):
        diagnostics.append(
            Diagnostic(
                "RUNTIME_OBSERVATION_UNEXPECTED",
                "Runtime inventory contains an unselected route observation.",
                harness=harness,
                route_identity=route_identity,
                evidence_source="runtime-inventory",
            )
        )
    for group in all_groups:
        route_key = (group.harness, group.route_identity)
        observation = observations.get(route_key)
        capability = selected_capabilities.get(route_key)
        if observation is None or capability is None:
            continue
        diagnostics.extend(
            _observation_binding_diagnostics(group, capability, observation)
        )
        diagnostics.extend(_route_state_coherence_diagnostics(group, observation))
        diagnostics.extend(_native_rolling_version_diagnostics(group, observation))

    operation_matrix = tuple(
        sorted(
            matrix_records,
            key=lambda matrix: (
                str(matrix.get("harness")),
                str(matrix.get("route_identity")),
            ),
        )
    )
    if contains_literal_credential(
        {
            "provider_selections": provider_selections,
            "operation_matrix": operation_matrix,
            "overlays": overlays,
        }
    ):
        diagnostics.append(
            Diagnostic(
                "RESOLUTION_LITERAL_SECRET",
                "Resolved output contains prohibited literal secret material.",
                evidence_source="resolver-output",
            )
        )

    if diagnostics:
        return _make_resolution(
            command=command,
            diagnostics=tuple(diagnostics),
            coverage=validated.coverage,
            provider_selections=provider_selections,
            operation_matrix=operation_matrix,
            overlays=overlays,
            candidate_plan=None,
        )

    logical_nodes, dependency_keys, plan_diagnostics = _derive_logical_plan(
        validated,
        inventory,
        active_groups,
        retirement_groups,
        selected_capabilities,
        matrices,
        observations,
    )
    if plan_diagnostics:
        return _make_resolution(
            command=command,
            diagnostics=plan_diagnostics,
            coverage=validated.coverage,
            provider_selections=provider_selections,
            operation_matrix=operation_matrix,
            overlays=overlays,
            candidate_plan=None,
        )
    plan_result = _build_validated_plan(
        candidate_identity=inventory.candidate_identity,
        implementation_manifest_digest=inventory.implementation_manifest_digest,
        catalog_digest=catalog.digest,
        lock_digest=lock.digest,
        inventory_digest=inventory.digest,
        capability_set_digest=capabilities.digest,
        logical_nodes=logical_nodes,
        dependency_keys=dependency_keys,
    )
    if plan_result.diagnostics:
        return _make_resolution(
            command=command,
            diagnostics=plan_result.diagnostics,
            coverage=validated.coverage,
            provider_selections=provider_selections,
            operation_matrix=operation_matrix,
            overlays=overlays,
            candidate_plan=None,
        )
    assert plan_result.plan is not None
    if contains_literal_credential(plan_result.plan.as_json()):
        return _make_resolution(
            command=command,
            diagnostics=(
                Diagnostic(
                    "RESOLUTION_LITERAL_SECRET",
                    "Resolved plan contains prohibited literal secret material.",
                    evidence_source="resolver-output",
                ),
            ),
            coverage=validated.coverage,
            provider_selections=provider_selections,
            operation_matrix=operation_matrix,
            overlays=overlays,
            candidate_plan=None,
        )
    return _make_resolution(
        command=command,
        diagnostics=(),
        coverage=validated.coverage,
        provider_selections=provider_selections,
        operation_matrix=operation_matrix,
        overlays=overlays,
        candidate_plan=plan_result.plan,
    )


def _route_controls(route: FrozenJsonObject) -> tuple[str, ...]:
    controls = route.get("component_controls")
    if type(controls) is not tuple:
        raise ValueError("validated route controls are unavailable")
    identities: list[str] = []
    for control in controls:
        if not isinstance(control, FrozenJsonObject):
            raise TypeError("validated route control must be frozen JSON")
        identity = control.get("equipment_identity")
        if type(identity) is not str:
            raise ValueError("validated route control identity is unavailable")
        identities.append(identity)
    return tuple(sorted(identities))


def _active_route_groups(
    validated: ValidatedCatalogLock,
) -> tuple[_RouteGroup, ...]:
    """Return exact active groups after applying component controls."""

    routes: dict[tuple[str, str], FrozenJsonObject] = {}
    memberships: dict[tuple[str, str], set[str]] = {}
    for coverage in validated.coverage:
        selection = coverage.record.get("provider_selection")
        if not isinstance(selection, FrozenJsonObject):
            continue
        route_documents = selection.get("routes")
        if type(route_documents) is not tuple:
            raise ValueError("validated provider routes are unavailable")
        for route in route_documents:
            if not isinstance(route, FrozenJsonObject):
                raise TypeError("validated route must be frozen JSON")
            route_identity = route.get("identity")
            if type(route_identity) is not str:
                raise ValueError("validated route identity is unavailable")
            key = (coverage.harness, route_identity)
            previous = routes.setdefault(key, route)
            if previous != route:
                raise ValueError("active route definitions must be identical")
            memberships.setdefault(key, set()).add(coverage.equipment_identity)

    groups: list[_RouteGroup] = []
    for (harness, route_identity), route in sorted(routes.items()):
        activation_group = route.get("activation_group")
        if type(activation_group) is not str:
            raise ValueError("validated activation group is unavailable")
        groups.append(
            _RouteGroup(
                harness=harness,
                route_identity=route_identity,
                activation_group=activation_group,
                equipment_identities=tuple(
                    sorted(memberships[(harness, route_identity)])
                ),
                controlled_equipment_identities=_route_controls(route),
                route=route,
            )
        )
    return tuple(groups)


def _retirement_route_groups(
    validated: ValidatedCatalogLock,
) -> tuple[_RetirementRouteGroup, ...]:
    """Return only the reviewed immutable retirement records."""

    retirement_documents = validated.lock.document.get("retirements")
    if type(retirement_documents) is not tuple:
        raise ValueError("validated retirements are unavailable")
    groups: list[_RetirementRouteGroup] = []
    for retirement in retirement_documents:
        if not isinstance(retirement, FrozenJsonObject):
            raise TypeError("validated retirement must be frozen JSON")
        route = retirement.get("route")
        if not isinstance(route, FrozenJsonObject):
            raise TypeError("validated retirement route must be frozen JSON")
        retirement_identity = retirement.get("identity")
        harness = retirement.get("harness")
        equipment_identity = retirement.get("equipment_identity")
        desired_state = retirement.get("desired_state")
        route_identity = route.get("identity")
        activation_group = route.get("activation_group")
        if not all(
            type(value) is str
            for value in (
                retirement_identity,
                harness,
                equipment_identity,
                desired_state,
                route_identity,
                activation_group,
            )
        ):
            raise ValueError("validated retirement bindings are unavailable")
        assert isinstance(retirement_identity, str)
        assert isinstance(harness, str)
        assert isinstance(equipment_identity, str)
        assert isinstance(desired_state, str)
        assert isinstance(route_identity, str)
        assert isinstance(activation_group, str)
        groups.append(
            _RetirementRouteGroup(
                retirement_identity=retirement_identity,
                harness=harness,
                route_identity=route_identity,
                activation_group=activation_group,
                equipment_identities=(equipment_identity,),
                controlled_equipment_identities=_route_controls(route),
                desired_state=desired_state,
                route=route,
            )
        )
    return tuple(sorted(groups, key=lambda group: group.retirement_identity))


@dataclass(frozen=True, slots=True)
class _LogicalNode:
    """One closed semantic graph node before plan-bound identities exist."""

    key: str
    kind: str
    semantic_key: tuple[str, ...]
    definition: FrozenJsonObject

    def __post_init__(self) -> None:
        if type(self.key) is not str or not self.key:
            raise ValueError("logical node key must be a nonempty string")
        if self.kind not in {"mutation", "verification"}:
            raise ValueError("logical node kind must be mutation or verification")
        if type(self.semantic_key) is not tuple or not self.semantic_key:
            raise ValueError("logical node semantic key must be a nonempty tuple")
        if any(type(part) is not str for part in self.semantic_key):
            raise TypeError("logical node semantic key members must be strings")
        if type(self.definition) is not FrozenJsonObject:
            raise TypeError("logical node definition must be a frozen JSON object")
        if self.kind == "verification":
            purpose = self.definition.get("purpose")
            if purpose not in _VERIFICATION_PURPOSES:
                raise ValueError("verification node purpose is not supported")


@dataclass(frozen=True, slots=True)
class _PlanBuildResult:
    """Atomic result of graph validation and plan construction."""

    plan: ValidatedPlan | None
    diagnostics: tuple[Diagnostic, ...]

    def __post_init__(self) -> None:
        if (self.plan is None) == (not self.diagnostics):
            raise ValueError("plan build must return either one plan or diagnostics")


def _diagnostic(code: str, message: str) -> _PlanBuildResult:
    return _PlanBuildResult(None, (Diagnostic(code, message),))


@dataclass(frozen=True, slots=True)
class _NormalizedLogicalGraph:
    nodes: tuple[_LogicalNode, ...]
    edges: tuple[tuple[str, str], ...]


def _logical_node_order(node: _LogicalNode) -> tuple[tuple[str, ...], str, str]:
    return (
        node.semantic_key,
        canonical_json_sha256(node.definition),
        node.key,
    )


def _mutation_surface_scope(node: _LogicalNode) -> tuple[str, ...] | None:
    scope = node.definition.get("surface_scope")
    if (
        type(scope) is not tuple
        or not scope
        or any(type(surface) is not str or not surface for surface in scope)
        or len(scope) != len(set(scope))
    ):
        return None
    return scope  # type: ignore[return-value]


def _mutation_surface_authority(node: _LogicalNode) -> FrozenJsonObject:
    """Project route-independent authority for one physical mutation surface."""

    route_local_fields = {
        "capability_identity",
        "capability_digest",
        "manager_version_evidence_digest",
        "adapter_identity",
        "adapter_version",
        "harness",
        "route_identity",
        "route_digest",
        "route_record",
        "equipment_identities",
        "controlled_equipment_identities",
        "activation_group",
    }
    authority_fields: dict[str, object] = {
        field: value
        for field, value in node.definition.items()
        if field not in route_local_fields
    }
    route = node.definition.get("route_record")
    if isinstance(route, FrozenJsonObject):
        authority_fields["route_surface_authority"] = {
            field: route.get(field)
            for field in (
                "control_owner",
                "distribution",
                "provider",
                "provenance",
                "restore",
                "secret_references",
            )
        }
    authority = freeze_json(authority_fields)
    assert isinstance(authority, FrozenJsonObject)
    return authority


def _mutation_route_writer(node: _LogicalNode) -> FrozenJsonObject:
    writer = freeze_json(
        {
            field: node.definition.get(field)
            for field in (
                "harness",
                "route_identity",
                "capability_identity",
                "capability_digest",
                "manager_version_evidence_digest",
                "adapter_identity",
                "adapter_version",
                "activation_group",
            )
        }
    )
    assert isinstance(writer, FrozenJsonObject)
    return writer


def _ordered_route_mutations(
    nodes: tuple[_LogicalNode, ...],
    edges: set[tuple[str, str]],
) -> tuple[_LogicalNode, ...] | None:
    by_key = {node.key: node for node in nodes}
    successors: dict[str, set[str]] = {key: set() for key in by_key}
    indegree = {key: 0 for key in by_key}
    for predecessor, successor in edges:
        if predecessor in by_key and successor in by_key:
            successors[predecessor].add(successor)
            indegree[successor] += 1
    ready = sorted(
        (node for node in nodes if indegree[node.key] == 0),
        key=_logical_node_order,
    )
    ordered: list[_LogicalNode] = []
    while ready:
        node = ready.pop(0)
        ordered.append(node)
        for successor in sorted(successors[node.key]):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(by_key[successor])
                ready.sort(key=_logical_node_order)
    return tuple(ordered) if len(ordered) == len(nodes) else None


def _merged_desired_state(
    nodes: tuple[_LogicalNode, ...],
    edges: set[tuple[str, str]],
) -> FrozenJsonObject | None:
    ordered = _ordered_route_mutations(nodes, edges)
    if ordered is None:
        return None
    merged: dict[str, object] = {}
    for node in ordered:
        desired_state = node.definition.get("desired_state")
        if not isinstance(desired_state, FrozenJsonObject):
            return None
        merged.update(desired_state)
    result = freeze_json(merged)
    assert isinstance(result, FrozenJsonObject)
    return result


def _coalesced_route_verification(
    dependents: tuple[_LogicalNode, ...],
    writers: tuple[_LogicalNode, ...],
    edges: set[tuple[str, str]],
    *,
    inventory_digest: str,
) -> _LogicalNode | None:
    if not dependents or not writers:
        return None
    ordered_dependents = _ordered_route_mutations(dependents, edges)
    ordered_writers = _ordered_route_mutations(writers, edges)
    if ordered_dependents is None or ordered_writers is None:
        return None
    dependent = ordered_dependents[0]
    desired_state = _merged_desired_state(dependents, edges)
    if desired_state is None:
        return None
    predicate = _normalized_state_predicate("contains", desired_state)
    copied_fields = (
        "candidate_identity",
        "implementation_manifest_digest",
        "catalog_digest",
        "lock_digest",
        "capability_identity",
        "capability_digest",
        "manager_version_evidence_digest",
        "adapter_identity",
        "adapter_version",
        "harness",
        "route_identity",
        "route_digest",
        "route_record",
        "activation_group",
        "secret_references",
    )
    definition_fields: dict[str, object] = {
        field: dependent.definition.get(field)
        for field in copied_fields
        if dependent.definition.get(field) is not None
    }
    definition_fields.update(
        {
            "purpose": "coalesced_route_state",
            "inventory_digest": inventory_digest,
            "active_equipment_identities": dependent.definition.get(
                "equipment_identities", ()
            ),
            "controlled_equipment_identities": dependent.definition.get(
                "controlled_equipment_identities", ()
            ),
            "read_surface_scope": dependent.definition.get("surface_scope", ()),
            "coalesced_operations": [
                node.definition.get("operation") for node in ordered_dependents
            ],
            "coalesced_writer": {
                "harness": ordered_writers[0].definition.get("harness"),
                "route_identity": ordered_writers[0].definition.get("route_identity"),
                "surface_scope": ordered_writers[0].definition.get("surface_scope"),
            },
            "surface_authority_digest": canonical_json_sha256(
                [_mutation_surface_authority(node) for node in ordered_writers]
            ),
            "normalized_state_predicate": predicate,
            "predicate_digest": canonical_json_sha256(predicate),
        }
    )
    definition = freeze_json(definition_fields)
    assert isinstance(definition, FrozenJsonObject)
    harness = dependent.definition.get("harness")
    route_identity = dependent.definition.get("route_identity")
    if type(harness) is not str or type(route_identity) is not str:
        return None
    predicate_digest = canonical_json_sha256(predicate)
    scope_digest = canonical_json_sha256(
        {"surface_scope": dependent.definition.get("surface_scope", ())}
    )
    return _LogicalNode(
        key=(
            "verification:coalesced-route-state:"
            f"{harness}:{route_identity}:{scope_digest}"
        ),
        kind="verification",
        semantic_key=(
            "coalesced_route_state",
            harness,
            route_identity,
            predicate_digest,
            canonical_json_sha256(definition),
        ),
        definition=definition,
    )


def _verification_definition_is_valid(node: _LogicalNode) -> bool:
    purpose = node.definition.get("purpose")
    predicate_field = (
        "coverage_predicate"
        if purpose == "final_coverage"
        else "projector_policy_predicate"
        if purpose == "projector_readiness"
        else "normalized_state_predicate"
    )
    predicate = node.definition.get(predicate_field)
    if not isinstance(predicate, FrozenJsonObject) or node.definition.get(
        "predicate_digest"
    ) != canonical_json_sha256(predicate):
        return False
    if purpose == "final_coverage":
        return (
            predicate.get("operator") == "all"
            and type(predicate.get("coverage_membership")) is tuple
            and type(predicate.get("active_activation_membership")) is tuple
            and type(predicate.get("route_state_predicates")) is tuple
            and type(predicate.get("read_surface_scope")) is tuple
            and node.definition.get("active_activation_membership")
            == predicate.get("active_activation_membership")
            and node.definition.get("read_surface_scope")
            == predicate.get("read_surface_scope")
        )
    if purpose == "projector_readiness":
        desired_policy = predicate.get("desired_policy")
        if (
            set(predicate) != {"operator", "desired_policy"}
            or predicate.get("operator") != "equals"
            or not isinstance(desired_policy, FrozenJsonObject)
            or set(desired_policy)
            != {
                "mode",
                "harness",
                "control_surface",
                "included_skill_identities",
                "excluded_skill_identities",
                "implementation_manifest_digest",
                "catalog_digest",
                "lock_digest",
                "policy_digest",
            }
        ):
            return False
        included = desired_policy.get("included_skill_identities")
        excluded = desired_policy.get("excluded_skill_identities")
        if (
            type(included) is not tuple
            or type(excluded) is not tuple
            or any(
                type(identity) is not str or not identity.startswith("skill:")
                for identity in (*included, *excluded)
            )
        ):
            return False
        included_identities = tuple(
            identity for identity in included if isinstance(identity, str)
        )
        excluded_identities = tuple(
            identity for identity in excluded if isinstance(identity, str)
        )
        if (
            included_identities != tuple(sorted(set(included_identities)))
            or excluded_identities != tuple(sorted(set(excluded_identities)))
            or set(included_identities) & set(excluded_identities)
        ):
            return False
        policy_payload = thaw_json(desired_policy)
        if type(policy_payload) is not dict:
            return False
        policy_digest = policy_payload.pop("policy_digest", None)
        return (
            desired_policy.get("mode") == "catalog_driven"
            and desired_policy.get("harness") == "claude"
            and desired_policy.get("control_surface")
            == _CLAUDE_PROJECTOR_CONTROL_SURFACE
            and desired_policy.get("implementation_manifest_digest")
            == node.definition.get("implementation_manifest_digest")
            and desired_policy.get("catalog_digest")
            == node.definition.get("catalog_digest")
            and desired_policy.get("lock_digest") == node.definition.get("lock_digest")
            and policy_digest == canonical_json_sha256(policy_payload)
            and node.definition.get("harness") == ""
            and node.definition.get("route_identity") == ""
            and node.definition.get("activation_group") == ""
            and node.definition.get("active_equipment_identities") == ()
            and node.definition.get("controlled_equipment_identities") == ()
            and node.definition.get("capability_identity") is None
            and node.definition.get("capability_digest") is None
            and node.definition.get("read_surface_scope")
            == (_CLAUDE_PROJECTOR_CONTROL_SURFACE,)
        )
    return predicate.get("operator") in {"equals", "contains"} and isinstance(
        predicate.get("expected"), FrozenJsonObject
    )


def _normalize_logical_graph(
    logical_nodes: tuple[_LogicalNode, ...],
    dependency_keys: tuple[tuple[str, str], ...],
    *,
    inventory_digest: str,
) -> _NormalizedLogicalGraph | _PlanBuildResult:
    nodes_by_original_key: dict[str, _LogicalNode] = {}
    unique_nodes: list[_LogicalNode] = []
    for node in logical_nodes:
        previous = nodes_by_original_key.get(node.key)
        if previous is None:
            nodes_by_original_key[node.key] = node
            unique_nodes.append(node)
        elif previous != node:
            return _diagnostic(
                "PLAN_NODE_DUPLICATE", "The plan contains a duplicate node."
            )

    original_edges: set[tuple[str, str]] = set()
    for edge in dependency_keys:
        if (
            type(edge) is not tuple
            or len(edge) != 2
            or any(type(endpoint) is not str for endpoint in edge)
        ):
            return _diagnostic(
                "PLAN_DEPENDENCY_INVALID", "The plan contains an invalid dependency."
            )
        if edge in original_edges:
            return _diagnostic(
                "PLAN_DEPENDENCY_DUPLICATE",
                "The plan contains a duplicate dependency.",
            )
        original_edges.add(edge)

    exact_mutations: dict[tuple[tuple[str, ...], FrozenJsonObject], _LogicalNode] = {}
    exact_aliases: dict[str, str] = {}
    exact_nodes: list[_LogicalNode] = []
    for node in sorted(unique_nodes, key=_logical_node_order):
        if node.kind != "mutation":
            exact_aliases[node.key] = node.key
            exact_nodes.append(node)
            continue
        signature = (node.semantic_key, node.definition)
        canonical = exact_mutations.get(signature)
        if canonical is None:
            exact_mutations[signature] = node
            exact_aliases[node.key] = node.key
            exact_nodes.append(node)
        else:
            exact_aliases[node.key] = canonical.key

    exact_edges: set[tuple[str, str]] = set()
    for predecessor, successor in original_edges:
        remapped = (
            exact_aliases.get(predecessor, predecessor),
            exact_aliases.get(successor, successor),
        )
        if remapped[0] != remapped[1]:
            exact_edges.add(remapped)

    semantic_identities: set[tuple[str, tuple[str, ...]]] = set()
    for node in exact_nodes:
        semantic_identity = (node.kind, node.semantic_key)
        if semantic_identity in semantic_identities:
            return _diagnostic(
                "PLAN_NODE_DUPLICATE", "The plan contains a duplicate node."
            )
        semantic_identities.add(semantic_identity)

    mutation_groups: dict[tuple[str, ...], list[_LogicalNode]] = {}
    scope_by_surface: dict[str, tuple[str, ...]] = {}
    for node in exact_nodes:
        if node.kind != "mutation":
            continue
        scope = _mutation_surface_scope(node)
        if scope is None:
            return _diagnostic(
                "PLAN_NODE_INVALID", "The plan contains an invalid mutation surface."
            )
        for surface in scope:
            previous_scope = scope_by_surface.setdefault(surface, scope)
            if previous_scope != scope:
                return _diagnostic(
                    "PLAN_SURFACE_WRITER_CONFLICT",
                    "The plan assigns overlapping scopes to conflicting writers.",
                )
        mutation_groups.setdefault(scope, []).append(node)

    coalescence_by_action: dict[str, tuple[tuple[str, ...], FrozenJsonObject]] = {}
    writer_by_dependent_action: dict[str, _LogicalNode] = {}
    dependent_verifications: dict[
        tuple[tuple[str, ...], FrozenJsonObject], _LogicalNode
    ] = {}
    writer_nodes_by_coalescence: dict[
        tuple[tuple[str, ...], FrozenJsonObject], tuple[_LogicalNode, ...]
    ] = {}
    for scope, group in mutation_groups.items():
        route_groups: dict[FrozenJsonObject, list[_LogicalNode]] = {}
        for node in group:
            route_groups.setdefault(_mutation_route_writer(node), []).append(node)
        if len(route_groups) < 2:
            continue
        ordered_routes = sorted(
            route_groups.items(),
            key=lambda item: min(
                (_logical_node_order(node) for node in item[1]),
            ),
        )
        _, writer_list = ordered_routes[0]
        writer_nodes = tuple(writer_list)
        writer_by_authority = {
            _mutation_surface_authority(node): node for node in writer_nodes
        }
        if len(writer_by_authority) != len(writer_nodes):
            return _diagnostic(
                "PLAN_SURFACE_WRITER_CONFLICT",
                "One route repeats mutation authority for the same surface.",
            )
        for dependent_route, dependent_list in ordered_routes[1:]:
            dependent_nodes = tuple(dependent_list)
            dependent_by_authority = {
                _mutation_surface_authority(node): node for node in dependent_nodes
            }
            if len(dependent_by_authority) != len(dependent_nodes) or set(
                dependent_by_authority
            ) != set(writer_by_authority):
                return _diagnostic(
                    "PLAN_SURFACE_WRITER_CONFLICT",
                    "The plan assigns one surface to conflicting mutation authority.",
                )
            coalescence = (scope, dependent_route)
            verification = _coalesced_route_verification(
                dependent_nodes,
                writer_nodes,
                exact_edges,
                inventory_digest=inventory_digest,
            )
            if verification is None:
                return _diagnostic(
                    "PLAN_NODE_INVALID",
                    "A coalesced mutation lacks a verifiable desired state.",
                )
            dependent_verifications[coalescence] = verification
            writer_nodes_by_coalescence[coalescence] = writer_nodes
            for authority, dependent in dependent_by_authority.items():
                coalescence_by_action[dependent.key] = coalescence
                writer_by_dependent_action[dependent.key] = writer_by_authority[
                    authority
                ]

    normalized_nodes = [
        node for node in exact_nodes if node.key not in coalescence_by_action
    ]
    normalized_nodes.extend(dependent_verifications.values())
    normalized_edges: set[tuple[str, str]] = set()
    for predecessor, successor in exact_edges:
        predecessor_coalescence = coalescence_by_action.get(predecessor)
        successor_coalescence = coalescence_by_action.get(successor)
        if (
            predecessor_coalescence is not None
            and predecessor_coalescence == successor_coalescence
        ):
            remapped_predecessor = writer_by_dependent_action[predecessor].key
        elif predecessor_coalescence is not None:
            remapped_predecessor = dependent_verifications[predecessor_coalescence].key
        else:
            remapped_predecessor = predecessor
        remapped_successor = (
            writer_by_dependent_action[successor].key
            if successor_coalescence is not None
            else successor
        )
        remapped = (remapped_predecessor, remapped_successor)
        if remapped[0] != remapped[1]:
            normalized_edges.add(remapped)
    for coalescence, verification in dependent_verifications.items():
        writer_nodes = writer_nodes_by_coalescence[coalescence]
        writer_keys = {node.key for node in writer_nodes}
        writer_predecessors = {
            predecessor
            for predecessor, successor in exact_edges
            if predecessor in writer_keys and successor in writer_keys
        }
        terminal_writers = tuple(
            node for node in writer_nodes if node.key not in writer_predecessors
        )
        for writer in terminal_writers:
            normalized_edges.add((writer.key, verification.key))
    return _NormalizedLogicalGraph(
        tuple(sorted(normalized_nodes, key=_logical_node_order)),
        tuple(sorted(normalized_edges)),
    )


def _build_validated_plan(
    *,
    candidate_identity: str,
    implementation_manifest_digest: str,
    catalog_digest: str,
    lock_digest: str,
    inventory_digest: str,
    capability_set_digest: str,
    logical_nodes: tuple[_LogicalNode, ...],
    dependency_keys: tuple[tuple[str, str], ...],
) -> _PlanBuildResult:
    """Validate a logical graph and seal one deterministic immutable plan."""

    if not logical_nodes:
        return _diagnostic("PLAN_GRAPH_EMPTY", "The plan graph is empty.")

    normalized = _normalize_logical_graph(
        logical_nodes,
        dependency_keys,
        inventory_digest=inventory_digest,
    )
    if isinstance(normalized, _PlanBuildResult):
        return normalized
    logical_nodes = normalized.nodes
    dependency_keys = normalized.edges

    by_key: dict[str, _LogicalNode] = {}
    semantic_identities: set[tuple[str, tuple[str, ...]]] = set()
    for node in logical_nodes:
        if node.key in by_key:
            return _diagnostic(
                "PLAN_NODE_DUPLICATE", "The plan contains a duplicate node."
            )
        semantic_identity = (
            node.kind,
            node.semantic_key,
        )
        if semantic_identity in semantic_identities:
            return _diagnostic(
                "PLAN_NODE_DUPLICATE", "The plan contains a duplicate node."
            )
        by_key[node.key] = node
        semantic_identities.add(semantic_identity)
        if node.kind == "verification" and not _verification_definition_is_valid(node):
            return _diagnostic(
                "PLAN_NODE_INVALID", "The plan contains an invalid verification."
            )

    successors: dict[str, set[str]] = {key: set() for key in by_key}
    predecessors: dict[str, set[str]] = {key: set() for key in by_key}
    edge_keys: set[tuple[str, str]] = set()
    for edge in dependency_keys:
        predecessor, successor = edge
        if predecessor not in by_key or successor not in by_key:
            return _diagnostic(
                "PLAN_DEPENDENCY_MISSING",
                "The plan references a missing dependency.",
            )
        if predecessor == successor:
            return _diagnostic(
                "PLAN_DEPENDENCY_CYCLE", "The plan dependency graph contains a cycle."
            )
        if edge in edge_keys:
            return _diagnostic(
                "PLAN_DEPENDENCY_DUPLICATE",
                "The plan contains a duplicate dependency.",
            )
        edge_keys.add(edge)
        successors[predecessor].add(successor)
        predecessors[successor].add(predecessor)

    final_keys = tuple(
        node.key
        for node in logical_nodes
        if node.kind == "verification"
        and node.definition.get("purpose") == "final_coverage"
    )
    if len(final_keys) != 1:
        return _diagnostic(
            "PLAN_ACTION_ORPHANED",
            "The plan does not have exactly one final coverage sink.",
        )
    final_key = final_keys[0]
    if successors[final_key]:
        return _diagnostic(
            "PLAN_ACTION_ORPHANED",
            "The final coverage node must be the plan sink.",
        )

    reaches_final = {final_key}
    pending = deque((final_key,))
    while pending:
        current = pending.popleft()
        for predecessor in predecessors[current]:
            if predecessor not in reaches_final:
                reaches_final.add(predecessor)
                pending.append(predecessor)
    if reaches_final != set(by_key):
        return _diagnostic(
            "PLAN_ACTION_ORPHANED",
            "Every plan node must lead to final coverage.",
        )

    indegree = {key: len(predecessors[key]) for key in by_key}
    ready: list[tuple[tuple[str, ...], str, str]] = []
    for key, count in indegree.items():
        if count == 0:
            node = by_key[key]
            heapq.heappush(
                ready,
                (
                    node.semantic_key,
                    canonical_json_sha256(node.definition),
                    key,
                ),
            )

    ordered_keys: list[str] = []
    while ready:
        _, _, key = heapq.heappop(ready)
        ordered_keys.append(key)
        for successor in sorted(successors[key]):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                node = by_key[successor]
                heapq.heappush(
                    ready,
                    (
                        node.semantic_key,
                        canonical_json_sha256(node.definition),
                        successor,
                    ),
                )

    if len(ordered_keys) != len(by_key):
        return _diagnostic(
            "PLAN_DEPENDENCY_CYCLE", "The plan dependency graph contains a cycle."
        )

    ordinal_by_key = {key: ordinal for ordinal, key in enumerate(ordered_keys)}
    ordinal_edges = tuple(
        sorted(
            (ordinal_by_key[predecessor], ordinal_by_key[successor])
            for predecessor, successor in edge_keys
        )
    )
    preimage_value = freeze_json(
        {
            "schema_version": _PLAN_PREIMAGE_VERSION,
            "candidate_identity": candidate_identity,
            "implementation_manifest_digest": implementation_manifest_digest,
            "catalog_digest": catalog_digest,
            "lock_digest": lock_digest,
            "inventory_digest": inventory_digest,
            "capability_set_digest": capability_set_digest,
            "nodes": [
                {
                    "ordinal": ordinal_by_key[key],
                    "kind": by_key[key].kind,
                    "definition": by_key[key].definition,
                }
                for key in ordered_keys
            ],
            "edges": [list(edge) for edge in ordinal_edges],
        }
    )
    assert isinstance(preimage_value, FrozenJsonObject)
    plan_digest = canonical_json_sha256(preimage_value)

    identities: dict[str, str] = {}
    plan_nodes: list[PlanNode] = []
    for key in ordered_keys:
        node = by_key[key]
        ordinal = ordinal_by_key[key]
        predecessor_keys = tuple(
            sorted(predecessors[key], key=ordinal_by_key.__getitem__)
        )
        predecessor_identities = tuple(
            identities[predecessor] for predecessor in predecessor_keys
        )
        if node.kind == "mutation":
            route_identity = node.definition.get("route_identity")
            operation = node.definition.get("operation")
            desired_state_digest = node.definition.get("desired_state_digest")
            if not all(
                type(value) is str
                for value in (route_identity, operation, desired_state_digest)
            ):
                return _diagnostic(
                    "PLAN_NODE_INVALID", "The plan contains an invalid mutation."
                )
            identity = "action:" + canonical_json_sha256(
                {
                    "plan_digest": plan_digest,
                    "ordinal": ordinal,
                    "route_id": route_identity,
                    "operation": operation,
                    "desired_state_digest": desired_state_digest,
                }
            )
        else:
            semantic_definition_digest = canonical_json_sha256(node.definition)
            identity = "verification:" + canonical_json_sha256(
                {
                    "plan_digest": plan_digest,
                    "ordinal": ordinal,
                    "semantic_definition_digest": semantic_definition_digest,
                    "predecessor_identities": predecessor_identities,
                }
            )
        identities[key] = identity
        plan_nodes.append(
            PlanNode(
                key=key,
                kind=node.kind,
                ordinal=ordinal,
                identity=identity,
                dependencies=predecessor_identities,
                definition=node.definition,
            )
        )

    final_edges = tuple(
        (identities[ordered_keys[predecessor]], identities[ordered_keys[successor]])
        for predecessor, successor in ordinal_edges
    )
    return _PlanBuildResult(
        ValidatedPlan(tuple(plan_nodes), final_edges, plan_digest, preimage_value),
        (),
    )
