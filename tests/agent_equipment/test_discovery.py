from __future__ import annotations

import unittest
from copy import deepcopy
from typing import override
from unittest.mock import patch

from agent_equipment import discovery
from agent_equipment.canonical import canonical_json_sha256
from agent_equipment.discovery import (
    MAX_DISCOVERY_AGGREGATE_BYTES,
    MAX_DISCOVERY_DEPTH,
    MAX_DISCOVERY_FIELD_CHARACTERS,
    MAX_DISCOVERY_RECORDS,
    MAX_DISCOVERY_REFERENCES,
    MAX_DISCOVERY_RESPONSE_BYTES,
    DiscoveryError,
    EquipmentDiscoveryAdapter,
    EquipmentDiscoveryObservation,
    EquipmentDiscoveryReport,
    EquipmentDiscoveryRequest,
    admit_discovery_report,
    collect_discovery,
)
from agent_equipment.model import FrozenJsonObject, freeze_json, thaw_json


def request(
    targets: tuple[str, ...] | None = None,
) -> EquipmentDiscoveryRequest:
    return EquipmentDiscoveryRequest.create(
        command="unmanaged",
        candidate_identity="candidate:sha256:" + "1" * 64,
        implementation_manifest_digest="sha256:" + "2" * 64,
        catalog_digest="sha256:" + "3" * 64,
        lock_digest="sha256:" + "4" * 64,
        capability_identity="capability:codex/standalone-skill",
        capability_digest="sha256:" + "5" * 64,
        manager_version_evidence_digest="sha256:" + "6" * 64,
        harness="codex",
        targets=targets,
    )


def capability_payload() -> dict[str, object]:
    return {
        "supports_equipment_discovery": True,
        "harness": "codex",
        "capability_identity": "capability:codex/standalone-skill",
        "capability_digest": "sha256:" + "5" * 64,
        "manager_version_evidence_digest": "sha256:" + "6" * 64,
    }


def observation_payload(
    target: str,
    *,
    state: dict[str, object] | None = None,
) -> dict[str, object]:
    equipment_identity = target.split("/", 1)[1]
    normalized_state = {"enabled": True} if state is None else state
    repository = "https://example.invalid/skills.git"
    revision = "a" * 40
    return {
        "target": target,
        "equipment_identity": equipment_identity,
        "equipment_kind": equipment_identity.split(":", 1)[0],
        "present": True,
        "provider_evidence": {
            "kind": "standalone_skill",
            "canonical_root": "agents_skills",
        },
        "source_evidence": {
            "distribution_identity": "distribution:example/skills",
            "source": {
                "kind": "git",
                "repository": repository,
            },
            "resolved_source": {
                "kind": "git",
                "revision": revision,
            },
            "source_manifest_digest": "sha256:" + "8" * 64,
        },
        "restore_evidence": {
            "class": "immutable",
            "revision": revision,
            "artifact_ref": f"git+{repository}@{revision}",
            "content_digest": "sha256:" + "7" * 64,
            "native_update_control": "not_applicable",
        },
        "secret_references": [],
        "normalized_state": normalized_state,
        "state_digest": canonical_json_sha256(normalized_state),
        "capability_identity": "capability:codex/standalone-skill",
        "capability_digest": "sha256:" + "5" * 64,
        "manager_version_evidence_digest": "sha256:" + "6" * 64,
        "evidence_references": [
            {"kind": "filesystem", "reference": "agents_skills/custom/grilling"}
        ],
    }


def native_observation_payload(
    target: str,
    *,
    manager: str,
    package: str,
    version: dict[str, object],
    channel: str | None = None,
) -> dict[str, object]:
    payload = observation_payload(target)
    source: dict[str, object] = {
        "kind": "native_manager",
        "manager": manager,
        "package": package,
    }
    if channel is not None:
        source["channel"] = channel
    payload["source_evidence"] = {
        "distribution_identity": f"distribution:example/{manager}",
        "source": source,
        "resolved_source": {
            "kind": "native_manager",
            "version": deepcopy(version),
        },
        "source_manifest_digest": "sha256:" + "8" * 64,
    }
    version_value = version.get("value")
    if manager == "npx":
        assert isinstance(version_value, str)
        restore_channel = f"npm:{version_value}"
        reviewed_baseline = f"{package}@{version_value}"
    elif manager == "http":
        restore_channel = "static"
        reviewed_baseline = package
    else:
        assert isinstance(version_value, str)
        restore_channel = "latest" if channel is None else channel
        reviewed_baseline = version_value
    payload["restore_evidence"] = {
        "class": "native_rolling",
        "channel": restore_channel,
        "reviewed_baseline": reviewed_baseline,
        "observation_source": "reviewed public manager state",
        "native_update_control": "suppressible",
    }
    return payload


