import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "home/private_dot_local/lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from hindsight_memory_control_plane.harnesses import (
    OWNED_KEYS,
    apply_activation,
    activation_plan,
    render_harness,
    render_harnesses,
    rollback_activation,
)
from hindsight_memory_control_plane.canonical import digest


DIGESTS = {
    "inventory_digest": "1" * 64,
    "artifact_digest": "2" * 64,
    "policy_digest": "3" * 64,
}


class HarnessRenderingTest(unittest.TestCase):
    def setUp(self):
        self.existing = {
            "codex": {
                "hindsightApiUrl": "http://localhost:7979",
                "bankId": "engineering",
                "schema_version": None,
                "broker": {"transport": "tcp", "unknown_broker_option": 7},
                "adapter": {"id": "legacy", "registration": "keep"},
                "active": True,
                "unknown_setting": {"nested": [1, 2]},
                "registrations": [{"id": "third-party"}],
                "serviceEndpoint": "/other/service",
                "bankingPreference": "credit-union",
            },
            "claude-code": {"active": None, "theme": "warm"},
            "cursor": {"telemetry": False},
        }
        self.bindings = {
            "codex": "hindsight-codex",
            "claude-code": "hindsight-claude-code",
            "cursor": "hindsight-cursor",
        }

    def test_render_preserves_unknowns_and_records_exact_owned_prestate(self):
        outcome = render_harnesses(
            self.existing,
            self.bindings,
            socket_path="/Users/ivan/.local/state/hindsight-memory/broker.sock",
        )

        codex = outcome["codex"].to_dict()["rendered"]
        self.assertEqual(codex["unknown_setting"], {"nested": [1, 2]})
        self.assertEqual(codex["registrations"], [{"id": "third-party"}])
        self.assertEqual(codex["serviceEndpoint"], "/other/service")
        self.assertEqual(codex["bankingPreference"], "credit-union")
        self.assertTrue(
            {
                "hindsightApiUrl",
                "bankId",
            }.isdisjoint(codex)
        )
        self.assertEqual(
            set(codex) - set(self.existing["codex"]), set(OWNED_KEYS) - set(self.existing["codex"])
        )
        self.assertEqual(codex["schemaVersion"], 1)
        self.assertEqual(
            codex["broker"],
            {
                "transport": "unix",
                "path": "/Users/ivan/.local/state/hindsight-memory/broker.sock",
                "scope": "user",
            },
        )
        self.assertEqual(codex["adapter"], "hindsight-codex")
        self.assertIs(codex["active"], False)
        self.assertEqual(
            outcome["codex"].prestate["schemaVersion"], {"present": False}
        )
        self.assertNotIn("schema_version", outcome["codex"].prestate)
        self.assertEqual(outcome["cursor"].prestate["active"], {"present": False})
        serialized = json.dumps(
            {key: value.to_dict()["rendered"] for key, value in outcome.items()}
        ).lower()
        for forbidden in ("http://", "https://", "bankid", "bank_id", "bearer", "token", "signing"):
            self.assertNotIn(forbidden, serialized)

    def test_render_rejects_network_or_unsupported_harness_bindings(self):
        with self.assertRaisesRegex(ValueError, "Unix socket"):
            render_harnesses({}, self.bindings, socket_path="http://localhost:7979")
        with self.assertRaisesRegex(ValueError, "unsupported harness"):
            render_harnesses({}, {**self.bindings, "other": "x"}, socket_path="/tmp/broker.sock")

    def test_render_retires_direct_secret_fields_without_serializing_their_values(self):
        for key in ("tenantToken", "bearerToken", "apiKey", "signingKey"):
            with self.subTest(key=key):
                outcome = render_harness(
                    {key: "secret-value"},
                    harness_id="codex",
                    adapter="hindsight-codex",
                    socket_path="/Users/ivan/.local/state/hindsight-memory/broker.sock",
                )
                self.assertNotIn(key, outcome.rendered)
                self.assertNotIn("secret-value", json.dumps(outcome.to_dict()))


