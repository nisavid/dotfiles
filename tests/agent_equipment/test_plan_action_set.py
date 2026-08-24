from __future__ import annotations

import json
import unittest
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from agent_equipment import _json_schema as json_schema_module
from agent_equipment import plan_action_set as plan_action_set_module
from agent_equipment.canonical import canonical_json_bytes, canonical_json_sha256
from agent_equipment.model import PlanNode, ValidatedPlan, freeze_json, thaw_json
from agent_equipment.plan_action_set import (
    MAX_PLAN_ACTION_SET_BYTES,
    AdmittedPlanActionSet,
    PlanActionSetRejection,
    PlanActionSetTrust,
    admit_plan_action_set,
)
from scripts.agent_equipment_captured_state import (
    plan_action_digest,
    plan_action_identity,
    plan_action_set_digest,
)

ROOT = Path(__file__).resolve().parents[2]
PLAN_ACTION_SET_FIXTURE = (
    ROOT / "tests/fixtures/agent-equipment/schema/valid-plan-action-set.json"
)


def _valid_plan_and_action_set() -> tuple[ValidatedPlan, dict[str, object]]:
    document = json.loads(PLAN_ACTION_SET_FIXTURE.read_text(encoding="utf-8"))
    actions = document["actions"]
    assert isinstance(actions, list) and len(actions) == 1
    evidence = actions[0]
    assert isinstance(evidence, dict)
    payload = evidence["action_payload"]
    assert isinstance(payload, dict)

    route_record = {
        "provider": payload["provider"],
        "control_owner": "reconciler_owned",
        "activation_group": payload["activation_group"],
        "component_controls": [],
        "secret_references": payload["secret_references"],
    }
    payload["route_digest"] = canonical_json_sha256(route_record)
    mutation_definition = freeze_json(
        {
            "candidate_identity": payload["candidate_identity"],
            "implementation_manifest_digest": payload[
                "implementation_manifest_digest"
            ],
            "catalog_digest": payload["catalog_digest"],
            "lock_digest": payload["lock_digest"],
            "capability_identity": payload["capability_identity"],
            "capability_digest": payload["capability_digest"],
            "manager_version_evidence_digest": payload[
                "manager_version_evidence_digest"
            ],
            "adapter_identity": payload["adapter_identity"],
            "adapter_version": payload["adapter_version"],
            "harness": payload["harness"],
            "route_identity": payload["route_identity"],
            "route_digest": payload["route_digest"],
            "route_record": route_record,
            "equipment_identities": payload["equipment_identities"],
            "controlled_equipment_identities": payload[
                "controlled_equipment_identities"
            ],
            "activation_group": payload["activation_group"],
            "surface_scope": payload["surface_scope"],
            "operation": payload["operation"],
            "operation_disposition": payload["operation_disposition"],
            "desired_state": payload["desired_state"],
            "desired_state_digest": payload["desired_state_digest"],
            "secret_references": payload["secret_references"],
        }
    )
    final_definition = freeze_json({"purpose": "final_coverage"})
    candidate_identity = str(payload["candidate_identity"])
    implementation_digest = str(payload["implementation_manifest_digest"])
    catalog_digest = str(payload["catalog_digest"])
    lock_digest = str(payload["lock_digest"])
    preimage = freeze_json(
        {
            "schema_version": "agent-equipment-plan-preimage/v1",
            "candidate_identity": candidate_identity,
            "implementation_manifest_digest": implementation_digest,
            "catalog_digest": catalog_digest,
            "lock_digest": lock_digest,
            "inventory_digest": "sha256:" + "5" * 64,
            "capability_set_digest": "sha256:" + "6" * 64,
            "nodes": [
                {
                    "ordinal": 0,
                    "kind": "mutation",
                    "definition": mutation_definition,
                },
                {
                    "ordinal": 1,
                    "kind": "verification",
                    "definition": final_definition,
                },
            ],
            "edges": [[0, 1]],
        }
    )
    plan_digest = canonical_json_sha256(preimage)
    payload.update(
        {
            "action_identity": "action:pending",
            "ordinal": 0,
            "candidate_identity": candidate_identity,
            "implementation_manifest_digest": implementation_digest,
            "catalog_digest": catalog_digest,
            "lock_digest": lock_digest,
            "plan_digest": plan_digest,
        }
    )
    preconditions = payload["preconditions"]
    assert isinstance(preconditions, dict)
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
        preconditions[field] = payload[field]
    payload["action_identity"] = plan_action_identity(payload)
    evidence["action_digest"] = plan_action_digest(payload)
    document.update(
        {
            "candidate_identity": candidate_identity,
            "implementation_manifest_digest": implementation_digest,
            "plan_digest": plan_digest,
        }
    )
    document["action_set_digest"] = plan_action_set_digest(
        candidate_identity,
        implementation_digest,
        plan_digest,
        actions,
    )
    mutation_identity = str(payload["action_identity"])
    final_identity = "verification:" + canonical_json_sha256(
        {
            "plan_digest": plan_digest,
            "ordinal": 1,
            "semantic_definition_digest": canonical_json_sha256(final_definition),
            "predecessor_identities": (mutation_identity,),
        }
    )
    plan = ValidatedPlan(
        nodes=(
            PlanNode(
                key="mutation:fixture",
                kind="mutation",
                ordinal=0,
                identity=mutation_identity,
                dependencies=(),
                definition=mutation_definition,
            ),
            PlanNode(
                key="verification:final",
                kind="verification",
                ordinal=1,
                identity=final_identity,
                dependencies=(mutation_identity,),
                definition=final_definition,
            ),
        ),
        edges=((mutation_identity, final_identity),),
        digest=plan_digest,
        preimage=preimage,
    )
    return plan, document


def _rebuild_plan_for_document(
    original: ValidatedPlan,
    document: dict[str, object],
    mutation_definition: dict[str, object],
) -> ValidatedPlan:
    """Rebuild trusted plan coordinates after a test changes one definition."""

    actions = document["actions"]
    assert isinstance(actions, list) and len(actions) == 1
    evidence = actions[0]
    assert isinstance(evidence, dict)
    payload = evidence["action_payload"]
    assert isinstance(payload, dict)
    preimage = thaw_json(original.preimage)
    assert isinstance(preimage, dict)
    nodes = preimage["nodes"]
    assert isinstance(nodes, list)
    mutation_preimage = nodes[0]
    assert isinstance(mutation_preimage, dict)
    mutation_preimage["definition"] = mutation_definition
    frozen_preimage = freeze_json(preimage)
    assert isinstance(frozen_preimage, type(original.preimage))
    plan_digest = canonical_json_sha256(frozen_preimage)
    payload["plan_digest"] = plan_digest
    preconditions = payload["preconditions"]
    assert isinstance(preconditions, dict)
    preconditions["plan_digest"] = plan_digest
    payload["action_identity"] = plan_action_identity(payload)
    evidence["action_digest"] = plan_action_digest(payload)
    document["plan_digest"] = plan_digest
    document["action_set_digest"] = plan_action_set_digest(
        str(document["candidate_identity"]),
        str(document["implementation_manifest_digest"]),
        plan_digest,
        actions,
    )
    mutation_identity = str(payload["action_identity"])
    final = original.nodes[1]
    final_identity = "verification:" + canonical_json_sha256(
        {
            "plan_digest": plan_digest,
            "ordinal": final.ordinal,
            "semantic_definition_digest": canonical_json_sha256(final.definition),
            "predecessor_identities": (mutation_identity,),
        }
    )
    frozen_definition = freeze_json(mutation_definition)
    assert isinstance(frozen_definition, type(original.nodes[0].definition))
    return ValidatedPlan(
        nodes=(
            PlanNode(
                key=original.nodes[0].key,
                kind="mutation",
                ordinal=0,
                identity=mutation_identity,
                dependencies=(),
                definition=frozen_definition,
            ),
            PlanNode(
                key=final.key,
                kind=final.kind,
                ordinal=final.ordinal,
                identity=final_identity,
                dependencies=(mutation_identity,),
                definition=final.definition,
            ),
        ),
        edges=((mutation_identity, final_identity),),
        digest=plan_digest,
        preimage=frozen_preimage,
    )


def _replace_target(target: dict[str, object], **changes: object) -> None:
    target.update(changes)
    identity_payload = {
        "surface_kind": target.get("surface_kind"),
        "locator": target.get("locator"),
    }
    if "equipment_identity" in target:
        identity_payload["equipment_identity"] = target.get("equipment_identity")
    target["target_identity"] = "target:" + canonical_json_sha256(
        identity_payload
    )


def _configure_desired_state(
    provider: dict[str, object],
    controls: list[dict[str, object]],
) -> dict[str, object]:
    desired: dict[str, object] = {
        "configuration": {
            "status": "desired",
            "digest": canonical_json_sha256(
                {"provider": provider, "component_controls": controls}
            ),
        }
    }
    if controls:
        desired["component_states"] = sorted(
            deepcopy(controls), key=lambda control: str(control["equipment_identity"])
        )
    return desired


def _set_operation_desired_state(
    payload: dict[str, object],
    operation: str,
    provider: dict[str, object],
    controls: list[dict[str, object]],
) -> None:
    desired_state = {
        "install": {"route_presence": "present"},
        "configure": _configure_desired_state(provider, controls),
        "enable": {"enablement": "enabled"},
        "disable": {"enablement": "disabled"},
        "remove": {"route_presence": "absent"},
        "restore": {"route_presence": "present"},
    }.get(operation, {"route_presence": "present"})
    payload["desired_state"] = desired_state
    payload["desired_state_digest"] = canonical_json_sha256(desired_state)


