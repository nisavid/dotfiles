"""Projection and admission coverage for the settled physical-target matrix.

Each row supplies an independently constructed validated plan and records
whether production projection and the separate public admission seam accept
the settled one-to-one target contract. This keeps unsupported shapes outside
capture, checkpoint, and adapter authority.
"""

from __future__ import annotations

import unittest
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass

from agent_equipment.canonical import canonical_json_bytes, canonical_json_sha256
from agent_equipment.model import PlanNode, ValidatedPlan, freeze_json, thaw_json
from agent_equipment.plan_action_set import (
    AdmittedPlanActionSet,
    PlanActionSetProjectionRejection,
    PlanActionSetRejection,
    PlanActionSetTrust,
    ProjectedPlanActionSet,
    admit_plan_action_set,
    project_plan_action_set,
)
from tests.agent_equipment.test_plan_action_set import (
    _claude_skill_plan_and_action_set,
    _direct_mcp_plan_and_action_set,
    _legacy_projector_plan_and_action_set,
    _native_plugin_plan_and_action_set,
    _plugin_selection_plan_and_action_set,
    _rebuild_plan_for_document,
    _reseal,
    _surface_rule_plan_and_action_set,
    _valid_plan_and_action_set,
)

Builder = Callable[[], tuple[ValidatedPlan, dict[str, object]]]
TargetMutation = Callable[
    [ValidatedPlan, dict[str, object], dict[str, object]], ValidatedPlan
]


@dataclass(frozen=True)
class MatrixCase:
    """One explicit provider/operation row in the supported target matrix."""

    name: str
    builder: Builder
    admitted: bool
    diagnostic: str | None = None


def _recomputed_set_digest(document: dict[str, object]) -> str:
    """Recompute internal consistency from one supplied projection."""

    actions = document.get("actions")
    assert isinstance(actions, list)
    ordered_actions = sorted(
        deepcopy(actions),
        key=lambda action: (
            int(action["action_payload"]["ordinal"]),
            str(action["action_payload"]["action_identity"]),
        ),
    )
    return canonical_json_sha256(
        {
            "schema_version": document["schema_version"],
            "candidate_identity": document["candidate_identity"],
            "implementation_manifest_digest": document[
                "implementation_manifest_digest"
            ],
            "plan_digest": document["plan_digest"],
            "actions": ordered_actions,
        }
    )


def _admit(
    plan: ValidatedPlan,
    document: dict[str, object],
) -> AdmittedPlanActionSet | PlanActionSetRejection:
    trust = PlanActionSetTrust(
        validated_plan=plan,
        expected_action_set_digest=_recomputed_set_digest(document),
    )
    result = admit_plan_action_set(canonical_json_bytes(document), trust)
    return result


def _diagnostic_codes(result: object) -> tuple[str, ...]:
    return tuple(diagnostic.code for diagnostic in getattr(result, "diagnostics", ()))


def _plan_from_mutation_definitions(
    template: ValidatedPlan,
    definitions: tuple[object, ...],
) -> ValidatedPlan:
    typed_definitions = tuple(freeze_json(definition) for definition in definitions)
    assert all(
        type(definition) is type(freeze_json({})) for definition in typed_definitions
    )
    final_definition = freeze_json({"purpose": "final_coverage"})
    assert type(final_definition) is type(freeze_json({}))
    preimage = freeze_json(
        {
            "schema_version": "agent-equipment-plan-preimage/v1",
            "candidate_identity": template.preimage.get("candidate_identity"),
            "implementation_manifest_digest": template.preimage.get(
                "implementation_manifest_digest"
            ),
            "catalog_digest": template.preimage.get("catalog_digest"),
            "lock_digest": template.preimage.get("lock_digest"),
            "inventory_digest": template.preimage.get("inventory_digest"),
            "capability_set_digest": template.preimage.get("capability_set_digest"),
            "nodes": [
                {
                    "ordinal": ordinal,
                    "kind": "mutation",
                    "definition": definition,
                }
                for ordinal, definition in enumerate(typed_definitions)
            ]
            + [
                {
                    "ordinal": len(typed_definitions),
                    "kind": "verification",
                    "definition": final_definition,
                }
            ],
            "edges": [
                [ordinal, len(typed_definitions)]
                for ordinal in range(len(typed_definitions))
            ],
        }
    )
    assert type(preimage) is type(freeze_json({}))
    plan_digest = canonical_json_sha256(preimage)
    mutations: list[PlanNode] = []
    for ordinal, definition in enumerate(typed_definitions):
        assert type(definition) is type(freeze_json({}))
        identity = "action:" + canonical_json_sha256(
            {
                "plan_digest": plan_digest,
                "ordinal": ordinal,
                "route_id": definition.get("route_identity"),
                "operation": definition.get("operation"),
                "desired_state_digest": definition.get("desired_state_digest"),
            }
        )
        mutations.append(
            PlanNode(
                key=f"mutation:{ordinal}",
                kind="mutation",
                ordinal=ordinal,
                identity=identity,
                dependencies=(),
                definition=definition,
            )
        )
    dependencies = tuple(node.identity for node in mutations)
    final_identity = "verification:" + canonical_json_sha256(
        {
            "plan_digest": plan_digest,
            "ordinal": len(mutations),
            "semantic_definition_digest": canonical_json_sha256(final_definition),
            "predecessor_identities": dependencies,
        }
    )
    final = PlanNode(
        key="verification:final",
        kind="verification",
        ordinal=len(mutations),
        identity=final_identity,
        dependencies=dependencies,
        definition=final_definition,
    )
    return ValidatedPlan(
        nodes=(*mutations, final),
        edges=tuple((identity, final_identity) for identity in dependencies),
        digest=plan_digest,
        preimage=preimage,
    )


