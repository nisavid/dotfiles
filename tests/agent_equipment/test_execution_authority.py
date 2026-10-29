from __future__ import annotations

import base64
import copy
import json
import sys
import unittest
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
PREPARATION_PACKAGE_ROOT = ROOT / "agent-equipment-preparation-authority/src"
if str(PREPARATION_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PREPARATION_PACKAGE_ROOT))

import agent_equipment_preparation as PREPARATION

from agent_equipment.canonical import (
    byte_sha256,
    canonical_json_bytes,
    canonical_json_sha256,
)
from agent_equipment.execution_authority import (
    MAX_APPLY_AUTHORIZATION_BYTES,
    AdmittedApplyAuthorization,
    ApplyAdmissionRejection,
    ApplyAuthorizationTrust,
    ApplyPreclaimGate,
    ResolvedPreparationBundle,
)
from agent_equipment.model import freeze_json
from tests import test_agent_equipment_deployment_contract as CONTRACT


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _trust(
    authority_record: dict[str, object] | None = None,
) -> ApplyAuthorizationTrust:
    authority_record = authority_record or {
        "authorization_identity": "apply-authorization:sha256:" + "2" * 64,
        "issuer_identity": "authority:fixture/operator",
        "execution_domain_identity": "execution-domain:fixture/global-ledger-v1",
        "execution_nonce": "execution-nonce:sha256:" + "4" * 64,
        "run_identity": "run:sha256:" + "5" * 64,
        "bindings": {
            "candidate_identity": "candidate:fixture/controller-v1",
            "implementation_manifest_digest": _digest("1"),
            "operator_review_package_digest": _digest("6"),
        },
    }
    bindings = authority_record["bindings"]
    assert isinstance(bindings, dict)
    return ApplyAuthorizationTrust(
        expected_candidate_identity=str(bindings["candidate_identity"]),
        expected_implementation_manifest_digest=str(
            bindings["implementation_manifest_digest"]
        ),
        expected_authorization_identity=str(authority_record["authorization_identity"]),
        expected_authorization_digest=canonical_json_sha256(authority_record),
        expected_execution_domain_identity=str(
            authority_record["execution_domain_identity"]
        ),
        expected_execution_nonce=str(authority_record["execution_nonce"]),
        expected_run_identity=str(authority_record["run_identity"]),
        expected_operator_review_package_digest=str(
            bindings["operator_review_package_digest"]
        ),
        expected_issuer_identity=str(authority_record["issuer_identity"]),
        trusted_now=datetime(2026, 8, 13, 7, 30, tzinfo=timezone.utc),
    )


class _RecordingResolver:
    def __init__(self, resolution: object | None = None) -> None:
        self.requests: list[str] = []
        self.resolution = resolution

    def resolve(self, preparation_bundle_digest: str) -> object:
        self.requests.append(preparation_bundle_digest)
        if self.resolution is None:
            raise AssertionError("rejected authorization must not be resolved")
        return self.resolution


_ARTIFACT_ROLES = (
    "plan_action_set",
    "captured_state",
    "capability_binding_set",
    "adapter_manifest_set",
    "gate_manifest",
    "capture_observation_authority_set",
    "prepared_action_authority_set",
)


def _seal_bundle(document: dict[str, object]) -> None:
    identity_payload = copy.deepcopy(document)
    identity_payload.pop("preparation_bundle_identity")
    identity_payload.pop("preparation_bundle_digest")
    document["preparation_bundle_identity"] = (
        "preparation-bundle:" + canonical_json_sha256(identity_payload)
    )
    digest_payload = copy.deepcopy(document)
    digest_payload.pop("preparation_bundle_digest")
    document["preparation_bundle_digest"] = canonical_json_sha256(digest_payload)


def _seal_authorization(document: dict[str, object]) -> None:
    identity_payload = copy.deepcopy(document)
    identity_payload.pop("authorization_identity")
    document["authorization_identity"] = "apply-authorization:" + canonical_json_sha256(
        identity_payload
    )


def _seal_authority_set(document: dict[str, object], prefix: str) -> None:
    identity_payload = copy.deepcopy(document)
    identity_payload.pop("authority_set_identity")
    identity_payload.pop("authority_set_digest")
    document["authority_set_identity"] = prefix + canonical_json_sha256(
        identity_payload
    )
    digest_payload = copy.deepcopy(document)
    digest_payload.pop("authority_set_digest")
    document["authority_set_digest"] = canonical_json_sha256(digest_payload)


class _ProducerFactsAdapter:
    def prepare(self, request_bytes: bytes) -> bytes:
        request = json.loads(request_bytes)
        captured_pre_state = CONTRACT.normalized_state(present=False)
        expected_post_state = CONTRACT.normalized_state(present=True)
        response: dict[str, object] = {
            "contract_version": "adapter-contract-v1",
            "request_identity": request["request_identity"],
            "request_digest": request["request_digest"],
            "echo_bindings": copy.deepcopy(request["echo_bindings"]),
            "captured_pre_state": captured_pre_state,
            "captured_pre_state_digest": canonical_json_sha256(captured_pre_state),
            "expected_post_state": expected_post_state,
            "expected_post_state_digest": canonical_json_sha256(expected_post_state),
            "facts_digest": _digest("0"),
        }
        facts_payload = copy.deepcopy(response)
        facts_payload.pop("facts_digest")
        response["facts_digest"] = canonical_json_sha256(facts_payload)
        return canonical_json_bytes(response)


@lru_cache(maxsize=1)
def _producer_preparation_bytes() -> tuple[bytes, bytes, tuple[tuple[str, bytes], ...]]:
    plan = CONTRACT.valid_plan_action_set(1)
    captured_state = CONTRACT.valid_captured_state(plan)
    schema_names = (
        "adapter-contract-v1.schema.json",
        "captured-state-v1.schema.json",
        "execution-authority-v1.schema.json",
        "plan-action-set-v1.schema.json",
    )
    schema_directory = ROOT / "home/private_dot_local/lib/agent-equipment/schemas"
    schema_documents = {
        name: (schema_directory / name).read_bytes() for name in schema_names
    }
    gate_manifest_bytes = PREPARATION.build_gate_manifest(
        gate_identity="preparation-gate:agent-equipment/v1",
        runtime_identity="cpython:fixture/v1",
        runtime_executable_digest=_digest("8"),
        files={"agent_equipment_preparation/preparation.py": b"fixture"},
        schema_documents=schema_documents,
    )
    action_evidence = plan["actions"][0]
    assert isinstance(action_evidence, dict)
    action = action_evidence["action_payload"]
    assert isinstance(action, dict)
    adapter_manifest_bytes = PREPARATION.build_adapter_manifest(
        adapter_identity=str(action["adapter_identity"]),
        adapter_version=str(action["adapter_version"]),
        implementation_identity=("adapter-implementation:fixture/claude-plugin-v1"),
        implementation_manifest_digest=_digest("7"),
        capability_binding={
            "capability_identity": action["capability_identity"],
            "capability_digest": action["capability_digest"],
            "manager_version_evidence_digest": action[
                "manager_version_evidence_digest"
            ],
        },
    )
    adapter_manifest_set_bytes = PREPARATION.build_adapter_manifest_set(
        [adapter_manifest_bytes]
    )
    adapter_manifest_set = json.loads(adapter_manifest_set_bytes)
    assert isinstance(adapter_manifest_set, dict)
    capture_bindings = captured_state["bindings"]
    assert isinstance(capture_bindings, dict)
    with TemporaryDirectory() as directory:
        store = PREPARATION.FilePreparationStore(
            Path(directory),
            store_identity="preparation-store:fixture/protected-v1",
        )
        gate = PREPARATION.PreparationGate(
            gate_manifest_bytes=gate_manifest_bytes,
            expected_gate_manifest_digest=str(
                json.loads(gate_manifest_bytes)["manifest_digest"]
            ),
            schema_documents=schema_documents,
            adapters=(
                PREPARATION.BoundPreparationAdapter(
                    manifest_bytes=adapter_manifest_bytes,
                    adapter=_ProducerFactsAdapter(),
                ),
            ),
            expected_adapter_manifest_set_digest=str(
                adapter_manifest_set["adapter_manifest_set_digest"]
            ),
            store=store,
        )
        result = gate.prepare(
            canonical_json_bytes(plan),
            canonical_json_bytes(captured_state),
            PREPARATION.PreparationTrust(
                expected_candidate_identity=str(plan["candidate_identity"]),
                expected_implementation_manifest_digest=str(
                    plan["implementation_manifest_digest"]
                ),
                expected_plan_digest=str(plan["plan_digest"]),
                expected_plan_action_set_digest=str(plan["action_set_digest"]),
                expected_captured_state_identity="capture:fixture/run-v1",
                expected_captured_state_digest=canonical_json_sha256(captured_state),
                expected_capability_set_digest=str(
                    capture_bindings["capability_set_digest"]
                ),
            ),
        )
    if not isinstance(result, PREPARATION.PreparedBundleCommit):
        raise TypeError(f"fixture preparation failed: {result!r}")
    bundle = json.loads(result.bundle_bytes)
    assert isinstance(bundle, dict)
    artifacts = bundle["artifacts"]
    assert isinstance(artifacts, dict)
    artifact_bytes = tuple(
        (
            role,
            base64.b64decode(artifacts[role]["bytes_base64"], validate=True),
        )
        for role in _ARTIFACT_ROLES
    )
    return result.receipt_bytes, result.bundle_bytes, artifact_bytes


