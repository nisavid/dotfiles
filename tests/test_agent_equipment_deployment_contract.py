from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "docs/agent-equipment/execution-authority-v1.schema.json"
SPEC = importlib.util.spec_from_file_location(
    "agent_equipment_json_schema_deployment_contract",
    ROOT / "scripts/agent_equipment_json_schema.py",
)
assert SPEC is not None and SPEC.loader is not None
SCHEMA = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCHEMA
SPEC.loader.exec_module(SCHEMA)

AUTHORITY_SPEC = importlib.util.spec_from_file_location(
    "agent_equipment_execution_authority_test",
    ROOT / "scripts/agent_equipment_execution_authority.py",
)
assert AUTHORITY_SPEC is not None and AUTHORITY_SPEC.loader is not None
EXECUTION_AUTHORITY = importlib.util.module_from_spec(AUTHORITY_SPEC)
sys.modules[AUTHORITY_SPEC.name] = EXECUTION_AUTHORITY
AUTHORITY_SPEC.loader.exec_module(EXECUTION_AUTHORITY)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64
PLAN_ACTION_FIXTURE_PATH = (
    ROOT / "tests/fixtures/agent-equipment/schema/valid-plan-action-set.json"
)
CAPTURED_STATE_FIXTURE_PATH = (
    ROOT / "tests/fixtures/agent-equipment/schema/valid-captured-state.json"
)


def canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def byte_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def valid_apply_authorization() -> dict[str, object]:
    plan_action_set = valid_plan_action_set()
    prepared_authorities = valid_prepared_action_authority_set(plan_action_set)
    captured_state = valid_captured_state(plan_action_set)
    capture_observation_authorities = valid_capture_observation_authority_set(
        plan_action_set,
        captured_state,
    )
    first_action = plan_action_set["actions"][0]["action_payload"]
    return {
        "schema_version": "agent-equipment-apply-authorization/v1",
        "authorization_identity": "apply-authorization:sha256:" + "1" * 64,
        "issuer_identity": "authority:fixture/operator",
        "issued_at": "2026-08-13T07:00:00Z",
        "not_before": "2026-08-13T07:00:00Z",
        "expires_at": "2026-08-13T08:00:00Z",
        "execution_nonce": "execution-nonce:sha256:" + "2" * 64,
        "run_identity": "run:sha256:" + "3" * 64,
        "execution_domain_identity": "execution-domain:fixture/global-ledger-v1",
        "command": "apply",
        "bindings": {
            "candidate_identity": "candidate:fixture/controller-v1",
            "implementation_manifest_digest": DIGEST_A,
            "catalog_digest": first_action["catalog_digest"],
            "lock_digest": first_action["lock_digest"],
            "plan_digest": plan_action_set["plan_digest"],
            "plan_action_set_digest": plan_action_set["action_set_digest"],
            "prepared_action_authority_set_identity": prepared_authorities[
                "authority_set_identity"
            ],
            "prepared_action_authority_set_digest": prepared_authorities[
                "authority_set_digest"
            ],
            "capability_set_digest": captured_state["bindings"][
                "capability_set_digest"
            ],
            "captured_state_identity": "capture:fixture/run-v1",
            "captured_state_digest": canonical_digest(captured_state),
            "capture_observation_authority_set_identity": (
                capture_observation_authorities["authority_set_identity"]
            ),
            "capture_observation_authority_set_digest": (
                capture_observation_authorities["authority_set_digest"]
            ),
            "expected_case_manifest_digest": DIGEST_B,
            "operator_review_package_digest": DIGEST_C,
        },
    }


def seal_apply_authorization(document: dict[str, object]) -> str:
    payload = copy.deepcopy(document)
    payload.pop("authorization_identity", None)
    document["authorization_identity"] = "apply-authorization:" + canonical_digest(
        payload
    )
    return canonical_digest(document)


def execution_binding(
    authorization: dict[str, object], authorization_digest: str
) -> dict[str, object]:
    return {
        "apply_authorization_identity": authorization["authorization_identity"],
        "apply_authorization_digest": authorization_digest,
        "execution_domain_identity": authorization["execution_domain_identity"],
        "execution_nonce": authorization["execution_nonce"],
        "run_identity": authorization["run_identity"],
    }


def valid_plan_action_set(action_count: int = 2) -> dict[str, object]:
    document = json.loads(PLAN_ACTION_FIXTURE_PATH.read_text(encoding="utf-8"))
    first = document["actions"][0]
    first["action_payload"]["expected_post_state_digest"] = canonical_digest(
        normalized_state(present=True)
    )
    first["action_digest"] = EXECUTION_AUTHORITY._plan_action_digest(
        first["action_payload"]
    )
    actions = [first]
    for ordinal in range(1, action_count):
        evidence = copy.deepcopy(first)
        payload = evidence["action_payload"]
        suffix = f"route-{ordinal}"
        payload["ordinal"] = ordinal
        payload["route_identity"] = f"route:fixture/claude-plugin-{suffix}"
        payload["route_digest"] = "sha256:" + format(ordinal, "064x")
        payload["provider"]["plugin_id"] = f"example-{suffix}@fixture"
        payload["equipment_identities"] = sorted(
            [f"plugin:fixture/example-{suffix}", f"skill:fixture/example-{suffix}"]
        )
        payload["activation_group"] = f"activation:fixture/claude-plugin-{suffix}"
        plugin_surface = (
            f"surface:route:fixture/claude-plugin-{suffix}/"
            f"plugin:fixture/example-{suffix}"
        )
        skill_surface = (
            f"surface:route:fixture/claude-plugin-{suffix}/"
            f"skill:fixture/example-{suffix}"
        )
        payload["surface_scope"] = sorted([plugin_surface, skill_surface])
        for target in payload["write_targets"]:
            if target["surface_kind"] == "plugin_installation":
                target["write_surface_identity"] = plugin_surface
                target["locator"]["native_identity"] = f"example-{suffix}@fixture"
            else:
                target["write_surface_identity"] = skill_surface
                target["equipment_identity"] = f"skill:fixture/example-{suffix}"
                target["locator"]["path"] = f"~/.claude/skills/example-{suffix}"
            target["target_identity"] = "target:" + canonical_digest(
                {
                    key: value
                    for key, value in target.items()
                    if key != "target_identity"
                }
            )
        payload["write_targets"].sort(key=lambda target: target["target_identity"])
        payload["preconditions"]["route_digest"] = payload["route_digest"]
        payload["preconditions"]["activation_group"] = payload["activation_group"]
        payload["preconditions"]["surface_scope"] = copy.deepcopy(
            payload["surface_scope"]
        )
        dependency = payload["verification_dependencies"][0]
        dependency["dependency_identity"] = (
            f"dependency:fixture/canonical-skill-{suffix}"
        )
        dependency["write_surface_identity"] = skill_surface
        dependency["equipment_identity"] = f"skill:fixture/example-{suffix}"
        dependency["target_locator"]["path"] = f"~/.agents/skills/example-{suffix}"
        payload["action_identity"] = EXECUTION_AUTHORITY._plan_action_identity(payload)
        evidence["action_digest"] = EXECUTION_AUTHORITY._plan_action_digest(payload)
        actions.append(evidence)
    document["actions"] = actions
    document["action_set_digest"] = EXECUTION_AUTHORITY._plan_action_set_digest(
        document["candidate_identity"],
        document["implementation_manifest_digest"],
        document["plan_digest"],
        actions,
    )
    return document


def valid_captured_state(
    plan_action_set: dict[str, object] | None = None,
) -> dict[str, object]:
    plan_action_set = plan_action_set or valid_plan_action_set()
    document = json.loads(CAPTURED_STATE_FIXTURE_PATH.read_text(encoding="utf-8"))
    document["provider_routes"][0]["planned_actions"][0]["action_digest"] = (
        plan_action_set["actions"][0]["action_digest"]
    )
    document["surfaces"][0]["recovery"]["expected_pre_state_digest"] = plan_action_set[
        "actions"
    ][0]["action_payload"]["expected_post_state_digest"]
    for evidence in plan_action_set["actions"][1:]:
        action = evidence["action_payload"]
        suffix = f"route-{action['ordinal']}"
        route = copy.deepcopy(document["provider_routes"][0])
        route["route_id"] = action["route_identity"]
        route["route_digest"] = action["route_digest"]
        route["equipment_identities"] = copy.deepcopy(action["equipment_identities"])
        route["provenance_owner"] = f"source:fixture/marketplace-{suffix}"
        reference = route["planned_actions"][0]
        reference["action_identity"] = action["action_identity"]
        reference["action_digest"] = evidence["action_digest"]
        installation_id = f"surface:fixture/{suffix}-installation"
        skill_id = f"surface:fixture/{suffix}-claude-skill"
        canonical_id = f"surface:fixture/{suffix}-canonical-skill"
        surface_ids = {
            "plugin_installation": installation_id,
            "claude_skill_entry": skill_id,
        }
        reference["write_bindings"] = sorted(
            [
                {
                    "target_identity": target["target_identity"],
                    "surface_id": surface_ids[target["surface_kind"]],
                }
                for target in action["write_targets"]
            ],
            key=lambda binding: binding["target_identity"],
        )
        dependency = action["verification_dependencies"][0]
        reference["verification_dependency_bindings"] = [
            {
                "dependency_identity": dependency["dependency_identity"],
                "surface_id": canonical_id,
            }
        ]
        route["surface_references"]["installation"]["surface_id"] = installation_id
        route["surface_references"]["skill_entries"][0]["surface_id"] = skill_id
        route["surface_references"]["canonical_skill_dependencies"][0]["surface_id"] = (
            canonical_id
        )
        route["restore_evidence"]["channel"] = f"channel-{suffix}"
        route["restore_evidence"]["observation_source"] = f"source-{suffix}"
        document["provider_routes"].append(route)
        for index, original_surface in enumerate(document["surfaces"][:3]):
            surface = copy.deepcopy(original_surface)
            surface["surface_id"] = [installation_id, canonical_id, skill_id][index]
            surface["route_id"] = action["route_identity"]
            if index == 0:
                surface["locator"]["native_identity"] = f"example-{suffix}@fixture"
                surface["provenance"]["evidence"][0]["source"] = f"source-{suffix}"
                surface["recovery"]["expected_pre_state_digest"] = action[
                    "expected_post_state_digest"
                ]
            else:
                surface["equipment_identity"] = f"skill:fixture/example-{suffix}"
                root = "agents" if index == 1 else "claude"
                surface["locator"]["path"] = f"~/.{root}/skills/example-{suffix}"
            document["surfaces"].append(surface)
    document["bindings"]["plan_action_set_digest"] = plan_action_set[
        "action_set_digest"
    ]
    return document


def normalized_state(*, present: bool) -> dict[str, object]:
    return {
        "route_presence": "present" if present else "absent",
        "enablement": "enabled" if present else "disabled",
        "configuration": {"status": "not_applicable"},
        "component_states": [],
        "observed_version": {"status": "route_absent"},
        "native_update_control": "not_applicable",
        "native_update_suppression_state": "not_applicable",
        "manager_drift": {
            "status": "not_applicable",
            "reviewed_baseline": None,
            "observation_source": None,
        },
    }


def seal_prepared_action_authority_set(document: dict[str, object]) -> str:
    identity_payload = copy.deepcopy(document)
    identity_payload.pop("authority_set_identity", None)
    identity_payload.pop("authority_set_digest", None)
    document["authority_set_identity"] = (
        "prepared-action-authority-set:" + canonical_digest(identity_payload)
    )
    digest_payload = copy.deepcopy(document)
    digest_payload.pop("authority_set_digest", None)
    document["authority_set_digest"] = canonical_digest(digest_payload)
    return document["authority_set_digest"]


def seal_prepared_action_authority(authority: dict[str, object]) -> str:
    payload = copy.deepcopy(authority)
    payload.pop("authority_digest", None)
    authority["authority_digest"] = canonical_digest(payload)
    return authority["authority_digest"]


def valid_prepared_action_authority_set(
    plan_action_set: dict[str, object] | None = None,
) -> dict[str, object]:
    plan_action_set = plan_action_set or valid_plan_action_set()
    capture = valid_captured_state(plan_action_set)
    authorities = []
    for evidence in plan_action_set["actions"]:
        action = evidence["action_payload"]
        pre_state = normalized_state(present=False)
        post_state = normalized_state(present=True)
        authority = {
            "action_identity": action["action_identity"],
            "ordinal": action["ordinal"],
            "candidate_identity": action["candidate_identity"],
            "implementation_manifest_digest": action["implementation_manifest_digest"],
            "catalog_digest": action["catalog_digest"],
            "lock_digest": action["lock_digest"],
            "plan_digest": action["plan_digest"],
            "capability_set_digest": capture["bindings"]["capability_set_digest"],
            "route_capability_binding": {
                "capability_identity": action["capability_identity"],
                "capability_digest": action["capability_digest"],
                "manager_version_evidence_digest": action[
                    "manager_version_evidence_digest"
                ],
            },
            "route_digest": action["route_digest"],
            "operation_digest": canonical_digest(action["operation"]),
            "compensation_operation": "restore_captured_pre_state",
            "surface": copy.deepcopy(action["surface_scope"]),
            "captured_state_identity": "capture:fixture/run-v1",
            "captured_state_digest": canonical_digest(capture),
            "captured_pre_state": pre_state,
            "captured_pre_state_digest": canonical_digest(pre_state),
            "expected_post_state": post_state,
            "expected_post_state_digest": canonical_digest(post_state),
            "authority_digest": "",
        }
        seal_prepared_action_authority(authority)
        authorities.append(authority)
    document = {
        "schema_version": "agent-equipment-prepared-action-authority-set/v1",
        "authority_set_identity": "prepared-action-authority-set:sha256:" + "0" * 64,
        "authorities": authorities,
        "authority_set_digest": DIGEST_A,
    }
    seal_prepared_action_authority_set(document)
    return document