def _plan_with_interleaved_verification(
    template: ValidatedPlan,
    first_definition: object,
    second_definition: object,
) -> ValidatedPlan:
    first = freeze_json(first_definition)
    second = freeze_json(second_definition)
    middle = freeze_json({"purpose": "winner_activation"})
    final = freeze_json({"purpose": "final_coverage"})
    assert all(
        type(value) is type(freeze_json({})) for value in (first, second, middle, final)
    )
    preimage = freeze_json(
        {
            "schema_version": "agent-equipment-plan-preimage/v1",
            "candidate_identity": template.preimage.get("candidate_identity"),
            "implementation_manifest_digest": template.preimage.get(
                "implementation_manifest_digest"
            ),
            "catalog_digest": template.preimage.get("catalog_digest"),
            "lock_digest": template.preimage.get("lock_digest"),
            "inventory_digest": template.preimage.get("inventory_digest"),
            "capability_set_digest": template.preimage.get("capability_set_digest"),
            "nodes": [
                {"ordinal": 0, "kind": "mutation", "definition": first},
                {"ordinal": 1, "kind": "verification", "definition": middle},
                {"ordinal": 2, "kind": "mutation", "definition": second},
                {"ordinal": 3, "kind": "verification", "definition": final},
            ],
            "edges": [[0, 1], [1, 2], [2, 3]],
        }
    )
    assert type(preimage) is type(freeze_json({}))
    digest = canonical_json_sha256(preimage)
    assert type(first) is type(freeze_json({}))
    assert type(second) is type(freeze_json({}))
    assert type(middle) is type(freeze_json({}))
    assert type(final) is type(freeze_json({}))
    first_identity = "action:" + canonical_json_sha256(
        {
            "plan_digest": digest,
            "ordinal": 0,
            "route_id": first.get("route_identity"),
            "operation": first.get("operation"),
            "desired_state_digest": first.get("desired_state_digest"),
        }
    )
    middle_identity = "verification:" + canonical_json_sha256(
        {
            "plan_digest": digest,
            "ordinal": 1,
            "semantic_definition_digest": canonical_json_sha256(middle),
            "predecessor_identities": (first_identity,),
        }
    )
    second_identity = "action:" + canonical_json_sha256(
        {
            "plan_digest": digest,
            "ordinal": 2,
            "route_id": second.get("route_identity"),
            "operation": second.get("operation"),
            "desired_state_digest": second.get("desired_state_digest"),
        }
    )
    final_identity = "verification:" + canonical_json_sha256(
        {
            "plan_digest": digest,
            "ordinal": 3,
            "semantic_definition_digest": canonical_json_sha256(final),
            "predecessor_identities": (second_identity,),
        }
    )
    nodes = (
        PlanNode("mutation:first", "mutation", 0, first_identity, (), first),
        PlanNode(
            "verification:middle",
            "verification",
            1,
            middle_identity,
            (first_identity,),
            middle,
        ),
        PlanNode(
            "mutation:second",
            "mutation",
            2,
            second_identity,
            (middle_identity,),
            second,
        ),
        PlanNode(
            "verification:final",
            "verification",
            3,
            final_identity,
            (second_identity,),
            final,
        ),
    )
    return ValidatedPlan(
        nodes=nodes,
        edges=(
            (first_identity, middle_identity),
            (middle_identity, second_identity),
            (second_identity, final_identity),
        ),
        digest=digest,
        preimage=preimage,
    )