def _valid_preclaim_material() -> tuple[
    dict[str, object],
    ResolvedPreparationBundle,
    dict[str, bytes],
]:
    receipt_bytes, bundle_bytes, artifacts = _producer_preparation_bytes()
    bundle = json.loads(bundle_bytes)
    assert isinstance(bundle, dict)
    bundle_bindings = bundle["bindings"]
    assert isinstance(bundle_bindings, dict)
    authorization_bindings = {
        key: bundle_bindings[key]
        for key in (
            "candidate_identity",
            "implementation_manifest_digest",
            "catalog_digest",
            "lock_digest",
            "plan_digest",
            "plan_action_set_digest",
            "capability_set_digest",
            "captured_state_identity",
            "captured_state_digest",
            "capture_observation_authority_set_identity",
            "capture_observation_authority_set_digest",
            "prepared_action_authority_set_identity",
            "prepared_action_authority_set_digest",
        )
    }
    authorization_bindings.update(
        {
            "preparation_bundle_digest": bundle["preparation_bundle_digest"],
            "expected_case_manifest_digest": _digest("e"),
            "operator_review_package_digest": _digest("f"),
        }
    )
    authority_record: dict[str, object] = {
        "schema_version": "agent-equipment-apply-authorization/v1",
        "authorization_identity": "apply-authorization:sha256:" + "0" * 64,
        "issuer_identity": "authority:fixture/operator",
        "issued_at": "2026-08-13T07:00:00Z",
        "not_before": "2026-08-13T07:00:00Z",
        "expires_at": "2026-08-13T08:00:00Z",
        "execution_nonce": "execution-nonce:sha256:" + "1" * 64,
        "run_identity": "run:sha256:" + "2" * 64,
        "execution_domain_identity": "execution-domain:fixture/global-ledger-v1",
        "command": "apply",
        "bindings": authorization_bindings,
    }
    _seal_authorization(authority_record)
    return (
        authority_record,
        ResolvedPreparationBundle(
            receipt_bytes=receipt_bytes,
            bundle_bytes=bundle_bytes,
        ),
        dict(artifacts),
    )


def _reseal_resolution(
    authorization: dict[str, object],
    resolution: ResolvedPreparationBundle,
    *,
    mutate_bundle: object,
) -> ResolvedPreparationBundle:
    bundle = json.loads(resolution.bundle_bytes)
    assert isinstance(bundle, dict)
    assert callable(mutate_bundle)
    mutate_bundle(bundle)
    _seal_bundle(bundle)
    bundle_bytes = canonical_json_bytes(bundle)

    receipt = json.loads(resolution.receipt_bytes)
    assert isinstance(receipt, dict)
    payload = receipt["payload"]
    assert isinstance(payload, dict)
    bindings = bundle["bindings"]
    assert isinstance(bindings, dict)
    payload.update(
        {
            "preparation_bundle_identity": bundle["preparation_bundle_identity"],
            "preparation_bundle_digest": bundle["preparation_bundle_digest"],
            "preparation_bundle_bytes_digest": byte_sha256(bundle_bytes),
            "preparation_gate_identity": bindings["preparation_gate_identity"],
            "preparation_gate_manifest_digest": bindings[
                "preparation_gate_manifest_digest"
            ],
            "store_identity": bindings["store_identity"],
            "store_generation": bindings["store_generation"],
        }
    )
    receipt["receipt_identity"] = "preparation-receipt:" + canonical_json_sha256(
        payload
    )
    authorization_bindings = authorization["bindings"]
    assert isinstance(authorization_bindings, dict)
    for field in (
        "candidate_identity",
        "implementation_manifest_digest",
        "catalog_digest",
        "lock_digest",
        "plan_digest",
        "plan_action_set_digest",
        "capability_set_digest",
        "captured_state_identity",
        "captured_state_digest",
        "capture_observation_authority_set_identity",
        "capture_observation_authority_set_digest",
        "prepared_action_authority_set_identity",
        "prepared_action_authority_set_digest",
    ):
        authorization_bindings[field] = bindings[field]
    authorization_bindings["preparation_bundle_digest"] = bundle[
        "preparation_bundle_digest"
    ]
    _seal_authorization(authorization)
    return ResolvedPreparationBundle(
        receipt_bytes=canonical_json_bytes(receipt),
        bundle_bytes=bundle_bytes,
    )


def _artifact_document(
    bundle: dict[str, object],
    role: str,
) -> dict[str, object]:
    artifacts = bundle["artifacts"]
    assert isinstance(artifacts, dict)
    member = artifacts[role]
    assert isinstance(member, dict)
    document = json.loads(base64.b64decode(member["bytes_base64"], validate=True))
    assert isinstance(document, dict)
    return document


def _replace_artifact_document(
    bundle: dict[str, object],
    role: str,
    document: dict[str, object],
) -> None:
    artifacts = bundle["artifacts"]
    assert isinstance(artifacts, dict)
    member = artifacts[role]
    assert isinstance(member, dict)
    payload = canonical_json_bytes(document)
    member["bytes_base64"] = base64.b64encode(payload).decode("ascii")
    member["bytes_digest"] = byte_sha256(payload)


def _seal_prepared_authority(authority: dict[str, object]) -> None:
    payload = copy.deepcopy(authority)
    payload.pop("authority_digest")
    authority["authority_digest"] = canonical_json_sha256(payload)