def _direct_mcp_plan_and_action_set(
    harness: str,
    operation: str = "configure",
    surface_rule: str = "route_and_equipment_identity",
) -> tuple[ValidatedPlan, dict[str, object]]:
    plan, document = _valid_plan_and_action_set()
    actions = document["actions"]
    assert isinstance(actions, list)
    evidence = actions[0]
    assert isinstance(evidence, dict)
    payload = evidence["action_payload"]
    assert isinstance(payload, dict)
    provider = {
        "kind": "direct_mcp",
        "server_name": "context7",
        "transport": "stdio",
        "command": "npx",
        "arguments": [{"literal": "context7"}],
    }
    source, root = {
        "claude": ("settings", "mcpServers"),
        "codex": ("config", "mcp_servers"),
        "cursor": ("config", "mcpServers"),
    }[harness]
    route_identity = f"route:fixture/{harness}-direct-mcp"
    surface = (
        f"surface:{route_identity}"
        if surface_rule == "route_identity"
        else f"surface:{route_identity}/mcp:fixture/context7"
    )
    target = {
        "target_identity": "",
        "write_surface_identity": surface,
        "surface_kind": "mcp_selection",
        "equipment_identity": "mcp:fixture/context7",
        "locator": {
            "owner": harness,
            "source": source,
            "key_path": [root, "context7"],
        },
    }
    _replace_target(target)
    route_record = {
        "provider": provider,
        "control_owner": "reconciler_owned",
        "activation_group": payload["activation_group"],
        "component_controls": [],
        "secret_references": [],
    }
    route_digest = canonical_json_sha256(route_record)
    _set_operation_desired_state(payload, operation, provider, [])
    payload.update(
        {
            "harness": harness,
            "route_identity": route_identity,
            "route_digest": route_digest,
            "provider": provider,
            "equipment_identities": ["mcp:fixture/context7"],
            "controlled_equipment_identities": [],
            "surface_scope": [surface],
            "write_targets": [target],
            "operation": operation,
            "secret_references": [],
            "verification_dependencies": [],
        }
    )
    preconditions = payload["preconditions"]
    assert isinstance(preconditions, dict)
    preconditions.update(
        {
            "route_digest": route_digest,
            "surface_scope": [surface],
        }
    )
    definition = thaw_json(plan.nodes[0].definition)
    assert isinstance(definition, dict)
    for field in (
        "harness",
        "route_identity",
        "route_digest",
        "equipment_identities",
        "controlled_equipment_identities",
        "surface_scope",
        "operation",
        "desired_state",
        "desired_state_digest",
        "secret_references",
    ):
        definition[field] = deepcopy(payload[field])
    definition["route_record"] = route_record
    return _rebuild_plan_for_document(plan, document, definition), document


def _claude_skill_plan_and_action_set(
    provider_kind: str,
    operation: str,
) -> tuple[ValidatedPlan, dict[str, object]]:
    plan, document = _valid_plan_and_action_set()
    actions = document["actions"]
    assert isinstance(actions, list)
    evidence = actions[0]
    assert isinstance(evidence, dict)
    payload = evidence["action_payload"]
    assert isinstance(payload, dict)
    targets = payload["write_targets"]
    assert isinstance(targets, list)
    skill_target = next(
        target
        for target in targets
        if isinstance(target, dict)
        and target.get("surface_kind") == "claude_skill_entry"
    )
    provider = (
        payload["provider"]
        if provider_kind == "native_plugin"
        else {"kind": "standalone_skill", "canonical_root": "agents_skills"}
    )
    route_identity = f"route:fixture/claude-{provider_kind}"
    surface = f"surface:{route_identity}/skill:fixture/example"
    _replace_target(skill_target, write_surface_identity=surface)
    dependencies = payload["verification_dependencies"]
    assert isinstance(dependencies, list) and len(dependencies) == 1
    dependency = dependencies[0]
    assert isinstance(dependency, dict)
    dependency["write_surface_identity"] = surface
    route_record = {
        "provider": provider,
        "control_owner": "reconciler_owned",
        "activation_group": payload["activation_group"],
        "component_controls": [],
        "secret_references": [],
    }
    route_digest = canonical_json_sha256(route_record)
    _set_operation_desired_state(payload, operation, provider, [])
    payload.update(
        {
            "provider": provider,
            "route_identity": route_identity,
            "route_digest": route_digest,
            "equipment_identities": ["skill:fixture/example"],
            "controlled_equipment_identities": [],
            "surface_scope": [surface],
            "write_targets": [skill_target],
            "operation": operation,
            "secret_references": [],
        }
    )
    preconditions = payload["preconditions"]
    assert isinstance(preconditions, dict)
    preconditions.update({"route_digest": route_digest, "surface_scope": [surface]})
    definition = thaw_json(plan.nodes[0].definition)
    assert isinstance(definition, dict)
    for field in (
        "route_identity",
        "route_digest",
        "equipment_identities",
        "controlled_equipment_identities",
        "surface_scope",
        "operation",
        "desired_state",
        "desired_state_digest",
        "secret_references",
    ):
        definition[field] = deepcopy(payload[field])
    definition["route_record"] = route_record
    return _rebuild_plan_for_document(plan, document, definition), document


def _native_plugin_plan_and_action_set(
    manager: str,
    operation: str,
) -> tuple[ValidatedPlan, dict[str, object]]:
    plan, document = _valid_plan_and_action_set()
    actions = document["actions"]
    assert isinstance(actions, list)
    evidence = actions[0]
    assert isinstance(evidence, dict)
    payload = evidence["action_payload"]
    assert isinstance(payload, dict)
    provider = {
        "kind": "native_plugin",
        "manager": manager,
        "plugin_id": "example@fixture",
        "scope": "user",
    }
    route_identity = f"route:fixture/{manager}-native-plugin"
    surface = f"surface:{route_identity}/plugin:fixture/example"
    target = {
        "target_identity": "",
        "write_surface_identity": surface,
        "surface_kind": (
            "plugin_enablement"
            if operation in {"enable", "disable"}
            else "plugin_installation"
        ),
        "locator": {
            "manager": manager,
            "native_identity": "example@fixture",
            "scope": "user",
        },
    }
    _replace_target(target)
    route_record = {
        "provider": provider,
        "control_owner": "reconciler_owned",
        "activation_group": payload["activation_group"],
        "component_controls": [],
        "secret_references": [],
    }
    route_digest = canonical_json_sha256(route_record)
    _set_operation_desired_state(payload, operation, provider, [])
    payload.update(
        {
            "harness": manager,
            "provider": provider,
            "route_identity": route_identity,
            "route_digest": route_digest,
            "equipment_identities": ["plugin:fixture/example"],
            "controlled_equipment_identities": [],
            "surface_scope": [surface],
            "write_targets": [target],
            "operation": operation,
            "secret_references": [],
            "verification_dependencies": [],
        }
    )
    preconditions = payload["preconditions"]
    assert isinstance(preconditions, dict)
    preconditions.update({"route_digest": route_digest, "surface_scope": [surface]})
    definition = thaw_json(plan.nodes[0].definition)
    assert isinstance(definition, dict)
    for field in (
        "harness",
        "route_identity",
        "route_digest",
        "equipment_identities",
        "controlled_equipment_identities",
        "surface_scope",
        "operation",
        "desired_state",
        "desired_state_digest",
        "secret_references",
    ):
        definition[field] = deepcopy(payload[field])
    definition["route_record"] = route_record
    return _rebuild_plan_for_document(plan, document, definition), document


def _surface_rule_plan_and_action_set(
    rule: str,
) -> tuple[ValidatedPlan, dict[str, object]]:
    plan, document = _valid_plan_and_action_set()
    actions = document["actions"]
    assert isinstance(actions, list)
    evidence = actions[0]
    assert isinstance(evidence, dict)
    payload = evidence["action_payload"]
    assert isinstance(payload, dict)
    targets = payload["write_targets"]
    assert isinstance(targets, list)
    route_identity = str(payload["route_identity"])
    if rule == "route_identity":
        targets = [
            next(
                target
                for target in targets
                if isinstance(target, dict)
                and target.get("surface_kind") == "plugin_installation"
            )
        ]
        payload["write_targets"] = targets
        payload["verification_dependencies"] = []
        surfaces = [f"surface:{route_identity}"]
    else:
        surfaces = []
        for target in targets:
            assert isinstance(target, dict)
            equipment = target.get("equipment_identity")
            if not isinstance(equipment, str):
                equipment = "plugin:fixture/example"
            prefix = (
                "surface:shared"
                if rule == "shared_equipment_identity"
                else f"surface:{route_identity}"
            )
            surfaces.append(f"{prefix}/{equipment}")
    for target, surface in zip(targets, surfaces, strict=True):
        assert isinstance(target, dict)
        _replace_target(target, write_surface_identity=surface)
    dependencies = payload["verification_dependencies"]
    assert isinstance(dependencies, list)
    for dependency in dependencies:
        assert isinstance(dependency, dict)
        equipment = dependency.get("equipment_identity")
        assert isinstance(equipment, str)
        dependency["write_surface_identity"] = next(
            surface for surface in surfaces if surface.endswith(f"/{equipment}")
        )
    targets.sort(key=lambda target: str(target["target_identity"]))
    surfaces.sort()
    payload["surface_scope"] = surfaces
    preconditions = payload["preconditions"]
    assert isinstance(preconditions, dict)
    preconditions["surface_scope"] = surfaces
    definition = thaw_json(plan.nodes[0].definition)
    assert isinstance(definition, dict)
    definition["surface_scope"] = deepcopy(surfaces)
    return _rebuild_plan_for_document(plan, document, definition), document


