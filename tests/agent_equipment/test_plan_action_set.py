from __future__ import annotations

import json
import unittest
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from agent_equipment import _json_schema as json_schema_module
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
            "route_record": {
                "provider": payload["provider"],
                "control_owner": "reconciler_owned",
                "secret_references": payload["secret_references"],
            },
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

    def test_reordered_actions_keep_the_canonical_set_digest_but_fail_membership(
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
        actions.reverse()
        _reseal(document)

        result = admit_plan_action_set(
            canonical_json_bytes(document),
            PlanActionSetTrust(
                validated_plan=plan,
                expected_action_set_digest=str(document["action_set_digest"]),
            ),
        )

        codes = _diagnostic_codes(result)
        self.assertIn("PLAN_ACTION_SET_MEMBERSHIP_INVALID", codes)
        self.assertNotIn("PLAN_ACTION_SET_DIGEST_INVALID", codes)

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
        first["write_surface_identity"] = str(
            payload["surface_scope"][1]  # type: ignore[index]
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
        relabelled_payload = {
            key: value
            for key, value in relabelled.items()
            if key != "target_identity"
        }
        relabelled["target_identity"] = (
            "target:" + canonical_json_sha256(relabelled_payload)
        )
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
        native_target = targets[0]
        assert isinstance(native_target, dict)
        locator = native_target["locator"]
        assert isinstance(locator, dict)
        locator["native_identity"] = "foreign@fixture"
        native_target["target_identity"] = "target:" + canonical_json_sha256(
            {
                key: value
                for key, value in native_target.items()
                if key != "target_identity"
            }
        )
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
            "kind": lambda targets: targets[0].__setitem__(
                "surface_kind", "plugin_enablement"
            ),
            "equipment": lambda targets: targets[1].__setitem__(
                "equipment_identity", "skill:fixture/foreign"
            ),
            "manager": lambda targets: targets[0]["locator"].__setitem__(
                "manager", "cursor"
            ),
            "route": lambda targets: targets[1].__setitem__(
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
                    target["target_identity"] = (
                        "target:"
                        + canonical_json_sha256(
                            {
                                key: value
                                for key, value in target.items()
                                if key != "target_identity"
                            }
                        )
                    )
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

    def test_original_trusted_set_digest_transitively_binds_expected_post_state(
        self,
    ) -> None:
        plan, document = _valid_plan_and_action_set()
        original_set_digest = str(document["action_set_digest"])
        actions = document["actions"]
        assert isinstance(actions, list)
        evidence = actions[0]
        assert isinstance(evidence, dict)
        payload = evidence["action_payload"]
        assert isinstance(payload, dict)
        payload["expected_post_state_digest"] = "sha256:" + "7" * 64
        _reseal_digest_fields_only(document)

        result = admit_plan_action_set(
            canonical_json_bytes(document),
            PlanActionSetTrust(
                validated_plan=plan,
                expected_action_set_digest=original_set_digest,
            ),
        )

        self.assertIsInstance(result, PlanActionSetRejection)
        self.assertIn("PLAN_ACTION_SET_DIGEST_INVALID", _diagnostic_codes(result))


if __name__ == "__main__":
    unittest.main()