def _rebind_target_surface(
    plan: ValidatedPlan,
    document: dict[str, object],
    target: dict[str, object],
    *,
    equipment_identity: str,
) -> ValidatedPlan:
    """Keep the mutated target and its trusted plan scope internally coherent."""

    actions = document["actions"]
    assert isinstance(actions, list)
    payload = actions[0]["action_payload"]
    assert isinstance(payload, dict)
    route_identity = payload["route_identity"]
    assert isinstance(route_identity, str)
    surface = f"surface:{route_identity}/{equipment_identity}"
    target["equipment_identity"] = equipment_identity
    target["write_surface_identity"] = surface
    payload["surface_scope"] = [surface]
    preconditions = payload["preconditions"]
    assert isinstance(preconditions, dict)
    preconditions["surface_scope"] = [surface]
    payload["equipment_identities"] = [equipment_identity]

    definition = thaw_json(plan.nodes[0].definition)
    assert isinstance(definition, dict)
    definition["equipment_identities"] = [equipment_identity]
    definition["surface_scope"] = [surface]
    return _rebuild_plan_for_document(plan, document, definition)


def _foreign_selection_owner(
    plan: ValidatedPlan,
    _document: dict[str, object],
    target: dict[str, object],
) -> ValidatedPlan:
    locator = target["locator"]
    assert isinstance(locator, dict)
    locator["owner"] = "cursor"
    return plan


def _wrong_kind_target(
    plan: ValidatedPlan,
    document: dict[str, object],
    target: dict[str, object],
) -> ValidatedPlan:
    target.update(
        {
            "surface_kind": "plugin_selection",
            "locator": {
                "owner": "claude",
                "source": "settings",
                "key_path": ["enabledPlugins", "example@fixture"],
            },
        }
    )
    return _rebind_target_surface(
        plan,
        document,
        target,
        equipment_identity="plugin:fixture/example",
    )


def _unrepresentable_mcp_target(
    plan: ValidatedPlan,
    document: dict[str, object],
    target: dict[str, object],
) -> ValidatedPlan:
    target.update(
        {
            "surface_kind": "mcp_selection",
            "locator": {
                "owner": "claude",
                "source": "settings",
                "key_path": ["mcpServers", "context7"],
            },
        }
    )
    return _rebind_target_surface(
        plan,
        document,
        target,
        equipment_identity="mcp:fixture/context7",
    )


def _matrix_cases() -> tuple[MatrixCase, ...]:
    """Return the settled matrix as data so every row is reviewable."""

    cases: list[MatrixCase] = []

    for manager in ("claude", "codex"):
        for operation in ("install", "enable", "disable"):
            cases.append(
                MatrixCase(
                    f"native-plugin/{manager}/{operation}",
                    lambda manager=manager, operation=operation: (
                        _native_plugin_plan_and_action_set(manager, operation)
                    ),
                    True,
                )
            )
        for operation in ("remove", "restore", "suppress_native_update"):
            cases.append(
                MatrixCase(
                    f"native-plugin/{manager}/{operation}",
                    lambda manager=manager, operation=operation: (
                        _native_plugin_plan_and_action_set(manager, operation)
                    ),
                    False,
                    "PLAN_ACTION_TARGET_BINDING_INVALID",
                )
            )

    for operation in ("install", "remove", "restore"):
        cases.append(
            MatrixCase(
                f"standalone-claude-skill/{operation}",
                lambda operation=operation: _claude_skill_plan_and_action_set(
                    "standalone_skill", operation
                ),
                True,
            )
        )
    for operation in (
        "install",
        "configure",
        "enable",
        "disable",
        "remove",
        "restore",
    ):
        cases.append(
            MatrixCase(
                f"native-plugin-claude-skill/{operation}",
                lambda operation=operation: _claude_skill_plan_and_action_set(
                    "native_plugin", operation
                ),
                operation == "install",
                "PLAN_ACTION_TARGET_BINDING_INVALID",
            )
        )

    for harness in ("claude", "codex", "cursor"):
        for operation in ("configure", "enable", "disable", "remove", "restore"):
            cases.append(
                MatrixCase(
                    f"direct-mcp/{harness}/{operation}",
                    lambda harness=harness, operation=operation: (
                        _direct_mcp_plan_and_action_set(harness, operation)
                    ),
                    True,
                )
            )
        cases.append(
            MatrixCase(
                f"direct-mcp/{harness}/install",
                lambda harness=harness: _direct_mcp_plan_and_action_set(
                    harness, "install"
                ),
                False,
                "PLAN_ACTION_TARGET_BINDING_INVALID",
            )
        )

    cases.extend(
        (
            MatrixCase(
                "plugin-selection/codex/configure",
                lambda: _plugin_selection_plan_and_action_set("codex"),
                True,
            ),
            MatrixCase(
                "plugin-selection/claude/configure",
                lambda: _plugin_selection_plan_and_action_set("claude"),
                False,
                "PLAN_ACTION_TARGET_BINDING_INVALID",
            ),
            MatrixCase(
                "legacy-projector/claude/configure",
                _legacy_projector_plan_and_action_set,
                False,
                "PLAN_ACTION_TARGET_AUTHORITY_UNAVAILABLE",
            ),
        )
    )
    return tuple(cases)


