from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from datetime import datetime, timezone
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

AUTHORITY_SPEC = importlib.util.spec_from_file_location(
    "agent_equipment_execution_authority_test",
    ROOT / "scripts/agent_equipment_execution_authority.py",
)
assert AUTHORITY_SPEC is not None and AUTHORITY_SPEC.loader is not None
EXECUTION_AUTHORITY = importlib.util.module_from_spec(AUTHORITY_SPEC)
sys.modules[AUTHORITY_SPEC.name] = EXECUTION_AUTHORITY
AUTHORITY_SPEC.loader.exec_module(EXECUTION_AUTHORITY)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64


def canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def byte_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


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
        "execution_domain_identity": "execution-domain:fixture/global-ledger-v1",
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
            "operator_review_package_digest": DIGEST_C,
        },
    }


def seal_apply_authorization(document: dict[str, object]) -> str:
    payload = copy.deepcopy(document)
    payload.pop("authorization_identity", None)
    document["authorization_identity"] = "apply-authorization:" + canonical_digest(
        payload
    )
    return canonical_digest(document)


def execution_binding(
    authorization: dict[str, object], authorization_digest: str
) -> dict[str, object]:
    return {
        "apply_authorization_identity": authorization["authorization_identity"],
        "apply_authorization_digest": authorization_digest,
        "execution_domain_identity": authorization["execution_domain_identity"],
        "execution_nonce": authorization["execution_nonce"],
        "run_identity": authorization["run_identity"],
    }


def apply_validation_inputs(
    authorization: dict[str, object],
    *,
    trusted_now: datetime | None = None,
) -> dict[str, object]:
    bindings = authorization["bindings"]
    assert isinstance(bindings, dict)
    return {
        "expected_candidate_identity": bindings["candidate_identity"],
        "expected_implementation_manifest_digest": bindings[
            "implementation_manifest_digest"
        ],
        "expected_apply_authorization_identity": authorization[
            "authorization_identity"
        ],
        "expected_apply_authorization_digest": canonical_digest(authorization),
        "expected_execution_domain_identity": authorization[
            "execution_domain_identity"
        ],
        "expected_execution_nonce": authorization["execution_nonce"],
        "expected_run_identity": authorization["run_identity"],
        "expected_operator_review_package_digest": bindings[
            "operator_review_package_digest"
        ],
        "expected_issuer_identity": authorization["issuer_identity"],
        "trusted_now": trusted_now or datetime(2026, 8, 13, 7, 30, tzinfo=timezone.utc),
        "expected_bindings": copy.deepcopy(bindings),
    }


def valid_compensation_authorization() -> dict[str, object]:
    apply_authorization = valid_apply_authorization()
    apply_authorization_digest = seal_apply_authorization(apply_authorization)
    document: dict[str, object] = {
        "schema_version": "agent-equipment-compensation-authorization/v1",
        "compensation_authorization_identity": (
            "compensation-authorization:sha256:" + "8" * 64
        ),
        "issuer_identity": "authority:fixture/operator",
        "issued_at": "2026-08-13T09:00:00Z",
        "not_before": "2026-08-13T09:00:00Z",
        "expires_at": "2026-08-13T10:00:00Z",
        "compensation_nonce": "compensation-nonce:sha256:" + "9" * 64,
        "command": "compensate",
        "bindings": {
            "apply_authorization_identity": apply_authorization[
                "authorization_identity"
            ],
            "apply_authorization_digest": apply_authorization_digest,
            "execution_domain_identity": apply_authorization[
                "execution_domain_identity"
            ],
            "execution_nonce": apply_authorization["execution_nonce"],
            "run_identity": apply_authorization["run_identity"],
            "checkpoint_set_digest": DIGEST_D,
            "plan_action_set_digest": apply_authorization["bindings"][
                "plan_action_set_digest"
            ],
        },
    }
    seal_compensation_authorization(document)
    return document


def seal_compensation_authorization(document: dict[str, object]) -> str:
    payload = copy.deepcopy(document)
    payload.pop("compensation_authorization_identity", None)
    document["compensation_authorization_identity"] = (
        "compensation-authorization:" + canonical_digest(payload)
    )
    return canonical_digest(document)


