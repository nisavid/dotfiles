"""Bounded, secret-free admission for read-only adapter inventory."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol

from .canonical import canonical_json_bytes, canonical_json_sha256
from .model import (
    AdapterError,
    CapabilityDiscovery,
    CapabilityRecord,
    FrozenJsonObject,
    ObserveRequest,
    RuntimeInventory,
    RuntimeObservation,
    ValidatedCatalogLock,
    _capability_record_sort_key,
    _runtime_inventory_digest,
    freeze_json,
    thaw_json,
)
from .secrets import contains_literal_credential
from .validator import _validate_adapter_contract_document

__all__ = (
    "ReadOnlyAdapter",
    "admit_capability_discovery",
    "admit_observe_request",
    "admit_runtime_inventory",
    "admit_runtime_observation",
    "collect_runtime_inventory",
)

MAX_ADAPTER_SNAPSHOT_BYTES = 1024 * 1024
MAX_CAPABILITY_RECORDS = 256
MAX_OBSERVATION_RECORDS = 4096
MAX_INVENTORY_BYTES = 8 * 1024 * 1024
_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 100_000

_CAPABILITY_INVALID_MESSAGE = "Capability discovery failed admission."
_LITERAL_SECRET_MESSAGE = "The adapter snapshot contains literal secret material."
_OBSERVE_REQUEST_INVALID_MESSAGE = "Observe request failed admission."
_OBSERVATION_INVALID_MESSAGE = "Runtime observation failed admission."
_INVENTORY_INVALID_MESSAGE = "Runtime inventory failed admission."
_COLLECTION_FAILED_MESSAGE = "Read-only adapter collection failed."


class ReadOnlyAdapter(Protocol):
    """The only adapter surface available during runtime inventory."""

    def capabilities(self) -> object:
        """Return one plain or typed CapabilityDiscovery snapshot."""

    def observe(self, request: ObserveRequest) -> object:
        """Return one plain or typed RuntimeObservation snapshot."""


def admit_capability_discovery(snapshot: object) -> CapabilityDiscovery | AdapterError:
    """Admit one complete canonical CapabilityDiscovery snapshot."""

    if _plain_snapshot_canonical_bytes(snapshot, MAX_ADAPTER_SNAPSHOT_BYTES) is None:
        return _admission_error(
            "CAPABILITY_DISCOVERY_INVALID", _CAPABILITY_INVALID_MESSAGE
        )
    return _admit_bounded_capability_discovery(snapshot)


def _admit_bounded_capability_discovery(
    snapshot: object,
) -> CapabilityDiscovery | AdapterError:
    assert type(snapshot) is dict
    if contains_literal_credential(snapshot):
        return _admission_error(
            "ADAPTER_SNAPSHOT_LITERAL_SECRET", _LITERAL_SECRET_MESSAGE
        )
    if not _validate_adapter_contract_document(
        snapshot,
        record_type="CapabilityDiscovery",
    ):
        return _admission_error(
            "CAPABILITY_DISCOVERY_INVALID", _CAPABILITY_INVALID_MESSAGE
        )
    result = snapshot["result"]
    assert type(result) is dict
    if result["status"] == "error":
        return CapabilityDiscovery((), _adapter_error_from_result(result))
    records = result["records"]
    assert type(records) is list
    if not 0 < len(records) <= MAX_CAPABILITY_RECORDS:
        return _admission_error(
            "CAPABILITY_DISCOVERY_INVALID", _CAPABILITY_INVALID_MESSAGE
        )
    if records != sorted(records, key=_capability_sort_key):
        return _admission_error(
            "CAPABILITY_DISCOVERY_INVALID", _CAPABILITY_INVALID_MESSAGE
        )

    admitted: list[CapabilityRecord] = []
    identities: set[str] = set()
    try:
        for record in records:
            assert type(record) is dict
            if not _capability_digests_are_canonical(record):
                return _admission_error(
                    "CAPABILITY_DISCOVERY_INVALID",
                    _CAPABILITY_INVALID_MESSAGE,
                )
            component_support = record["component_control_support"]
            assert type(component_support) is dict
            supported = component_support["supported_equipment_identities"]
            assert type(supported) is list
            if supported != sorted(supported):
                return _admission_error(
                    "CAPABILITY_DISCOVERY_INVALID",
                    _CAPABILITY_INVALID_MESSAGE,
                )
            identity = record["capability_identity"]
            assert type(identity) is str
            if identity in identities:
                return _admission_error(
                    "CAPABILITY_DISCOVERY_INVALID",
                    _CAPABILITY_INVALID_MESSAGE,
                )
            identities.add(identity)
            manager_evidence = record["manager_version_evidence"]
            assert type(manager_evidence) is dict
            frozen = freeze_json(record)
            assert isinstance(frozen, FrozenJsonObject)
            admitted.append(
                CapabilityRecord(
                    document=frozen,
                    capability_identity=identity,
                    adapter_identity=record["adapter_identity"],
                    adapter_version=record["adapter_version"],
                    harness=record["harness"],
                    capability_digest=record["capability_digest"],
                    manager_version_evidence_digest=manager_evidence["evidence_digest"],
                )
            )
        return CapabilityDiscovery(tuple(admitted))
    except (
        AssertionError,
        KeyError,
        TypeError,
        UnicodeError,
        ValueError,
        RecursionError,
    ):
        return _admission_error(
            "CAPABILITY_DISCOVERY_INVALID", _CAPABILITY_INVALID_MESSAGE
        )


def admit_observe_request(snapshot: object) -> ObserveRequest | AdapterError:
    """Admit one closed, read-only ObserveRequest snapshot."""

    if not _plain_snapshot_within_bound(snapshot, MAX_ADAPTER_SNAPSHOT_BYTES):
        return _admission_error(
            "OBSERVE_REQUEST_INVALID",
            _OBSERVE_REQUEST_INVALID_MESSAGE,
        )
    assert type(snapshot) is dict
    if contains_literal_credential(snapshot):
        return _admission_error(
            "ADAPTER_SNAPSHOT_LITERAL_SECRET", _LITERAL_SECRET_MESSAGE
        )
    if not _validate_adapter_contract_document(snapshot, record_type="ObserveRequest"):
        return _admission_error(
            "OBSERVE_REQUEST_INVALID",
            _OBSERVE_REQUEST_INVALID_MESSAGE,
        )
    record = snapshot["record"]
    assert type(record) is dict
    try:
        frozen = freeze_json(record)
        assert isinstance(frozen, FrozenJsonObject)
        return ObserveRequest(
            document=frozen,
            request_identity=record["request_identity"],
            capability_identity=record["capability_identity"],
        )
    except (
        AssertionError,
        KeyError,
        TypeError,
        UnicodeError,
        ValueError,
        RecursionError,
    ):
        return _admission_error(
            "OBSERVE_REQUEST_INVALID",
            _OBSERVE_REQUEST_INVALID_MESSAGE,
        )


def admit_runtime_observation(snapshot: object) -> RuntimeObservation | AdapterError:
    """Admit one closed observation and recompute its normalized-state digest."""

    if _plain_snapshot_canonical_bytes(snapshot, MAX_ADAPTER_SNAPSHOT_BYTES) is None:
        return _admission_error(
            "RUNTIME_OBSERVATION_INVALID",
            _OBSERVATION_INVALID_MESSAGE,
        )
    return _admit_bounded_runtime_observation(snapshot)


def _admit_bounded_runtime_observation(
    snapshot: object,
) -> RuntimeObservation | AdapterError:
    assert type(snapshot) is dict
    if contains_literal_credential(snapshot):
        return _admission_error(
            "ADAPTER_SNAPSHOT_LITERAL_SECRET", _LITERAL_SECRET_MESSAGE
        )
    if not _validate_adapter_contract_document(
        snapshot,
        record_type="RuntimeObservation",
    ):
        return _admission_error(
            "RUNTIME_OBSERVATION_INVALID",
            _OBSERVATION_INVALID_MESSAGE,
        )
    record = snapshot["record"]
    assert type(record) is dict
    result = record["result"]
    assert type(result) is dict
    try:
        error: AdapterError | None = None
        state_digest: str | None = None
        if result["status"] == "ok":
            normalized_state = result["normalized_state"]
            assert type(normalized_state) is dict
            if result["state_digest"] != canonical_json_sha256(normalized_state):
                return _admission_error(
                    "RUNTIME_OBSERVATION_INVALID",
                    _OBSERVATION_INVALID_MESSAGE,
                )
            if not _observation_collections_are_canonical(result, normalized_state):
                return _admission_error(
                    "RUNTIME_OBSERVATION_INVALID",
                    _OBSERVATION_INVALID_MESSAGE,
                )
            state_digest = result["state_digest"]
            assert type(state_digest) is str
        else:
            error = _adapter_error_from_result(result)
        frozen = freeze_json(record)
        assert isinstance(frozen, FrozenJsonObject)
        return RuntimeObservation(
            document=frozen,
            request_identity=record["request_identity"],
            capability_identity=record["capability_identity"],
            route_identity=record["route_identity"],
            state_digest=state_digest,
            error=error,
        )
    except (
        AssertionError,
        KeyError,
        TypeError,
        UnicodeError,
        ValueError,
        RecursionError,
    ):
        return _admission_error(
            "RUNTIME_OBSERVATION_INVALID",
            _OBSERVATION_INVALID_MESSAGE,
        )


def admit_runtime_inventory(
    capability_snapshots: Sequence[object],
    observation_snapshots: Sequence[object],
) -> RuntimeInventory | AdapterError:
    """Admit complete adapter snapshots atomically as one runtime inventory."""

    if (
        type(capability_snapshots) not in {list, tuple}
        or type(observation_snapshots) not in {list, tuple}
        or not capability_snapshots
        or not observation_snapshots
        or len(capability_snapshots) > MAX_CAPABILITY_RECORDS
        or len(observation_snapshots) > MAX_OBSERVATION_RECORDS
    ):
        return _admission_error("RUNTIME_INVENTORY_INVALID", _INVENTORY_INVALID_MESSAGE)
    aggregate_bytes = 0
    records: list[CapabilityRecord] = []
    for snapshot in capability_snapshots:
        encoded = _plain_snapshot_canonical_bytes(
            snapshot,
            MAX_ADAPTER_SNAPSHOT_BYTES,
        )
        if encoded is None:
            return _admission_error(
                "RUNTIME_INVENTORY_INVALID",
                _INVENTORY_INVALID_MESSAGE,
            )
        aggregate_bytes += len(encoded)
        if aggregate_bytes > MAX_INVENTORY_BYTES:
            return _admission_error(
                "RUNTIME_INVENTORY_INVALID",
                _INVENTORY_INVALID_MESSAGE,
            )
        discovery = _admit_bounded_capability_discovery(snapshot)
        if isinstance(discovery, AdapterError):
            return discovery
        if discovery.error is not None:
            return discovery.error
        records.extend(discovery.records)
    observations: list[RuntimeObservation] = []
    for snapshot in observation_snapshots:
        encoded = _plain_snapshot_canonical_bytes(
            snapshot,
            MAX_ADAPTER_SNAPSHOT_BYTES,
        )
        if encoded is None:
            return _admission_error(
                "RUNTIME_INVENTORY_INVALID",
                _INVENTORY_INVALID_MESSAGE,
            )
        aggregate_bytes += len(encoded)
        if aggregate_bytes > MAX_INVENTORY_BYTES:
            return _admission_error(
                "RUNTIME_INVENTORY_INVALID",
                _INVENTORY_INVALID_MESSAGE,
            )
        observation = _admit_bounded_runtime_observation(snapshot)
        if isinstance(observation, AdapterError):
            return observation
        if observation.error is not None:
            return observation.error
        observations.append(observation)
    records.sort(key=_capability_record_sort_key)
    observations.sort(
        key=lambda observation: (
            observation.harness,
            observation.route_identity,
            observation.request_identity,
        )
    )
    if not records or len(records) > MAX_CAPABILITY_RECORDS:
        return _admission_error("RUNTIME_INVENTORY_INVALID", _INVENTORY_INVALID_MESSAGE)
    try:
        capabilities = CapabilityDiscovery(tuple(records))
        observation_tuple = tuple(observations)
        first = observation_tuple[0]
        digest = _runtime_inventory_digest(
            capabilities,
            observation_tuple,
            first.candidate_identity,
            first.implementation_manifest_digest,
            first.catalog_digest,
            first.lock_digest,
        )
        return RuntimeInventory(
            capabilities=capabilities,
            observations=observation_tuple,
            candidate_identity=first.candidate_identity,
            implementation_manifest_digest=first.implementation_manifest_digest,
            catalog_digest=first.catalog_digest,
            lock_digest=first.lock_digest,
            digest=digest,
        )
    except (IndexError, TypeError, UnicodeError, ValueError, RecursionError):
        return _admission_error("RUNTIME_INVENTORY_INVALID", _INVENTORY_INVALID_MESSAGE)


def collect_runtime_inventory(
    adapters: Sequence[ReadOnlyAdapter],
    requests: Sequence[ObserveRequest],
    *,
    validated_catalog_lock: ValidatedCatalogLock,
) -> RuntimeInventory | AdapterError:
    """Call only read-only adapter methods and return one atomic inventory."""

    if (
        type(validated_catalog_lock) is not ValidatedCatalogLock
        or type(adapters) not in {list, tuple}
        or type(requests) not in {list, tuple}
        or not adapters
        or not requests
        or len(adapters) > MAX_CAPABILITY_RECORDS
        or len(requests) > MAX_OBSERVATION_RECORDS
        or any(type(request) is not ObserveRequest for request in requests)
    ):
        return _collection_error()
    for request in requests:
        admitted_request = admit_observe_request(
            {
                "record_type": "ObserveRequest",
                "record": thaw_json(request.document),
            }
        )
        if isinstance(admitted_request, AdapterError):
            return admitted_request
        if admitted_request != request:
            return _collection_error()
    ordered_requests = tuple(
        sorted(
            requests,
            key=lambda request: (
                request.harness,
                request.route_identity,
                request.request_identity,
            ),
        )
    )
    if len({request.request_identity for request in ordered_requests}) != len(
        ordered_requests
    ):
        return _collection_error()
    request_authorities: dict[
        str,
        tuple[FrozenJsonObject, tuple[str, ...], tuple[str, ...]],
    ] = {}
    for request in ordered_requests:
        authority = _request_catalog_authority(request, validated_catalog_lock)
        if authority is None:
            return _admission_error(
                "OBSERVE_REQUEST_INVALID",
                _OBSERVE_REQUEST_INVALID_MESSAGE,
            )
        request_authorities[request.request_identity] = authority

    discoveries: list[CapabilityDiscovery] = []
    capability_adapter: dict[str, ReadOnlyAdapter] = {}
    capability_by_identity: dict[str, CapabilityRecord] = {}
    capability_record_count = 0
    aggregate_bytes = 0
    try:
        for adapter in adapters:
            if aggregate_bytes >= MAX_INVENTORY_BYTES:
                return _collection_error()
            raw_discovery = adapter.capabilities()
            if isinstance(raw_discovery, AdapterError):
                return _readmit_adapter_error(raw_discovery)
            if type(raw_discovery) is CapabilityDiscovery:
                readmitted_discovery = admit_capability_discovery(
                    thaw_json(raw_discovery.as_json())
                )
                if (
                    isinstance(readmitted_discovery, AdapterError)
                    or readmitted_discovery != raw_discovery
                ):
                    return _collection_error()
                discovery_candidate: CapabilityDiscovery | AdapterError = raw_discovery
            else:
                discovery_candidate = admit_capability_discovery(raw_discovery)
            if isinstance(discovery_candidate, AdapterError):
                return discovery_candidate
            discovery = discovery_candidate
            if discovery.error is not None:
                return discovery.error
            next_record_count = capability_record_count + len(discovery.records)
            if next_record_count > MAX_CAPABILITY_RECORDS:
                return _collection_error()
            discovery_bytes = len(canonical_json_bytes(discovery.as_json()))
            next_aggregate_bytes = aggregate_bytes + discovery_bytes
            if next_aggregate_bytes > MAX_INVENTORY_BYTES:
                return _collection_error()
            capability_record_count = next_record_count
            aggregate_bytes = next_aggregate_bytes
            discoveries.append(discovery)
            for record in discovery.records:
                if record.capability_identity in capability_adapter:
                    return _admission_error(
                        "CAPABILITY_DISCOVERY_INVALID",
                        _CAPABILITY_INVALID_MESSAGE,
                    )
                capability_adapter[record.capability_identity] = adapter
                capability_by_identity[record.capability_identity] = record
    except SystemExit:
        return _collection_error()
    except Exception:  # noqa: BLE001 - native adapters are an untrusted boundary
        return _collection_error()

    observations: list[RuntimeObservation] = []
    try:
        for request in ordered_requests:
            if aggregate_bytes >= MAX_INVENTORY_BYTES:
                return _collection_error()
            selected_adapter = capability_adapter.get(request.capability_identity)
            selected_capability = capability_by_identity.get(
                request.capability_identity
            )
            if selected_adapter is None or selected_capability is None:
                return _collection_error()
            _, authorized_equipment, authorized_controls = request_authorities[
                request.request_identity
            ]
            if not _request_matches_capability(
                request,
                selected_capability,
                authorized_equipment=authorized_equipment,
                authorized_controls=authorized_controls,
            ):
                return _admission_error(
                    "OBSERVE_REQUEST_INVALID",
                    _OBSERVE_REQUEST_INVALID_MESSAGE,
                )
            raw_observation = selected_adapter.observe(request)
            if isinstance(raw_observation, AdapterError):
                return _readmit_adapter_error(raw_observation)
            if type(raw_observation) is RuntimeObservation:
                readmitted_observation = admit_runtime_observation(
                    {
                        "record_type": "RuntimeObservation",
                        "record": thaw_json(raw_observation.document),
                    }
                )
                if (
                    isinstance(readmitted_observation, AdapterError)
                    or readmitted_observation != raw_observation
                ):
                    return _collection_error()
                observation_candidate: RuntimeObservation | AdapterError = (
                    raw_observation
                )
            else:
                observation_candidate = admit_runtime_observation(raw_observation)
            if isinstance(observation_candidate, AdapterError):
                return observation_candidate
            observation = observation_candidate
            if observation.error is not None:
                return observation.error
            if not _observation_matches_request(
                observation,
                request,
                selected_capability,
            ):
                return _admission_error(
                    "RUNTIME_OBSERVATION_INVALID",
                    _OBSERVATION_INVALID_MESSAGE,
                )
            observation_bytes = len(
                canonical_json_bytes(
                    {
                        "record_type": "RuntimeObservation",
                        "record": observation.document,
                    }
                )
            )
            next_aggregate_bytes = aggregate_bytes + observation_bytes
            if next_aggregate_bytes > MAX_INVENTORY_BYTES:
                return _collection_error()
            aggregate_bytes = next_aggregate_bytes
            observations.append(observation)
    except SystemExit:
        return _collection_error()
    except Exception:  # noqa: BLE001 - native adapters are an untrusted boundary
        return _collection_error()

    records = sorted(
        (record for discovery in discoveries for record in discovery.records),
        key=_capability_record_sort_key,
    )
    observations.sort(
        key=lambda observation: (
            observation.harness,
            observation.route_identity,
            observation.request_identity,
        )
    )
    try:
        capabilities = (
            discoveries[0]
            if len(discoveries) == 1
            else CapabilityDiscovery(tuple(records))
        )
        observation_tuple = tuple(observations)
        first = observation_tuple[0]
        digest = _runtime_inventory_digest(
            capabilities,
            observation_tuple,
            first.candidate_identity,
            first.implementation_manifest_digest,
            first.catalog_digest,
            first.lock_digest,
        )
        return RuntimeInventory(
            capabilities=capabilities,
            observations=observation_tuple,
            candidate_identity=first.candidate_identity,
            implementation_manifest_digest=first.implementation_manifest_digest,
            catalog_digest=first.catalog_digest,
            lock_digest=first.lock_digest,
            digest=digest,
        )
    except (IndexError, TypeError, UnicodeError, ValueError, RecursionError):
        return _collection_error()


def _request_catalog_authority(
    request: ObserveRequest,
    validated: ValidatedCatalogLock,
) -> tuple[FrozenJsonObject, tuple[str, ...], tuple[str, ...]] | None:
    document = request.document
    if (
        document.get("catalog_digest") != validated.catalog.digest
        or document.get("lock_digest") != validated.lock.digest
    ):
        return None
    active = _active_route_authority(
        validated,
        harness=request.harness,
        route_identity=request.route_identity,
    )
    retirement = _retirement_route_authority(
        validated,
        harness=request.harness,
        route_identity=request.route_identity,
    )
    candidates = tuple(
        candidate for candidate in (active, retirement) if candidate is not None
    )
    if len(candidates) != 1:
        return None
    route, equipment_identities = candidates[0]
    controlled_identities = _route_control_identities(
        route.get("component_controls"),
    )
    if controlled_identities is None:
        return None
    route_identity = route.get("identity")
    activation_group = route.get("activation_group")
    if (
        type(route_identity) is not str
        or type(activation_group) is not str
        or document.get("route_record") != route
        or document.get("route_identity") != route_identity
        or document.get("route_digest") != canonical_json_sha256(route)
        or document.get("activation_group") != activation_group
        or document.get("secret_references") != route.get("secret_references")
        or _frozen_string_tuple(document.get("equipment_identities"))
        != equipment_identities
        or _frozen_string_tuple(document.get("controlled_equipment_identities"))
        != controlled_identities
    ):
        return None
    return route, equipment_identities, controlled_identities


def _active_route_authority(
    validated: ValidatedCatalogLock,
    *,
    harness: str,
    route_identity: str,
) -> tuple[FrozenJsonObject, tuple[str, ...]] | None:
    selected_route: FrozenJsonObject | None = None
    equipment_identities: list[str] = []
    for coverage in validated.coverage:
        if coverage.harness != harness:
            continue
        selection = coverage.record.get("provider_selection")
        if not isinstance(selection, FrozenJsonObject):
            continue
        routes = selection.get("routes")
        if type(routes) is not tuple:
            return None
        matches = tuple(
            route
            for route in routes
            if isinstance(route, FrozenJsonObject)
            and route.get("identity") == route_identity
        )
        if len(matches) > 1:
            return None
        if not matches:
            continue
        route = matches[0]
        if selected_route is None:
            selected_route = route
        elif selected_route != route:
            return None
        equipment_identities.append(coverage.equipment_identity)
    if selected_route is None:
        return None
    ordered_identities = tuple(sorted(equipment_identities))
    if not ordered_identities or len(ordered_identities) != len(
        set(ordered_identities)
    ):
        return None
    return selected_route, ordered_identities


def _retirement_route_authority(
    validated: ValidatedCatalogLock,
    *,
    harness: str,
    route_identity: str,
) -> tuple[FrozenJsonObject, tuple[str, ...]] | None:
    retirements = validated.lock.document.get("retirements")
    if type(retirements) is not tuple:
        return None
    selected_route: FrozenJsonObject | None = None
    equipment_identities: list[str] = []
    for retirement in retirements:
        if not isinstance(retirement, FrozenJsonObject):
            return None
        route = retirement.get("route")
        if retirement.get("harness") != harness:
            continue
        if not isinstance(route, FrozenJsonObject):
            return None
        if route.get("identity") != route_identity:
            continue
        equipment_identity = retirement.get("equipment_identity")
        if type(equipment_identity) is not str:
            return None
        if selected_route is None:
            selected_route = route
        elif selected_route != route:
            return None
        equipment_identities.append(equipment_identity)
    if selected_route is None:
        return None
    ordered_identities = tuple(sorted(equipment_identities))
    if not ordered_identities or len(ordered_identities) != len(
        set(ordered_identities)
    ):
        return None
    return selected_route, ordered_identities


def _observation_matches_request(
    observation: RuntimeObservation,
    request: ObserveRequest,
    capability: CapabilityRecord,
) -> bool:
    echoed_fields = (
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
    )
    if any(
        observation.document.get(field) != request.document.get(field)
        for field in echoed_fields
    ):
        return False
    route = request.document.get("route_record")
    if not isinstance(route, FrozenJsonObject) or observation.document.get(
        "control_owner"
    ) != route.get("control_owner"):
        return False
    result = observation.document.get("result")
    if not isinstance(result, FrozenJsonObject) or result.get("status") != "ok":
        return False
    normalized_state = result.get("normalized_state")
    if not isinstance(normalized_state, FrozenJsonObject):
        return False
    component_identities = _record_identities(
        normalized_state.get("component_states"),
        identity_field="equipment_identity",
    )
    evidence_identities = _record_identities(
        result.get("surface_evidence"),
        identity_field="identity",
    )
    controlled = _frozen_string_tuple(
        request.document.get("controlled_equipment_identities")
    )
    surfaces = _frozen_string_tuple(request.document.get("surface_scope"))
    if component_identities != controlled or evidence_identities != surfaces:
        return False
    restore = route.get("restore")
    native_support = capability.document.get("native_update_support")
    if not isinstance(restore, FrozenJsonObject) or not isinstance(
        native_support, FrozenJsonObject
    ):
        return False
    route_control = restore.get("native_update_control")
    if (
        normalized_state.get("native_update_control") != route_control
        or native_support.get("native_update_control") != route_control
        or not _normalized_state_matches_restore_class(normalized_state, restore)
    ):
        return False
    captured_state = result.get("captured_state")
    purpose = request.document.get("purpose")
    if not isinstance(captured_state, FrozenJsonObject) or type(purpose) is not str:
        return False
    expected_capture = (
        "captured" if purpose in {"capture_pre_state", "recovery"} else "not_applicable"
    )
    if captured_state.get("status") != expected_capture:
        return False
    expected_state_digest = request.document.get("expected_state_digest")
    return (
        expected_state_digest is None
        or observation.state_digest == expected_state_digest
    )


def _normalized_state_matches_restore_class(
    normalized_state: FrozenJsonObject,
    restore: FrozenJsonObject,
) -> bool:
    """Bind normalized evidence tags to the request's reviewed route class."""

    immutable_content = normalized_state.get("immutable_content")
    not_applicable = freeze_json({"status": "not_applicable"})
    restore_class = restore.get("class")
    if restore_class == "native_rolling":
        return immutable_content == not_applicable
    if restore_class != "immutable":
        return False
    status = (
        immutable_content.get("status")
        if isinstance(immutable_content, FrozenJsonObject)
        else None
    )
    presence = normalized_state.get("route_presence")
    presence_matches = (
        (presence == "present" and status in {"observed", "unknown"})
        or (presence == "absent" and status == "route_absent")
        or (presence in {"partial", "unknown"} and status == "unknown")
    )
    manager_not_applicable = freeze_json(
        {
            "status": "not_applicable",
            "reviewed_baseline": None,
            "observation_source": None,
        }
    )
    return (
        presence_matches
        and normalized_state.get("observed_version") == not_applicable
        and normalized_state.get("native_update_control") == "not_applicable"
        and normalized_state.get("native_update_suppression_state") == "not_applicable"
        and normalized_state.get("manager_drift") == manager_not_applicable
    )


