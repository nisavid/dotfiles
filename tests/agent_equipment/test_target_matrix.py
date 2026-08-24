"""Independent coverage for the settled plan-action physical-target matrix.

The resolver and the later production projector are intentionally not coupled
to this matrix.  Each row supplies a complete, independently trusted
pre-capture action projection to the public admission seam and records whether
the settled one-to-one target contract admits it.  This keeps unsupported
shapes outside capture, checkpoint, and adapter authority.
"""

from __future__ import annotations

import unittest
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from agent_equipment.canonical import canonical_json_bytes, canonical_json_sha256
from agent_equipment.model import ValidatedPlan, freeze_json, thaw_json
from agent_equipment.plan_action_set import (
    AdmittedPlanActionSet,
    PlanActionSetRejection,
    PlanActionSetTrust,
    admit_plan_action_set,
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


def _independent_set_digest(document: dict[str, object]) -> str:
    """Recompute trust from the complete supplied projection, not its field."""

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
        expected_action_set_digest=_independent_set_digest(document),
    )
    result = admit_plan_action_set(canonical_json_bytes(document), trust)
    return result


def _diagnostic_codes(result: object) -> tuple[str, ...]:
    return tuple(diagnostic.code for diagnostic in getattr(result, "diagnostics", ()))


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
        self.assertIsInstance(
            _admit(route_plan, route_document), AdmittedPlanActionSet
        )

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
        payload["write_targets"].sort(
            key=lambda item: str(item["target_identity"])
        )
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


class ConstructorBypassTargetMatrixTest(unittest.TestCase):
    def _construct_directly(
        self,
        plan: ValidatedPlan,
        document: dict[str, object],
    ) -> AdmittedPlanActionSet:
        frozen = freeze_json(document)
        assert type(frozen) is type(freeze_json({}))
        digest = _independent_set_digest(document)
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
            expected_action_set_digest=_independent_set_digest(document),
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