def _seal_adapter_manifest(manifest: dict[str, object]) -> None:
    identity_payload = copy.deepcopy(manifest)
    identity_payload.pop("adapter_manifest_identity")
    identity_payload.pop("adapter_manifest_digest")
    manifest["adapter_manifest_identity"] = (
        "preparation-adapter-manifest:"
        + canonical_json_sha256(identity_payload)
    )
    digest_payload = copy.deepcopy(manifest)
    digest_payload.pop("adapter_manifest_digest")
    manifest["adapter_manifest_digest"] = canonical_json_sha256(digest_payload)


def _bind_resealed_adapter_set(
    bundle: dict[str, object],
    manifest_set: dict[str, object],
) -> None:
    manifests = manifest_set["manifests"]
    assert isinstance(manifests, list)
    manifests.sort(key=lambda manifest: manifest["adapter_manifest_identity"])
    identity_payload = copy.deepcopy(manifest_set)
    identity_payload.pop("adapter_manifest_set_identity")
    identity_payload.pop("adapter_manifest_set_digest")
    manifest_set["adapter_manifest_set_identity"] = (
        "preparation-adapter-manifest-set:"
        + canonical_json_sha256(identity_payload)
    )
    digest_payload = copy.deepcopy(manifest_set)
    digest_payload.pop("adapter_manifest_set_digest")
    manifest_set["adapter_manifest_set_digest"] = canonical_json_sha256(
        digest_payload
    )
    _replace_artifact_document(bundle, "adapter_manifest_set", manifest_set)

    bindings = bundle["bindings"]
    assert isinstance(bindings, dict)
    manifest_set_digest = manifest_set["adapter_manifest_set_digest"]
    bindings["preparation_adapter_manifest_set_digest"] = manifest_set_digest

    capture_set = _artifact_document(
        bundle,
        "capture_observation_authority_set",
    )
    capture_bindings = capture_set["bindings"]
    assert isinstance(capture_bindings, dict)
    capture_bindings["preparation_adapter_manifest_set_digest"] = (
        manifest_set_digest
    )
    _seal_authority_set(capture_set, "capture-observation-authority-set:")
    _replace_artifact_document(
        bundle,
        "capture_observation_authority_set",
        capture_set,
    )
    bindings["capture_observation_authority_set_identity"] = capture_set[
        "authority_set_identity"
    ]
    bindings["capture_observation_authority_set_digest"] = capture_set[
        "authority_set_digest"
    ]

    manifest_index = {}
    for manifest in manifests:
        assert isinstance(manifest, dict)
        capability = manifest["capability_binding"]
        assert isinstance(capability, dict)
        manifest_index[
            (
                manifest["adapter_identity"],
                manifest["adapter_version"],
                capability["capability_identity"],
                capability["capability_digest"],
                capability["manager_version_evidence_digest"],
            )
        ] = manifest

    prepared_set = _artifact_document(bundle, "prepared_action_authority_set")
    prepared_bindings = prepared_set["bindings"]
    assert isinstance(prepared_bindings, dict)
    prepared_bindings["preparation_adapter_manifest_set_digest"] = (
        manifest_set_digest
    )
    prepared_bindings["capture_observation_authority_set_identity"] = (
        capture_set["authority_set_identity"]
    )
    prepared_bindings["capture_observation_authority_set_digest"] = capture_set[
        "authority_set_digest"
    ]
    authorities = prepared_set["authorities"]
    assert isinstance(authorities, list)
    for authority in authorities:
        assert isinstance(authority, dict)
        authority["capture_observation_authority_set_identity"] = capture_set[
            "authority_set_identity"
        ]
        authority["capture_observation_authority_set_digest"] = capture_set[
            "authority_set_digest"
        ]
        adapter_binding = authority["adapter_binding"]
        capability_binding = authority["route_capability_binding"]
        assert isinstance(adapter_binding, dict)
        assert isinstance(capability_binding, dict)
        manifest = manifest_index.get(
            (
                adapter_binding["adapter_identity"],
                adapter_binding["adapter_version"],
                capability_binding["capability_identity"],
                capability_binding["capability_digest"],
                capability_binding["manager_version_evidence_digest"],
            )
        )
        if manifest is not None:
            for field in (
                "adapter_manifest_identity",
                "adapter_manifest_digest",
                "adapter_implementation_identity",
                "adapter_implementation_manifest_digest",
            ):
                adapter_binding[field] = manifest[field]
        _seal_prepared_authority(authority)
    _seal_authority_set(prepared_set, "prepared-action-authority-set:")
    _replace_artifact_document(bundle, "prepared_action_authority_set", prepared_set)
    bindings["prepared_action_authority_set_identity"] = prepared_set[
        "authority_set_identity"
    ]
    bindings["prepared_action_authority_set_digest"] = prepared_set[
        "authority_set_digest"
    ]


def _bind_resealed_gate_manifest(
    bundle: dict[str, object],
    gate_manifest: dict[str, object],
) -> None:
    digest_payload = copy.deepcopy(gate_manifest)
    digest_payload.pop("manifest_digest")
    gate_manifest["manifest_digest"] = canonical_json_sha256(digest_payload)
    _replace_artifact_document(bundle, "gate_manifest", gate_manifest)
    bindings = bundle["bindings"]
    assert isinstance(bindings, dict)
    bindings["preparation_gate_manifest_digest"] = gate_manifest[
        "manifest_digest"
    ]


def _bind_resealed_capture_set(
    bundle: dict[str, object],
    capture_set: dict[str, object],
) -> None:
    _seal_authority_set(
        capture_set,
        "capture-observation-authority-set:",
    )
    _replace_artifact_document(
        bundle,
        "capture_observation_authority_set",
        capture_set,
    )
    bindings = bundle["bindings"]
    assert isinstance(bindings, dict)
    bindings["capture_observation_authority_set_identity"] = capture_set[
        "authority_set_identity"
    ]
    bindings["capture_observation_authority_set_digest"] = capture_set[
        "authority_set_digest"
    ]
    prepared_set = _artifact_document(
        bundle,
        "prepared_action_authority_set",
    )
    prepared_bindings = prepared_set["bindings"]
    assert isinstance(prepared_bindings, dict)
    prepared_bindings["capture_observation_authority_set_identity"] = capture_set[
        "authority_set_identity"
    ]
    prepared_bindings["capture_observation_authority_set_digest"] = capture_set[
        "authority_set_digest"
    ]
    authorities = prepared_set["authorities"]
    assert isinstance(authorities, list)
    for authority in authorities:
        assert isinstance(authority, dict)
        authority["capture_observation_authority_set_identity"] = capture_set[
            "authority_set_identity"
        ]
        authority["capture_observation_authority_set_digest"] = capture_set[
            "authority_set_digest"
        ]
        _seal_prepared_authority(authority)
    _seal_authority_set(prepared_set, "prepared-action-authority-set:")
    _replace_artifact_document(
        bundle,
        "prepared_action_authority_set",
        prepared_set,
    )
    bindings["prepared_action_authority_set_identity"] = prepared_set[
        "authority_set_identity"
    ]
    bindings["prepared_action_authority_set_digest"] = prepared_set[
        "authority_set_digest"
    ]