def _request_matches_capability(
    request: ObserveRequest,
    capability: CapabilityRecord,
    *,
    authorized_equipment: tuple[str, ...],
    authorized_controls: tuple[str, ...],
) -> bool:
    document = request.document
    if (
        document.get("capability_identity") != capability.capability_identity
        or document.get("capability_digest") != capability.capability_digest
        or document.get("manager_version_evidence_digest")
        != capability.manager_version_evidence_digest
        or document.get("harness") != capability.harness
    ):
        return False
    route = document.get("route_record")
    if not isinstance(route, FrozenJsonObject):
        return False
    if (
        document.get("route_digest") != canonical_json_sha256(route)
        or document.get("route_identity") != route.get("identity")
        or document.get("activation_group") != route.get("activation_group")
        or document.get("secret_references") != route.get("secret_references")
    ):
        return False
    if not _provider_selector_matches(
        capability.document.get("provider_match"),
        route.get("provider"),
        capability.harness,
    ):
        return False
    restore = route.get("restore")
    capability_operations = capability.document.get("operation_support")
    if isinstance(restore, FrozenJsonObject) and restore.get("class") == "immutable":
        inspect_support = (
            capability_operations.get("inspect")
            if isinstance(capability_operations, FrozenJsonObject)
            else None
        )
        normalized_fields = (
            inspect_support.get("normalized_fields")
            if isinstance(inspect_support, FrozenJsonObject)
            else None
        )
        if type(normalized_fields) is not tuple or "immutable_content" not in (
            normalized_fields
        ):
            return False
    equipment = _frozen_string_tuple(document.get("equipment_identities"))
    controlled = _frozen_string_tuple(document.get("controlled_equipment_identities"))
    if (
        equipment != authorized_equipment
        or controlled != authorized_controls
        or not authorized_equipment
    ):
        return False
    if equipment != tuple(sorted(equipment)) or controlled != tuple(sorted(controlled)):
        return False
    route_controls = route.get("component_controls")
    controlled_from_route = _route_control_identities(route_controls)
    if controlled != controlled_from_route:
        return False
    expected_scope = _derive_surface_scope(
        capability,
        request.route_identity,
        tuple(sorted(set(authorized_equipment) | set(authorized_controls))),
    )
    return (
        expected_scope is not None and document.get("surface_scope") == expected_scope
    )


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
        expected_overlay = {
            "claude": "claude_json",
            "codex": "codex_toml",
            "cursor": "cursor_json",
        }.get(harness)
        transport = capability_provider.get("transport")
        return (
            transport is not None
            and transport == route_provider.get("transport")
            and expected_overlay is not None
            and capability_provider.get("overlay_family") == expected_overlay
        )
    return False


