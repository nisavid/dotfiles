import unittest

from home.private_dot_local.lib.hindsight_memory_control_plane.airlock import (
    AirlockPlanError,
    CLOSEOUT_PROBES,
    PREFLIGHT_PROBES,
    validate_airlock_closeout,
    validate_airlock_plan,
)


class FakeOrbStackRunner:
    def __init__(self, failing=()):
        self.failing = set(failing)
        self.calls = []

    def probe(self, probe):
        self.calls.append(probe)
        return probe not in self.failing


def valid_candidate():
    return {
        "schema_version": 1,
        "backend": "orbstack",
        "machine": {
            "os": "linux",
            "fresh": True,
            "ephemeral": True,
            "macos_integration": False,
            "host_network": False,
            "peer_network": False,
            "separate_guest_kernel_required": False,
        },
        "mounts": {
            "inputs": [
                {"id": "task-source", "mode": "read-only"},
                {"id": "reviewed-bootstrap", "mode": "read-only"},
            ],
            "output": {
                "id": "encrypted-export",
                "mode": "write-only",
                "narrow": True,
            },
        },
        "egress": {
            "enforcement_owner": "root",
            "default_deny": True,
            "approved_destinations": ["provider.example:443"],
            "harness_can_modify": False,
        },
        "harness": {
            "kind": "cli",
            "host_gui": False,
            "principal": "airlock-agent",
            "unprivileged": True,
            "sudo": False,
            "setuid_escalation": False,
            "network_admin": False,
            "container_socket": False,
        },
        "probes": {
            "tamper_denied": [
                "firewall",
                "routes",
                "dns",
                "network_namespace",
                "broker_config",
            ],
            "unreachable": [
                "host_loopback",
                "host_broker_socket",
                "core_profile_endpoints",
                "undeclared_destinations",
            ],
        },
        "state": {
            "independent_profile": True,
            "independent_token": True,
            "independent_session": True,
            "reuses_oauth_home": False,
            "reuses_data_plane_token": False,
        },
        "retention": {
            "mode": "chunk-only",
            "enable_observations": False,
            "enable_auto_consolidation": False,
            "models": [],
            "refresh_routes": [],
            "mental_model_generation": False,
        },
        "recall": {"engineering": False, "personal": False, "core": False},
        "bootstrap": {
            "mount_id": "reviewed-bootstrap",
            "artifact_id": "airlock-bootstrap",
            "artifact_version": "v1",
            "artifact_digest": "b" * 64,
            "reviewed": True,
            "content_classes": [
                "transferable_engineering_principles",
                "security_rules",
            ],
            "excluded_classes": [
                "personal_content",
                "project_facts",
                "credentials",
                "operational_state",
            ],
        },
        "export": {"encrypted": True, "verify_before_teardown": True},
        "bridge": {
            "source_citations_required": True,
            "candidate_dispositions_required": True,
            "promotion_is_separate": True,
        },
        "teardown": {
            "immediate": True,
            "delete_bank": True,
            "delete_profile": True,
            "delete_machine": True,
        },
    }


