from __future__ import annotations

import importlib.util
from dataclasses import replace
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


class AgentEquipmentAcceptanceTest(unittest.TestCase):
    def test_fresh_home_converges_to_the_complete_desired_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))

            result = fixture.apply(ACCEPTANCE.complete_desired_state())

            self.assertEqual(result.status, "completed")
            self.assertEqual(fixture.adapter.state, ACCEPTANCE.complete_desired_state())

    def test_reapply_is_a_steady_state_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            desired = ACCEPTANCE.complete_desired_state()
            fixture.apply(desired)
            checkpoint_bytes = fixture.checkpoint_bytes()
            fixture.adapter.calls.clear()

            result = fixture.apply(desired)

            self.assertEqual(result.status, "no_op")
            self.assertEqual(fixture.adapter.calls, [])
            self.assertEqual(fixture.checkpoint_bytes(), checkpoint_bytes)

    def test_each_missing_owned_item_is_repaired_without_touching_other_state(self) -> None:
        desired = ACCEPTANCE.complete_desired_state()
        for missing_surface in desired:
            with self.subTest(missing_surface=missing_surface):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
                    fixture.apply(desired)
                    fixture.adapter.state["unmanaged/custom-hook"] = {"enabled": True}
                    del fixture.adapter.state[missing_surface]
                    fixture.adapter.calls.clear()

                    result = fixture.apply(desired)

                    self.assertEqual(result.mutated_surfaces, (missing_surface,))
                    self.assertEqual(
                        fixture.adapter.state["unmanaged/custom-hook"],
                        {"enabled": True},
                    )

    def test_update_is_an_explicit_proposal_until_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            desired = ACCEPTANCE.complete_desired_state()
            fixture.apply(desired)
            before = fixture.adapter.digest()

            proposal = fixture.propose_update(
                desired,
                "standalone/skill:research",
                {
                    "kind": "skill",
                    "revision": "sha256:standalone-research-v2",
                },
            )

            self.assertEqual(fixture.adapter.digest(), before)
            self.assertEqual(
                proposal.desired_state["standalone/skill:research"]["revision"],
                "sha256:standalone-research-v2",
            )
            self.assertEqual(
                fixture.apply(proposal.desired_state).mutated_surfaces,
                ("standalone/skill:research",),
            )

    def test_immutable_content_is_verified_before_explicit_update_mutates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = ACCEPTANCE.AcceptanceFixture(Path(temporary_directory))
            surface = "standalone/skill:research"
            fixture.adapter.state[surface] = {
                "revision": "sha256:revision-v1",
                "content": b"version-one",
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
                {"revision": "sha256:revision-v2", "content": artifact},
            )

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
            proposal = fixture.propose_native_rolling_update(surface, baseline)

            self.assertEqual(audit.status, "drift")
            self.assertEqual(ordinary_apply.status, "drift_reported")
            self.assertEqual(fixture.adapter.digest(), runtime_before)
            self.assertEqual(
                proposal.baseline,
                {"observed_version": "1.2.4", "reviewed": False},
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

            self.assertEqual(result.trace[0], "audit:step-000:post_state")
            self.assertEqual(
                fixture.checkpoints()["step-000"]["phase"], "compensated"
            )
            self.assertEqual(fixture.adapter.calls[: len(forward_calls)], forward_calls)
            self.assertEqual(fixture.adapter.state["surface/a"], {"version": 1})

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

    def test_checkpoint_replay_rejects_every_changed_binding(self) -> None:
        plan_fields = (
            "candidate_digest",
            "catalog_digest",
            "lock_digest",
            "plan_digest",
            "capability_digest",
        )
        action_fields = (
            "route",
            "operation",
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
                        changed = replace(plan, **{field: f"changed:{field}"})
                    else:
                        changed_value = {
                            "route": "route:fixture/changed",
                            "operation": "install",
                            "before": {"changed": "before"},
                            "after": {"changed": "after"},
                        }[field]
                        changed_action = replace(
                            plan.actions[0], **{field: changed_value}
                        )
                        changed = replace(plan, actions=(changed_action,))

                    with self.assertRaises(ACCEPTANCE.BindingMismatchError):
                        fixture.execute(changed)

                    self.assertEqual(fixture.adapter.calls, [])

    def test_checkpoint_fault_contract_covers_every_mutating_operation(self) -> None:
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
            self.assertNotIn("01/matt-link", fixture.adapter.state)
            self.assertEqual(
                {
                    surface: fixture.adapter.state[surface]
                    for surface in ACCEPTANCE.migration_desired_state()
                    if surface != "01/matt-link"
                },
                {
                    surface: value
                    for surface, value in ACCEPTANCE.migration_desired_state().items()
                    if surface != "01/matt-link"
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