def _derive_surface_scope(
    capability: CapabilityRecord,
    route_identity: str,
    equipment_identities: tuple[str, ...],
) -> tuple[str, ...] | None:
    surface_rule = capability.document.get("surface_identity_rule")
    if (
        not isinstance(surface_rule, FrozenJsonObject)
        or surface_rule.get("version") != 1
    ):
        return None
    rule = surface_rule.get("rule")
    if rule == "shared_equipment_identity":
        return tuple(
            sorted(
                f"surface:shared/{equipment_identity}"
                for equipment_identity in equipment_identities
            )
        )
    if rule == "route_and_equipment_identity":
        return tuple(
            sorted(
                f"surface:{route_identity}/{equipment_identity}"
                for equipment_identity in equipment_identities
            )
        )
    if rule == "route_identity":
        return (f"surface:{route_identity}",)
    return None


def _frozen_string_tuple(value: object) -> tuple[str, ...] | None:
    if type(value) is not tuple or any(type(item) is not str for item in value):
        return None
    return value


def _record_identities(
    records: object,
    *,
    identity_field: str,
) -> tuple[str, ...] | None:
    if type(records) is not tuple:
        return None
    identities: list[str] = []
    for record in records:
        if not isinstance(record, FrozenJsonObject):
            return None
        identity = record.get(identity_field)
        if type(identity) is not str:
            return None
        identities.append(identity)
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        return None
    return tuple(identities)


