from __future__ import annotations

import unittest
from dataclasses import replace

from agent_equipment.canonical import canonical_json_sha256
from agent_equipment.model import FrozenJsonObject, freeze_json, thaw_json
from agent_equipment.resolver import _build_validated_plan, _LogicalNode

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_F = "sha256:" + "f" * 64


def frozen_object(document: dict[str, object]) -> FrozenJsonObject:
    frozen = freeze_json(document)
    assert isinstance(frozen, FrozenJsonObject)
    return frozen


def mutation(
    key: str,
    *,
    equipment_identity: str = "skill:example/a",
    harness: str = "claude",
    route_identity: str = "route:claude/a",
    operation: str = "install",
    desired_state_digest: str = SHA_A,
    surface_scope: tuple[str, ...] | None = None,
) -> _LogicalNode:
    surfaces = (
        (f"surface:{route_identity}/{equipment_identity}",)
        if surface_scope is None
        else surface_scope
    )
    definition = frozen_object(
        {
            "controlled_equipment_identities": [],
            "desired_state": {"test_marker": desired_state_digest},
            "desired_state_digest": desired_state_digest,
            "equipment_identities": [equipment_identity],
            "harness": harness,
            "operation": operation,
            "route_identity": route_identity,
            "surface_scope": list(surfaces),
        }
    )
    return _LogicalNode(
        key=key,
        kind="mutation",
        semantic_key=(
            equipment_identity,
            harness,
            route_identity,
            operation,
            desired_state_digest,
        ),
        definition=definition,
    )


def verification(
    key: str,
    *,
    purpose: str = "final_coverage",
    route_identity: str = "",
    predicate_digest: str = SHA_F,
) -> _LogicalNode:
    if purpose == "final_coverage":
        predicate_field = "coverage_predicate"
        predicate = frozen_object(
            {
                "operator": "all",
                "coverage_membership": [],
                "active_activation_membership": [],
                "route_state_predicates": [],
                "read_surface_scope": [],
                "test_marker": predicate_digest,
            }
        )
    elif purpose == "projector_readiness":
        predicate_field = "projector_policy_predicate"
        policy: dict[str, object] = {
            "mode": "catalog_driven",
            "harness": "claude",
            "control_surface": "surface:claude/standalone-skill-projector",
            "included_skill_identities": ["skill:example/included"],
            "excluded_skill_identities": ["skill:example/excluded"],
            "implementation_manifest_digest": "sha256:" + "2" * 64,
            "catalog_digest": "sha256:" + "3" * 64,
            "lock_digest": "sha256:" + "4" * 64,
        }
        policy["policy_digest"] = canonical_json_sha256(policy)
        predicate = frozen_object(
            {
                "operator": "equals",
                "desired_policy": policy,
            }
        )
    else:
        predicate_field = "normalized_state_predicate"
        predicate = frozen_object(
            {
                "operator": "equals",
                "expected": {"test_marker": predicate_digest},
            }
        )
    actual_predicate_digest = canonical_json_sha256(predicate)
    definition_fields: dict[str, object] = {
        "active_equipment_identities": [],
        "active_activation_membership": [],
        "harness": "",
        predicate_field: predicate,
        "predicate_digest": actual_predicate_digest,
        "purpose": purpose,
        "read_surface_scope": [],
        "route_identity": route_identity,
    }
    if purpose == "projector_readiness":
        definition_fields.update(
            {
                "activation_group": "",
                "capability_identity": None,
                "capability_digest": None,
                "controlled_equipment_identities": [],
                "implementation_manifest_digest": "sha256:" + "2" * 64,
                "catalog_digest": "sha256:" + "3" * 64,
                "lock_digest": "sha256:" + "4" * 64,
                "read_surface_scope": ["surface:claude/standalone-skill-projector"],
            }
        )
    definition = frozen_object(definition_fields)
    return _LogicalNode(
        key=key,
        kind="verification",
        semantic_key=(
            purpose,
            "",
            route_identity,
            actual_predicate_digest,
            canonical_json_sha256(definition),
        ),
        definition=definition,
    )


