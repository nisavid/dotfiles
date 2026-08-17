from __future__ import annotations

import copy
import inspect
import json
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "home/private_dot_local/lib/agent-equipment"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from agent_equipment import validator
from agent_equipment.canonical import canonical_json_bytes, canonical_json_sha256
from agent_equipment.inventory import (
    MAX_ADAPTER_SNAPSHOT_BYTES,
    MAX_INVENTORY_BYTES,
    MAX_OBSERVATION_RECORDS,
    admit_capability_discovery,
    admit_observe_request,
    admit_runtime_inventory,
    admit_runtime_observation,
    collect_runtime_inventory,
)
from agent_equipment.model import (
    AdapterError,
    CapabilityDiscovery,
    CapabilitySet,
    Diagnostic,
    FrozenJsonObject,
    ObserveRequest,
    RuntimeInventory,
    RuntimeObservation,
    ValidatedCatalogLock,
    thaw_json,
)
from agent_equipment.validator import (
    _validate_adapter_contract_document,
    load_catalog_lock,
)

FIXTURES = ROOT / "tests/fixtures/agent-equipment/schema"
DOCUMENTS = ROOT / "docs/agent-equipment"

_CATALOG_LOCK_VALIDATION = load_catalog_lock(
    DOCUMENTS / "initial-catalog.proposed.json",
    DOCUMENTS / "initial-lock.proposed.json",
)
assert _CATALOG_LOCK_VALIDATION.model is not None
VALIDATED_CATALOG_LOCK: ValidatedCatalogLock = _CATALOG_LOCK_VALIDATION.model


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def reseal_capability(record: dict[str, object]) -> None:
    manager_evidence = record["manager_version_evidence"]
    assert isinstance(manager_evidence, dict)
    manager_payload = copy.deepcopy(manager_evidence)
    manager_payload.pop("evidence_digest")
    manager_evidence["evidence_digest"] = canonical_json_sha256(manager_payload)
    capability_payload = copy.deepcopy(record)
    capability_payload.pop("capability_digest")
    record["capability_digest"] = canonical_json_sha256(capability_payload)


def bulk_capability_discovery(
    count: int,
    *,
    offset: int,
    include_bound_capability: bool,
) -> dict[str, object]:
    snapshot = load_fixture("valid-adapter-capability-record.json")
    base = snapshot["result"]["records"][0]  # type: ignore[index]
    assert isinstance(base, dict)
    records: list[dict[str, object]] = []
    if include_bound_capability:
        records.append(copy.deepcopy(base))
    generated_count = count - len(records)
    for ordinal in range(offset, offset + generated_count):
        record = copy.deepcopy(base)
        record["capability_identity"] = f"capability:bulk-{ordinal:03d}"
        record["adapter_identity"] = f"adapter:bulk-{ordinal:03d}"
        reseal_capability(record)
        records.append(record)
    records.sort(key=lambda record: str(record["capability_identity"]))
    snapshot["result"]["records"] = records  # type: ignore[index]
    return snapshot


def padded_capability_discovery(
    ordinal: int,
    *,
    padding_bytes: int,
) -> dict[str, object]:
    snapshot = load_fixture("valid-adapter-capability-record.json")
    record = snapshot["result"]["records"][0]  # type: ignore[index]
    assert isinstance(record, dict)
    if ordinal > 0:
        record["capability_identity"] = f"capability:padded-{ordinal:02d}"
        record["adapter_identity"] = f"adapter:padded-{ordinal:02d}"
    manager_evidence = record["manager_version_evidence"]
    assert isinstance(manager_evidence, dict)
    manager_evidence["observation_source"] = "x" * padding_bytes
    reseal_capability(record)
    return snapshot


def bound_observe_request_snapshot() -> dict[str, object]:
    snapshot = load_fixture("valid-adapter-observe-request.json")
    record = snapshot["record"]
    assert isinstance(record, dict)
    route_identity = record["route_identity"]
    harness = record["harness"]
    assert isinstance(route_identity, str)
    assert isinstance(harness, str)

    route: FrozenJsonObject | None = None
    equipment_identities: list[str] = []
    for coverage in VALIDATED_CATALOG_LOCK.coverage:
        if coverage.harness != harness:
            continue
        selection = coverage.record.get("provider_selection")
        if not isinstance(selection, FrozenJsonObject):
            continue
        routes = selection.get("routes")
        assert type(routes) is tuple
        for candidate in routes:
            assert isinstance(candidate, FrozenJsonObject)
            if candidate.get("identity") != route_identity:
                continue
            if route is None:
                route = candidate
            else:
                assert route == candidate
            equipment_identities.append(coverage.equipment_identity)

    assert route is not None
    route_document = thaw_json(route)
    assert isinstance(route_document, dict)
    component_controls = route_document["component_controls"]
    assert isinstance(component_controls, list)
    controlled_identities = sorted(
        control["equipment_identity"]
        for control in component_controls
        if isinstance(control, dict)
        and isinstance(control.get("equipment_identity"), str)
    )
    equipment_identities.sort()
    surfaces = sorted(
        f"surface:{route_identity}/{identity}"
        for identity in set(equipment_identities) | set(controlled_identities)
    )
    record.update(
        {
            "catalog_digest": VALIDATED_CATALOG_LOCK.catalog.digest,
            "lock_digest": VALIDATED_CATALOG_LOCK.lock.digest,
            "route_record": route_document,
            "route_digest": canonical_json_sha256(route_document),
            "equipment_identities": equipment_identities,
            "controlled_equipment_identities": controlled_identities,
            "activation_group": route_document["activation_group"],
            "surface_scope": surfaces,
            "secret_references": copy.deepcopy(route_document["secret_references"]),
        }
    )
    return snapshot