def _bind_resealed_captured_state(
    bundle: dict[str, object],
    captured_state: dict[str, object],
) -> None:
    _replace_artifact_document(bundle, "captured_state", captured_state)
    captured_state_digest = canonical_json_sha256(captured_state)
    bindings = bundle["bindings"]
    assert isinstance(bindings, dict)
    bindings["captured_state_digest"] = captured_state_digest

    capture_set = _artifact_document(
        bundle,
        "capture_observation_authority_set",
    )
    capture_bindings = capture_set["bindings"]
    assert isinstance(capture_bindings, dict)
    capture_bindings["captured_state_digest"] = captured_state_digest
    observations = capture_set["observations"]
    assert isinstance(observations, list)
    for observation in observations:
        assert isinstance(observation, dict)
        observation["captured_state_digest"] = captured_state_digest

    prepared_set = _artifact_document(bundle, "prepared_action_authority_set")
    prepared_bindings = prepared_set["bindings"]
    assert isinstance(prepared_bindings, dict)
    prepared_bindings["captured_state_digest"] = captured_state_digest
    authorities = prepared_set["authorities"]
    assert isinstance(authorities, list)
    for authority in authorities:
        assert isinstance(authority, dict)
        authority["captured_state_digest"] = captured_state_digest
        _seal_prepared_authority(authority)
    _seal_authority_set(prepared_set, "prepared-action-authority-set:")
    _replace_artifact_document(bundle, "prepared_action_authority_set", prepared_set)
    bindings["prepared_action_authority_set_identity"] = prepared_set[
        "authority_set_identity"
    ]
    bindings["prepared_action_authority_set_digest"] = prepared_set[
        "authority_set_digest"
    ]
    _bind_resealed_capture_set(bundle, capture_set)


def _bind_resealed_plan_mutation(
    bundle: dict[str, object],
    mutate_action: object,
) -> None:
    assert callable(mutate_action)
    plan = _artifact_document(bundle, "plan_action_set")
    actions = plan["actions"]
    assert isinstance(actions, list)
    evidence = actions[0]
    assert isinstance(evidence, dict)
    action = evidence["action_payload"]
    assert isinstance(action, dict)
    old_action_identity = action["action_identity"]
    old_targets = copy.deepcopy(action["write_targets"])
    mutate_action(action)
    action["desired_state_digest"] = canonical_json_sha256(action["desired_state"])
    action["action_identity"] = "action:" + canonical_json_sha256(
        {
            "plan_digest": action["plan_digest"],
            "ordinal": action["ordinal"],
            "route_id": action["route_identity"],
            "operation": action["operation"],
            "desired_state_digest": action["desired_state_digest"],
        }
    )
    evidence["action_digest"] = canonical_json_sha256(action)
    plan_payload = copy.deepcopy(plan)
    plan_payload.pop("action_set_digest")
    plan["action_set_digest"] = canonical_json_sha256(plan_payload)
    _replace_artifact_document(bundle, "plan_action_set", plan)

    bindings = bundle["bindings"]
    assert isinstance(bindings, dict)
    bindings["plan_action_set_digest"] = plan["action_set_digest"]

    captured = _artifact_document(bundle, "captured_state")
    captured_bindings = captured["bindings"]
    assert isinstance(captured_bindings, dict)
    captured_bindings["plan_action_set_digest"] = plan["action_set_digest"]
    routes = captured["provider_routes"]
    captured_surfaces = captured["surfaces"]
    assert isinstance(routes, list)
    assert isinstance(captured_surfaces, list)
    for route in routes:
        assert isinstance(route, dict)
        references = route["planned_actions"]
        assert isinstance(references, list)
        for reference in references:
            assert isinstance(reference, dict)
            if reference["action_identity"] != old_action_identity:
                continue
            reference["action_identity"] = action["action_identity"]
            route["equipment_identities"] = copy.deepcopy(
                action["equipment_identities"]
            )
            route["controlled_equipment_identities"] = copy.deepcopy(
                action["controlled_equipment_identities"]
            )
            reference["action_digest"] = evidence["action_digest"]
            write_bindings = reference["write_bindings"]
            assert isinstance(write_bindings, list)
            new_targets = action["write_targets"]
            assert isinstance(old_targets, list)
            assert isinstance(new_targets, list)
            old_by_surface = {
                target["write_surface_identity"]: target
                for target in old_targets
                if isinstance(target, dict)
            }
            new_by_surface = {
                target["write_surface_identity"]: target
                for target in new_targets
                if isinstance(target, dict)
            }
            for surface, old_target in old_by_surface.items():
                new_target = new_by_surface.get(surface)
                if new_target is None:
                    continue
                for write_binding in write_bindings:
                    assert isinstance(write_binding, dict)
                    if write_binding["target_identity"] == old_target["target_identity"]:
                        write_binding["target_identity"] = new_target["target_identity"]
            write_bindings.sort(key=lambda item: item["target_identity"])
            target_by_identity = {
                target["target_identity"]: target
                for target in new_targets
                if isinstance(target, dict)
            }
            surface_by_identity = {
                surface["surface_id"]: surface
                for surface in captured_surfaces
                if isinstance(surface, dict)
            }
            for write_binding in write_bindings:
                assert isinstance(write_binding, dict)
                target = target_by_identity[write_binding["target_identity"]]
                surface = surface_by_identity[write_binding["surface_id"]]
                surface["kind"] = target["surface_kind"]
                surface["locator"] = copy.deepcopy(target["locator"])
                if "equipment_identity" in target:
                    surface["equipment_identity"] = target["equipment_identity"]
                else:
                    surface.pop("equipment_identity", None)
    _replace_artifact_document(bundle, "captured_state", captured)
    captured_digest = canonical_json_sha256(captured)
    bindings["captured_state_digest"] = captured_digest

    capture_set = _artifact_document(bundle, "capture_observation_authority_set")
    capture_bindings = capture_set["bindings"]
    assert isinstance(capture_bindings, dict)
    capture_bindings["plan_action_set_digest"] = plan["action_set_digest"]
    capture_bindings["captured_state_digest"] = captured_digest
    observations = capture_set["observations"]
    assert isinstance(observations, list)
    for observation in observations:
        assert isinstance(observation, dict)
        if observation["action_identity"] == old_action_identity:
            observation["action_identity"] = action["action_identity"]
        observation["captured_state_digest"] = captured_digest
    _seal_authority_set(capture_set, "capture-observation-authority-set:")
    _replace_artifact_document(bundle, "capture_observation_authority_set", capture_set)
    bindings["capture_observation_authority_set_identity"] = capture_set[
        "authority_set_identity"
    ]
    bindings["capture_observation_authority_set_digest"] = capture_set[
        "authority_set_digest"
    ]

    prepared_set = _artifact_document(bundle, "prepared_action_authority_set")
    prepared_bindings = prepared_set["bindings"]
    assert isinstance(prepared_bindings, dict)
    prepared_bindings["plan_action_set_digest"] = plan["action_set_digest"]
    prepared_bindings["captured_state_digest"] = captured_digest
    prepared_bindings["capture_observation_authority_set_identity"] = capture_set[
        "authority_set_identity"
    ]
    prepared_bindings["capture_observation_authority_set_digest"] = capture_set[
        "authority_set_digest"
    ]
    authorities = prepared_set["authorities"]
    assert isinstance(authorities, list)
    for authority in authorities:
        assert isinstance(authority, dict)
        if authority["action_identity"] == old_action_identity:
            authority.update(
                {
                    "action_identity": action["action_identity"],
                    "provider": copy.deepcopy(action["provider"]),
                    "provider_digest": canonical_json_sha256(action["provider"]),
                    "operation": action["operation"],
                    "operation_digest": canonical_json_sha256(action["operation"]),
                    "desired_state": copy.deepcopy(action["desired_state"]),
                    "desired_state_digest": action["desired_state_digest"],
                }
            )
        authority["action_digest"] = evidence["action_digest"]
        authority["plan_action_set_digest"] = plan["action_set_digest"]
        authority["captured_state_digest"] = captured_digest
        authority["capture_observation_authority_set_identity"] = capture_set[
            "authority_set_identity"
        ]
        authority["capture_observation_authority_set_digest"] = capture_set[
            "authority_set_digest"
        ]
        _seal_prepared_authority(authority)
    _seal_authority_set(prepared_set, "prepared-action-authority-set:")
    _replace_artifact_document(bundle, "prepared_action_authority_set", prepared_set)
    bindings["prepared_action_authority_set_identity"] = prepared_set[
        "authority_set_identity"
    ]
    bindings["prepared_action_authority_set_digest"] = prepared_set[
        "authority_set_digest"
    ]