class SupportedTargetMatrixTest(unittest.TestCase):
    def test_supported_matrix_is_explicit_and_complete(self) -> None:
        cases = _matrix_cases()
        self.assertEqual(len(cases), 42)

        for case in cases:
            with self.subTest(case=case.name):
                plan, document = case.builder()
                result = _admit(plan, document)
                if case.admitted:
                    self.assertIsInstance(result, AdmittedPlanActionSet)
                else:
                    self.assertIsInstance(result, PlanActionSetRejection)
                    assert isinstance(result, PlanActionSetRejection)
                    self.assertIn(case.diagnostic, _diagnostic_codes(result))

    def test_route_and_equipment_component_scope_requires_one_target_per_identity(
        self,
    ) -> None:
        """A resolver binding is valid; an inferred split is not."""

        route_plan, route_document = _plugin_selection_plan_and_action_set("codex")
        self.assertIsInstance(_admit(route_plan, route_document), AdmittedPlanActionSet)

        split_plan, split_document = _surface_rule_plan_and_action_set(
            "route_and_equipment_identity"
        )
        result = _admit(split_plan, split_document)
        self.assertIsInstance(result, AdmittedPlanActionSet)

        # Turn the exact multi-equipment scope into a single selection target.
        # Admission must reject this rather than inventing a route slot or
        # coalescing the missing component write.
        split_actions = split_document["actions"]
        assert isinstance(split_actions, list)
        payload = split_actions[0]["action_payload"]
        assert isinstance(payload, dict)
        payload["write_targets"] = [payload["write_targets"][0]]
        payload["surface_scope"] = [payload["surface_scope"][0]]
        payload["preconditions"]["surface_scope"] = list(payload["surface_scope"])
        _reseal(split_document)
        rejected = _admit(split_plan, split_document)
        self.assertIsInstance(rejected, PlanActionSetRejection)
        assert isinstance(rejected, PlanActionSetRejection)
        self.assertIn("PLAN_ACTION_SET_MEMBERSHIP_INVALID", _diagnostic_codes(rejected))
        self.assertIn("PLAN_ACTION_TARGET_SCOPE_INVALID", _diagnostic_codes(rejected))

    def test_unrepresentable_foreign_wrong_kind_and_duplicate_shapes_fail_closed(
        self,
    ) -> None:
        """No inferred locator, owner, route slot, coalescing, or splitting."""

        mutations: tuple[
            str,
            Builder,
            TargetMutation,
            str,
        ] = (
            (
                "foreign-selection-owner",
                lambda: _plugin_selection_plan_and_action_set("codex"),
                _foreign_selection_owner,
                "PLAN_ACTION_TARGET_BINDING_INVALID",
            ),
            (
                "wrong-kind-native-as-selection",
                lambda: _native_plugin_plan_and_action_set("claude", "install"),
                lambda plan, document, target: _wrong_kind_target(
                    plan, document, target
                ),
                "PLAN_ACTION_TARGET_BINDING_INVALID",
            ),
            (
                "unrepresentable-native-mcp-surface",
                lambda: _native_plugin_plan_and_action_set("claude", "install"),
                lambda plan, document, target: _unrepresentable_mcp_target(
                    plan, document, target
                ),
                "PLAN_ACTION_TARGET_BINDING_INVALID",
            ),
        )

        for name, builder, mutate, expected_code in mutations:
            with self.subTest(shape=name):
                plan, document = builder()
                payload = document["actions"][0]["action_payload"]
                assert isinstance(payload, dict)
                target = payload["write_targets"][0]
                assert isinstance(target, dict)
                plan = mutate(plan, document, target)
                target["target_identity"] = "target:" + canonical_json_sha256(
                    {
                        "surface_kind": target["surface_kind"],
                        "locator": target["locator"],
                        **(
                            {"equipment_identity": target["equipment_identity"]}
                            if "equipment_identity" in target
                            else {}
                        ),
                    }
                )
                payload["write_targets"].sort(
                    key=lambda item: str(item["target_identity"])
                )
                _reseal(document)
                result = _admit(plan, document)
                self.assertIsInstance(result, PlanActionSetRejection)
                assert isinstance(result, PlanActionSetRejection)
                self.assertIn(expected_code, _diagnostic_codes(result))
                self.assertNotIsInstance(result, AdmittedPlanActionSet)

        plan, document = _direct_mcp_plan_and_action_set("codex")
        payload = document["actions"][0]["action_payload"]
        assert isinstance(payload, dict)
        original_target = payload["write_targets"][0]
        duplicate = deepcopy(original_target)
        assert isinstance(duplicate, dict)
        duplicate["equipment_identity"] = "mcp:fixture/other"
        duplicate["write_surface_identity"] = (
            "surface:route:fixture/codex-direct-mcp/mcp:fixture/other"
        )
        duplicate["target_identity"] = "target:" + canonical_json_sha256(
            {
                "surface_kind": duplicate["surface_kind"],
                "locator": duplicate["locator"],
                "equipment_identity": duplicate["equipment_identity"],
            }
        )
        payload["write_targets"].append(duplicate)
        payload["write_targets"].sort(key=lambda item: str(item["target_identity"]))
        payload["surface_scope"].append(duplicate["write_surface_identity"])
        payload["surface_scope"].sort()
        payload["preconditions"]["surface_scope"] = list(payload["surface_scope"])
        _reseal(document)
        rejected = _admit(plan, document)
        self.assertIsInstance(rejected, PlanActionSetRejection)
        assert isinstance(rejected, PlanActionSetRejection)
        self.assertIn(
            "PLAN_ACTION_PHYSICAL_TARGET_DUPLICATE",
            _diagnostic_codes(rejected),
        )