def _route_control_identities(records: object) -> tuple[str, ...] | None:
    if type(records) is not tuple:
        return None
    identities: list[str] = []
    for record in records:
        if not isinstance(record, FrozenJsonObject):
            return None
        identity = record.get("equipment_identity")
        if type(identity) is not str:
            return None
        identities.append(identity)
    if len(identities) != len(set(identities)):
        return None
    return tuple(sorted(identities))


def _collection_error() -> AdapterError:
    return AdapterError(
        code="ADAPTER_COLLECTION_FAILED",
        classification="native_failure",
        message=_COLLECTION_FAILED_MESSAGE,
        retry="after_audit",
        mutation_state="not_started",
    )


def _readmit_adapter_error(error: AdapterError) -> AdapterError:
    admitted = admit_capability_discovery(
        {
            "record_type": "CapabilityDiscovery",
            "result": thaw_json(error.as_json()),
        }
    )
    if isinstance(admitted, AdapterError):
        return admitted
    if admitted.error is None:
        return _collection_error()
    return admitted.error


def _observation_collections_are_canonical(
    result: dict[str, object],
    normalized_state: dict[str, object],
) -> bool:
    components = normalized_state.get("component_states")
    evidence = result.get("surface_evidence")
    if type(components) is not list or type(evidence) is not list:
        return False
    component_identities: list[str] = []
    for component in components:
        if type(component) is not dict:
            return False
        identity = component.get("equipment_identity")
        if type(identity) is not str:
            return False
        component_identities.append(identity)
    if component_identities != sorted(component_identities):
        return False
    if len(component_identities) != len(set(component_identities)):
        return False

    def evidence_key(item: object) -> tuple[str, str, str]:
        if type(item) is not dict:
            return ("", "", "")
        identity = item.get("identity")
        kind = item.get("kind")
        digest = item.get("digest")
        return (
            identity if type(identity) is str else "",
            kind if type(kind) is str else "",
            digest if type(digest) is str else "",
        )

    return evidence == sorted(evidence, key=evidence_key)