def build(
    nodes: tuple[_LogicalNode, ...],
    edges: tuple[tuple[str, str], ...],
):
    return _build_validated_plan(
        candidate_identity="candidate:sha256:" + "1" * 64,
        implementation_manifest_digest="sha256:" + "2" * 64,
        catalog_digest="sha256:" + "3" * 64,
        lock_digest="sha256:" + "4" * 64,
        inventory_digest="sha256:" + "5" * 64,
        capability_set_digest="sha256:" + "6" * 64,
        logical_nodes=nodes,
        dependency_keys=edges,
    )


class ResolverGraphTest(unittest.TestCase):
    def test_graph_rejects_a_verification_with_a_forged_predicate_digest(
        self,
    ) -> None:
        final = verification("final")
        changed_definition = frozen_object(
            {**thaw_json(final.definition), "predicate_digest": SHA_A}
        )
        forged = replace(final, definition=changed_definition)

        result = build(
            (mutation("action"), forged),
            (("action", "final"),),
        )

        self.assertIsNone(result.plan)
        self.assertEqual(
            tuple(diagnostic.code for diagnostic in result.diagnostics),
            ("PLAN_NODE_INVALID",),
        )

    def test_graph_rejects_a_forged_projector_policy_digest(self) -> None:
        readiness = verification("ready", purpose="projector_readiness")
        changed_definition = thaw_json(readiness.definition)
        assert isinstance(changed_definition, dict)
        predicate = changed_definition["projector_policy_predicate"]
        assert isinstance(predicate, dict)
        desired_policy = predicate["desired_policy"]
        assert isinstance(desired_policy, dict)
        desired_policy["policy_digest"] = SHA_A
        changed_definition["predicate_digest"] = canonical_json_sha256(predicate)
        forged = replace(
            readiness,
            definition=frozen_object(changed_definition),
        )

        result = build(
            (forged, mutation("action"), verification("final")),
            (("ready", "action"), ("action", "final")),
        )

        self.assertIsNone(result.plan)
        self.assertEqual(
            tuple(diagnostic.code for diagnostic in result.diagnostics),
            ("PLAN_NODE_INVALID",),
        )

    def test_graph_coalesces_cross_route_writers_for_one_shared_surface(self) -> None:
        surface = ("surface:shared/skill:example/a",)
        nodes = (
            mutation(
                "codex-writer",
                harness="codex",
                route_identity="route:codex/a",
                surface_scope=surface,
            ),
            mutation("claude-writer", surface_scope=surface),
            verification("final"),
        )
        edges = (("codex-writer", "final"), ("claude-writer", "final"))
        result = build(
            nodes,
            edges,
        )
        permuted = build(tuple(reversed(nodes)), tuple(reversed(edges)))

        self.assertEqual(result.diagnostics, ())
        self.assertEqual(permuted.diagnostics, ())
        self.assertEqual(result.plan, permuted.plan)
        assert result.plan is not None
        mutations = tuple(node for node in result.plan.nodes if node.kind == "mutation")
        self.assertEqual(len(mutations), 1)
        self.assertEqual(
            mutations[0].definition.get("route_identity"),
            "route:claude/a",
        )
        dependent = next(
            node
            for node in result.plan.nodes
            if node.kind == "verification"
            and node.definition.get("purpose") == "coalesced_route_state"
        )
        self.assertEqual(
            dependent.definition.get("route_identity"),
            "route:codex/a",
        )
        self.assertIn(mutations[0].identity, dependent.dependencies)
        final = next(
            node
            for node in result.plan.nodes
            if node.definition.get("purpose") == "final_coverage"
        )
        self.assertIn(dependent.identity, final.dependencies)

    def test_coalesced_route_verification_waits_for_the_complete_writer_sequence(
        self,
    ) -> None:
        surface = ("surface:shared/skill:example/a",)
        nodes = (
            mutation("claude-install", surface_scope=surface),
            mutation(
                "claude-configure",
                operation="configure",
                desired_state_digest=SHA_B,
                surface_scope=surface,
            ),
            mutation(
                "codex-install",
                harness="codex",
                route_identity="route:codex/a",
                surface_scope=surface,
            ),
            mutation(
                "codex-configure",
                harness="codex",
                route_identity="route:codex/a",
                operation="configure",
                desired_state_digest=SHA_B,
                surface_scope=surface,
            ),
            verification("final"),
        )
        edges = (
            ("claude-install", "claude-configure"),
            ("claude-configure", "final"),
            ("codex-install", "codex-configure"),
            ("codex-configure", "final"),
        )

        result = build(nodes, edges)

        self.assertEqual(result.diagnostics, ())
        assert result.plan is not None
        mutations = tuple(node for node in result.plan.nodes if node.kind == "mutation")
        self.assertEqual(
            tuple(node.definition.get("operation") for node in mutations),
            ("install", "configure"),
        )
        dependent = next(
            node
            for node in result.plan.nodes
            if node.definition.get("purpose") == "coalesced_route_state"
        )
        self.assertEqual(
            dependent.definition.get("coalesced_operations"),
            ("install", "configure"),
        )
        self.assertEqual(dependent.dependencies, (mutations[-1].identity,))
        final = next(
            node
            for node in result.plan.nodes
            if node.definition.get("purpose") == "final_coverage"
        )
        self.assertIn(dependent.identity, final.dependencies)

    def test_graph_rejects_conflicting_shared_surface_mutation_authority(self) -> None:
        surface = ("surface:shared/skill:example/a",)
        cases = (
            mutation(
                "different-operation",
                harness="codex",
                route_identity="route:codex/a",
                operation="remove",
                surface_scope=surface,
            ),
            mutation(
                "different-state",
                harness="codex",
                route_identity="route:codex/a",
                desired_state_digest=SHA_B,
                surface_scope=surface,
            ),
            replace(
                mutation(
                    "different-precondition",
                    harness="codex",
                    route_identity="route:codex/a",
                    surface_scope=surface,
                ),
                definition=frozen_object(
                    {
                        **thaw_json(
                            mutation(
                                "source",
                                harness="codex",
                                route_identity="route:codex/a",
                                surface_scope=surface,
                            ).definition
                        ),
                        "surface_precondition_digest": SHA_B,
                    }
                ),
            ),
        )
        for conflicting in cases:
            with self.subTest(key=conflicting.key):
                result = build(
                    (
                        mutation("claude-writer", surface_scope=surface),
                        conflicting,
                        verification("final"),
                    ),
                    (("claude-writer", "final"), (conflicting.key, "final")),
                )
                self.assertIsNone(result.plan)
                self.assertEqual(
                    tuple(diagnostic.code for diagnostic in result.diagnostics),
                    ("PLAN_SURFACE_WRITER_CONFLICT",),
                )

    def test_graph_coalesces_only_semantically_identical_mutation_authority(
        self,
    ) -> None:
        first = mutation("writer-a")
        duplicate = replace(first, key="writer-b")

        result = build(
            (duplicate, verification("final"), first),
            (("writer-b", "final"), ("writer-a", "final")),
        )

        self.assertEqual(result.diagnostics, ())
        assert result.plan is not None
        self.assertEqual(
            tuple(node.key for node in result.plan.nodes),
            ("writer-a", "final"),
        )

    def test_graph_rejects_duplicate_action_semantics_even_if_payloads_differ(
        self,
    ) -> None:
        first = mutation("first")
        changed_definition = frozen_object(
            {**thaw_json(first.definition), "adapter_identity": "adapter:changed"}
        )
        second = replace(first, key="second", definition=changed_definition)

        result = build(
            (first, second, verification("final")),
            (("first", "final"), ("second", "final")),
        )

        self.assertIsNone(result.plan)
        self.assertEqual(
            tuple(diagnostic.code for diagnostic in result.diagnostics),
            ("PLAN_NODE_DUPLICATE",),
        )

    def test_graph_rejects_missing_dependencies_without_returning_a_plan(self) -> None:
        result = build(
            (mutation("action"), verification("final")),
            (("missing", "action"), ("action", "final")),
        )

        self.assertIsNone(result.plan)
        self.assertEqual(
            tuple(diagnostic.code for diagnostic in result.diagnostics),
            ("PLAN_DEPENDENCY_MISSING",),
        )

    def test_graph_rejects_cycles_without_returning_a_plan(self) -> None:
        result = build(
            (
                mutation("a"),
                mutation(
                    "b",
                    equipment_identity="skill:example/b",
                    route_identity="route:claude/b",
                ),
                verification("final"),
            ),
            (("a", "b"), ("b", "a"), ("b", "final")),
        )

        self.assertIsNone(result.plan)
        self.assertEqual(
            tuple(diagnostic.code for diagnostic in result.diagnostics),
            ("PLAN_DEPENDENCY_CYCLE",),
        )

    def test_graph_rejects_orphaned_mutations_and_multiple_final_sinks(self) -> None:
        cases = (
            (
                (
                    mutation("linked"),
                    mutation(
                        "orphan",
                        equipment_identity="skill:example/orphan",
                        route_identity="route:claude/orphan",
                    ),
                    verification("final"),
                ),
                (("linked", "final"),),
            ),
            (
                (
                    mutation("action"),
                    verification("final-a", predicate_digest=SHA_A),
                    verification("final-b", predicate_digest=SHA_B),
                ),
                (("action", "final-a"), ("action", "final-b")),
            ),
        )

        for nodes, edges in cases:
            with self.subTest(nodes=tuple(node.key for node in nodes)):
                result = build(nodes, edges)
                self.assertIsNone(result.plan)
                self.assertEqual(
                    tuple(diagnostic.code for diagnostic in result.diagnostics),
                    ("PLAN_ACTION_ORPHANED",),
                )

    def test_topological_order_compares_only_ready_semantic_nodes(self) -> None:
        # "blocked" sorts before "root" semantically but cannot be emitted first.
        root = mutation(
            "root",
            equipment_identity="skill:example/z",
            route_identity="route:claude/z",
        )
        blocked = mutation(
            "blocked",
            equipment_identity="skill:example/a",
            route_identity="route:claude/a",
        )
        peer = mutation(
            "peer",
            equipment_identity="skill:example/y",
            route_identity="route:claude/y",
        )
        final = verification("final")

        result = build(
            (final, blocked, peer, root),
            (("root", "blocked"), ("blocked", "final"), ("peer", "final")),
        )

        self.assertEqual(result.diagnostics, ())
        assert result.plan is not None
        self.assertEqual(
            tuple(node.key for node in result.plan.nodes),
            ("peer", "root", "blocked", "final"),
        )
        self.assertEqual(
            tuple(node.ordinal for node in result.plan.nodes),
            (0, 1, 2, 3),
        )

    def test_plan_preimage_uses_ordinals_and_excludes_derived_identities(self) -> None:
        result = build(
            (mutation("action"), verification("final")),
            (("action", "final"),),
        )

        self.assertEqual(result.diagnostics, ())
        assert result.plan is not None
        preimage = thaw_json(result.plan.preimage)
        assert isinstance(preimage, dict)
        self.assertEqual(preimage["edges"], [[0, 1]])
        self.assertNotIn("plan_digest", preimage)
        serialized = repr(preimage)
        self.assertNotIn("predecessor_identities", serialized)
        self.assertNotIn("predecessor_ordinals", serialized)
        self.assertNotIn("action:sha256:", serialized)
        self.assertNotIn("verification:sha256:", serialized)
        self.assertEqual(
            result.plan.digest, canonical_json_sha256(result.plan.preimage)
        )
        action, final = result.plan.nodes
        self.assertEqual(final.dependencies, (action.identity,))
        self.assertNotIn("predecessor_identities", final.definition)
        self.assertNotIn("predecessor_ordinals", final.definition)

    def test_semantic_node_or_edge_changes_change_the_plan_digest(self) -> None:
        base = build(
            (
                mutation("a"),
                mutation(
                    "b",
                    equipment_identity="skill:example/b",
                    route_identity="route:claude/b",
                ),
                verification("final"),
            ),
            (("a", "b"), ("b", "final")),
        )
        changed_node = build(
            (
                mutation("a", desired_state_digest=SHA_B),
                mutation(
                    "b",
                    equipment_identity="skill:example/b",
                    route_identity="route:claude/b",
                ),
                verification("final"),
            ),
            (("a", "b"), ("b", "final")),
        )
        changed_edge = build(
            (
                mutation("a"),
                mutation(
                    "b",
                    equipment_identity="skill:example/b",
                    route_identity="route:claude/b",
                ),
                verification("final"),
            ),
            (("a", "final"), ("b", "final")),
        )

        for result in (base, changed_node, changed_edge):
            self.assertEqual(result.diagnostics, ())
            self.assertIsNotNone(result.plan)
        assert base.plan is not None
        assert changed_node.plan is not None
        assert changed_edge.plan is not None
        self.assertNotEqual(base.plan.digest, changed_node.plan.digest)
        self.assertNotEqual(base.plan.digest, changed_edge.plan.digest)

    def test_input_permutations_produce_identical_plan_bytes_and_identities(
        self,
    ) -> None:
        nodes = (
            mutation("a"),
            mutation(
                "b",
                equipment_identity="skill:example/b",
                route_identity="route:claude/b",
            ),
            verification("final"),
        )
        edges = (("a", "final"), ("b", "final"))

        first = build(nodes, edges)
        second = build(tuple(reversed(nodes)), tuple(reversed(edges)))

        self.assertEqual(first.diagnostics, ())
        self.assertEqual(second.diagnostics, ())
        self.assertEqual(first.plan, second.plan)

    def test_final_identities_are_bound_to_the_sealed_plan(self) -> None:
        result = build(
            (
                mutation("action", operation="configure"),
                verification("ready", purpose="projector_readiness"),
                verification("winner", purpose="winner_activation"),
                verification("final"),
            ),
            (
                ("ready", "action"),
                ("action", "winner"),
                ("winner", "final"),
            ),
        )

        self.assertEqual(result.diagnostics, ())
        assert result.plan is not None
        by_key = {node.key: node for node in result.plan.nodes}
        action = by_key["action"]
        expected_action_identity = canonical_json_sha256(
            {
                "plan_digest": result.plan.digest,
                "ordinal": action.ordinal,
                "route_id": "route:claude/a",
                "operation": "configure",
                "desired_state_digest": SHA_A,
            }
        )
        self.assertEqual(action.identity, f"action:{expected_action_identity}")
        for key in ("ready", "winner", "final"):
            self.assertRegex(
                by_key[key].identity,
                r"^verification:sha256:[0-9a-f]{64}$",
            )

    def test_validated_plan_rejects_forged_identity_or_dependency_projection(
        self,
    ) -> None:
        result = build(
            (mutation("action"), verification("final")),
            (("action", "final"),),
        )
        assert result.plan is not None
        plan = result.plan

        forged_action = replace(
            plan.nodes[0],
            identity="action:sha256:" + "0" * 64,
        )
        with self.assertRaises(ValueError):
            replace(plan, nodes=(forged_action, *plan.nodes[1:]))
        with self.assertRaises(ValueError):
            replace(plan, edges=())


if __name__ == "__main__":
    unittest.main()