class PlanActionSetProjectionTargetMatrixTest(unittest.TestCase):
    def test_direct_mcp_configure_projects_one_immutable_admissible_artifact(
        self,
    ) -> None:
        plan, expected_document = _direct_mcp_plan_and_action_set("codex")
        trusted_set_digest = str(expected_document["action_set_digest"])

        projected = project_plan_action_set(plan)

        self.assertIsInstance(projected, ProjectedPlanActionSet)
        assert isinstance(projected, ProjectedPlanActionSet)
        self.assertEqual(
            projected.canonical_bytes,
            canonical_json_bytes(projected.document),
        )
        self.assertEqual(
            projected.action_set_digest,
            _recomputed_set_digest(thaw_json(projected.document)),
        )
        self.assertEqual(projected.action_set_digest, trusted_set_digest)
        admitted = admit_plan_action_set(
            projected.canonical_bytes,
            PlanActionSetTrust(
                validated_plan=plan,
                expected_action_set_digest=trusted_set_digest,
            ),
        )
        self.assertIsInstance(admitted, AdmittedPlanActionSet)

    def test_exact_42_row_matrix_projects_or_rejects_atomically(self) -> None:
        cases = _matrix_cases()
        self.assertEqual(len(cases), 42)

        for case in cases:
            with self.subTest(case=case.name):
                plan, expected_document = case.builder()
                result = project_plan_action_set(plan)
                if case.admitted:
                    self.assertIsInstance(result, ProjectedPlanActionSet)
                    assert isinstance(result, ProjectedPlanActionSet)
                    recomputed_digest = _recomputed_set_digest(
                        thaw_json(result.document)
                    )
                    self.assertEqual(
                        result.action_set_digest,
                        recomputed_digest,
                    )
                    trusted_set_digest = str(expected_document["action_set_digest"])
                    self.assertEqual(result.action_set_digest, trusted_set_digest)
                    admitted = admit_plan_action_set(
                        result.canonical_bytes,
                        PlanActionSetTrust(
                            validated_plan=plan,
                            expected_action_set_digest=trusted_set_digest,
                        ),
                    )
                    self.assertIsInstance(admitted, AdmittedPlanActionSet)
                else:
                    self.assertIsInstance(
                        result,
                        PlanActionSetProjectionRejection,
                    )
                    assert isinstance(result, PlanActionSetProjectionRejection)
                    self.assertEqual(
                        tuple(diagnostic.code for diagnostic in result.diagnostics),
                        (case.diagnostic,),
                    )
                    self.assertFalse(hasattr(result, "document"))

    def test_combined_claude_native_install_projects_plugin_skill_and_dependency(
        self,
    ) -> None:
        plan, _ = _valid_plan_and_action_set()

        result = project_plan_action_set(plan)

        self.assertIsInstance(result, ProjectedPlanActionSet)
        assert isinstance(result, ProjectedPlanActionSet)
        actions = result.document.get("actions")
        assert isinstance(actions, tuple) and len(actions) == 1
        payload = actions[0].get("action_payload")
        assert type(payload) is type(freeze_json({}))
        targets = payload.get("write_targets")
        dependencies = payload.get("verification_dependencies")
        assert isinstance(targets, tuple)
        assert isinstance(dependencies, tuple)
        self.assertEqual(
            tuple(sorted(target.get("surface_kind") for target in targets)),
            ("claude_skill_entry", "plugin_installation"),
        )
        self.assertEqual(len(dependencies), 1)
        dependency = dependencies[0]
        self.assertEqual(
            dependency.get("relationship"),
            "canonical_skill_projection",
        )
        self.assertEqual(
            dependency.get("target_locator"),
            freeze_json({"path": "~/.agents/skills/example"}),
        )
        self.assertEqual(
            dependency.get("dependency_identity"),
            "dependency:"
            + canonical_json_sha256(
                {
                    "relationship": "canonical_skill_projection",
                    "write_surface_identity": dependency.get("write_surface_identity"),
                    "equipment_identity": dependency.get("equipment_identity"),
                    "target_locator": {"path": "~/.agents/skills/example"},
                }
            ),
        )

    def test_zero_mutation_plan_projects_one_valid_empty_set(self) -> None:
        template, _ = _direct_mcp_plan_and_action_set("codex")
        plan = _plan_from_mutation_definitions(template, ())
        trusted_set_digest = canonical_json_sha256(
            {
                "schema_version": "agent-equipment-plan-action-set/v1",
                "candidate_identity": plan.preimage.get("candidate_identity"),
                "implementation_manifest_digest": plan.preimage.get(
                    "implementation_manifest_digest"
                ),
                "plan_digest": plan.digest,
                "actions": (),
            }
        )

        result = project_plan_action_set(plan)

        self.assertIsInstance(result, ProjectedPlanActionSet)
        assert isinstance(result, ProjectedPlanActionSet)
        self.assertEqual(result.document.get("actions"), ())
        recomputed_digest = _recomputed_set_digest(thaw_json(result.document))
        self.assertEqual(result.action_set_digest, recomputed_digest)
        self.assertEqual(result.action_set_digest, trusted_set_digest)
        self.assertIsInstance(
            admit_plan_action_set(
                result.canonical_bytes,
                PlanActionSetTrust(plan, trusted_set_digest),
            ),
            AdmittedPlanActionSet,
        )

    def test_interleaved_verification_preserves_all_mutation_ordinals_and_bytes(
        self,
    ) -> None:
        first, _ = _direct_mcp_plan_and_action_set("codex", "configure")
        second, _ = _direct_mcp_plan_and_action_set("cursor", "enable")
        plan = _plan_with_interleaved_verification(
            first,
            first.nodes[0].definition,
            second.nodes[0].definition,
        )

        projected = project_plan_action_set(plan)
        repeated = project_plan_action_set(plan)

        self.assertIsInstance(projected, ProjectedPlanActionSet)
        self.assertEqual(projected, repeated)
        assert isinstance(projected, ProjectedPlanActionSet)
        actions = projected.document.get("actions")
        assert isinstance(actions, tuple)
        payloads = tuple(action.get("action_payload") for action in actions)
        self.assertEqual(
            tuple(payload.get("ordinal") for payload in payloads),
            (0, 2),
        )
        self.assertEqual(
            tuple(payload.get("action_identity") for payload in payloads),
            tuple(node.identity for node in plan.nodes if node.kind == "mutation"),
        )
        self.assertEqual(
            projected.canonical_bytes,
            canonical_json_bytes(projected.document),
        )

    def test_one_unsupported_node_rejects_the_complete_mixed_plan(self) -> None:
        supported, _ = _direct_mcp_plan_and_action_set("codex")
        unsupported, _ = _legacy_projector_plan_and_action_set()
        plan = _plan_from_mutation_definitions(
            supported,
            (
                supported.nodes[0].definition,
                unsupported.nodes[0].definition,
            ),
        )

        result = project_plan_action_set(plan)

        self.assertIsInstance(result, PlanActionSetProjectionRejection)
        assert isinstance(result, PlanActionSetProjectionRejection)
        self.assertEqual(
            tuple(diagnostic.code for diagnostic in result.diagnostics),
            ("PLAN_ACTION_TARGET_AUTHORITY_UNAVAILABLE",),
        )
        for partial_field in ("document", "canonical_bytes", "action_set_digest"):
            self.assertFalse(hasattr(result, partial_field))

    def test_missing_extra_reordered_and_foreign_bindings_reject_without_artifact(
        self,
    ) -> None:
        direct, _ = _direct_mcp_plan_and_action_set("codex")
        native, _ = _valid_plan_and_action_set()
        direct_definition = thaw_json(direct.nodes[0].definition)
        native_definition = thaw_json(native.nodes[0].definition)
        assert isinstance(direct_definition, dict)
        assert isinstance(native_definition, dict)
        cases: dict[str, tuple[ValidatedPlan, dict[str, object]]] = {}

        missing = deepcopy(direct_definition)
        missing.pop("route_record")
        cases["missing"] = (direct, missing)

        extra = deepcopy(direct_definition)
        extra["equipment_identities"] = [
            *extra["equipment_identities"],
            "skill:fixture/foreign",
        ]
        cases["extra"] = (direct, extra)

        reordered = deepcopy(native_definition)
        reordered["equipment_identities"] = list(
            reversed(reordered["equipment_identities"])
        )
        cases["reordered"] = (native, reordered)

        foreign = deepcopy(direct_definition)
        foreign["surface_scope"] = ["surface:route:foreign/mcp:fixture/context7"]
        cases["foreign"] = (direct, foreign)

        for name, (template, definition) in cases.items():
            with self.subTest(binding=name):
                plan = _plan_from_mutation_definitions(template, (definition,))
                result = project_plan_action_set(plan)
                self.assertIsInstance(result, PlanActionSetProjectionRejection)
                self.assertFalse(hasattr(result, "document"))

    def test_duplicate_physical_locator_and_skill_basename_collision_reject(
        self,
    ) -> None:
        configure, _ = _direct_mcp_plan_and_action_set("codex", "configure")
        enable, _ = _direct_mcp_plan_and_action_set("codex", "enable")
        duplicate_plan = _plan_from_mutation_definitions(
            configure,
            (configure.nodes[0].definition, enable.nodes[0].definition),
        )

        duplicate_result = project_plan_action_set(duplicate_plan)

        self.assertIsInstance(
            duplicate_result,
            PlanActionSetProjectionRejection,
        )
        self.assertIn(
            "PLAN_ACTION_PHYSICAL_TARGET_DUPLICATE",
            _diagnostic_codes(duplicate_result),
        )

        standalone, _ = _claude_skill_plan_and_action_set("standalone_skill", "install")
        collision = thaw_json(standalone.nodes[0].definition)
        assert isinstance(collision, dict)
        collision["equipment_identities"] = [
            "skill:first/example",
            "skill:second/example",
        ]
        route_identity = collision["route_identity"]
        collision["surface_scope"] = [
            f"surface:{route_identity}/skill:first/example",
            f"surface:{route_identity}/skill:second/example",
        ]
        collision_plan = _plan_from_mutation_definitions(
            standalone,
            (collision,),
        )

        collision_result = project_plan_action_set(collision_plan)

        self.assertIsInstance(
            collision_result,
            PlanActionSetProjectionRejection,
        )
        self.assertIn(
            "PLAN_ACTION_PHYSICAL_TARGET_DUPLICATE",
            _diagnostic_codes(collision_result),
        )

    def test_unsupported_native_configure_and_cursor_native_reject(self) -> None:
        cases = (
            _native_plugin_plan_and_action_set("claude", "configure")[0],
            _native_plugin_plan_and_action_set("cursor", "install")[0],
        )
        for plan in cases:
            with self.subTest(route=plan.nodes[0].definition.get("route_identity")):
                result = project_plan_action_set(plan)
                self.assertIsInstance(result, PlanActionSetProjectionRejection)
                self.assertEqual(
                    _diagnostic_codes(result),
                    ("PLAN_ACTION_TARGET_BINDING_INVALID",),
                )

    def test_malformed_mixed_identity_node_returns_only_typed_diagnostics(
        self,
    ) -> None:
        template, _ = _direct_mcp_plan_and_action_set("codex")
        definition = thaw_json(template.nodes[0].definition)
        assert isinstance(definition, dict)
        definition["equipment_identities"] = [
            "mcp:fixture/context7",
            {"malformed": "identity"},
        ]
        plan = _plan_from_mutation_definitions(template, (definition,))

        result = project_plan_action_set(plan)

        self.assertIsInstance(result, PlanActionSetProjectionRejection)
        self.assertEqual(
            _diagnostic_codes(result),
            ("PLAN_ACTION_TARGET_BINDING_INVALID",),
        )
        self.assertFalse(hasattr(result, "document"))

    def test_native_install_respects_route_wide_and_shared_surface_rules(
        self,
    ) -> None:
        template, _ = _valid_plan_and_action_set()
        definition = thaw_json(template.nodes[0].definition)
        assert isinstance(definition, dict)
        route_identity = definition["route_identity"]
        equipment = definition["equipment_identities"]
        assert isinstance(route_identity, str)
        assert isinstance(equipment, list)

        route_wide = deepcopy(definition)
        route_wide["surface_scope"] = [f"surface:{route_identity}"]
        route_plan = _plan_from_mutation_definitions(template, (route_wide,))

        route_result = project_plan_action_set(route_plan)

        self.assertIsInstance(route_result, ProjectedPlanActionSet)
        assert isinstance(route_result, ProjectedPlanActionSet)
        route_actions = route_result.document.get("actions")
        assert isinstance(route_actions, tuple)
        route_payload = route_actions[0].get("action_payload")
        assert type(route_payload) is type(freeze_json({}))
        route_targets = route_payload.get("write_targets")
        self.assertEqual(len(route_targets), 1)
        self.assertEqual(
            route_targets[0].get("surface_kind"),
            "plugin_installation",
        )
        self.assertEqual(route_payload.get("verification_dependencies"), ())

        shared = deepcopy(definition)
        shared["surface_scope"] = [
            f"surface:shared/{identity}" for identity in equipment
        ]
        shared_plan = _plan_from_mutation_definitions(template, (shared,))

        shared_result = project_plan_action_set(shared_plan)

        self.assertIsInstance(shared_result, ProjectedPlanActionSet)
        assert isinstance(shared_result, ProjectedPlanActionSet)
        shared_actions = shared_result.document.get("actions")
        assert isinstance(shared_actions, tuple)
        shared_payload = shared_actions[0].get("action_payload")
        assert type(shared_payload) is type(freeze_json({}))
        self.assertEqual(len(shared_payload.get("write_targets")), 2)
        self.assertEqual(len(shared_payload.get("verification_dependencies")), 1)