class ApplyPreclaimAdmissionTest(unittest.TestCase):
    def test_admission_reloads_and_rehashes_authenticated_bundle_before_cas(
        self,
    ) -> None:
        authorization, resolution, artifact_bytes = _valid_preclaim_material()
        resolver = _RecordingResolver(resolution)
        gate = ApplyPreclaimGate(resolver)

        result = gate.admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, AdmittedApplyAuthorization)
        assert isinstance(result, AdmittedApplyAuthorization)
        bindings = authorization["bindings"]
        assert isinstance(bindings, dict)
        self.assertEqual(
            resolver.requests,
            [bindings["preparation_bundle_digest"]],
        )
        self.assertEqual(result.authorization_record, freeze_json(authorization))
        self.assertEqual(
            result.authorization_digest,
            canonical_json_sha256(authorization),
        )
        self.assertEqual(
            result.artifacts.as_dict(),
            artifact_bytes,
        )
        self.assertFalse(hasattr(gate, "authorize_apply_start"))

    def test_admission_uses_the_resolver_bound_at_construction(self) -> None:
        authorization, resolution, _ = _valid_preclaim_material()
        resolver = _RecordingResolver(resolution)
        gate = ApplyPreclaimGate(resolver)
        replacement_effects: list[str] = []

        def replacement(preparation_bundle_digest: str) -> object:
            replacement_effects.append(preparation_bundle_digest)
            return resolution

        resolver.resolve = replacement  # type: ignore[method-assign]
        result = gate.admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, AdmittedApplyAuthorization)
        bindings = authorization["bindings"]
        assert isinstance(bindings, dict)
        self.assertEqual(
            resolver.requests,
            [bindings["preparation_bundle_digest"]],
        )
        self.assertEqual(replacement_effects, [])

    def test_admission_uses_only_the_import_time_captured_schema_set(self) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        with mock.patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("preclaim reread a mutable Schema path"),
        ):
            result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
                canonical_json_bytes(authorization),
                _trust(authorization),
            )

        self.assertIsInstance(result, AdmittedApplyAuthorization)

    def test_untrusted_authorization_bindings_never_reach_the_resolver(self) -> None:
        authorization, resolution, _ = _valid_preclaim_material()
        trust = _trust(authorization)
        bindings = authorization["bindings"]
        assert isinstance(bindings, dict)
        bindings["candidate_identity"] = "candidate:fixture/substitution-v1"
        _seal_authorization(authorization)
        resolver = _RecordingResolver(resolution)

        result = ApplyPreclaimGate(resolver).admit(
            canonical_json_bytes(authorization),
            trust,
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)
        self.assertEqual(resolver.requests, [])
        self.assertFalse(hasattr(trust, "expected_bindings"))

    def test_closed_authorization_schema_rejects_invalid_nonce_before_resolution(
        self,
    ) -> None:
        authorization, resolution, _ = _valid_preclaim_material()
        authorization["execution_nonce"] = "caller-selected-invalid-nonce"
        _seal_authorization(authorization)
        resolver = _RecordingResolver(resolution)

        result = ApplyPreclaimGate(resolver).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)
        assert isinstance(result, ApplyAdmissionRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["APPLY_AUTHORIZATION_SCHEMA_INVALID"],
        )
        self.assertEqual(resolver.requests, [])

    def test_coordinated_outer_reseal_cannot_hide_an_invalid_artifact_self_digest(
        self,
    ) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def invalidate_capability_set(bundle: dict[str, object]) -> None:
            artifacts = bundle["artifacts"]
            bindings = bundle["bindings"]
            assert isinstance(artifacts, dict)
            assert isinstance(bindings, dict)
            member = artifacts["capability_binding_set"]
            assert isinstance(member, dict)
            document = json.loads(base64.b64decode(member["bytes_base64"]))
            assert isinstance(document, dict)
            document["capability_set_digest"] = _digest("0")
            payload = canonical_json_bytes(document)
            member["bytes_base64"] = base64.b64encode(payload).decode("ascii")
            member["bytes_digest"] = byte_sha256(payload)
            bindings["capability_set_digest"] = document["capability_set_digest"]

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=invalidate_capability_set,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)
        assert isinstance(result, ApplyAdmissionRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["PREPARATION_ARTIFACT_BINDING_INVALID"],
        )

    def test_coordinated_reseal_cannot_hide_schema_invalid_captured_state(
        self,
    ) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def remove_required_capture_field(bundle: dict[str, object]) -> None:
            captured_state = _artifact_document(bundle, "captured_state")
            captured_state.pop("migration_id")
            captured_state_digest = canonical_json_sha256(captured_state)
            _replace_artifact_document(bundle, "captured_state", captured_state)
            bindings = bundle["bindings"]
            assert isinstance(bindings, dict)
            bindings["captured_state_digest"] = captured_state_digest
            capture_set = _artifact_document(
                bundle,
                "capture_observation_authority_set",
            )
            capture_bindings = capture_set["bindings"]
            assert isinstance(capture_bindings, dict)
            capture_bindings["captured_state_digest"] = captured_state_digest
            observations = capture_set["observations"]
            assert isinstance(observations, list)
            for observation in observations:
                assert isinstance(observation, dict)
                observation["captured_state_digest"] = captured_state_digest
            prepared_set = _artifact_document(
                bundle,
                "prepared_action_authority_set",
            )
            prepared_bindings = prepared_set["bindings"]
            assert isinstance(prepared_bindings, dict)
            prepared_bindings["captured_state_digest"] = captured_state_digest
            authorities = prepared_set["authorities"]
            assert isinstance(authorities, list)
            for authority in authorities:
                assert isinstance(authority, dict)
                authority["captured_state_digest"] = captured_state_digest
                _seal_prepared_authority(authority)
            _seal_authority_set(prepared_set, "prepared-action-authority-set:")
            _replace_artifact_document(
                bundle,
                "prepared_action_authority_set",
                prepared_set,
            )
            bindings["prepared_action_authority_set_identity"] = prepared_set[
                "authority_set_identity"
            ]
            bindings["prepared_action_authority_set_digest"] = prepared_set[
                "authority_set_digest"
            ]
            _bind_resealed_capture_set(bundle, capture_set)

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=remove_required_capture_field,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)
        assert isinstance(result, ApplyAdmissionRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["PREPARATION_ARTIFACT_SCHEMA_INVALID"],
        )

    def test_each_exact_artifact_stream_is_independently_schema_validated(
        self,
    ) -> None:
        for role in _ARTIFACT_ROLES:
            with self.subTest(role=role):
                authorization, resolution, _ = _valid_preclaim_material()

                def add_unknown_field(
                    bundle: dict[str, object],
                    *,
                    artifact_role: str = role,
                ) -> None:
                    document = _artifact_document(bundle, artifact_role)
                    document["unexpected_schema_field"] = True
                    _replace_artifact_document(
                        bundle,
                        artifact_role,
                        document,
                    )

                resolution = _reseal_resolution(
                    authorization,
                    resolution,
                    mutate_bundle=add_unknown_field,
                )
                result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
                    canonical_json_bytes(authorization),
                    _trust(authorization),
                )

                self.assertIsInstance(result, ApplyAdmissionRejection)
                assert isinstance(result, ApplyAdmissionRejection)
                self.assertEqual(
                    [diagnostic.code for diagnostic in result.diagnostics],
                    ["PREPARATION_ARTIFACT_SCHEMA_INVALID"],
                )

    def test_cross_substituted_observation_is_rejected_after_full_reseal(
        self,
    ) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def substitute_observation(bundle: dict[str, object]) -> None:
            capture_set = _artifact_document(
                bundle,
                "capture_observation_authority_set",
            )
            observations = capture_set["observations"]
            assert isinstance(observations, list)
            observation = observations[0]
            assert isinstance(observation, dict)
            observation["action_identity"] = "action:sha256:" + "f" * 64
            _bind_resealed_capture_set(bundle, capture_set)

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=substitute_observation,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)
        assert isinstance(result, ApplyAdmissionRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["PREPARATION_ARTIFACT_BINDING_INVALID"],
        )

    def test_coordinated_reseal_cannot_substitute_a_target_surface(self) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def substitute_surface(bundle: dict[str, object]) -> None:
            def mutate(action: dict[str, object]) -> None:
                targets = action["write_targets"]
                assert isinstance(targets, list)
                target = targets[0]
                assert isinstance(target, dict)
                target["write_surface_identity"] = "surface:foreign/preclaim-bypass"

            _bind_resealed_plan_mutation(bundle, mutate)

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=substitute_surface,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)

    def test_coordinated_reseal_cannot_substitute_a_dependency_surface(self) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def substitute_surface(bundle: dict[str, object]) -> None:
            def mutate(action: dict[str, object]) -> None:
                dependencies = action["verification_dependencies"]
                assert isinstance(dependencies, list)
                dependency = dependencies[0]
                assert isinstance(dependency, dict)
                dependency["write_surface_identity"] = (
                    "surface:foreign/dependency-bypass"
                )

            _bind_resealed_plan_mutation(bundle, mutate)

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=substitute_surface,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)

    def test_coordinated_reseal_cannot_reorder_write_targets(self) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def reorder_targets(bundle: dict[str, object]) -> None:
            def mutate(action: dict[str, object]) -> None:
                targets = action["write_targets"]
                assert isinstance(targets, list)
                targets.reverse()

            _bind_resealed_plan_mutation(bundle, mutate)

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=reorder_targets,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)

    def test_coordinated_reseal_cannot_substitute_a_target_locator(self) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def substitute_locator(bundle: dict[str, object]) -> None:
            def mutate(action: dict[str, object]) -> None:
                targets = action["write_targets"]
                assert isinstance(targets, list)
                target = targets[0]
                assert isinstance(target, dict)
                locator = target["locator"]
                assert isinstance(locator, dict)
                locator["path"] = "~/.claude/skills/foreign"
                identity_payload = {
                    "surface_kind": target["surface_kind"],
                    "locator": locator,
                    "equipment_identity": target["equipment_identity"],
                }
                target["target_identity"] = (
                    "target:" + canonical_json_sha256(identity_payload)
                )
                targets.sort(key=lambda item: item["target_identity"])

            _bind_resealed_plan_mutation(bundle, mutate)

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=substitute_locator,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)

    def test_coordinated_reseal_cannot_add_unrepresented_equipment(self) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def add_equipment(bundle: dict[str, object]) -> None:
            def mutate(action: dict[str, object]) -> None:
                equipment = action["equipment_identities"]
                assert isinstance(equipment, list)
                equipment.append("mcp:fixture/unrepresented")
                equipment.sort()

            _bind_resealed_plan_mutation(bundle, mutate)

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=add_equipment,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)

    def test_coordinated_reseal_cannot_add_an_unbound_mutable_surface(self) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def add_orphan_surface(bundle: dict[str, object]) -> None:
            captured_state = _artifact_document(bundle, "captured_state")
            surfaces = captured_state["surfaces"]
            assert isinstance(surfaces, list)
            orphan = copy.deepcopy(surfaces[0])
            assert isinstance(orphan, dict)
            orphan["surface_id"] = "surface:fixture/orphan-resealed"
            surfaces.append(orphan)
            _bind_resealed_captured_state(bundle, captured_state)

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=add_orphan_surface,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)

    def test_coordinated_reseal_cannot_open_the_captured_route_graph(self) -> None:
        def add_foreign_action(captured_state: dict[str, object]) -> None:
            references = captured_state["provider_routes"][0]["planned_actions"]
            foreign = copy.deepcopy(references[0])
            foreign["action_identity"] = "action:sha256:" + "f" * 64
            foreign["action_digest"] = "sha256:" + "f" * 64
            references.append(foreign)

        def hide_bound_slots(captured_state: dict[str, object]) -> None:
            references = captured_state["provider_routes"][0]["surface_references"]
            references["installation"] = {"status": "not_applicable"}
            references["skill_entries"] = []
            references["canonical_skill_dependencies"] = []

        def add_unowned_route(captured_state: dict[str, object]) -> None:
            route = copy.deepcopy(captured_state["provider_routes"][0])
            route["route_id"] = "route:fixture/unowned-resealed"
            route["planned_actions"] = []
            references = route["surface_references"]
            references["installation"] = {"status": "not_applicable"}
            references["enablement"] = {"status": "not_applicable"}
            references["projector"] = {"status": "not_applicable"}
            references["mcp_selections"] = []
            references["plugin_selections"] = []
            references["skill_entries"] = []
            references["canonical_skill_dependencies"] = []
            captured_state["provider_routes"].append(route)

        def add_unbound_canonical_dependency(
            captured_state: dict[str, object],
        ) -> None:
            canonical = next(
                surface
                for surface in captured_state["surfaces"]
                if surface["kind"] == "canonical_skill_entry"
            )
            extra = copy.deepcopy(canonical)
            extra["surface_id"] = "surface:fixture/unbound-canonical-resealed"
            extra["locator"]["path"] = "~/.agents/skills/unbound-canonical"
            captured_state["surfaces"].append(extra)
            captured_state["provider_routes"][0]["surface_references"][
                "canonical_skill_dependencies"
            ].append({"status": "captured", "surface_id": extra["surface_id"]})

        mutations = {
            "foreign action reference": add_foreign_action,
            "hidden bound slots": hide_bound_slots,
            "unowned reconciler route": add_unowned_route,
            "unbound canonical dependency": add_unbound_canonical_dependency,
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                authorization, resolution, _ = _valid_preclaim_material()

                def mutate_bundle(
                    bundle: dict[str, object],
                    mutate_capture: object = mutate,
                ) -> None:
                    assert callable(mutate_capture)
                    captured_state = _artifact_document(bundle, "captured_state")
                    mutate_capture(captured_state)
                    _bind_resealed_captured_state(bundle, captured_state)

                resolution = _reseal_resolution(
                    authorization,
                    resolution,
                    mutate_bundle=mutate_bundle,
                )
                result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
                    canonical_json_bytes(authorization),
                    _trust(authorization),
                )

                self.assertIsInstance(result, ApplyAdmissionRejection)

    def test_coordinated_reseal_cannot_admit_incoherent_capture_semantics(
        self,
    ) -> None:
        def present_installation(captured_state: dict[str, object]) -> None:
            installation = next(
                surface
                for surface in captured_state["surfaces"]
                if surface["kind"] == "plugin_installation"
            )
            installation["observation"] = {
                "installed": True,
                "channel": "foreign",
                "observed_version": "9.9.9",
                "observation_source": "foreign",
            }

        def invalid_absent_skill_recovery(
            captured_state: dict[str, object],
        ) -> None:
            skill = next(
                surface
                for surface in captured_state["surfaces"]
                if surface["kind"] == "claude_skill_entry"
            )
            skill["recovery"] = {"kind": "none", "reason": "verification_only"}

        for name, mutate in {
            "present native forward-install surface": present_installation,
            "absent Claude skill recovery": invalid_absent_skill_recovery,
        }.items():
            with self.subTest(name=name):
                authorization, resolution, _ = _valid_preclaim_material()

                def mutate_bundle(
                    bundle: dict[str, object],
                    mutate_capture: object = mutate,
                ) -> None:
                    assert callable(mutate_capture)
                    captured_state = _artifact_document(bundle, "captured_state")
                    mutate_capture(captured_state)
                    _bind_resealed_captured_state(bundle, captured_state)

                resolution = _reseal_resolution(
                    authorization,
                    resolution,
                    mutate_bundle=mutate_bundle,
                )
                result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
                    canonical_json_bytes(authorization),
                    _trust(authorization),
                )

                self.assertIsInstance(result, ApplyAdmissionRejection)

    def test_coordinated_reseal_cannot_add_an_unconsumed_secret_reference(
        self,
    ) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def add_unconsumed_reference(bundle: dict[str, object]) -> None:
            def mutate(action: dict[str, object]) -> None:
                action["secret_references"] = [
                    {"kind": "environment_variable", "name": "TOKEN"}
                ]

            _bind_resealed_plan_mutation(bundle, mutate)

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=add_unconsumed_reference,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)

    def test_coordinated_reseal_cannot_expand_operation_derived_desired_state(
        self,
    ) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def expand_desired_state(bundle: dict[str, object]) -> None:
            def mutate(action: dict[str, object]) -> None:
                desired = action["desired_state"]
                assert isinstance(desired, dict)
                desired["enablement"] = "enabled"

            _bind_resealed_plan_mutation(bundle, mutate)

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=expand_desired_state,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)

    def test_every_artifact_stream_is_rehashed_from_its_exact_bytes(self) -> None:
        for role in _ARTIFACT_ROLES:
            with self.subTest(role=role):
                authorization, resolution, _ = _valid_preclaim_material()

                def replace_exact_bytes(
                    bundle: dict[str, object],
                    *,
                    artifact_role: str = role,
                ) -> None:
                    artifacts = bundle["artifacts"]
                    assert isinstance(artifacts, dict)
                    member = artifacts[artifact_role]
                    assert isinstance(member, dict)
                    payload = bytearray(base64.b64decode(member["bytes_base64"]))
                    payload[-1] ^= 1
                    member["bytes_base64"] = base64.b64encode(payload).decode("ascii")

                resolution = _reseal_resolution(
                    authorization,
                    resolution,
                    mutate_bundle=replace_exact_bytes,
                )
                result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
                    canonical_json_bytes(authorization),
                    _trust(authorization),
                )

                self.assertIsInstance(result, ApplyAdmissionRejection)
                assert isinstance(result, ApplyAdmissionRejection)
                self.assertEqual(
                    [diagnostic.code for diagnostic in result.diagnostics],
                    ["PREPARATION_ARTIFACT_DIGEST_MISMATCH"],
                )

    def test_adapter_manifest_capability_substitution_is_rejected(self) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def substitute_capability(bundle: dict[str, object]) -> None:
            artifacts = bundle["artifacts"]
            bindings = bundle["bindings"]
            assert isinstance(artifacts, dict)
            assert isinstance(bindings, dict)
            member = artifacts["adapter_manifest_set"]
            assert isinstance(member, dict)
            manifest_set = json.loads(base64.b64decode(member["bytes_base64"]))
            assert isinstance(manifest_set, dict)
            manifests = manifest_set["manifests"]
            assert isinstance(manifests, list)
            manifest = manifests[0]
            assert isinstance(manifest, dict)
            capability_binding = manifest["capability_binding"]
            assert isinstance(capability_binding, dict)
            capability_binding["capability_identity"] = (
                "capability:fixture/substitution-v1"
            )
            identity_payload = copy.deepcopy(manifest)
            identity_payload.pop("adapter_manifest_identity")
            identity_payload.pop("adapter_manifest_digest")
            manifest["adapter_manifest_identity"] = (
                "preparation-adapter-manifest:"
                + canonical_json_sha256(identity_payload)
            )
            digest_payload = copy.deepcopy(manifest)
            digest_payload.pop("adapter_manifest_digest")
            manifest["adapter_manifest_digest"] = canonical_json_sha256(digest_payload)
            set_identity_payload = copy.deepcopy(manifest_set)
            set_identity_payload.pop("adapter_manifest_set_identity")
            set_identity_payload.pop("adapter_manifest_set_digest")
            manifest_set["adapter_manifest_set_identity"] = (
                "preparation-adapter-manifest-set:"
                + canonical_json_sha256(set_identity_payload)
            )
            set_digest_payload = copy.deepcopy(manifest_set)
            set_digest_payload.pop("adapter_manifest_set_digest")
            manifest_set["adapter_manifest_set_digest"] = canonical_json_sha256(
                set_digest_payload
            )
            payload = canonical_json_bytes(manifest_set)
            member["bytes_base64"] = base64.b64encode(payload).decode("ascii")
            member["bytes_digest"] = byte_sha256(payload)
            bindings["preparation_adapter_manifest_set_digest"] = manifest_set[
                "adapter_manifest_set_digest"
            ]

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=substitute_capability,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)
        assert isinstance(result, ApplyAdmissionRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["PREPARATION_ARTIFACT_BINDING_INVALID"],
        )

    def test_coordinated_reseal_cannot_replace_prepare_with_a_mutating_seam(
        self,
    ) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def substitute_seam(bundle: dict[str, object]) -> None:
            manifest_set = _artifact_document(bundle, "adapter_manifest_set")
            manifests = manifest_set["manifests"]
            assert isinstance(manifests, list)
            manifest = manifests[0]
            assert isinstance(manifest, dict)
            seam = manifest["prepare_seam"]
            assert isinstance(seam, dict)
            seam["entrypoint"] = "apply"
            _seal_adapter_manifest(manifest)
            _bind_resealed_adapter_set(bundle, manifest_set)

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=substitute_seam,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)
        assert isinstance(result, ApplyAdmissionRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["PREPARATION_ARTIFACT_SCHEMA_INVALID"],
        )

    def test_coordinated_reseal_cannot_add_an_unused_adapter_manifest(self) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def add_unused_manifest(bundle: dict[str, object]) -> None:
            manifest_set = _artifact_document(bundle, "adapter_manifest_set")
            manifests = manifest_set["manifests"]
            assert isinstance(manifests, list)
            unused = copy.deepcopy(manifests[0])
            assert isinstance(unused, dict)
            unused["adapter_identity"] = "adapter:fixture/unused-plugin"
            unused["adapter_version"] = "1.0.1"
            unused["adapter_implementation_identity"] = (
                "adapter-implementation:fixture/unused-plugin-v1"
            )
            unused["adapter_implementation_manifest_digest"] = _digest("b")
            _seal_adapter_manifest(unused)
            manifests.append(unused)
            _bind_resealed_adapter_set(bundle, manifest_set)

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=add_unused_manifest,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)
        assert isinstance(result, ApplyAdmissionRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["PREPARATION_ARTIFACT_BINDING_INVALID"],
        )

    def test_coordinated_reseal_cannot_reorder_gate_schema_inventory(self) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def reorder_schema_inventory(bundle: dict[str, object]) -> None:
            gate_manifest = _artifact_document(bundle, "gate_manifest")
            schema_digests = gate_manifest["schema_digests"]
            assert isinstance(schema_digests, list)
            schema_digests.reverse()
            _bind_resealed_gate_manifest(bundle, gate_manifest)

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=reorder_schema_inventory,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)
        assert isinstance(result, ApplyAdmissionRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["PREPARATION_ARTIFACT_BINDING_INVALID"],
        )

    def test_coordinated_reseal_cannot_duplicate_gate_file_inventory(self) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def duplicate_gate_file(bundle: dict[str, object]) -> None:
            gate_manifest = _artifact_document(bundle, "gate_manifest")
            files = gate_manifest["files"]
            assert isinstance(files, list)
            duplicate = copy.deepcopy(files[0])
            assert isinstance(duplicate, dict)
            duplicate["digest"] = _digest("b")
            files.append(duplicate)
            _bind_resealed_gate_manifest(bundle, gate_manifest)

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=duplicate_gate_file,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)
        assert isinstance(result, ApplyAdmissionRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["PREPARATION_ARTIFACT_BINDING_INVALID"],
        )

    def test_literal_secret_in_artifact_is_rejected_after_outer_reseal(
        self,
    ) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def inject_literal_secret(bundle: dict[str, object]) -> None:
            artifacts = bundle["artifacts"]
            bindings = bundle["bindings"]
            assert isinstance(artifacts, dict)
            assert isinstance(bindings, dict)
            member = artifacts["gate_manifest"]
            assert isinstance(member, dict)
            gate_manifest = json.loads(base64.b64decode(member["bytes_base64"]))
            assert isinstance(gate_manifest, dict)
            files = gate_manifest["files"]
            assert isinstance(files, list)
            file_record = files[0]
            assert isinstance(file_record, dict)
            file_record["path"] = "ghp_" + "A" * 24
            digest_payload = copy.deepcopy(gate_manifest)
            digest_payload.pop("manifest_digest")
            gate_manifest["manifest_digest"] = canonical_json_sha256(digest_payload)
            payload = canonical_json_bytes(gate_manifest)
            member["bytes_base64"] = base64.b64encode(payload).decode("ascii")
            member["bytes_digest"] = byte_sha256(payload)
            bindings["preparation_gate_manifest_digest"] = gate_manifest[
                "manifest_digest"
            ]

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=inject_literal_secret,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)
        assert isinstance(result, ApplyAdmissionRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["PREPARATION_ARTIFACT_LITERAL_SECRET"],
        )

    def test_closed_preparation_schema_rejects_boolean_store_generation(self) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def use_boolean_generation(bundle: dict[str, object]) -> None:
            bindings = bundle["bindings"]
            assert isinstance(bindings, dict)
            bindings["store_generation"] = True

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=use_boolean_generation,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)
        assert isinstance(result, ApplyAdmissionRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["PREPARATION_EVIDENCE_SCHEMA_INVALID"],
        )

    def test_coordinated_reseal_cannot_change_the_v1_store_generation(self) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def advance_store_generation(bundle: dict[str, object]) -> None:
            bindings = bundle["bindings"]
            assert isinstance(bindings, dict)
            bindings["store_generation"] = 2

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=advance_store_generation,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)
        assert isinstance(result, ApplyAdmissionRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["PREPARATION_EVIDENCE_SCHEMA_INVALID"],
        )

    def test_oversized_authorization_is_rejected_without_resolution_or_cas(
        self,
    ) -> None:
        resolver = _RecordingResolver()
        gate = ApplyPreclaimGate(resolver)

        result = gate.admit(
            b"x" * (MAX_APPLY_AUTHORIZATION_BYTES + 1),
            _trust(),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)
        assert isinstance(result, ApplyAdmissionRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["EXECUTION_AUTHORITY_BYTES_INVALID"],
        )
        self.assertEqual(resolver.requests, [])

    def test_ambiguous_authorization_is_rejected_without_resolution(self) -> None:
        resolver = _RecordingResolver()
        gate = ApplyPreclaimGate(resolver)

        result = gate.admit(b'{"bindings":{},"bindings":{}}', _trust())

        self.assertIsInstance(result, ApplyAdmissionRejection)
        assert isinstance(result, ApplyAdmissionRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["EXECUTION_AUTHORITY_JSON_INVALID"],
        )
        self.assertEqual(resolver.requests, [])

    def test_noncanonical_authorization_is_rejected_without_resolution(self) -> None:
        authorization, resolution, _ = _valid_preclaim_material()
        resolver = _RecordingResolver(resolution)

        result = ApplyPreclaimGate(resolver).admit(
            json.dumps(authorization, indent=2, sort_keys=True).encode("utf-8"),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)
        assert isinstance(result, ApplyAdmissionRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["EXECUTION_AUTHORITY_JSON_INVALID"],
        )
        self.assertEqual(resolver.requests, [])

    def test_coordinated_noncanonical_receipt_and_bundle_are_rejected(self) -> None:
        authorization, resolution, _ = _valid_preclaim_material()
        bundle = json.loads(resolution.bundle_bytes)
        bundle_bytes = json.dumps(bundle, indent=2, sort_keys=True).encode("utf-8")
        receipt = json.loads(resolution.receipt_bytes)
        payload = receipt["payload"]
        assert isinstance(payload, dict)
        payload["preparation_bundle_bytes_digest"] = byte_sha256(bundle_bytes)
        receipt["receipt_identity"] = "preparation-receipt:" + canonical_json_sha256(
            payload
        )
        noncanonical = ResolvedPreparationBundle(
            receipt_bytes=json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8"),
            bundle_bytes=bundle_bytes,
        )

        result = ApplyPreclaimGate(_RecordingResolver(noncanonical)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)
        assert isinstance(result, ApplyAdmissionRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["PREPARATION_EVIDENCE_JSON_INVALID"],
        )

    def test_noncanonical_artifact_stream_is_rejected_after_outer_reseal(
        self,
    ) -> None:
        authorization, resolution, _ = _valid_preclaim_material()

        def make_plan_noncanonical(bundle: dict[str, object]) -> None:
            artifacts = bundle["artifacts"]
            assert isinstance(artifacts, dict)
            member = artifacts["plan_action_set"]
            assert isinstance(member, dict)
            document = json.loads(base64.b64decode(member["bytes_base64"]))
            payload = json.dumps(document, indent=2, sort_keys=True).encode("utf-8")
            member["bytes_base64"] = base64.b64encode(payload).decode("ascii")
            member["bytes_digest"] = byte_sha256(payload)

        resolution = _reseal_resolution(
            authorization,
            resolution,
            mutate_bundle=make_plan_noncanonical,
        )
        result = ApplyPreclaimGate(_RecordingResolver(resolution)).admit(
            canonical_json_bytes(authorization),
            _trust(authorization),
        )

        self.assertIsInstance(result, ApplyAdmissionRejection)
        assert isinstance(result, ApplyAdmissionRejection)
        self.assertEqual(
            [diagnostic.code for diagnostic in result.diagnostics],
            ["PREPARATION_ARTIFACT_JSON_INVALID"],
        )


if __name__ == "__main__":
    unittest.main()