class FakeDiscoveryAdapter(EquipmentDiscoveryAdapter):
    def __init__(
        self,
        observations: list[dict[str, object]],
        *,
        observed_at: str = "2026-08-17T00:00:00Z",
        complete: bool = True,
    ) -> None:
        self.observations = observations
        self.observed_at = observed_at
        self.complete = complete
        self.calls: list[str] = []

    @override
    def capabilities(self) -> object:
        self.calls.append("capabilities")
        return capability_payload()

    @override
    def discover(self, request: EquipmentDiscoveryRequest) -> object:
        self.calls.append("discover")
        records = deepcopy(self.observations)
        for index, record in enumerate(records):
            record["correlation_id"] = f"ignored-{index}"
            record["observed_at"] = self.observed_at
        return {
            "request_digest": request.request_digest,
            "complete": self.complete,
            "observations": records,
            "observed_at": self.observed_at,
        }


class EquipmentDiscoveryRequestTests(unittest.TestCase):
    def test_discovery_errors_reject_literal_secret_messages(self) -> None:
        with self.assertRaises(ValueError):
            DiscoveryError("DISCOVERY_FAILED", "s" + "k-" + "x" * 32)

    def test_add_request_requires_one_or_more_exact_targets(self) -> None:
        with self.assertRaises(ValueError):
            EquipmentDiscoveryRequest.create(
                command="add",
                candidate_identity="candidate:sha256:" + "1" * 64,
                implementation_manifest_digest="sha256:" + "2" * 64,
                catalog_digest="sha256:" + "3" * 64,
                lock_digest="sha256:" + "4" * 64,
                capability_identity="capability:codex/standalone-skill",
                capability_digest="sha256:" + "5" * 64,
                manager_version_evidence_digest="sha256:" + "6" * 64,
                harness="codex",
                targets=None,
            )

    def test_exact_target_request_rejects_more_than_the_record_ceiling(self) -> None:
        targets = tuple(
            f"codex/skill:custom/target-{index:05d}"
            for index in range(MAX_DISCOVERY_RECORDS + 1)
        )

        with self.assertRaises(ValueError):
            request(targets)

    def test_request_rejects_every_oversized_structured_identity(self) -> None:
        oversized = "x" * (MAX_DISCOVERY_FIELD_CHARACTERS + 1)
        for field, value in (
            ("candidate_identity", "candidate:" + oversized),
            ("capability_identity", "capability:" + oversized),
        ):
            arguments = {
                "command": "unmanaged",
                "candidate_identity": "candidate:sha256:" + "1" * 64,
                "implementation_manifest_digest": "sha256:" + "2" * 64,
                "catalog_digest": "sha256:" + "3" * 64,
                "lock_digest": "sha256:" + "4" * 64,
                "capability_identity": "capability:codex/standalone-skill",
                "capability_digest": "sha256:" + "5" * 64,
                "manager_version_evidence_digest": "sha256:" + "6" * 64,
                "harness": "codex",
                "targets": None,
            }
            arguments[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                EquipmentDiscoveryRequest.create(**arguments)  # type: ignore[arg-type]

    def test_oversized_exact_target_is_rejected_before_adapter_calls(self) -> None:
        oversized_target = "codex/skill:" + "x" * (MAX_DISCOVERY_FIELD_CHARACTERS + 1)
        payload = thaw_json(request().document)
        assert isinstance(payload, dict)
        payload["target_scope"] = {"targets": [oversized_target]}
        payload_without_digest = {
            key: value for key, value in payload.items() if key != "request_digest"
        }
        request_digest = canonical_json_sha256(payload_without_digest)
        document = freeze_json(
            payload_without_digest | {"request_digest": request_digest}
        )
        assert isinstance(document, FrozenJsonObject)
        forged = EquipmentDiscoveryRequest(
            document,
            "unmanaged",
            "codex",
            (oversized_target,),
            request_digest,
        )
        adapter = FakeDiscoveryAdapter(
            [observation_payload("codex/skill:custom/grilling")]
        )

        collected = collect_discovery((adapter,), forged)

        self.assertIsInstance(collected, DiscoveryError)
        self.assertEqual(adapter.calls, [])

    def test_exact_target_grammar_is_canonical_and_aliases_are_rejected(self) -> None:
        request = EquipmentDiscoveryRequest.create(
            command="add",
            candidate_identity="candidate:sha256:" + "1" * 64,
            implementation_manifest_digest="sha256:" + "2" * 64,
            catalog_digest="sha256:" + "3" * 64,
            lock_digest="sha256:" + "4" * 64,
            capability_identity="capability:codex/standalone-skill",
            capability_digest="sha256:" + "5" * 64,
            manager_version_evidence_digest="sha256:" + "6" * 64,
            harness="codex",
            targets=("codex/skill:custom/grilling",),
        )

        self.assertEqual(request.targets, ("codex/skill:custom/grilling",))
        request_document = thaw_json(request.document)
        assert isinstance(request_document, dict)
        target_scope = request_document["target_scope"]
        assert isinstance(target_scope, dict)
        assert request.targets is not None
        self.assertEqual(target_scope["targets"], list(request.targets))
        self.assertTrue(request.request_digest.startswith("sha256:"))

        for suffix in (".", "_", "/", "-"):
            with self.subTest(valid_terminal=suffix):
                terminal_request = EquipmentDiscoveryRequest.create(
                    command="add",
                    candidate_identity="candidate:sha256:" + "1" * 64,
                    implementation_manifest_digest="sha256:" + "2" * 64,
                    catalog_digest="sha256:" + "3" * 64,
                    lock_digest="sha256:" + "4" * 64,
                    capability_identity="capability:codex/standalone-skill",
                    capability_digest="sha256:" + "5" * 64,
                    manager_version_evidence_digest="sha256:" + "6" * 64,
                    harness="codex",
                    targets=(f"codex/skill:custom/grilling{suffix}",),
                )
                self.assertEqual(
                    terminal_request.targets,
                    (f"codex/skill:custom/grilling{suffix}",),
                )

        for target in (
            "skill:custom/grilling",
            "codex:skill:custom/grilling",
            "Codex/skill:custom/grilling",
            "codex/skill:Custom/grilling",
            "codex//skill:custom/grilling",
        ):
            with self.subTest(target=target), self.assertRaises(ValueError):
                EquipmentDiscoveryRequest.create(
                    command="add",
                    candidate_identity="candidate:sha256:" + "1" * 64,
                    implementation_manifest_digest="sha256:" + "2" * 64,
                    catalog_digest="sha256:" + "3" * 64,
                    lock_digest="sha256:" + "4" * 64,
                    capability_identity="capability:codex/standalone-skill",
                    capability_digest="sha256:" + "5" * 64,
                    manager_version_evidence_digest="sha256:" + "6" * 64,
                    harness="codex",
                    targets=(target,),
                )


class EquipmentDiscoveryCollectionTests(unittest.TestCase):
    def _assert_report_rejected_before_untrusted_thaw(
        self,
        report: EquipmentDiscoveryReport,
        current_request: EquipmentDiscoveryRequest,
        hostile_document: FrozenJsonObject,
    ) -> None:
        thaw = discovery.thaw_json
        canonical_json_bytes = discovery.canonical_json_bytes

        def guarded_thaw(value: object) -> object:
            if value is hostile_document:
                raise AssertionError("untrusted discovery report reached thaw")
            return thaw(value)  # type: ignore[arg-type]

        def guarded_canonical_json_bytes(value: object) -> bytes:
            if value is hostile_document:
                raise AssertionError(
                    "untrusted discovery report reached canonical serialization"
                )
            return canonical_json_bytes(value)

        with (
            patch.object(discovery, "thaw_json", side_effect=guarded_thaw),
            patch.object(
                discovery,
                "canonical_json_bytes",
                side_effect=guarded_canonical_json_bytes,
            ),
        ):
            admitted = admit_discovery_report(report, current_request)

        self.assertIsInstance(admitted, DiscoveryError)

    def test_report_readmission_rejects_a_delayed_frozen_document_subclass(
        self,
    ) -> None:
        canary = "V7pDelayedDiscoveryExitPrivate9Qx"
        current_request = request()
        collected = collect_discovery(
            (
                FakeDiscoveryAdapter(
                    [observation_payload("codex/skill:custom/grilling")]
                ),
            ),
            current_request,
        )
        assert isinstance(collected, EquipmentDiscoveryReport)

        class DelayedExitDocument(FrozenJsonObject):
            def __iter__(self):  # type: ignore[no-untyped-def]
                raise SystemExit(canary)

        hostile_document = DelayedExitDocument(tuple(collected.document.items()))
        hostile_report = EquipmentDiscoveryReport(
            hostile_document,
            collected.request,
            collected.observations,
            collected.complete,
            collected.discovery_digest,
        )

        admitted = admit_discovery_report(hostile_report, current_request)

        self.assertIsInstance(admitted, DiscoveryError)
        self.assertNotIn(canary, repr(admitted))

    def test_raw_observation_rejects_oversized_target_and_equipment_identities(
        self,
    ) -> None:
        suffix = "x" * (MAX_DISCOVERY_FIELD_CHARACTERS + 1)
        payload = observation_payload("codex/skill:custom/grilling")
        payload["target"] = "codex/skill:" + suffix
        payload["equipment_identity"] = "skill:" + suffix

        collected = collect_discovery(
            (FakeDiscoveryAdapter([payload]),),
            request(),
        )

        self.assertIsInstance(collected, DiscoveryError)
        assert isinstance(collected, DiscoveryError)
        self.assertEqual(collected.code, "DISCOVERY_RESPONSE_INVALID")

    def test_oversized_report_is_rejected_before_thaw_or_serialization(self) -> None:
        current_request = request()
        collected = collect_discovery(
            (
                FakeDiscoveryAdapter(
                    [observation_payload("codex/skill:custom/grilling")]
                ),
            ),
            current_request,
        )
        assert isinstance(collected, EquipmentDiscoveryReport)
        payload = thaw_json(collected.document)
        assert isinstance(payload, dict)
        payload["hostile_extra"] = "x" * (MAX_DISCOVERY_AGGREGATE_BYTES + 1)
        hostile_document = freeze_json(payload)
        assert isinstance(hostile_document, FrozenJsonObject)
        hostile_report = EquipmentDiscoveryReport(
            hostile_document,
            collected.request,
            collected.observations,
            collected.complete,
            collected.discovery_digest,
        )

        self._assert_report_rejected_before_untrusted_thaw(
            hostile_report,
            current_request,
            hostile_document,
        )

    def test_overdeep_report_is_rejected_before_thaw_or_serialization(self) -> None:
        current_request = request()
        collected = collect_discovery(
            (
                FakeDiscoveryAdapter(
                    [observation_payload("codex/skill:custom/grilling")]
                ),
            ),
            current_request,
        )
        assert isinstance(collected, EquipmentDiscoveryReport)
        payload = thaw_json(collected.document)
        assert isinstance(payload, dict)
        nested: object = "leaf"
        for _ in range(MAX_DISCOVERY_DEPTH + 1):
            nested = [nested]
        payload["hostile_extra"] = nested
        hostile_document = freeze_json(payload)
        assert isinstance(hostile_document, FrozenJsonObject)
        hostile_report = EquipmentDiscoveryReport(
            hostile_document,
            collected.request,
            collected.observations,
            collected.complete,
            collected.discovery_digest,
        )

        self._assert_report_rejected_before_untrusted_thaw(
            hostile_report,
            current_request,
            hostile_document,
        )

    def test_oversized_observation_is_rejected_before_thaw_or_serialization(
        self,
    ) -> None:
        current_request = request()
        collected = collect_discovery(
            (
                FakeDiscoveryAdapter(
                    [observation_payload("codex/skill:custom/grilling")]
                ),
            ),
            current_request,
        )
        assert isinstance(collected, EquipmentDiscoveryReport)
        valid_observation = collected.observations[0]
        payload = thaw_json(valid_observation.document)
        assert isinstance(payload, dict)
        payload["hostile_extra"] = "x" * (MAX_DISCOVERY_RESPONSE_BYTES + 1)
        hostile_document = freeze_json(payload)
        assert isinstance(hostile_document, FrozenJsonObject)
        hostile_observation = EquipmentDiscoveryObservation(
            hostile_document,
            valid_observation.observation_identity,
            valid_observation.target,
            valid_observation.equipment_identity,
            valid_observation.equipment_kind,
            valid_observation.present,
            valid_observation.state_digest,
            valid_observation.capability_identity,
        )
        hostile_report = EquipmentDiscoveryReport(
            collected.document,
            collected.request,
            (hostile_observation,),
            collected.complete,
            collected.discovery_digest,
        )

        self._assert_report_rejected_before_untrusted_thaw(
            hostile_report,
            current_request,
            hostile_document,
        )

    def test_oversized_exact_target_scope_is_rejected_before_adapter_calls(
        self,
    ) -> None:
        targets = tuple(
            f"codex/skill:custom/target-{index:05d}"
            for index in range(MAX_DISCOVERY_RECORDS + 1)
        )
        valid_document = thaw_json(request().document)
        assert isinstance(valid_document, dict)
        valid_document["target_scope"] = {"targets": list(targets)}
        payload = {
            key: value
            for key, value in valid_document.items()
            if key != "request_digest"
        }
        request_digest = canonical_json_sha256(payload)
        document = freeze_json(payload | {"request_digest": request_digest})
        assert isinstance(document, FrozenJsonObject)
        forged = EquipmentDiscoveryRequest(
            document,
            "unmanaged",
            "codex",
            targets,
            request_digest,
        )
        adapter = FakeDiscoveryAdapter(
            [observation_payload("codex/skill:custom/grilling")]
        )

        collected = collect_discovery((adapter,), forged)

        self.assertIsInstance(collected, DiscoveryError)
        assert isinstance(collected, DiscoveryError)
        self.assertEqual(collected.code, "DISCOVERY_REQUEST_INVALID")
        self.assertEqual(adapter.calls, [])

    def test_forged_request_is_rejected_before_any_adapter_call(self) -> None:
        valid = request()
        forged = EquipmentDiscoveryRequest(
            valid.document,
            valid.command,
            valid.harness,
            valid.targets,
            "sha256:" + "0" * 64,
        )
        adapter = FakeDiscoveryAdapter(
            [observation_payload("codex/skill:custom/grilling")]
        )

        collected = collect_discovery((adapter,), forged)

        self.assertIsInstance(collected, DiscoveryError)
        assert isinstance(collected, DiscoveryError)
        self.assertEqual(collected.code, "DISCOVERY_REQUEST_INVALID")
        self.assertEqual(adapter.calls, [])

    def test_collection_is_sorted_atomic_and_ignores_ephemeral_metadata(self) -> None:
        later = observation_payload("codex/skill:custom/zeta")
        earlier = observation_payload("codex/skill:custom/alpha")
        first_adapter = FakeDiscoveryAdapter([later, earlier])
        duplicate_adapter = FakeDiscoveryAdapter(
            [earlier], observed_at="2030-01-01T00:00:00Z"
        )

        collected = collect_discovery(
            (first_adapter, duplicate_adapter),
            request(),
        )

        self.assertIsInstance(collected, EquipmentDiscoveryReport)
        assert isinstance(collected, EquipmentDiscoveryReport)
        self.assertEqual(
            tuple(item.target for item in collected.observations),
            ("codex/skill:custom/alpha", "codex/skill:custom/zeta"),
        )
        self.assertEqual(first_adapter.calls, ["capabilities", "discover"])
        self.assertEqual(duplicate_adapter.calls, ["capabilities", "discover"])
        report = thaw_json(collected.document)
        self.assertIsInstance(report, dict)
        self.assertNotIn("observed_at", repr(report))
        self.assertNotIn("correlation_id", repr(report))

    def test_closed_observation_evidence_is_emitted_canonically(self) -> None:
        payload = observation_payload("codex/skill:custom/grilling")

        collected = collect_discovery((FakeDiscoveryAdapter([payload]),), request())

        self.assertIsInstance(collected, EquipmentDiscoveryReport)
        assert isinstance(collected, EquipmentDiscoveryReport)
        observation = thaw_json(collected.observations[0].document)
        assert isinstance(observation, dict)
        semantic = {
            key: value
            for key, value in observation.items()
            if key != "observation_identity"
        }
        self.assertEqual(
            observation["observation_identity"],
            canonical_json_sha256(semantic),
        )
        self.assertEqual(observation["normalized_state"], payload["normalized_state"])
        for field in (
            "provider_evidence",
            "source_evidence",
            "restore_evidence",
            "secret_references",
            "evidence_references",
        ):
            self.assertEqual(
                observation[f"{field}_digest"],
                canonical_json_sha256(payload[field]),
            )
            self.assertNotIn(field, observation)

    def test_adapter_owned_provider_and_restore_text_is_digest_projected(
        self,
    ) -> None:
        canary = "V7pOpaque" + "PrivateValue9Qx"
        payload = native_observation_payload(
            "codex/mcp:custom/opaque",
            manager="npx",
            package=canary.lower(),
            version={"kind": "semantic_version", "value": "1.2.3"},
        )
        secret_reference = canary.lower()
        payload["provider_evidence"] = {
            "kind": "direct_mcp",
            "server_name": "opaque",
            "transport": "stdio",
            "command": "secret-exec",
            "arguments": [
                {"secret_profile_reference": secret_reference},
                {"literal": "--"},
                {"literal": "example-mcp"},
                {"literal": "--" + "to" + "ken=" + canary},
            ],
        }
        payload["secret_references"] = [
            {"kind": "secret_profile", "name": secret_reference}
        ]
        payload["evidence_references"] = [{"kind": "manager", "reference": canary}]
        restore = payload["restore_evidence"]
        assert isinstance(restore, dict)
        restore["observation_source"] = canary

        collected = collect_discovery((FakeDiscoveryAdapter([payload]),), request())

        self.assertIsInstance(collected, EquipmentDiscoveryReport)
        assert isinstance(collected, EquipmentDiscoveryReport)
        observation = thaw_json(collected.observations[0].document)
        assert isinstance(observation, dict)
        self.assertNotIn(canary, repr(collected))
        self.assertNotIn(canary.lower(), repr(collected))
        for field in (
            "provider_evidence",
            "source_evidence",
            "restore_evidence",
            "secret_references",
            "evidence_references",
        ):
            self.assertNotIn(field, observation)
            self.assertEqual(
                observation[f"{field}_digest"],
                canonical_json_sha256(payload[field]),
            )

    def test_report_readmission_rejects_legacy_and_free_form_projections(
        self,
    ) -> None:
        payload = observation_payload("codex/skill:custom/grilling")
        current_request = request()
        collected = collect_discovery(
            (FakeDiscoveryAdapter([payload]),),
            current_request,
        )
        self.assertIsInstance(collected, EquipmentDiscoveryReport)
        assert isinstance(collected, EquipmentDiscoveryReport)
        projected = thaw_json(collected.observations[0].document)
        assert isinstance(projected, dict)
        canary = "V7pOpaque" + "PrivateValue9Qx"
        for field in (
            "provider_evidence",
            "source_evidence",
            "restore_evidence",
            "secret_references",
            "evidence_references",
        ):
            legacy = deepcopy(projected)
            legacy.pop(f"{field}_digest")
            legacy[field] = deepcopy(payload[field])
            free_form = deepcopy(projected)
            free_form[f"{field}_digest"] = {
                "digest": free_form[f"{field}_digest"],
                "description": canary,
            }
            for shape, forged_document in (
                ("legacy", legacy),
                ("free_form", free_form),
            ):
                with self.subTest(field=field, shape=shape):
                    self._assert_report_readmission_rejects_projection(
                        collected,
                        current_request,
                        forged_document,
                        canary,
                    )

    def _assert_report_readmission_rejects_projection(
        self,
        collected: EquipmentDiscoveryReport,
        current_request: EquipmentDiscoveryRequest,
        forged_document: dict[str, object],
        canary: str,
    ) -> None:
        semantic = {
            key: value
            for key, value in forged_document.items()
            if key != "observation_identity"
        }
        observation_identity = canonical_json_sha256(semantic)
        forged_document["observation_identity"] = observation_identity
        frozen_observation_document = freeze_json(forged_document)
        assert isinstance(frozen_observation_document, FrozenJsonObject)
        valid_observation = collected.observations[0]
        forged_observation = EquipmentDiscoveryObservation(
            frozen_observation_document,
            observation_identity,
            valid_observation.target,
            valid_observation.equipment_identity,
            valid_observation.equipment_kind,
            valid_observation.present,
            valid_observation.state_digest,
            valid_observation.capability_identity,
        )
        discovery_digest = canonical_json_sha256(
            {
                "request_digest": current_request.request_digest,
                "complete": collected.complete,
                "observation_identities": [observation_identity],
            }
        )
        report_document = thaw_json(collected.document)
        assert isinstance(report_document, dict)
        report_document["observations"] = [forged_document]
        report_document["discovery_digest"] = discovery_digest
        frozen_report_document = freeze_json(report_document)
        assert isinstance(frozen_report_document, FrozenJsonObject)
        forged_report = EquipmentDiscoveryReport(
            frozen_report_document,
            current_request,
            (forged_observation,),
            collected.complete,
            discovery_digest,
        )

        admitted = admit_discovery_report(forged_report, current_request)

        self.assertIsInstance(admitted, DiscoveryError)
        self.assertNotIn(canary, repr(admitted))

    def test_fact_only_resolved_source_is_admitted_for_supported_sources(
        self,
    ) -> None:
        cases = (
            (
                "claude",
                "example-plugin@claude-plugins-official",
                {"kind": "semantic_version", "value": "1.7.0"},
                "stable",
            ),
            (
                "cursor",
                "example-plugin",
                {"kind": "semantic_version", "value": "2.0.1-beta.1"},
                None,
            ),
            (
                "npx",
                "@example/equipment",
                {"kind": "semantic_version", "value": "3.2.4"},
                None,
            ),
            (
                "codex",
                "example@openai-curated",
                {"kind": "revision", "value": "11c74d6b"},
                "openai-curated",
            ),
            (
                "http",
                "https://example.invalid/equipment.json",
                {"kind": "static_source"},
                "static",
            ),
        )
        for manager, package, version, channel in cases:
            with self.subTest(manager=manager):
                payload = native_observation_payload(
                    f"codex/skill:custom/{manager}",
                    manager=manager,
                    package=package,
                    version=version,
                    channel=channel,
                )

                collected = collect_discovery(
                    (FakeDiscoveryAdapter([payload]),),
                    request(),
                )

                self.assertIsInstance(collected, EquipmentDiscoveryReport)

    def test_npx_source_rejects_registry_or_version_qualified_packages(self) -> None:
        for package in ("example-equipment@beta", "example-equipment@1.2.3"):
            with self.subTest(package=package):
                payload = native_observation_payload(
                    "codex/skill:custom/npx-invalid-package",
                    manager="npx",
                    package=package,
                    version={"kind": "semantic_version", "value": "1.2.3"},
                )

                collected = collect_discovery(
                    (FakeDiscoveryAdapter([payload]),),
                    request(),
                )

                self.assertIsInstance(collected, DiscoveryError)
                assert isinstance(collected, DiscoveryError)
                self.assertEqual(collected.code, "DISCOVERY_RESPONSE_INVALID")

    def test_legacy_resolved_source_policy_duplicates_are_rejected(self) -> None:
        git_payload = observation_payload("codex/skill:custom/legacy-git")
        git_evidence = git_payload["source_evidence"]
        assert isinstance(git_evidence, dict)
        git_evidence["resolved_source"] = {
            "kind": "git",
            "repository": "https://example.invalid/skills.git",
            "branch": "main",
            "revision": "a" * 40,
        }
        native_payload = native_observation_payload(
            "codex/skill:custom/legacy-native",
            manager="npx",
            package="example-equipment",
            version={"kind": "semantic_version", "value": "1.2.3"},
        )
        native_evidence = native_payload["source_evidence"]
        assert isinstance(native_evidence, dict)
        native_evidence["resolved_source"] = {
            "kind": "native_manager",
            "manager": "npx",
            "package": "example-equipment",
            "channel": "latest",
            "version": "1.2.3",
        }

        for payload in (git_payload, native_payload):
            with self.subTest(target=payload["target"]):
                collected = collect_discovery(
                    (FakeDiscoveryAdapter([payload]),),
                    request(),
                )

                self.assertIsInstance(collected, DiscoveryError)
                assert isinstance(collected, DiscoveryError)
                self.assertEqual(collected.code, "DISCOVERY_RESPONSE_INVALID")

    def test_restore_evidence_is_bound_to_policy_and_fact_only_resolution(
        self,
    ) -> None:
        git_payload = observation_payload("codex/skill:custom/git-restore")
        git_restore = git_payload["restore_evidence"]
        assert isinstance(git_restore, dict)
        git_restore["artifact_ref"] = (
            "git+https://example.invalid/other.git@" + "a" * 40
        )
        native_payload = native_observation_payload(
            "codex/skill:custom/native-restore",
            manager="npx",
            package="example-equipment",
            version={"kind": "semantic_version", "value": "1.2.3"},
        )
        native_restore = native_payload["restore_evidence"]
        assert isinstance(native_restore, dict)
        native_restore["reviewed_baseline"] = "other-equipment@1.2.3"

        for payload in (git_payload, native_payload):
            with self.subTest(target=payload["target"]):
                collected = collect_discovery(
                    (FakeDiscoveryAdapter([payload]),),
                    request(),
                )

                self.assertIsInstance(collected, DiscoveryError)
                assert isinstance(collected, DiscoveryError)
                self.assertEqual(collected.code, "DISCOVERY_RESPONSE_INVALID")

    def test_opaque_canary_in_an_unknown_nested_field_is_not_emitted(self) -> None:
        canary = "V7p!opaque.private.value!9Qx"
        payload = observation_payload("codex/skill:custom/opaque")
        normalized_state = payload["normalized_state"]
        assert isinstance(normalized_state, dict)
        normalized_state["description"] = canary
        payload["state_digest"] = canonical_json_sha256(normalized_state)

        collected = collect_discovery((FakeDiscoveryAdapter([payload]),), request())

        self.assertIsInstance(collected, DiscoveryError)
        assert isinstance(collected, DiscoveryError)
        self.assertEqual(collected.code, "DISCOVERY_RESPONSE_INVALID")
        self.assertNotIn(canary, repr(collected))

    def test_observation_evidence_rejects_unknown_keys_and_wrong_types(self) -> None:
        def unknown_provider_key(payload: dict[str, object]) -> None:
            provider = payload["provider_evidence"]
            assert isinstance(provider, dict)
            provider["description"] = "unexpected"

        def unknown_source_key(payload: dict[str, object]) -> None:
            source_evidence = payload["source_evidence"]
            assert isinstance(source_evidence, dict)
            source = source_evidence["source"]
            assert isinstance(source, dict)
            source["ref"] = "a" * 40

        def wrong_restore_type(payload: dict[str, object]) -> None:
            restore = payload["restore_evidence"]
            assert isinstance(restore, dict)
            restore["content_digest"] = 7

        def wrong_state_type(payload: dict[str, object]) -> None:
            state = payload["normalized_state"]
            assert isinstance(state, dict)
            state["enabled"] = "yes"
            payload["state_digest"] = canonical_json_sha256(state)

        def wrong_secret_reference_type(payload: dict[str, object]) -> None:
            payload["secret_references"] = [{"kind": "secret_profile", "name": 7}]

        def wrong_evidence_reference_type(payload: dict[str, object]) -> None:
            payload["evidence_references"] = [{"kind": "filesystem", "reference": 7}]

        mutations = (
            unknown_provider_key,
            unknown_source_key,
            wrong_restore_type,
            wrong_state_type,
            wrong_secret_reference_type,
            wrong_evidence_reference_type,
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate.__name__):
                payload = observation_payload("codex/skill:custom/invalid")
                mutate(payload)

                collected = collect_discovery(
                    (FakeDiscoveryAdapter([payload]),),
                    request(),
                )

                self.assertIsInstance(collected, DiscoveryError)
                assert isinstance(collected, DiscoveryError)
                self.assertEqual(collected.code, "DISCOVERY_RESPONSE_INVALID")

    def test_observation_evidence_rejects_scalar_and_collection_overflow(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []
        oversized_scalar = observation_payload("codex/skill:custom/scalar-overflow")
        scalar_references = oversized_scalar["evidence_references"]
        assert isinstance(scalar_references, list)
        scalar_reference = scalar_references[0]
        assert isinstance(scalar_reference, dict)
        scalar_reference["reference"] = "x" * (MAX_DISCOVERY_FIELD_CHARACTERS + 1)
        cases.append(("scalar", oversized_scalar))

        oversized_collection = observation_payload(
            "codex/skill:custom/collection-overflow"
        )
        oversized_collection["evidence_references"] = [
            {
                "kind": "filesystem",
                "reference": f"agents_skills/custom/{index:03d}",
            }
            for index in range(MAX_DISCOVERY_REFERENCES + 1)
        ]
        cases.append(("collection", oversized_collection))

        for name, payload in cases:
            with self.subTest(bound=name):
                collected = collect_discovery(
                    (FakeDiscoveryAdapter([payload]),),
                    request(),
                )

                self.assertIsInstance(collected, DiscoveryError)
                assert isinstance(collected, DiscoveryError)
                self.assertEqual(collected.code, "DISCOVERY_RESPONSE_INVALID")

    def test_one_literal_secret_rejects_the_complete_collection(self) -> None:
        canary = "s" + "k-" + "x" * 32
        safe = FakeDiscoveryAdapter([observation_payload("codex/skill:custom/safe")])
        unsafe_adapter = FakeDiscoveryAdapter(
            [
                observation_payload(
                    "codex/skill:custom/secret",
                    state={"api_" + "key": canary},
                )
            ]
        )

        collected = collect_discovery((safe, unsafe_adapter), request())

        self.assertIsInstance(collected, DiscoveryError)
        assert isinstance(collected, DiscoveryError)
        self.assertEqual(collected.code, "DISCOVERY_LITERAL_SECRET")
        self.assertNotIn(canary, repr(collected))

    def test_conflicting_duplicate_observations_fail_without_partial_output(
        self,
    ) -> None:
        target = "codex/skill:custom/grilling"
        present = observation_payload(target)
        changed = observation_payload(target, state={"enabled": False})

        collected = collect_discovery(
            (FakeDiscoveryAdapter([present]), FakeDiscoveryAdapter([changed])),
            request(),
        )

        self.assertIsInstance(collected, DiscoveryError)
        assert isinstance(collected, DiscoveryError)
        self.assertEqual(collected.code, "DISCOVERY_CONFLICT")
        self.assertFalse(hasattr(collected, "observations"))

    def test_all_target_discovery_requires_an_explicit_complete_response(self) -> None:
        adapter = FakeDiscoveryAdapter(
            [observation_payload("codex/skill:custom/grilling")],
            complete=False,
        )

        collected = collect_discovery((adapter,), request())

        self.assertIsInstance(collected, DiscoveryError)
        assert isinstance(collected, DiscoveryError)
        self.assertEqual(collected.code, "DISCOVERY_SCOPE_INCOMPLETE")

    def test_system_exit_from_an_untrusted_adapter_is_redacted(self) -> None:
        canary = "s" + "k-" + "x" * 32

        class ExitingAdapter(EquipmentDiscoveryAdapter):
            @override
            def capabilities(self) -> object:
                raise SystemExit(canary)

            @override
            def discover(self, request: EquipmentDiscoveryRequest) -> object:
                raise AssertionError("discover must not run")

        collected = collect_discovery((ExitingAdapter(),), request())

        self.assertIsInstance(collected, DiscoveryError)
        assert isinstance(collected, DiscoveryError)
        self.assertEqual(collected.code, "DISCOVERY_FAILED")
        self.assertNotIn(canary, repr(collected))

    def test_oversized_response_is_rejected_before_admission(self) -> None:
        oversized_state: dict[str, object] = {
            "padding": "x" * MAX_DISCOVERY_RESPONSE_BYTES
        }
        current_request = request()
        response = {
            "request_digest": current_request.request_digest,
            "complete": True,
            "observations": [
                observation_payload(
                    "codex/skill:custom/oversized",
                    state=oversized_state,
                )
            ],
        }

        class OversizedAdapter(EquipmentDiscoveryAdapter):
            @override
            def capabilities(self) -> object:
                return capability_payload()

            @override
            def discover(self, request: EquipmentDiscoveryRequest) -> object:
                del request
                return response

        canonical_json_bytes = discovery.canonical_json_bytes

        def guard(value: object) -> bytes:
            if value is response:
                raise AssertionError(
                    "oversized adapter response reached canonical serialization"
                )
            return canonical_json_bytes(value)

        with patch.object(discovery, "canonical_json_bytes", side_effect=guard):
            collected = collect_discovery((OversizedAdapter(),), current_request)

        self.assertIsInstance(collected, DiscoveryError)
        assert isinstance(collected, DiscoveryError)
        self.assertEqual(collected.code, "DISCOVERY_RESPONSE_INVALID")


if __name__ == "__main__":
    unittest.main()
