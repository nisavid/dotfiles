from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
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

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64


def valid_apply_authorization() -> dict[str, object]:
    return {
        "schema_version": "agent-equipment-apply-authorization/v1",
        "authorization_identity": "apply-authorization:sha256:" + "1" * 64,
        "issuer_identity": "authority:fixture/operator",
        "issued_at": "2026-08-13T07:00:00Z",
        "not_before": "2026-08-13T07:00:00Z",
        "expires_at": "2026-08-13T08:00:00Z",
        "execution_nonce": "execution-nonce:sha256:" + "2" * 64,
        "run_identity": "run:sha256:" + "3" * 64,
        "command": "apply",
        "bindings": {
            "candidate_identity": "candidate:fixture/controller-v1",
            "implementation_manifest_digest": DIGEST_A,
            "catalog_digest": DIGEST_B,
            "lock_digest": DIGEST_C,
            "plan_digest": DIGEST_A,
            "plan_action_set_digest": DIGEST_B,
            "capability_set_digest": DIGEST_C,
            "captured_state_identity": "capture:fixture/run-v1",
            "captured_state_digest": DIGEST_A,
            "expected_case_manifest_digest": DIGEST_B,
        },
    }


def valid_release_receipt() -> dict[str, object]:
    return {
        "schema_version": "agent-equipment-release-receipt/v1",
        "receipt_identity": "release-receipt:sha256:" + "4" * 64,
        "payload": {
            "issued_at": "2026-08-13T09:00:00Z",
            "outcome": "passed",
            "launcher_identity": "release-launcher:fixture/v1",
            "launcher_manifest_digest": DIGEST_A,
            "apply_authorization_digest": DIGEST_B,
            "candidate_identity": "candidate:fixture/controller-v1",
            "implementation_manifest_digest": DIGEST_C,
            "expected_case_manifest_digest": DIGEST_A,
            "evidence_bundle_digest": DIGEST_B,
            "attestation_manifest_digest": DIGEST_C,
            "archive_commit": {
                "archive_identity": "release-archive:fixture/candidate-v1",
                "archive_manifest_digest": DIGEST_A,
                "compare_token": "absent",
                "committed_generation": 1,
            },
        },
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
                candidate["payload"]["archive_commit"][field] = value
                self.assertFalse(self.validate(candidate))

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
