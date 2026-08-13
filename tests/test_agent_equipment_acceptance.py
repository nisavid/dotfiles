from __future__ import annotations

import importlib.util
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "agent_equipment_acceptance_model",
    ROOT / "scripts/agent_equipment_acceptance_model.py",
)
assert SPEC is not None and SPEC.loader is not None
ACCEPTANCE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ACCEPTANCE
SPEC.loader.exec_module(ACCEPTANCE)
DESIGN_SPEC = importlib.util.spec_from_file_location(
    "agent_equipment_design_for_acceptance",
    ROOT / "scripts/agent_equipment_design.py",
)
assert DESIGN_SPEC is not None and DESIGN_SPEC.loader is not None
DESIGN = importlib.util.module_from_spec(DESIGN_SPEC)
sys.modules[DESIGN_SPEC.name] = DESIGN
DESIGN_SPEC.loader.exec_module(DESIGN)
FIXTURES = ROOT / "tests/fixtures/agent-equipment/schema"


def valid_catalog_and_lock() -> tuple[dict[str, object], dict[str, object]]:
    return (
        json.loads((FIXTURES / "valid-catalog.json").read_text(encoding="utf-8")),
        json.loads((FIXTURES / "valid-lock.json").read_text(encoding="utf-8")),
    )


class AgentEquipmentAcceptanceTest(unittest.TestCase):
    def test_fresh_home_converges_to_the_complete_desired_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            desired = ACCEPTANCE.complete_desired_state()
            plan = fixture.plan(desired)

            result = fixture.execute(plan)

            self.assertEqual(result.status, "completed")
            self.assertEqual(fixture.adapter.state, desired)
            self.assertEqual(
                tuple(action.surface for action in plan.actions),
                tuple(sorted(desired)),
            )
            self.assertTrue(
                all(
                    checkpoint["phase"] == "completed"
                    for checkpoint in fixture.checkpoints().values()
                )
            )

    def test_reapply_is_a_steady_state_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            desired = ACCEPTANCE.complete_desired_state()
            fixture.execute(fixture.plan(desired))
            reapply = ACCEPTANCE.AcceptanceFixture(
                Path(temporary_directory) / "reapply"
            )
            reapply.adapter.state = ACCEPTANCE.deep_copy(fixture.adapter.state)
            plan = reapply.plan(desired)

            result = reapply.execute(plan)

            self.assertEqual(result.status, "no_op")
            self.assertEqual(plan.actions, ())
            self.assertEqual(reapply.adapter.calls, [])
            self.assertEqual(reapply.checkpoints(), {})
            self.assertEqual(reapply.adapter.state, desired)

    def test_each_missing_owned_item_is_repaired_without_touching_other_state(self) -> None:
        desired = ACCEPTANCE.complete_desired_state()
        for missing_surface in desired:
            with self.subTest(missing_surface=missing_surface):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    fixture.adapter.state = ACCEPTANCE.deep_copy(desired)
                    fixture.adapter.state["unmanaged/custom-hook"] = {"enabled": True}
                    del fixture.adapter.state[missing_surface]
                    fixture.adapter.calls.clear()
                    plan = fixture.plan(desired)

                    result = fixture.execute(plan)

                    self.assertEqual(result.status, "completed")
                    self.assertEqual(
                        tuple(action.surface for action in plan.actions),
                        (missing_surface,),
                    )
                    self.assertEqual(
                        fixture.adapter.calls,
                        [("set", missing_surface)],
                    )
                    self.assertEqual(
                        fixture.adapter.state["unmanaged/custom-hook"],
                        {"enabled": True},
                    )

    def test_update_emits_one_digest_bound_catalog_and_lock_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            desired = ACCEPTANCE.complete_desired_state()
            fixture.adapter.state = ACCEPTANCE.deep_copy(desired)
            before = fixture.adapter.digest()
            catalog, lock = valid_catalog_and_lock()

            proposal = fixture.propose_update(
                catalog,
                lock,
                validate_pair=DESIGN.validate_design,
            )

            self.assertEqual(fixture.adapter.digest(), before)
            self.assertEqual(proposal.catalog, catalog)
            self.assertEqual(proposal.lock, lock)
            self.assertEqual(fixture.checkpoints(), {})

            stale_lock = ACCEPTANCE.deep_copy(lock)
            stale_lock["catalog_digest"] = "sha256:" + "0" * 64
            with self.assertRaises(ACCEPTANCE.BindingMismatchError):
                fixture.propose_update(
                    catalog,
                    stale_lock,
                    validate_pair=DESIGN.validate_design,
                )
            mismatched_lock = ACCEPTANCE.deep_copy(lock)
            mismatched_lock["distributions"][0]["restore"]["content_digest"] = (
                "sha256:" + "f" * 64
            )
            with self.assertRaises(ACCEPTANCE.BindingMismatchError):
                fixture.propose_update(
                    catalog,
                    mismatched_lock,
                    validate_pair=DESIGN.validate_design,
                )
            self.assertEqual(fixture.adapter.digest(), before)
            self.assertEqual(fixture.checkpoints(), {})

    def test_immutable_content_is_verified_before_explicit_update_mutates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            surface = "standalone/skill:research"
            fixture.adapter.state[surface] = {
                "revision": "sha256:revision-v1",
                "content_base64": "dmVyc2lvbi1vbmU=",
                "content_digest": ACCEPTANCE.bytes_digest(b"version-one"),
            }
            before = ACCEPTANCE.deep_copy(fixture.adapter.state)
            artifact = b"version-two"
            digest = ACCEPTANCE.bytes_digest(artifact)

            with self.assertRaises(ACCEPTANCE.ArtifactVerificationError):
                fixture.apply_immutable_update(
                    surface,
                    revision="sha256:revision-v2",
                    artifact=artifact + b"-corrupt",
                    expected_digest=digest,
                )
            self.assertEqual(fixture.adapter.state, before)

            result = fixture.apply_immutable_update(
                surface,
                revision="sha256:revision-v2",
                artifact=artifact,
                expected_digest=digest,
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(
                fixture.adapter.state[surface],
                {
                    "revision": "sha256:revision-v2",
                    "content_base64": "dmVyc2lvbi10d28=",
                    "content_digest": digest,
                },
            )
            self.assertRegex(fixture.adapter.digest(), r"^sha256:[0-9a-f]{64}$")

    def test_route_switch_controls_components_and_retires_only_owned_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            owned_projection = "claude/skill:mattpocock/create-auth"
            unmanaged_projection = "claude/skill:custom/create-auth"
            fixture.adapter.state.update(
                {
                    owned_projection: {"provider": "standalone"},
                    unmanaged_projection: {"provider": "unmanaged"},
                }
            )

            result = fixture.switch_provider(
                winner_surface="claude/plugin:mattpocock",
                winner_value={"installed": True, "enabled": True},
                component_controls={
                    "skill:mattpocock/create-auth": True,
                    "skill:mattpocock/deferred-component": False,
                },
                losing_projections=(owned_projection, unmanaged_projection),
                catalog_owned={owned_projection},
            )

            self.assertEqual(
                result.trace,
                (
                    "set:claude/plugin:mattpocock",
                    "control:skill:mattpocock/create-auth=enabled",
                    "control:skill:mattpocock/deferred-component=disabled",
                    "verify:claude/plugin:mattpocock",
                    f"remove:{owned_projection}",
                    f"report_unmanaged:{unmanaged_projection}",
                ),
            )
            self.assertEqual(
                result.active_components,
                ("skill:mattpocock/create-auth",),
            )
            self.assertNotIn(owned_projection, fixture.adapter.state)
            self.assertIn(unmanaged_projection, fixture.adapter.state)

    def test_duplicate_routes_fail_closed_unless_the_exact_overlap_is_declared(self) -> None:
        selected = ("route:matt/plugin",)
        observed = ("route:matt/plugin", "route:matt/standalone")

        with self.assertRaises(ACCEPTANCE.DuplicateProviderError):
            ACCEPTANCE.resolve_provider_routes(selected, observed, allow_overlap=None)
        with self.assertRaises(ACCEPTANCE.DuplicateProviderError):
            ACCEPTANCE.resolve_provider_routes(
                selected,
                observed,
                allow_overlap=("route:matt/plugin", "route:matt/other"),
            )

        self.assertEqual(
            ACCEPTANCE.resolve_provider_routes(
                observed,
                observed,
                allow_overlap=observed,
            ),
            observed,
        )
        duplicate_cases = (
            (("route:matt/plugin", "route:matt/plugin"), selected, None),
            (selected, ("route:matt/plugin", "route:matt/plugin"), None),
            (
                observed,
                observed,
                ("route:matt/plugin", "route:matt/plugin"),
            ),
        )
        for duplicate_selected, duplicate_observed, duplicate_overlap in duplicate_cases:
            with self.subTest(
                selected=duplicate_selected,
                observed=duplicate_observed,
                overlap=duplicate_overlap,
            ):
                with self.assertRaises(ACCEPTANCE.DuplicateProviderError):
                    ACCEPTANCE.resolve_provider_routes(
                        duplicate_selected,
                        duplicate_observed,
                        allow_overlap=duplicate_overlap,
                    )

    def test_adoption_requires_an_exact_import_and_never_mutates_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            surface = "claude/skill:custom/grilling"
            fixture.adapter.state[surface] = {"provider": "custom"}
            before = fixture.adapter.digest()

            imported = fixture.import_unmanaged(surface)
            adoption = fixture.adopt(imported)

            self.assertEqual(adoption.control_owner, "reconciler_owned")
            self.assertEqual(fixture.adapter.digest(), before)
            fixture.adapter.state[surface] = {"provider": "changed-externally"}
            with self.assertRaises(ACCEPTANCE.ConcurrentChangeError):
                fixture.adopt(imported)

    def test_adoption_rejects_incoherent_imported_value_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            surface = "claude/skill:custom/grilling"
            live_value = {"provider": "custom"}
            fixture.adapter.state[surface] = live_value
            before = fixture.adapter.digest()
            imported = fixture.import_unmanaged(surface)
            forged_value = replace(imported, value={"provider": "forged"})
            forged_digest = replace(imported, digest=f"sha256:{'f' * 64}")

            for observation in (forged_value, forged_digest):
                with self.subTest(observation=observation):
                    with self.assertRaises(ACCEPTANCE.BindingMismatchError):
                        fixture.adopt(observation)

            self.assertEqual(fixture.adapter.digest(), before)
            self.assertEqual(fixture.adapter.calls, [])

    def test_adoption_requires_a_minted_import_identity_and_exact_bindings(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            surface = "claude/skill:custom/grilling"
            live_value = {"provider": "custom"}
            fixture.adapter.state[surface] = live_value
            before = fixture.adapter.digest()
            imported = fixture.import_unmanaged(surface)
            self.assertEqual(fixture.adopt(imported).value, live_value)

            forged_unminted = ACCEPTANCE.ImportedObservation(
                observation_identity=imported.observation_identity,
                surface=surface,
                value=ACCEPTANCE.deep_copy(live_value),
                digest=ACCEPTANCE.canonical_digest(live_value),
                catalog_digest=imported.catalog_digest,
                inventory_digest=imported.inventory_digest,
            )
            second_fixture = ACCEPTANCE.AcceptanceFixture(
                Path(temporary_directory) / "second"
            )
            second_fixture.adapter.state[surface] = ACCEPTANCE.deep_copy(live_value)

            forged_identity = replace(
                imported,
                observation_identity="imported-observation:sha256:" + "f" * 64,
            )
            forged_catalog = replace(
                imported,
                catalog_digest="sha256:" + "f" * 64,
            )
            forged_inventory = replace(
                imported,
                inventory_digest="sha256:" + "e" * 64,
            )
            for target, observation in (
                (second_fixture, forged_unminted),
                (fixture, forged_identity),
                (fixture, forged_catalog),
                (fixture, forged_inventory),
            ):
                with self.subTest(observation=observation):
                    with self.assertRaises(ACCEPTANCE.BindingMismatchError):
                        target.adopt(observation)

            self.assertEqual(fixture.adapter.digest(), before)
            self.assertEqual(fixture.adapter.calls, [])

    def test_adoption_distinguishes_present_null_from_absence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            surface = "claude/skill:null-state"
            fixture.adapter.state[surface] = None
            imported = fixture.import_unmanaged(surface)
            del fixture.adapter.state[surface]

            with self.assertRaises(ACCEPTANCE.ConcurrentChangeError):
                fixture.adopt(imported)

            self.assertNotIn(surface, fixture.adapter.state)
            self.assertEqual(fixture.adapter.calls, [])

    def test_retirement_reports_drift_when_adopted_state_disappears(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            surface = "claude/skill:adopted"
            fixture.adapter.state[surface] = {"present": True}
            fixture.register_adoption(fixture.import_unmanaged(surface))
            del fixture.adapter.state[surface]

            proposal = fixture.propose_retirement(surface)

            self.assertEqual(proposal.status, "report_only")
            self.assertIsNone(proposal.plan)
            self.assertEqual(fixture.adapter.calls, [])

    def test_retirement_mutates_only_exact_adopted_owned_state_through_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            owned = "claude/skill:adopted"
            unmanaged = "claude/skill:unmanaged"
            fixture.adapter.state.update(
                {owned: {"present": True}, unmanaged: {"present": True}}
            )
            fixture.register_adoption(fixture.import_unmanaged(owned))
            before = fixture.adapter.digest()

            unmanaged_result = fixture.propose_retirement(unmanaged)

            self.assertEqual(unmanaged_result.status, "report_only")
            self.assertEqual(fixture.adapter.digest(), before)
            proposal = fixture.propose_retirement(owned)
            self.assertEqual(fixture.adapter.digest(), before)

            fixture.execute(proposal.plan)

            self.assertNotIn(owned, fixture.adapter.state)
            self.assertIn(unmanaged, fixture.adapter.state)

    def test_native_rolling_drift_requires_reviewed_baseline_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            surface = "claude/plugin:mattpocock"
            fixture.adapter.state[surface] = {"observed_version": "1.2.4"}
            baseline = {"observed_version": "1.2.3", "reviewed": True}
            runtime_before = fixture.adapter.digest()

            audit = fixture.audit_native_rolling(surface, baseline)
            ordinary_apply = fixture.apply_native_rolling(surface, baseline)
            catalog, lock = valid_catalog_and_lock()
            proposal = fixture.propose_native_rolling_update(
                catalog,
                lock,
                validate_pair=DESIGN.validate_design,
            )

            self.assertEqual(audit.status, "drift")
            self.assertEqual(ordinary_apply.status, "drift_reported")
            self.assertEqual(fixture.adapter.digest(), runtime_before)
            self.assertEqual(proposal.catalog, catalog)
            self.assertEqual(proposal.lock, lock)
            unreviewed_baseline = {
                "observed_version": "1.2.4",
                "reviewed": False,
            }
            with self.assertRaises(ACCEPTANCE.BindingMismatchError):
                fixture.audit_native_rolling(surface, unreviewed_baseline)
            with self.assertRaises(ACCEPTANCE.BindingMismatchError):
                fixture.apply_native_rolling(surface, unreviewed_baseline)
            self.assertEqual(fixture.adapter.digest(), runtime_before)

    def test_native_rolling_audit_is_type_exact_and_fails_closed_when_absent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            surface = "claude/plugin:fixture"
            fixture.adapter.state[surface] = {"observed_version": True}

            self.assertEqual(
                fixture.audit_native_rolling(
                    surface, {"observed_version": 1, "reviewed": True}
                ).status,
                "drift",
            )
            fixture.adapter.state.pop(surface)
            with self.assertRaises(ACCEPTANCE.ConcurrentChangeError):
                fixture.audit_native_rolling(
                    surface, {"observed_version": "1.0.0", "reviewed": True}
                )

    def test_audit_import_and_adopt_commands_are_runtime_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            surface = "claude/skill:unmanaged"
            fixture.adapter.state[surface] = {"provider": "custom"}
            before = fixture.adapter.digest()
            checkpoint_before = fixture.checkpoint_bytes()

            audit = fixture.audit({surface: {"provider": "selected"}})
            imported = fixture.import_unmanaged(surface)
            adoption = fixture.adopt(imported)

            self.assertEqual(audit.status, "drift")
            self.assertEqual(adoption.surface, surface)
            self.assertEqual(fixture.adapter.digest(), before)
            self.assertEqual(fixture.checkpoint_bytes(), checkpoint_before)

    def test_nonautomated_operations_are_reported_without_adapter_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.adapter.state["claude/plugin:example"] = {"enabled": False}
            before = fixture.adapter.digest()
            fixture.adapter.calls.clear()

            result = fixture.report_nonautomated(
                (
                    {
                        "surface": "claude/plugin:example",
                        "operation": "enable",
                        "disposition": "operator_action",
                        "verification": "observed_disabled",
                    },
                    {
                        "surface": "cursor/plugin:example",
                        "operation": "install",
                        "disposition": "unavailable",
                        "verification": "manager_has_no_install_surface",
                    },
                )
            )

            self.assertEqual(
                tuple(item["disposition"] for item in result.items),
                ("operator_action", "unavailable"),
            )
            self.assertTrue(all(item["verification"] for item in result.items))
            self.assertEqual(fixture.adapter.digest(), before)
            self.assertEqual(fixture.adapter.calls, [])

    def test_prepared_write_failure_has_no_runtime_effect_and_retry_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            desired = {"claude/plugin:example": {"installed": True}}
            plan = fixture.plan(desired)

            with self.assertRaises(ACCEPTANCE.InjectedFailure):
                fixture.execute(plan, fail_at={"prepared_write:step-000"})

            self.assertEqual(fixture.adapter.state, {})
            self.assertEqual(fixture.checkpoints(), {})

            result = fixture.execute(plan)
            self.assertEqual(result.status, "completed")
            self.assertEqual(
                fixture.checkpoints()["step-000"]["phase"],
                "completed",
            )

    def test_prepared_failure_before_mutation_audits_then_retries_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            plan = fixture.plan({"claude/plugin:example": {"installed": True}})

            with self.assertRaises(ACCEPTANCE.InjectedFailure):
                fixture.execute(plan, fail_at={"before_mutation:step-000"})

            self.assertEqual(fixture.checkpoints()["step-000"]["phase"], "prepared")
            self.assertEqual(fixture.adapter.calls, [])

            result = fixture.execute(plan)

            self.assertEqual(result.trace[0], "audit:step-000:pre_state")
            self.assertEqual(fixture.adapter.calls, [("set", "claude/plugin:example")])

    def test_mutated_but_uncompleted_step_is_audited_without_replay(self) -> None:
        for fault in ("after_mutation:step-000", "completion_write:step-000"):
            with self.subTest(fault=fault):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    plan = fixture.plan(
                        {"claude/plugin:example": {"installed": True}}
                    )

                    with self.assertRaises(ACCEPTANCE.InjectedFailure):
                        fixture.execute(plan, fail_at={fault})

                    self.assertEqual(
                        fixture.checkpoints()["step-000"]["phase"], "prepared"
                    )
                    calls = list(fixture.adapter.calls)
                    result = fixture.execute(plan)

                    self.assertEqual(result.trace[0], "audit:step-000:post_state")
                    self.assertEqual(fixture.adapter.calls, calls)
                    self.assertEqual(
                        fixture.checkpoints()["step-000"]["phase"], "completed"
                    )

    def test_later_failure_compensates_completed_steps_in_reverse_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.adapter.state.update(
                {"surface/a": {"version": 1}, "surface/b": {"version": 1}}
            )
            before = fixture.adapter.digest()
            plan = fixture.plan(
                {"surface/a": {"version": 2}, "surface/b": {"version": 2}}
            )

            with self.assertRaises(ACCEPTANCE.InjectedFailure):
                fixture.execute(
                    plan,
                    fail_at={"before_mutation:step-001"},
                    compensate_on_failure=True,
                )

            self.assertEqual(fixture.adapter.digest(), before)
            checkpoint = fixture.checkpoints()["step-000"]
            self.assertEqual(checkpoint["phase"], "compensated")
            self.assertEqual(
                checkpoint["phase_history"],
                ["prepared", "completed", "compensating", "compensated"],
            )
            self.assertEqual(
                fixture.last_trace[-2:],
                ("compensating:step-000", "compensated:step-000"),
            )

    def test_compare_before_restore_preserves_an_external_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.adapter.state.update(
                {"surface/a": {"version": 1}, "surface/b": {"version": 1}}
            )
            plan = fixture.plan(
                {"surface/a": {"version": 2}, "surface/b": {"version": 2}}
            )

            def change_before_restore(action: object) -> None:
                if action.step_id == "step-000":
                    fixture.adapter.state["surface/a"] = {"version": "external"}

            with self.assertRaises(ACCEPTANCE.ConcurrentChangeError):
                fixture.execute(
                    plan,
                    fail_at={"before_mutation:step-001"},
                    compensate_on_failure=True,
                    before_compensation=change_before_restore,
                )

            self.assertEqual(
                fixture.adapter.state["surface/a"], {"version": "external"}
            )
            self.assertEqual(
                fixture.checkpoints()["step-000"]["phase"],
                "compensation_blocked",
            )
            self.assertIn("completed:step-000", fixture.last_trace)

    def test_completed_checkpoint_reverted_to_pre_state_blocks_all_compensation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.adapter.state.update(
                {
                    "surface/a": {"version": 1},
                    "surface/b": {"version": 1},
                    "surface/c": {"version": 1},
                }
            )
            plan = fixture.plan(
                {
                    "surface/a": {"version": 2},
                    "surface/b": {"version": 2},
                    "surface/c": {"version": 2},
                }
            )

            def revert_completed_surface(action: object) -> None:
                if action.step_id == "step-001":
                    fixture.adapter.state["surface/b"] = {"version": 1}

            with self.assertRaises(ACCEPTANCE.ConcurrentChangeError):
                fixture.execute(
                    plan,
                    fail_at={"before_mutation:step-002"},
                    compensate_on_failure=True,
                    before_compensation=revert_completed_surface,
                )

            self.assertEqual(fixture.adapter.state["surface/a"], {"version": 2})
            self.assertEqual(fixture.adapter.state["surface/b"], {"version": 1})
            checkpoints = fixture.checkpoints()
            self.assertEqual(checkpoints["step-001"]["phase"], "compensation_blocked")
            self.assertEqual(checkpoints["step-000"]["phase"], "completed")

    def test_failed_compensation_is_durable_and_recovery_audits_before_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.adapter.state.update(
                {"surface/a": {"version": 1}, "surface/b": {"version": 1}}
            )
            plan = fixture.plan(
                {"surface/a": {"version": 2}, "surface/b": {"version": 2}}
            )

            with self.assertRaises(ACCEPTANCE.InjectedFailure):
                fixture.execute(
                    plan,
                    fail_at={
                        "before_mutation:step-001",
                        "before_compensation_mutation:step-000",
                    },
                    compensate_on_failure=True,
                )

            self.assertEqual(
                fixture.checkpoints()["step-000"]["phase"], "compensating"
            )
            forward_calls = list(fixture.adapter.calls)

            result = fixture.recover_compensation(plan)

            self.assertIn("audit:step-000:post_state", result.trace)
            self.assertEqual(
                fixture.checkpoints()["step-000"]["phase"], "compensated"
            )
            self.assertEqual(fixture.adapter.calls[: len(forward_calls)], forward_calls)
            self.assertEqual(fixture.adapter.state["surface/a"], {"version": 1})

    def test_explicit_compensation_can_resume_after_first_intent_write_fails(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            initial = {
                "surface/a": {"version": 1},
                "surface/b": {"version": 1},
            }
            fixture.adapter.state.update(ACCEPTANCE.deep_copy(initial))
            plan = fixture.plan(
                {surface: {"version": 2} for surface in initial}
            )

            with self.assertRaises(ACCEPTANCE.InjectedFailure):
                fixture.execute(
                    plan,
                    fail_at={
                        "before_mutation:step-001",
                        "compensating_write:step-001",
                    },
                    compensate_on_failure=True,
                )

            self.assertEqual(
                {
                    step_id: checkpoint["phase"]
                    for step_id, checkpoint in fixture.checkpoints().items()
                },
                {"step-000": "completed", "step-001": "prepared"},
            )

            result = fixture.compensate(plan)

            self.assertEqual(result.status, "recovered")
            self.assertEqual(fixture.adapter.state, initial)
            self.assertTrue(
                all(
                    checkpoint["phase"] == "compensated"
                    for checkpoint in fixture.checkpoints().values()
                )
            )

    def test_compensation_recovery_finishes_the_complete_reverse_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            initial = {
                f"surface/{name}": {"version": 1}
                for name in ("a", "b", "c", "d")
            }
            fixture.adapter.state.update(ACCEPTANCE.deep_copy(initial))
            plan = fixture.plan(
                {surface: {"version": 2} for surface in initial}
            )
            with self.assertRaises(ACCEPTANCE.InjectedFailure):
                fixture.execute(
                    plan,
                    fail_at={
                        "before_mutation:step-003",
                        "before_compensation_mutation:step-001",
                    },
                    compensate_on_failure=True,
                )

            phases = {
                step_id: checkpoint["phase"]
                for step_id, checkpoint in fixture.checkpoints().items()
            }
            self.assertEqual(phases["step-001"], "compensating")
            self.assertEqual(phases["step-000"], "completed")

            result = fixture.recover_compensation(plan)

            self.assertEqual(result.status, "recovered")
            self.assertEqual(fixture.adapter.state, initial)
            self.assertTrue(
                all(
                    checkpoint["phase"] == "compensated"
                    for checkpoint in fixture.checkpoints().values()
                )
            )

    def test_blocked_compensation_cannot_report_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.adapter.state.update(
                {"surface/a": {"version": 1}, "surface/b": {"version": 1}}
            )
            plan = fixture.plan(
                {"surface/a": {"version": 2}, "surface/b": {"version": 2}}
            )

            def change_before_restore(action: object) -> None:
                if action.step_id == "step-000":
                    fixture.adapter.state[action.surface] = {"external": True}

            with self.assertRaises(ACCEPTANCE.ConcurrentChangeError):
                fixture.execute(
                    plan,
                    fail_at={"before_mutation:step-001"},
                    compensate_on_failure=True,
                    before_compensation=change_before_restore,
                )
            state_before = ACCEPTANCE.deep_copy(fixture.adapter.state)
            checkpoints_before = fixture.checkpoint_bytes()

            with self.assertRaises(ACCEPTANCE.CompensationBlockedError):
                fixture.recover_compensation(plan)

            self.assertEqual(fixture.adapter.state, state_before)
            self.assertEqual(fixture.checkpoint_bytes(), checkpoints_before)

    def test_compensation_recovery_rejects_changed_bindings_before_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.adapter.state.update(
                {"surface/a": {"version": 1}, "surface/b": {"version": 1}}
            )
            plan = fixture.plan(
                {"surface/a": {"version": 2}, "surface/b": {"version": 2}}
            )
            with self.assertRaises(ACCEPTANCE.InjectedFailure):
                fixture.execute(
                    plan,
                    fail_at={
                        "before_mutation:step-001",
                        "before_compensation_mutation:step-000",
                    },
                    compensate_on_failure=True,
                )

            changed_action = replace(plan.actions[0], before={"version": 0})
            changed_plan = replace(
                plan,
                actions=(changed_action, *plan.actions[1:]),
                plan_digest=ACCEPTANCE.plan_actions_digest(
                    (changed_action, *plan.actions[1:])
                ),
            )
            state_before = ACCEPTANCE.deep_copy(fixture.adapter.state)
            calls_before = list(fixture.adapter.calls)

            with self.assertRaises(ACCEPTANCE.BindingMismatchError):
                fixture.recover_compensation(changed_plan)

            self.assertEqual(fixture.adapter.state, state_before)
            self.assertEqual(fixture.adapter.calls, calls_before)
            self.assertEqual(
                fixture.checkpoints()["step-000"]["phase"],
                "compensating",
            )

    def test_compensated_checkpoint_cannot_replay_forward_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.adapter.state.update(
                {"surface/a": {"version": 1}, "surface/b": {"version": 1}}
            )
            plan = fixture.plan(
                {"surface/a": {"version": 2}, "surface/b": {"version": 2}}
            )
            with self.assertRaises(ACCEPTANCE.InjectedFailure):
                fixture.execute(
                    plan,
                    fail_at={"before_mutation:step-001"},
                    compensate_on_failure=True,
                )

            state_before = ACCEPTANCE.deep_copy(fixture.adapter.state)
            calls_before = list(fixture.adapter.calls)
            checkpoints_before = fixture.checkpoints()

            with self.assertRaises(ACCEPTANCE.HistoricalCheckpointError):
                fixture.execute(plan)

            self.assertEqual(fixture.adapter.state, state_before)
            self.assertEqual(fixture.adapter.calls, calls_before)
            self.assertEqual(fixture.checkpoints(), checkpoints_before)

    def test_completed_checkpoint_preserves_reverted_external_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.adapter.state["surface/a"] = {"version": 1}
            plan = fixture.plan({"surface/a": {"version": 2}})
            fixture.execute(plan)
            fixture.adapter.state["surface/a"] = {"version": 1}
            fixture.adapter.calls.clear()
            checkpoints_before = fixture.checkpoint_bytes()

            with self.assertRaises(ACCEPTANCE.ConcurrentChangeError):
                fixture.execute(plan)

            self.assertEqual(fixture.adapter.state["surface/a"], {"version": 1})
            self.assertEqual(fixture.adapter.calls, [])
            self.assertEqual(fixture.checkpoint_bytes(), checkpoints_before)

    def test_compare_before_mutate_preserves_concurrent_changes_on_every_surface(self) -> None:
        surfaces = (
            "standalone/skill:research",
            "claude/plugin:mattpocock",
            "claude/component:mattpocock/create-auth",
            "claude/mcp:context7",
        )
        for surface in surfaces:
            with self.subTest(surface=surface):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    fixture.adapter.state[surface] = {"version": 1}
                    plan = fixture.plan({surface: {"version": 2}})

                    def concurrent_change(_action: object) -> None:
                        fixture.adapter.state[surface] = {"version": "external"}

                    with self.assertRaises(ACCEPTANCE.ConcurrentChangeError):
                        fixture.execute(plan, before_mutation=concurrent_change)

                    self.assertEqual(
                        fixture.adapter.state[surface], {"version": "external"}
                    )
                    self.assertEqual(fixture.adapter.calls, [])

    def test_fresh_action_rejects_target_valued_concurrent_change(self) -> None:
        surfaces = (
            "standalone/skill:research",
            "claude/plugin:mattpocock",
            "claude/component:mattpocock/create-auth",
            "claude/mcp:context7",
        )
        for surface in surfaces:
            with self.subTest(surface=surface):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    fixture.adapter.state[surface] = {"version": 1}
                    desired = {"version": 2}
                    plan = fixture.plan({surface: desired})

                    def concurrent_change(_action: object) -> None:
                        fixture.adapter.state[surface] = ACCEPTANCE.deep_copy(desired)

                    with self.assertRaises(ACCEPTANCE.ConcurrentChangeError):
                        fixture.execute(plan, before_mutation=concurrent_change)

                    self.assertEqual(fixture.adapter.state[surface], desired)
                    self.assertEqual(fixture.adapter.calls, [])
                    self.assertEqual(
                        fixture.checkpoints()["step-000"]["phase"],
                        "prepared",
                    )

    def test_auto_compensation_preserves_target_valued_external_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            surface = "surface/value"
            fixture.adapter.state[surface] = {"version": 1}
            desired = {"version": 2}
            plan = fixture.plan({surface: desired})

            def concurrent_change(_action: object) -> None:
                fixture.adapter.state[surface] = ACCEPTANCE.deep_copy(desired)

            with self.assertRaises(ACCEPTANCE.ConcurrentChangeError):
                fixture.execute(
                    plan,
                    before_mutation=concurrent_change,
                    compensate_on_failure=True,
                )

            self.assertEqual(fixture.adapter.state[surface], desired)
            self.assertEqual(fixture.adapter.calls, [])
            checkpoint = fixture.checkpoints()["step-000"]
            self.assertEqual(checkpoint["phase"], "compensation_blocked")
            self.assertEqual(checkpoint["invocation_state"], "not_started")

    def test_invocation_intent_write_failure_occurs_before_adapter_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            plan = fixture.plan({"surface/value": {"version": 2}})

            with self.assertRaises(ACCEPTANCE.InjectedFailure):
                fixture.execute(plan, fail_at={"invocation_write:step-000"})

            self.assertEqual(fixture.adapter.state, {})
            self.assertEqual(fixture.adapter.calls, [])
            checkpoint = fixture.checkpoints()["step-000"]
            self.assertEqual(checkpoint["phase"], "prepared")
            self.assertEqual(checkpoint["invocation_state"], "not_started")

    def test_checkpoint_replay_rejects_every_changed_binding(self) -> None:
        plan_fields = (
            "run_identity",
            "execution_domain_identity",
            "candidate_digest",
            "implementation_manifest_digest",
            "catalog_digest",
            "lock_digest",
            "plan_digest",
            "capability_set_digest",
            "captured_state_identity",
            "captured_state_digest",
        )
        action_fields = (
            "route",
            "operation",
            "compensation",
            "before",
            "after",
        )
        for field in plan_fields + action_fields:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    plan = fixture.plan({"surface/a": {"version": 2}})
                    with self.assertRaises(ACCEPTANCE.InjectedFailure):
                        fixture.execute(
                            plan, fail_at={"before_mutation:step-000"}
                        )
                    fixture.adapter.calls.clear()
                    if field in plan_fields:
                        changed_value = {
                            "run_identity": "run:fixture/changed",
                            "execution_domain_identity": (
                                "execution-domain:fixture/other-ledger-v1"
                            ),
                            "captured_state_identity": "captured-state:fixture/changed",
                        }.get(field, f"sha256:{'f' * 64}")
                        changed = replace(plan, **{field: changed_value})
                    else:
                        changed_value = {
                            "route": "route:fixture/changed",
                            "operation": "install",
                            "compensation": "unavailable",
                            "before": {"changed": "before"},
                            "after": {"changed": "after"},
                        }[field]
                        changed_action = replace(
                            plan.actions[0], **{field: changed_value}
                        )
                        changed = replace(
                            plan,
                            actions=(changed_action,),
                            plan_digest=ACCEPTANCE.plan_actions_digest(
                                (changed_action,)
                            ),
                        )

                    expected_error = (
                        ACCEPTANCE.PlanValidationError
                        if field
                        in {
                            "candidate_digest",
                            "implementation_manifest_digest",
                            "plan_digest",
                            "capability_set_digest",
                            "compensation",
                        }
                        else ACCEPTANCE.BindingMismatchError
                    )
                    with self.assertRaises(expected_error):
                        fixture.execute(changed)

                    self.assertEqual(fixture.adapter.calls, [])

    def test_checkpoint_replay_rejects_forged_embedded_step_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            plan = fixture.plan({"surface/a": {"version": 2}})
            with self.assertRaises(ACCEPTANCE.InjectedFailure):
                fixture.execute(plan, fail_at={"before_mutation:step-000"})
            checkpoint_path = fixture.checkpoint_directory / "step-000.json"
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            checkpoint["step_id"] = "step-forged"
            checkpoint_path.write_text(
                json.dumps(checkpoint, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            fixture.adapter.calls.clear()

            with self.assertRaises(ACCEPTANCE.BindingMismatchError):
                fixture.execute(plan)

            self.assertEqual(fixture.adapter.calls, [])

    def test_checkpoint_preflight_rejects_malformed_durable_record(self) -> None:
        corruptions = {
            "action_identity": "action:sha256:forged",
            "ordinal": 999,
            "compensation_operation": "forged",
            "pre_state": {"version": "forged"},
            "expected_post_state": {"version": "forged"},
            "phase_history": ["prepared", "compensated", "completed"],
            "invocation_state": "forged",
            "unexpected_field": "forged",
        }
        for field, value in corruptions.items():
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    fixture.adapter.state["surface/a"] = {"version": 1}
                    plan = fixture.plan({"surface/a": {"version": 2}})
                    with self.assertRaises(ACCEPTANCE.InjectedFailure):
                        fixture.execute(
                            plan, fail_at={"before_mutation:step-000"}
                        )
                    checkpoint_path = fixture.checkpoint_directory / "step-000.json"
                    checkpoint = json.loads(
                        checkpoint_path.read_text(encoding="utf-8")
                    )
                    checkpoint[field] = value
                    checkpoint_path.write_text(
                        json.dumps(
                            checkpoint, sort_keys=True, separators=(",", ":")
                        ),
                        encoding="utf-8",
                    )
                    fixture.adapter.calls.clear()

                    with self.assertRaises(ACCEPTANCE.BindingMismatchError):
                        fixture.execute(plan)

                    self.assertEqual(fixture.adapter.calls, [])

    def test_checkpoint_preflight_rejects_duplicate_json_members(self) -> None:
        duplicate_members = {
            "top_level": (
                '"surface":"surface/a"',
                '"surface":"forged/surface","surface":"surface/a"',
            ),
            "nested": (
                '"value":{"version":1}',
                '"value":{"version":0},"value":{"version":1}',
            ),
        }
        for location, (needle, replacement) in duplicate_members.items():
            with self.subTest(location=location):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    fixture.adapter.state["surface/a"] = {"version": 1}
                    plan = fixture.plan({"surface/a": {"version": 2}})
                    with self.assertRaises(ACCEPTANCE.InjectedFailure):
                        fixture.execute(
                            plan, fail_at={"before_mutation:step-000"}
                        )
                    checkpoint_path = fixture.checkpoint_directory / "step-000.json"
                    checkpoint_text = checkpoint_path.read_text(encoding="utf-8")
                    self.assertIn(needle, checkpoint_text)
                    checkpoint_path.write_text(
                        checkpoint_text.replace(needle, replacement, 1),
                        encoding="utf-8",
                    )
                    fixture.adapter.calls.clear()

                    with self.assertRaises(ACCEPTANCE.BindingMismatchError):
                        fixture.execute(plan)

                    self.assertEqual(fixture.adapter.calls, [])
                    self.assertEqual(
                        fixture.adapter.state["surface/a"], {"version": 1}
                    )

    def test_checkpoint_binding_is_type_exact_for_json_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.adapter.state["surface/value"] = True
            plan = fixture.plan({"surface/value": False})
            with self.assertRaises(ACCEPTANCE.InjectedFailure):
                fixture.execute(plan, fail_at={"before_mutation:step-000"})
            checkpoint_path = fixture.checkpoint_directory / "step-000.json"
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            checkpoint["pre_state"]["value"] = 1
            checkpoint_path.write_text(
                json.dumps(checkpoint, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )

            with self.assertRaises(ACCEPTANCE.BindingMismatchError):
                fixture.execute(plan)

            self.assertEqual(fixture.adapter.state["surface/value"], True)
            self.assertEqual(fixture.adapter.calls, [])

    def test_checkpoint_replay_binds_capability_set_and_route_evidence(self) -> None:
        binding_fields = (
            "capability_identity",
            "capability_digest",
            "manager_version_evidence_digest",
        )
        cases = ("set_membership", *binding_fields)
        for field in cases:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    plan = fixture.plan({"surface/a": {"version": 2}})
                    with self.assertRaises(ACCEPTANCE.InjectedFailure):
                        fixture.execute(
                            plan, fail_at={"before_mutation:step-000"}
                        )
                    fixture.adapter.calls.clear()

                    if field == "set_membership":
                        added_binding = ACCEPTANCE.CapabilityBinding(
                            capability_identity="capability:fixture/additional",
                            capability_digest=f"sha256:{'5' * 64}",
                            manager_version_evidence_digest=(
                                f"sha256:{'6' * 64}"
                            ),
                        )
                        changed_bindings = tuple(
                            sorted((*plan.capability_bindings, added_binding))
                        )
                        changed = replace(
                            plan,
                            capability_bindings=changed_bindings,
                            capability_set_digest=ACCEPTANCE.capability_set_digest(
                                changed_bindings
                            ),
                        )
                    else:
                        changed_value = (
                            "capability:fixture/changed"
                            if field == "capability_identity"
                            else f"sha256:{'f' * 64}"
                        )
                        changed_binding = replace(
                            plan.actions[0].capability_binding,
                            **{field: changed_value},
                        )
                        changed_action = replace(
                            plan.actions[0], capability_binding=changed_binding
                        )
                        changed_bindings = (changed_binding,)
                        changed = replace(
                            plan,
                            actions=(changed_action,),
                            capability_bindings=changed_bindings,
                            capability_set_digest=ACCEPTANCE.capability_set_digest(
                                changed_bindings
                            ),
                            plan_digest=ACCEPTANCE.plan_actions_digest(
                                (changed_action,)
                            ),
                        )

                    with self.assertRaises(ACCEPTANCE.BindingMismatchError):
                        fixture.execute(changed)

                    self.assertEqual(fixture.adapter.calls, [])

    def test_plan_rejects_ambiguous_capability_identity_before_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            plan = fixture.plan({"surface/a": {"version": 2}})
            original = plan.capability_bindings[0]
            conflicting = replace(
                original,
                capability_digest=f"sha256:{'f' * 64}",
            )
            bindings = tuple(sorted((original, conflicting)))
            ambiguous = replace(
                plan,
                capability_bindings=bindings,
                capability_set_digest=ACCEPTANCE.capability_set_digest(bindings),
            )

            with self.assertRaises(ACCEPTANCE.PlanValidationError):
                fixture.execute(ambiguous)

            self.assertEqual(fixture.checkpoints(), {})
            self.assertEqual(fixture.adapter.calls, [])

    def test_retry_preflights_every_checkpoint_binding_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.adapter.state.update(
                {"surface/a": {"version": 1}, "surface/b": {"version": 1}}
            )
            plan = fixture.plan(
                {"surface/a": {"version": 2}, "surface/b": {"version": 2}}
            )
            with self.assertRaises(ACCEPTANCE.InjectedFailure):
                fixture.execute(plan, fail_at={"before_mutation:step-001"})

            changed_final = replace(plan.actions[-1], route="route:fixture/changed")
            changed_plan = replace(
                plan,
                actions=(*plan.actions[:-1], changed_final),
                plan_digest=ACCEPTANCE.plan_actions_digest(
                    (*plan.actions[:-1], changed_final)
                ),
            )
            state_before = ACCEPTANCE.deep_copy(fixture.adapter.state)
            checkpoints_before = fixture.checkpoint_bytes()
            calls_before = list(fixture.adapter.calls)

            with self.assertRaises(ACCEPTANCE.BindingMismatchError):
                fixture.execute(changed_plan)

            self.assertEqual(fixture.adapter.state, state_before)
            self.assertEqual(fixture.checkpoint_bytes(), checkpoints_before)
            self.assertEqual(fixture.adapter.calls, calls_before)

    def test_forward_recovery_and_reverse_compensation_cover_every_mutating_operation(
        self,
    ) -> None:
        self.assertIn("suppress_native_update", ACCEPTANCE.MUTATING_OPERATIONS)
        for operation in sorted(ACCEPTANCE.MUTATING_OPERATIONS):
            with self.subTest(operation=operation):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    fixture.adapter.state.update(
                        {"surface/a": {"version": 1}, "surface/b": {"version": 1}}
                    )
                    before = fixture.adapter.digest()
                    plan = fixture.plan_for_operation(
                        operation,
                        {"surface/a": {"version": 2}, "surface/b": {"version": 2}},
                    )

                    with self.assertRaises(ACCEPTANCE.InjectedFailure):
                        fixture.execute(
                            plan,
                            fail_at={"after_mutation:step-001"},
                            compensate_on_failure=True,
                        )

                    self.assertEqual(fixture.adapter.digest(), before)
                    self.assertEqual(
                        {
                            checkpoint["phase"]
                            for checkpoint in fixture.checkpoints().values()
                        },
                        {"compensated"},
                    )

                    retry_fixture = ACCEPTANCE.AcceptanceFixture(
                        Path(temporary_directory) / "retry"
                    )
                    retry_fixture.adapter.state["surface/a"] = {"version": 1}
                    retry_plan = retry_fixture.plan_for_operation(
                        operation, {"surface/a": {"version": 2}}
                    )
                    with self.assertRaises(ACCEPTANCE.InjectedFailure):
                        retry_fixture.execute(
                            retry_plan, fail_at={"completion_write:step-000"}
                        )
                    calls = list(retry_fixture.adapter.calls)
                    retry = retry_fixture.execute(retry_plan)
                    self.assertEqual(retry.trace[0], "audit:step-000:post_state")
                    self.assertEqual(retry_fixture.adapter.calls, calls)

    def test_standalone_lexical_traversal_cannot_capture_or_restore_outside(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.standalone_root.mkdir()
            outside = fixture.sandbox / "outside-canary.txt"
            outside.write_bytes(b"outside-must-survive")
            escaped = fixture.standalone_root / ".." / outside.name
            replacement = {
                "kind": "regular_file",
                "mode": 0o600,
                "content_base64": "cmVwbGFjZWQ=",
                "content_digest": ACCEPTANCE.canonical_digest(
                    {"content_base64": "cmVwbGFjZWQ="}
                ),
            }

            with self.assertRaisesRegex(ValueError, "escaped fixture root"):
                fixture.capture_standalone(escaped)
            with self.assertRaisesRegex(ValueError, "escaped fixture root"):
                fixture.restore_standalone(escaped, replacement)

            self.assertEqual(outside.read_bytes(), b"outside-must-survive")

    def test_symlinked_standalone_root_cannot_escape_fixture_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            outside = fixture.sandbox / "outside"
            outside.mkdir()
            canary = outside / "canary"
            canary.write_bytes(b"outside-must-survive")
            os.symlink(outside, fixture.standalone_root)

            with self.assertRaises(ACCEPTANCE.ConcurrentChangeError):
                fixture.capture_standalone(fixture.standalone_root / canary.name)
            with self.assertRaises(ACCEPTANCE.ConcurrentChangeError):
                fixture.restore_standalone(
                    fixture.standalone_root / canary.name,
                    {
                        "kind": "regular_file",
                        "mode": 0o600,
                        "content_base64": "cmVwbGFjZWQ=",
                        "content_digest": ACCEPTANCE.canonical_digest(
                            {"content_base64": "cmVwbGFjZWQ="}
                        ),
                    },
                )

            self.assertEqual(canary.read_bytes(), b"outside-must-survive")

    def test_standalone_restore_rejects_nested_traversal_before_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.standalone_root.mkdir()
            target = fixture.standalone_root / "restore-target"
            target.write_bytes(b"original-must-survive")
            outside = fixture.sandbox / "outside-canary.txt"
            outside.write_bytes(b"outside-must-survive")
            encoded = "b3ZlcndyaXR0ZW4="
            child = {
                "kind": "regular_file",
                "mode": 0o600,
                "content_base64": encoded,
                "content_digest": ACCEPTANCE.canonical_digest(
                    {"content_base64": encoded}
                ),
            }
            children = {"../../outside-canary.txt": child}
            snapshot = {
                "kind": "directory",
                "mode": 0o700,
                "children": children,
                "tree_digest": ACCEPTANCE.canonical_digest(children),
            }

            with self.assertRaisesRegex(ValueError, "invalid snapshot"):
                fixture.restore_standalone(target, snapshot)

            self.assertEqual(target.read_bytes(), b"original-must-survive")
            self.assertEqual(outside.read_bytes(), b"outside-must-survive")

    def test_standalone_restore_rejects_tampered_digests_before_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.standalone_root.mkdir()
            target = fixture.standalone_root / "restore-target"
            target.write_bytes(b"original-must-survive")
            original = fixture.capture_standalone(target)
            tampered_content = ACCEPTANCE.deep_copy(original)
            tampered_content["content_base64"] = "dGFtcGVyZWQ="
            child = ACCEPTANCE.deep_copy(original)
            children = {"child": child}
            tampered_tree = {
                "kind": "directory",
                "mode": 0o700,
                "children": children,
                "tree_digest": "sha256:tampered-tree",
            }

            for snapshot in (tampered_content, tampered_tree):
                with self.subTest(kind=snapshot["kind"]):
                    with self.assertRaisesRegex(ValueError, "invalid snapshot"):
                        fixture.restore_standalone(target, snapshot)
                    self.assertEqual(
                        target.read_bytes(), b"original-must-survive"
                    )

    def test_standalone_restore_rejects_changed_symlink_target_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.standalone_root.mkdir()

            resolved_target = fixture.sandbox / "resolved-target"
            resolved_target.write_bytes(b"target")
            resolved_link = fixture.standalone_root / "resolved-link"
            os.symlink("../resolved-target", resolved_link)
            resolved_snapshot = fixture.capture_standalone(resolved_link)
            resolved_target.unlink()

            broken_link = fixture.standalone_root / "broken-link"
            future_target = fixture.sandbox / "future-target"
            os.symlink("../future-target", broken_link)
            broken_snapshot = fixture.capture_standalone(broken_link)
            future_target.write_bytes(b"now-present")

            for path, snapshot in (
                (resolved_link, resolved_snapshot),
                (broken_link, broken_snapshot),
            ):
                with self.subTest(path=path.name):
                    link_text = os.readlink(path)
                    with self.assertRaises(ACCEPTANCE.ConcurrentChangeError):
                        fixture.restore_standalone(path, snapshot)
                    self.assertTrue(path.is_symlink())
                    self.assertEqual(os.readlink(path), link_text)

    def test_standalone_restore_recreates_deleted_and_replaced_symlink_entries(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.standalone_root.mkdir()
            target = fixture.sandbox / "resolved-target"
            target.write_bytes(b"target")
            resolved = fixture.standalone_root / "resolved-link"
            broken = fixture.standalone_root / "broken-link"
            os.symlink("../resolved-target", resolved)
            os.symlink("missing-target", broken)
            resolved_snapshot = fixture.capture_standalone(resolved)
            broken_snapshot = fixture.capture_standalone(broken)

            resolved.unlink()
            broken.unlink()
            broken.write_bytes(b"replacement-entry")

            fixture.restore_standalone(resolved, resolved_snapshot)
            fixture.restore_standalone(broken, broken_snapshot)

            self.assertEqual(
                fixture.capture_standalone(resolved), resolved_snapshot
            )
            self.assertEqual(fixture.capture_standalone(broken), broken_snapshot)

    def test_invalid_final_action_fails_before_the_checkpoint_store_changes(self) -> None:
        for invalid_operation in ("unknown-operation", {"not": "a string"}):
            with self.subTest(invalid_operation=invalid_operation):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    plan = fixture.plan(
                        {
                            "surface/a": {"version": 2},
                            "surface/b": {"version": 2},
                        }
                    )
                    invalid_final = replace(
                        plan.actions[-1], operation=invalid_operation
                    )
                    invalid_plan = replace(
                        plan, actions=plan.actions[:-1] + (invalid_final,)
                    )

                    with self.assertRaises(ACCEPTANCE.PlanValidationError):
                        fixture.execute(invalid_plan)

                    self.assertEqual(fixture.checkpoints(), {})
                    self.assertEqual(fixture.adapter.state, {})

    def test_duplicate_surface_final_action_fails_before_any_effect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.adapter.state["surface/a"] = {"version": 1}
            first = fixture.plan({"surface/a": {"version": 2}}).actions[0]
            second = replace(
                first,
                step_id="step-001",
                after={"version": 3},
            )
            actions = (first, second)
            plan = replace(
                fixture.plan({"surface/a": {"version": 2}}),
                actions=actions,
                plan_digest=ACCEPTANCE.plan_actions_digest(actions),
            )

            with self.assertRaises(ACCEPTANCE.PlanValidationError):
                fixture.execute(plan)

            self.assertEqual(fixture.adapter.state["surface/a"], {"version": 1})
            self.assertEqual(fixture.adapter.calls, [])
            self.assertEqual(fixture.checkpoints(), {})

    def test_invalid_plan_bindings_fail_before_checkpoint_store_changes(self) -> None:
        fields = (
            "candidate_digest",
            "implementation_manifest_digest",
            "catalog_digest",
            "lock_digest",
            "plan_digest",
            "capability_set_digest",
            "captured_state_digest",
        )
        invalid_values = (
            "",
            "sha256:x",
            "sha256:not-hex" + "0" * 57,
            f"sha256:{'A' * 64}",
            None,
        )
        for field in fields:
            for invalid_value in invalid_values:
                with self.subTest(field=field, invalid_value=invalid_value):
                    with tempfile.TemporaryDirectory() as temporary_directory:
                        fixture = ACCEPTANCE.AcceptanceFixture(
                            Path(temporary_directory)
                        )
                        plan = fixture.plan({"surface/a": {"version": 2}})
                        invalid = replace(plan, **{field: invalid_value})

                        with self.assertRaises(ACCEPTANCE.PlanValidationError):
                            fixture.execute(invalid)

                        self.assertEqual(fixture.checkpoints(), {})
                        self.assertEqual(fixture.adapter.calls, [])

    def test_plan_rejects_non_string_and_empty_identities_before_any_effect(
        self,
    ) -> None:
        plan_cases = {
            "run_identity": (1, ""),
            "execution_domain_identity": (1, ""),
            "captured_state_identity": (2, ""),
        }
        action_cases = {
            "surface": (1, ""),
            "route": (2, ""),
            "step_id": (3, ""),
        }
        for field, invalid_values in plan_cases.items():
            for invalid_value in invalid_values:
                with self.subTest(field=field, invalid_value=invalid_value):
                    with tempfile.TemporaryDirectory() as temporary_directory:
                        fixture = ACCEPTANCE.AcceptanceFixture(
                            Path(temporary_directory)
                        )
                        invalid = replace(
                            fixture.plan({"surface/a": {"version": 2}}),
                            **{field: invalid_value},
                        )

                        with self.assertRaises(ACCEPTANCE.PlanValidationError):
                            fixture.execute(invalid)

                        self.assertEqual(fixture.checkpoints(), {})
                        self.assertEqual(fixture.adapter.calls, [])

        for field, invalid_values in action_cases.items():
            for invalid_value in invalid_values:
                with self.subTest(field=field, invalid_value=invalid_value):
                    with tempfile.TemporaryDirectory() as temporary_directory:
                        fixture = ACCEPTANCE.AcceptanceFixture(
                            Path(temporary_directory)
                        )
                        plan = fixture.plan({"surface/a": {"version": 2}})
                        changed_action = replace(
                            plan.actions[0], **{field: invalid_value}
                        )
                        invalid = replace(
                            plan,
                            actions=(changed_action,),
                            plan_digest=ACCEPTANCE.plan_actions_digest(
                                (changed_action,)
                            ),
                        )

                        with self.assertRaises(ACCEPTANCE.PlanValidationError):
                            fixture.execute(invalid)

                        self.assertEqual(fixture.checkpoints(), {})
                        self.assertEqual(fixture.adapter.calls, [])

        for invalid_identity in (1, ""):
            with self.subTest(
                field="capability_identity", invalid_value=invalid_identity
            ):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    plan = fixture.plan({"surface/a": {"version": 2}})
                    changed_binding = replace(
                        plan.capability_bindings[0],
                        capability_identity=invalid_identity,
                    )
                    changed_action = replace(
                        plan.actions[0], capability_binding=changed_binding
                    )
                    bindings = (changed_binding,)
                    invalid = replace(
                        plan,
                        actions=(changed_action,),
                        plan_digest=ACCEPTANCE.plan_actions_digest(
                            (changed_action,)
                        ),
                        capability_bindings=bindings,
                        capability_set_digest=ACCEPTANCE.capability_set_digest(
                            bindings
                        ),
                    )

                    with self.assertRaises(ACCEPTANCE.PlanValidationError):
                        fixture.execute(invalid)

                    self.assertEqual(fixture.checkpoints(), {})
                    self.assertEqual(fixture.adapter.calls, [])

    def test_plan_rejects_non_json_state_before_any_effect(self) -> None:
        invalid_values = (
            {1: "numeric-key"},
            ("tuple", "coerces-to-array"),
            float("nan"),
            float("inf"),
        )
        for invalid_value in invalid_values:
            with self.subTest(invalid_value=invalid_value):
                with self.assertRaises(ValueError):
                    ACCEPTANCE.canonical_bytes(invalid_value)
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    plan = fixture.plan({"surface/a": {"version": 2}})
                    changed_action = replace(
                        plan.actions[0], after=invalid_value
                    )
                    invalid = replace(
                        plan,
                        actions=(changed_action,),
                        plan_digest="sha256:" + "f" * 64,
                    )

                    with self.assertRaises(ACCEPTANCE.PlanValidationError):
                        fixture.execute(invalid)

                    self.assertEqual(fixture.adapter.state, {})
                    self.assertEqual(fixture.adapter.calls, [])
                    self.assertEqual(fixture.checkpoints(), {})

    def test_plan_rejects_foreign_candidate_authority_before_checkpoint(self) -> None:
        fields = ("candidate_digest", "implementation_manifest_digest")
        for field in fields:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    plan = fixture.plan({"surface/a": {"version": 2}})
                    foreign = replace(plan, **{field: f"sha256:{'f' * 64}"})

                    with self.assertRaises(ACCEPTANCE.PlanValidationError):
                        fixture.execute(foreign)

                    self.assertEqual(fixture.adapter.calls, [])
                    self.assertEqual(fixture.checkpoints(), {})

    def test_absence_sentinel_cannot_collide_with_valid_json_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            surface = "surface/data"
            valid_data = {"$state": "missing"}

            install_fixture = ACCEPTANCE.AcceptanceFixture(
                Path(temporary_directory) / "install"
            )
            install = install_fixture.plan({surface: valid_data})
            install_fixture.execute(install)
            self.assertEqual(install_fixture.adapter.state[surface], valid_data)

            checkpoint = install_fixture.checkpoints()["step-000"]
            self.assertEqual(checkpoint["pre_state"], {"presence": "absent"})
            self.assertEqual(
                checkpoint["expected_post_state"],
                {"presence": "present", "value": valid_data},
            )

            remove_fixture = ACCEPTANCE.AcceptanceFixture(
                Path(temporary_directory) / "remove"
            )
            remove_fixture.adapter.state[surface] = ACCEPTANCE.deep_copy(valid_data)
            self.assertEqual(
                remove_fixture.plan({surface: valid_data}).actions,
                (),
            )
            remove = remove_fixture.plan({surface: ACCEPTANCE.MISSING})
            self.assertEqual(remove.actions[0].before, valid_data)
            self.assertIs(remove.actions[0].after, ACCEPTANCE.MISSING)
            remove_fixture.execute(remove)
            self.assertNotIn(surface, remove_fixture.adapter.state)

            reinstall_fixture = ACCEPTANCE.AcceptanceFixture(
                Path(temporary_directory) / "reinstall"
            )
            reinstall = reinstall_fixture.plan({surface: valid_data})
            self.assertIs(reinstall.actions[0].before, ACCEPTANCE.MISSING)
            reinstall_fixture.execute(reinstall)
            self.assertEqual(reinstall_fixture.adapter.state[surface], valid_data)

    def test_state_equality_distinguishes_booleans_from_numbers(self) -> None:
        for observed, desired in ((True, 1), (False, 0)):
            with self.subTest(observed=observed, desired=desired):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    fixture.adapter.state["surface/value"] = observed

                    plan = fixture.plan({"surface/value": desired})
                    self.assertEqual(len(plan.actions), 1)
                    fixture.execute(plan)

                    value = fixture.adapter.state["surface/value"]
                    self.assertIs(type(value), int)
                    self.assertEqual(value, desired)

    def test_plan_rejects_forged_no_op_action_before_any_effect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.adapter.state["surface/value"] = 1
            plan = fixture.plan({"surface/value": 2})
            forged_action = replace(plan.actions[0], after=1)
            forged = replace(
                plan,
                actions=(forged_action,),
                plan_digest=ACCEPTANCE.plan_actions_digest((forged_action,)),
            )

            with self.assertRaises(ACCEPTANCE.PlanValidationError):
                fixture.execute(forged)

            self.assertEqual(fixture.adapter.state["surface/value"], 1)
            self.assertEqual(fixture.adapter.calls, [])
            self.assertEqual(fixture.checkpoints(), {})

    def test_invalid_capability_binding_digests_fail_before_checkpoint(self) -> None:
        invalid_values = (
            "sha256:x",
            "sha256:not-hex" + "0" * 57,
            f"sha256:{'A' * 64}",
        )
        fields = ("capability_digest", "manager_version_evidence_digest")
        for field in fields:
            for invalid_value in invalid_values:
                with self.subTest(field=field, invalid_value=invalid_value):
                    with tempfile.TemporaryDirectory() as temporary_directory:
                        fixture = ACCEPTANCE.AcceptanceFixture(
                            Path(temporary_directory)
                        )
                        plan = fixture.plan({"surface/a": {"version": 2}})
                        binding = replace(
                            plan.actions[0].capability_binding,
                            **{field: invalid_value},
                        )
                        action = replace(
                            plan.actions[0], capability_binding=binding
                        )
                        bindings = (binding,)
                        invalid = replace(
                            plan,
                            actions=(action,),
                            plan_digest=ACCEPTANCE.plan_actions_digest((action,)),
                            capability_bindings=bindings,
                            capability_set_digest=ACCEPTANCE.capability_set_digest(
                                bindings
                            ),
                        )

                        with self.assertRaises(ACCEPTANCE.PlanValidationError):
                            fixture.execute(invalid)

                        self.assertEqual(fixture.checkpoints(), {})
                        self.assertEqual(fixture.adapter.calls, [])

    def test_stale_plan_digest_fails_before_checkpoint_or_runtime_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            plan = fixture.plan({"surface/a": {"version": 2}})
            appended = ACCEPTANCE.Mutation(
                step_id="step-001",
                surface="surface/b",
                before=ACCEPTANCE.MISSING,
                after={"version": 2},
                route="route:fixture/surface/b",
                operation="configure",
                capability_binding=plan.actions[0].capability_binding,
            )
            stale = replace(plan, actions=(*plan.actions, appended))

            with self.assertRaises(ACCEPTANCE.PlanValidationError):
                fixture.execute(stale)

            self.assertEqual(fixture.checkpoints(), {})
            self.assertEqual(fixture.adapter.state, {})

    def test_standalone_capture_restores_files_trees_and_links_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            root = fixture.standalone_root
            root.mkdir()
            outside = fixture.sandbox / "outside-canary.txt"
            outside.write_bytes(b"outside-must-survive")

            regular = root / "regular"
            regular.write_bytes(b"regular-bytes\x00")
            os.chmod(regular, 0o640)
            tree = root / "tree"
            (tree / "nested").mkdir(parents=True)
            (tree / "nested" / "data").write_bytes(b"tree-bytes")
            os.symlink("nested/data", tree / "data-link")
            symlink = root / "resolved-link"
            os.symlink("../outside-canary.txt", symlink)
            broken = root / "broken-link"
            os.symlink("missing-target", broken)
            escape_parent = root / "escape-parent"
            os.symlink("..", escape_parent)

            with self.assertRaises(ACCEPTANCE.ConcurrentChangeError):
                fixture.capture_standalone(escape_parent / outside.name)

            snapshots = {
                path.name: fixture.capture_standalone(path)
                for path in (regular, tree, symlink, broken)
            }
            self.assertEqual(snapshots["regular"]["kind"], "regular_file")
            self.assertEqual(snapshots["tree"]["kind"], "directory")
            self.assertFalse(snapshots["resolved-link"]["broken"])
            self.assertTrue(snapshots["broken-link"]["broken"])
            self.assertEqual(snapshots["broken-link"]["link_text"], "missing-target")

            regular.unlink()
            os.symlink("../outside-canary.txt", regular)
            fixture.restore_standalone(regular, snapshots["regular"])
            fixture.restore_standalone(tree, snapshots["tree"])
            fixture.restore_standalone(symlink, snapshots["resolved-link"])
            fixture.restore_standalone(broken, snapshots["broken-link"])

            self.assertEqual(outside.read_bytes(), b"outside-must-survive")
            self.assertFalse(regular.is_symlink())
            for name, snapshot in snapshots.items():
                self.assertEqual(
                    fixture.capture_standalone(root / name), snapshot, msg=name
                )

    def test_every_migration_boundary_compensates_to_the_exact_initial_state(self) -> None:
        initial = ACCEPTANCE.migration_initial_state()
        desired = ACCEPTANCE.migration_desired_state()
        for boundary in desired:
            with self.subTest(boundary=boundary):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    fixture.adapter.state = ACCEPTANCE.deep_copy(initial)
                    before = fixture.adapter.digest()
                    plan = fixture.migration_plan(desired)
                    self.assertEqual(
                        tuple(action.surface for action in plan.actions),
                        tuple(desired),
                    )
                    action = next(
                        action for action in plan.actions if action.surface == boundary
                    )

                    with self.assertRaises(ACCEPTANCE.InjectedFailure):
                        fixture.execute(
                            plan,
                            fail_at={f"after_mutation:{action.step_id}"},
                            compensate_on_failure=True,
                        )

                    self.assertEqual(fixture.adapter.digest(), before)
                    self.assertTrue(
                        all(
                            checkpoint["phase"] == "compensated"
                            for checkpoint in fixture.checkpoints().values()
                        )
                    )

    def test_migration_activates_winner_before_retiring_loser(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.adapter.state = ACCEPTANCE.migration_initial_state()

            plan = fixture.migration_plan(ACCEPTANCE.migration_desired_state())

            self.assertEqual(
                tuple(action.surface for action in plan.actions),
                (
                    "00/projector",
                    "01/matt-plugin-installed",
                    "02/matt-plugin-enabled",
                    "03/matt-winner-activation",
                    "04/matt-link",
                    "05/context7-mcp",
                    "06/component-selection",
                    "07/coverage-verification",
                ),
            )

    def test_migration_rollback_restores_loser_before_retiring_winner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.adapter.state = ACCEPTANCE.migration_initial_state()
            plan = fixture.migration_plan(ACCEPTANCE.migration_desired_state())
            failure_action = plan.actions[-1]

            with self.assertRaises(ACCEPTANCE.InjectedFailure):
                fixture.execute(
                    plan,
                    fail_at={f"after_mutation:{failure_action.step_id}"},
                    compensate_on_failure=True,
                )

            action_surfaces = {
                action.step_id: action.surface for action in plan.actions
            }
            compensated_surfaces = tuple(
                action_surfaces[event.removeprefix("compensated:")]
                for event in fixture.last_trace
                if event.startswith("compensated:")
            )
            self.assertEqual(
                compensated_surfaces,
                (
                    "07/coverage-verification",
                    "06/component-selection",
                    "05/context7-mcp",
                    "04/matt-link",
                    "03/matt-winner-activation",
                    "02/matt-plugin-enabled",
                    "01/matt-plugin-installed",
                    "00/projector",
                ),
            )

    def test_failed_winner_verification_never_retires_loser(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.adapter.state = ACCEPTANCE.migration_initial_state()
            plan = fixture.migration_plan(ACCEPTANCE.migration_desired_state())
            winner_verification = next(
                action
                for action in plan.actions
                if action.surface == "03/matt-winner-activation"
            )

            with self.assertRaises(ACCEPTANCE.InjectedFailure):
                fixture.execute(
                    plan,
                    fail_at={f"after_mutation:{winner_verification.step_id}"},
                    compensate_on_failure=True,
                )

            self.assertEqual(
                fixture.adapter.state["04/matt-link"],
                {"link_text": "../../.agents/skills/create-auth"},
            )
            self.assertNotIn(("remove", "04/matt-link"), fixture.adapter.calls)

    def test_every_migration_surface_preserves_changes_before_mutate_and_restore(self) -> None:
        initial = ACCEPTANCE.migration_initial_state()
        desired = ACCEPTANCE.migration_desired_state()
        for surface, desired_value in desired.items():
            with self.subTest(surface=surface, boundary="before_mutate"):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    fixture.adapter.state = ACCEPTANCE.deep_copy(initial)
                    plan = fixture.migration_plan({surface: desired_value})

                    def change_before_mutate(_action: object) -> None:
                        fixture.adapter.state[surface] = {"external": "mutation"}

                    with self.assertRaises(ACCEPTANCE.ConcurrentChangeError):
                        fixture.execute(plan, before_mutation=change_before_mutate)
                    self.assertEqual(
                        fixture.adapter.state[surface], {"external": "mutation"}
                    )

            with self.subTest(surface=surface, boundary="before_restore"):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    fixture.adapter.state = ACCEPTANCE.deep_copy(initial)
                    plan = fixture.migration_plan({surface: desired_value})

                    def change_before_restore(_action: object) -> None:
                        fixture.adapter.state[surface] = {"external": "restore"}

                    with self.assertRaises(ACCEPTANCE.ConcurrentChangeError):
                        fixture.execute(
                            plan,
                            fail_at={"after_mutation:step-000"},
                            compensate_on_failure=True,
                            before_compensation=change_before_restore,
                        )
                    self.assertEqual(
                        fixture.adapter.state[surface], {"external": "restore"}
                    )

    def test_successful_migration_retains_winners_and_removes_only_owned_losers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            fixture.adapter.state = ACCEPTANCE.migration_initial_state()
            fixture.adapter.state["99/unmanaged-custom-skill"] = {"present": True}

            fixture.execute(
                fixture.migration_plan(ACCEPTANCE.migration_desired_state())
            )

            self.assertEqual(
                fixture.adapter.state["99/unmanaged-custom-skill"], {"present": True}
            )
            self.assertNotIn("04/matt-link", fixture.adapter.state)
            self.assertEqual(
                {
                    surface: fixture.adapter.state[surface]
                    for surface in ACCEPTANCE.migration_desired_state()
                    if surface != "04/matt-link"
                },
                {
                    surface: value
                    for surface, value in ACCEPTANCE.migration_desired_state().items()
                    if surface != "04/matt-link"
                },
            )

    def test_durable_artifacts_contain_secret_references_but_no_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            secret_value = "fixture-secret-canary-do-not-serialize"
            desired = {
                "claude/mcp:context7": {
                    "transport": "stdio",
                    "secret_ref": "CONTEXT7_API_KEY",
                }
            }
            with mock.patch.dict(
                os.environ, {"CONTEXT7_API_KEY": secret_value}, clear=False
            ):
                fixture.execute(fixture.plan(desired))
                evidence = fixture.evidence_bundle()
                encoded = ACCEPTANCE.canonical_bytes(evidence)

            self.assertIn(b"CONTEXT7_API_KEY", encoded)
            self.assertNotIn(secret_value.encode(), encoded)
            ACCEPTANCE.assert_secret_free(evidence, forbidden_values={secret_value})


if __name__ == "__main__":
    unittest.main()