def _legacy_projector_plan_and_action_set() -> tuple[ValidatedPlan, dict[str, object]]:
    plan, document = _valid_plan_and_action_set()
    actions = document["actions"]
    assert isinstance(actions, list)
    evidence = actions[0]
    assert isinstance(evidence, dict)
    payload = evidence["action_payload"]
    assert isinstance(payload, dict)
    provider = {"kind": "standalone_skill", "canonical_root": "agents_skills"}
    route_identity = "route:fixture/claude-standalone"
    surface = f"surface:{route_identity}"
    target = {
        "target_identity": "",
        "write_surface_identity": surface,
        "surface_kind": "legacy_projector",
        "locator": {
            "owner": "claude",
            "source": "projector",
            "key_path": ["agents_skills"],
        },
    }
    _replace_target(target)
    route_record = {
        "provider": provider,
        "control_owner": "reconciler_owned",
        "activation_group": payload["activation_group"],
        "component_controls": [],
        "secret_references": [],
    }
    route_digest = canonical_json_sha256(route_record)
    _set_operation_desired_state(payload, "configure", provider, [])
    payload.update(
        {
            "harness": "claude",
            "route_identity": route_identity,
            "route_digest": route_digest,
            "provider": provider,
            "equipment_identities": ["skill:fixture/example"],
            "controlled_equipment_identities": [],
            "surface_scope": [surface],
            "write_targets": [target],
            "operation": "configure",
            "secret_references": [],
            "verification_dependencies": [],
        }
    )
    preconditions = payload["preconditions"]
    assert isinstance(preconditions, dict)
    preconditions.update({"route_digest": route_digest, "surface_scope": [surface]})
    definition = thaw_json(plan.nodes[0].definition)
    assert isinstance(definition, dict)
    for field in (
        "harness",
        "route_identity",
        "route_digest",
        "equipment_identities",
        "controlled_equipment_identities",
        "surface_scope",
        "operation",
        "desired_state",
        "desired_state_digest",
        "secret_references",
    ):
        definition[field] = deepcopy(payload[field])
    definition["route_record"] = route_record
    return _rebuild_plan_for_document(plan, document, definition), document


def _plugin_selection_plan_and_action_set(
    manager: str = "codex",
    *,
    desired_controls: list[dict[str, object]] | None = None,
    configuration_digest: str | None = None,
) -> tuple[ValidatedPlan, dict[str, object]]:
    plan, document = _valid_plan_and_action_set()
    actions = document["actions"]
    assert isinstance(actions, list)
    evidence = actions[0]
    assert isinstance(evidence, dict)
    payload = evidence["action_payload"]
    assert isinstance(payload, dict)
    provider = {
        "kind": "native_plugin",
        "manager": manager,
        "plugin_id": "example@fixture",
        "scope": "user",
    }
    route_identity = f"route:fixture/{manager}-plugin"
    surface = f"surface:{route_identity}"
    controls = [
        {"equipment_identity": "plugin:fixture/example", "state": "disabled"},
        {"equipment_identity": "skill:fixture/aux", "state": "enabled"},
    ]
    target = {
        "target_identity": "",
        "write_surface_identity": surface,
        "surface_kind": "plugin_selection",
        "equipment_identity": "plugin:fixture/example",
        "locator": (
            {
                "owner": "codex",
                "source": "config",
                "key_path": ["plugins", "example@fixture"],
            }
            if manager == "codex"
            else {
                "owner": "claude",
                "source": "settings",
                "key_path": ["enabledPlugins", "example@fixture"],
            }
        ),
    }
    _replace_target(target)
    route_record = {
        "provider": provider,
        "control_owner": "reconciler_owned",
        "activation_group": payload["activation_group"],
        "component_controls": controls,
        "secret_references": [],
    }
    route_digest = canonical_json_sha256(route_record)
    desired_state = _configure_desired_state(
        provider,
        controls if desired_controls is None else desired_controls,
    )
    if configuration_digest is not None:
        configuration = desired_state["configuration"]
        assert isinstance(configuration, dict)
        configuration["digest"] = configuration_digest
    payload.update(
        {
            "harness": manager,
            "provider": provider,
            "route_identity": route_identity,
            "route_digest": route_digest,
            "equipment_identities": ["plugin:fixture/example"],
            "controlled_equipment_identities": [
                "plugin:fixture/example",
                "skill:fixture/aux",
            ],
            "surface_scope": [surface],
            "write_targets": [target],
            "operation": "configure",
            "desired_state": desired_state,
            "desired_state_digest": canonical_json_sha256(desired_state),
            "secret_references": [],
            "verification_dependencies": [],
        }
    )
    preconditions = payload["preconditions"]
    assert isinstance(preconditions, dict)
    preconditions.update({"route_digest": route_digest, "surface_scope": [surface]})
    definition = thaw_json(plan.nodes[0].definition)
    assert isinstance(definition, dict)
    for field in (
        "harness",
        "route_identity",
        "route_digest",
        "equipment_identities",
        "controlled_equipment_identities",
        "surface_scope",
        "operation",
        "desired_state",
        "desired_state_digest",
        "secret_references",
    ):
        definition[field] = deepcopy(payload[field])
    definition["route_record"] = route_record
    return _rebuild_plan_for_document(plan, document, definition), document


def _reseal(document: dict[str, object]) -> None:
    actions = document["actions"]
    assert isinstance(actions, list)
    for evidence in actions:
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        payload["action_identity"] = plan_action_identity(payload)
        evidence["action_digest"] = plan_action_digest(payload)
    document["action_set_digest"] = plan_action_set_digest(
        str(document["candidate_identity"]),
        str(document["implementation_manifest_digest"]),
        str(document["plan_digest"]),
        actions,
    )


def _reseal_digest_fields_only(document: dict[str, object]) -> None:
    """Reseal a deliberately semantically invalid but closed-shape document."""

    actions = document["actions"]
    assert isinstance(actions, list)
    for evidence in actions:
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        evidence["action_digest"] = canonical_json_sha256(payload)
    document["action_set_digest"] = canonical_json_sha256(
        {
            "schema_version": document["schema_version"],
            "candidate_identity": document["candidate_identity"],
            "implementation_manifest_digest": document[
                "implementation_manifest_digest"
            ],
            "plan_digest": document["plan_digest"],
            "actions": actions,
        }
    )


def _plan_with_foreign_route_field(
    field: str,
) -> tuple[ValidatedPlan, dict[str, object]]:
    plan, document = _valid_plan_and_action_set()
    definition = thaw_json(plan.nodes[0].definition)
    assert isinstance(definition, dict)
    route_record = definition["route_record"]
    assert isinstance(route_record, dict)
    foreign_values: dict[str, object] = {
        "secret_references": [
            {"kind": "environment_variable", "name": "ATTACKER_TOKEN"}
        ],
        "activation_group": "activation:fixture/foreign",
        "component_controls": [
            {"equipment_identity": "skill:fixture/foreign", "state": "disabled"}
        ],
    }
    route_record[field] = foreign_values[field]
    route_digest = canonical_json_sha256(route_record)
    definition["route_digest"] = route_digest
    actions = document["actions"]
    assert isinstance(actions, list)
    evidence = actions[0]
    assert isinstance(evidence, dict)
    payload = evidence["action_payload"]
    assert isinstance(payload, dict)
    payload["route_digest"] = route_digest
    preconditions = payload["preconditions"]
    assert isinstance(preconditions, dict)
    preconditions["route_digest"] = route_digest
    return _rebuild_plan_for_document(plan, document, definition), document


def _plan_with_component_controls(
    controls: list[dict[str, object]],
) -> tuple[ValidatedPlan, dict[str, object]]:
    plan, document = _surface_rule_plan_and_action_set("route_identity")
    definition = thaw_json(plan.nodes[0].definition)
    assert isinstance(definition, dict)
    route_record = definition["route_record"]
    assert isinstance(route_record, dict)
    route_record["component_controls"] = deepcopy(controls)
    identities = sorted(
        {
            str(control["equipment_identity"])
            for control in controls
            if "equipment_identity" in control
        }
    )
    definition["controlled_equipment_identities"] = identities
    route_digest = canonical_json_sha256(route_record)
    definition["route_digest"] = route_digest
    actions = document["actions"]
    assert isinstance(actions, list)
    evidence = actions[0]
    assert isinstance(evidence, dict)
    payload = evidence["action_payload"]
    assert isinstance(payload, dict)
    payload["controlled_equipment_identities"] = identities
    payload["route_digest"] = route_digest
    preconditions = payload["preconditions"]
    assert isinstance(preconditions, dict)
    preconditions["route_digest"] = route_digest
    return _rebuild_plan_for_document(plan, document, definition), document


def _diagnostic_codes(result: object) -> tuple[str, ...]:
    diagnostics = getattr(result, "diagnostics", ())
    return tuple(diagnostic.code for diagnostic in diagnostics)


