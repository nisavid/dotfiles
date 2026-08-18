from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from typing import override
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "home/private_dot_local/lib/agent-equipment"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from agent_equipment.authoring import (
    AuthoringError,
    CatalogAdditionProposal,
    DiscoveryHarnessBinding,
    DiscoveryPort,
    DiscoverySelection,
    TargetSelection,
    UnmanagedReport,
    find_unmanaged,
    propose_add,
)
from agent_equipment.canonical import canonical_json_bytes, canonical_json_sha256
from agent_equipment.discovery import (
    MAX_DISCOVERY_AGGREGATE_BYTES,
    MAX_DISCOVERY_RECORDS,
    MAX_DISCOVERY_RESPONSE_BYTES,
    DiscoveryError,
    EquipmentDiscoveryAdapter,
    EquipmentDiscoveryObservation,
    EquipmentDiscoveryReport,
    EquipmentDiscoveryRequest,
    admit_discovery_report,
    collect_discovery,
)
from agent_equipment.model import (
    FrozenJsonObject,
    ValidatedCatalogLock,
    freeze_json,
    thaw_json,
)
from agent_equipment.validator import load_catalog_lock, validate_catalog_lock

DOCUMENTS = ROOT / "docs/agent-equipment"


def record_identity(value: object) -> str:
    if isinstance(value, dict) and isinstance(value.get("identity"), str):
        return value["identity"]
    return ""


def base_catalog_lock() -> ValidatedCatalogLock:
    result = load_catalog_lock(
        DOCUMENTS / "initial-catalog.proposed.json",
        DOCUMENTS / "initial-lock.proposed.json",
    )
    assert result.model is not None, result.diagnostics
    return result.model


def addable_base_catalog_lock(*equipment_identities: str) -> ValidatedCatalogLock:
    base = base_catalog_lock()
    catalog = thaw_json(base.catalog.document)
    lock = thaw_json(base.lock.document)
    assert isinstance(catalog, dict)
    assert isinstance(lock, dict)
    lock_distributions = lock["distributions"]
    assert isinstance(lock_distributions, list)
    manifest = next(
        item
        for item in lock_distributions
        if isinstance(item, dict)
        and item.get("distribution_identity") == "distribution:context7/direct-mcp"
    )
    available = manifest["available_equipment"]
    assert isinstance(available, list)
    available.extend(equipment_identities)
    available.sort()
    membership_evidence = manifest["membership_evidence"]
    assert isinstance(membership_evidence, dict)
    membership_evidence["evidence_digest"] = canonical_json_sha256(
        {"available_equipment": available}
    )
    manifest_payload = copy.deepcopy(manifest)
    manifest_payload.pop("source_manifest_digest")
    manifest["source_manifest_digest"] = canonical_json_sha256(manifest_payload)
    result = validate_catalog_lock(catalog, lock)
    assert result.model is not None, result.diagnostics
    return result.model


def addable_multi_distribution_base_catalog_lock(
    equipment_identity: str,
    *distribution_identities: str,
) -> ValidatedCatalogLock:
    base = base_catalog_lock()
    catalog = thaw_json(base.catalog.document)
    lock = thaw_json(base.lock.document)
    assert isinstance(catalog, dict)
    assert isinstance(lock, dict)
    lock_distributions = lock["distributions"]
    retirements = lock["retirements"]
    history = lock["source_manifest_history"]
    assert isinstance(lock_distributions, list)
    assert isinstance(retirements, list)
    assert isinstance(history, list)
    for distribution_identity in distribution_identities:
        manifest = next(
            item
            for item in lock_distributions
            if isinstance(item, dict)
            and item.get("distribution_identity") == distribution_identity
        )
        old_manifest = copy.deepcopy(manifest)
        old_manifest_digest = manifest["source_manifest_digest"]
        if any(
            isinstance(item, dict)
            and item.get("source_manifest_digest") == old_manifest_digest
            for item in retirements
        ):
            history.append(old_manifest)
        available = manifest["available_equipment"]
        assert isinstance(available, list)
        available.append(equipment_identity)
        available.sort()
        membership_evidence = manifest["membership_evidence"]
        assert isinstance(membership_evidence, dict)
        membership_evidence["evidence_digest"] = canonical_json_sha256(
            {"available_equipment": available}
        )
        manifest_payload = copy.deepcopy(manifest)
        manifest_payload.pop("source_manifest_digest")
        manifest["source_manifest_digest"] = canonical_json_sha256(manifest_payload)
    history.sort(
        key=lambda item: (
            (
                item.get("distribution_identity", ""),
                item.get("source_manifest_digest", ""),
            )
            if isinstance(item, dict)
            else ("", "")
        )
    )
    result = validate_catalog_lock(catalog, lock)
    assert result.model is not None, result.diagnostics
    return result.model


def retirement_bound_base_catalog_lock(
    target: str,
) -> ValidatedCatalogLock:
    target_equipment_identity = target.split("/", 1)[1]
    base = addable_base_catalog_lock(target_equipment_identity)
    equipment_identity = "mcp:context7/server"
    catalog = thaw_json(base.catalog.document)
    lock = thaw_json(base.lock.document)
    assert isinstance(catalog, dict)
    assert isinstance(lock, dict)
    lock_distributions = lock["distributions"]
    lock_coverage = lock["coverage"]
    assert isinstance(lock_distributions, list)
    assert isinstance(lock_coverage, list)
    manifest = next(
        item
        for item in lock_distributions
        if isinstance(item, dict)
        and item.get("distribution_identity") == "distribution:context7/direct-mcp"
    )
    peer_coverage = next(
        item
        for item in lock_coverage
        if isinstance(item, dict)
        and item.get("equipment_identity") == "mcp:context7/server"
        and item.get("harness") == "codex"
    )
    record = peer_coverage["record"]
    assert isinstance(record, dict)
    selection = record["provider_selection"]
    assert isinstance(selection, dict)
    routes = selection["routes"]
    assert isinstance(routes, list)
    route = copy.deepcopy(routes[0])
    assert isinstance(route, dict)
    route["identity"] = "route:codex/retire-context7-alternate"
    route["activation_group"] = "activation:codex/retire-context7-alternate"
    provider = route["provider"]
    assert isinstance(provider, dict)
    provider["server_name"] = "context7-retired-alternate"
    retirement = {
        "identity": "retirement:codex/context7-alternate",
        "equipment_identity": equipment_identity,
        "harness": "codex",
        "route": route,
        "surface": {
            "kind": "direct_mcp",
            "server_name": "context7-retired-alternate",
        },
        "desired_state": "absent",
        "source_manifest_digest": manifest["source_manifest_digest"],
    }
    catalog_retirements = catalog["retirements"]
    lock_retirements = lock["retirements"]
    assert isinstance(catalog_retirements, list)
    assert isinstance(lock_retirements, list)
    catalog_retirements.append(copy.deepcopy(retirement))
    lock_retirements.append(copy.deepcopy(retirement))
    catalog_retirements.sort(key=record_identity)
    lock_retirements.sort(key=record_identity)
    lock["catalog_digest"] = canonical_json_sha256(catalog)
    result = validate_catalog_lock(catalog, lock)
    assert result.model is not None, result.diagnostics
    return result.model