def compensation_validation_inputs(
    authorization: dict[str, object],
) -> dict[str, object]:
    bindings = authorization["bindings"]
    assert isinstance(bindings, dict)
    return {
        "expected_compensation_authorization_identity": authorization[
            "compensation_authorization_identity"
        ],
        "expected_compensation_authorization_digest": canonical_digest(authorization),
        "expected_apply_authorization_identity": bindings[
            "apply_authorization_identity"
        ],
        "expected_apply_authorization_digest": bindings["apply_authorization_digest"],
        "expected_execution_domain_identity": bindings["execution_domain_identity"],
        "expected_execution_nonce": bindings["execution_nonce"],
        "expected_run_identity": bindings["run_identity"],
        "expected_checkpoint_set_digest": bindings["checkpoint_set_digest"],
        "expected_plan_action_set_digest": bindings["plan_action_set_digest"],
        "expected_compensation_nonce": authorization["compensation_nonce"],
        "expected_issuer_identity": authorization["issuer_identity"],
        "trusted_now": datetime(2026, 8, 13, 9, 30, tzinfo=timezone.utc),
    }


def valid_release_archive_manifest() -> dict[str, object]:
    authorization = valid_apply_authorization()
    authorization_digest = seal_apply_authorization(authorization)
    payload = {
        "candidate_identity": authorization["bindings"]["candidate_identity"],
        "implementation_manifest_digest": authorization["bindings"][
            "implementation_manifest_digest"
        ],
        "execution_binding": execution_binding(authorization, authorization_digest),
        "launcher_identity": "release-launcher:fixture/v1",
        "launcher_manifest_digest": DIGEST_A,
        "archive_destination": {
            "store_identity": "release-store:fixture/authority",
            "store_key": "archive-key:fixture/candidate-v1",
            "compare_token": "absent",
            "committed_generation": 1,
        },
        "archived_document_byte_digests": {
            "apply_authorization_bytes_digest": DIGEST_D,
            "expected_case_manifest_bytes_digest": DIGEST_A,
            "evidence_bundle_bytes_digest": DIGEST_B,
            "attestation_manifest_bytes_digest": DIGEST_C,
        },
    }
    document: dict[str, object] = {
        "schema_version": "agent-equipment-release-archive-manifest/v1",
        "archive_identity": "release-archive:" + canonical_digest(payload),
        "payload": payload,
        "archive_manifest_digest": "",
    }
    unsigned = copy.deepcopy(document)
    del unsigned["archive_manifest_digest"]
    document["archive_manifest_digest"] = canonical_digest(unsigned)
    return document