class AirlockPlanTests(unittest.TestCase):
    def test_launch_requires_preflight_evidence_and_returns_an_immutable_plan(
        self,
    ):
        candidate = valid_candidate()
        runner = FakeOrbStackRunner()

        plan = validate_airlock_plan(candidate, runner)

        self.assertEqual(plan.to_dict(), candidate)
        self.assertEqual(runner.calls, list(PREFLIGHT_PROBES))
        self.assertFalse(set(runner.calls) & set(CLOSEOUT_PROBES))
        candidate["machine"]["fresh"] = False
        self.assertTrue(plan.machine["fresh"])
        with self.assertRaises(TypeError):
            plan.machine["fresh"] = False

    def test_closeout_verifies_export_bridge_dispositions_and_then_teardown(
        self,
    ):
        preflight_runner = FakeOrbStackRunner()
        plan = validate_airlock_plan(valid_candidate(), preflight_runner)
        closeout_runner = FakeOrbStackRunner()

        validate_airlock_closeout(plan, closeout_runner)

        self.assertEqual(closeout_runner.calls, list(CLOSEOUT_PROBES))
        export_index = closeout_runner.calls.index("export.encrypted.verified")
        bridge_index = closeout_runner.calls.index(
            "bridge.candidates.dispositioned"
        )
        immediate_index = closeout_runner.calls.index("teardown.immediate")
        self.assertLess(export_index, bridge_index)
        for probe in (
            "teardown.bank.deleted",
            "teardown.profile.deleted",
            "teardown.machine.deleted",
        ):
            self.assertLess(bridge_index, closeout_runner.calls.index(probe))
            self.assertLess(closeout_runner.calls.index(probe), immediate_index)

    def test_rejects_each_closed_airlock_boundary(self):
        cases = {
            "fresh machine": ("machine", "fresh", False),
            "Linux machine": ("machine", "os", "darwin"),
            "ephemeral machine": ("machine", "ephemeral", False),
            "macOS integration": ("machine", "macos_integration", True),
            "host networking": ("machine", "host_network", True),
            "peer networking": ("machine", "peer_network", True),
            "read-only inputs": (
                "mounts",
                "inputs",
                [{"id": "task-source", "mode": "read-write"}],
            ),
            "narrow output": (
                "mounts",
                "output",
                {"id": "export", "mode": "write-only", "narrow": False},
            ),
            "root egress": ("egress", "enforcement_owner", "airlock-agent"),
            "default-deny egress": ("egress", "default_deny", False),
            "unprivileged harness": ("harness", "unprivileged", False),
            "no sudo": ("harness", "sudo", True),
            "independent profile": ("state", "independent_profile", False),
            "independent token": ("state", "independent_token", False),
            "independent session": ("state", "independent_session", False),
            "chunk-only retention": ("retention", "mode", "observation"),
            "observations disabled": ("retention", "enable_observations", True),
            "consolidation disabled": (
                "retention",
                "enable_auto_consolidation",
                True,
            ),
            "models disabled": ("retention", "models", ["summarizer"]),
            "no core recall": ("recall", "core", True),
            "encrypted export": ("export", "encrypted", False),
            "verified export": ("export", "verify_before_teardown", False),
            "immediate teardown": ("teardown", "immediate", False),
        }
        for label, (section, field, value) in cases.items():
            with self.subTest(label=label):
                candidate = valid_candidate()
                candidate[section][field] = value
                with self.assertRaisesRegex(AirlockPlanError, label):
                    validate_airlock_plan(candidate, FakeOrbStackRunner())

    def test_requires_complete_tamper_and_reachability_probes(self):
        for group, probe in (
            ("tamper_denied", "firewall"),
            ("unreachable", "host_loopback"),
        ):
            with self.subTest(group=group, probe=probe):
                candidate = valid_candidate()
                candidate["probes"][group].remove(probe)
                with self.assertRaisesRegex(AirlockPlanError, "probe set"):
                    validate_airlock_plan(candidate, FakeOrbStackRunner())

        runner = FakeOrbStackRunner({"tamper.firewall.denied"})
        with self.assertRaisesRegex(AirlockPlanError, "tamper.firewall.denied"):
            validate_airlock_plan(valid_candidate(), runner)

    def test_requires_one_digest_bound_reviewed_non_sensitive_bootstrap(self):
        cases = {
            "reviewed": False,
            "artifact_version": "",
            "artifact_digest": "not-a-digest",
            "mount_id": "missing-bootstrap-input",
            "content_classes": ["security_rules"],
            "excluded_classes": ["personal_content"],
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                candidate = valid_candidate()
                candidate["bootstrap"][field] = value
                with self.assertRaisesRegex(AirlockPlanError, "bootstrap"):
                    validate_airlock_plan(candidate, FakeOrbStackRunner())

    def test_requires_verified_bank_profile_and_machine_deletion_after_export(
        self,
    ):
        for probe in (
            "teardown.bank.deleted",
            "teardown.profile.deleted",
            "teardown.machine.deleted",
        ):
            with self.subTest(probe=probe):
                with self.assertRaisesRegex(AirlockPlanError, probe):
                    validate_airlock_plan(
                        valid_candidate(), FakeOrbStackRunner()
                    )
                    validate_airlock_closeout(
                        validate_airlock_plan(
                            valid_candidate(), FakeOrbStackRunner()
                        ),
                        FakeOrbStackRunner({probe}),
                    )

    def test_rejects_host_gui_harnesses_before_any_probe(self):
        candidate = valid_candidate()
        candidate["harness"].update({"kind": "gui", "host_gui": True})
        runner = FakeOrbStackRunner()

        with self.assertRaisesRegex(AirlockPlanError, "host GUI"):
            validate_airlock_plan(candidate, runner)

        self.assertEqual(runner.calls, [])

    def test_rejects_unknown_plan_fields_and_non_boolean_probe_results(self):
        candidate = valid_candidate()
        candidate["host_home"] = "/Users/ivan"
        with self.assertRaisesRegex(AirlockPlanError, "closed"):
            validate_airlock_plan(candidate, FakeOrbStackRunner())

        class AmbiguousRunner:
            def probe(self, probe):
                return 1

        with self.assertRaisesRegex(AirlockPlanError, "boolean"):
            validate_airlock_plan(valid_candidate(), AmbiguousRunner())


if __name__ == "__main__":
    unittest.main()