def discovery_binding(harness: str) -> DiscoveryHarnessBinding:
    return DiscoveryHarnessBinding(
        capability_identity=f"capability:{harness}/equipment-discovery",
        capability_digest="sha256:" + "3" * 64,
        manager_version_evidence_digest="sha256:" + "4" * 64,
        harness=harness,
    )


def discovery_selection(*, harness: str = "codex") -> DiscoverySelection:
    return DiscoverySelection(
        candidate_identity="candidate:sha256:" + "1" * 64,
        implementation_manifest_digest="sha256:" + "2" * 64,
        bindings=(discovery_binding(harness),),
        targets=None,
    )


def target_selection(*targets: str) -> TargetSelection:
    harnesses = sorted({target.split("/", 1)[0] for target in targets})
    return TargetSelection(
        candidate_identity="candidate:sha256:" + "1" * 64,
        implementation_manifest_digest="sha256:" + "2" * 64,
        bindings=tuple(discovery_binding(harness) for harness in harnesses),
        targets=tuple(sorted(targets)),
    )


def catalog_binding(
    base: ValidatedCatalogLock,
    distribution_identity: str,
    harness: str,
    peer_equipment_identity: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], list[object]]:
    catalog = thaw_json(base.catalog.document)
    lock = thaw_json(base.lock.document)
    assert isinstance(catalog, dict)
    assert isinstance(lock, dict)
    catalog_distributions = catalog["distributions"]
    lock_distributions = lock["distributions"]
    lock_coverage = lock["coverage"]
    assert isinstance(catalog_distributions, list)
    assert isinstance(lock_distributions, list)
    assert isinstance(lock_coverage, list)
    distribution = next(
        item
        for item in catalog_distributions
        if isinstance(item, dict) and item.get("identity") == distribution_identity
    )
    locked_distribution = next(
        item
        for item in lock_distributions
        if isinstance(item, dict)
        and item.get("distribution_identity") == distribution_identity
    )
    coverage = next(
        item
        for item in lock_coverage
        if isinstance(item, dict)
        and item.get("equipment_identity") == peer_equipment_identity
        and item.get("harness") == harness
    )
    record = coverage["record"]
    assert isinstance(record, dict)
    provider_selection = record["provider_selection"]
    assert isinstance(provider_selection, dict)
    routes = provider_selection["routes"]
    assert isinstance(routes, list)
    route = next(
        item
        for item in routes
        if isinstance(item, dict) and item.get("distribution") == distribution_identity
    )
    source = distribution["source"]
    resolved_source = locked_distribution["resolved_source"]
    source_manifest_digest = locked_distribution["source_manifest_digest"]
    restore = locked_distribution["restore"]
    provider = route["provider"]
    secret_references = route["secret_references"]
    assert isinstance(source, dict)
    assert isinstance(resolved_source, dict)
    assert isinstance(source_manifest_digest, str)
    assert isinstance(restore, dict)
    assert isinstance(provider, dict)
    assert isinstance(secret_references, list)
    return (
        {
            "distribution_identity": distribution_identity,
            "source": copy.deepcopy(source),
            "resolved_source": copy.deepcopy(resolved_source),
            "source_manifest_digest": source_manifest_digest,
        },
        copy.deepcopy(restore),
        copy.deepcopy(provider),
        copy.deepcopy(secret_references),
    )


def observation(
    request: EquipmentDiscoveryRequest,
    target: str,
    *,
    base: ValidatedCatalogLock | None = None,
    present: bool = True,
    state: dict[str, object] | None = None,
    distribution_identity: str = "distribution:context7/direct-mcp",
    peer_equipment_identity: str = "mcp:context7/server",
) -> dict[str, object]:
    equipment_identity = target.split("/", 1)[1]
    bound_base = base_catalog_lock() if base is None else base
    source_evidence, restore, provider, secret_references = catalog_binding(
        bound_base,
        distribution_identity,
        request.harness,
        peer_equipment_identity,
    )
    normalized_state = {"present": present} if state is None else state
    return {
        "target": target,
        "equipment_identity": equipment_identity,
        "equipment_kind": equipment_identity.split(":", 1)[0],
        "present": present,
        "provider_evidence": provider,
        "source_evidence": source_evidence,
        "restore_evidence": restore,
        "secret_references": secret_references,
        "normalized_state": normalized_state,
        "state_digest": canonical_json_sha256(normalized_state),
        "capability_identity": request.document["capability_identity"],
        "capability_digest": request.document["capability_digest"],
        "manager_version_evidence_digest": request.document[
            "manager_version_evidence_digest"
        ],
        "evidence_references": [
            {"kind": "manager", "reference": "context7/direct-mcp"}
        ],
    }


class ResponseAdapter(EquipmentDiscoveryAdapter):
    def __init__(self, records: list[dict[str, object]]) -> None:
        self.records = records

    @override
    def capabilities(self) -> object:
        first = self.records[0]
        target = first["target"]
        assert isinstance(target, str)
        return {
            "supports_equipment_discovery": True,
            "harness": target.split("/", 1)[0],
            "capability_identity": first["capability_identity"],
            "capability_digest": first["capability_digest"],
            "manager_version_evidence_digest": first["manager_version_evidence_digest"],
        }

    @override
    def discover(self, request: EquipmentDiscoveryRequest) -> object:
        return {
            "request_digest": request.request_digest,
            "complete": True,
            "observations": copy.deepcopy(self.records),
        }