def valid_release_receipt(
    archive: dict[str, object] | None = None,
) -> dict[str, object]:
    archive = archive or valid_release_archive_manifest()
    archive_payload = archive["payload"]
    assert isinstance(archive_payload, dict)
    payload = {
        "issued_at": "2026-08-13T09:00:00Z",
        "outcome": "passed",
        "candidate_identity": archive_payload["candidate_identity"],
        "implementation_manifest_digest": archive_payload[
            "implementation_manifest_digest"
        ],
        "execution_binding": copy.deepcopy(archive_payload["execution_binding"]),
        "launcher_identity": archive_payload["launcher_identity"],
        "launcher_manifest_digest": archive_payload["launcher_manifest_digest"],
        "archive_identity": archive["archive_identity"],
        "archive_manifest_digest": archive["archive_manifest_digest"],
        "archive_destination": copy.deepcopy(archive_payload["archive_destination"]),
    }
    return {
        "schema_version": "agent-equipment-release-receipt/v1",
        "receipt_identity": "release-receipt:" + canonical_digest(payload),
        "payload": payload,
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

    def test_apply_authorization_identity_and_operator_review_are_semantic_authority(
        self,
    ) -> None:
        authorization = valid_apply_authorization()
        trusted_digest = seal_apply_authorization(authorization)
        self.assertEqual(
            authorization["authorization_identity"],
            "apply-authorization:sha256:bd5f01148ad90227e2b0acf50f1831a8d69ae107664f0d455a0e719bde4a0e71",
        )
        self.assertEqual(
            trusted_digest,
            "sha256:d993ccb152cf6a6b16ed12c0683db8ad4c739d2f531bd9d6b67dc459c00a759b",
        )

        diagnostics = EXECUTION_AUTHORITY.validate_apply_authorization(
            authorization,
            expected_candidate_identity=authorization["bindings"]["candidate_identity"],
            expected_implementation_manifest_digest=authorization["bindings"][
                "implementation_manifest_digest"
            ],
            expected_apply_authorization_identity=authorization[
                "authorization_identity"
            ],
            expected_apply_authorization_digest=trusted_digest,
            expected_execution_domain_identity=authorization[
                "execution_domain_identity"
            ],
            expected_execution_nonce=authorization["execution_nonce"],
            expected_run_identity=authorization["run_identity"],
            expected_operator_review_package_digest=authorization["bindings"][
                "operator_review_package_digest"
            ],
            expected_issuer_identity=authorization["issuer_identity"],
            trusted_now=datetime(2026, 8, 13, 7, 30, tzinfo=timezone.utc),
            expected_bindings=authorization["bindings"],
        )
        self.assertEqual(diagnostics, ())

        forged = copy.deepcopy(authorization)
        forged["bindings"]["operator_review_package_digest"] = DIGEST_A
        forged_digest = seal_apply_authorization(forged)
        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_apply_authorization(
                forged,
                expected_candidate_identity=forged["bindings"]["candidate_identity"],
                expected_implementation_manifest_digest=forged["bindings"][
                    "implementation_manifest_digest"
                ],
                expected_apply_authorization_identity=forged["authorization_identity"],
                expected_apply_authorization_digest=forged_digest,
                expected_execution_domain_identity=forged["execution_domain_identity"],
                expected_execution_nonce=forged["execution_nonce"],
                expected_run_identity=forged["run_identity"],
                expected_operator_review_package_digest=DIGEST_C,
                expected_issuer_identity=forged["issuer_identity"],
                trusted_now=datetime(2026, 8, 13, 7, 30, tzinfo=timezone.utc),
                expected_bindings=authorization["bindings"],
            )
        }
        self.assertIn("OPERATOR_REVIEW_PACKAGE_BINDING_MISMATCH", codes)

    def test_apply_authorization_validates_the_complete_tuple_and_time_window(
        self,
    ) -> None:
        authorization = valid_apply_authorization()
        trusted_digest = seal_apply_authorization(authorization)
        trusted_bindings = copy.deepcopy(authorization["bindings"])
        trusted_inputs = {
            "expected_candidate_identity": trusted_bindings["candidate_identity"],
            "expected_implementation_manifest_digest": trusted_bindings[
                "implementation_manifest_digest"
            ],
            "expected_apply_authorization_identity": authorization[
                "authorization_identity"
            ],
            "expected_apply_authorization_digest": trusted_digest,
            "expected_execution_domain_identity": authorization[
                "execution_domain_identity"
            ],
            "expected_execution_nonce": authorization["execution_nonce"],
            "expected_run_identity": authorization["run_identity"],
            "expected_operator_review_package_digest": trusted_bindings[
                "operator_review_package_digest"
            ],
            "expected_issuer_identity": authorization["issuer_identity"],
            "trusted_now": datetime(2026, 8, 13, 7, 30, tzinfo=timezone.utc),
            "expected_bindings": trusted_bindings,
        }
        self.assertEqual(
            EXECUTION_AUTHORITY.validate_apply_authorization(
                authorization, **trusted_inputs
            ),
            (),
        )

        mutations = {
            "issuer": lambda candidate: candidate.update(
                {"issuer_identity": "authority:fixture/other"}
            ),
            "catalog": lambda candidate: candidate["bindings"].update(
                {"catalog_digest": DIGEST_A}
            ),
            "lock": lambda candidate: candidate["bindings"].update(
                {"lock_digest": DIGEST_A}
            ),
            "plan": lambda candidate: candidate["bindings"].update(
                {"plan_digest": DIGEST_B}
            ),
            "action set": lambda candidate: candidate["bindings"].update(
                {"plan_action_set_digest": DIGEST_C}
            ),
            "capability set": lambda candidate: candidate["bindings"].update(
                {"capability_set_digest": DIGEST_A}
            ),
            "capture": lambda candidate: candidate["bindings"].update(
                {"captured_state_digest": DIGEST_B}
            ),
            "expected cases": lambda candidate: candidate["bindings"].update(
                {"expected_case_manifest_digest": DIGEST_A}
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                candidate = copy.deepcopy(authorization)
                mutate(candidate)
                candidate_digest = seal_apply_authorization(candidate)
                inputs = dict(trusted_inputs)
                inputs["expected_apply_authorization_identity"] = candidate[
                    "authorization_identity"
                ]
                inputs["expected_apply_authorization_digest"] = candidate_digest
                codes = {
                    diagnostic.code
                    for diagnostic in EXECUTION_AUTHORITY.validate_apply_authorization(
                        candidate, **inputs
                    )
                }
                self.assertIn("APPLY_AUTHORIZATION_BINDING_MISMATCH", codes)

        for label, trusted_now in (
            ("before", datetime(2026, 8, 13, 6, 59, 59, tzinfo=timezone.utc)),
            ("expired", datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)),
        ):
            with self.subTest(label=label):
                inputs = dict(trusted_inputs)
                inputs["trusted_now"] = trusted_now
                codes = {
                    diagnostic.code
                    for diagnostic in EXECUTION_AUTHORITY.validate_apply_authorization(
                        authorization, **inputs
                    )
                }
                self.assertIn("APPLY_AUTHORIZATION_TIME_INVALID", codes)

        for label, trusted_now in (
            ("naive", datetime(2026, 8, 13, 7, 30)),  # noqa: DTZ001
            ("non-datetime", "2026-08-13T07:30:00Z"),
        ):
            with self.subTest(label=label):
                inputs = dict(trusted_inputs)
                inputs["trusted_now"] = trusted_now
                diagnostics = EXECUTION_AUTHORITY.validate_apply_authorization(
                    authorization, **inputs
                )
                self.assertEqual(
                    [diagnostic.code for diagnostic in diagnostics],
                    ["TRUSTED_CLOCK_INVALID"],
                )

    def test_apply_authorization_is_bound_to_one_trusted_execution_domain(
        self,
    ) -> None:
        authorization = valid_apply_authorization()
        seal_apply_authorization(authorization)
        trusted_inputs = apply_validation_inputs(authorization)

        self.assertEqual(
            EXECUTION_AUTHORITY.validate_apply_authorization(
                authorization, **trusted_inputs
            ),
            (),
        )
        foreign_inputs = dict(trusted_inputs)
        foreign_inputs["expected_execution_domain_identity"] = (
            "execution-domain:fixture/other-ledger-v1"
        )
        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_apply_authorization(
                authorization, **foreign_inputs
            )
        }
        self.assertIn("EXECUTION_DOMAIN_MISMATCH", codes)
        self.assertEqual(
            EXECUTION_AUTHORITY.authorization_ledger_claim_identity(
                authorization["execution_domain_identity"],
                authorization["execution_nonce"],
            ),
            "authorization-ledger-claim:sha256:"
            "9e9791ab1c9634b4c9740924bf7370ce1418ab20e1a9666656e8c43ad2c36ebd",
        )

    def test_apply_authorization_compares_arbitrary_fractional_seconds_exactly(
        self,
    ) -> None:
        authorization = valid_apply_authorization()
        authorization["issued_at"] = "2026-08-13T06:59:59Z"
        authorization["not_before"] = "2026-08-13T07:00:00.0000009Z"
        seal_apply_authorization(authorization)
        diagnostics = EXECUTION_AUTHORITY.validate_apply_authorization(
            authorization,
            **apply_validation_inputs(
                authorization,
                trusted_now=datetime(2026, 8, 13, 7, 0, tzinfo=timezone.utc),
            ),
        )
        self.assertIn(
            "APPLY_AUTHORIZATION_TIME_INVALID",
            {diagnostic.code for diagnostic in diagnostics},
        )

        authorization["not_before"] = "2026-08-13T07:00:00Z"
        authorization["expires_at"] = "2026-08-13T07:00:00.9999999Z"
        seal_apply_authorization(authorization)
        diagnostics = EXECUTION_AUTHORITY.validate_apply_authorization(
            authorization,
            **apply_validation_inputs(
                authorization,
                trusted_now=datetime(2026, 8, 13, 7, 0, 0, 999999, tzinfo=timezone.utc),
            ),
        )
        self.assertEqual(diagnostics, ())

        authorization["not_before"] = "2026-08-13T07:00:00." + "0" * 5000 + "1Z"
        authorization["expires_at"] = "2026-08-13T08:00:00Z"
        seal_apply_authorization(authorization)
        diagnostics = EXECUTION_AUTHORITY.validate_apply_authorization(
            authorization,
            **apply_validation_inputs(
                authorization,
                trusted_now=datetime(2026, 8, 13, 7, 0, tzinfo=timezone.utc),
            ),
        )
        self.assertIn(
            "APPLY_AUTHORIZATION_TIME_INVALID",
            {diagnostic.code for diagnostic in diagnostics},
        )

    def test_compensation_authorization_is_closed_and_independently_trusted(
        self,
    ) -> None:
        authorization = valid_compensation_authorization()
        self.assertTrue(self.validate(authorization))
        self.assertEqual(
            authorization["compensation_authorization_identity"],
            "compensation-authorization:sha256:"
            "8bec97e8dfc9e687c27d7131d9f1fa8a5bbf31eaf3949387182241a8f876020c",
        )
        self.assertEqual(
            canonical_digest(authorization),
            "sha256:40f167515f61373b46b1a16301199f1254020b29611b4e5035bf09de2765628d",
        )
        self.assertEqual(
            EXECUTION_AUTHORITY.validate_compensation_authorization(
                authorization, **compensation_validation_inputs(authorization)
            ),
            (),
        )
        bindings = authorization["bindings"]
        assert isinstance(bindings, dict)
        self.assertEqual(
            EXECUTION_AUTHORITY.compensation_ledger_claim_identity(
                bindings["execution_domain_identity"],
                authorization["compensation_nonce"],
            ),
            "compensation-ledger-claim:sha256:"
            "657d939e28c931af52c8d160eb199e058bf2db98817412581a6ec7bba5e88632",
        )

        for field in tuple(bindings):
            with self.subTest(field=field):
                candidate = copy.deepcopy(authorization)
                del candidate["bindings"][field]
                self.assertFalse(self.validate(candidate))

    def test_compensation_authorization_rejects_resealing_and_forward_apply(
        self,
    ) -> None:
        authorization = valid_compensation_authorization()
        trusted_inputs = compensation_validation_inputs(authorization)
        mutations = {
            "apply authorization": lambda candidate: candidate["bindings"].update(
                {"apply_authorization_digest": DIGEST_A}
            ),
            "execution domain": lambda candidate: candidate["bindings"].update(
                {"execution_domain_identity": "execution-domain:fixture/other"}
            ),
            "run": lambda candidate: candidate["bindings"].update(
                {"run_identity": "run:sha256:" + "a" * 64}
            ),
            "checkpoint set": lambda candidate: candidate["bindings"].update(
                {"checkpoint_set_digest": DIGEST_A}
            ),
            "action set": lambda candidate: candidate["bindings"].update(
                {"plan_action_set_digest": DIGEST_A}
            ),
            "nonce": lambda candidate: candidate.update(
                {"compensation_nonce": "compensation-nonce:sha256:" + "a" * 64}
            ),
            "issuer": lambda candidate: candidate.update(
                {"issuer_identity": "authority:fixture/other"}
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                candidate = copy.deepcopy(authorization)
                mutate(candidate)
                seal_compensation_authorization(candidate)
                codes = {
                    diagnostic.code
                    for diagnostic in EXECUTION_AUTHORITY.validate_compensation_authorization(
                        candidate, **trusted_inputs
                    )
                }
                self.assertIn("COMPENSATION_AUTHORIZATION_BINDING_MISMATCH", codes)
                self.assertIn("COMPENSATION_AUTHORIZATION_TRUST_MISMATCH", codes)
                self.assertIn("COMPENSATION_AUTHORIZATION_DIGEST_MISMATCH", codes)

        for label, trusted_now in (
            ("not yet valid", datetime(2026, 8, 13, 8, 59, 59, tzinfo=timezone.utc)),
            ("expired", datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc)),
        ):
            with self.subTest(label=label):
                inputs = compensation_validation_inputs(authorization)
                inputs["trusted_now"] = trusted_now
                codes = {
                    diagnostic.code
                    for diagnostic in EXECUTION_AUTHORITY.validate_compensation_authorization(
                        authorization, **inputs
                    )
                }
                self.assertIn("COMPENSATION_AUTHORIZATION_TIME_INVALID", codes)

        apply_authorization = valid_apply_authorization()
        seal_apply_authorization(apply_authorization)
        diagnostics = EXECUTION_AUTHORITY.validate_compensation_authorization(
            apply_authorization, **trusted_inputs
        )
        self.assertEqual(
            [diagnostic.code for diagnostic in diagnostics],
            ["COMPENSATION_AUTHORIZATION_SCHEMA_INVALID"],
        )

        candidate = copy.deepcopy(authorization)
        candidate["command"] = "apply"
        self.assertFalse(self.validate(candidate))

        apply_inputs = apply_validation_inputs(apply_authorization)
        diagnostics = EXECUTION_AUTHORITY.validate_apply_authorization(
            authorization, **apply_inputs
        )
        self.assertEqual(
            [diagnostic.code for diagnostic in diagnostics],
            ["APPLY_AUTHORIZATION_SCHEMA_INVALID"],
        )

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
            "execution_domain_identity",
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
                candidate["payload"]["archive_destination"][field] = value
                self.assertFalse(self.validate(candidate))

    def test_release_archive_manifest_and_receipt_bind_exact_bytes_and_execution(
        self,
    ) -> None:
        archive = valid_release_archive_manifest()
        receipt = valid_release_receipt(archive)
        self.assertEqual(
            archive["archive_identity"],
            "release-archive:sha256:ffcd88a835be1bf7f1c9159da4af94540030f415180ce5decb1beaeb467c9f72",
        )
        self.assertEqual(
            archive["archive_manifest_digest"],
            "sha256:effb2db5b024aba3a5ff6b4160ddb002250388094a6a11d44d0ff85bd703c003",
        )
        self.assertEqual(
            receipt["receipt_identity"],
            "release-receipt:sha256:021c6c45f71149ba32d05cd73ef554c45a2013e71e06b25ee9021b7410936d9c",
        )
        payload = archive["payload"]
        assert isinstance(payload, dict)
        trusted_execution = copy.deepcopy(payload["execution_binding"])
        trusted_byte_digests = copy.deepcopy(payload["archived_document_byte_digests"])
        self.assertNotEqual(
            trusted_byte_digests["apply_authorization_bytes_digest"],
            trusted_execution["apply_authorization_digest"],
        )
        destination = payload["archive_destination"]
        assert isinstance(destination, dict)

        archive_diagnostics = EXECUTION_AUTHORITY.validate_release_archive_manifest(
            archive,
            expected_candidate_identity=payload["candidate_identity"],
            expected_implementation_manifest_digest=payload[
                "implementation_manifest_digest"
            ],
            expected_execution_binding=trusted_execution,
            expected_launcher_identity=payload["launcher_identity"],
            expected_launcher_manifest_digest=payload["launcher_manifest_digest"],
            expected_store_identity=destination["store_identity"],
            expected_store_key=destination["store_key"],
            expected_archived_document_byte_digests=trusted_byte_digests,
        )
        self.assertEqual(archive_diagnostics, ())

        receipt_diagnostics = EXECUTION_AUTHORITY.validate_release_receipt(
            receipt,
            expected_candidate_identity=payload["candidate_identity"],
            expected_implementation_manifest_digest=payload[
                "implementation_manifest_digest"
            ],
            expected_execution_binding=trusted_execution,
            expected_launcher_identity=payload["launcher_identity"],
            expected_launcher_manifest_digest=payload["launcher_manifest_digest"],
            expected_archive_identity=archive["archive_identity"],
            expected_archive_manifest_digest=archive["archive_manifest_digest"],
            expected_store_identity=destination["store_identity"],
            expected_store_key=destination["store_key"],
        )
        self.assertEqual(receipt_diagnostics, ())

        forged_archive = copy.deepcopy(archive)
        forged_archive["payload"]["execution_binding"]["run_identity"] = (
            "run:sha256:" + "8" * 64
        )
        forged_archive["archive_identity"] = "release-archive:" + canonical_digest(
            forged_archive["payload"]
        )
        unsigned = copy.deepcopy(forged_archive)
        del unsigned["archive_manifest_digest"]
        forged_archive["archive_manifest_digest"] = canonical_digest(unsigned)
        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_release_archive_manifest(
                forged_archive,
                expected_candidate_identity=payload["candidate_identity"],
                expected_implementation_manifest_digest=payload[
                    "implementation_manifest_digest"
                ],
                expected_execution_binding=trusted_execution,
                expected_launcher_identity=payload["launcher_identity"],
                expected_launcher_manifest_digest=payload["launcher_manifest_digest"],
                expected_store_identity=destination["store_identity"],
                expected_store_key=destination["store_key"],
                expected_archived_document_byte_digests=trusted_byte_digests,
            )
        }
        self.assertIn("EXECUTION_BINDING_MISMATCH", codes)

        foreign_domain_archive = copy.deepcopy(archive)
        foreign_domain_archive["payload"]["execution_binding"][
            "execution_domain_identity"
        ] = "execution-domain:fixture/other-ledger-v1"
        foreign_domain_archive["archive_identity"] = (
            "release-archive:" + canonical_digest(foreign_domain_archive["payload"])
        )
        unsigned = copy.deepcopy(foreign_domain_archive)
        del unsigned["archive_manifest_digest"]
        foreign_domain_archive["archive_manifest_digest"] = canonical_digest(unsigned)
        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_release_archive_manifest(
                foreign_domain_archive,
                expected_candidate_identity=payload["candidate_identity"],
                expected_implementation_manifest_digest=payload[
                    "implementation_manifest_digest"
                ],
                expected_execution_binding=trusted_execution,
                expected_launcher_identity=payload["launcher_identity"],
                expected_launcher_manifest_digest=payload["launcher_manifest_digest"],
                expected_store_identity=destination["store_identity"],
                expected_store_key=destination["store_key"],
                expected_archived_document_byte_digests=trusted_byte_digests,
            )
        }
        self.assertIn("EXECUTION_BINDING_MISMATCH", codes)

        forged_bytes = copy.deepcopy(archive)
        forged_bytes["payload"]["archived_document_byte_digests"][
            "evidence_bundle_bytes_digest"
        ] = DIGEST_A
        forged_bytes["archive_identity"] = "release-archive:" + canonical_digest(
            forged_bytes["payload"]
        )
        unsigned = copy.deepcopy(forged_bytes)
        del unsigned["archive_manifest_digest"]
        forged_bytes["archive_manifest_digest"] = canonical_digest(unsigned)
        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_release_archive_manifest(
                forged_bytes,
                expected_candidate_identity=payload["candidate_identity"],
                expected_implementation_manifest_digest=payload[
                    "implementation_manifest_digest"
                ],
                expected_execution_binding=trusted_execution,
                expected_launcher_identity=payload["launcher_identity"],
                expected_launcher_manifest_digest=payload["launcher_manifest_digest"],
                expected_store_identity=destination["store_identity"],
                expected_store_key=destination["store_key"],
                expected_archived_document_byte_digests=trusted_byte_digests,
            )
        }
        self.assertIn("ARCHIVED_DOCUMENT_BYTES_MISMATCH", codes)

        forged_receipt = copy.deepcopy(receipt)
        forged_receipt["payload"]["execution_binding"]["run_identity"] = (
            "run:sha256:" + "8" * 64
        )
        forged_receipt["receipt_identity"] = "release-receipt:" + canonical_digest(
            forged_receipt["payload"]
        )
        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_release_receipt(
                forged_receipt,
                expected_candidate_identity=payload["candidate_identity"],
                expected_implementation_manifest_digest=payload[
                    "implementation_manifest_digest"
                ],
                expected_execution_binding=trusted_execution,
                expected_launcher_identity=payload["launcher_identity"],
                expected_launcher_manifest_digest=payload["launcher_manifest_digest"],
                expected_archive_identity=archive["archive_identity"],
                expected_archive_manifest_digest=archive["archive_manifest_digest"],
                expected_store_identity=destination["store_identity"],
                expected_store_key=destination["store_key"],
            )
        }
        self.assertIn("EXECUTION_BINDING_MISMATCH", codes)

        foreign_domain_receipt = copy.deepcopy(receipt)
        foreign_domain_receipt["payload"]["execution_binding"][
            "execution_domain_identity"
        ] = "execution-domain:fixture/other-ledger-v1"
        foreign_domain_receipt["receipt_identity"] = (
            "release-receipt:" + canonical_digest(foreign_domain_receipt["payload"])
        )
        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_release_receipt(
                foreign_domain_receipt,
                expected_candidate_identity=payload["candidate_identity"],
                expected_implementation_manifest_digest=payload[
                    "implementation_manifest_digest"
                ],
                expected_execution_binding=trusted_execution,
                expected_launcher_identity=payload["launcher_identity"],
                expected_launcher_manifest_digest=payload["launcher_manifest_digest"],
                expected_archive_identity=archive["archive_identity"],
                expected_archive_manifest_digest=archive["archive_manifest_digest"],
                expected_store_identity=destination["store_identity"],
                expected_store_key=destination["store_key"],
            )
        }
        self.assertIn("EXECUTION_BINDING_MISMATCH", codes)

    def test_release_authority_uses_shared_public_data_policy(self) -> None:
        archive = valid_release_archive_manifest()
        payload = archive["payload"]
        assert isinstance(payload, dict)
        destination = payload["archive_destination"]
        assert isinstance(destination, dict)
        self.assertFalse(EXECUTION_AUTHORITY.contains_literal_credential(archive))

        archive["payload"]["archive_destination"]["store_key"] = (
            "archive-key:ghp_" + "A" * 24
        )
        archive["archive_identity"] = "release-archive:" + canonical_digest(
            archive["payload"]
        )
        unsigned = copy.deepcopy(archive)
        del unsigned["archive_manifest_digest"]
        archive["archive_manifest_digest"] = canonical_digest(unsigned)
        diagnostics = EXECUTION_AUTHORITY.validate_release_archive_manifest(
            archive,
            expected_candidate_identity=payload["candidate_identity"],
            expected_implementation_manifest_digest=payload[
                "implementation_manifest_digest"
            ],
            expected_execution_binding=payload["execution_binding"],
            expected_launcher_identity=payload["launcher_identity"],
            expected_launcher_manifest_digest=payload["launcher_manifest_digest"],
            expected_store_identity=destination["store_identity"],
            expected_store_key=archive["payload"]["archive_destination"]["store_key"],
            expected_archived_document_byte_digests=payload[
                "archived_document_byte_digests"
            ],
        )
        self.assertEqual(
            {diagnostic.code for diagnostic in diagnostics},
            {"RELEASE_ARCHIVE_LITERAL_SECRET"},
        )

    def test_archive_byte_digest_is_distinct_from_authorization_canonical_digest(
        self,
    ) -> None:
        authorization = valid_apply_authorization()
        canonical_authorization_digest = seal_apply_authorization(authorization)
        compact_bytes = json.dumps(
            authorization,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        pretty_bytes = json.dumps(
            authorization,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        compact_digest = byte_digest(compact_bytes)
        pretty_digest = byte_digest(pretty_bytes)
        self.assertEqual(compact_digest, canonical_authorization_digest)
        self.assertNotEqual(pretty_digest, canonical_authorization_digest)

        archive = valid_release_archive_manifest()
        payload = archive["payload"]
        assert isinstance(payload, dict)
        destination = payload["archive_destination"]
        assert isinstance(destination, dict)
        payload["archived_document_byte_digests"][
            "apply_authorization_bytes_digest"
        ] = compact_digest
        archive["archive_identity"] = "release-archive:" + canonical_digest(payload)
        unsigned = copy.deepcopy(archive)
        del unsigned["archive_manifest_digest"]
        archive["archive_manifest_digest"] = canonical_digest(unsigned)
        expected_byte_digests = copy.deepcopy(payload["archived_document_byte_digests"])
        expected_byte_digests["apply_authorization_bytes_digest"] = pretty_digest

        codes = {
            diagnostic.code
            for diagnostic in EXECUTION_AUTHORITY.validate_release_archive_manifest(
                archive,
                expected_candidate_identity=payload["candidate_identity"],
                expected_implementation_manifest_digest=payload[
                    "implementation_manifest_digest"
                ],
                expected_execution_binding=payload["execution_binding"],
                expected_launcher_identity=payload["launcher_identity"],
                expected_launcher_manifest_digest=payload["launcher_manifest_digest"],
                expected_store_identity=destination["store_identity"],
                expected_store_key=destination["store_key"],
                expected_archived_document_byte_digests=expected_byte_digests,
            )
        }
        self.assertIn("ARCHIVED_DOCUMENT_BYTES_MISMATCH", codes)

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