class HarnessActivationTest(unittest.TestCase):
    def setUp(self):
        self.current = {"active": False, "unknown": {"registration": "keep"}}
        self.rendered = render_harness(
            self.current,
            harness_id="codex",
            adapter="hindsight-codex",
            socket_path="/Users/ivan/.local/state/hindsight-memory/broker.sock",
        )
        self.plan = activation_plan(self.rendered, **DIGESTS)

    def apply(self, current=None, **overrides):
        gates = {
            **DIGESTS,
            "approved_plan_digest": self.plan.plan_digest,
            "broker_healthy": True,
            "profile_healthy": True,
            "adapter_self_test": True,
            "postcheck": True,
        }
        gates.update(overrides)
        return apply_activation(self.plan, self.current if current is None else current, **gates)

    def test_plan_is_immutable_digest_bound_and_names_required_gates(self):
        self.assertEqual(self.plan.harness_id, "codex")
        self.assertEqual(self.plan.inventory_digest, DIGESTS["inventory_digest"])
        self.assertRegex(self.plan.plan_digest, r"^[0-9a-f]{64}$")
        self.assertEqual(
            self.plan.requirements,
            ("broker_healthy", "profile_healthy", "adapter_self_test"),
        )
        self.assertIs(self.plan.owned_target["active"], True)
        with self.assertRaises(FrozenInstanceError):
            self.plan.plan_digest = "0" * 64

    def test_apply_changes_only_owned_active_after_all_fresh_gates_pass(self):
        outcome = self.apply()
        self.assertEqual((outcome.status, outcome.activation_state), ("activated", "active"))
        self.assertIs(outcome.configuration["active"], True)
        self.assertEqual(outcome.configuration["unknown"], {"registration": "keep"})
        for key in OWNED_KEYS - {"active"}:
            self.assertEqual(outcome.configuration[key], self.rendered.rendered[key])

    def test_apply_refuses_digest_health_self_test_or_exact_prestate_drift(self):
        cases = (
            ({"inventory_digest": "0" * 64}, "inventory_digest_changed"),
            ({"artifact_digest": "0" * 64}, "artifact_digest_changed"),
            ({"policy_digest": "0" * 64}, "policy_digest_changed"),
            ({"approved_plan_digest": "0" * 64}, "plan_not_approved"),
            ({"broker_healthy": False}, "broker_unhealthy"),
            ({"profile_healthy": False}, "profile_unhealthy"),
            ({"adapter_self_test": False}, "adapter_self_test_failed"),
        )
        for overrides, reason in cases:
            with self.subTest(reason=reason):
                outcome = self.apply(**overrides)
                self.assertEqual((outcome.status, outcome.reason), ("refused", reason))
                self.assertEqual(outcome.activation_state, "inactive")

        drifted = dict(self.current)
        drifted["adapter"] = None
        outcome = self.apply(drifted)
        self.assertEqual((outcome.status, outcome.reason), ("refused", "owned_prestate_changed"))
        self.assertEqual(outcome.activation_state, "inactive")

        registration_drifted = dict(self.current)
        registration_drifted["unknown"] = {"registration": "changed"}
        outcome = self.apply(registration_drifted)
        self.assertEqual((outcome.status, outcome.reason), ("refused", "prestate_changed"))
        self.assertEqual(outcome.activation_state, "inactive")

    def test_failed_postcheck_rolls_back_exact_owned_values_and_unknowns_stay(self):
        outcome = self.apply(postcheck=False)
        self.assertEqual((outcome.status, outcome.reason), ("rolled_back", "postcheck_failed"))
        self.assertTrue(outcome.rollback_attempted)
        self.assertTrue(outcome.rollback_succeeded)
        self.assertEqual(outcome.activation_state, "inactive")
        self.assertEqual(outcome.configuration, self.current)

    def test_plan_serialization_contains_no_owned_prestate_credentials(self):
        current = {
            "broker": {"transport": "tcp", "token": "broker-secret"},
            "adapter": {"apiKey": "adapter-secret"},
            "active": False,
        }
        rendered = render_harness(
            current,
            harness_id="codex",
            adapter="hindsight-codex",
            socket_path="/Users/ivan/.local/state/hindsight-memory/broker.sock",
        )
        plan = activation_plan(rendered, **DIGESTS)

        serialized = json.dumps({"rendered": rendered.to_dict(), "plan": plan.to_dict()})
        self.assertNotIn("broker-secret", serialized)
        self.assertNotIn("adapter-secret", serialized)

    def test_apply_rejects_a_self_consistent_plan_without_the_approved_digest(self):
        target = dict(self.plan.owned_target)
        target["broker"] = {"transport": "unix", "path": "/tmp/unapproved.sock", "scope": "user"}
        tampered = replace(self.plan, owned_target=target, plan_digest="0" * 64)
        tampered = replace(tampered, plan_digest=digest(tampered.body()))

        outcome = apply_activation(
            tampered,
            self.current,
            **DIGESTS,
            approved_plan_digest=self.plan.plan_digest,
            broker_healthy=True,
            profile_healthy=True,
            adapter_self_test=True,
            postcheck=True,
        )
        self.assertEqual((outcome.status, outcome.reason), ("refused", "plan_not_approved"))

    def test_failed_postcheck_restores_an_exact_active_prestate(self):
        original = {
            "schemaVersion": None,
            "active": True,
            "unknown": {"registration": "keep"},
        }
        rendered = render_harness(
            original,
            harness_id="codex",
            adapter="hindsight-codex",
            socket_path="/Users/ivan/.local/state/hindsight-memory/broker.sock",
        )
        plan = activation_plan(rendered, **DIGESTS)
        activated = rendered.to_dict()["rendered"]
        activated["active"] = True
        exact_rollback = rollback_activation(
            plan,
            activated,
            approved_plan_digest=plan.plan_digest,
            prestate=original,
        )
        self.assertEqual(exact_rollback.configuration, original)

        outcome = apply_activation(
            plan,
            original,
            **DIGESTS,
            approved_plan_digest=plan.plan_digest,
            broker_healthy=True,
            profile_healthy=True,
            adapter_self_test=True,
            postcheck=False,
        )

        self.assertEqual((outcome.status, outcome.reason), ("rolled_back", "postcheck_failed"))
        self.assertEqual(outcome.activation_state, "active")
        self.assertTrue(outcome.rollback_attempted)
        self.assertTrue(outcome.rollback_succeeded)
        self.assertEqual(outcome.configuration, original)

    def test_rollback_restores_missing_and_explicit_null_without_unknown_changes(self):
        prestate = render_harness(
            {"schemaVersion": None, "unknown": ["keep"]},
            harness_id="cursor",
            adapter="hindsight-cursor",
            socket_path="/Users/ivan/.local/state/hindsight-memory/broker.sock",
        )
        original = {"schemaVersion": None, "unknown": ["keep"]}
        plan = activation_plan(prestate, **DIGESTS)
        activated = {**prestate.to_dict()["rendered"], "active": True, "unknown": ["keep"]}
        outcome = rollback_activation(
            plan,
            activated,
            approved_plan_digest=plan.plan_digest,
            prestate=original,
        )
        self.assertEqual(outcome.status, "rolled_back")
        self.assertIsNone(outcome.configuration["schemaVersion"])
        self.assertNotIn("broker", outcome.configuration)
        self.assertNotIn("adapter", outcome.configuration)
        self.assertNotIn("active", outcome.configuration)
        self.assertEqual(outcome.configuration["unknown"], ["keep"])

    def test_activation_removes_retired_direct_fields_and_rollback_restores_snapshot(self):
        original = {
            "hindsightApiUrl": "http://localhost:7979",
            "bankId": "engineering",
            "tenantToken": "tenant-secret",
            "active": False,
            "registrations": [{"id": "third-party"}],
        }
        rendered = render_harness(
            original,
            harness_id="cursor",
            adapter="hindsight-cursor",
            socket_path="/Users/ivan/.local/state/hindsight-memory/broker.sock",
        )
        plan = activation_plan(rendered, **DIGESTS)
        outcome = apply_activation(
            plan,
            original,
            **DIGESTS,
            approved_plan_digest=plan.plan_digest,
            broker_healthy=True,
            profile_healthy=True,
            adapter_self_test=True,
            postcheck=True,
        )
        self.assertEqual((outcome.status, outcome.activation_state), ("activated", "active"))
        self.assertNotIn("hindsightApiUrl", outcome.configuration)
        self.assertNotIn("bankId", outcome.configuration)
        self.assertNotIn("tenantToken", outcome.configuration)
        self.assertEqual(outcome.configuration["registrations"], [{"id": "third-party"}])

        rollback = rollback_activation(
            plan,
            outcome.configuration,
            approved_plan_digest=plan.plan_digest,
            prestate=original,
        )
        self.assertEqual(rollback.configuration, original)

    def test_rollback_requires_approval_and_preserves_unrelated_current_changes(self):
        original = {
            "hindsightApiUrl": "http://localhost:7979",
            "active": False,
            "registrations": [{"id": "before"}],
        }
        rendered = render_harness(
            original,
            harness_id="codex",
            adapter="hindsight-codex",
            socket_path="/Users/ivan/.local/state/hindsight-memory/broker.sock",
        )
        plan = activation_plan(rendered, **DIGESTS)
        activated = dict(rendered.rendered)
        activated["active"] = True
        activated["registrations"] = [{"id": "after"}]

        refused = rollback_activation(
            plan,
            activated,
            approved_plan_digest="0" * 64,
            prestate=original,
        )
        self.assertEqual((refused.status, refused.reason), ("refused", "plan_not_approved"))

        target = dict(plan.owned_target)
        target["adapter"] = "unapproved-adapter"
        tampered = replace(plan, owned_target=target, plan_digest="0" * 64)
        tampered = replace(tampered, plan_digest=digest(tampered.body()))
        refused = rollback_activation(
            tampered,
            activated,
            approved_plan_digest=plan.plan_digest,
            prestate=original,
        )
        self.assertEqual((refused.status, refused.reason), ("refused", "plan_not_approved"))

        outcome = rollback_activation(
            plan,
            activated,
            approved_plan_digest=plan.plan_digest,
            prestate=original,
        )
        self.assertEqual((outcome.status, outcome.reason), ("rolled_back", "ok"))
        self.assertEqual(outcome.configuration["registrations"], [{"id": "after"}])
        self.assertEqual(outcome.configuration["hindsightApiUrl"], "http://localhost:7979")
        self.assertIs(outcome.configuration["active"], False)


class HarnessTemplateTest(unittest.TestCase):
    def test_templates_render_exact_inactive_broker_only_documents(self):
        expected_socket = str(Path.home() / ".local/state/hindsight-memory/broker.sock")
        for harness_id in ("codex", "claude-code", "cursor"):
            with self.subTest(harness_id=harness_id):
                template = ROOT / f"home/private_dot_hindsight/{harness_id}.json.tmpl"
                completed = subprocess.run(
                    ["chezmoi", "--source", "home", "execute-template"],
                    cwd=ROOT,
                    input=template.read_text(),
                    text=True,
                    capture_output=True,
                    check=True,
                )
                rendered = json.loads(completed.stdout)
                self.assertEqual(
                    rendered,
                    {
                        "schemaVersion": 1,
                        "broker": {
                            "transport": "unix",
                            "path": expected_socket,
                            "scope": "user",
                        },
                        "adapter": (
                            "hindsight-codex"
                            if harness_id == "codex"
                            else harness_id
                        ),
                        "active": False,
                    },
                )
                serialized = completed.stdout.lower()
                for forbidden in ("http://", "https://", "bank", "bearer", "token", "signing", "hook", "write"):
                    self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