def _capability_digests_are_canonical(record: dict[str, object]) -> bool:
    manager_evidence = record.get("manager_version_evidence")
    if type(manager_evidence) is not dict:
        return False
    manager_payload = dict(manager_evidence)
    manager_digest = manager_payload.pop("evidence_digest", None)
    capability_payload = dict(record)
    capability_digest = capability_payload.pop("capability_digest", None)
    try:
        return bool(
            manager_digest == canonical_json_sha256(manager_payload)
            and capability_digest == canonical_json_sha256(capability_payload)
        )
    except (TypeError, UnicodeError, ValueError, RecursionError):
        return False


def _capability_sort_key(record: object) -> tuple[str, ...]:
    if type(record) is not dict:
        return ("", "", "", "", "")
    provider = record.get("provider_match")
    if type(provider) is not dict:
        provider = {}
    kind = provider.get("kind")
    if type(kind) is not str:
        kind = ""
    selector: tuple[object, object] = {
        "standalone_skill": (provider.get("canonical_root"), ""),
        "native_plugin": (provider.get("manager"), provider.get("scope")),
        "direct_mcp": (provider.get("transport"), provider.get("overlay_family")),
    }.get(kind, ("", ""))
    values = (
        record.get("harness"),
        kind,
        *selector,
        record.get("capability_identity"),
    )
    return tuple(value if type(value) is str else "" for value in values)