class ConstructorBypassTargetMatrixTest(unittest.TestCase):
    def _construct_directly(
        self,
        plan: ValidatedPlan,
        document: dict[str, object],
    ) -> AdmittedPlanActionSet:
        frozen = freeze_json(document)
        assert type(frozen) is type(freeze_json({}))
        digest = _recomputed_set_digest(document)
        return AdmittedPlanActionSet(
            document=frozen,
            canonical_bytes=canonical_json_bytes(frozen),
            action_set_digest=digest,
            trust=PlanActionSetTrust(
                validated_plan=plan,
                expected_action_set_digest=digest,
            ),
        )

    def test_direct_constructor_cannot_admit_a_resealed_foreign_target(self) -> None:
        plan, document = _direct_mcp_plan_and_action_set("codex")
        payload = document["actions"][0]["action_payload"]
        assert isinstance(payload, dict)
        target = payload["write_targets"][0]
        assert isinstance(target, dict)
        target["locator"]["source"] = "foreign-config"
        target["target_identity"] = "target:" + canonical_json_sha256(
            {
                "surface_kind": target["surface_kind"],
                "locator": target["locator"],
                "equipment_identity": target["equipment_identity"],
            }
        )
        _reseal(document)

        with self.assertRaises(ValueError):
            self._construct_directly(plan, document)

    def test_direct_constructor_cannot_admit_the_legacy_projector(self) -> None:
        plan, document = _legacy_projector_plan_and_action_set()

        with self.assertRaises(ValueError):
            self._construct_directly(plan, document)

    def test_direct_constructor_rejects_untrusted_bytes_and_digest(self) -> None:
        plan, document = _valid_plan_and_action_set()
        frozen = freeze_json(document)
        assert type(frozen) is type(freeze_json({}))
        trust = PlanActionSetTrust(
            validated_plan=plan,
            expected_action_set_digest=_recomputed_set_digest(document),
        )

        with self.assertRaises(ValueError):
            AdmittedPlanActionSet(
                document=frozen,
                canonical_bytes=b"{}",
                action_set_digest=trust.expected_action_set_digest,
                trust=trust,
            )
        with self.assertRaises(ValueError):
            AdmittedPlanActionSet(
                document=frozen,
                canonical_bytes=canonical_json_bytes(frozen),
                action_set_digest="sha256:" + "0" * 64,
                trust=trust,
            )


if __name__ == "__main__":
    unittest.main()