def _plan_with_foreign_top_tuple(
    original: ValidatedPlan,
    document: dict[str, object],
) -> ValidatedPlan:
    preimage = thaw_json(original.preimage)
    assert isinstance(preimage, dict)
    preimage.update(
        {
            "candidate_identity": "candidate:fixture/foreign-controller",
            "implementation_manifest_digest": "sha256:" + "7" * 64,
            "catalog_digest": "sha256:" + "8" * 64,
            "lock_digest": "sha256:" + "9" * 64,
        }
    )
    frozen_preimage = freeze_json(preimage)
    assert isinstance(frozen_preimage, type(original.preimage))
    plan_digest = canonical_json_sha256(frozen_preimage)

    actions = document["actions"]
    assert isinstance(actions, list)
    evidence = actions[0]
    assert isinstance(evidence, dict)
    payload = evidence["action_payload"]
    assert isinstance(payload, dict)
    payload["plan_digest"] = plan_digest
    preconditions = payload["preconditions"]
    assert isinstance(preconditions, dict)
    preconditions["plan_digest"] = plan_digest
    payload["action_identity"] = plan_action_identity(payload)
    evidence["action_digest"] = plan_action_digest(payload)
    document.update(
        {
            "candidate_identity": preimage["candidate_identity"],
            "implementation_manifest_digest": preimage[
                "implementation_manifest_digest"
            ],
            "plan_digest": plan_digest,
        }
    )
    document["action_set_digest"] = plan_action_set_digest(
        str(document["candidate_identity"]),
        str(document["implementation_manifest_digest"]),
        plan_digest,
        actions,
    )

    mutation = original.nodes[0]
    final = original.nodes[1]
    mutation_identity = str(payload["action_identity"])
    final_identity = "verification:" + canonical_json_sha256(
        {
            "plan_digest": plan_digest,
            "ordinal": final.ordinal,
            "semantic_definition_digest": canonical_json_sha256(final.definition),
            "predecessor_identities": (mutation_identity,),
        }
    )
    return ValidatedPlan(
        nodes=(
            PlanNode(
                key=mutation.key,
                kind=mutation.kind,
                ordinal=mutation.ordinal,
                identity=mutation_identity,
                dependencies=(),
                definition=mutation.definition,
            ),
            PlanNode(
                key=final.key,
                kind=final.kind,
                ordinal=final.ordinal,
                identity=final_identity,
                dependencies=(mutation_identity,),
                definition=final.definition,
            ),
        ),
        edges=((mutation_identity, final_identity),),
        digest=plan_digest,
        preimage=frozen_preimage,
    )