class SequencedDiscoveryPort(DiscoveryPort):
    def __init__(self, responses: list[list[dict[str, object]]]) -> None:
        self.responses = responses
        self.requests: list[EquipmentDiscoveryRequest] = []

    @override
    def discover(
        self,
        request: EquipmentDiscoveryRequest,
    ) -> EquipmentDiscoveryReport | DiscoveryError:
        self.requests.append(request)
        records = self.responses[len(self.requests) - 1]
        for record in records:
            record["capability_identity"] = request.document["capability_identity"]
            record["capability_digest"] = request.document["capability_digest"]
            record["manager_version_evidence_digest"] = request.document[
                "manager_version_evidence_digest"
            ]
        return collect_discovery((ResponseAdapter(records),), request)


def records_for_targets(
    selection: DiscoverySelection,
    targets: list[tuple[str, bool]],
) -> list[dict[str, object]]:
    base = base_catalog_lock()
    request = selection.requests("unmanaged", base)[0]
    return [
        observation(request, target, present=present) for target, present in targets
    ]


class UnmanagedAuthoringTests(unittest.TestCase):
    @staticmethod
    def _multi_harness_selection() -> DiscoverySelection:
        return DiscoverySelection(
            candidate_identity="candidate:sha256:" + "1" * 64,
            implementation_manifest_digest="sha256:" + "2" * 64,
            bindings=(discovery_binding("claude"), discovery_binding("codex")),
            targets=None,
        )

    @staticmethod
    def _multi_harness_responses(
        base: ValidatedCatalogLock,
        selection: DiscoverySelection,
    ) -> tuple[
        tuple[EquipmentDiscoveryRequest, ...],
        list[list[dict[str, object]]],
    ]:
        requests = selection.requests("unmanaged", base)
        responses = [
            [
                observation(
                    request,
                    f"{request.harness}/skill:custom/{request.harness}-only",
                    base=base,
                )
            ]
            for request in requests
        ]
        return requests, responses

    def test_report_admission_rejects_a_nominal_document_subclass(self) -> None:
        base = base_catalog_lock()
        selection = discovery_selection()
        request = selection.requests("unmanaged", base)[0]
        record = observation(request, "codex/skill:custom/grilling", base=base)
        collected = collect_discovery((ResponseAdapter([record]),), request)
        assert isinstance(collected, EquipmentDiscoveryReport)

        class NominalDocument(FrozenJsonObject):
            pass

        nominal_report = EquipmentDiscoveryReport(
            NominalDocument(tuple(collected.document.items())),
            collected.request,
            collected.observations,
            collected.complete,
            collected.discovery_digest,
        )

        admitted = admit_discovery_report(nominal_report, request)

        self.assertIsInstance(admitted, DiscoveryError)
        assert isinstance(admitted, DiscoveryError)
        self.assertEqual(admitted.code, "DISCOVERY_RESPONSE_INVALID")
        self.assertEqual(
            admitted.message,
            "Equipment discovery response is invalid.",
        )

    def test_unmanaged_redacts_delayed_system_exit_from_report_admission(
        self,
    ) -> None:
        canary = "V7pOpaque" + "PrivateValue9Qx"
        base = base_catalog_lock()
        selection = discovery_selection()
        request = selection.requests("unmanaged", base)[0]
        record = observation(request, "codex/skill:custom/grilling", base=base)
        collected = collect_discovery((ResponseAdapter([record]),), request)
        assert isinstance(collected, EquipmentDiscoveryReport)

        class DelayedExitPort(DiscoveryPort):
            @override
            def discover(
                self,
                current_request: EquipmentDiscoveryRequest,
            ) -> EquipmentDiscoveryReport | DiscoveryError:
                return collected

        with patch(
            "agent_equipment.authoring.admit_discovery_report",
            side_effect=SystemExit(canary),
        ):
            result = find_unmanaged(base, selection, DelayedExitPort())

        self.assertIsInstance(result, AuthoringError)
        assert isinstance(result, AuthoringError)
        self.assertEqual(result.code, "DISCOVERY_FAILED")
        self.assertEqual(result.message, "Equipment discovery failed.")
        self.assertNotIn(canary, repr(result))

    def test_unmanaged_does_not_catch_keyboard_interrupt_from_report_admission(
        self,
    ) -> None:
        base = base_catalog_lock()
        selection = discovery_selection()
        request = selection.requests("unmanaged", base)[0]
        record = observation(request, "codex/skill:custom/grilling", base=base)
        collected = collect_discovery((ResponseAdapter([record]),), request)
        assert isinstance(collected, EquipmentDiscoveryReport)

        class DelayedInterruptPort(DiscoveryPort):
            @override
            def discover(
                self,
                current_request: EquipmentDiscoveryRequest,
            ) -> EquipmentDiscoveryReport | DiscoveryError:
                return collected

        with (
            patch(
                "agent_equipment.authoring.admit_discovery_report",
                side_effect=KeyboardInterrupt,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            find_unmanaged(base, selection, DelayedInterruptPort())

    def test_unmanaged_redacts_and_bounds_an_untrusted_port_error(self) -> None:
        base = base_catalog_lock()
        selection = discovery_selection()
        oversized_message = "x" * (MAX_DISCOVERY_RESPONSE_BYTES + 1)

        class ErrorPort(DiscoveryPort):
            @override
            def discover(
                self,
                request: EquipmentDiscoveryRequest,
            ) -> EquipmentDiscoveryReport | DiscoveryError:
                return DiscoveryError("DISCOVERY_FAILED", oversized_message)

        result = find_unmanaged(base, selection, ErrorPort())

        self.assertIsInstance(result, AuthoringError)
        assert isinstance(result, AuthoringError)
        self.assertEqual(result.code, "DISCOVERY_FAILED")
        self.assertEqual(result.message, "Equipment discovery failed.")
        self.assertNotIn(oversized_message, repr(result))

    def test_unmanaged_rejects_cross_harness_observation_count_overflow(
        self,
    ) -> None:
        base = base_catalog_lock()
        selection = self._multi_harness_selection()
        _, responses = self._multi_harness_responses(base, selection)
        port = SequencedDiscoveryPort(responses)
        base_catalog = base.catalog.document
        base_lock = base.lock.document

        with patch("agent_equipment.authoring.MAX_DISCOVERY_RECORDS", 1):
            result = find_unmanaged(base, selection, port)

        self.assertIsInstance(result, AuthoringError)
        assert isinstance(result, AuthoringError)
        self.assertEqual(result.code, "DISCOVERY_LIMIT_EXCEEDED")
        self.assertEqual(
            result.message,
            "Equipment discovery exceeds its collection limits.",
        )
        self.assertFalse(hasattr(result, "records"))
        self.assertEqual(len(port.requests), 2)
        self.assertEqual(base.catalog.document, base_catalog)
        self.assertEqual(base.lock.document, base_lock)

    def test_unmanaged_rejects_cross_harness_aggregate_byte_overflow(
        self,
    ) -> None:
        base = base_catalog_lock()
        selection = self._multi_harness_selection()
        requests, responses = self._multi_harness_responses(base, selection)
        reports = tuple(
            collect_discovery((ResponseAdapter(records),), request)
            for request, records in zip(requests, responses, strict=True)
        )
        self.assertTrue(
            all(isinstance(report, EquipmentDiscoveryReport) for report in reports)
        )
        admitted_reports = tuple(
            report for report in reports if isinstance(report, EquipmentDiscoveryReport)
        )
        crossing = (
            sum(
                len(canonical_json_bytes(report.document))
                for report in admitted_reports
            )
            - 1
        )
        self.assertLess(
            max(
                len(canonical_json_bytes(report.document))
                for report in admitted_reports
            ),
            crossing,
        )
        self.assertLess(crossing, MAX_DISCOVERY_AGGREGATE_BYTES)
        port = SequencedDiscoveryPort(copy.deepcopy(responses))
        base_catalog = base.catalog.document
        base_lock = base.lock.document

        with patch(
            "agent_equipment.authoring.MAX_DISCOVERY_AGGREGATE_BYTES",
            crossing,
        ):
            result = find_unmanaged(base, selection, port)

        self.assertIsInstance(result, AuthoringError)
        assert isinstance(result, AuthoringError)
        self.assertEqual(result.code, "DISCOVERY_LIMIT_EXCEEDED")
        self.assertEqual(
            result.message,
            "Equipment discovery exceeds its collection limits.",
        )
        self.assertFalse(hasattr(result, "records"))
        self.assertEqual(len(port.requests), 2)
        self.assertEqual(base.catalog.document, base_catalog)
        self.assertEqual(base.lock.document, base_lock)

    def test_unmanaged_rejects_a_forged_secret_bearing_report(self) -> None:
        canary = "s" + "k-" + "x" * 32
        base = base_catalog_lock()
        selection = discovery_selection()
        request = selection.requests("unmanaged", base)[0]
        record = observation(request, "codex/skill:custom/grilling", base=base)
        admitted = collect_discovery((ResponseAdapter([record]),), request)
        assert isinstance(admitted, EquipmentDiscoveryReport)
        valid_observation = admitted.observations[0]
        forged_document = thaw_json(valid_observation.document)
        assert isinstance(forged_document, dict)
        forged_document["normalized_state"] = {"api_key": canary}
        frozen_document = freeze_json(forged_document)
        assert isinstance(frozen_document, FrozenJsonObject)
        forged_observation = EquipmentDiscoveryObservation(
            frozen_document,
            valid_observation.observation_identity,
            valid_observation.target,
            valid_observation.equipment_identity,
            valid_observation.equipment_kind,
            valid_observation.present,
            valid_observation.state_digest,
            valid_observation.capability_identity,
        )
        forged_report = EquipmentDiscoveryReport(
            admitted.document,
            admitted.request,
            (forged_observation,),
            admitted.complete,
            admitted.discovery_digest,
        )

        class ForgedPort(DiscoveryPort):
            @override
            def discover(
                self,
                request: EquipmentDiscoveryRequest,
            ) -> EquipmentDiscoveryReport | DiscoveryError:
                return forged_report

        result = find_unmanaged(base, selection, ForgedPort())

        self.assertIsInstance(result, AuthoringError)
        assert isinstance(result, AuthoringError)
        self.assertEqual(result.code, "DISCOVERY_LITERAL_SECRET")
        self.assertNotIn(canary, repr(result))

    def test_unmanaged_emits_only_positive_catalog_absent_factual_records(
        self,
    ) -> None:
        base = base_catalog_lock()
        selection = discovery_selection()
        records = records_for_targets(
            selection,
            [
                ("codex/skill:custom/grilling", True),
                ("codex/skill:mattpocock/grilling", True),
                ("codex/skill:custom/absent", False),
            ],
        )
        port = SequencedDiscoveryPort([records])

        result = find_unmanaged(base, selection, port)

        self.assertIsInstance(result, UnmanagedReport)
        assert isinstance(result, UnmanagedReport)
        self.assertEqual(
            tuple(record.target for record in result.records),
            ("codex/skill:custom/grilling",),
        )
        record = result.records[0]
        expected_identity = canonical_json_sha256(
            {
                "target": record.target,
                "state_digest": record.state_digest,
                "catalog_digest": base.catalog.digest,
                "discovery_digest": result.discovery_digest,
            }
        )
        self.assertEqual(record.unmanaged_identity, expected_identity)
        serialized = thaw_json(result.document)
        self.assertNotIn("proposal", repr(serialized).lower())
        self.assertEqual(len(port.requests), 1)

    def test_unmanaged_digest_projects_adapter_owned_provider_and_restore_text(
        self,
    ) -> None:
        canary = "V7pOpaque" + "PrivateValue9Qx"
        base = base_catalog_lock()
        selection = discovery_selection()
        request = selection.requests("unmanaged", base)[0]
        record = observation(
            request,
            "codex/mcp:custom/opaque",
            base=base,
        )
        provider = record["provider_evidence"]
        assert isinstance(provider, dict)
        arguments = provider["arguments"]
        assert isinstance(arguments, list)
        arguments.append({"literal": "--" + "to" + "ken=" + canary})
        source_evidence = record["source_evidence"]
        assert isinstance(source_evidence, dict)
        source_evidence["distribution_identity"] = "distribution:" + canary.lower()
        secret_references = record["secret_references"]
        assert isinstance(secret_references, list)
        secret_reference = secret_references[0]
        assert isinstance(secret_reference, dict)
        secret_reference["name"] = canary.lower()
        first_argument = arguments[0]
        assert isinstance(first_argument, dict)
        first_argument["secret_profile_reference"] = canary.lower()
        record["evidence_references"] = [{"kind": "manager", "reference": canary}]
        restore = record["restore_evidence"]
        assert isinstance(restore, dict)
        restore["observation_source"] = canary

        result = find_unmanaged(base, selection, SequencedDiscoveryPort([[record]]))

        self.assertIsInstance(result, UnmanagedReport)
        assert isinstance(result, UnmanagedReport)
        self.assertNotIn(canary, repr(result))
        self.assertNotIn(canary.lower(), repr(result))
        serialized = thaw_json(result.document)
        assert isinstance(serialized, dict)
        records = serialized["records"]
        assert isinstance(records, list)
        observation_document = records[0]["observation"]  # type: ignore[index]
        assert isinstance(observation_document, dict)
        for field in (
            "provider_evidence",
            "source_evidence",
            "restore_evidence",
            "secret_references",
            "evidence_references",
        ):
            self.assertNotIn(field, observation_document)
            self.assertEqual(
                observation_document[f"{field}_digest"],
                canonical_json_sha256(record[field]),
            )


class AddAuthoringTests(unittest.TestCase):
    TARGET = "codex/mcp:context7/alternate"

    def test_add_rejects_total_cross_harness_target_count_overflow(self) -> None:
        targets = tuple(
            sorted(
                (
                    *(
                        f"claude/skill:bulk/item-{index:04d}"
                        for index in range(MAX_DISCOVERY_RECORDS // 2 + 1)
                    ),
                    *(
                        f"codex/skill:bulk/item-{index:04d}"
                        for index in range(MAX_DISCOVERY_RECORDS // 2)
                    ),
                )
            )
        )

        with self.assertRaisesRegex(ValueError, "target.*limit"):
            TargetSelection(
                candidate_identity="candidate:sha256:" + "1" * 64,
                implementation_manifest_digest="sha256:" + "2" * 64,
                bindings=(discovery_binding("claude"), discovery_binding("codex")),
                targets=targets,
            )

    def records(
        self,
        selection: TargetSelection,
        base: ValidatedCatalogLock,
    ) -> list[dict[str, object]]:
        request = selection.requests("add", base)[0]
        return [observation(request, self.TARGET, base=base)]

    def test_target_selection_requires_sorted_targets_and_exact_bindings(self) -> None:
        for suffix in (".", "_", "/", "-"):
            with self.subTest(valid_terminal=suffix):
                target = f"codex/skill:custom/grilling{suffix}"
                selection = TargetSelection(
                    candidate_identity="candidate:sha256:" + "1" * 64,
                    implementation_manifest_digest="sha256:" + "2" * 64,
                    bindings=(discovery_binding("codex"),),
                    targets=(target,),
                )
                self.assertEqual(selection.targets, (target,))

        with self.assertRaises(ValueError):
            TargetSelection(
                candidate_identity="candidate:sha256:" + "1" * 64,
                implementation_manifest_digest="sha256:" + "2" * 64,
                bindings=(discovery_binding("codex"),),
                targets=(
                    "codex/skill:custom/zeta",
                    "codex/skill:custom/alpha",
                ),
            )
        with self.assertRaises(ValueError):
            TargetSelection(
                candidate_identity="candidate:sha256:" + "1" * 64,
                implementation_manifest_digest="sha256:" + "2" * 64,
                bindings=(discovery_binding("codex"),),
                targets=("cursor/skill:custom/grilling",),
            )

    def test_add_discovers_twice_and_emits_one_valid_full_pair(self) -> None:
        base = addable_base_catalog_lock(self.TARGET.split("/", 1)[1])
        base_catalog = base.catalog.document
        base_lock = base.lock.document
        selection = target_selection(self.TARGET)
        first = self.records(selection, base)
        second = copy.deepcopy(first)
        port = SequencedDiscoveryPort([first, second])

        result = propose_add(base, selection, port)

        self.assertIsInstance(result, CatalogAdditionProposal)
        assert isinstance(result, CatalogAdditionProposal)
        self.assertEqual(len(port.requests), 2)
        self.assertEqual(
            tuple(request.command for request in port.requests), ("add", "add")
        )
        proposal = thaw_json(result.document)
        assert isinstance(proposal, dict)
        proposed_catalog = proposal["catalog"]
        proposed_lock = proposal["lock"]
        self.assertIsInstance(proposed_catalog, dict)
        self.assertIsInstance(proposed_lock, dict)
        validation = validate_catalog_lock(proposed_catalog, proposed_lock)
        self.assertIsNotNone(validation.model, validation.diagnostics)
        self.assertEqual(proposal["targets"], [self.TARGET])
        self.assertEqual(
            proposed_lock["catalog_digest"],  # type: ignore[index]
            canonical_json_sha256(proposed_catalog),
        )

        old_catalog = thaw_json(base.catalog.document)
        old_lock = thaw_json(base.lock.document)
        assert isinstance(old_catalog, dict)
        assert isinstance(old_lock, dict)
        self.assertEqual(
            len(proposed_catalog["equipment"]),  # type: ignore[index]
            len(old_catalog["equipment"]) + 1,  # type: ignore[arg-type]
        )
        self.assertEqual(
            len(proposed_lock["coverage"]),  # type: ignore[index]
            len(old_lock["coverage"]) + len(old_catalog["active_harnesses"]),  # type: ignore[arg-type]
        )
        self.assertEqual(base.catalog.document, base_catalog)
        self.assertEqual(base.lock.document, base_lock)

    def test_add_rejects_catalog_lock_and_proposal_byte_ceiling_crossings(
        self,
    ) -> None:
        base = addable_base_catalog_lock(self.TARGET.split("/", 1)[1])
        selection = target_selection(self.TARGET)
        base_catalog = base.catalog.document
        base_lock = base.lock.document
        records = self.records(selection, base)
        accepted = propose_add(
            base,
            selection,
            SequencedDiscoveryPort([records, copy.deepcopy(records)]),
        )
        self.assertIsInstance(accepted, CatalogAdditionProposal)
        assert isinstance(accepted, CatalogAdditionProposal)

        for label, limit_name, document in (
            ("catalog", "MAX_ADD_CATALOG_BYTES", accepted.catalog),
            ("lock", "MAX_ADD_LOCK_BYTES", accepted.lock),
            ("proposal", "MAX_ADD_PROPOSAL_BYTES", accepted.document),
        ):
            with self.subTest(document=label):
                current = self.records(selection, base)
                with (
                    patch(
                        f"agent_equipment.authoring.{limit_name}",
                        len(canonical_json_bytes(document)) - 1,
                        create=True,
                    ),
                    patch(
                        "agent_equipment.authoring.validate_catalog_lock",
                        wraps=validate_catalog_lock,
                    ) as validate_pair,
                ):
                    result = propose_add(
                        base,
                        selection,
                        SequencedDiscoveryPort([current, copy.deepcopy(current)]),
                    )

                self.assertIsInstance(result, AuthoringError)
                assert isinstance(result, AuthoringError)
                self.assertEqual(result.code, "ADD_PROPOSAL_LIMIT_EXCEEDED")
                self.assertFalse(hasattr(result, "catalog"))
                if label in {"catalog", "lock"}:
                    validate_pair.assert_not_called()
                else:
                    validate_pair.assert_called_once()
                self.assertEqual(base.catalog.document, base_catalog)
                self.assertEqual(base.lock.document, base_lock)

    def test_add_rejects_adapter_policy_canaries_without_emitting_them(
        self,
    ) -> None:
        canary = "V7pOpaque" + "PrivateValue9Qx"
        base = addable_base_catalog_lock(self.TARGET.split("/", 1)[1])
        selection = target_selection(self.TARGET)
        records = self.records(selection, base)
        record = records[0]
        provider = record["provider_evidence"]
        source_evidence = record["source_evidence"]
        restore = record["restore_evidence"]
        secret_references = record["secret_references"]
        assert isinstance(provider, dict)
        assert isinstance(source_evidence, dict)
        assert isinstance(restore, dict)
        assert isinstance(secret_references, list)
        arguments = provider["arguments"]
        assert isinstance(arguments, list)
        first_argument = arguments[0]
        secret_reference = secret_references[0]
        assert isinstance(first_argument, dict)
        assert isinstance(secret_reference, dict)
        arguments.append({"literal": "--" + "to" + "ken=" + canary})
        source_evidence["distribution_identity"] = "distribution:" + canary.lower()
        restore["observation_source"] = canary
        first_argument["secret_profile_reference"] = canary.lower()
        secret_reference["name"] = canary.lower()
        record["evidence_references"] = [{"kind": "manager", "reference": canary}]

        result = propose_add(
            base,
            selection,
            SequencedDiscoveryPort([records, copy.deepcopy(records)]),
        )

        self.assertIsInstance(result, AuthoringError)
        assert isinstance(result, AuthoringError)
        self.assertEqual(result.code, "ADD_AUTHORING_POLICY_REQUIRED")
        self.assertNotIn(canary, repr(result))
        self.assertNotIn(canary.lower(), repr(result))
        self.assertFalse(hasattr(result, "catalog"))

    def test_add_normalizes_valid_catalog_and_lock_array_order(self) -> None:
        equipment_identity = self.TARGET.split("/", 1)[1]
        canonical_base = addable_base_catalog_lock(equipment_identity)
        reordered_catalog = thaw_json(canonical_base.catalog.document)
        reordered_lock = thaw_json(canonical_base.lock.document)
        assert isinstance(reordered_catalog, dict)
        assert isinstance(reordered_lock, dict)
        for field in (
            "distributions",
            "coverage_templates",
            "equipment",
            "retirements",
        ):
            values = reordered_catalog[field]
            assert isinstance(values, list)
            values.reverse()
        for field in (
            "distributions",
            "source_manifest_history",
            "coverage",
            "retirements",
        ):
            values = reordered_lock[field]
            assert isinstance(values, list)
            values.reverse()
        reordered_lock["catalog_digest"] = canonical_json_sha256(reordered_catalog)
        reordered_validation = validate_catalog_lock(
            reordered_catalog,
            reordered_lock,
        )
        self.assertIsNotNone(
            reordered_validation.model,
            reordered_validation.diagnostics,
        )
        assert reordered_validation.model is not None

        def proposal_for(base: ValidatedCatalogLock) -> CatalogAdditionProposal:
            selection = target_selection(self.TARGET)
            request = selection.requests("add", base)[0]
            records = [observation(request, self.TARGET, base=base)]
            result = propose_add(
                base,
                selection,
                SequencedDiscoveryPort([records, copy.deepcopy(records)]),
            )
            self.assertIsInstance(result, CatalogAdditionProposal)
            assert isinstance(result, CatalogAdditionProposal)
            return result

        canonical_proposal = proposal_for(canonical_base)
        reordered_proposal = proposal_for(reordered_validation.model)

        self.assertEqual(
            canonical_json_bytes(canonical_proposal.catalog),
            canonical_json_bytes(reordered_proposal.catalog),
        )
        self.assertEqual(
            canonical_json_bytes(canonical_proposal.lock),
            canonical_json_bytes(reordered_proposal.lock),
        )

    def test_add_revalidation_change_fails_without_a_partial_proposal(self) -> None:
        selection = target_selection(self.TARGET)
        base = addable_base_catalog_lock(self.TARGET.split("/", 1)[1])
        base_catalog = base.catalog.document
        base_lock = base.lock.document
        first = self.records(selection, base)
        second = copy.deepcopy(first)
        changed_state = {"present": True, "enabled": False}
        second[0]["normalized_state"] = changed_state
        second[0]["state_digest"] = canonical_json_sha256(changed_state)
        port = SequencedDiscoveryPort([first, second])

        result = propose_add(base, selection, port)

        self.assertIsInstance(result, AuthoringError)
        assert isinstance(result, AuthoringError)
        self.assertEqual(result.code, "ADD_OBSERVATION_CHANGED")
        self.assertFalse(hasattr(result, "catalog"))
        self.assertEqual(len(port.requests), 2)
        self.assertEqual(base.catalog.document, base_catalog)
        self.assertEqual(base.lock.document, base_lock)

    def test_add_revalidates_after_the_complete_proposal_is_constructed(self) -> None:
        selection = target_selection(self.TARGET)
        base = addable_base_catalog_lock(self.TARGET.split("/", 1)[1])
        request = selection.requests("add", base)[0]
        unchanged = observation(request, self.TARGET, base=base)
        changed = copy.deepcopy(unchanged)
        changed_state = {"present": True, "enabled": False}
        changed["normalized_state"] = changed_state
        changed["state_digest"] = canonical_json_sha256(changed_state)
        proposal_constructed = False

        class ConstructionAwarePort(DiscoveryPort):
            @override
            def discover(
                self,
                current_request: EquipmentDiscoveryRequest,
            ) -> EquipmentDiscoveryReport | DiscoveryError:
                record = changed if proposal_constructed else unchanged
                return collect_discovery(
                    (ResponseAdapter([copy.deepcopy(record)]),),
                    current_request,
                )

        def observe_construction(
            catalog: object,
            lock: object,
        ) -> object:
            nonlocal proposal_constructed
            proposal_constructed = True
            return validate_catalog_lock(catalog, lock)

        with patch(
            "agent_equipment.authoring.validate_catalog_lock",
            side_effect=observe_construction,
        ):
            result = propose_add(base, selection, ConstructionAwarePort())

        self.assertIsInstance(result, AuthoringError)
        assert isinstance(result, AuthoringError)
        self.assertEqual(result.code, "ADD_OBSERVATION_CHANGED")

    def test_add_revalidation_rejects_every_changed_observation_binding(
        self,
    ) -> None:
        for changed_field, expected_code in (
            ("present", "ADD_TARGET_NOT_UNMANAGED"),
            ("provider_evidence", "ADD_OBSERVATION_CHANGED"),
            ("source_evidence", "ADD_OBSERVATION_CHANGED"),
            ("restore_evidence", "ADD_OBSERVATION_CHANGED"),
            ("secret_references", "ADD_OBSERVATION_CHANGED"),
            ("evidence_references", "ADD_OBSERVATION_CHANGED"),
        ):
            with self.subTest(changed_field=changed_field):
                selection = target_selection(self.TARGET)
                base = addable_base_catalog_lock(self.TARGET.split("/", 1)[1])
                first = self.records(selection, base)
                second = copy.deepcopy(first)
                record = second[0]
                if changed_field == "present":
                    record[changed_field] = False
                    normalized_state = record["normalized_state"]
                    assert isinstance(normalized_state, dict)
                    normalized_state["present"] = False
                    record["state_digest"] = canonical_json_sha256(normalized_state)
                elif changed_field == "provider_evidence":
                    provider_evidence = record[changed_field]
                    assert isinstance(provider_evidence, dict)
                    provider_evidence["server_name"] = "context7-alternate"
                elif changed_field == "source_evidence":
                    source_evidence = record[changed_field]
                    assert isinstance(source_evidence, dict)
                    source_evidence["distribution_identity"] = (
                        "distribution:context7/alternate"
                    )
                elif changed_field == "restore_evidence":
                    restore_evidence = record[changed_field]
                    assert isinstance(restore_evidence, dict)
                    restore_evidence["observation_source"] = (
                        "alternate reviewed overlay"
                    )
                elif changed_field == "secret_references":
                    references = record[changed_field]
                    assert isinstance(references, list)
                    secret_reference = references[0]
                    assert isinstance(secret_reference, dict)
                    secret_reference["name"] = "context7-alternate"
                    provider_evidence = record["provider_evidence"]
                    assert isinstance(provider_evidence, dict)
                    arguments = provider_evidence["arguments"]
                    assert isinstance(arguments, list)
                    first_argument = arguments[0]
                    assert isinstance(first_argument, dict)
                    first_argument["secret_profile_reference"] = "context7-alternate"
                elif changed_field == "evidence_references":
                    references = record[changed_field]
                    assert isinstance(references, list)
                    references.append(
                        {
                            "kind": "filesystem",
                            "reference": "changed/evidence",
                        }
                    )
                port = SequencedDiscoveryPort([first, second])

                result = propose_add(base, selection, port)

                self.assertIsInstance(result, AuthoringError)
                assert isinstance(result, AuthoringError)
                self.assertEqual(result.code, expected_code)
                self.assertFalse(hasattr(result, "catalog"))

    def test_add_requires_one_existing_distribution_with_complete_templates(
        self,
    ) -> None:
        selection = target_selection(self.TARGET)
        base = addable_base_catalog_lock(self.TARGET.split("/", 1)[1])
        first = self.records(selection, base)
        for record in first:
            source_evidence = record["source_evidence"]
            assert isinstance(source_evidence, dict)
            source_evidence["distribution_identity"] = "distribution:unknown/bundle"
        port = SequencedDiscoveryPort([first, copy.deepcopy(first)])

        result = propose_add(base, selection, port)

        self.assertIsInstance(result, AuthoringError)
        assert isinstance(result, AuthoringError)
        self.assertEqual(result.code, "ADD_AUTHORING_POLICY_REQUIRED")

    def test_multi_target_add_is_atomic_when_one_second_pass_target_changes(
        self,
    ) -> None:
        other_target = "cursor/mcp:context7/second-alternate"
        selection = target_selection(self.TARGET, other_target)
        base = addable_base_catalog_lock(
            self.TARGET.split("/", 1)[1],
            other_target.split("/", 1)[1],
        )
        requests = selection.requests("add", base)
        self.assertEqual(tuple(item.harness for item in requests), ("codex", "cursor"))
        first_codex = [observation(requests[0], self.TARGET, base=base)]
        first_cursor = [observation(requests[1], other_target, base=base)]
        second_codex = copy.deepcopy(first_codex)
        second_cursor = copy.deepcopy(first_cursor)
        changed_state = {"present": True, "enabled": False}
        second_cursor[0]["normalized_state"] = changed_state
        second_cursor[0]["state_digest"] = canonical_json_sha256(changed_state)
        port = SequencedDiscoveryPort(
            [first_codex, first_cursor, second_codex, second_cursor]
        )

        result = propose_add(base, selection, port)

        self.assertIsInstance(result, AuthoringError)
        assert isinstance(result, AuthoringError)
        self.assertEqual(result.code, "ADD_OBSERVATION_CHANGED")
        self.assertEqual(len(port.requests), 4)
        self.assertFalse(hasattr(result, "catalog"))

    def test_multi_target_add_batches_one_distribution_and_reseals_once(
        self,
    ) -> None:
        other_target = "cursor/mcp:context7/second-alternate"
        selection = target_selection(self.TARGET, other_target)
        base = addable_base_catalog_lock(
            self.TARGET.split("/", 1)[1],
            other_target.split("/", 1)[1],
        )
        requests = selection.requests("add", base)
        first_codex = [observation(requests[0], self.TARGET, base=base)]
        first_cursor = [observation(requests[1], other_target, base=base)]
        port = SequencedDiscoveryPort(
            [
                first_codex,
                first_cursor,
                copy.deepcopy(first_codex),
                copy.deepcopy(first_cursor),
            ]
        )

        result = propose_add(base, selection, port)

        self.assertIsInstance(result, CatalogAdditionProposal)
        assert isinstance(result, CatalogAdditionProposal)
        proposal = thaw_json(result.document)
        assert isinstance(proposal, dict)
        proposed_catalog = proposal["catalog"]
        proposed_lock = proposal["lock"]
        assert isinstance(proposed_catalog, dict)
        assert isinstance(proposed_lock, dict)
        validation = validate_catalog_lock(proposed_catalog, proposed_lock)
        self.assertIsNotNone(validation.model, validation.diagnostics)
        manifest = next(
            item
            for item in proposed_lock["distributions"]
            if isinstance(item, dict)
            and item.get("distribution_identity") == "distribution:context7/direct-mcp"
        )
        self.assertIn(self.TARGET.split("/", 1)[1], manifest["equipment"])
        self.assertIn(other_target.split("/", 1)[1], manifest["equipment"])

    def test_multi_distribution_add_requires_policy_when_coverages_conflict(
        self,
    ) -> None:
        equipment_identity = "mcp:custom/ambiguous"
        targets = (f"codex/{equipment_identity}", f"cursor/{equipment_identity}")
        selection = target_selection(*targets)
        base = addable_multi_distribution_base_catalog_lock(
            equipment_identity,
            "distribution:context7/direct-mcp",
            "distribution:firecrawl/direct-mcp",
        )
        requests = selection.requests("add", base)
        first_codex = [observation(requests[0], targets[0], base=base)]
        first_cursor = [
            observation(
                requests[1],
                targets[1],
                base=base,
                distribution_identity="distribution:firecrawl/direct-mcp",
                peer_equipment_identity="mcp:firecrawl/server",
            )
        ]
        port = SequencedDiscoveryPort(
            [
                first_codex,
                first_cursor,
                copy.deepcopy(first_codex),
                copy.deepcopy(first_cursor),
            ]
        )

        result = propose_add(base, selection, port)

        self.assertIsInstance(result, AuthoringError)
        assert isinstance(result, AuthoringError)
        self.assertEqual(result.code, "ADD_AUTHORING_POLICY_REQUIRED")

    def test_multi_distribution_add_composes_one_compatible_equipment_row(
        self,
    ) -> None:
        equipment_identity = "mcp:custom/composed"
        targets = tuple(
            f"{harness}/{equipment_identity}"
            for harness in ("claude", "codex", "cursor")
        )
        selection = target_selection(*targets)
        base = addable_multi_distribution_base_catalog_lock(
            equipment_identity,
            "distribution:chrome-devtools/claude-plugin",
            "distribution:chrome-devtools/direct-mcp",
        )
        requests = selection.requests("add", base)
        first = [
            [
                observation(
                    requests[0],
                    targets[0],
                    base=base,
                    distribution_identity=(
                        "distribution:chrome-devtools/claude-plugin"
                    ),
                    peer_equipment_identity="mcp:chrome-devtools/server",
                )
            ],
            [
                observation(
                    requests[1],
                    targets[1],
                    base=base,
                    distribution_identity="distribution:chrome-devtools/direct-mcp",
                    peer_equipment_identity="mcp:chrome-devtools/server",
                )
            ],
            [
                observation(
                    requests[2],
                    targets[2],
                    base=base,
                    distribution_identity="distribution:chrome-devtools/direct-mcp",
                    peer_equipment_identity="mcp:chrome-devtools/server",
                )
            ],
        ]
        port = SequencedDiscoveryPort(first + copy.deepcopy(first))

        result = propose_add(base, selection, port)

        self.assertIsInstance(result, CatalogAdditionProposal)
        assert isinstance(result, CatalogAdditionProposal)
        proposed_catalog = thaw_json(result.catalog)
        proposed_lock = thaw_json(result.lock)
        assert isinstance(proposed_catalog, dict)
        assert isinstance(proposed_lock, dict)
        equipment = proposed_catalog["equipment"]
        coverage = proposed_lock["coverage"]
        distributions = proposed_lock["distributions"]
        assert isinstance(equipment, list)
        assert isinstance(coverage, list)
        assert isinstance(distributions, list)
        self.assertEqual(
            sum(
                isinstance(item, dict) and item.get("identity") == equipment_identity
                for item in equipment
            ),
            1,
        )
        self.assertEqual(
            sum(
                isinstance(item, dict)
                and item.get("equipment_identity") == equipment_identity
                for item in coverage
            ),
            3,
        )
        for distribution_identity in (
            "distribution:chrome-devtools/claude-plugin",
            "distribution:chrome-devtools/direct-mcp",
        ):
            manifest = next(
                item
                for item in distributions
                if isinstance(item, dict)
                and item.get("distribution_identity") == distribution_identity
            )
            self.assertIn(equipment_identity, manifest["equipment"])
        validation = validate_catalog_lock(proposed_catalog, proposed_lock)
        self.assertIsNotNone(validation.model, validation.diagnostics)

    def test_add_preserves_retirement_manifest_history_without_rewriting_it(
        self,
    ) -> None:
        base = retirement_bound_base_catalog_lock(self.TARGET)
        selection = target_selection(self.TARGET)
        request = selection.requests("add", base)[0]
        records = [observation(request, self.TARGET, base=base)]
        port = SequencedDiscoveryPort([records, copy.deepcopy(records)])
        base_lock = thaw_json(base.lock.document)
        assert isinstance(base_lock, dict)
        base_retirements = copy.deepcopy(base_lock["retirements"])
        base_distributions = base_lock["distributions"]
        assert isinstance(base_distributions, list)
        old_manifest = next(
            item
            for item in base_distributions
            if isinstance(item, dict)
            and item.get("distribution_identity") == "distribution:context7/direct-mcp"
        )

        result = propose_add(base, selection, port)

        self.assertIsInstance(result, CatalogAdditionProposal)
        assert isinstance(result, CatalogAdditionProposal)
        proposed_lock = thaw_json(result.lock)
        assert isinstance(proposed_lock, dict)
        self.assertEqual(proposed_lock["retirements"], base_retirements)
        source_manifest_history = proposed_lock["source_manifest_history"]
        assert isinstance(source_manifest_history, list)
        self.assertIn(old_manifest, source_manifest_history)
        proposed_catalog = thaw_json(result.catalog)
        assert isinstance(proposed_catalog, dict)
        validation = validate_catalog_lock(proposed_catalog, proposed_lock)
        self.assertIsNotNone(validation.model, validation.diagnostics)


if __name__ == "__main__":
    unittest.main()