def valid_capture_observations(
    plan_action_set: dict[str, object] | None = None,
    captured_state: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    plan_action_set = plan_action_set or valid_plan_action_set()
    captured_state = captured_state or valid_captured_state(plan_action_set)
    captured_state_digest = canonical_digest(captured_state)
    observations = []
    for evidence in plan_action_set["actions"]:
        action = evidence["action_payload"]
        pre_state = normalized_state(present=False)
        observations.append(
            {
                "action_identity": action["action_identity"],
                "ordinal": action["ordinal"],
                "captured_state_identity": "capture:fixture/run-v1",
                "captured_state_digest": captured_state_digest,
                "surface": copy.deepcopy(action["surface_scope"]),
                "controlled_equipment_identities": copy.deepcopy(
                    action["controlled_equipment_identities"]
                ),
                "normalized_pre_state": pre_state,
                "normalized_pre_state_digest": canonical_digest(pre_state),
            }
        )
    return observations


def valid_capture_observation_authority_set(
    plan_action_set: dict[str, object] | None = None,
    captured_state: dict[str, object] | None = None,
) -> dict[str, object]:
    plan_action_set = plan_action_set or valid_plan_action_set()
    captured_state = captured_state or valid_captured_state(plan_action_set)
    document: dict[str, object] = {
        "schema_version": "agent-equipment-capture-observation-authority-set/v1",
        "authority_set_identity": (
            "capture-observation-authority-set:sha256:" + "0" * 64
        ),
        "bindings": {
            "candidate_identity": plan_action_set["candidate_identity"],
            "implementation_manifest_digest": plan_action_set[
                "implementation_manifest_digest"
            ],
            "plan_digest": plan_action_set["plan_digest"],
            "plan_action_set_digest": plan_action_set["action_set_digest"],
            "capability_set_digest": captured_state["bindings"][
                "capability_set_digest"
            ],
            "captured_state_identity": "capture:fixture/run-v1",
            "captured_state_digest": canonical_digest(captured_state),
        },
        "observations": valid_capture_observations(
            plan_action_set,
            captured_state,
        ),
        "authority_set_digest": DIGEST_A,
    }
    seal_capture_observation_authority_set(document)
    return document


def seal_capture_observation_authority_set(document: dict[str, object]) -> None:
    identity_payload = copy.deepcopy(document)
    identity_payload.pop("authority_set_identity", None)
    identity_payload.pop("authority_set_digest", None)
    document["authority_set_identity"] = (
        "capture-observation-authority-set:" + canonical_digest(identity_payload)
    )
    digest_payload = copy.deepcopy(document)
    digest_payload.pop("authority_set_digest", None)
    document["authority_set_digest"] = canonical_digest(digest_payload)


def valid_checkpoint_record(
    ordinal: int = 0,
    plan_action_set: dict[str, object] | None = None,
) -> dict[str, object]:
    authorization = valid_apply_authorization()
    authorization_digest = seal_apply_authorization(authorization)
    plan_action_set = plan_action_set or valid_plan_action_set()
    evidence = plan_action_set["actions"][ordinal]
    payload = evidence["action_payload"]
    prepared_authority = valid_prepared_action_authority_set(plan_action_set)[
        "authorities"
    ][ordinal]
    assert isinstance(payload, dict)
    record = {
        "checkpoint_identity": "checkpoint:sha256:" + "0" * 64,
        "apply_authorization_identity": authorization["authorization_identity"],
        "apply_authorization_digest": authorization_digest,
        "execution_nonce": authorization["execution_nonce"],
        "step_id": f"step-{ordinal:03d}",
        "action_identity": payload["action_identity"],
        "ordinal": ordinal,
        "run_identity": authorization["run_identity"],
        "execution_domain_identity": authorization["execution_domain_identity"],
        "phase": "completed",
        "phase_history": ["prepared", "completed"],
        "invocation_state": "started",
        "compensation_authority_kind": "none",
        "candidate_digest": plan_action_set["candidate_identity"],
        "implementation_manifest_digest": plan_action_set[
            "implementation_manifest_digest"
        ],
        "catalog_digest": payload["catalog_digest"],
        "lock_digest": payload["lock_digest"],
        "plan_digest": plan_action_set["plan_digest"],
        "capability_set_digest": authorization["bindings"]["capability_set_digest"],
        "captured_state_identity": authorization["bindings"]["captured_state_identity"],
        "captured_state_digest": authorization["bindings"]["captured_state_digest"],
        "route_capability_binding": {
            "capability_identity": payload["capability_identity"],
            "capability_digest": payload["capability_digest"],
            "manager_version_evidence_digest": payload[
                "manager_version_evidence_digest"
            ],
        },
        "route_digest": payload["route_digest"],
        "operation_digest": canonical_digest(payload["operation"]),
        "compensation_operation": "restore_captured_pre_state",
        "pre_state_digest": prepared_authority["captured_pre_state_digest"],
        "expected_post_state_digest": payload["expected_post_state_digest"],
        "pre_state": copy.deepcopy(prepared_authority["captured_pre_state"]),
        "expected_post_state": copy.deepcopy(prepared_authority["expected_post_state"]),
        "surface": payload["surface_scope"],
        "compensation_transition_claim": None,
    }
    record["checkpoint_identity"] = EXECUTION_AUTHORITY.checkpoint_identity(
        "agent-equipment-checkpoint/v1", record
    )
    return record


def checkpoint_snapshot(
    record: dict[str, object], durable_generation: int
) -> dict[str, object]:
    return {
        "durable_generation": durable_generation,
        "record_version": "agent-equipment-checkpoint/v1",
        "record": copy.deepcopy(record),
    }


def checkpoint_manifest_entry(snapshot: dict[str, object]) -> dict[str, object]:
    record = snapshot["record"]
    assert isinstance(record, dict)
    return {
        "checkpoint_identity": record["checkpoint_identity"],
        "durable_generation": snapshot["durable_generation"],
        "record_version": snapshot["record_version"],
        "phase": record["phase"],
        "invocation_state": record["invocation_state"],
        "compensation_authority_kind": record["compensation_authority_kind"],
        "action_identity": record["action_identity"],
        "ordinal": record["ordinal"],
        "compensation_transition_claim_identity": (
            record["compensation_transition_claim"]["transition_claim_identity"]
            if isinstance(record["compensation_transition_claim"], dict)
            else None
        ),
        "checkpoint_record_digest": canonical_digest(record),
    }


def checkpoint_authority_inputs(
    plan_action_set: dict[str, object] | None = None,
) -> dict[str, object]:
    plan_action_set = plan_action_set or valid_plan_action_set()
    apply_authorization = valid_apply_authorization()
    apply_bindings = apply_authorization["bindings"]
    assert isinstance(apply_bindings, dict)
    capture = valid_captured_state(plan_action_set)
    capture_observation_authorities = valid_capture_observation_authority_set(
        plan_action_set,
        capture,
    )
    prepared = valid_prepared_action_authority_set(plan_action_set)
    return {
        "authoritative_captured_state": capture,
        "expected_captured_state_identity": "capture:fixture/run-v1",
        "expected_captured_state_digest": canonical_digest(capture),
        "capture_observation_authority_set": capture_observation_authorities,
        "expected_capture_observation_authority_set_identity": (
            apply_bindings["capture_observation_authority_set_identity"]
        ),
        "expected_capture_observation_authority_set_digest": (
            apply_bindings["capture_observation_authority_set_digest"]
        ),
        "prepared_action_authority_set": prepared,
        "expected_prepared_action_authority_set_identity": prepared[
            "authority_set_identity"
        ],
        "expected_prepared_action_authority_set_digest": prepared[
            "authority_set_digest"
        ],
    }


def prepared_validation_inputs(
    plan_action_set: dict[str, object] | None = None,
    captured_state: dict[str, object] | None = None,
    prepared_action_authority_set: dict[str, object] | None = None,
) -> dict[str, object]:
    plan_action_set = plan_action_set or valid_plan_action_set()
    captured_state = captured_state or valid_captured_state(plan_action_set)
    prepared_action_authority_set = (
        prepared_action_authority_set
        or valid_prepared_action_authority_set(plan_action_set)
    )
    capture_observation_authorities = valid_capture_observation_authority_set(
        plan_action_set,
        captured_state,
    )
    return {
        "authoritative_captured_state": captured_state,
        "expected_captured_state_identity": "capture:fixture/run-v1",
        "expected_captured_state_digest": canonical_digest(captured_state),
        "capture_observation_authority_set": capture_observation_authorities,
        "expected_capture_observation_authority_set_identity": (
            capture_observation_authorities["authority_set_identity"]
        ),
        "expected_capture_observation_authority_set_digest": (
            capture_observation_authorities["authority_set_digest"]
        ),
        "authoritative_plan_action_set": plan_action_set,
        "expected_plan_action_set_digest": plan_action_set["action_set_digest"],
        "expected_candidate_identity": plan_action_set["candidate_identity"],
        "expected_implementation_manifest_digest": plan_action_set[
            "implementation_manifest_digest"
        ],
        "expected_plan_digest": plan_action_set["plan_digest"],
        "expected_prepared_action_authority_set_identity": (
            prepared_action_authority_set["authority_set_identity"]
        ),
        "expected_prepared_action_authority_set_digest": (
            prepared_action_authority_set["authority_set_digest"]
        ),
    }


def trusted_plan_action(record: dict[str, object]) -> dict[str, object]:
    return {
        field: record[field]
        for field in (
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
    }


def seal_checkpoint_set_manifest(document: dict[str, object]) -> str:
    identity_payload = copy.deepcopy(document)
    identity_payload.pop("checkpoint_set_identity", None)
    identity_payload.pop("checkpoint_set_digest", None)
    document["checkpoint_set_identity"] = "checkpoint-set:" + canonical_digest(
        identity_payload
    )
    digest_payload = copy.deepcopy(document)
    digest_payload.pop("checkpoint_set_digest", None)
    document["checkpoint_set_digest"] = canonical_digest(digest_payload)
    return document["checkpoint_set_digest"]


def valid_checkpoint_snapshots() -> list[dict[str, object]]:
    plan_action_set = valid_plan_action_set()
    return [
        checkpoint_snapshot(valid_checkpoint_record(0, plan_action_set), 1),
        checkpoint_snapshot(valid_checkpoint_record(1, plan_action_set), 2),
    ]


def valid_checkpoint_set_manifest(
    snapshots: list[dict[str, object]] | None = None,
    *,
    store_generation: int = 7,
) -> dict[str, object]:
    authorization = valid_apply_authorization()
    authorization_digest = seal_apply_authorization(authorization)
    document: dict[str, object] = {
        "schema_version": "agent-equipment-checkpoint-set/v1",
        "checkpoint_set_identity": "checkpoint-set:sha256:" + "4" * 64,
        "checkpoint_store_generation": store_generation,
        "bindings": {
            "apply_authorization_identity": authorization["authorization_identity"],
            "apply_authorization_digest": authorization_digest,
            "execution_domain_identity": authorization["execution_domain_identity"],
            "execution_nonce": authorization["execution_nonce"],
            "run_identity": authorization["run_identity"],
            "plan_action_set_digest": authorization["bindings"][
                "plan_action_set_digest"
            ],
        },
        "checkpoints": [
            checkpoint_manifest_entry(snapshot)
            for snapshot in (
                snapshots if snapshots is not None else valid_checkpoint_snapshots()
            )
        ],
        "checkpoint_set_digest": DIGEST_D,
    }
    seal_checkpoint_set_manifest(document)
    return document


def apply_validation_inputs(
    authorization: dict[str, object],
    *,
    trusted_now: datetime | None = None,
) -> dict[str, object]:
    bindings = authorization["bindings"]
    assert isinstance(bindings, dict)
    return {
        "expected_candidate_identity": bindings["candidate_identity"],
        "expected_implementation_manifest_digest": bindings[
            "implementation_manifest_digest"
        ],
        "expected_apply_authorization_identity": authorization[
            "authorization_identity"
        ],
        "expected_apply_authorization_digest": canonical_digest(authorization),
        "expected_execution_domain_identity": authorization[
            "execution_domain_identity"
        ],
        "expected_execution_nonce": authorization["execution_nonce"],
        "expected_run_identity": authorization["run_identity"],
        "expected_operator_review_package_digest": bindings[
            "operator_review_package_digest"
        ],
        "expected_issuer_identity": authorization["issuer_identity"],
        "trusted_now": trusted_now or datetime(2026, 8, 13, 7, 30, tzinfo=timezone.utc),
        "expected_bindings": copy.deepcopy(bindings),
    }


def valid_compensation_authorization(
    checkpoint_set: dict[str, object] | None = None,
) -> dict[str, object]:
    apply_authorization = valid_apply_authorization()
    apply_authorization_digest = seal_apply_authorization(apply_authorization)
    checkpoint_set = checkpoint_set or valid_checkpoint_set_manifest()
    document: dict[str, object] = {
        "schema_version": "agent-equipment-compensation-authorization/v1",
        "compensation_authorization_identity": (
            "compensation-authorization:sha256:" + "8" * 64
        ),
        "issuer_identity": "authority:fixture/operator",
        "issued_at": "2026-08-13T09:00:00Z",
        "not_before": "2026-08-13T09:00:00Z",
        "expires_at": "2026-08-13T10:00:00Z",
        "compensation_nonce": "compensation-nonce:sha256:" + "9" * 64,
        "command": "compensate",
        "bindings": {
            "apply_authorization_identity": apply_authorization[
                "authorization_identity"
            ],
            "apply_authorization_digest": apply_authorization_digest,
            "execution_domain_identity": apply_authorization[
                "execution_domain_identity"
            ],
            "execution_nonce": apply_authorization["execution_nonce"],
            "run_identity": apply_authorization["run_identity"],
            "checkpoint_set_digest": checkpoint_set["checkpoint_set_digest"],
            "plan_action_set_digest": apply_authorization["bindings"][
                "plan_action_set_digest"
            ],
        },
    }
    seal_compensation_authorization(document)
    return document


def seal_compensation_authorization(document: dict[str, object]) -> str:
    payload = copy.deepcopy(document)
    payload.pop("compensation_authorization_identity", None)
    document["compensation_authorization_identity"] = (
        "compensation-authorization:" + canonical_digest(payload)
    )
    return canonical_digest(document)


def attach_public_compensation_claim(
    record: dict[str, object], authorization: dict[str, object]
) -> None:
    claim: dict[str, object] = {
        "schema_version": "agent-equipment-compensation-transition-claim/v1",
        "checkpoint_identity": record["checkpoint_identity"],
        "compensation_authorization_identity": authorization[
            "compensation_authorization_identity"
        ],
        "compensation_authorization_digest": canonical_digest(authorization),
        "compensation_nonce": authorization["compensation_nonce"],
        "transition_claim_identity": "",
        "transition_claim_digest": "",
    }
    claim["transition_claim_identity"] = (
        EXECUTION_AUTHORITY._compensation_transition_claim_identity(claim)
    )
    claim["transition_claim_digest"] = (
        EXECUTION_AUTHORITY._compensation_transition_claim_digest(claim)
    )
    record["compensation_authority_kind"] = "public_compensation"
    record["compensation_transition_claim"] = claim


def transition_public_checkpoint(
    record: dict[str, object],
    authorization: dict[str, object],
    phase: str,
) -> None:
    history = list(record["phase_history"])
    if phase == "compensated":
        history.extend(["compensating", "compensated"])
    else:
        history.append(phase)
    record["phase"] = phase
    record["phase_history"] = history
    attach_public_compensation_claim(record, authorization)


def compensation_validation_inputs(
    authorization: dict[str, object],
    checkpoint_set: dict[str, object] | None = None,
    checkpoint_snapshots: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    bindings = authorization["bindings"]
    assert isinstance(bindings, dict)
    checkpoint_set = checkpoint_set or valid_checkpoint_set_manifest()
    checkpoint_snapshots = copy.deepcopy(
        checkpoint_snapshots or valid_checkpoint_snapshots()
    )
    first_snapshot = checkpoint_snapshots[0]
    first_checkpoint = first_snapshot["record"]
    assert isinstance(first_checkpoint, dict)
    return {
        "expected_compensation_authorization_identity": authorization[
            "compensation_authorization_identity"
        ],
        "expected_compensation_authorization_digest": canonical_digest(authorization),
        "expected_apply_authorization_identity": bindings[
            "apply_authorization_identity"
        ],
        "expected_apply_authorization_digest": bindings["apply_authorization_digest"],
        "expected_execution_domain_identity": bindings["execution_domain_identity"],
        "expected_execution_nonce": bindings["execution_nonce"],
        "expected_run_identity": bindings["run_identity"],
        "checkpoint_set_manifest": checkpoint_set,
        "trusted_checkpoint_store_generation": checkpoint_set[
            "checkpoint_store_generation"
        ],
        "trusted_checkpoint_records": checkpoint_snapshots,
        "pretransition_checkpoint_store_generation": checkpoint_set[
            "checkpoint_store_generation"
        ],
        "pretransition_checkpoint_records": copy.deepcopy(checkpoint_snapshots),
        **checkpoint_authority_inputs(),
        "authoritative_plan_action_set": valid_plan_action_set(),
        "expected_candidate_identity": first_checkpoint["candidate_digest"],
        "expected_implementation_manifest_digest": first_checkpoint[
            "implementation_manifest_digest"
        ],
        "expected_plan_digest": first_checkpoint["plan_digest"],
        "expected_plan_action_set_digest": bindings["plan_action_set_digest"],
        "expected_compensation_nonce": authorization["compensation_nonce"],
        "expected_issuer_identity": authorization["issuer_identity"],
        "trusted_now": datetime(2026, 8, 13, 9, 30, tzinfo=timezone.utc),
    }


def public_recovery_validation_inputs(
    authorization: dict[str, object],
    original_manifest: dict[str, object],
    original_snapshots: list[dict[str, object]],
    current_manifest: dict[str, object],
    current_snapshots: list[dict[str, object]],
) -> dict[str, object]:
    fresh_inputs = compensation_validation_inputs(
        authorization, original_manifest, original_snapshots
    )
    recovery_inputs = {
        key: value
        for key, value in fresh_inputs.items()
        if key
        not in {
            "checkpoint_set_manifest",
            "trusted_checkpoint_store_generation",
            "trusted_checkpoint_records",
            "pretransition_checkpoint_store_generation",
            "pretransition_checkpoint_records",
            "trusted_now",
        }
    }
    ledger_claim_identity = EXECUTION_AUTHORITY.compensation_ledger_claim_identity(
        recovery_inputs["expected_execution_domain_identity"],
        recovery_inputs["expected_compensation_nonce"],
    )
    recovery_inputs.update(
        {
            "original_checkpoint_set_manifest": original_manifest,
            "original_checkpoint_store_generation": original_manifest[
                "checkpoint_store_generation"
            ],
            "original_checkpoint_records": original_snapshots,
            "current_checkpoint_set_manifest": current_manifest,
            "current_checkpoint_store_generation": current_manifest[
                "checkpoint_store_generation"
            ],
            "current_checkpoint_records": current_snapshots,
            "pretransition_checkpoint_store_generation": current_manifest[
                "checkpoint_store_generation"
            ],
            "pretransition_checkpoint_records": copy.deepcopy(current_snapshots),
            "expected_compensation_ledger_claim_identity": ledger_claim_identity,
            "trusted_compensation_ledger_claim_identity": ledger_claim_identity,
            "trusted_compensation_ledger_authorization_identity": authorization[
                "compensation_authorization_identity"
            ],
            "trusted_compensation_ledger_authorization_digest": canonical_digest(
                authorization
            ),
            "trusted_compensation_ledger_generation": 1,
        }
    )
    return recovery_inputs


def valid_release_archive_manifest() -> dict[str, object]:
    authorization = valid_apply_authorization()
    authorization_digest = seal_apply_authorization(authorization)
    checkpoint_set = valid_checkpoint_set_manifest()
    run_terminal = valid_run_terminal_record(checkpoint_set)
    prepared = valid_prepared_action_authority_set()
    capture_observation_authorities = valid_capture_observation_authority_set()
    payload = {
        "candidate_identity": authorization["bindings"]["candidate_identity"],
        "implementation_manifest_digest": authorization["bindings"][
            "implementation_manifest_digest"
        ],
        "execution_binding": execution_binding(authorization, authorization_digest),
        "plan_action_set_digest": authorization["bindings"]["plan_action_set_digest"],
        "checkpoint_set_identity": checkpoint_set["checkpoint_set_identity"],
        "checkpoint_set_digest": checkpoint_set["checkpoint_set_digest"],
        "run_terminal_identity": run_terminal["run_terminal_identity"],
        "run_terminal_digest": run_terminal["run_terminal_digest"],
        "launcher_identity": "release-launcher:fixture/v1",
        "launcher_manifest_digest": DIGEST_A,
        "archive_destination": {
            "store_identity": "release-store:fixture/authority",
            "store_key": "archive-key:fixture/candidate-v1",
            "compare_token": "absent",
            "committed_generation": 1,
        },
        "archived_document_byte_digests": {
            "apply_authorization_bytes_digest": DIGEST_D,
            "capture_observation_authority_set_bytes_digest": byte_digest(
                canonical_bytes(capture_observation_authorities)
            ),
            "prepared_action_authority_set_bytes_digest": byte_digest(
                canonical_bytes(prepared)
            ),
            "checkpoint_set_manifest_bytes_digest": byte_digest(
                canonical_bytes(checkpoint_set)
            ),
            "run_terminal_record_bytes_digest": byte_digest(
                canonical_bytes(run_terminal)
            ),
            "expected_case_manifest_bytes_digest": DIGEST_A,
            "evidence_bundle_bytes_digest": DIGEST_B,
            "attestation_manifest_bytes_digest": DIGEST_C,
        },
    }
    document: dict[str, object] = {
        "schema_version": "agent-equipment-release-archive-manifest/v1",
        "archive_identity": "release-archive:" + canonical_digest(payload),
        "payload": payload,
        "archive_manifest_digest": "",
    }
    unsigned = copy.deepcopy(document)
    del unsigned["archive_manifest_digest"]
    document["archive_manifest_digest"] = canonical_digest(unsigned)
    return document


def valid_release_receipt(
    archive: dict[str, object] | None = None,
) -> dict[str, object]:
    archive = archive or valid_release_archive_manifest()
    archive_payload = archive["payload"]
    assert isinstance(archive_payload, dict)
    payload = {
        "issued_at": "2026-08-13T09:00:00Z",
        "outcome": "passed",
        "candidate_identity": archive_payload["candidate_identity"],
        "implementation_manifest_digest": archive_payload[
            "implementation_manifest_digest"
        ],
        "execution_binding": copy.deepcopy(archive_payload["execution_binding"]),
        "plan_action_set_digest": archive_payload["plan_action_set_digest"],
        "checkpoint_set_identity": archive_payload["checkpoint_set_identity"],
        "checkpoint_set_digest": archive_payload["checkpoint_set_digest"],
        "run_terminal_identity": archive_payload["run_terminal_identity"],
        "run_terminal_digest": archive_payload["run_terminal_digest"],
        "launcher_identity": archive_payload["launcher_identity"],
        "launcher_manifest_digest": archive_payload["launcher_manifest_digest"],
        "archive_identity": archive["archive_identity"],
        "archive_manifest_digest": archive["archive_manifest_digest"],
        "archive_destination": copy.deepcopy(archive_payload["archive_destination"]),
    }
    return {
        "schema_version": "agent-equipment-release-receipt/v1",
        "receipt_identity": "release-receipt:" + canonical_digest(payload),
        "payload": payload,
    }


def canonical_bytes(document: object) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def valid_run_terminal_record(
    checkpoint_set: dict[str, object] | None = None,
) -> dict[str, object]:
    authorization = valid_apply_authorization()
    authorization_digest = seal_apply_authorization(authorization)
    checkpoint_set = checkpoint_set or valid_checkpoint_set_manifest()
    document: dict[str, object] = {
        "schema_version": "agent-equipment-run-terminal-record/v1",
        "run_terminal_identity": "run-terminal:sha256:" + "0" * 64,
        "execution_binding": execution_binding(authorization, authorization_digest),
        "plan_action_set_digest": authorization["bindings"]["plan_action_set_digest"],
        "checkpoint_set_identity": checkpoint_set["checkpoint_set_identity"],
        "checkpoint_set_digest": checkpoint_set["checkpoint_set_digest"],
        "checkpoint_store_generation": checkpoint_set["checkpoint_store_generation"],
        "state": "succeeded",
        "run_terminal_digest": DIGEST_A,
    }
    identity_payload = copy.deepcopy(document)
    identity_payload.pop("run_terminal_identity")
    identity_payload.pop("run_terminal_digest")
    document["run_terminal_identity"] = "run-terminal:" + canonical_digest(
        identity_payload
    )
    digest_payload = copy.deepcopy(document)
    digest_payload.pop("run_terminal_digest")
    document["run_terminal_digest"] = canonical_digest(digest_payload)
    return document


def release_validation_inputs(
    archive: dict[str, object] | None = None,
) -> dict[str, object]:
    archive = archive or valid_release_archive_manifest()
    payload = archive["payload"]
    assert isinstance(payload, dict)
    execution = payload["execution_binding"]
    assert isinstance(execution, dict)
    checkpoint_set = valid_checkpoint_set_manifest()
    run_terminal = valid_run_terminal_record(checkpoint_set)
    snapshots = valid_checkpoint_snapshots()
    first_record = snapshots[0]["record"]
    assert isinstance(first_record, dict)
    destination = payload["archive_destination"]
    assert isinstance(destination, dict)
    byte_digests = copy.deepcopy(payload["archived_document_byte_digests"])
    byte_digests.pop("checkpoint_set_manifest_bytes_digest")
    byte_digests.pop("capture_observation_authority_set_bytes_digest")
    byte_digests.pop("prepared_action_authority_set_bytes_digest")
    byte_digests.pop("run_terminal_record_bytes_digest")
    return {
        "checkpoint_set_manifest": checkpoint_set,
        "checkpoint_set_manifest_bytes": canonical_bytes(checkpoint_set),
        "capture_observation_authority_set_bytes": canonical_bytes(
            valid_capture_observation_authority_set()
        ),
        "prepared_action_authority_set_bytes": canonical_bytes(
            valid_prepared_action_authority_set()
        ),
        "run_terminal_record": run_terminal,
        "run_terminal_record_bytes": canonical_bytes(run_terminal),
        "expected_apply_authorization_identity": execution[
            "apply_authorization_identity"
        ],
        "expected_apply_authorization_digest": execution["apply_authorization_digest"],
        "expected_execution_domain_identity": execution["execution_domain_identity"],
        "expected_execution_nonce": execution["execution_nonce"],
        "expected_run_identity": execution["run_identity"],
        "authoritative_plan_action_set": valid_plan_action_set(),
        "expected_plan_action_set_digest": payload["plan_action_set_digest"],
        "expected_candidate_identity": payload["candidate_identity"],
        "expected_implementation_manifest_digest": payload[
            "implementation_manifest_digest"
        ],
        "expected_plan_digest": first_record["plan_digest"],
        "trusted_checkpoint_store_generation": checkpoint_set[
            "checkpoint_store_generation"
        ],
        "trusted_checkpoint_records": snapshots,
        **checkpoint_authority_inputs(),
        "expected_launcher_identity": payload["launcher_identity"],
        "expected_launcher_manifest_digest": payload["launcher_manifest_digest"],
        "expected_store_identity": destination["store_identity"],
        "expected_store_key": destination["store_key"],
        "expected_archived_document_byte_digests": byte_digests,
    }


class AgentEquipmentDeploymentContractTests(unittest.TestCase):
    def validate(self, document: object) -> bool:
        return SCHEMA.validate_document(
            document,
            schema_directory=SCHEMA_PATH.parent,
            root_schema_name=SCHEMA_PATH.name,
            allowed_schema_names=frozenset({SCHEMA_PATH.name}),
        )

    def test_apply_authorization_is_closed_over_the_complete_binding_tuple(
        self,
    ) -> None:
        authorization = valid_apply_authorization()
        self.assertTrue(self.validate(authorization))

        required_bindings = tuple(authorization["bindings"])
        for field in required_bindings:
            with self.subTest(field=field):
                candidate = copy.deepcopy(authorization)
                del candidate["bindings"][field]
                self.assertFalse(self.validate(candidate))

        candidate = copy.deepcopy(authorization)
        candidate["bindings"]["unreviewed_digest"] = DIGEST_C
        self.assertFalse(self.validate(candidate))

    def test_capture_observation_authority_is_closed_and_apply_bound(self) -> None:
        authority_set = valid_capture_observation_authority_set()
        authorization = valid_apply_authorization()

        self.assertTrue(self.validate(authority_set))
        self.assertEqual(
            authorization["bindings"]["capture_observation_authority_set_identity"],
            authority_set["authority_set_identity"],
        )
        self.assertEqual(
            authorization["bindings"]["capture_observation_authority_set_digest"],
            authority_set["authority_set_digest"],
        )
        self.assertTrue(self.validate(authorization))

        for field in tuple(authority_set):
            with self.subTest(field=field):
                candidate = copy.deepcopy(authority_set)
                del candidate[field]
                self.assertFalse(self.validate(candidate))

        candidate = copy.deepcopy(authority_set)
        candidate["bindings"]["unreviewed_digest"] = DIGEST_C
        self.assertFalse(self.validate(candidate))

    def test_capture_observation_reseal_cannot_escape_apply_authority(self) -> None:
        plan_action_set = valid_plan_action_set()
        captured_state = valid_captured_state(plan_action_set)
        authority_set = valid_capture_observation_authority_set(
            plan_action_set,
            captured_state,
        )
        authorization = valid_apply_authorization()
        inputs = {
            "authoritative_plan_action_set": plan_action_set,
            "expected_authority_set_identity": authorization["bindings"][
                "capture_observation_authority_set_identity"
            ],
            "expected_authority_set_digest": authorization["bindings"][
                "capture_observation_authority_set_digest"
            ],
            "expected_candidate_identity": plan_action_set["candidate_identity"],
            "expected_implementation_manifest_digest": plan_action_set[
                "implementation_manifest_digest"
            ],
            "expected_plan_digest": plan_action_set["plan_digest"],
            "expected_plan_action_set_digest": plan_action_set["action_set_digest"],
            "expected_capability_set_digest": captured_state["bindings"][
                "capability_set_digest"
            ],
            "expected_captured_state_identity": "capture:fixture/run-v1",
            "expected_captured_state_digest": canonical_digest(captured_state),
        }
        self.assertEqual(
            EXECUTION_AUTHORITY.validate_capture_observation_authority_set(
                authority_set,
                **inputs,
            ),
            (),
        )

        forged = copy.deepcopy(authority_set)
        forged_pre_state = forged["observations"][0]["normalized_pre_state"]
        forged_pre_state["route_presence"] = "unknown"
        forged["observations"][0]["normalized_pre_state_digest"] = canonical_digest(
            forged_pre_state
        )
        seal_capture_observation_authority_set(forged)
        diagnostics = EXECUTION_AUTHORITY.validate_capture_observation_authority_set(
            forged,
            **inputs,
        )
        self.assertIn(
            "CAPTURE_OBSERVATION_AUTHORITY_TRUST_MISMATCH",
            {diagnostic.code for diagnostic in diagnostics},
        )

        trusted_apply = valid_apply_authorization()
        seal_apply_authorization(trusted_apply)
        trusted_apply_inputs = apply_validation_inputs(trusted_apply)
        forged_apply = copy.deepcopy(trusted_apply)
        forged_apply["bindings"]["capture_observation_authority_set_digest"] = forged[
            "authority_set_digest"
        ]
        seal_apply_authorization(forged_apply)
        forged_apply_codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_apply_authorization(
                forged_apply,
                **trusted_apply_inputs,
            )
        }
        self.assertIn("APPLY_AUTHORIZATION_TRUST_MISMATCH", forged_apply_codes)
        self.assertIn("APPLY_AUTHORIZATION_DIGEST_MISMATCH", forged_apply_codes)
        self.assertIn("APPLY_AUTHORIZATION_BINDING_MISMATCH", forged_apply_codes)

    def test_capture_observation_authority_rejects_partial_raw_and_secret_inputs(
        self,
    ) -> None:
        plan_action_set = valid_plan_action_set()
        captured_state = valid_captured_state(plan_action_set)
        authority_set = valid_capture_observation_authority_set(
            plan_action_set,
            captured_state,
        )
        inputs = {
            "authoritative_plan_action_set": plan_action_set,
            "expected_authority_set_identity": authority_set["authority_set_identity"],
            "expected_authority_set_digest": authority_set["authority_set_digest"],
            "expected_candidate_identity": plan_action_set["candidate_identity"],
            "expected_implementation_manifest_digest": plan_action_set[
                "implementation_manifest_digest"
            ],
            "expected_plan_digest": plan_action_set["plan_digest"],
            "expected_plan_action_set_digest": plan_action_set["action_set_digest"],
            "expected_capability_set_digest": captured_state["bindings"][
                "capability_set_digest"
            ],
            "expected_captured_state_identity": "capture:fixture/run-v1",
            "expected_captured_state_digest": canonical_digest(captured_state),
        }

        raw_diagnostics = (
            EXECUTION_AUTHORITY.validate_capture_observation_authority_set(
                authority_set["observations"],
                **inputs,
            )
        )
        self.assertEqual(
            [diagnostic.code for diagnostic in raw_diagnostics],
            ["CAPTURE_OBSERVATION_AUTHORITY_SCHEMA_INVALID"],
        )

        missing = copy.deepcopy(authority_set)
        missing["observations"].pop()
        seal_capture_observation_authority_set(missing)
        missing_codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_capture_observation_authority_set(
                missing,
                **inputs,
            )
        }
        self.assertIn("CAPTURE_OBSERVATION_AUTHORITY_MEMBERSHIP_INVALID", missing_codes)

        reordered = copy.deepcopy(authority_set)
        reordered["observations"].reverse()
        seal_capture_observation_authority_set(reordered)
        reordered_codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_capture_observation_authority_set(
                reordered,
                **inputs,
            )
        }
        self.assertIn(
            "CAPTURE_OBSERVATION_AUTHORITY_MEMBERSHIP_INVALID",
            reordered_codes,
        )

        secret = copy.deepcopy(authority_set)
        secret["observations"][0]["normalized_pre_state"]["manager_drift"][
            "reviewed_baseline"
        ] = "ghp_" + "A" * 36
        seal_capture_observation_authority_set(secret)
        secret_diagnostics = (
            EXECUTION_AUTHORITY.validate_capture_observation_authority_set(
                secret,
                **inputs,
            )
        )
        self.assertEqual(
            [diagnostic.code for diagnostic in secret_diagnostics],
            ["CAPTURE_OBSERVATION_AUTHORITY_LITERAL_SECRET"],
        )

    def test_apply_authorization_identity_and_operator_review_are_semantic_authority(
        self,
    ) -> None:
        authorization = valid_apply_authorization()
        trusted_digest = seal_apply_authorization(authorization)
        self.assertEqual(
            authorization["authorization_identity"],
            "apply-authorization:sha256:7efe1cc1915c066a43e085365de9bfa972f12268a776af121eaadbd2fdb80b9e",
        )
        self.assertEqual(
            trusted_digest,
            "sha256:8a32cd6b574c1b43deeb7e995cffb6f1ff084e5e489a401e8438826683a9e871",
        )

        diagnostics = EXECUTION_AUTHORITY.validate_apply_authorization(
            authorization,
            expected_candidate_identity=authorization["bindings"]["candidate_identity"],
            expected_implementation_manifest_digest=authorization["bindings"][
                "implementation_manifest_digest"
            ],
            expected_apply_authorization_identity=authorization[
                "authorization_identity"
            ],
            expected_apply_authorization_digest=trusted_digest,
            expected_execution_domain_identity=authorization[
                "execution_domain_identity"
            ],
            expected_execution_nonce=authorization["execution_nonce"],
            expected_run_identity=authorization["run_identity"],
            expected_operator_review_package_digest=authorization["bindings"][
                "operator_review_package_digest"
            ],
            expected_issuer_identity=authorization["issuer_identity"],
            trusted_now=datetime(2026, 8, 13, 7, 30, tzinfo=timezone.utc),
            expected_bindings=authorization["bindings"],
        )
        self.assertEqual(diagnostics, ())

        forged = copy.deepcopy(authorization)
        forged["bindings"]["operator_review_package_digest"] = DIGEST_A
        forged_digest = seal_apply_authorization(forged)
        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_apply_authorization(
                forged,
                expected_candidate_identity=forged["bindings"]["candidate_identity"],
                expected_implementation_manifest_digest=forged["bindings"][
                    "implementation_manifest_digest"
                ],
                expected_apply_authorization_identity=forged["authorization_identity"],
                expected_apply_authorization_digest=forged_digest,
                expected_execution_domain_identity=forged["execution_domain_identity"],
                expected_execution_nonce=forged["execution_nonce"],
                expected_run_identity=forged["run_identity"],
                expected_operator_review_package_digest=DIGEST_C,
                expected_issuer_identity=forged["issuer_identity"],
                trusted_now=datetime(2026, 8, 13, 7, 30, tzinfo=timezone.utc),
                expected_bindings=authorization["bindings"],
            )
        }
        self.assertIn("OPERATOR_REVIEW_PACKAGE_BINDING_MISMATCH", codes)

    def test_apply_authorization_validates_the_complete_tuple_and_time_window(
        self,
    ) -> None:
        authorization = valid_apply_authorization()
        trusted_digest = seal_apply_authorization(authorization)
        trusted_bindings = copy.deepcopy(authorization["bindings"])
        trusted_inputs = {
            "expected_candidate_identity": trusted_bindings["candidate_identity"],
            "expected_implementation_manifest_digest": trusted_bindings[
                "implementation_manifest_digest"
            ],
            "expected_apply_authorization_identity": authorization[
                "authorization_identity"
            ],
            "expected_apply_authorization_digest": trusted_digest,
            "expected_execution_domain_identity": authorization[
                "execution_domain_identity"
            ],
            "expected_execution_nonce": authorization["execution_nonce"],
            "expected_run_identity": authorization["run_identity"],
            "expected_operator_review_package_digest": trusted_bindings[
                "operator_review_package_digest"
            ],
            "expected_issuer_identity": authorization["issuer_identity"],
            "trusted_now": datetime(2026, 8, 13, 7, 30, tzinfo=timezone.utc),
            "expected_bindings": trusted_bindings,
        }
        self.assertEqual(
            EXECUTION_AUTHORITY.validate_apply_authorization(
                authorization, **trusted_inputs
            ),
            (),
        )

        mutations = {
            "issuer": lambda candidate: candidate.update(
                {"issuer_identity": "authority:fixture/other"}
            ),
            "catalog": lambda candidate: candidate["bindings"].update(
                {"catalog_digest": DIGEST_A}
            ),
            "lock": lambda candidate: candidate["bindings"].update(
                {"lock_digest": DIGEST_A}
            ),
            "plan": lambda candidate: candidate["bindings"].update(
                {"plan_digest": DIGEST_B}
            ),
            "action set": lambda candidate: candidate["bindings"].update(
                {"plan_action_set_digest": DIGEST_C}
            ),
            "capability set": lambda candidate: candidate["bindings"].update(
                {"capability_set_digest": DIGEST_A}
            ),
            "capture": lambda candidate: candidate["bindings"].update(
                {"captured_state_digest": DIGEST_B}
            ),
            "capture observation authority identity": lambda candidate: candidate[
                "bindings"
            ].update(
                {
                    "capture_observation_authority_set_identity": (
                        "capture-observation-authority-set:sha256:" + "9" * 64
                    )
                }
            ),
            "capture observation authority digest": lambda candidate: candidate[
                "bindings"
            ].update({"capture_observation_authority_set_digest": DIGEST_D}),
            "expected cases": lambda candidate: candidate["bindings"].update(
                {"expected_case_manifest_digest": DIGEST_A}
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                candidate = copy.deepcopy(authorization)
                mutate(candidate)
                candidate_digest = seal_apply_authorization(candidate)
                inputs = dict(trusted_inputs)
                inputs["expected_apply_authorization_identity"] = candidate[
                    "authorization_identity"
                ]
                inputs["expected_apply_authorization_digest"] = candidate_digest
                codes = {
                    diagnostic.code
                    for diagnostic in EXECUTION_AUTHORITY.validate_apply_authorization(
                        candidate, **inputs
                    )
                }
                self.assertIn("APPLY_AUTHORIZATION_BINDING_MISMATCH", codes)

        for label, trusted_now in (
            ("before", datetime(2026, 8, 13, 6, 59, 59, tzinfo=timezone.utc)),
            ("expired", datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)),
        ):
            with self.subTest(label=label):
                inputs = dict(trusted_inputs)
                inputs["trusted_now"] = trusted_now
                codes = {
                    diagnostic.code
                    for diagnostic in EXECUTION_AUTHORITY.validate_apply_authorization(
                        authorization, **inputs
                    )
                }
                self.assertIn("APPLY_AUTHORIZATION_TIME_INVALID", codes)

        for label, trusted_now in (
            ("naive", datetime(2026, 8, 13, 7, 30)),  # noqa: DTZ001
            ("non-datetime", "2026-08-13T07:30:00Z"),
        ):
            with self.subTest(label=label):
                inputs = dict(trusted_inputs)
                inputs["trusted_now"] = trusted_now
                diagnostics = EXECUTION_AUTHORITY.validate_apply_authorization(
                    authorization, **inputs
                )
                self.assertEqual(
                    [diagnostic.code for diagnostic in diagnostics],
                    ["TRUSTED_CLOCK_INVALID"],
                )

    def test_apply_authorization_is_bound_to_one_trusted_execution_domain(
        self,
    ) -> None:
        authorization = valid_apply_authorization()
        seal_apply_authorization(authorization)
        trusted_inputs = apply_validation_inputs(authorization)

        self.assertEqual(
            EXECUTION_AUTHORITY.validate_apply_authorization(
                authorization, **trusted_inputs
            ),
            (),
        )
        foreign_inputs = dict(trusted_inputs)
        foreign_inputs["expected_execution_domain_identity"] = (
            "execution-domain:fixture/other-ledger-v1"
        )
        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_apply_authorization(
                authorization, **foreign_inputs
            )
        }
        self.assertIn("EXECUTION_DOMAIN_MISMATCH", codes)
        self.assertEqual(
            EXECUTION_AUTHORITY.authorization_ledger_claim_identity(
                authorization["execution_domain_identity"],
                authorization["execution_nonce"],
            ),
            "authorization-ledger-claim:sha256:"
            "9e9791ab1c9634b4c9740924bf7370ce1418ab20e1a9666656e8c43ad2c36ebd",
        )

    def test_apply_authorization_compares_bounded_fractional_seconds_exactly(
        self,
    ) -> None:
        authorization = valid_apply_authorization()
        authorization["issued_at"] = "2026-08-13T06:59:59Z"
        authorization["not_before"] = "2026-08-13T07:00:00.0000009Z"
        seal_apply_authorization(authorization)
        diagnostics = EXECUTION_AUTHORITY.validate_apply_authorization(
            authorization,
            **apply_validation_inputs(
                authorization,
                trusted_now=datetime(2026, 8, 13, 7, 0, tzinfo=timezone.utc),
            ),
        )
        self.assertIn(
            "APPLY_AUTHORIZATION_TIME_INVALID",
            {diagnostic.code for diagnostic in diagnostics},
        )

        authorization["not_before"] = "2026-08-13T07:00:00Z"
        authorization["expires_at"] = "2026-08-13T07:00:00.9999999Z"
        seal_apply_authorization(authorization)
        diagnostics = EXECUTION_AUTHORITY.validate_apply_authorization(
            authorization,
            **apply_validation_inputs(
                authorization,
                trusted_now=datetime(2026, 8, 13, 7, 0, 0, 999999, tzinfo=timezone.utc),
            ),
        )
        self.assertEqual(diagnostics, ())

        authorization["not_before"] = "2026-08-13T07:00:00.000000001Z"
        authorization["expires_at"] = "2026-08-13T08:00:00Z"
        seal_apply_authorization(authorization)
        diagnostics = EXECUTION_AUTHORITY.validate_apply_authorization(
            authorization,
            **apply_validation_inputs(
                authorization,
                trusted_now=datetime(2026, 8, 13, 7, 0, tzinfo=timezone.utc),
            ),
        )
        self.assertIn(
            "APPLY_AUTHORIZATION_TIME_INVALID",
            {diagnostic.code for diagnostic in diagnostics},
        )

        authorization["not_before"] = "2026-08-13T07:00:00.0000000001Z"
        seal_apply_authorization(authorization)
        self.assertFalse(self.validate(authorization))

    def test_prepared_action_authority_is_complete_and_semantically_bound(self) -> None:
        plan = valid_plan_action_set()
        capture = valid_captured_state(plan)
        prepared = valid_prepared_action_authority_set(plan)
        trusted_inputs = prepared_validation_inputs(plan, capture, prepared)
        self.assertEqual(
            EXECUTION_AUTHORITY.validate_prepared_action_authority_set(
                prepared, **trusted_inputs
            ),
            (),
        )

        resealed_observations = copy.deepcopy(
            trusted_inputs["capture_observation_authority_set"]
        )
        resealed_observations["observations"][0]["normalized_pre_state"][
            "route_presence"
        ] = "unknown"
        resealed_observations["observations"][0]["normalized_pre_state_digest"] = (
            canonical_digest(
                resealed_observations["observations"][0]["normalized_pre_state"]
            )
        )
        seal_capture_observation_authority_set(resealed_observations)
        stale_observation_digest_inputs = dict(trusted_inputs)
        stale_observation_digest_inputs["capture_observation_authority_set"] = (
            resealed_observations
        )
        self.assertIn(
            "CAPTURE_OBSERVATION_AUTHORITY_TRUST_MISMATCH",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_prepared_action_authority_set(
                    prepared, **stale_observation_digest_inputs
                )
            },
        )

        missing = copy.deepcopy(prepared)
        missing["authorities"].pop()
        seal_prepared_action_authority_set(missing)
        missing_inputs = prepared_validation_inputs(plan, capture, missing)
        self.assertIn(
            "PREPARED_ACTION_AUTHORITY_INVALID",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_prepared_action_authority_set(
                    missing, **missing_inputs
                )
            },
        )

        wrong_post = copy.deepcopy(prepared)
        wrong_authority = wrong_post["authorities"][0]
        wrong_authority["expected_post_state"]["route_presence"] = "absent"
        wrong_authority["expected_post_state_digest"] = canonical_digest(
            wrong_authority["expected_post_state"]
        )
        seal_prepared_action_authority(wrong_authority)
        seal_prepared_action_authority_set(wrong_post)
        wrong_post_inputs = prepared_validation_inputs(plan, capture, wrong_post)
        self.assertIn(
            "PREPARED_ACTION_AUTHORITY_INVALID",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_prepared_action_authority_set(
                    wrong_post, **wrong_post_inputs
                )
            },
        )

        wrong_capability = copy.deepcopy(prepared)
        wrong_capability["authorities"][0]["capability_set_digest"] = DIGEST_D
        seal_prepared_action_authority(wrong_capability["authorities"][0])
        seal_prepared_action_authority_set(wrong_capability)
        capability_inputs = prepared_validation_inputs(plan, capture, wrong_capability)
        self.assertIn(
            "PREPARED_ACTION_AUTHORITY_INVALID",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_prepared_action_authority_set(
                    wrong_capability, **capability_inputs
                )
            },
        )

        coordinated_reseal = copy.deepcopy(prepared)
        coordinated_authority = coordinated_reseal["authorities"][0]
        coordinated_authority["captured_pre_state"]["route_presence"] = "unknown"
        coordinated_authority["captured_pre_state_digest"] = canonical_digest(
            coordinated_authority["captured_pre_state"]
        )
        seal_prepared_action_authority(coordinated_authority)
        seal_prepared_action_authority_set(coordinated_reseal)
        coordinated_capture_authorities = copy.deepcopy(
            trusted_inputs["capture_observation_authority_set"]
        )
        coordinated_observation = coordinated_capture_authorities["observations"][0]
        coordinated_observation["normalized_pre_state"] = copy.deepcopy(
            coordinated_authority["captured_pre_state"]
        )
        coordinated_observation["normalized_pre_state_digest"] = canonical_digest(
            coordinated_observation["normalized_pre_state"]
        )
        seal_capture_observation_authority_set(coordinated_capture_authorities)
        coordinated_inputs = dict(trusted_inputs)
        coordinated_inputs["capture_observation_authority_set"] = (
            coordinated_capture_authorities
        )
        coordinated_inputs["expected_prepared_action_authority_set_identity"] = (
            coordinated_reseal["authority_set_identity"]
        )
        coordinated_inputs["expected_prepared_action_authority_set_digest"] = (
            coordinated_reseal["authority_set_digest"]
        )
        self.assertIn(
            "CAPTURE_OBSERVATION_AUTHORITY_TRUST_MISMATCH",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_prepared_action_authority_set(
                    coordinated_reseal, **coordinated_inputs
                )
            },
        )

        oversized = copy.deepcopy(prepared)
        oversized_pre_state = oversized["authorities"][0]["captured_pre_state"]
        oversized_pre_state["observed_version"] = {
            "status": "observed",
            "value": "x" * 300_000,
        }
        oversized["authorities"][0]["captured_pre_state_digest"] = canonical_digest(
            oversized_pre_state
        )
        seal_prepared_action_authority(oversized["authorities"][0])
        seal_prepared_action_authority_set(oversized)
        oversized_inputs = prepared_validation_inputs(plan, capture, oversized)
        self.assertGreater(
            len(canonical_bytes(oversized)),
            EXECUTION_AUTHORITY.MAX_EXECUTION_AUTHORITY_BYTES,
        )

        original_validate_schema = EXECUTION_AUTHORITY._validate_schema
        original_identity = EXECUTION_AUTHORITY._prepared_action_authority_set_identity
        original_digest = EXECUTION_AUTHORITY._prepared_action_authority_set_digest

        def reject_oversized_schema_bypass(candidate: object, **kwargs: object) -> bool:
            if candidate is oversized:
                raise AssertionError("oversized authority reached Schema validation")
            return original_validate_schema(candidate, **kwargs)

        def reject_oversized_seal_trust(*_args: object, **_kwargs: object) -> str:
            raise AssertionError("oversized authority reached seal-trust comparison")

        try:
            EXECUTION_AUTHORITY._validate_schema = reject_oversized_schema_bypass
            EXECUTION_AUTHORITY._prepared_action_authority_set_identity = (
                reject_oversized_seal_trust
            )
            EXECUTION_AUTHORITY._prepared_action_authority_set_digest = (
                reject_oversized_seal_trust
            )
            oversized_codes = {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_prepared_action_authority_set(
                    oversized, **oversized_inputs
                )
            }
        finally:
            EXECUTION_AUTHORITY._validate_schema = original_validate_schema
            EXECUTION_AUTHORITY._prepared_action_authority_set_identity = (
                original_identity
            )
            EXECUTION_AUTHORITY._prepared_action_authority_set_digest = original_digest
        self.assertIn("PREPARED_ACTION_AUTHORITY_INVALID", oversized_codes)

        duplicate_ordinal_plan = valid_plan_action_set()
        duplicate_action = duplicate_ordinal_plan["actions"][1]["action_payload"]
        duplicate_action["ordinal"] = 0
        duplicate_action["action_identity"] = EXECUTION_AUTHORITY._plan_action_identity(
            duplicate_action
        )
        duplicate_ordinal_plan["actions"][1]["action_digest"] = (
            EXECUTION_AUTHORITY._plan_action_digest(duplicate_action)
        )
        duplicate_ordinal_plan["action_set_digest"] = (
            EXECUTION_AUTHORITY._plan_action_set_digest(
                duplicate_ordinal_plan["candidate_identity"],
                duplicate_ordinal_plan["implementation_manifest_digest"],
                duplicate_ordinal_plan["plan_digest"],
                duplicate_ordinal_plan["actions"],
            )
        )
        self.assertIn(
            "PLAN_ACTION_SET_MEMBERSHIP_INVALID",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_plan_action_set(
                    duplicate_ordinal_plan,
                    expected_action_set_digest=duplicate_ordinal_plan[
                        "action_set_digest"
                    ],
                    expected_candidate_identity=duplicate_ordinal_plan[
                        "candidate_identity"
                    ],
                    expected_implementation_manifest_digest=duplicate_ordinal_plan[
                        "implementation_manifest_digest"
                    ],
                    expected_plan_digest=duplicate_ordinal_plan["plan_digest"],
                )
            },
        )

    def test_prepared_action_authority_rejects_component_and_data_ambiguity(
        self,
    ) -> None:
        plan = valid_plan_action_set()
        capture = valid_captured_state(plan)
        prepared = valid_prepared_action_authority_set(plan)

        duplicate = copy.deepcopy(prepared)
        duplicate_state = duplicate["authorities"][0]["captured_pre_state"]
        duplicate_state["component_states"] = [
            {"equipment_identity": "plugin:fixture/example", "state": "enabled"},
            {"equipment_identity": "plugin:fixture/example", "state": "disabled"},
        ]
        duplicate["authorities"][0]["captured_pre_state_digest"] = canonical_digest(
            duplicate_state
        )
        seal_prepared_action_authority(duplicate["authorities"][0])
        seal_prepared_action_authority_set(duplicate)
        duplicate_inputs = prepared_validation_inputs(plan, capture, duplicate)
        self.assertIn(
            "PREPARED_ACTION_AUTHORITY_INVALID",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_prepared_action_authority_set(
                    duplicate, **duplicate_inputs
                )
            },
        )

        secret = copy.deepcopy(prepared)
        secret_state = secret["authorities"][0]["expected_post_state"]
        secret_state["observed_version"] = {
            "status": "observed",
            "value": "ghp_" + "A" * 24,
        }
        secret["authorities"][0]["expected_post_state_digest"] = canonical_digest(
            secret_state
        )
        seal_prepared_action_authority(secret["authorities"][0])
        seal_prepared_action_authority_set(secret)
        secret_inputs = prepared_validation_inputs(plan, capture, secret)
        self.assertIn(
            "PREPARED_ACTION_AUTHORITY_INVALID",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_prepared_action_authority_set(
                    secret, **secret_inputs
                )
            },
        )

        invalid_native_state = copy.deepcopy(prepared)
        invalid_native_state["authorities"][0]["captured_pre_state"].update(
            {
                "native_update_control": "unsuppressible",
                "native_update_suppression_state": "enabled",
            }
        )
        self.assertFalse(self.validate(invalid_native_state))

        plus_capability = copy.deepcopy(prepared)
        plus_capability["authorities"][0]["route_capability_binding"][
            "capability_identity"
        ] = "capability:fixture+native"
        seal_prepared_action_authority(plus_capability["authorities"][0])
        seal_prepared_action_authority_set(plus_capability)
        self.assertTrue(self.validate(plus_capability))

        for malformed_capture in (object(), {"not_json": float("nan")}):
            with self.subTest(malformed_capture=type(malformed_capture).__name__):
                malformed_inputs = dict(
                    prepared_validation_inputs(plan, capture, prepared)
                )
                malformed_inputs["authoritative_captured_state"] = malformed_capture
                malformed_inputs["expected_captured_state_digest"] = DIGEST_D
                codes = {
                    diagnostic.code
                    for diagnostic in EXECUTION_AUTHORITY.validate_prepared_action_authority_set(
                        prepared, **malformed_inputs
                    )
                }
                self.assertIn("CAPTURED_STATE_AUTHORITY_INVALID", codes)

    def test_prepared_action_authority_requires_exact_controlled_components(
        self,
    ) -> None:
        plan = valid_plan_action_set()
        evidence = plan["actions"][0]
        action = evidence["action_payload"]
        action["controlled_equipment_identities"] = ["plugin:fixture/example"]
        action["action_identity"] = EXECUTION_AUTHORITY._plan_action_identity(action)
        evidence["action_digest"] = EXECUTION_AUTHORITY._plan_action_digest(action)
        plan["action_set_digest"] = EXECUTION_AUTHORITY._plan_action_set_digest(
            plan["candidate_identity"],
            plan["implementation_manifest_digest"],
            plan["plan_digest"],
            plan["actions"],
        )
        capture = valid_captured_state(plan)
        first_route = capture["provider_routes"][0]
        first_route["controlled_equipment_identities"] = ["plugin:fixture/example"]
        first_route["planned_actions"][0]["action_identity"] = action["action_identity"]
        prepared = valid_prepared_action_authority_set(plan)
        for authority in prepared["authorities"]:
            authority["captured_state_digest"] = canonical_digest(capture)
            seal_prepared_action_authority(authority)
        seal_prepared_action_authority_set(prepared)
        inputs = prepared_validation_inputs(plan, capture, prepared)
        self.assertIn(
            "PREPARED_ACTION_AUTHORITY_INVALID",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_prepared_action_authority_set(
                    prepared, **inputs
                )
            },
        )

        extra = copy.deepcopy(prepared)
        for state_field in ("captured_pre_state", "expected_post_state"):
            extra["authorities"][0][state_field]["component_states"] = [
                {"equipment_identity": "plugin:fixture/example", "state": "enabled"},
                {"equipment_identity": "skill:fixture/example", "state": "enabled"},
            ]
            extra["authorities"][0][f"{state_field}_digest"] = canonical_digest(
                extra["authorities"][0][state_field]
            )
        seal_prepared_action_authority(extra["authorities"][0])
        seal_prepared_action_authority_set(extra)
        extra_inputs = prepared_validation_inputs(plan, capture, extra)
        self.assertIn(
            "PREPARED_ACTION_AUTHORITY_INVALID",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_prepared_action_authority_set(
                    extra, **extra_inputs
                )
            },
        )

    def test_checkpoint_set_manifest_is_closed_and_matches_the_trusted_store(
        self,
    ) -> None:
        snapshots = valid_checkpoint_snapshots()
        manifest = valid_checkpoint_set_manifest(snapshots)
        self.assertTrue(self.validate(manifest))
        bindings = manifest["bindings"]
        assert isinstance(bindings, dict)
        first_record = snapshots[0]["record"]
        assert isinstance(first_record, dict)
        diagnostics = EXECUTION_AUTHORITY.validate_checkpoint_set_manifest(
            manifest,
            expected_apply_authorization_identity=bindings[
                "apply_authorization_identity"
            ],
            expected_apply_authorization_digest=bindings["apply_authorization_digest"],
            expected_execution_domain_identity=bindings["execution_domain_identity"],
            expected_execution_nonce=bindings["execution_nonce"],
            expected_run_identity=bindings["run_identity"],
            expected_plan_action_set_digest=bindings["plan_action_set_digest"],
            trusted_checkpoint_store_generation=manifest["checkpoint_store_generation"],
            trusted_checkpoint_records=copy.deepcopy(snapshots),
            pretransition_checkpoint_store_generation=manifest[
                "checkpoint_store_generation"
            ],
            pretransition_checkpoint_records=copy.deepcopy(snapshots),
            **checkpoint_authority_inputs(),
            authoritative_plan_action_set=valid_plan_action_set(),
            expected_candidate_identity=first_record["candidate_digest"],
            expected_implementation_manifest_digest=first_record[
                "implementation_manifest_digest"
            ],
            expected_plan_digest=first_record["plan_digest"],
        )
        self.assertEqual(diagnostics, ())
        self.assertEqual(
            first_record["checkpoint_identity"],
            EXECUTION_AUTHORITY.checkpoint_identity(
                "agent-equipment-checkpoint/v1", first_record
            ),
        )

        acceptance_spec = importlib.util.spec_from_file_location(
            "agent_equipment_acceptance_model_checkpoint_contract",
            ROOT / "scripts/agent_equipment_acceptance_model.py",
        )
        assert acceptance_spec is not None and acceptance_spec.loader is not None
        acceptance = importlib.util.module_from_spec(acceptance_spec)
        sys.modules[acceptance_spec.name] = acceptance
        acceptance_spec.loader.exec_module(acceptance)
        acceptance_checkpoint = copy.deepcopy(first_record)
        self.assertEqual(
            acceptance.checkpoint_identity(acceptance_checkpoint),
            first_record["checkpoint_identity"],
        )

        identity_payload = copy.deepcopy(manifest)
        identity_payload.pop("checkpoint_set_identity")
        identity_payload.pop("checkpoint_set_digest")
        self.assertEqual(
            manifest["checkpoint_set_identity"],
            "checkpoint-set:" + canonical_digest(identity_payload),
        )
        digest_payload = copy.deepcopy(manifest)
        digest_payload.pop("checkpoint_set_digest")
        self.assertEqual(
            manifest["checkpoint_set_digest"],
            canonical_digest(digest_payload),
        )

    def test_checkpoint_set_rejects_incomplete_foreign_or_stale_store_views(
        self,
    ) -> None:
        snapshots = valid_checkpoint_snapshots()
        manifest = valid_checkpoint_set_manifest(snapshots)
        bindings = manifest["bindings"]
        assert isinstance(bindings, dict)
        first_record = snapshots[0]["record"]
        assert isinstance(first_record, dict)
        plan_action_set = valid_plan_action_set()

        def diagnostics_for(
            candidate: dict[str, object],
            *,
            trusted_records: list[dict[str, object]] | None = None,
            trusted_generation: int | None = None,
            pretransition_records: list[dict[str, object]] | None = None,
            pretransition_generation: int | None = None,
            expected_action_set: dict[str, object] | None = None,
        ) -> set[str]:
            return {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_checkpoint_set_manifest(
                    candidate,
                    expected_apply_authorization_identity=bindings[
                        "apply_authorization_identity"
                    ],
                    expected_apply_authorization_digest=bindings[
                        "apply_authorization_digest"
                    ],
                    expected_execution_domain_identity=bindings[
                        "execution_domain_identity"
                    ],
                    expected_execution_nonce=bindings["execution_nonce"],
                    expected_run_identity=bindings["run_identity"],
                    expected_plan_action_set_digest=bindings["plan_action_set_digest"],
                    trusted_checkpoint_store_generation=(
                        manifest["checkpoint_store_generation"]
                        if trusted_generation is None
                        else trusted_generation
                    ),
                    trusted_checkpoint_records=(
                        copy.deepcopy(snapshots)
                        if trusted_records is None
                        else trusted_records
                    ),
                    pretransition_checkpoint_store_generation=(
                        manifest["checkpoint_store_generation"]
                        if pretransition_generation is None
                        else pretransition_generation
                    ),
                    pretransition_checkpoint_records=(
                        copy.deepcopy(snapshots)
                        if pretransition_records is None
                        else pretransition_records
                    ),
                    **checkpoint_authority_inputs(),
                    authoritative_plan_action_set=(
                        copy.deepcopy(plan_action_set)
                        if expected_action_set is None
                        else expected_action_set
                    ),
                    expected_candidate_identity=first_record["candidate_digest"],
                    expected_implementation_manifest_digest=first_record[
                        "implementation_manifest_digest"
                    ],
                    expected_plan_digest=first_record["plan_digest"],
                )
            }

        three_actions = valid_plan_action_set(action_count=3)
        extra_snapshot = checkpoint_snapshot(
            valid_checkpoint_record(2, three_actions), 3
        )
        mutations = {
            "missing": lambda candidate: candidate["checkpoints"].pop(),
            "extra": lambda candidate: candidate["checkpoints"].append(
                checkpoint_manifest_entry(extra_snapshot)
            ),
            "duplicate identity": lambda candidate: candidate["checkpoints"][1].update(
                {
                    "checkpoint_identity": candidate["checkpoints"][0][
                        "checkpoint_identity"
                    ]
                }
            ),
            "duplicate ordinal": lambda candidate: candidate["checkpoints"][1].update(
                {"ordinal": candidate["checkpoints"][0]["ordinal"]}
            ),
            "foreign action": lambda candidate: candidate["checkpoints"][0].update(
                {"action_identity": "action:sha256:" + "f" * 64}
            ),
            "reordered": lambda candidate: candidate["checkpoints"].reverse(),
            "phase": lambda candidate: candidate["checkpoints"][0].update(
                {"phase": "prepared"}
            ),
            "intent": lambda candidate: candidate["checkpoints"][0].update(
                {"invocation_state": "not_started"}
            ),
            "record digest": lambda candidate: candidate["checkpoints"][0].update(
                {"checkpoint_record_digest": DIGEST_D}
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                candidate = copy.deepcopy(manifest)
                mutate(candidate)
                seal_checkpoint_set_manifest(candidate)
                self.assertIn(
                    "CHECKPOINT_SET_MEMBERSHIP_MISMATCH", diagnostics_for(candidate)
                )

        empty = valid_checkpoint_set_manifest([])
        self.assertIn("CHECKPOINT_SET_SCHEMA_INVALID", diagnostics_for(empty))

        self.assertIn(
            "CHECKPOINT_STORE_GENERATION_MISMATCH",
            diagnostics_for(manifest, trusted_generation=8),
        )
        self.assertIn(
            "CHECKPOINT_STORE_GENERATION_MISMATCH",
            diagnostics_for(manifest, trusted_generation=True),
        )
        self.assertIn(
            "CHECKPOINT_STORE_CONCURRENT_CHANGE",
            diagnostics_for(manifest, pretransition_generation=True),
        )

        changed_store = copy.deepcopy(snapshots)
        changed_store[0]["durable_generation"] += 1
        self.assertIn(
            "CHECKPOINT_SET_MEMBERSHIP_MISMATCH",
            diagnostics_for(manifest, trusted_records=changed_store),
        )

        for label, mutate in {
            "unknown field": lambda record: record.update({"foreign": True}),
            "invalid history": lambda record: record.update(
                {"phase_history": ["completed"]}
            ),
            "non-string history": lambda record: record.update({"phase_history": [{}]}),
        }.items():
            with self.subTest(malformed_store=label):
                malformed_store = copy.deepcopy(snapshots)
                malformed_record = malformed_store[0]["record"]
                assert isinstance(malformed_record, dict)
                mutate(malformed_record)
                self.assertIn(
                    "CHECKPOINT_SET_MEMBERSHIP_MISMATCH",
                    diagnostics_for(manifest, trusted_records=malformed_store),
                )

        changed_before_transition = copy.deepcopy(snapshots)
        changed_record = changed_before_transition[0]["record"]
        assert isinstance(changed_record, dict)
        changed_record["phase"] = "compensating"
        changed_record["phase_history"].append("compensating")
        self.assertIn(
            "CHECKPOINT_STORE_CONCURRENT_CHANGE",
            diagnostics_for(
                manifest,
                pretransition_records=changed_before_transition,
                pretransition_generation=8,
            ),
        )

        foreign_action_store = copy.deepcopy(snapshots)
        foreign_action_record = foreign_action_store[0]["record"]
        assert isinstance(foreign_action_record, dict)
        foreign_action_record["action_identity"] = "action:sha256:" + "f" * 64
        foreign_action_manifest = valid_checkpoint_set_manifest(foreign_action_store)
        self.assertIn(
            "CHECKPOINT_PLAN_ACTION_MISMATCH",
            diagnostics_for(
                foreign_action_manifest,
                trusted_records=foreign_action_store,
                pretransition_records=foreign_action_store,
            ),
        )

        coordinated_store = copy.deepcopy(snapshots)
        coordinated_record = coordinated_store[0]["record"]
        assert isinstance(coordinated_record, dict)
        coordinated_record["catalog_digest"] = DIGEST_D
        coordinated_record["checkpoint_identity"] = (
            EXECUTION_AUTHORITY.checkpoint_identity(
                "agent-equipment-checkpoint/v1", coordinated_record
            )
        )
        coordinated_manifest = valid_checkpoint_set_manifest(coordinated_store)
        self.assertIn(
            "CHECKPOINT_BINDING_MISMATCH",
            diagnostics_for(
                coordinated_manifest,
                trusted_records=coordinated_store,
                pretransition_records=coordinated_store,
            ),
        )

        wrong_step_store = copy.deepcopy(snapshots)
        wrong_step_record = wrong_step_store[0]["record"]
        assert isinstance(wrong_step_record, dict)
        wrong_step_record["step_id"] = "step-999"
        wrong_step_record["checkpoint_identity"] = (
            EXECUTION_AUTHORITY.checkpoint_identity(
                "agent-equipment-checkpoint/v1", wrong_step_record
            )
        )
        wrong_step_manifest = valid_checkpoint_set_manifest(wrong_step_store)
        self.assertIn(
            "CHECKPOINT_PLAN_ACTION_MISMATCH",
            diagnostics_for(
                wrong_step_manifest,
                trusted_records=wrong_step_store,
                pretransition_records=wrong_step_store,
            ),
        )

        late_only_store = [copy.deepcopy(snapshots[1])]
        late_only_manifest = valid_checkpoint_set_manifest(late_only_store)
        self.assertIn(
            "CHECKPOINT_PLAN_ACTION_MISMATCH",
            diagnostics_for(
                late_only_manifest,
                trusted_records=late_only_store,
                pretransition_records=late_only_store,
            ),
        )

        impossible_forward_store = copy.deepcopy(snapshots)
        impossible_forward_record = impossible_forward_store[0]["record"]
        assert isinstance(impossible_forward_record, dict)
        impossible_forward_record["phase"] = "prepared"
        impossible_forward_record["phase_history"] = ["prepared"]
        impossible_forward_record["invocation_state"] = "not_started"
        impossible_forward_manifest = valid_checkpoint_set_manifest(
            impossible_forward_store
        )
        self.assertIn(
            "CHECKPOINT_LIFECYCLE_FRONTIER_MISMATCH",
            diagnostics_for(
                impossible_forward_manifest,
                trusted_records=impossible_forward_store,
                pretransition_records=impossible_forward_store,
            ),
        )

        impossible_reverse_store = copy.deepcopy(snapshots)
        impossible_reverse_record = impossible_reverse_store[0]["record"]
        assert isinstance(impossible_reverse_record, dict)
        impossible_reverse_record["phase"] = "compensated"
        impossible_reverse_record["phase_history"] = [
            "prepared",
            "completed",
            "compensating",
            "compensated",
        ]
        impossible_reverse_record["compensation_authority_kind"] = "automatic_apply"
        impossible_reverse_manifest = valid_checkpoint_set_manifest(
            impossible_reverse_store
        )
        self.assertIn(
            "CHECKPOINT_LIFECYCLE_FRONTIER_MISMATCH",
            diagnostics_for(
                impossible_reverse_manifest,
                trusted_records=impossible_reverse_store,
                pretransition_records=impossible_reverse_store,
            ),
        )

        null_claim_store = copy.deepcopy(snapshots)
        null_claim_record = null_claim_store[-1]["record"]
        assert isinstance(null_claim_record, dict)
        null_claim_record["phase"] = "compensating"
        null_claim_record["phase_history"].append("compensating")
        null_claim_record["compensation_authority_kind"] = "public_compensation"
        null_claim: dict[str, object] = {
            "schema_version": "agent-equipment-compensation-transition-claim/v1",
            "checkpoint_identity": null_claim_record["checkpoint_identity"],
            "compensation_authorization_identity": None,
            "compensation_authorization_digest": None,
            "compensation_nonce": None,
            "transition_claim_identity": "",
            "transition_claim_digest": "",
        }
        null_claim["transition_claim_identity"] = (
            EXECUTION_AUTHORITY._compensation_transition_claim_identity(null_claim)
        )
        null_claim["transition_claim_digest"] = (
            EXECUTION_AUTHORITY._compensation_transition_claim_digest(null_claim)
        )
        null_claim_record["compensation_transition_claim"] = null_claim
        null_claim_manifest = valid_checkpoint_set_manifest(null_claim_store)
        self.assertIn(
            "CHECKPOINT_SET_MEMBERSHIP_MISMATCH",
            diagnostics_for(
                null_claim_manifest,
                trusted_records=null_claim_store,
                pretransition_records=null_claim_store,
            ),
        )

        coordinated_pre_state_store = copy.deepcopy(snapshots)
        coordinated_pre_state = coordinated_pre_state_store[0]["record"]
        assert isinstance(coordinated_pre_state, dict)
        coordinated_pre_state["pre_state"] = {"present": "foreign"}
        coordinated_pre_state["pre_state_digest"] = canonical_digest(
            coordinated_pre_state["pre_state"]
        )
        coordinated_pre_state["checkpoint_identity"] = (
            EXECUTION_AUTHORITY.checkpoint_identity(
                "agent-equipment-checkpoint/v1", coordinated_pre_state
            )
        )
        coordinated_pre_state_manifest = valid_checkpoint_set_manifest(
            coordinated_pre_state_store
        )
        self.assertIn(
            "CHECKPOINT_BINDING_MISMATCH",
            diagnostics_for(
                coordinated_pre_state_manifest,
                trusted_records=coordinated_pre_state_store,
                pretransition_records=coordinated_pre_state_store,
            ),
        )

        resealed_action_set = valid_plan_action_set()
        resealed_payload = resealed_action_set["actions"][0]["action_payload"]
        resealed_payload["desired_state"] = {"route_presence": "absent"}
        resealed_payload["desired_state_digest"] = canonical_digest(
            resealed_payload["desired_state"]
        )
        resealed_payload["action_identity"] = EXECUTION_AUTHORITY._plan_action_identity(
            resealed_payload
        )
        resealed_action_set["actions"][0]["action_digest"] = (
            EXECUTION_AUTHORITY._plan_action_digest(resealed_payload)
        )
        resealed_action_set["action_set_digest"] = (
            EXECUTION_AUTHORITY._plan_action_set_digest(
                resealed_action_set["candidate_identity"],
                resealed_action_set["implementation_manifest_digest"],
                resealed_action_set["plan_digest"],
                resealed_action_set["actions"],
            )
        )
        self.assertIn(
            "PLAN_ACTION_SET_DIGEST_MISMATCH",
            diagnostics_for(manifest, expected_action_set=resealed_action_set),
        )

        for field, value in (
            ("run_identity", "run:sha256:" + "f" * 64),
            ("execution_domain_identity", "execution-domain:fixture/foreign"),
        ):
            with self.subTest(foreign_checkpoint_binding=field):
                foreign_store = copy.deepcopy(snapshots)
                foreign_record = foreign_store[0]["record"]
                assert isinstance(foreign_record, dict)
                foreign_record[field] = value
                foreign_manifest = valid_checkpoint_set_manifest(foreign_store)
                self.assertIn(
                    "CHECKPOINT_BINDING_MISMATCH",
                    diagnostics_for(
                        foreign_manifest,
                        trusted_records=foreign_store,
                        pretransition_records=foreign_store,
                    ),
                )

        self.assertIn(
            "CHECKPOINT_PLAN_ACTION_MISMATCH",
            diagnostics_for(
                manifest,
                expected_action_set=valid_plan_action_set(action_count=1),
            ),
        )

    def test_compensation_derives_checkpoint_digest_from_the_trusted_store(
        self,
    ) -> None:
        snapshots = valid_checkpoint_snapshots()
        checkpoint_set = valid_checkpoint_set_manifest(snapshots)
        authorization = valid_compensation_authorization(checkpoint_set)
        self.assertEqual(
            EXECUTION_AUTHORITY.validate_compensation_authorization(
                authorization,
                **compensation_validation_inputs(
                    authorization, checkpoint_set, snapshots
                ),
            ),
            (),
        )

        incomplete = copy.deepcopy(checkpoint_set)
        incomplete["checkpoints"].pop()
        seal_checkpoint_set_manifest(incomplete)
        inputs = compensation_validation_inputs(authorization, incomplete, snapshots)
        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_compensation_authorization(
                authorization, **inputs
            )
        }
        self.assertIn("CHECKPOINT_SET_MEMBERSHIP_MISMATCH", codes)
        self.assertIn("COMPENSATION_AUTHORIZATION_BINDING_MISMATCH", codes)

    def test_public_compensation_recovery_uses_original_authority_and_ledger_claim(
        self,
    ) -> None:
        original_snapshots = valid_checkpoint_snapshots()
        original_manifest = valid_checkpoint_set_manifest(original_snapshots)
        authorization = valid_compensation_authorization(original_manifest)
        current_snapshots = copy.deepcopy(original_snapshots)
        transitioned = current_snapshots[1]["record"]
        assert isinstance(transitioned, dict)
        transitioned["phase"] = "compensated"
        transitioned["phase_history"] = [
            "prepared",
            "completed",
            "compensating",
            "compensated",
        ]
        attach_public_compensation_claim(transitioned, authorization)
        current_snapshots[1]["durable_generation"] += 10
        current_manifest = valid_checkpoint_set_manifest(
            current_snapshots, store_generation=8
        )

        recovery_inputs = public_recovery_validation_inputs(
            authorization,
            original_manifest,
            original_snapshots,
            current_manifest,
            current_snapshots,
        )
        self.assertEqual(
            EXECUTION_AUTHORITY.validate_public_compensation_recovery(
                authorization, **recovery_inputs
            ),
            (),
        )

        wrong_ledger_inputs = dict(recovery_inputs)
        wrong_ledger_inputs["trusted_compensation_ledger_claim_identity"] = (
            "compensation-ledger-claim:sha256:" + "f" * 64
        )
        self.assertIn(
            "COMPENSATION_RECOVERY_LEDGER_MISMATCH",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_public_compensation_recovery(
                    authorization, **wrong_ledger_inputs
                )
            },
        )

        automatic_snapshots = copy.deepcopy(current_snapshots)
        automatic_record = automatic_snapshots[1]["record"]
        assert isinstance(automatic_record, dict)
        automatic_record["compensation_authority_kind"] = "automatic_apply"
        automatic_record["compensation_transition_claim"] = None
        automatic_manifest = valid_checkpoint_set_manifest(
            automatic_snapshots, store_generation=8
        )
        automatic_inputs = dict(recovery_inputs)
        automatic_inputs.update(
            {
                "current_checkpoint_set_manifest": automatic_manifest,
                "current_checkpoint_records": automatic_snapshots,
                "pretransition_checkpoint_records": copy.deepcopy(automatic_snapshots),
            }
        )
        self.assertIn(
            "COMPENSATION_RECOVERY_DESCENDANT_MISMATCH",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_public_compensation_recovery(
                    authorization, **automatic_inputs
                )
            },
        )

    def test_public_compensation_recovery_covers_every_crash_boundary(self) -> None:
        original_snapshots = valid_checkpoint_snapshots()
        prepared_record = original_snapshots[1]["record"]
        assert isinstance(prepared_record, dict)
        prepared_record["phase"] = "prepared"
        prepared_record["phase_history"] = ["prepared"]
        prepared_record["invocation_state"] = "not_started"
        original_manifest = valid_checkpoint_set_manifest(original_snapshots)
        authorization = valid_compensation_authorization(original_manifest)

        ledger_only_inputs = public_recovery_validation_inputs(
            authorization,
            original_manifest,
            original_snapshots,
            original_manifest,
            copy.deepcopy(original_snapshots),
        )
        self.assertEqual(
            EXECUTION_AUTHORITY.validate_public_compensation_recovery(
                authorization, **ledger_only_inputs
            ),
            (),
        )

        generation_only_snapshots = copy.deepcopy(original_snapshots)
        generation_only_snapshots[1]["durable_generation"] += 1
        same_store_generation_manifest = valid_checkpoint_set_manifest(
            generation_only_snapshots,
            store_generation=original_manifest["checkpoint_store_generation"],
        )
        same_store_generation_inputs = public_recovery_validation_inputs(
            authorization,
            original_manifest,
            original_snapshots,
            same_store_generation_manifest,
            generation_only_snapshots,
        )
        self.assertIn(
            "COMPENSATION_RECOVERY_DESCENDANT_MISMATCH",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_public_compensation_recovery(
                    authorization, **same_store_generation_inputs
                )
            },
        )

        advanced_store_generation_manifest = valid_checkpoint_set_manifest(
            generation_only_snapshots,
            store_generation=original_manifest["checkpoint_store_generation"] + 1,
        )
        advanced_store_generation_inputs = public_recovery_validation_inputs(
            authorization,
            original_manifest,
            original_snapshots,
            advanced_store_generation_manifest,
            generation_only_snapshots,
        )
        self.assertEqual(
            EXECUTION_AUTHORITY.validate_public_compensation_recovery(
                authorization, **advanced_store_generation_inputs
            ),
            (),
        )

        prepared_started_snapshots = copy.deepcopy(original_snapshots)
        prepared_started_record = prepared_started_snapshots[1]["record"]
        assert isinstance(prepared_started_record, dict)
        transition_public_checkpoint(
            prepared_started_record, authorization, "compensating"
        )
        prepared_started_snapshots[1]["durable_generation"] += 1
        prepared_started_manifest = valid_checkpoint_set_manifest(
            prepared_started_snapshots, store_generation=8
        )
        prepared_started_inputs = public_recovery_validation_inputs(
            authorization,
            original_manifest,
            original_snapshots,
            prepared_started_manifest,
            prepared_started_snapshots,
        )
        self.assertEqual(
            EXECUTION_AUTHORITY.validate_public_compensation_recovery(
                authorization, **prepared_started_inputs
            ),
            (),
        )

        stale_generation_snapshots = copy.deepcopy(prepared_started_snapshots)
        stale_generation_snapshots[1]["durable_generation"] = original_snapshots[1][
            "durable_generation"
        ]
        stale_generation_manifest = valid_checkpoint_set_manifest(
            stale_generation_snapshots,
            store_generation=original_manifest["checkpoint_store_generation"],
        )
        stale_generation_inputs = public_recovery_validation_inputs(
            authorization,
            original_manifest,
            original_snapshots,
            stale_generation_manifest,
            stale_generation_snapshots,
        )
        self.assertIn(
            "COMPENSATION_RECOVERY_DESCENDANT_MISMATCH",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_public_compensation_recovery(
                    authorization, **stale_generation_inputs
                )
            },
        )

        forward_intent_snapshots = copy.deepcopy(prepared_started_snapshots)
        forward_intent_record = forward_intent_snapshots[1]["record"]
        assert isinstance(forward_intent_record, dict)
        forward_intent_record["invocation_state"] = "started"
        forward_intent_snapshots[1]["durable_generation"] += 1
        forward_intent_manifest = valid_checkpoint_set_manifest(
            forward_intent_snapshots, store_generation=9
        )
        forward_intent_inputs = public_recovery_validation_inputs(
            authorization,
            original_manifest,
            original_snapshots,
            forward_intent_manifest,
            forward_intent_snapshots,
        )
        self.assertIn(
            "COMPENSATION_RECOVERY_DESCENDANT_MISMATCH",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_public_compensation_recovery(
                    authorization, **forward_intent_inputs
                )
            },
        )

        blocked_snapshots = copy.deepcopy(original_snapshots)
        blocked_record = blocked_snapshots[1]["record"]
        assert isinstance(blocked_record, dict)
        transition_public_checkpoint(
            blocked_record, authorization, "compensation_blocked"
        )
        blocked_snapshots[1]["durable_generation"] += 1
        blocked_manifest = valid_checkpoint_set_manifest(
            blocked_snapshots, store_generation=8
        )
        blocked_inputs = public_recovery_validation_inputs(
            authorization,
            original_manifest,
            original_snapshots,
            blocked_manifest,
            blocked_snapshots,
        )
        self.assertIn(
            "COMPENSATION_RECOVERY_BLOCKED",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_public_compensation_recovery(
                    authorization, **blocked_inputs
                )
            },
        )

        completed_original = valid_checkpoint_snapshots()
        completed_manifest = valid_checkpoint_set_manifest(completed_original)
        completed_authorization = valid_compensation_authorization(completed_manifest)
        out_of_order = copy.deepcopy(completed_original)
        lower_record = out_of_order[0]["record"]
        assert isinstance(lower_record, dict)
        transition_public_checkpoint(
            lower_record, completed_authorization, "compensated"
        )
        out_of_order[0]["durable_generation"] += 1
        out_of_order_manifest = valid_checkpoint_set_manifest(
            out_of_order, store_generation=8
        )
        out_of_order_inputs = public_recovery_validation_inputs(
            completed_authorization,
            completed_manifest,
            completed_original,
            out_of_order_manifest,
            out_of_order,
        )
        self.assertIn(
            "CHECKPOINT_LIFECYCLE_FRONTIER_MISMATCH",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_public_compensation_recovery(
                    completed_authorization, **out_of_order_inputs
                )
            },
        )

    def test_public_compensation_claim_rejects_canonical_foreign_reseal(self) -> None:
        snapshots = valid_checkpoint_snapshots()
        authorization = valid_compensation_authorization()
        inputs = compensation_validation_inputs(authorization)
        record = snapshots[0]["record"]
        assert isinstance(record, dict)
        record["phase"] = "compensating"
        record["phase_history"] = ["prepared", "completed", "compensating"]
        record["compensation_authority_kind"] = "public_compensation"
        claim: dict[str, object] = {
            "schema_version": "agent-equipment-compensation-transition-claim/v1",
            "checkpoint_identity": record["checkpoint_identity"],
            "compensation_authorization_identity": (
                "compensation-authorization:sha256:" + "f" * 64
            ),
            "compensation_authorization_digest": DIGEST_D,
            "compensation_nonce": "compensation-nonce:sha256:" + "e" * 64,
            "transition_claim_identity": "",
            "transition_claim_digest": "",
        }
        claim["transition_claim_identity"] = (
            EXECUTION_AUTHORITY._compensation_transition_claim_identity(claim)
        )
        claim["transition_claim_digest"] = (
            EXECUTION_AUTHORITY._compensation_transition_claim_digest(claim)
        )
        record["compensation_transition_claim"] = claim
        manifest = valid_checkpoint_set_manifest(snapshots)
        inputs.update(
            {
                "checkpoint_set_manifest": manifest,
                "trusted_checkpoint_records": snapshots,
                "pretransition_checkpoint_records": copy.deepcopy(snapshots),
            }
        )
        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_compensation_authorization(
                authorization, **inputs
            )
        }
        self.assertIn("CHECKPOINT_COMPENSATION_CLAIM_MISMATCH", codes)

    def test_compensation_phase_requires_explicit_authority_kind(self) -> None:
        snapshots = valid_checkpoint_snapshots()
        record = snapshots[0]["record"]
        assert isinstance(record, dict)
        record["phase"] = "compensating"
        record["phase_history"] = ["prepared", "completed", "compensating"]
        record["compensation_authority_kind"] = "none"
        manifest = valid_checkpoint_set_manifest(snapshots)
        self.assertFalse(self.validate(manifest))
        authorization = valid_compensation_authorization(manifest)
        inputs = compensation_validation_inputs(authorization, manifest, snapshots)
        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_compensation_authorization(
                authorization, **inputs
            )
        }
        self.assertIn("CHECKPOINT_SET_SCHEMA_INVALID", codes)

    def test_authority_validators_reject_malformed_trusted_checkpoint_collections(
        self,
    ) -> None:
        authorization = valid_compensation_authorization()
        compensation_inputs = compensation_validation_inputs(authorization)
        release_inputs = release_validation_inputs()
        terminal = release_inputs["run_terminal_record"]
        terminal_input_fields = {
            "checkpoint_set_manifest",
            "expected_apply_authorization_identity",
            "expected_apply_authorization_digest",
            "expected_execution_domain_identity",
            "expected_execution_nonce",
            "expected_run_identity",
            "authoritative_plan_action_set",
            "expected_plan_action_set_digest",
            "expected_candidate_identity",
            "expected_implementation_manifest_digest",
            "expected_plan_digest",
            "trusted_checkpoint_store_generation",
            "trusted_checkpoint_records",
            "authoritative_captured_state",
            "expected_captured_state_identity",
            "expected_captured_state_digest",
            "capture_observation_authority_set",
            "expected_capture_observation_authority_set_identity",
            "expected_capture_observation_authority_set_digest",
            "prepared_action_authority_set",
            "expected_prepared_action_authority_set_identity",
            "expected_prepared_action_authority_set_digest",
        }
        terminal_inputs = {
            key: value
            for key, value in release_inputs.items()
            if key in terminal_input_fields
        }

        for malformed_records in (object(), "not-a-checkpoint-sequence"):
            with self.subTest(
                validator="compensation",
                records_type=type(malformed_records).__name__,
            ):
                malformed_inputs = dict(compensation_inputs)
                malformed_inputs["trusted_checkpoint_records"] = malformed_records
                diagnostics = EXECUTION_AUTHORITY.validate_compensation_authorization(
                    authorization, **malformed_inputs
                )
                self.assertIn(
                    "CHECKPOINT_SET_MEMBERSHIP_MISMATCH",
                    {diagnostic.code for diagnostic in diagnostics},
                )

            with self.subTest(
                validator="terminal",
                records_type=type(malformed_records).__name__,
            ):
                malformed_inputs = dict(terminal_inputs)
                malformed_inputs["trusted_checkpoint_records"] = malformed_records
                diagnostics = EXECUTION_AUTHORITY.validate_run_terminal_record(
                    terminal, **malformed_inputs
                )
                self.assertIn(
                    "CHECKPOINT_SET_MEMBERSHIP_MISMATCH",
                    {diagnostic.code for diagnostic in diagnostics},
                )

    def test_raw_authority_boundary_rejects_ambiguous_or_unbounded_input(self) -> None:
        authorization = valid_apply_authorization()
        seal_apply_authorization(authorization)
        valid_bytes = json.dumps(authorization).encode("utf-8")
        parsed, diagnostics = EXECUTION_AUTHORITY.parse_execution_authority_bytes(
            valid_bytes
        )
        self.assertEqual(diagnostics, ())
        self.assertEqual(parsed, authorization)

        exact_limit_bytes = valid_bytes + b" " * (
            EXECUTION_AUTHORITY.MAX_EXECUTION_AUTHORITY_BYTES - len(valid_bytes)
        )
        parsed, diagnostics = EXECUTION_AUTHORITY.parse_execution_authority_bytes(
            exact_limit_bytes
        )
        self.assertEqual(diagnostics, ())
        self.assertEqual(parsed, authorization)

        cases = {
            "oversized bytes": b" "
            * (EXECUTION_AUTHORITY.MAX_EXECUTION_AUTHORITY_BYTES + 1),
            "non utf8": b"\xff",
            "duplicate key": valid_bytes.replace(
                b'"schema_version":',
                b'"schema_version":"foreign","schema_version":',
                1,
            ),
            "NaN": valid_bytes.replace(b'"command": "apply"', b'"command": NaN'),
            "Infinity": valid_bytes.replace(
                b'"command": "apply"', b'"command": Infinity'
            ),
        }
        for label, raw in cases.items():
            with self.subTest(label=label):
                parsed, diagnostics = (
                    EXECUTION_AUTHORITY.parse_execution_authority_bytes(raw)
                )
                self.assertIsNone(parsed)
                self.assertTrue(diagnostics)

        original_schema_valid = EXECUTION_AUTHORITY._schema_valid
        original_credential_scan = EXECUTION_AUTHORITY.contains_literal_credential
        original_canonical_digest = EXECUTION_AUTHORITY.canonical_digest

        def forbidden_after_oversize(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("oversized bytes reached parsed-object processing")

        try:
            EXECUTION_AUTHORITY._schema_valid = forbidden_after_oversize
            EXECUTION_AUTHORITY.contains_literal_credential = forbidden_after_oversize
            EXECUTION_AUTHORITY.canonical_digest = forbidden_after_oversize
            parsed, diagnostics = EXECUTION_AUTHORITY.parse_execution_authority_bytes(
                b" " * (EXECUTION_AUTHORITY.MAX_EXECUTION_AUTHORITY_BYTES + 1)
            )
            self.assertIsNone(parsed)
            self.assertEqual(
                {diagnostic.code for diagnostic in diagnostics},
                {"EXECUTION_AUTHORITY_BYTES_INVALID"},
            )
        finally:
            EXECUTION_AUTHORITY._schema_valid = original_schema_valid
            EXECUTION_AUTHORITY.contains_literal_credential = original_credential_scan
            EXECUTION_AUTHORITY.canonical_digest = original_canonical_digest

        oversized_string = copy.deepcopy(authorization)
        oversized_string["issuer_identity"] = "authority:" + "a" * 256
        parsed, diagnostics = EXECUTION_AUTHORITY.parse_execution_authority_bytes(
            json.dumps(oversized_string).encode("utf-8")
        )
        self.assertIsNone(parsed)
        self.assertEqual(
            {diagnostic.code for diagnostic in diagnostics},
            {"EXECUTION_AUTHORITY_SCHEMA_INVALID"},
        )

        excessive_fraction = copy.deepcopy(authorization)
        excessive_fraction["issued_at"] = "2026-08-13T07:00:00." + "1" * 5000 + "Z"
        parsed, diagnostics = EXECUTION_AUTHORITY.parse_execution_authority_bytes(
            json.dumps(excessive_fraction).encode("utf-8")
        )
        self.assertIsNone(parsed)
        self.assertEqual(
            {diagnostic.code for diagnostic in diagnostics},
            {"EXECUTION_AUTHORITY_SCHEMA_INVALID"},
        )

    def test_compensation_authorization_is_closed_and_independently_trusted(
        self,
    ) -> None:
        authorization = valid_compensation_authorization()
        self.assertTrue(self.validate(authorization))
        identity_payload = copy.deepcopy(authorization)
        identity_payload.pop("compensation_authorization_identity")
        self.assertEqual(
            authorization["compensation_authorization_identity"],
            "compensation-authorization:" + canonical_digest(identity_payload),
        )
        self.assertEqual(
            EXECUTION_AUTHORITY.validate_compensation_authorization(
                authorization, **compensation_validation_inputs(authorization)
            ),
            (),
        )
        bindings = authorization["bindings"]
        assert isinstance(bindings, dict)
        self.assertEqual(
            EXECUTION_AUTHORITY.compensation_ledger_claim_identity(
                bindings["execution_domain_identity"],
                authorization["compensation_nonce"],
            ),
            "compensation-ledger-claim:sha256:"
            "657d939e28c931af52c8d160eb199e058bf2db98817412581a6ec7bba5e88632",
        )

        for field in tuple(bindings):
            with self.subTest(field=field):
                candidate = copy.deepcopy(authorization)
                del candidate["bindings"][field]
                self.assertFalse(self.validate(candidate))

    def test_compensation_authorization_rejects_resealing_and_forward_apply(
        self,
    ) -> None:
        authorization = valid_compensation_authorization()
        trusted_inputs = compensation_validation_inputs(authorization)
        mutations = {
            "apply authorization": lambda candidate: candidate["bindings"].update(
                {"apply_authorization_digest": DIGEST_A}
            ),
            "execution domain": lambda candidate: candidate["bindings"].update(
                {"execution_domain_identity": "execution-domain:fixture/other"}
            ),
            "run": lambda candidate: candidate["bindings"].update(
                {"run_identity": "run:sha256:" + "a" * 64}
            ),
            "checkpoint set": lambda candidate: candidate["bindings"].update(
                {"checkpoint_set_digest": DIGEST_A}
            ),
            "action set": lambda candidate: candidate["bindings"].update(
                {"plan_action_set_digest": DIGEST_A}
            ),
            "nonce": lambda candidate: candidate.update(
                {"compensation_nonce": "compensation-nonce:sha256:" + "a" * 64}
            ),
            "issuer": lambda candidate: candidate.update(
                {"issuer_identity": "authority:fixture/other"}
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                candidate = copy.deepcopy(authorization)
                mutate(candidate)
                seal_compensation_authorization(candidate)
                codes = {
                    diagnostic.code
                    for diagnostic in EXECUTION_AUTHORITY.validate_compensation_authorization(
                        candidate, **trusted_inputs
                    )
                }
                self.assertIn("COMPENSATION_AUTHORIZATION_BINDING_MISMATCH", codes)
                self.assertIn("COMPENSATION_AUTHORIZATION_TRUST_MISMATCH", codes)
                self.assertIn("COMPENSATION_AUTHORIZATION_DIGEST_MISMATCH", codes)

        for label, trusted_now in (
            ("not yet valid", datetime(2026, 8, 13, 8, 59, 59, tzinfo=timezone.utc)),
            ("expired", datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc)),
        ):
            with self.subTest(label=label):
                inputs = compensation_validation_inputs(authorization)
                inputs["trusted_now"] = trusted_now
                codes = {
                    diagnostic.code
                    for diagnostic in EXECUTION_AUTHORITY.validate_compensation_authorization(
                        authorization, **inputs
                    )
                }
                self.assertIn("COMPENSATION_AUTHORIZATION_TIME_INVALID", codes)

        apply_authorization = valid_apply_authorization()
        seal_apply_authorization(apply_authorization)
        diagnostics = EXECUTION_AUTHORITY.validate_compensation_authorization(
            apply_authorization, **trusted_inputs
        )
        self.assertEqual(
            [diagnostic.code for diagnostic in diagnostics],
            ["COMPENSATION_AUTHORIZATION_SCHEMA_INVALID"],
        )

        candidate = copy.deepcopy(authorization)
        candidate["command"] = "apply"
        self.assertFalse(self.validate(candidate))

        apply_inputs = apply_validation_inputs(apply_authorization)
        diagnostics = EXECUTION_AUTHORITY.validate_apply_authorization(
            authorization, **apply_inputs
        )
        self.assertEqual(
            [diagnostic.code for diagnostic in diagnostics],
            ["APPLY_AUTHORIZATION_SCHEMA_INVALID"],
        )

    def test_apply_authorization_requires_command_time_run_and_replay_identity(
        self,
    ) -> None:
        authorization = valid_apply_authorization()
        required_fields = (
            "authorization_identity",
            "issuer_identity",
            "issued_at",
            "not_before",
            "expires_at",
            "execution_nonce",
            "run_identity",
            "execution_domain_identity",
            "command",
        )
        for field in required_fields:
            with self.subTest(field=field):
                candidate = copy.deepcopy(authorization)
                del candidate[field]
                self.assertFalse(self.validate(candidate))

        candidate = copy.deepcopy(authorization)
        candidate["command"] = "audit"
        self.assertFalse(self.validate(candidate))

    def test_release_receipt_binds_launcher_authority_and_one_cas_archive(self) -> None:
        receipt = valid_release_receipt()
        self.assertTrue(self.validate(receipt))

        payload_fields = tuple(receipt["payload"])
        for field in payload_fields:
            with self.subTest(field=field):
                candidate = copy.deepcopy(receipt)
                del candidate["payload"][field]
                self.assertFalse(self.validate(candidate))

        invalid_archive_values = (
            ("compare_token", "present"),
            ("committed_generation", 0),
            ("committed_generation", 2),
        )
        for field, value in invalid_archive_values:
            with self.subTest(field=field, value=value):
                candidate = copy.deepcopy(receipt)
                candidate["payload"]["archive_destination"][field] = value
                self.assertFalse(self.validate(candidate))

    def test_release_archive_manifest_and_receipt_bind_exact_bytes_and_execution(
        self,
    ) -> None:
        archive = valid_release_archive_manifest()
        receipt = valid_release_receipt(archive)
        self.assertEqual(
            archive["archive_identity"],
            "release-archive:" + canonical_digest(archive["payload"]),
        )
        unsigned_archive = copy.deepcopy(archive)
        unsigned_archive.pop("archive_manifest_digest")
        self.assertEqual(
            archive["archive_manifest_digest"], canonical_digest(unsigned_archive)
        )
        self.assertEqual(
            receipt["receipt_identity"],
            "release-receipt:" + canonical_digest(receipt["payload"]),
        )
        payload = archive["payload"]
        assert isinstance(payload, dict)
        trusted_execution = copy.deepcopy(payload["execution_binding"])
        release_inputs = release_validation_inputs(archive)
        trusted_byte_digests = copy.deepcopy(payload["archived_document_byte_digests"])
        self.assertNotEqual(
            trusted_byte_digests["apply_authorization_bytes_digest"],
            trusted_execution["apply_authorization_digest"],
        )
        destination = payload["archive_destination"]
        assert isinstance(destination, dict)

        archive_diagnostics = EXECUTION_AUTHORITY.validate_release_archive_manifest(
            archive, **release_inputs
        )
        self.assertEqual(archive_diagnostics, ())

        missing_capture_bytes_digest = copy.deepcopy(archive)
        del missing_capture_bytes_digest["payload"]["archived_document_byte_digests"][
            "capture_observation_authority_set_bytes_digest"
        ]
        self.assertFalse(self.validate(missing_capture_bytes_digest))

        for field, malformed_bytes in (
            ("capture_observation_authority_set_bytes", b"{}"),
            ("prepared_action_authority_set_bytes", "not-bytes"),
            ("checkpoint_set_manifest_bytes", bytearray(b"{}")),
            ("run_terminal_record_bytes", memoryview(b"{}")),
        ):
            with self.subTest(malformed_exact_bytes=field):
                malformed_inputs = dict(release_inputs)
                malformed_inputs[field] = malformed_bytes
                codes = {
                    diagnostic.code
                    for diagnostic in EXECUTION_AUTHORITY.validate_release_archive_manifest(
                        archive, **malformed_inputs
                    )
                }
                self.assertIn("RELEASE_EVIDENCE_BYTES_MISMATCH", codes)
                self.assertIn("ARCHIVED_DOCUMENT_BYTES_MISMATCH", codes)

        receipt_inputs = dict(release_inputs)
        receipt_inputs["release_archive_manifest"] = archive
        receipt_diagnostics = EXECUTION_AUTHORITY.validate_release_receipt(
            receipt, **receipt_inputs
        )
        self.assertEqual(receipt_diagnostics, ())
        malformed_receipt_inputs = dict(receipt_inputs)
        malformed_receipt_inputs["capture_observation_authority_set_bytes"] = b"{}"
        receipt_codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_release_receipt(
                receipt,
                **malformed_receipt_inputs,
            )
        }
        self.assertIn("RELEASE_EVIDENCE_BYTES_MISMATCH", receipt_codes)
        self.assertIn("ARCHIVED_DOCUMENT_BYTES_MISMATCH", receipt_codes)

        incomplete_inputs = dict(release_inputs)
        incomplete_inputs["trusted_checkpoint_records"] = release_inputs[
            "trusted_checkpoint_records"
        ][:-1]
        incomplete_checkpoint_set = valid_checkpoint_set_manifest(
            incomplete_inputs["trusted_checkpoint_records"]
        )
        incomplete_inputs["checkpoint_set_manifest"] = incomplete_checkpoint_set
        incomplete_inputs["checkpoint_set_manifest_bytes"] = canonical_bytes(
            incomplete_checkpoint_set
        )
        incomplete_terminal = valid_run_terminal_record(incomplete_checkpoint_set)
        incomplete_inputs["run_terminal_record"] = incomplete_terminal
        incomplete_inputs["run_terminal_record_bytes"] = canonical_bytes(
            incomplete_terminal
        )
        self.assertIn(
            "RUN_TERMINAL_CHECKPOINT_STATE_MISMATCH",
            {
                diagnostic.code
                for diagnostic in EXECUTION_AUTHORITY.validate_release_archive_manifest(
                    archive, **incomplete_inputs
                )
            },
        )

        forged_archive = copy.deepcopy(archive)
        forged_archive["payload"]["execution_binding"]["run_identity"] = (
            "run:sha256:" + "8" * 64
        )
        forged_archive["archive_identity"] = "release-archive:" + canonical_digest(
            forged_archive["payload"]
        )
        unsigned = copy.deepcopy(forged_archive)
        del unsigned["archive_manifest_digest"]
        forged_archive["archive_manifest_digest"] = canonical_digest(unsigned)
        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_release_archive_manifest(
                forged_archive, **release_inputs
            )
        }
        self.assertIn("RELEASE_ARCHIVE_AUTHORITY_MISMATCH", codes)

        foreign_domain_archive = copy.deepcopy(archive)
        foreign_domain_archive["payload"]["execution_binding"][
            "execution_domain_identity"
        ] = "execution-domain:fixture/other-ledger-v1"
        foreign_domain_archive["archive_identity"] = (
            "release-archive:" + canonical_digest(foreign_domain_archive["payload"])
        )
        unsigned = copy.deepcopy(foreign_domain_archive)
        del unsigned["archive_manifest_digest"]
        foreign_domain_archive["archive_manifest_digest"] = canonical_digest(unsigned)
        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_release_archive_manifest(
                foreign_domain_archive, **release_inputs
            )
        }
        self.assertIn("RELEASE_ARCHIVE_AUTHORITY_MISMATCH", codes)

        forged_bytes = copy.deepcopy(archive)
        forged_bytes["payload"]["archived_document_byte_digests"][
            "evidence_bundle_bytes_digest"
        ] = DIGEST_A
        forged_bytes["archive_identity"] = "release-archive:" + canonical_digest(
            forged_bytes["payload"]
        )
        unsigned = copy.deepcopy(forged_bytes)
        del unsigned["archive_manifest_digest"]
        forged_bytes["archive_manifest_digest"] = canonical_digest(unsigned)
        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_release_archive_manifest(
                forged_bytes, **release_inputs
            )
        }
        self.assertIn("ARCHIVED_DOCUMENT_BYTES_MISMATCH", codes)

        forged_receipt = copy.deepcopy(receipt)
        forged_receipt["payload"]["execution_binding"]["run_identity"] = (
            "run:sha256:" + "8" * 64
        )
        forged_receipt["receipt_identity"] = "release-receipt:" + canonical_digest(
            forged_receipt["payload"]
        )
        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_release_receipt(
                forged_receipt, **receipt_inputs
            )
        }
        self.assertIn("RELEASE_RECEIPT_AUTHORITY_MISMATCH", codes)

        foreign_domain_receipt = copy.deepcopy(receipt)
        foreign_domain_receipt["payload"]["execution_binding"][
            "execution_domain_identity"
        ] = "execution-domain:fixture/other-ledger-v1"
        foreign_domain_receipt["receipt_identity"] = (
            "release-receipt:" + canonical_digest(foreign_domain_receipt["payload"])
        )
        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_release_receipt(
                foreign_domain_receipt, **receipt_inputs
            )
        }
        self.assertIn("RELEASE_RECEIPT_AUTHORITY_MISMATCH", codes)

    def test_release_authority_uses_shared_public_data_policy(self) -> None:
        archive = valid_release_archive_manifest()
        payload = archive["payload"]
        assert isinstance(payload, dict)
        destination = payload["archive_destination"]
        assert isinstance(destination, dict)
        self.assertFalse(EXECUTION_AUTHORITY.contains_literal_credential(archive))

        archive["payload"]["archive_destination"]["store_key"] = (
            "archive-key:ghp_" + "A" * 24
        )
        archive["archive_identity"] = "release-archive:" + canonical_digest(
            archive["payload"]
        )
        unsigned = copy.deepcopy(archive)
        del unsigned["archive_manifest_digest"]
        archive["archive_manifest_digest"] = canonical_digest(unsigned)
        diagnostics = EXECUTION_AUTHORITY.validate_release_archive_manifest(
            archive, **release_validation_inputs(valid_release_archive_manifest())
        )
        self.assertEqual(
            {diagnostic.code for diagnostic in diagnostics},
            {"RELEASE_ARCHIVE_LITERAL_SECRET"},
        )

    def test_archive_byte_digest_is_distinct_from_authorization_canonical_digest(
        self,
    ) -> None:
        authorization = valid_apply_authorization()
        canonical_authorization_digest = seal_apply_authorization(authorization)
        compact_bytes = json.dumps(
            authorization,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        pretty_bytes = json.dumps(
            authorization,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        compact_digest = byte_digest(compact_bytes)
        pretty_digest = byte_digest(pretty_bytes)
        self.assertEqual(compact_digest, canonical_authorization_digest)
        self.assertNotEqual(pretty_digest, canonical_authorization_digest)

        archive = valid_release_archive_manifest()
        payload = archive["payload"]
        assert isinstance(payload, dict)
        destination = payload["archive_destination"]
        assert isinstance(destination, dict)
        payload["archived_document_byte_digests"][
            "apply_authorization_bytes_digest"
        ] = compact_digest
        archive["archive_identity"] = "release-archive:" + canonical_digest(payload)
        unsigned = copy.deepcopy(archive)
        del unsigned["archive_manifest_digest"]
        archive["archive_manifest_digest"] = canonical_digest(unsigned)
        expected_byte_digests = copy.deepcopy(payload["archived_document_byte_digests"])
        expected_byte_digests["apply_authorization_bytes_digest"] = pretty_digest

        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_release_archive_manifest(
                archive,
                **{
                    **release_validation_inputs(archive),
                    "expected_archived_document_byte_digests": {
                        key: value
                        for key, value in expected_byte_digests.items()
                        if key
                        not in {
                            "checkpoint_set_manifest_bytes_digest",
                            "run_terminal_record_bytes_digest",
                        }
                    },
                },
            )
        }
        self.assertIn("ARCHIVED_DOCUMENT_BYTES_MISMATCH", codes)

    def test_source_shape_keeps_audit_candidate_and_release_authority_separate(
        self,
    ) -> None:
        handoff = (ROOT / "docs/agent-equipment/IMPLEMENTATION_HANDOFF.md").read_text()
        self.assertIn("home/run_onchange_after_audit-agent-equipment.zsh.tmpl", handoff)
        self.assertNotIn(
            "home/run_onchange_after_reconcile-agent-equipment.zsh.tmpl", handoff
        )
        self.assertIn(
            "agent-equipment-release-authority/src/executable_agent-equipment-release",
            handoff,
        )
        self.assertIn(
            "/usr/local/libexec/agent-equipment-release/v1/agent-equipment-release",
            handoff,
        )

    def test_runtime_gate_and_external_authority_precede_every_mutation(self) -> None:
        architecture = (ROOT / "docs/agent-equipment/ARCHITECTURE.md").read_text()
        handoff = (ROOT / "docs/agent-equipment/IMPLEMENTATION_HANDOFF.md").read_text()
        migration = (ROOT / "docs/agent-equipment/MIGRATION.md").read_text()

        for document in (architecture, handoff, migration):
            with self.subTest(document=document[:40]):
                self.assertIn("CPython 3.12", document)
                self.assertIn("trusted_apply_authorization_digest", document)
                self.assertRegex(
                    document, r"before\s+the\s+first\s+action\s+checkpoint"
                )

        self.assertIn("authorization ledger", architecture)
        self.assertIn("candidate-independent release launcher", architecture)


if __name__ == "__main__":
    unittest.main()