def _adapter_error_from_result(result: dict[str, object]) -> AdapterError:
    references = result["evidence_references"]
    assert type(references) is list
    frozen_references: list[FrozenJsonObject] = []
    for reference in references:
        frozen = freeze_json(reference)
        assert isinstance(frozen, FrozenJsonObject)
        frozen_references.append(frozen)
    code = result["code"]
    classification = result["classification"]
    message = result["message"]
    retry = result["retry"]
    mutation_state = result["mutation_state"]
    assert type(code) is str
    assert type(classification) is str
    assert type(message) is str
    assert type(retry) is str
    assert type(mutation_state) is str
    return AdapterError(
        code=code,
        classification=classification,
        message=message,
        retry=retry,
        mutation_state=mutation_state,
        evidence_references=tuple(frozen_references),
    )


def _admission_error(code: str, message: str) -> AdapterError:
    return AdapterError(
        code=code,
        classification="invalid_request",
        message=message,
        retry="never",
        mutation_state="not_started",
    )


def _plain_snapshot_canonical_bytes(
    document: object,
    maximum_bytes: int,
) -> bytes | None:
    if maximum_bytes < 0:
        return None
    pending: list[tuple[object, int, bool]] = [(document, 0, False)]
    active_containers: set[int] = set()
    nodes = 0
    estimated_bytes = 0
    try:
        while pending:
            value, depth, leaving = pending.pop()
            if leaving:
                active_containers.discard(id(value))
                continue
            nodes += 1
            estimated_bytes += 8
            if (
                nodes > _MAX_JSON_NODES
                or depth > _MAX_JSON_DEPTH
                or estimated_bytes > maximum_bytes
            ):
                return None
            if value is None or type(value) is bool:
                continue
            if type(value) is int:
                estimated_bytes += len(str(value))
                continue
            if type(value) is float:
                if not math.isfinite(value):
                    return None
                estimated_bytes += len(repr(value))
                continue
            if type(value) is str:
                estimated_bytes += len(value.encode("utf-8"))
                continue
            if type(value) is dict:
                identity = id(value)
                if identity in active_containers:
                    return None
                active_containers.add(identity)
                pending.append((value, depth, True))
                for key, member in value.items():
                    if type(key) is not str:
                        return None
                    estimated_bytes += len(key.encode("utf-8"))
                    pending.append((member, depth + 1, False))
            elif type(value) is list:
                identity = id(value)
                if identity in active_containers:
                    return None
                active_containers.add(identity)
                pending.append((value, depth, True))
                pending.extend((member, depth + 1, False) for member in value)
            else:
                return None
        encoded = canonical_json_bytes(document)
        return encoded if len(encoded) <= maximum_bytes else None
    except (TypeError, UnicodeError, ValueError, RecursionError):
        return None


def _plain_snapshot_within_bound(document: object, maximum_bytes: int) -> bool:
    return _plain_snapshot_canonical_bytes(document, maximum_bytes) is not None