class PlanActionSetAdmissionTest(unittest.TestCase):
    def test_complete_projection_is_admitted_as_one_immutable_typed_artifact(
        self,
    ) -> None:
        plan, document = _valid_plan_and_action_set()

        result = admit_plan_action_set(
            canonical_json_bytes(document),
            PlanActionSetTrust(
                validated_plan=plan,
                expected_action_set_digest=str(document["action_set_digest"]),
            ),
        )

        self.assertIsInstance(result, AdmittedPlanActionSet)
        assert isinstance(result, AdmittedPlanActionSet)
        self.assertEqual(result.document, freeze_json(document))
        self.assertEqual(result.canonical_bytes, canonical_json_bytes(document))
        self.assertEqual(result.action_set_digest, document["action_set_digest"])
        with self.assertRaises(FrozenInstanceError):
            result.action_set_digest = "sha256:" + "0" * 64  # type: ignore[misc]

    def test_canonical_skill_dependency_must_match_its_claude_write_target(
        self,
    ) -> None:
        plan, original = _valid_plan_and_action_set()
        document = deepcopy(original)
        actions = document["actions"]
        assert isinstance(actions, list)
        evidence = actions[0]
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        dependencies = payload["verification_dependencies"]
        assert isinstance(dependencies, list)
        dependency = dependencies[0]
        assert isinstance(dependency, dict)
        dependency["target_locator"] = {"path": "~/.agents/skills/other"}
        _reseal(document)

        result = admit_plan_action_set(
            canonical_json_bytes(document),
            PlanActionSetTrust(
                validated_plan=plan,
                expected_action_set_digest=str(document["action_set_digest"]),
            ),
        )

        self.assertIn("PLAN_ACTION_VERIFICATION_DEPENDENCY_INVALID", _diagnostic_codes(result))

    def test_canonical_skill_dependency_identities_must_be_unique(self) -> None:
        plan, document = _valid_plan_and_action_set()
        actions = document["actions"]
        assert isinstance(actions, list)
        evidence = actions[0]
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        targets = payload["write_targets"]
        dependencies = payload["verification_dependencies"]
        assert isinstance(targets, list)
        assert isinstance(dependencies, list) and len(dependencies) == 1

        second_target = deepcopy(
            next(
                target
                for target in targets
                if isinstance(target, dict)
                and target.get("surface_kind") == "claude_skill_entry"
            )
        )
        assert isinstance(second_target, dict)
        second_surface = (
            "surface:route:fixture/claude-plugin/skill:fixture/other"
        )
        _replace_target(
            second_target,
            write_surface_identity=second_surface,
            equipment_identity="skill:fixture/other",
            locator={"path": "~/.claude/skills/other"},
        )
        targets.append(second_target)
        targets.sort(key=lambda target: str(target["target_identity"]))

        second_dependency = deepcopy(dependencies[0])
        assert isinstance(second_dependency, dict)
        second_dependency.update(
            {
                "write_surface_identity": second_surface,
                "equipment_identity": "skill:fixture/other",
                "target_locator": {"path": "~/.agents/skills/other"},
            }
        )
        dependencies.append(second_dependency)
        dependencies.sort(key=canonical_json_bytes)

        equipment_identities = [
            "plugin:fixture/example",
            "skill:fixture/example",
            "skill:fixture/other",
        ]
        surface_scope = [
            "surface:route:fixture/claude-plugin/plugin:fixture/example",
            "surface:route:fixture/claude-plugin/skill:fixture/example",
            second_surface,
        ]
        payload["equipment_identities"] = equipment_identities
        payload["surface_scope"] = surface_scope
        preconditions = payload["preconditions"]
        assert isinstance(preconditions, dict)
        preconditions["surface_scope"] = surface_scope

        mutation_definition = thaw_json(plan.nodes[0].definition)
        assert isinstance(mutation_definition, dict)
        mutation_definition["equipment_identities"] = equipment_identities
        mutation_definition["surface_scope"] = surface_scope
        plan = _rebuild_plan_for_document(plan, document, mutation_definition)
        trust = PlanActionSetTrust(
            validated_plan=plan,
            expected_action_set_digest=str(document["action_set_digest"]),
        )

        result = admit_plan_action_set(canonical_json_bytes(document), trust)

        self.assertIsInstance(result, PlanActionSetRejection)
        self.assertIn(
            "PLAN_ACTION_VERIFICATION_DEPENDENCY_INVALID",
            _diagnostic_codes(result),
        )

    def test_reordered_actions_change_the_canonical_set_digest_and_fail_membership(
        self,
    ) -> None:
        plan, original = _valid_plan_and_action_set()
        document = deepcopy(original)
        actions = document["actions"]
        assert isinstance(actions, list)
        second = deepcopy(actions[0])
        assert isinstance(second, dict)
        payload = second["action_payload"]
        assert isinstance(payload, dict)
        payload["ordinal"] = 1
        payload["route_identity"] = "route:fixture/other-plugin"
        _reseal(document)
        actions.append(second)
        _reseal(document)
        ordered_digest = str(document["action_set_digest"])
        actions.reverse()

        result = admit_plan_action_set(
            canonical_json_bytes(document),
            PlanActionSetTrust(
                validated_plan=plan,
                expected_action_set_digest=ordered_digest,
            ),
        )

        codes = _diagnostic_codes(result)
        self.assertIn("PLAN_ACTION_SET_MEMBERSHIP_INVALID", codes)
        self.assertIn("PLAN_ACTION_SET_DIGEST_INVALID", codes)

    def test_malformed_or_oversized_bytes_fail_closed_before_admission(self) -> None:
        plan, document = _valid_plan_and_action_set()
        trust = PlanActionSetTrust(
            validated_plan=plan,
            expected_action_set_digest=str(document["action_set_digest"]),
        )
        cases = {
            "wrong_type": ("not-bytes", "PLAN_ACTION_SET_BYTES_INVALID"),
            "oversized": (
                b"x" * (MAX_PLAN_ACTION_SET_BYTES + 1),
                "PLAN_ACTION_SET_BYTES_INVALID",
            ),
            "non_utf8": (b"\xff", "PLAN_ACTION_SET_JSON_INVALID"),
            "duplicate_member": (b'{"x":1,"x":2}', "PLAN_ACTION_SET_JSON_INVALID"),
            "nonfinite": (b'{"x":NaN}', "PLAN_ACTION_SET_JSON_INVALID"),
        }
        for case, (raw_document, expected_code) in cases.items():
            with self.subTest(case=case):
                result = admit_plan_action_set(raw_document, trust)  # type: ignore[arg-type]
                self.assertIsInstance(result, PlanActionSetRejection)
                self.assertEqual(_diagnostic_codes(result), (expected_code,))

    def test_raw_and_canonical_documents_share_the_exact_sixteen_mib_bound(
        self,
    ) -> None:
        plan, document = _valid_plan_and_action_set()
        trust = PlanActionSetTrust(
            validated_plan=plan,
            expected_action_set_digest=str(document["action_set_digest"]),
        )
        self.assertEqual(MAX_PLAN_ACTION_SET_BYTES, 16 * 1024 * 1024)
        canonically_oversized = b"[" + b",".join([b"1e9"] * 50_000) + b"]"
        reduced_bound = 256 * 1024
        self.assertLessEqual(len(canonically_oversized), reduced_bound)

        with patch(
            "agent_equipment.plan_action_set.MAX_PLAN_ACTION_SET_BYTES",
            reduced_bound,
        ):
            result = admit_plan_action_set(canonically_oversized, trust)

        self.assertEqual(
            _diagnostic_codes(result),
            ("PLAN_ACTION_SET_JSON_INVALID",),
        )

    def test_closed_schema_and_literal_secret_reject_without_echo(self) -> None:
        plan, original = _valid_plan_and_action_set()

        extra = deepcopy(original)
        extra["unexpected"] = True
        extra_result = admit_plan_action_set(
            canonical_json_bytes(extra),
            PlanActionSetTrust(
                validated_plan=plan,
                expected_action_set_digest=str(extra["action_set_digest"]),
            ),
        )
        self.assertEqual(
            _diagnostic_codes(extra_result),
            ("PLAN_ACTION_SET_SCHEMA_INVALID",),
        )

        canary = "ghp_" + "A" * 32
        secret = deepcopy(original)
        secret["candidate_identity"] = canary
        secret_result = admit_plan_action_set(
            canonical_json_bytes(secret),
            PlanActionSetTrust(
                validated_plan=plan,
                expected_action_set_digest=str(secret["action_set_digest"]),
            ),
        )
        self.assertEqual(
            _diagnostic_codes(secret_result),
            ("PLAN_ACTION_SET_LITERAL_SECRET",),
        )
        self.assertNotIn(canary, repr(secret_result))

    def test_schema_pins_skill_roots_and_requires_nonempty_desired_state(
        self,
    ) -> None:
        plan, original = _valid_plan_and_action_set()
        cases: dict[str, dict[str, object]] = {}

        unrooted_write = deepcopy(original)
        write_payload = unrooted_write["actions"][0]["action_payload"]  # type: ignore[index]
        write_target = next(
            target
            for target in write_payload["write_targets"]  # type: ignore[index]
            if target["surface_kind"] == "claude_skill_entry"
        )
        write_target["locator"] = {"path": "example"}
        cases["unrooted_write"] = unrooted_write

        unrooted_dependency = deepcopy(original)
        dependency_payload = unrooted_dependency["actions"][0][  # type: ignore[index]
            "action_payload"
        ]
        dependency_payload["verification_dependencies"][0][  # type: ignore[index]
            "target_locator"
        ] = {"path": "example"}
        cases["unrooted_dependency"] = unrooted_dependency

        empty_desired_state = deepcopy(original)
        empty_payload = empty_desired_state["actions"][0][  # type: ignore[index]
            "action_payload"
        ]
        empty_payload["desired_state"] = {}
        cases["empty_desired_state"] = empty_desired_state

        for case, document in cases.items():
            with self.subTest(case=case):
                result = admit_plan_action_set(
                    canonical_json_bytes(document),
                    PlanActionSetTrust(
                        validated_plan=plan,
                        expected_action_set_digest=str(document["action_set_digest"]),
                    ),
                )

                self.assertEqual(
                    _diagnostic_codes(result),
                    ("PLAN_ACTION_SET_SCHEMA_INVALID",),
                )

    def test_coordinated_reseal_cannot_substitute_validated_action_authority(
        self,
    ) -> None:
        plan, original = _valid_plan_and_action_set()
        document = deepcopy(original)
        actions = document["actions"]
        assert isinstance(actions, list)
        evidence = actions[0]
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        payload["route_digest"] = "sha256:" + "7" * 64
        preconditions = payload["preconditions"]
        assert isinstance(preconditions, dict)
        preconditions["route_digest"] = payload["route_digest"]
        _reseal(document)

        result = admit_plan_action_set(
            canonical_json_bytes(document),
            PlanActionSetTrust(
                validated_plan=plan,
                expected_action_set_digest=str(document["action_set_digest"]),
            ),
        )

        self.assertIn("PLAN_ACTION_SET_MEMBERSHIP_INVALID", _diagnostic_codes(result))

    def test_missing_or_extra_actions_cannot_change_complete_membership(self) -> None:
        plan, original = _valid_plan_and_action_set()
        cases: dict[str, dict[str, object]] = {}

        missing = deepcopy(original)
        missing["actions"] = []
        _reseal(missing)
        cases["missing"] = missing

        extra = deepcopy(original)
        extra_actions = extra["actions"]
        assert isinstance(extra_actions, list)
        second = deepcopy(extra_actions[0])
        assert isinstance(second, dict)
        second_payload = second["action_payload"]
        assert isinstance(second_payload, dict)
        second_payload["ordinal"] = 1
        second_payload["route_identity"] = "route:fixture/extra-plugin"
        extra_actions.append(second)
        _reseal(extra)
        cases["extra"] = extra

        for case, document in cases.items():
            with self.subTest(case=case):
                result = admit_plan_action_set(
                    canonical_json_bytes(document),
                    PlanActionSetTrust(
                        validated_plan=plan,
                        expected_action_set_digest=str(
                            document["action_set_digest"]
                        ),
                    ),
                )
                self.assertIn(
                    "PLAN_ACTION_SET_MEMBERSHIP_INVALID",
                    _diagnostic_codes(result),
                )

    def test_target_identity_and_logical_scope_are_self_authenticating(self) -> None:
        plan, original = _valid_plan_and_action_set()
        document = deepcopy(original)
        actions = document["actions"]
        assert isinstance(actions, list)
        evidence = actions[0]
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        targets = payload["write_targets"]
        assert isinstance(targets, list)
        first = targets[0]
        assert isinstance(first, dict)
        first["target_identity"] = "target:sha256:" + "0" * 64
        first["write_surface_identity"] = next(
            str(surface)
            for surface in payload["surface_scope"]  # type: ignore[union-attr]
            if surface != first["write_surface_identity"]
        )
        _reseal(document)

        result = admit_plan_action_set(
            canonical_json_bytes(document),
            PlanActionSetTrust(
                validated_plan=plan,
                expected_action_set_digest=str(document["action_set_digest"]),
            ),
        )

        self.assertIn("PLAN_ACTION_TARGET_IDENTITY_INVALID", _diagnostic_codes(result))
        self.assertIn("PLAN_ACTION_TARGET_SCOPE_INVALID", _diagnostic_codes(result))

    def test_logical_surface_relabel_does_not_change_physical_target_identity(
        self,
    ) -> None:
        plan, document = _valid_plan_and_action_set()
        fixed_trust = PlanActionSetTrust(
            validated_plan=plan,
            expected_action_set_digest=str(document["action_set_digest"]),
        )
        actions = document["actions"]
        assert isinstance(actions, list)
        evidence = actions[0]
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        targets = payload["write_targets"]
        assert isinstance(targets, list)
        target = targets[0]
        assert isinstance(target, dict)
        original_identity = target["target_identity"]
        target["write_surface_identity"] = "surface:route:fixture/relabelled"
        _reseal_digest_fields_only(document)

        result = admit_plan_action_set(canonical_json_bytes(document), fixed_trust)

        self.assertEqual(target["target_identity"], original_identity)
        self.assertNotIn(
            "PLAN_ACTION_TARGET_IDENTITY_INVALID",
            _diagnostic_codes(result),
        )
        self.assertIn("PLAN_ACTION_TARGET_BINDING_INVALID", _diagnostic_codes(result))

    def test_physical_targets_require_the_canonical_identity_order(self) -> None:
        plan, original = _valid_plan_and_action_set()
        document = deepcopy(original)
        actions = document["actions"]
        assert isinstance(actions, list)
        evidence = actions[0]
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        targets = payload["write_targets"]
        assert isinstance(targets, list)
        targets.reverse()
        _reseal_digest_fields_only(document)

        result = admit_plan_action_set(
            canonical_json_bytes(document),
            PlanActionSetTrust(
                validated_plan=plan,
                expected_action_set_digest=str(document["action_set_digest"]),
            ),
        )

        self.assertIn("PLAN_ACTION_TARGET_ORDER_INVALID", _diagnostic_codes(result))

    def test_preconditions_repeat_all_currently_proven_authority(self) -> None:
        plan, original = _valid_plan_and_action_set()
        document = deepcopy(original)
        actions = document["actions"]
        assert isinstance(actions, list)
        evidence = actions[0]
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        preconditions = payload["preconditions"]
        assert isinstance(preconditions, dict)
        preconditions["adapter_version"] = "foreign-version"
        _reseal(document)

        result = admit_plan_action_set(
            canonical_json_bytes(document),
            PlanActionSetTrust(
                validated_plan=plan,
                expected_action_set_digest=str(document["action_set_digest"]),
            ),
        )

        self.assertEqual(
            _diagnostic_codes(result),
            ("PLAN_ACTION_PRECONDITION_INVALID",),
        )

    def test_one_physical_locator_cannot_be_relabelled_as_two_targets(self) -> None:
        plan, original = _valid_plan_and_action_set()
        document = deepcopy(original)
        actions = document["actions"]
        assert isinstance(actions, list)
        evidence = actions[0]
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        targets = payload["write_targets"]
        assert isinstance(targets, list)
        relabelled = deepcopy(targets[0])
        assert isinstance(relabelled, dict)
        second = targets[1]
        assert isinstance(second, dict)
        relabelled["write_surface_identity"] = second["write_surface_identity"]
        _replace_target(relabelled)
        targets.append(relabelled)
        _reseal_digest_fields_only(document)

        result = admit_plan_action_set(
            canonical_json_bytes(document),
            PlanActionSetTrust(
                validated_plan=plan,
                expected_action_set_digest=str(document["action_set_digest"]),
            ),
        )

        self.assertIn(
            "PLAN_ACTION_PHYSICAL_TARGET_DUPLICATE",
            _diagnostic_codes(result),
        )

    def test_trusted_set_digest_is_independent_of_the_supplied_projection(self) -> None:
        plan, document = _valid_plan_and_action_set()

        result = admit_plan_action_set(
            canonical_json_bytes(document),
            PlanActionSetTrust(
                validated_plan=plan,
                expected_action_set_digest="sha256:" + "0" * 64,
            ),
        )

        self.assertEqual(
            _diagnostic_codes(result),
            ("PLAN_ACTION_SET_DIGEST_INVALID",),
        )

    def test_admission_uses_captured_schema_bytes_not_a_replaced_live_path(
        self,
    ) -> None:
        plan, document = _valid_plan_and_action_set()
        fixed_trust = PlanActionSetTrust(
            validated_plan=plan,
            expected_action_set_digest=str(document["action_set_digest"]),
        )
        document["unexpected"] = True
        _reseal_digest_fields_only(document)
        permissive_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
        }

        with patch.object(
            json_schema_module,
            "_load_schemas",
            return_value={"plan-action-set-v1.schema.json": permissive_schema},
        ):
            result = admit_plan_action_set(
                canonical_json_bytes(document),
                fixed_trust,
            )

        self.assertIsInstance(result, PlanActionSetRejection)
        self.assertIn("PLAN_ACTION_SET_SCHEMA_INVALID", _diagnostic_codes(result))

    def test_replaced_live_schema_cannot_deny_the_captured_valid_case(self) -> None:
        plan, document = _valid_plan_and_action_set()
        fixed_trust = PlanActionSetTrust(
            validated_plan=plan,
            expected_action_set_digest=str(document["action_set_digest"]),
        )
        with patch.object(
            json_schema_module,
            "_load_schemas",
            side_effect=AssertionError("admission reread the live Schema path"),
        ):
            result = admit_plan_action_set(
                canonical_json_bytes(document),
                fixed_trust,
            )

        self.assertIsInstance(result, AdmittedPlanActionSet)

    def test_plan_preimage_tuple_cannot_disagree_with_its_mutation_nodes(
        self,
    ) -> None:
        original_plan, document = _valid_plan_and_action_set()
        foreign_plan = _plan_with_foreign_top_tuple(original_plan, document)
        fixed_trust = PlanActionSetTrust(
            validated_plan=foreign_plan,
            expected_action_set_digest=str(document["action_set_digest"]),
        )

        result = admit_plan_action_set(
            canonical_json_bytes(document),
            fixed_trust,
        )

        self.assertIsInstance(result, PlanActionSetRejection)
        self.assertIn(
            "PLAN_ACTION_SET_PLAN_BINDING_INVALID",
            _diagnostic_codes(result),
        )

    def test_native_physical_target_must_equal_its_validated_provider(self) -> None:
        plan, document = _valid_plan_and_action_set()
        fixed_trust = PlanActionSetTrust(
            validated_plan=plan,
            expected_action_set_digest=str(document["action_set_digest"]),
        )
        actions = document["actions"]
        assert isinstance(actions, list)
        evidence = actions[0]
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        targets = payload["write_targets"]
        assert isinstance(targets, list)
        native_target = next(
            target
            for target in targets
            if isinstance(target, dict)
            and target.get("surface_kind") == "plugin_installation"
        )
        assert isinstance(native_target, dict)
        locator = native_target["locator"]
        assert isinstance(locator, dict)
        locator["native_identity"] = "foreign@fixture"
        _replace_target(native_target)
        targets.sort(key=lambda target: str(target["target_identity"]))
        _reseal_digest_fields_only(document)

        result = admit_plan_action_set(
            canonical_json_bytes(document),
            fixed_trust,
        )

        self.assertIsInstance(result, PlanActionSetRejection)
        self.assertIn("PLAN_ACTION_TARGET_BINDING_INVALID", _diagnostic_codes(result))

    def test_target_kind_equipment_manager_and_route_are_plan_bound(self) -> None:
        mutations = {
            "kind": lambda targets: next(
                target
                for target in targets
                if target["surface_kind"] == "plugin_installation"
            ).__setitem__("surface_kind", "plugin_enablement"),
            "equipment": lambda targets: next(
                target
                for target in targets
                if target["surface_kind"] == "claude_skill_entry"
            ).__setitem__("equipment_identity", "skill:fixture/foreign"),
            "manager": lambda targets: next(
                target
                for target in targets
                if target["surface_kind"] == "plugin_installation"
            )["locator"].__setitem__("manager", "cursor"),
            "route": lambda targets: next(
                target
                for target in targets
                if target["surface_kind"] == "claude_skill_entry"
            ).__setitem__(
                "write_surface_identity",
                "surface:route:fixture/foreign/skill:fixture/example",
            ),
        }
        for case, mutate in mutations.items():
            with self.subTest(case=case):
                plan, document = _valid_plan_and_action_set()
                fixed_trust = PlanActionSetTrust(
                    validated_plan=plan,
                    expected_action_set_digest=str(document["action_set_digest"]),
                )
                actions = document["actions"]
                assert isinstance(actions, list)
                evidence = actions[0]
                assert isinstance(evidence, dict)
                payload = evidence["action_payload"]
                assert isinstance(payload, dict)
                targets = payload["write_targets"]
                assert isinstance(targets, list)
                mutate(targets)
                for target in targets:
                    assert isinstance(target, dict)
                    _replace_target(target)
                targets.sort(key=lambda target: str(target["target_identity"]))
                _reseal_digest_fields_only(document)

                result = admit_plan_action_set(
                    canonical_json_bytes(document),
                    fixed_trust,
                )

                self.assertIsInstance(result, PlanActionSetRejection)
                self.assertIn(
                    "PLAN_ACTION_TARGET_BINDING_INVALID",
                    _diagnostic_codes(result),
                )

    def test_every_claude_write_target_requires_one_canonical_dependency(
        self,
    ) -> None:
        plan, document = _valid_plan_and_action_set()
        fixed_trust = PlanActionSetTrust(
            validated_plan=plan,
            expected_action_set_digest=str(document["action_set_digest"]),
        )
        actions = document["actions"]
        assert isinstance(actions, list)
        evidence = actions[0]
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        payload["verification_dependencies"] = []
        _reseal_digest_fields_only(document)

        result = admit_plan_action_set(
            canonical_json_bytes(document),
            fixed_trust,
        )

        self.assertIsInstance(result, PlanActionSetRejection)
        self.assertIn(
            "PLAN_ACTION_VERIFICATION_DEPENDENCY_INVALID",
            _diagnostic_codes(result),
        )

    def test_plan_projection_rejects_expected_post_state_field(self) -> None:
        plan, document = _valid_plan_and_action_set()
        actions = document["actions"]
        assert isinstance(actions, list)
        evidence = actions[0]
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        payload["expected_post_state_digest"] = "sha256:" + "7" * 64

        result = admit_plan_action_set(
            canonical_json_bytes(document),
            PlanActionSetTrust(
                validated_plan=plan,
                expected_action_set_digest=str(document["action_set_digest"]),
            ),
        )

        self.assertIsInstance(result, PlanActionSetRejection)
        self.assertEqual(
            _diagnostic_codes(result),
            ("PLAN_ACTION_SET_SCHEMA_INVALID",),
        )

    def test_route_digest_must_hash_the_complete_validated_route_record(self) -> None:
        plan, document = _valid_plan_and_action_set()
        actions = document["actions"]
        assert isinstance(actions, list)
        evidence = actions[0]
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        forged_digest = "sha256:" + "7" * 64
        payload["route_digest"] = forged_digest
        preconditions = payload["preconditions"]
        assert isinstance(preconditions, dict)
        preconditions["route_digest"] = forged_digest
        definition = thaw_json(plan.nodes[0].definition)
        assert isinstance(definition, dict)
        definition["route_digest"] = forged_digest
        forged_plan = _rebuild_plan_for_document(plan, document, definition)
        fixed_trust = PlanActionSetTrust(
            validated_plan=forged_plan,
            expected_action_set_digest=str(document["action_set_digest"]),
        )

        result = admit_plan_action_set(canonical_json_bytes(document), fixed_trust)

        self.assertIsInstance(result, PlanActionSetRejection)
        self.assertIn("PLAN_ACTION_SET_MEMBERSHIP_INVALID", _diagnostic_codes(result))

    def test_operation_and_provider_close_selection_target_authority(self) -> None:
        plan, document = _valid_plan_and_action_set()
        fixed_trust = PlanActionSetTrust(
            validated_plan=plan,
            expected_action_set_digest=str(document["action_set_digest"]),
        )
        actions = document["actions"]
        assert isinstance(actions, list)
        evidence = actions[0]
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        targets = payload["write_targets"]
        assert isinstance(targets, list)
        relabelled = targets[0]
        assert isinstance(relabelled, dict)
        _replace_target(
            relabelled,
            surface_kind="plugin_selection",
            equipment_identity="plugin:fixture/example",
            locator={
                "owner": "claude",
                "source": "attacker-controlled",
                "key_path": ["enabledPlugins", "example"],
            },
        )
        targets.sort(key=lambda target: str(target["target_identity"]))
        _reseal_digest_fields_only(document)

        result = admit_plan_action_set(canonical_json_bytes(document), fixed_trust)

        self.assertIsInstance(result, PlanActionSetRejection)
        self.assertIn("PLAN_ACTION_TARGET_BINDING_INVALID", _diagnostic_codes(result))

    def test_direct_mcp_selection_contract_matrix_is_complete(self) -> None:
        supported_operations = ("configure", "enable", "disable", "remove", "restore")
        for harness in ("claude", "codex", "cursor"):
            for operation in supported_operations:
                with self.subTest(harness=harness, operation=operation):
                    plan, document = _direct_mcp_plan_and_action_set(
                        harness, operation
                    )
                    trust = PlanActionSetTrust(
                        validated_plan=plan,
                        expected_action_set_digest=str(
                            document["action_set_digest"]
                        ),
                    )
                    valid_result = admit_plan_action_set(
                        canonical_json_bytes(document), trust
                    )
                    self.assertIsInstance(valid_result, AdmittedPlanActionSet)

        for operation in ("install", "suppress_native_update"):
            with self.subTest(invalid_operation=operation):
                plan, document = _direct_mcp_plan_and_action_set("codex", operation)
                trust = PlanActionSetTrust(
                    validated_plan=plan,
                    expected_action_set_digest=str(document["action_set_digest"]),
                )
                result = admit_plan_action_set(canonical_json_bytes(document), trust)
                self.assertIsInstance(result, PlanActionSetRejection)
                self.assertIn(
                    "PLAN_ACTION_TARGET_BINDING_INVALID",
                    _diagnostic_codes(result),
                )

    def test_claude_skill_entry_operation_matrix_matches_provider_authority(
        self,
    ) -> None:
        cases = {
            "standalone_skill": {
                "admitted": ("install", "remove", "restore"),
                "rejected": ("configure", "enable", "disable"),
            },
            "native_plugin": {
                "admitted": ("install",),
                "rejected": ("configure", "enable", "disable", "remove", "restore"),
            },
        }
        for provider_kind, dispositions in cases.items():
            for disposition, operations in dispositions.items():
                for operation in operations:
                    with self.subTest(
                        provider_kind=provider_kind,
                        operation=operation,
                        disposition=disposition,
                    ):
                        plan, document = _claude_skill_plan_and_action_set(
                            provider_kind, operation
                        )
                        result = admit_plan_action_set(
                            canonical_json_bytes(document),
                            PlanActionSetTrust(
                                validated_plan=plan,
                                expected_action_set_digest=str(
                                    document["action_set_digest"]
                                ),
                            ),
                        )
                        if disposition == "admitted":
                            self.assertIsInstance(result, AdmittedPlanActionSet)
                        else:
                            self.assertIsInstance(result, PlanActionSetRejection)
                            self.assertIn(
                                "PLAN_ACTION_TARGET_BINDING_INVALID",
                                _diagnostic_codes(result),
                            )

    def test_native_plugin_target_operation_matrix_is_manager_specific(
        self,
    ) -> None:
        automated_operations = {
            "claude": {"install", "enable", "disable"},
            "codex": {"install", "enable", "disable"},
            "cursor": set(),
        }
        operations = (
            "install",
            "configure",
            "enable",
            "disable",
            "remove",
            "restore",
        )
        for manager, automated in automated_operations.items():
            for operation in operations:
                with self.subTest(manager=manager, operation=operation):
                    plan, document = _native_plugin_plan_and_action_set(
                        manager, operation
                    )
                    result = admit_plan_action_set(
                        canonical_json_bytes(document),
                        PlanActionSetTrust(
                            validated_plan=plan,
                            expected_action_set_digest=str(
                                document["action_set_digest"]
                            ),
                        ),
                    )
                    if operation in automated:
                        self.assertIsInstance(result, AdmittedPlanActionSet)
                    else:
                        self.assertIsInstance(result, PlanActionSetRejection)
                        self.assertIn(
                            "PLAN_ACTION_TARGET_BINDING_INVALID",
                            _diagnostic_codes(result),
                        )

        for disposition in ("operator_action", "unavailable"):
            with self.subTest(disposition=disposition):
                plan, document = _native_plugin_plan_and_action_set(
                    "claude", "install"
                )
                original_digest = str(document["action_set_digest"])
                actions = document["actions"]
                assert isinstance(actions, list)
                evidence = actions[0]
                assert isinstance(evidence, dict)
                payload = evidence["action_payload"]
                assert isinstance(payload, dict)
                payload["operation_disposition"] = disposition
                _reseal_digest_fields_only(document)
                result = admit_plan_action_set(
                    canonical_json_bytes(document),
                    PlanActionSetTrust(
                        validated_plan=plan,
                        expected_action_set_digest=original_digest,
                    ),
                )
                self.assertIsInstance(result, PlanActionSetRejection)
                self.assertIn(
                    "PLAN_ACTION_SET_SCHEMA_INVALID",
                    _diagnostic_codes(result),
                )

    def test_direct_mcp_route_only_surface_admits_equipment_target(self) -> None:
        plan, document = _direct_mcp_plan_and_action_set(
            "codex", surface_rule="route_identity"
        )
        trust = PlanActionSetTrust(
            validated_plan=plan,
            expected_action_set_digest=str(document["action_set_digest"]),
        )

        result = admit_plan_action_set(canonical_json_bytes(document), trust)

        self.assertIsInstance(result, AdmittedPlanActionSet)

        attack = deepcopy(document)
        actions = attack["actions"]
        assert isinstance(actions, list)
        evidence = actions[0]
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        targets = payload["write_targets"]
        assert isinstance(targets, list)
        target = targets[0]
        assert isinstance(target, dict)
        _replace_target(target, equipment_identity="mcp:fixture/foreign")
        _reseal_digest_fields_only(attack)

        foreign_result = admit_plan_action_set(canonical_json_bytes(attack), trust)

        self.assertIsInstance(foreign_result, PlanActionSetRejection)
        self.assertIn(
            "PLAN_ACTION_TARGET_BINDING_INVALID",
            _diagnostic_codes(foreign_result),
        )

    def test_validated_route_owned_fields_bind_the_action_membership(self) -> None:
        for field in (
            "secret_references",
            "activation_group",
            "component_controls",
        ):
            with self.subTest(field=field):
                plan, document = _plan_with_foreign_route_field(field)
                trust = PlanActionSetTrust(
                    validated_plan=plan,
                    expected_action_set_digest=str(document["action_set_digest"]),
                )

                result = admit_plan_action_set(
                    canonical_json_bytes(document), trust
                )

                self.assertIsInstance(result, PlanActionSetRejection)
                self.assertIn(
                    "PLAN_ACTION_SET_MEMBERSHIP_INVALID",
                    _diagnostic_codes(result),
                )

    def test_component_controls_are_closed_unique_and_order_independent(
        self,
    ) -> None:
        unsorted_controls = [
            {"equipment_identity": "skill:fixture/example", "state": "disabled"},
            {"equipment_identity": "plugin:fixture/example", "state": "enabled"},
        ]
        with self.subTest(case="unsorted_valid"):
            plan, document = _plan_with_component_controls(unsorted_controls)
            valid_result = admit_plan_action_set(
                canonical_json_bytes(document),
                PlanActionSetTrust(
                    validated_plan=plan,
                    expected_action_set_digest=str(document["action_set_digest"]),
                ),
            )
            self.assertIsInstance(valid_result, AdmittedPlanActionSet)

        invalid_controls = {
            "duplicate": [unsorted_controls[0], deepcopy(unsorted_controls[0])],
            "invalid_state": [
                {
                    "equipment_identity": "skill:fixture/example",
                    "state": "attacker",
                }
            ],
            "extra_member": [
                {
                    "equipment_identity": "skill:fixture/example",
                    "state": "enabled",
                    "attacker": True,
                }
            ],
        }
        for case, controls in invalid_controls.items():
            with self.subTest(case=case):
                invalid_plan, invalid_document = _plan_with_component_controls(
                    controls
                )
                fixed_trust = PlanActionSetTrust(
                    validated_plan=invalid_plan,
                    expected_action_set_digest=str(
                        invalid_document["action_set_digest"]
                    ),
                )

                result = admit_plan_action_set(
                    canonical_json_bytes(invalid_document), fixed_trust
                )

                self.assertIsInstance(result, PlanActionSetRejection)
                self.assertIn(
                    "PLAN_ACTION_SET_MEMBERSHIP_INVALID",
                    _diagnostic_codes(result),
                )

    def test_direct_mcp_locator_is_exact(self) -> None:
        plan, document = _direct_mcp_plan_and_action_set("codex")
        trust = PlanActionSetTrust(
            validated_plan=plan,
            expected_action_set_digest=str(document["action_set_digest"]),
        )
        actions = document["actions"]
        assert isinstance(actions, list)
        evidence = actions[0]
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        targets = payload["write_targets"]
        assert isinstance(targets, list)
        target = targets[0]
        assert isinstance(target, dict)
        expected_equipment_identity = str(target["equipment_identity"])
        locator = target["locator"]
        assert isinstance(locator, dict)
        locator["source"] = "attacker-controlled"
        _replace_target(target)
        _reseal_digest_fields_only(document)

        result = admit_plan_action_set(canonical_json_bytes(document), trust)

        self.assertIsInstance(result, PlanActionSetRejection)
        self.assertIn(
            "PLAN_ACTION_TARGET_BINDING_INVALID",
            _diagnostic_codes(result),
        )
        assert isinstance(result, PlanActionSetRejection)
        diagnostic = next(
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code == "PLAN_ACTION_TARGET_BINDING_INVALID"
        )
        self.assertEqual(
            diagnostic.equipment_identity,
            expected_equipment_identity,
        )
        self.assertEqual(diagnostic.harness, payload["harness"])
        self.assertEqual(diagnostic.route_identity, payload["route_identity"])

    def test_plugin_selection_requires_its_exact_codex_config_key(self) -> None:
        plan, original = _plugin_selection_plan_and_action_set()
        fixed_trust = PlanActionSetTrust(
            validated_plan=plan,
            expected_action_set_digest=str(original["action_set_digest"]),
        )
        self.assertIsInstance(
            admit_plan_action_set(canonical_json_bytes(original), fixed_trust),
            AdmittedPlanActionSet,
        )
        mutations = {
            "owner": ("owner", "cursor"),
            "source": ("source", "attacker-controlled"),
            "key_path": ("key_path", ["plugins", "foreign@fixture"]),
        }
        for case, (field, value) in mutations.items():
            with self.subTest(case=case):
                document = deepcopy(original)
                actions = document["actions"]
                assert isinstance(actions, list)
                evidence = actions[0]
                assert isinstance(evidence, dict)
                payload = evidence["action_payload"]
                assert isinstance(payload, dict)
                targets = payload["write_targets"]
                assert isinstance(targets, list)
                target = targets[0]
                assert isinstance(target, dict)
                locator = target["locator"]
                assert isinstance(locator, dict)
                locator[field] = value
                _replace_target(target)
                _reseal_digest_fields_only(document)

                result = admit_plan_action_set(
                    canonical_json_bytes(document), fixed_trust
                )

                self.assertIsInstance(result, PlanActionSetRejection)
                self.assertIn(
                    "PLAN_ACTION_TARGET_BINDING_INVALID",
                    _diagnostic_codes(result),
                )

    def test_claude_plugin_configure_remains_unavailable(self) -> None:
        plan, document = _plugin_selection_plan_and_action_set("claude")
        fixed_trust = PlanActionSetTrust(
            validated_plan=plan,
            expected_action_set_digest=str(document["action_set_digest"]),
        )

        result = admit_plan_action_set(canonical_json_bytes(document), fixed_trust)

        self.assertIsInstance(result, PlanActionSetRejection)
        self.assertIn(
            "PLAN_ACTION_TARGET_BINDING_INVALID",
            _diagnostic_codes(result),
        )

    def test_configure_desired_state_is_derived_from_route_controls(self) -> None:
        route_controls = [
            {"equipment_identity": "plugin:fixture/example", "state": "disabled"},
            {"equipment_identity": "skill:fixture/aux", "state": "enabled"},
        ]
        cases = {
            "state_mismatch": [
                {"equipment_identity": "plugin:fixture/example", "state": "enabled"},
                route_controls[1],
            ],
            "missing_control": [route_controls[0]],
            "extra_control": [
                *route_controls,
                {"equipment_identity": "skill:fixture/extra", "state": "enabled"},
            ],
        }
        for case, desired_controls in cases.items():
            with self.subTest(case=case):
                plan, document = _plugin_selection_plan_and_action_set(
                    desired_controls=desired_controls
                )
                fixed_trust = PlanActionSetTrust(
                    validated_plan=plan,
                    expected_action_set_digest=str(document["action_set_digest"]),
                )

                result = admit_plan_action_set(
                    canonical_json_bytes(document), fixed_trust
                )

                self.assertIsInstance(result, PlanActionSetRejection)
                self.assertIn(
                    "PLAN_ACTION_SET_MEMBERSHIP_INVALID",
                    _diagnostic_codes(result),
                )

        plan, document = _plugin_selection_plan_and_action_set(
            configuration_digest="sha256:" + "0" * 64
        )
        fixed_trust = PlanActionSetTrust(
            validated_plan=plan,
            expected_action_set_digest=str(document["action_set_digest"]),
        )

        result = admit_plan_action_set(canonical_json_bytes(document), fixed_trust)

        self.assertIsInstance(result, PlanActionSetRejection)
        self.assertIn(
            "PLAN_ACTION_SET_MEMBERSHIP_INVALID",
            _diagnostic_codes(result),
        )

    def test_each_exact_surface_identity_rule_admits_only_its_derived_set(self) -> None:
        for rule in (
            "route_identity",
            "shared_equipment_identity",
            "route_and_equipment_identity",
        ):
            with self.subTest(rule=rule, disposition="valid"):
                plan, document = _surface_rule_plan_and_action_set(rule)
                trust = PlanActionSetTrust(
                    validated_plan=plan,
                    expected_action_set_digest=str(document["action_set_digest"]),
                )
                result = admit_plan_action_set(
                    canonical_json_bytes(document), trust
                )
                self.assertIsInstance(result, AdmittedPlanActionSet)

            with self.subTest(rule=rule, disposition="arbitrary-intermediate"):
                plan, document = _surface_rule_plan_and_action_set(rule)
                trust = PlanActionSetTrust(
                    validated_plan=plan,
                    expected_action_set_digest=str(document["action_set_digest"]),
                )
                attack = deepcopy(document)
                attack_actions = attack["actions"]
                assert isinstance(attack_actions, list)
                attack_evidence = attack_actions[0]
                assert isinstance(attack_evidence, dict)
                attack_payload = attack_evidence["action_payload"]
                assert isinstance(attack_payload, dict)
                attack_targets = attack_payload["write_targets"]
                assert isinstance(attack_targets, list)
                attack_target = attack_targets[0]
                assert isinstance(attack_target, dict)
                equipment = attack_target.get(
                    "equipment_identity", "plugin:fixture/example"
                )
                assert isinstance(equipment, str)
                route_identity = str(attack_payload["route_identity"])
                foreign_surface = (
                    f"surface:{route_identity}/attacker/{equipment}"
                    if rule != "shared_equipment_identity"
                    else f"surface:shared/attacker/{equipment}"
                )
                _replace_target(
                    attack_target,
                    write_surface_identity=foreign_surface,
                )
                attack_payload["surface_scope"] = [foreign_surface]
                attack_preconditions = attack_payload["preconditions"]
                assert isinstance(attack_preconditions, dict)
                attack_preconditions["surface_scope"] = [foreign_surface]
                _reseal_digest_fields_only(attack)

                foreign_result = admit_plan_action_set(
                    canonical_json_bytes(attack), trust
                )

                self.assertIsInstance(foreign_result, PlanActionSetRejection)
                self.assertIn(
                    "PLAN_ACTION_TARGET_BINDING_INVALID",
                    _diagnostic_codes(foreign_result),
                )

    def test_legacy_projector_fails_closed_until_locator_authority_exists(
        self,
    ) -> None:
        plan, document = _legacy_projector_plan_and_action_set()
        trust = PlanActionSetTrust(
            validated_plan=plan,
            expected_action_set_digest=str(document["action_set_digest"]),
        )

        result = admit_plan_action_set(canonical_json_bytes(document), trust)

        self.assertIsInstance(result, PlanActionSetRejection)
        self.assertEqual(
            _diagnostic_codes(result),
            ("PLAN_ACTION_TARGET_AUTHORITY_UNAVAILABLE",),
        )

    def test_direct_constructor_recomputes_the_canonical_set_digest(self) -> None:
        plan, document = _valid_plan_and_action_set()
        document["action_set_digest"] = "sha256:" + "0" * 64
        frozen = freeze_json(document)
        assert isinstance(frozen, type(freeze_json({})))

        with self.assertRaises(ValueError):
            AdmittedPlanActionSet(
                document=frozen,
                canonical_bytes=canonical_json_bytes(frozen),
                action_set_digest=str(document["action_set_digest"]),
                trust=PlanActionSetTrust(
                    validated_plan=plan,
                    expected_action_set_digest=str(document["action_set_digest"]),
                ),
            )

    def test_direct_constructor_cannot_bypass_complete_trust_membership(self) -> None:
        plan, document = _valid_plan_and_action_set()
        honest_digest = str(document["action_set_digest"])
        trust = PlanActionSetTrust(
            validated_plan=plan,
            expected_action_set_digest=honest_digest,
        )
        document["actions"] = []
        document["action_set_digest"] = canonical_json_sha256(
            {
                "schema_version": document["schema_version"],
                "candidate_identity": document["candidate_identity"],
                "implementation_manifest_digest": document[
                    "implementation_manifest_digest"
                ],
                "plan_digest": document["plan_digest"],
                "actions": [],
            }
        )
        frozen = freeze_json(document)
        assert isinstance(frozen, type(freeze_json({})))

        with self.assertRaises(ValueError):
            AdmittedPlanActionSet(
                document=frozen,
                canonical_bytes=canonical_json_bytes(frozen),
                action_set_digest=str(document["action_set_digest"]),
                trust=trust,
            )

        for attribute_name, candidate in vars(plan_action_set_module).items():
            with (
                self.subTest(imported_attribute=attribute_name),
                self.assertRaisesRegex(
                    (TypeError, ValueError),
                    "admitted plan-action set requires typed trust",
                ),
            ):
                AdmittedPlanActionSet(
                    document=frozen,
                    canonical_bytes=canonical_json_bytes(frozen),
                    action_set_digest=str(document["action_set_digest"]),
                    trust=candidate,  # type: ignore[arg-type]
                )


if __name__ == "__main__":
    unittest.main()