def bound_runtime_observation_snapshot() -> dict[str, object]:
    request_snapshot = bound_observe_request_snapshot()
    request_record = request_snapshot["record"]
    observation = load_fixture("valid-adapter-runtime-observation.json")
    observation_record = observation["record"]
    assert isinstance(request_record, dict)
    assert isinstance(observation_record, dict)
    for field in (
        "catalog_digest",
        "lock_digest",
        "route_identity",
        "route_digest",
        "equipment_identities",
        "controlled_equipment_identities",
        "activation_group",
        "surface_scope",
    ):
        observation_record[field] = copy.deepcopy(request_record[field])
    route_record = request_record["route_record"]
    assert isinstance(route_record, dict)
    observation_record["control_owner"] = route_record["control_owner"]
    result = observation_record["result"]
    assert isinstance(result, dict)
    evidence = result["surface_evidence"]
    assert isinstance(evidence, list)
    evidence_template = evidence[0]
    assert isinstance(evidence_template, dict)
    surfaces = request_record["surface_scope"]
    assert isinstance(surfaces, list)
    result["surface_evidence"] = [
        copy.deepcopy(evidence_template) | {"identity": surface} for surface in surfaces
    ]
    return observation


def padded_runtime_observation(
    request_identity: str,
    *,
    padding_bytes: int,
) -> dict[str, object]:
    observation = bound_runtime_observation_snapshot()
    record = observation["record"]
    assert isinstance(record, dict)
    record["request_identity"] = request_identity
    result = record["result"]
    assert isinstance(result, dict)
    normalized_state = result["normalized_state"]
    assert isinstance(normalized_state, dict)
    manager_drift = normalized_state["manager_drift"]
    assert isinstance(manager_drift, dict)
    manager_drift["observation_source"] = "x" * padding_bytes
    result["state_digest"] = canonical_json_sha256(normalized_state)
    return observation


class CapabilityAdmissionTests(unittest.TestCase):
    def test_valid_discovery_becomes_one_immutable_typed_capability(self) -> None:
        snapshot = load_fixture("valid-adapter-capability-record.json")

        admitted = admit_capability_discovery(snapshot)

        self.assertIsInstance(admitted, CapabilityDiscovery)
        assert isinstance(admitted, CapabilityDiscovery)
        self.assertIsNone(admitted.error)
        self.assertEqual(len(admitted.records), 1)
        capability = admitted.records[0]
        self.assertEqual(
            capability.capability_identity,
            "capability:claude-native-plugin-v1",
        )
        self.assertEqual(capability.harness, "claude")
        self.assertEqual(
            thaw_json(capability.document),
            snapshot["result"]["records"][0],  # type: ignore[index]
        )
        self.assertFalse(hasattr(capability, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            capability.harness = "codex"  # type: ignore[misc]

    def test_one_invalid_capability_rejects_the_entire_discovery(self) -> None:
        valid = load_fixture("valid-adapter-capability-record.json")
        snapshot = copy.deepcopy(valid)
        duplicate = copy.deepcopy(snapshot["result"]["records"][0])  # type: ignore[index]
        duplicate["capability_identity"] = "capability:invalid-digest"
        snapshot["result"]["records"].append(duplicate)  # type: ignore[index,union-attr]

        admitted = admit_capability_discovery(snapshot)

        self.assertIsInstance(admitted, AdapterError)
        assert isinstance(admitted, AdapterError)
        self.assertEqual(admitted.code, "CAPABILITY_DISCOVERY_INVALID")
        self.assertEqual(admitted.message, "Capability discovery failed admission.")

    def test_diagnostic_evidence_source_is_optional_and_validated(self) -> None:
        self.assertIsNone(Diagnostic("CODE", "message").evidence_source)
        self.assertEqual(
            Diagnostic(
                "CODE",
                "message",
                evidence_source="adapter:claude-native-plugin",
            ).evidence_source,
            "adapter:claude-native-plugin",
        )
        with self.assertRaises(TypeError):
            Diagnostic("CODE", "message", evidence_source=1)  # type: ignore[arg-type]

    def test_capability_set_is_the_concrete_discovery_shape(self) -> None:
        self.assertIs(CapabilitySet, CapabilityDiscovery)
        error_snapshot = load_fixture("valid-adapter-capability-error.json")

        admitted = admit_capability_discovery(error_snapshot)

        self.assertIsInstance(admitted, CapabilityDiscovery)
        assert isinstance(admitted, CapabilityDiscovery)
        self.assertEqual(admitted.records, ())
        self.assertIsInstance(admitted.error, AdapterError)
        assert admitted.error is not None
        self.assertEqual(admitted.error.code, "NATIVE_FAILURE")

    def test_manager_and_capability_digests_are_independently_recomputed(self) -> None:
        snapshot = load_fixture("valid-adapter-capability-record.json")
        record = snapshot["result"]["records"][0]  # type: ignore[index]
        assert isinstance(record, dict)
        manager_evidence = record["manager_version_evidence"]
        assert isinstance(manager_evidence, dict)
        manager_evidence["evidence_digest"] = "sha256:" + "0" * 64
        capability_payload = copy.deepcopy(record)
        capability_payload.pop("capability_digest")
        record["capability_digest"] = canonical_json_sha256(capability_payload)

        admitted = admit_capability_discovery(snapshot)

        self.assertIsInstance(admitted, AdapterError)
        assert isinstance(admitted, AdapterError)
        self.assertEqual(admitted.code, "CAPABILITY_DISCOVERY_INVALID")

    def test_duplicate_capability_identity_is_globally_rejected(self) -> None:
        snapshot = load_fixture("valid-adapter-capability-record.json")
        record = snapshot["result"]["records"][0]  # type: ignore[index]
        assert isinstance(record, dict)
        duplicate = copy.deepcopy(record)
        duplicate["adapter_version"] = "2.0.0"
        reseal_capability(duplicate)
        snapshot["result"]["records"].append(duplicate)  # type: ignore[index,union-attr]

        admitted = admit_capability_discovery(snapshot)

        self.assertIsInstance(admitted, AdapterError)

    def test_literal_secret_rejection_uses_one_fixed_redacted_message(self) -> None:
        snapshot = load_fixture("valid-adapter-capability-record.json")
        snapshot["api_key"] = "sk" + "-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"

        admitted = admit_capability_discovery(snapshot)

        self.assertIsInstance(admitted, AdapterError)
        assert isinstance(admitted, AdapterError)
        self.assertEqual(admitted.code, "ADAPTER_SNAPSHOT_LITERAL_SECRET")
        self.assertEqual(
            admitted.message,
            "The adapter snapshot contains literal secret material.",
        )
        self.assertNotIn("sk-", admitted.message)

    def test_adapter_schema_helper_has_no_schema_override_seam(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(_validate_adapter_contract_document).parameters),
            ("document", "record_type"),
        )

    def test_adapter_admission_uses_the_already_captured_schema_set(self) -> None:
        snapshot = load_fixture("valid-adapter-capability-record.json")

        with patch.object(
            validator,
            "_installed_schema_documents",
            side_effect=AssertionError("adapter admission reread Schemas"),
        ):
            valid = _validate_adapter_contract_document(
                snapshot,
                record_type="CapabilityDiscovery",
            )

        self.assertTrue(valid)

    def test_oversized_plain_snapshot_is_rejected_before_schema_admission(self) -> None:
        snapshot = {"padding": "x" * (MAX_ADAPTER_SNAPSHOT_BYTES + 1)}

        admitted = admit_capability_discovery(snapshot)

        self.assertIsInstance(admitted, AdapterError)
        assert isinstance(admitted, AdapterError)
        self.assertEqual(admitted.code, "CAPABILITY_DISCOVERY_INVALID")


class ObservationAdmissionTests(unittest.TestCase):
    def test_valid_observe_request_becomes_an_immutable_detached_record(self) -> None:
        snapshot = load_fixture("valid-adapter-observe-request.json")

        admitted = admit_observe_request(snapshot)

        self.assertIsInstance(admitted, ObserveRequest)
        assert isinstance(admitted, ObserveRequest)
        self.assertEqual(admitted.request_identity, "request:observe-001")
        self.assertEqual(
            admitted.capability_identity,
            "capability:claude-native-plugin-v1",
        )
        snapshot["record"]["request_identity"] = "request:changed"  # type: ignore[index]
        self.assertEqual(
            thaw_json(admitted.document)["request_identity"],
            "request:observe-001",
        )
        self.assertFalse(hasattr(admitted, "__dict__"))

    def test_valid_runtime_observation_recomputes_normalized_state_digest(
        self,
    ) -> None:
        snapshot = load_fixture("valid-adapter-runtime-observation.json")

        admitted = admit_runtime_observation(snapshot)

        self.assertIsInstance(admitted, RuntimeObservation)
        assert isinstance(admitted, RuntimeObservation)
        self.assertIsNone(admitted.error)
        self.assertEqual(
            admitted.state_digest,
            "sha256:6d56a256dad3604063078b0b4c68152f6015b07d97b10a991f5d0a2edea0d2ae",
        )
        self.assertEqual(admitted.route_identity, "route:claude/mattpocock-plugin")

    def test_runtime_observation_accepts_repeated_acyclic_containers(self) -> None:
        snapshot = load_fixture("valid-adapter-runtime-observation.json")
        record = snapshot["record"]
        assert isinstance(record, dict)
        result = record["result"]
        assert isinstance(result, dict)
        normalized_state = result["normalized_state"]
        assert isinstance(normalized_state, dict)
        shared_empty_components: list[object] = []
        record["controlled_equipment_identities"] = shared_empty_components
        normalized_state["component_states"] = shared_empty_components

        admitted = admit_runtime_observation(snapshot)

        self.assertIsInstance(admitted, RuntimeObservation)

    def test_runtime_observation_rejects_a_recursive_container(self) -> None:
        snapshot = load_fixture("valid-adapter-runtime-observation.json")
        recursive: dict[str, object] = {}
        recursive["self"] = recursive
        snapshot["recursive"] = recursive

        admitted = admit_runtime_observation(snapshot)

        self.assertIsInstance(admitted, AdapterError)
        assert isinstance(admitted, AdapterError)
        self.assertEqual(admitted.code, "RUNTIME_OBSERVATION_INVALID")

    def test_tampered_normalized_state_digest_rejects_the_observation(self) -> None:
        snapshot = load_fixture("valid-adapter-runtime-observation.json")
        snapshot["record"]["result"]["normalized_state"]["enablement"] = "enabled"  # type: ignore[index]

        admitted = admit_runtime_observation(snapshot)

        self.assertIsInstance(admitted, AdapterError)
        assert isinstance(admitted, AdapterError)
        self.assertEqual(admitted.code, "RUNTIME_OBSERVATION_INVALID")

    def test_schema_valid_observation_error_remains_typed_and_non_successful(
        self,
    ) -> None:
        snapshot = load_fixture("valid-adapter-runtime-observation.json")
        error = load_fixture("valid-adapter-capability-error.json")["result"]
        snapshot["record"]["result"] = error  # type: ignore[index]

        admitted = admit_runtime_observation(snapshot)

        self.assertIsInstance(admitted, RuntimeObservation)
        assert isinstance(admitted, RuntimeObservation)
        self.assertIsNone(admitted.state_digest)
        self.assertIsInstance(admitted.error, AdapterError)
        assert admitted.error is not None
        self.assertEqual(admitted.error.code, "NATIVE_FAILURE")

    def test_observation_literal_secret_uses_the_same_fixed_message(self) -> None:
        snapshot = load_fixture("valid-adapter-runtime-observation.json")
        snapshot["access_token"] = "gh" + "p_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"

        admitted = admit_runtime_observation(snapshot)

        self.assertIsInstance(admitted, AdapterError)
        assert isinstance(admitted, AdapterError)
        self.assertEqual(admitted.code, "ADAPTER_SNAPSHOT_LITERAL_SECRET")
        self.assertEqual(
            admitted.message,
            "The adapter snapshot contains literal secret material.",
        )


class RuntimeInventoryAdmissionTests(unittest.TestCase):
    def test_inventory_globally_sorts_reversed_capability_snapshots(self) -> None:
        later = load_fixture("valid-adapter-capability-record.json")
        earlier = copy.deepcopy(later)
        earlier_record = earlier["result"]["records"][0]  # type: ignore[index]
        assert isinstance(earlier_record, dict)
        earlier_record["capability_identity"] = "capability:aaa-native-plugin-v1"
        earlier_record["adapter_identity"] = "adapter:aaa-native-plugin"
        reseal_capability(earlier_record)
        observation = load_fixture("valid-adapter-runtime-observation.json")

        admitted = admit_runtime_inventory([later, earlier], [observation])

        self.assertIsInstance(admitted, RuntimeInventory)
        assert isinstance(admitted, RuntimeInventory)
        self.assertEqual(
            tuple(
                record.capability_identity for record in admitted.capabilities.records
            ),
            (
                "capability:aaa-native-plugin-v1",
                "capability:claude-native-plugin-v1",
            ),
        )

    def test_immutable_revision_and_content_each_change_state_and_inventory_digests(
        self,
    ) -> None:
        capability = load_fixture("valid-adapter-capability-record.json")
        base = load_fixture("valid-adapter-runtime-observation.json")
        normalized = base["record"]["result"]["normalized_state"]  # type: ignore[index]
        assert isinstance(normalized, dict)
        normalized["immutable_content"] = {
            "status": "observed",
            "revision": "1" * 40,
            "content_digest": "sha256:" + "2" * 64,
        }
        base["record"]["result"]["state_digest"] = canonical_json_sha256(normalized)  # type: ignore[index]
        revision_changed = copy.deepcopy(base)
        content_changed = copy.deepcopy(base)
        revision_content = revision_changed["record"]["result"]["normalized_state"][  # type: ignore[index]
            "immutable_content"
        ]
        content_content = content_changed["record"]["result"]["normalized_state"][  # type: ignore[index]
            "immutable_content"
        ]
        assert isinstance(revision_content, dict)
        assert isinstance(content_content, dict)
        revision_content["revision"] = "3" * 40
        content_content["content_digest"] = "sha256:" + "4" * 64
        revision_changed["record"]["result"][  # type: ignore[index]
            "state_digest"
        ] = canonical_json_sha256(
            revision_changed["record"]["result"]["normalized_state"]  # type: ignore[index]
        )
        content_changed["record"]["result"][  # type: ignore[index]
            "state_digest"
        ] = canonical_json_sha256(
            content_changed["record"]["result"]["normalized_state"]  # type: ignore[index]
        )

        inventories = tuple(
            admit_runtime_inventory([capability], [observation])
            for observation in (base, revision_changed, content_changed)
        )

        self.assertNotIn(
            True, tuple(isinstance(item, AdapterError) for item in inventories)
        )
        typed = tuple(
            item for item in inventories if isinstance(item, RuntimeInventory)
        )
        self.assertEqual(len(typed), 3)
        self.assertEqual(len({item.observations[0].state_digest for item in typed}), 3)
        self.assertEqual(len({item.digest for item in typed}), 3)

    def test_inventory_digest_ignores_request_identity_sort_order(self) -> None:
        capability = load_fixture("valid-adapter-capability-record.json")
        disabled = load_fixture("valid-adapter-runtime-observation.json")
        enabled = copy.deepcopy(disabled)
        disabled["record"]["request_identity"] = "request:a"  # type: ignore[index]
        enabled["record"]["request_identity"] = "request:z"  # type: ignore[index]
        normalized_state = enabled["record"]["result"]["normalized_state"]  # type: ignore[index]
        assert isinstance(normalized_state, dict)
        normalized_state["enablement"] = "enabled"
        enabled["record"]["result"]["state_digest"] = canonical_json_sha256(  # type: ignore[index]
            normalized_state
        )
        swapped_disabled = copy.deepcopy(disabled)
        swapped_enabled = copy.deepcopy(enabled)
        swapped_disabled["record"]["request_identity"] = "request:z"  # type: ignore[index]
        swapped_enabled["record"]["request_identity"] = "request:a"  # type: ignore[index]

        first = admit_runtime_inventory([capability], [disabled, enabled])
        swapped = admit_runtime_inventory(
            [capability],
            [swapped_disabled, swapped_enabled],
        )

        self.assertIsInstance(first, RuntimeInventory)
        self.assertIsInstance(swapped, RuntimeInventory)
        assert isinstance(first, RuntimeInventory)
        assert isinstance(swapped, RuntimeInventory)
        self.assertEqual(
            tuple(item.request_identity for item in first.observations),
            ("request:a", "request:z"),
        )
        self.assertEqual(
            tuple(item.request_identity for item in swapped.observations),
            ("request:a", "request:z"),
        )
        self.assertEqual(first.digest, swapped.digest)

    def test_inventory_digest_excludes_fresh_observation_metadata(self) -> None:
        capability = load_fixture("valid-adapter-capability-record.json")
        first_observation = load_fixture("valid-adapter-runtime-observation.json")
        fresh_observation = copy.deepcopy(first_observation)
        fresh_observation["record"].update(  # type: ignore[union-attr]
            {
                "request_identity": "request:fresh-002",
                "correlation_identity": "correlation:fresh-002",
                "observed_at": "2026-08-12T16:00:00Z",
            }
        )

        first = admit_runtime_inventory([capability], [first_observation])
        fresh = admit_runtime_inventory([capability], [fresh_observation])

        self.assertIsInstance(first, RuntimeInventory)
        self.assertIsInstance(fresh, RuntimeInventory)
        assert isinstance(first, RuntimeInventory)
        assert isinstance(fresh, RuntimeInventory)
        self.assertEqual(
            first.observations[0].request_identity,
            "request:observe-001",
        )
        self.assertEqual(
            fresh.observations[0].request_identity,
            "request:fresh-002",
        )
        self.assertEqual(
            fresh.observations[0].document["correlation_identity"],
            "correlation:fresh-002",
        )
        self.assertEqual(first.digest, fresh.digest)

    def test_inventory_digest_excludes_observation_timestamps(self) -> None:
        capability = load_fixture("valid-adapter-capability-record.json")
        first_observation = load_fixture("valid-adapter-runtime-observation.json")
        later_observation = copy.deepcopy(first_observation)
        later_observation["record"]["observed_at"] = "2026-08-12T16:00:00Z"  # type: ignore[index]

        first = admit_runtime_inventory([capability], [first_observation])
        later = admit_runtime_inventory([capability], [later_observation])

        self.assertIsInstance(first, RuntimeInventory)
        self.assertIsInstance(later, RuntimeInventory)
        assert isinstance(first, RuntimeInventory)
        assert isinstance(later, RuntimeInventory)
        self.assertEqual(first.digest, later.digest)
        self.assertEqual(first.capabilities.records[0].harness, "claude")
        self.assertEqual(first.candidate_identity, "candidate:001")
        self.assertEqual(
            first.implementation_manifest_digest,
            "sha256:" + "9" * 64,
        )
        self.assertEqual(first.catalog_digest, "sha256:" + "a" * 64)
        self.assertEqual(first.lock_digest, "sha256:" + "b" * 64)

    def test_inventory_rejects_mixed_candidate_bindings(self) -> None:
        capability = load_fixture("valid-adapter-capability-record.json")
        first = load_fixture("valid-adapter-runtime-observation.json")
        second = copy.deepcopy(first)
        second["record"]["request_identity"] = "request:observe-002"  # type: ignore[index]
        second["record"]["candidate_identity"] = "candidate:foreign"  # type: ignore[index]

        admitted = admit_runtime_inventory([capability], [first, second])

        self.assertIsInstance(admitted, AdapterError)
        assert isinstance(admitted, AdapterError)
        self.assertEqual(admitted.code, "RUNTIME_INVENTORY_INVALID")

    def test_inventory_observation_count_is_bounded_before_admission(self) -> None:
        capability = load_fixture("valid-adapter-capability-record.json")
        observation = load_fixture("valid-adapter-runtime-observation.json")

        admitted = admit_runtime_inventory(
            [capability],
            [observation] * (MAX_OBSERVATION_RECORDS + 1),
        )

        self.assertIsInstance(admitted, AdapterError)

    def test_inventory_size_budget_is_incremental_and_serializes_once(self) -> None:
        capability = load_fixture("valid-adapter-capability-record.json")
        observation = load_fixture("valid-adapter-runtime-observation.json")
        encoded_snapshot = b"x" * 950_014
        serialized: list[object] = []

        def serialize(snapshot: object) -> bytes:
            serialized.append(snapshot)
            return encoded_snapshot

        with patch(
            "agent_equipment.inventory.canonical_json_bytes",
            side_effect=serialize,
        ):
            admitted = admit_runtime_inventory([capability], [observation] * 9)

        self.assertIsInstance(admitted, AdapterError)
        self.assertEqual(MAX_INVENTORY_BYTES // len(encoded_snapshot) + 1, 9)
        self.assertEqual(len(serialized), 9)

    def test_inventory_size_budget_short_circuits_4096_aliases(self) -> None:
        capability = load_fixture("valid-adapter-capability-record.json")
        observation = load_fixture("valid-adapter-runtime-observation.json")
        encoded_snapshot = b"x" * 950_014
        cutoff = MAX_INVENTORY_BYTES // len(encoded_snapshot) + 1
        serializations = 0

        def serialize(_: object) -> bytes:
            nonlocal serializations
            if serializations == cutoff:
                raise AssertionError("serialized a snapshot after the size cutoff")
            serializations += 1
            return encoded_snapshot

        with patch(
            "agent_equipment.inventory.canonical_json_bytes",
            side_effect=serialize,
        ):
            admitted = admit_runtime_inventory(
                [capability],
                [observation] * MAX_OBSERVATION_RECORDS,
            )

        self.assertIsInstance(admitted, AdapterError)
        self.assertEqual(cutoff, 9)
        self.assertEqual(serializations, cutoff)


class ReadOnlyCollectorTests(unittest.TestCase):
    def test_capability_system_exit_is_redacted_without_catching_interrupts(
        self,
    ) -> None:
        request = admit_observe_request(bound_observe_request_snapshot())
        assert isinstance(request, ObserveRequest)

        class ExitingAdapter:
            def capabilities(self) -> object:
                raise SystemExit("gh" + "p_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456")

            def observe(self, _: ObserveRequest) -> object:
                raise AssertionError("failed discovery must stop observation")

        collected = collect_runtime_inventory(
            (ExitingAdapter(),),
            (request,),
            validated_catalog_lock=VALIDATED_CATALOG_LOCK,
        )

        self.assertIsInstance(collected, AdapterError)
        assert isinstance(collected, AdapterError)
        self.assertEqual(collected.code, "ADAPTER_COLLECTION_FAILED")
        self.assertEqual(collected.message, "Read-only adapter collection failed.")
        self.assertNotIn("ghp_", collected.message)

        class InterruptedAdapter:
            def capabilities(self) -> object:
                raise KeyboardInterrupt

            def observe(self, _: ObserveRequest) -> object:
                raise AssertionError("failed discovery must stop observation")

        with self.assertRaises(KeyboardInterrupt):
            collect_runtime_inventory(
                (InterruptedAdapter(),),
                (request,),
                validated_catalog_lock=VALIDATED_CATALOG_LOCK,
            )

    def test_observe_system_exit_is_redacted_without_catching_interrupts(
        self,
    ) -> None:
        capability = load_fixture("valid-adapter-capability-record.json")
        request = admit_observe_request(bound_observe_request_snapshot())
        assert isinstance(request, ObserveRequest)

        class ExitingAdapter:
            def capabilities(self) -> object:
                return capability

            def observe(self, _: ObserveRequest) -> object:
                raise SystemExit("gh" + "p_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456")

        collected = collect_runtime_inventory(
            (ExitingAdapter(),),
            (request,),
            validated_catalog_lock=VALIDATED_CATALOG_LOCK,
        )

        self.assertIsInstance(collected, AdapterError)
        assert isinstance(collected, AdapterError)
        self.assertEqual(collected.code, "ADAPTER_COLLECTION_FAILED")
        self.assertEqual(collected.message, "Read-only adapter collection failed.")
        self.assertNotIn("ghp_", collected.message)

        class InterruptedAdapter:
            def capabilities(self) -> object:
                return capability

            def observe(self, _: ObserveRequest) -> object:
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            collect_runtime_inventory(
                (InterruptedAdapter(),),
                (request,),
                validated_catalog_lock=VALIDATED_CATALOG_LOCK,
            )

    def test_observation_byte_budget_stops_before_the_next_observe(self) -> None:
        calls: list[str] = []
        capability = load_fixture("valid-adapter-capability-record.json")
        padding_bytes = 950_000
        request_identities = tuple(
            f"request:observe-{index:03d}" for index in range(10)
        )
        requests: list[ObserveRequest] = []
        observations: dict[str, dict[str, object]] = {}
        for request_identity in request_identities:
            request_snapshot = bound_observe_request_snapshot()
            request_snapshot["record"]["request_identity"] = request_identity  # type: ignore[index]
            request = admit_observe_request(request_snapshot)
            assert isinstance(request, ObserveRequest)
            requests.append(request)
            observations[request_identity] = padded_runtime_observation(
                request_identity,
                padding_bytes=padding_bytes,
            )
        observation_sizes = tuple(
            len(canonical_json_bytes(observations[identity]))
            for identity in request_identities
        )
        self.assertTrue(
            all(size <= MAX_ADAPTER_SNAPSHOT_BYTES for size in observation_sizes)
        )
        running = len(canonical_json_bytes(capability))
        cutoff_index: int | None = None
        for index, size in enumerate(observation_sizes):
            running += size
            if running > MAX_INVENTORY_BYTES:
                cutoff_index = index
                break
        assert cutoff_index is not None
        self.assertLess(cutoff_index + 1, len(requests))

        class Adapter:
            def capabilities(self) -> object:
                calls.append("capabilities")
                return capability

            def observe(self, request: ObserveRequest) -> object:
                calls.append(request.request_identity)
                return observations[request.request_identity]

        collected = collect_runtime_inventory(
            (Adapter(),),
            tuple(requests),
            validated_catalog_lock=VALIDATED_CATALOG_LOCK,
        )

        self.assertIsInstance(collected, AdapterError)
        self.assertEqual(
            calls,
            ["capabilities", *request_identities[: cutoff_index + 1]],
        )

    def test_capability_byte_budget_stops_before_the_next_adapter(self) -> None:
        calls: list[str] = []
        padding_bytes = 950_000
        snapshots = tuple(
            padded_capability_discovery(index, padding_bytes=padding_bytes)
            for index in range(10)
        )
        sizes = tuple(len(canonical_json_bytes(snapshot)) for snapshot in snapshots)
        self.assertTrue(all(size <= MAX_ADAPTER_SNAPSHOT_BYTES for size in sizes))
        running = 0
        cutoff_index: int | None = None
        for index, size in enumerate(sizes):
            running += size
            if running > MAX_INVENTORY_BYTES:
                cutoff_index = index
                break
        assert cutoff_index is not None
        self.assertLess(cutoff_index + 1, len(snapshots))
        request = admit_observe_request(bound_observe_request_snapshot())
        observation = bound_runtime_observation_snapshot()
        assert isinstance(request, ObserveRequest)

        class Adapter:
            def __init__(self, index: int) -> None:
                self.index = index

            def capabilities(self) -> object:
                calls.append(f"capabilities:{self.index}")
                return snapshots[self.index]

            def observe(self, _: ObserveRequest) -> object:
                calls.append(f"observe:{self.index}")
                return observation

        collected = collect_runtime_inventory(
            tuple(Adapter(index) for index in range(len(snapshots))),
            (request,),
            validated_catalog_lock=VALIDATED_CATALOG_LOCK,
        )

        self.assertIsInstance(collected, AdapterError)
        self.assertEqual(
            calls,
            [f"capabilities:{index}" for index in range(cutoff_index + 1)],
        )

    def test_collector_rejects_256_plus_one_flattened_capability_records(
        self,
    ) -> None:
        calls: list[str] = []
        request = admit_observe_request(bound_observe_request_snapshot())
        observation = bound_runtime_observation_snapshot()
        assert isinstance(request, ObserveRequest)

        class FirstAdapter:
            def capabilities(self) -> object:
                calls.append("first.capabilities")
                return bulk_capability_discovery(
                    128,
                    offset=0,
                    include_bound_capability=True,
                )

            def observe(self, _: ObserveRequest) -> object:
                calls.append("first.observe")
                return observation

        class SecondAdapter:
            def capabilities(self) -> object:
                calls.append("second.capabilities")
                return bulk_capability_discovery(
                    129,
                    offset=127,
                    include_bound_capability=False,
                )

            def observe(self, _: ObserveRequest) -> object:
                calls.append("second.observe")
                return observation

        collected = collect_runtime_inventory(
            (FirstAdapter(), SecondAdapter()),
            (request,),
            validated_catalog_lock=VALIDATED_CATALOG_LOCK,
        )

        self.assertIsInstance(collected, AdapterError)
        assert isinstance(collected, AdapterError)
        self.assertEqual(
            calls,
            ["first.capabilities", "second.capabilities"],
        )

    def test_caller_cannot_widen_active_membership_and_matching_read_scope(
        self,
    ) -> None:
        capability = load_fixture("valid-adapter-capability-record.json")
        request_snapshot = bound_observe_request_snapshot()
        request_record = request_snapshot["record"]
        observation = bound_runtime_observation_snapshot()
        observation_record = observation["record"]
        assert isinstance(request_record, dict)
        assert isinstance(observation_record, dict)
        attacker_identity = "skill:attacker/extra"
        attacker_surface = "surface:route:claude/mattpocock-plugin/skill:attacker/extra"
        request_record["equipment_identities"] = sorted(
            [*request_record["equipment_identities"], attacker_identity]  # type: ignore[misc]
        )
        request_record["surface_scope"] = sorted(
            [*request_record["surface_scope"], attacker_surface]  # type: ignore[misc]
        )
        observation_record["equipment_identities"] = copy.deepcopy(
            request_record["equipment_identities"]
        )
        observation_record["surface_scope"] = copy.deepcopy(
            request_record["surface_scope"]
        )
        result = observation_record["result"]
        assert isinstance(result, dict)
        evidence = result["surface_evidence"]
        assert isinstance(evidence, list)
        evidence_template = evidence[0]
        assert isinstance(evidence_template, dict)
        evidence.append(
            copy.deepcopy(evidence_template) | {"identity": attacker_surface}
        )
        evidence.sort(key=lambda item: item["identity"])  # type: ignore[index,return-value]
        request = admit_observe_request(request_snapshot)
        assert isinstance(request, ObserveRequest)

        class Adapter:
            def __init__(self) -> None:
                self.observed = False

            def capabilities(self) -> object:
                return capability

            def observe(self, _: ObserveRequest) -> object:
                self.observed = True
                return observation

        adapter = Adapter()

        collected = collect_runtime_inventory(
            (adapter,),
            (request,),
            validated_catalog_lock=VALIDATED_CATALOG_LOCK,
        )

        self.assertIsInstance(collected, AdapterError)
        assert isinstance(collected, AdapterError)
        self.assertEqual(collected.code, "OBSERVE_REQUEST_INVALID")
        self.assertFalse(adapter.observed)

    def test_collector_calls_only_capabilities_and_observe(self) -> None:
        capability = load_fixture("valid-adapter-capability-record.json")
        observation = bound_runtime_observation_snapshot()
        request_snapshot = bound_observe_request_snapshot()
        request = admit_observe_request(request_snapshot)
        assert isinstance(request, ObserveRequest)

        class Adapter:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def capabilities(self) -> object:
                self.calls.append("capabilities")
                return capability

            def observe(self, received: ObserveRequest) -> object:
                self.calls.append("observe")
                self.assert_request(received)
                return observation

            def assert_request(self, received: ObserveRequest) -> None:
                if received is not request:
                    raise AssertionError("collector replaced the admitted request")

            def apply(self, *_: object) -> object:
                raise AssertionError("collector invoked a mutating adapter method")

        adapter = Adapter()

        collected = collect_runtime_inventory(
            (adapter,),
            (request,),
            validated_catalog_lock=VALIDATED_CATALOG_LOCK,
        )

        self.assertIsInstance(collected, RuntimeInventory)
        self.assertEqual(adapter.calls, ["capabilities", "observe"])

    def test_collector_returns_no_partial_inventory_after_an_exception(self) -> None:
        capability = load_fixture("valid-adapter-capability-record.json")
        first_request_snapshot = bound_observe_request_snapshot()
        second_request_snapshot = copy.deepcopy(first_request_snapshot)
        second_request_snapshot["record"]["request_identity"] = "request:observe-002"  # type: ignore[index]
        first_request = admit_observe_request(first_request_snapshot)
        second_request = admit_observe_request(second_request_snapshot)
        assert isinstance(first_request, ObserveRequest)
        assert isinstance(second_request, ObserveRequest)
        observation = bound_runtime_observation_snapshot()

        class Adapter:
            def capabilities(self) -> object:
                return capability

            def observe(self, request: ObserveRequest) -> object:
                if request.request_identity == "request:observe-002":
                    raise RuntimeError("gh" + "p_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456")
                return observation

        collected = collect_runtime_inventory(
            (Adapter(),),
            (first_request, second_request),
            validated_catalog_lock=VALIDATED_CATALOG_LOCK,
        )

        self.assertIsInstance(collected, AdapterError)
        assert isinstance(collected, AdapterError)
        self.assertEqual(collected.code, "ADAPTER_COLLECTION_FAILED")
        self.assertEqual(collected.message, "Read-only adapter collection failed.")
        self.assertNotIn("ghp_", collected.message)

    def test_collector_preserves_the_single_admitted_capability_set(self) -> None:
        discovery = admit_capability_discovery(
            load_fixture("valid-adapter-capability-record.json")
        )
        request = admit_observe_request(bound_observe_request_snapshot())
        observation = bound_runtime_observation_snapshot()
        assert isinstance(discovery, CapabilityDiscovery)
        assert isinstance(request, ObserveRequest)

        class Adapter:
            def capabilities(self) -> object:
                return discovery

            def observe(self, _: ObserveRequest) -> object:
                return observation

        collected = collect_runtime_inventory(
            (Adapter(),),
            (request,),
            validated_catalog_lock=VALIDATED_CATALOG_LOCK,
        )

        self.assertIsInstance(collected, RuntimeInventory)
        assert isinstance(collected, RuntimeInventory)
        self.assertIs(collected.capabilities, discovery)

    def test_collector_globally_sorts_reversed_adapter_capabilities(self) -> None:
        later = load_fixture("valid-adapter-capability-record.json")
        earlier = copy.deepcopy(later)
        earlier_record = earlier["result"]["records"][0]  # type: ignore[index]
        assert isinstance(earlier_record, dict)
        earlier_record["capability_identity"] = "capability:aaa-native-plugin-v1"
        earlier_record["adapter_identity"] = "adapter:aaa-native-plugin"
        reseal_capability(earlier_record)
        request = admit_observe_request(bound_observe_request_snapshot())
        observation = bound_runtime_observation_snapshot()
        assert isinstance(request, ObserveRequest)

        class Adapter:
            def __init__(self, capability: dict[str, object]) -> None:
                self.capability = capability

            def capabilities(self) -> object:
                return self.capability

            def observe(self, _: ObserveRequest) -> object:
                return observation

        collected = collect_runtime_inventory(
            (Adapter(later), Adapter(earlier)),
            (request,),
            validated_catalog_lock=VALIDATED_CATALOG_LOCK,
        )

        self.assertIsInstance(collected, RuntimeInventory)
        assert isinstance(collected, RuntimeInventory)
        self.assertEqual(
            tuple(
                record.capability_identity for record in collected.capabilities.records
            ),
            (
                "capability:aaa-native-plugin-v1",
                "capability:claude-native-plugin-v1",
            ),
        )

    def test_collector_readmits_typed_adapter_errors_before_returning_them(
        self,
    ) -> None:
        request = admit_observe_request(bound_observe_request_snapshot())
        assert isinstance(request, ObserveRequest)

        class Adapter:
            def capabilities(self) -> object:
                return AdapterError(
                    code="NATIVE_FAILURE",
                    classification="native_failure",
                    message="gh" + "p_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
                    retry="after_audit",
                    mutation_state="not_started",
                )

            def observe(self, _: ObserveRequest) -> object:
                raise AssertionError("failed discovery must stop observation")

        collected = collect_runtime_inventory(
            (Adapter(),),
            (request,),
            validated_catalog_lock=VALIDATED_CATALOG_LOCK,
        )

        self.assertIsInstance(collected, AdapterError)
        assert isinstance(collected, AdapterError)
        self.assertEqual(collected.code, "ADAPTER_SNAPSHOT_LITERAL_SECRET")
        self.assertEqual(
            collected.message,
            "The adapter snapshot contains literal secret material.",
        )

    def test_forged_route_digest_and_read_scope_never_reach_observe(self) -> None:
        capability = load_fixture("valid-adapter-capability-record.json")
        request_snapshot = bound_observe_request_snapshot()
        request_snapshot["record"]["route_digest"] = "sha256:" + "0" * 64  # type: ignore[index]
        request_snapshot["record"]["surface_scope"] = [  # type: ignore[index]
            "surface:attacker/widened"
        ]
        request = admit_observe_request(request_snapshot)
        assert isinstance(request, ObserveRequest)

        class Adapter:
            def __init__(self) -> None:
                self.observed = False

            def capabilities(self) -> object:
                return capability

            def observe(self, _: ObserveRequest) -> object:
                self.observed = True
                raise AssertionError("forged read authority reached the adapter")

        adapter = Adapter()

        collected = collect_runtime_inventory(
            (adapter,),
            (request,),
            validated_catalog_lock=VALIDATED_CATALOG_LOCK,
        )

        self.assertIsInstance(collected, AdapterError)
        assert isinstance(collected, AdapterError)
        self.assertEqual(collected.code, "OBSERVE_REQUEST_INVALID")
        self.assertFalse(adapter.observed)

    def test_observation_must_cover_every_requested_surface(self) -> None:
        capability = load_fixture("valid-adapter-capability-record.json")
        request = admit_observe_request(bound_observe_request_snapshot())
        observation = bound_runtime_observation_snapshot()
        observation["record"]["result"]["surface_evidence"] = []  # type: ignore[index]
        assert isinstance(request, ObserveRequest)

        class Adapter:
            def capabilities(self) -> object:
                return capability

            def observe(self, _: ObserveRequest) -> object:
                return observation

        collected = collect_runtime_inventory(
            (Adapter(),),
            (request,),
            validated_catalog_lock=VALIDATED_CATALOG_LOCK,
        )

        self.assertIsInstance(collected, AdapterError)
        assert isinstance(collected, AdapterError)
        self.assertEqual(collected.code, "RUNTIME_OBSERVATION_INVALID")

    def test_collector_rejects_native_route_with_immutable_content_evidence(
        self,
    ) -> None:
        capability = load_fixture("valid-adapter-capability-record.json")
        request = admit_observe_request(bound_observe_request_snapshot())
        observation = bound_runtime_observation_snapshot()
        assert isinstance(request, ObserveRequest)
        result = observation["record"]["result"]  # type: ignore[index]
        assert isinstance(result, dict)
        normalized = result["normalized_state"]
        assert isinstance(normalized, dict)
        normalized["immutable_content"] = {
            "status": "observed",
            "revision": "0" * 40,
            "content_digest": "sha256:" + "0" * 64,
        }
        result["state_digest"] = canonical_json_sha256(normalized)

        class Adapter:
            def capabilities(self) -> object:
                return capability

            def observe(self, _: ObserveRequest) -> object:
                return observation

        collected = collect_runtime_inventory(
            (Adapter(),),
            (request,),
            validated_catalog_lock=VALIDATED_CATALOG_LOCK,
        )

        self.assertIsInstance(collected, AdapterError)
        assert isinstance(collected, AdapterError)
        self.assertEqual(collected.code, "RUNTIME_OBSERVATION_INVALID")


if __name__ == "__main__":
    unittest.main()
