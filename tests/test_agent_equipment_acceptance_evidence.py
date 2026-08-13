from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "docs/agent-equipment/acceptance-evidence-v1.schema.json"
SCRIPT = ROOT / "scripts/agent_equipment_acceptance_evidence.py"
SPEC = importlib.util.spec_from_file_location(
    "agent_equipment_acceptance_evidence",
    SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
ACCEPTANCE_EVIDENCE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ACCEPTANCE_EVIDENCE
SPEC.loader.exec_module(ACCEPTANCE_EVIDENCE)


DIGESTS = {
    name: "sha256:" + character * 64
    for name, character in {
        "implementation_manifest_digest": "a",
        "catalog_digest": "b",
        "lock_digest": "c",
        "plan_digest": "d",
        "plan_action_set_digest": "e",
        "capability_set_digest": "f",
        "captured_state_digest": "1",
    }.items()
}
CANDIDATE_IDENTITY = "candidate:fixture/controller-v1"


def canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def case_identity(
    requirement_id: str,
    fixture_family: str,
    subject_identity: str,
) -> str:
    return "case:" + canonical_digest(
        {
            "fixture_family": fixture_family,
            "requirement_id": requirement_id,
            "subject_identity": subject_identity,
        }
    )


def requirement_ids() -> tuple[str, ...]:
    groups = (
        ("CAT", 14),
        ("RES", 5),
        ("CMD", 6),
        ("CON", 11),
        ("ADP", 8),
        ("CAP", 7),
        ("CHK", 10),
        ("MIG", 7),
        ("LIVE", 6),
    )
    return tuple(
        f"{prefix}-{number:02d}"
        for prefix, count in groups
        for number in range(1, count + 1)
    )


CHECKPOINT_MATRIX = tuple(f"CHK-{number:02d}" for number in range(2, 10))
MIGRATION_REQUIREMENTS = tuple(f"MIG-{number:02d}" for number in range(1, 8))


def bindings() -> dict[str, str]:
    return {
        "candidate_identity": CANDIDATE_IDENTITY,
        **DIGESTS,
        "captured_state_identity": "capture:sha256:" + "2" * 64,
    }


def make_case(
    requirement_id: str,
    fixture_family: str,
    subject_identity: str,
    evidence_kind: str,
) -> dict[str, str]:
    return {
        "case_identity": case_identity(
            requirement_id,
            fixture_family,
            subject_identity,
        ),
        "requirement_id": requirement_id,
        "fixture_family": fixture_family,
        "subject_identity": subject_identity,
        "evidence_kind": evidence_kind,
    }


def valid_expected_case_manifest() -> dict[str, object]:
    matrix_requirements = set(CHECKPOINT_MATRIX) | set(MIGRATION_REQUIREMENTS)
    static_cases = []
    for requirement_id in requirement_ids():
        if requirement_id in matrix_requirements:
            continue
        if requirement_id.startswith("LIVE-"):
            evidence_kind = "live_receipt"
        elif requirement_id in {"CHK-01", "CHK-10"}:
            evidence_kind = "checkpoint_trace"
        elif requirement_id == "CON-01":
            evidence_kind = "mutation_receipt"
        else:
            evidence_kind = "automated_receipt"
        static_cases.append(
            make_case(
                requirement_id,
                "requirement-fixture",
                f"fixture:{requirement_id.lower()}",
                evidence_kind,
            )
        )

    document: dict[str, object] = {
        "schema_version": "agent-equipment-acceptance-expected-cases/v1",
        "bindings": bindings(),
        "fixture_version": "fixture-suite:2026-08-13",
        "requirements": [
            {
                "requirement_id": requirement_id,
                "evidence_mode": (
                    "live" if requirement_id.startswith("LIVE-") else "automated"
                ),
            }
            for requirement_id in requirement_ids()
        ],
        "static_cases": sorted(
            static_cases,
            key=lambda case: (
                case["requirement_id"],
                case["fixture_family"],
                case["subject_identity"],
            ),
        ),
        "plan_action_identities": ["action:sha256:" + "3" * 64],
        "verification_nodes": [
            {
                "node_identity": "verification:sha256:" + "4" * 64,
                "requirement_ids": ["MIG-01", "MIG-02", "MIG-05"],
                "evidence_kind": "automated_receipt",
            }
        ],
        "migration_nodes": [
            {
                "node_identity": "migration:sha256:" + "5" * 64,
                "requirement_ids": ["MIG-01", "MIG-02", "MIG-03", "MIG-04"],
                "evidence_kind": "mutation_receipt",
            },
            {
                "node_identity": "migration:sha256:" + "6" * 64,
                "requirement_ids": ["MIG-06", "MIG-07"],
                "evidence_kind": "mutation_receipt",
            },
        ],
        "route_capability_bindings": [
            {
                "route_identity": "route:fixture/claude-plugin",
                "route_digest": "sha256:" + "a" * 64,
                "harness": "claude",
                "provider_selector": {
                    "kind": "native_plugin",
                    "manager": "claude",
                    "plugin_id": "example@fixture",
                    "scope": "user",
                },
                "manager_identity": "manager:claude",
                "capability_identity": "capability:fixture/claude-plugin",
                "capability_digest": "sha256:" + "b" * 64,
                "manager_version_evidence_digest": "sha256:" + "c" * 64,
            }
        ],
        "expected_case_manifest_digest": "",
    }
    digest_payload = copy.deepcopy(document)
    del digest_payload["expected_case_manifest_digest"]
    document["expected_case_manifest_digest"] = canonical_digest(digest_payload)
    return document


def expected_cases(manifest: dict[str, object]) -> list[dict[str, str]]:
    cases = copy.deepcopy(manifest["static_cases"])
    assert isinstance(cases, list)
    plan_action_identities = manifest["plan_action_identities"]
    assert isinstance(plan_action_identities, list)
    for action_identity in plan_action_identities:
        assert isinstance(action_identity, str)
        for requirement_id in CHECKPOINT_MATRIX:
            cases.append(
                make_case(
                    requirement_id,
                    "checkpoint-action",
                    action_identity,
                    "checkpoint_trace",
                )
            )

    verification_nodes = manifest["verification_nodes"]
    assert isinstance(verification_nodes, list)
    for node in verification_nodes:
        assert isinstance(node, dict)
        for requirement_id in node["requirement_ids"]:
            cases.append(
                make_case(
                    requirement_id,
                    "verification-node",
                    node["node_identity"],
                    node["evidence_kind"],
                )
            )

    migration_nodes = manifest["migration_nodes"]
    assert isinstance(migration_nodes, list)
    for node in migration_nodes:
        assert isinstance(node, dict)
        for requirement_id in CHECKPOINT_MATRIX:
            cases.append(
                make_case(
                    requirement_id,
                    "migration-checkpoint",
                    node["node_identity"],
                    "checkpoint_trace",
                )
            )
        for requirement_id in node["requirement_ids"]:
            cases.append(
                make_case(
                    requirement_id,
                    "migration-boundary",
                    node["node_identity"],
                    node["evidence_kind"],
                )
            )

    return sorted(
        cases,
        key=lambda case: (
            case["requirement_id"],
            case["fixture_family"],
            case["subject_identity"],
        ),
    )


def evidence_for(kind: str) -> dict[str, object]:
    common = {
        "artifact_reference": "artifact:fixture/acceptance-result",
        "artifact_digest": "sha256:" + "7" * 64,
    }
    if kind == "automated_receipt":
        return {"kind": kind, **common}
    if kind == "mutation_receipt":
        return {
            "kind": kind,
            **common,
            "before_observation_digest": "sha256:" + "8" * 64,
            "after_observation_digest": "sha256:" + "9" * 64,
        }
    if kind == "checkpoint_trace":
        return {
            "kind": kind,
            **common,
            "before_observation_digest": "sha256:" + "8" * 64,
            "after_observation_digest": "sha256:" + "9" * 64,
            "checkpoint_trace_digest": "sha256:" + "0" * 64,
        }
    if kind == "live_receipt":
        return {
            "kind": kind,
            **common,
            "live_receipt_reference": "receipt:fixture/live-observation",
            "live_receipt_digest": "sha256:" + "8" * 64,
            "human_signoff": {
                "signer_identity": "operator:fixture/live-observer",
                "signed_at": "2026-08-13T05:00:00Z",
                "signoff_digest": "sha256:" + "9" * 64,
            },
        }
    raise AssertionError(f"unknown fixture evidence kind: {kind}")


def valid_evidence_bundle(
    manifest: dict[str, object] | None = None,
) -> dict[str, object]:
    manifest = manifest or valid_expected_case_manifest()
    cases = expected_cases(manifest)
    document: dict[str, object] = {
        "schema_version": "agent-equipment-acceptance-evidence/v1",
        "bindings": copy.deepcopy(manifest["bindings"]),
        "fixture_version": manifest["fixture_version"],
        "expected_case_manifest_digest": manifest["expected_case_manifest_digest"],
        "route_capability_bindings": copy.deepcopy(
            manifest["route_capability_bindings"]
        ),
        "harness_versions": [
            {"harness": "claude", "version": "fixture-1"},
            {"harness": "codex", "version": "fixture-1"},
            {"harness": "cursor", "version": "fixture-1"},
        ],
        "manager_versions": [
            {
                "manager_identity": manager_identity,
                "version": "fixture-1",
                "evidence_digest": evidence_digest,
            }
            for manager_identity, evidence_digest in sorted(
                {
                    (
                        binding["manager_identity"],
                        binding["manager_version_evidence_digest"],
                    )
                    for binding in manifest["route_capability_bindings"]
                }
            )
        ],
        "aggregate_results": [
            {
                "requirement_id": requirement_id,
                "status": "pass",
                "artifact_reference": f"artifact:fixture/{requirement_id.lower()}",
                "artifact_digest": "sha256:" + "7" * 64,
                "recorded_at": "2026-08-13T05:00:00Z",
            }
            for requirement_id in requirement_ids()
        ],
        "child_results": [
            {
                "case_identity": case["case_identity"],
                "requirement_id": case["requirement_id"],
                "fixture_family": case["fixture_family"],
                "subject_identity": case["subject_identity"],
                "status": "pass",
                "recorded_at": "2026-08-13T05:00:00Z",
                "evidence": evidence_for(case["evidence_kind"]),
            }
            for case in cases
        ],
        "bundle_digest": "",
    }
    digest_payload = copy.deepcopy(document)
    del digest_payload["bundle_digest"]
    document["bundle_digest"] = canonical_digest(digest_payload)
    return document


def valid_attestation_manifest(
    bundle: dict[str, object],
    manifest: dict[str, object],
) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "agent-equipment-acceptance-attestation/v1",
        "bindings": copy.deepcopy(manifest["bindings"]),
        "expected_case_manifest_digest": manifest["expected_case_manifest_digest"],
        "bundle_digest": bundle["bundle_digest"],
        "attestors": [
            {
                "role": "automated_runner",
                "identity": "service:fixture/acceptance-runner",
                "version": "fixture-1",
                "attested_at": "2026-08-13T05:01:00Z",
            },
            {
                "role": "live_operator",
                "identity": "operator:fixture/live-observer",
                "version": "fixture-1",
                "attested_at": "2026-08-13T05:02:00Z",
            },
            {
                "role": "release_reviewer",
                "identity": "person:fixture/release-reviewer",
                "version": "fixture-1",
                "attested_at": "2026-08-13T05:03:00Z",
            },
        ],
        "attestation_manifest_digest": "",
    }
    payload = copy.deepcopy(document)
    del payload["attestation_manifest_digest"]
    document["attestation_manifest_digest"] = canonical_digest(payload)
    return document


def reseal_bundle(document: dict[str, object]) -> None:
    payload = copy.deepcopy(document)
    del payload["bundle_digest"]
    document["bundle_digest"] = canonical_digest(payload)


def reseal_manifest(document: dict[str, object]) -> None:
    payload = copy.deepcopy(document)
    del payload["expected_case_manifest_digest"]
    document["expected_case_manifest_digest"] = canonical_digest(payload)


def reseal_attestation(document: dict[str, object]) -> None:
    payload = copy.deepcopy(document)
    del payload["attestation_manifest_digest"]
    document["attestation_manifest_digest"] = canonical_digest(payload)


def diagnostic_codes(
    bundle: object,
    manifest: object,
    attestation: object | None = None,
    *,
    expected_attestation_manifest_digest: str | None = None,
) -> set[str]:
    return {
        diagnostic.code
        for diagnostic in validation_diagnostics(
            bundle,
            manifest,
            attestation,
            expected_attestation_manifest_digest=(expected_attestation_manifest_digest),
        )
    }


def cli_args(
    manifest_path: Path,
    bundle_path: Path,
    attestation_path: Path,
    *,
    expected_case_manifest_digest: str,
    expected_attestation_manifest_digest: str,
) -> list[str]:
    return [
        sys.executable,
        "-B",
        str(SCRIPT),
        "--expected-case-manifest",
        str(manifest_path),
        "--expected-candidate-identity",
        CANDIDATE_IDENTITY,
        "--expected-implementation-manifest-digest",
        DIGESTS["implementation_manifest_digest"],
        "--expected-case-manifest-digest",
        expected_case_manifest_digest,
        "--attestation-manifest",
        str(attestation_path),
        "--expected-attestation-manifest-digest",
        expected_attestation_manifest_digest,
        str(bundle_path),
    ]


def validation_diagnostics(
    bundle: object,
    manifest: object,
    attestation: object | None = None,
    *,
    expected_case_manifest_digest: str | None = None,
    expected_attestation_manifest_digest: str | None = None,
) -> tuple[object, ...]:
    assert isinstance(manifest, dict)
    if attestation is None:
        assert isinstance(bundle, dict)
        attestation = valid_attestation_manifest(bundle, manifest)
    assert isinstance(attestation, dict)
    return ACCEPTANCE_EVIDENCE.validate_acceptance_evidence(
        bundle,
        manifest,
        attestation,
        expected_candidate_identity=CANDIDATE_IDENTITY,
        expected_implementation_manifest_digest=DIGESTS[
            "implementation_manifest_digest"
        ],
        expected_case_manifest_digest=(
            expected_case_manifest_digest or manifest["expected_case_manifest_digest"]
        ),
        expected_attestation_manifest_digest=(
            expected_attestation_manifest_digest
            or attestation["attestation_manifest_digest"]
        ),
    )


class AcceptanceEvidenceContractTests(unittest.TestCase):
    def test_release_accepts_only_an_independently_trusted_attestation(self) -> None:
        manifest = valid_expected_case_manifest()
        bundle = valid_evidence_bundle(manifest)
        attestation = valid_attestation_manifest(bundle, manifest)

        diagnostics = ACCEPTANCE_EVIDENCE.validate_acceptance_evidence(
            bundle,
            manifest,
            attestation,
            expected_candidate_identity=CANDIDATE_IDENTITY,
            expected_implementation_manifest_digest=DIGESTS[
                "implementation_manifest_digest"
            ],
            expected_case_manifest_digest=manifest["expected_case_manifest_digest"],
            expected_attestation_manifest_digest=attestation[
                "attestation_manifest_digest"
            ],
        )

        self.assertEqual(diagnostics, ())

    def test_trusted_attestation_freezes_every_candidate_bundle_value(self) -> None:
        manifest = valid_expected_case_manifest()
        original_bundle = valid_evidence_bundle(manifest)
        attestation = valid_attestation_manifest(original_bundle, manifest)
        trusted_attestation_digest = attestation["attestation_manifest_digest"]

        mutations = {
            "manager version": lambda bundle: bundle["manager_versions"][0].update(
                {"version": "forged-999"}
            ),
            "harness version": lambda bundle: bundle["harness_versions"][0].update(
                {"version": "forged-999"}
            ),
            "live signoff": lambda bundle: next(
                result
                for result in bundle["child_results"]
                if result["requirement_id"] == "LIVE-01"
            )["evidence"]["human_signoff"].update(
                {"signer_identity": "operator:fixture/forged-observer"}
            ),
            "aggregate artifact": lambda bundle: bundle["aggregate_results"][0].update(
                {"artifact_digest": "sha256:" + "8" * 64}
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                forged_bundle = copy.deepcopy(original_bundle)
                mutate(forged_bundle)
                reseal_bundle(forged_bundle)
                self.assertIn(
                    "ATTESTATION_BUNDLE_DIGEST_MISMATCH",
                    diagnostic_codes(
                        forged_bundle,
                        manifest,
                        attestation,
                        expected_attestation_manifest_digest=(
                            trusted_attestation_digest
                        ),
                    ),
                )

    def test_candidate_cannot_reseal_bundle_and_attestation_under_old_trust(
        self,
    ) -> None:
        manifest = valid_expected_case_manifest()
        original_bundle = valid_evidence_bundle(manifest)
        original_attestation = valid_attestation_manifest(original_bundle, manifest)

        rewritten_bundle = copy.deepcopy(original_bundle)
        rewritten_bundle["manager_versions"][0]["version"] = "forged-999"
        rewritten_bundle["harness_versions"][0]["version"] = "forged-999"
        live_result = next(
            result
            for result in rewritten_bundle["child_results"]
            if result["requirement_id"] == "LIVE-01"
        )
        live_result["evidence"]["human_signoff"]["signer_identity"] = (
            "operator:fixture/forged-observer"
        )
        reseal_bundle(rewritten_bundle)
        rewritten_attestation = valid_attestation_manifest(
            rewritten_bundle,
            manifest,
        )

        codes = diagnostic_codes(
            rewritten_bundle,
            manifest,
            rewritten_attestation,
            expected_attestation_manifest_digest=original_attestation[
                "attestation_manifest_digest"
            ],
        )
        self.assertIn("FOREIGN_ATTESTATION_MANIFEST", codes)
        self.assertNotIn("ATTESTATION_BUNDLE_DIGEST_MISMATCH", codes)

    def test_fully_resealed_artifact_tuple_requires_a_new_attestation_trust_root(
        self,
    ) -> None:
        original_manifest = valid_expected_case_manifest()
        original_bundle = valid_evidence_bundle(original_manifest)
        original_attestation = valid_attestation_manifest(
            original_bundle,
            original_manifest,
        )

        rewritten_manifest = copy.deepcopy(original_manifest)
        rewritten_manifest["bindings"].update(
            {
                "catalog_digest": "sha256:" + "3" * 64,
                "lock_digest": "sha256:" + "4" * 64,
                "plan_digest": "sha256:" + "5" * 64,
                "plan_action_set_digest": "sha256:" + "6" * 64,
                "capability_set_digest": "sha256:" + "7" * 64,
                "captured_state_digest": "sha256:" + "8" * 64,
            }
        )
        reseal_manifest(rewritten_manifest)
        rewritten_bundle = valid_evidence_bundle(rewritten_manifest)
        rewritten_attestation = valid_attestation_manifest(
            rewritten_bundle,
            rewritten_manifest,
        )

        codes = {
            diagnostic.code
            for diagnostic in validation_diagnostics(
                rewritten_bundle,
                rewritten_manifest,
                rewritten_attestation,
                expected_case_manifest_digest=rewritten_manifest[
                    "expected_case_manifest_digest"
                ],
                expected_attestation_manifest_digest=original_attestation[
                    "attestation_manifest_digest"
                ],
            )
        }
        self.assertIn("FOREIGN_ATTESTATION_MANIFEST", codes)

    def test_forged_attestor_fails_under_the_original_trusted_digest(self) -> None:
        manifest = valid_expected_case_manifest()
        bundle = valid_evidence_bundle(manifest)
        original_attestation = valid_attestation_manifest(bundle, manifest)
        forged_attestation = copy.deepcopy(original_attestation)
        forged_attestation["attestors"][2]["identity"] = (
            "person:fixture/forged-reviewer"
        )
        reseal_attestation(forged_attestation)

        self.assertIn(
            "FOREIGN_ATTESTATION_MANIFEST",
            diagnostic_codes(
                bundle,
                manifest,
                forged_attestation,
                expected_attestation_manifest_digest=original_attestation[
                    "attestation_manifest_digest"
                ],
            ),
        )

    def test_attestation_must_follow_results_and_bind_the_live_signer(self) -> None:
        manifest = valid_expected_case_manifest()
        bundle = valid_evidence_bundle(manifest)

        stale_attestation = valid_attestation_manifest(bundle, manifest)
        stale_attestation["attestors"][0]["attested_at"] = "2026-08-13T04:59:59Z"
        reseal_attestation(stale_attestation)
        self.assertIn(
            "ATTESTATION_PRECEDES_EVIDENCE",
            diagnostic_codes(bundle, manifest, stale_attestation),
        )

        mismatched_live_signer = valid_attestation_manifest(bundle, manifest)
        mismatched_live_signer["attestors"][1]["identity"] = (
            "operator:fixture/different-live-observer"
        )
        reseal_attestation(mismatched_live_signer)
        self.assertIn(
            "LIVE_SIGNER_ATTESTOR_MISMATCH",
            diagnostic_codes(bundle, manifest, mismatched_live_signer),
        )

        invalid_calendar_date = valid_attestation_manifest(bundle, manifest)
        invalid_calendar_date["attestors"][0]["attested_at"] = "2026-02-31T05:01:00Z"
        reseal_attestation(invalid_calendar_date)
        self.assertEqual(
            diagnostic_codes(bundle, manifest, invalid_calendar_date),
            {"ACCEPTANCE_ATTESTATION_SCHEMA_INVALID"},
        )

        timestamp_variants = {
            "year zero": "0000-01-01T00:00:00Z",
            "fraction": "2026-08-13t05:01:00.000Z",
            "comma fraction": "2026-08-13T05:01:00,000Z",
            "final LF": "2026-08-13T05:01:00Z\n",
        }
        for label, timestamp in timestamp_variants.items():
            with self.subTest(timestamp=label):
                variant = valid_attestation_manifest(bundle, manifest)
                variant["attestors"][0]["attested_at"] = timestamp
                reseal_attestation(variant)
                diagnostics = validation_diagnostics(bundle, manifest, variant)
                self.assertIsInstance(diagnostics, tuple)

    def test_attestor_and_signoff_identities_follow_their_human_roles(self) -> None:
        manifest = valid_expected_case_manifest()
        bundle = valid_evidence_bundle(manifest)
        attestation = valid_attestation_manifest(bundle, manifest)
        self.assertEqual(validation_diagnostics(bundle, manifest, attestation), ())

        service_live_bundle = valid_evidence_bundle(manifest)
        service_live_attestation = valid_attestation_manifest(
            service_live_bundle,
            manifest,
        )
        service_live_attestation["attestors"][1]["identity"] = (
            "service:fixture/live-observer"
        )
        reseal_attestation(service_live_attestation)
        self.assertEqual(
            diagnostic_codes(
                service_live_bundle,
                manifest,
                service_live_attestation,
            ),
            {"ACCEPTANCE_ATTESTATION_SCHEMA_INVALID"},
        )

        service_signoff = valid_evidence_bundle(manifest)
        live_result = next(
            result
            for result in service_signoff["child_results"]
            if result["requirement_id"] == "LIVE-01"
        )
        live_result["evidence"]["human_signoff"]["signer_identity"] = (
            "service:fixture/live-observer"
        )
        reseal_bundle(service_signoff)
        self.assertEqual(
            diagnostic_codes(service_signoff, manifest),
            {"ACCEPTANCE_EVIDENCE_SCHEMA_INVALID"},
        )

        service_reviewer = valid_attestation_manifest(bundle, manifest)
        service_reviewer["attestors"][2]["identity"] = (
            "service:fixture/release-reviewer"
        )
        reseal_attestation(service_reviewer)
        self.assertEqual(
            diagnostic_codes(bundle, manifest, service_reviewer),
            {"ACCEPTANCE_ATTESTATION_SCHEMA_INVALID"},
        )

    def test_timestamp_ordering_handles_arbitrary_fractional_precision(self) -> None:
        manifest = valid_expected_case_manifest()
        bundle = valid_evidence_bundle(manifest)
        prefix = "2026-08-13T05:00:00." + "0" * 5_000
        evidence_time = prefix + "2Z"
        earlier_attestation_time = prefix + "1Z"
        later_attestation_time = prefix + "3Z"
        for aggregate in bundle["aggregate_results"]:
            aggregate["recorded_at"] = evidence_time
        for result in bundle["child_results"]:
            result["recorded_at"] = evidence_time
            evidence = result["evidence"]
            if evidence["kind"] == "live_receipt":
                evidence["human_signoff"]["signed_at"] = evidence_time
        reseal_bundle(bundle)

        early = valid_attestation_manifest(bundle, manifest)
        for attestor in early["attestors"]:
            attestor["attested_at"] = earlier_attestation_time
        reseal_attestation(early)
        self.assertIn(
            "ATTESTATION_PRECEDES_EVIDENCE",
            diagnostic_codes(bundle, manifest, early),
        )

        late = valid_attestation_manifest(bundle, manifest)
        for attestor in late["attestors"]:
            attestor["attested_at"] = later_attestation_time
        reseal_attestation(late)
        self.assertEqual(validation_diagnostics(bundle, manifest, late), ())

    def test_public_validator_accepts_the_complete_closed_evidence_projection(
        self,
    ) -> None:
        manifest = valid_expected_case_manifest()
        bundle = valid_evidence_bundle(manifest)

        self.assertTrue(SCHEMA.is_file())
        self.assertEqual(len(requirement_ids()), 74)
        self.assertEqual(len(expected_cases(manifest)), 92)
        self.assertEqual(validation_diagnostics(bundle, manifest), ())

    def test_child_registry_rejects_missing_extra_and_duplicate_cases(self) -> None:
        manifest = valid_expected_case_manifest()

        missing = valid_evidence_bundle(manifest)
        missing["child_results"].pop()
        reseal_bundle(missing)
        self.assertIn("CHILD_RESULT_MISSING", diagnostic_codes(missing, manifest))

        extra = valid_evidence_bundle(manifest)
        extra_case = make_case(
            "CAT-01",
            "foreign-fixture",
            "fixture:foreign/case",
            "automated_receipt",
        )
        extra["child_results"].append(
            {
                **{
                    key: extra_case[key]
                    for key in (
                        "case_identity",
                        "requirement_id",
                        "fixture_family",
                        "subject_identity",
                    )
                },
                "status": "pass",
                "recorded_at": "2026-08-13T05:00:00Z",
                "evidence": evidence_for("automated_receipt"),
            }
        )
        extra["child_results"].sort(
            key=lambda result: (
                result["requirement_id"],
                result["fixture_family"],
                result["subject_identity"],
            )
        )
        reseal_bundle(extra)
        self.assertIn("CHILD_RESULT_EXTRA", diagnostic_codes(extra, manifest))

        duplicate = valid_evidence_bundle(manifest)
        cloned_result = copy.deepcopy(duplicate["child_results"][0])
        cloned_result["recorded_at"] = "2026-08-13T05:00:01Z"
        duplicate["child_results"].insert(1, cloned_result)
        reseal_bundle(duplicate)
        self.assertIn(
            "CHILD_RESULT_DUPLICATE",
            diagnostic_codes(duplicate, manifest),
        )

    def test_aggregate_pass_is_derived_from_complete_passing_children(self) -> None:
        manifest = valid_expected_case_manifest()

        failed_child = valid_evidence_bundle(manifest)
        failed_child["child_results"][0]["status"] = "fail"
        reseal_bundle(failed_child)
        codes = diagnostic_codes(failed_child, manifest)
        self.assertIn("CHILD_RESULT_NOT_PASSING", codes)
        self.assertIn("AGGREGATE_STATUS_INVALID", codes)

        false_failure = valid_evidence_bundle(manifest)
        false_failure["aggregate_results"][0]["status"] = "fail"
        reseal_bundle(false_failure)
        codes = diagnostic_codes(false_failure, manifest)
        self.assertIn("AGGREGATE_STATUS_INVALID", codes)
        self.assertIn("REQUIREMENT_NOT_PASSING", codes)

    def test_aggregate_timestamp_follows_every_child_for_the_requirement(self) -> None:
        manifest = valid_expected_case_manifest()
        bundle = valid_evidence_bundle(manifest)
        requirement_id = bundle["aggregate_results"][0]["requirement_id"]
        child = next(
            result
            for result in bundle["child_results"]
            if result["requirement_id"] == requirement_id
        )
        child["recorded_at"] = "2026-08-13T05:00:01Z"
        reseal_bundle(bundle)

        self.assertIn(
            "AGGREGATE_PRECEDES_CHILD_RESULT",
            diagnostic_codes(bundle, manifest),
        )

        bundle["aggregate_results"][0]["recorded_at"] = child["recorded_at"]
        reseal_bundle(bundle)
        self.assertEqual(validation_diagnostics(bundle, manifest), ())

    def test_aggregate_registry_rejects_missing_extra_and_duplicate_ids(self) -> None:
        manifest = valid_expected_case_manifest()

        missing = valid_evidence_bundle(manifest)
        missing["aggregate_results"].pop()
        reseal_bundle(missing)
        self.assertIn(
            "ACCEPTANCE_EVIDENCE_SCHEMA_INVALID",
            diagnostic_codes(missing, manifest),
        )

        extra = valid_evidence_bundle(manifest)
        extra["aggregate_results"].append(copy.deepcopy(extra["aggregate_results"][0]))
        reseal_bundle(extra)
        self.assertIn(
            "ACCEPTANCE_EVIDENCE_SCHEMA_INVALID",
            diagnostic_codes(extra, manifest),
        )

        duplicate = valid_evidence_bundle(manifest)
        duplicate["aggregate_results"][-1]["requirement_id"] = "LIVE-05"
        duplicate["aggregate_results"][-1]["recorded_at"] = "2026-08-13T05:00:01Z"
        reseal_bundle(duplicate)
        self.assertIn(
            "AGGREGATE_RESULT_SET_INVALID",
            diagnostic_codes(duplicate, manifest),
        )

    def test_bindings_reject_foreign_artifacts_and_route_capability_substitution(
        self,
    ) -> None:
        manifest = valid_expected_case_manifest()

        foreign_artifact = valid_evidence_bundle(manifest)
        foreign_artifact["bindings"]["catalog_digest"] = "sha256:" + "9" * 64
        reseal_bundle(foreign_artifact)
        self.assertIn(
            "EVIDENCE_BINDINGS_MISMATCH",
            diagnostic_codes(foreign_artifact, manifest),
        )

        substituted_capability = valid_evidence_bundle(manifest)
        substituted_capability["route_capability_bindings"][0]["capability_digest"] = (
            "sha256:" + "9" * 64
        )
        reseal_bundle(substituted_capability)
        self.assertIn(
            "ROUTE_CAPABILITY_BINDING_MISMATCH",
            diagnostic_codes(substituted_capability, manifest),
        )

        missing_manager_receipt = valid_evidence_bundle(manifest)
        missing_manager_receipt["manager_versions"][0]["evidence_digest"] = (
            "sha256:" + "9" * 64
        )
        reseal_bundle(missing_manager_receipt)
        self.assertIn(
            "MANAGER_EVIDENCE_COVERAGE_INCOMPLETE",
            diagnostic_codes(missing_manager_receipt, manifest),
        )

    def test_route_capability_bindings_close_each_provider_family_tuple(self) -> None:
        provider_families = {
            "standalone": {
                "harness": "cursor",
                "provider_selector": {
                    "kind": "standalone_skill",
                    "canonical_root": "agents_skills",
                },
                "manager_identity": "manager:standalone_skills",
            },
            "native": {
                "harness": "claude",
                "provider_selector": {
                    "kind": "native_plugin",
                    "manager": "claude",
                    "plugin_id": "example@fixture",
                    "scope": "user",
                },
                "manager_identity": "manager:claude",
            },
            "direct": {
                "harness": "codex",
                "provider_selector": {
                    "kind": "direct_mcp",
                    "transport": "stdio",
                    "overlay_family": "codex_toml",
                },
                "manager_identity": "manager:direct_mcp",
            },
        }
        for label, coordinates in provider_families.items():
            with self.subTest(provider_family=label):
                manifest = valid_expected_case_manifest()
                binding = manifest["route_capability_bindings"][0]
                binding.update(copy.deepcopy(coordinates))
                reseal_manifest(manifest)
                bundle = valid_evidence_bundle(manifest)
                self.assertEqual(validation_diagnostics(bundle, manifest), ())

        mismatches = {
            "native harness and manager": {
                "harness": "claude",
                "provider_selector": {
                    "kind": "native_plugin",
                    "manager": "codex",
                    "plugin_id": "example@fixture",
                    "scope": "user",
                },
                "manager_identity": "manager:codex",
            },
            "native manager identity": {
                "harness": "claude",
                "provider_selector": {
                    "kind": "native_plugin",
                    "manager": "claude",
                    "plugin_id": "example@fixture",
                    "scope": "user",
                },
                "manager_identity": "manager:cursor",
            },
            "direct overlay and harness": {
                "harness": "codex",
                "provider_selector": {
                    "kind": "direct_mcp",
                    "transport": "stdio",
                    "overlay_family": "cursor_json",
                },
                "manager_identity": "manager:direct_mcp",
            },
            "direct manager identity": {
                "harness": "codex",
                "provider_selector": {
                    "kind": "direct_mcp",
                    "transport": "stdio",
                    "overlay_family": "codex_toml",
                },
                "manager_identity": "manager:codex",
            },
            "standalone manager identity": {
                "harness": "cursor",
                "provider_selector": {
                    "kind": "standalone_skill",
                    "canonical_root": "agents_skills",
                },
                "manager_identity": "manager:claude",
            },
        }
        for label, coordinates in mismatches.items():
            with self.subTest(mismatch=label):
                manifest = valid_expected_case_manifest()
                binding = manifest["route_capability_bindings"][0]
                binding.update(copy.deepcopy(coordinates))
                reseal_manifest(manifest)
                bundle = valid_evidence_bundle(manifest)
                self.assertIn(
                    "ROUTE_CAPABILITY_BINDING_COHERENCE_INVALID",
                    diagnostic_codes(bundle, manifest),
                )

        unknown_manager = valid_expected_case_manifest()
        unknown_manager["route_capability_bindings"][0]["manager_identity"] = (
            "manager:fixture/claude"
        )
        reseal_manifest(unknown_manager)
        unknown_manager_bundle = valid_evidence_bundle(unknown_manager)
        self.assertEqual(
            diagnostic_codes(unknown_manager_bundle, unknown_manager),
            {"EXPECTED_CASE_MANIFEST_SCHEMA_INVALID"},
        )

    def test_trusted_manifest_digest_rejects_a_coordinated_foreign_tuple(self) -> None:
        authorized_manifest = valid_expected_case_manifest()
        foreign_manifest = copy.deepcopy(authorized_manifest)
        foreign_manifest["bindings"]["catalog_digest"] = "sha256:" + "9" * 64
        foreign_manifest["bindings"]["lock_digest"] = "sha256:" + "8" * 64
        foreign_manifest["bindings"]["plan_digest"] = "sha256:" + "7" * 64
        foreign_manifest["bindings"]["plan_action_set_digest"] = "sha256:" + "6" * 64
        reseal_manifest(foreign_manifest)
        foreign_bundle = valid_evidence_bundle(foreign_manifest)

        codes = {
            diagnostic.code
            for diagnostic in validation_diagnostics(
                foreign_bundle,
                foreign_manifest,
                expected_case_manifest_digest=authorized_manifest[
                    "expected_case_manifest_digest"
                ],
            )
        }
        self.assertIn("FOREIGN_EXPECTED_CASE_MANIFEST", codes)

    def test_live_cases_require_live_receipts_and_human_signoff(self) -> None:
        manifest = valid_expected_case_manifest()
        bundle = valid_evidence_bundle(manifest)
        live_index = next(
            index
            for index, result in enumerate(bundle["child_results"])
            if result["requirement_id"] == "LIVE-01"
        )
        bundle["child_results"][live_index]["evidence"] = evidence_for(
            "automated_receipt"
        )
        reseal_bundle(bundle)

        self.assertIn(
            "CHILD_EVIDENCE_KIND_MISMATCH",
            diagnostic_codes(bundle, manifest),
        )

        missing_signoff = valid_evidence_bundle(manifest)
        del missing_signoff["child_results"][live_index]["evidence"]["human_signoff"]
        reseal_bundle(missing_signoff)
        self.assertIn(
            "ACCEPTANCE_EVIDENCE_SCHEMA_INVALID",
            diagnostic_codes(missing_signoff, manifest),
        )

    def test_cli_accepts_valid_inputs_and_rejects_noncanonical_json(self) -> None:
        manifest = valid_expected_case_manifest()
        bundle = valid_evidence_bundle(manifest)
        attestation = valid_attestation_manifest(bundle, manifest)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "expected.json"
            bundle_path = root / "bundle.json"
            attestation_path = root / "attestation.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
            command = cli_args(
                manifest_path,
                bundle_path,
                attestation_path,
                expected_case_manifest_digest=manifest["expected_case_manifest_digest"],
                expected_attestation_manifest_digest=attestation[
                    "attestation_manifest_digest"
                ],
            )

            valid = subprocess.run(
                command,
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(valid.returncode, 0, valid.stderr)

            duplicate_manifest = json.dumps(manifest).replace(
                '"schema_version":',
                '"schema_version":"foreign","schema_version":',
                1,
            )
            manifest_path.write_text(duplicate_manifest, encoding="utf-8")
            rejected_manifest = subprocess.run(
                command,
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(rejected_manifest.returncode, 0)
            self.assertIn(
                "EXPECTED_CASE_MANIFEST_READ_FAILED",
                rejected_manifest.stderr,
            )

            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            nonfinite_bundle = json.dumps(bundle).replace(
                '"bundle_digest":',
                '"nonfinite":1e10000,"bundle_digest":',
                1,
            )
            bundle_path.write_text(nonfinite_bundle, encoding="utf-8")
            rejected_bundle = subprocess.run(
                command,
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(rejected_bundle.returncode, 0)
            self.assertIn(
                "ACCEPTANCE_EVIDENCE_READ_FAILED",
                rejected_bundle.stderr,
            )

            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            duplicate_attestation = json.dumps(attestation).replace(
                '"schema_version":',
                '"schema_version":"foreign","schema_version":',
                1,
            )
            attestation_path.write_text(
                duplicate_attestation,
                encoding="utf-8",
            )
            rejected_attestation = subprocess.run(
                command,
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(rejected_attestation.returncode, 0)
            self.assertIn(
                "ACCEPTANCE_ATTESTATION_READ_FAILED",
                rejected_attestation.stderr,
            )

    def test_api_and_cli_diagnostics_never_echo_seeded_secret_values(self) -> None:
        secret_canary = "api_token=super-secret-canary"
        manifest = valid_expected_case_manifest()
        bundle = valid_evidence_bundle(manifest)
        bundle["fixture_version"] = secret_canary
        reseal_bundle(bundle)
        attestation = valid_attestation_manifest(bundle, manifest)

        rendered = "\n".join(
            f"{diagnostic.path}: {diagnostic.code}: {diagnostic.message}"
            for diagnostic in validation_diagnostics(bundle, manifest)
        )
        self.assertNotIn(secret_canary, rendered)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "expected.json"
            bundle_path = root / "bundle.json"
            attestation_path = root / "attestation.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
            result = subprocess.run(
                cli_args(
                    manifest_path,
                    bundle_path,
                    attestation_path,
                    expected_case_manifest_digest=manifest[
                        "expected_case_manifest_digest"
                    ],
                    expected_attestation_manifest_digest=attestation[
                        "attestation_manifest_digest"
                    ],
                ),
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(secret_canary, result.stderr)

    def test_all_archived_release_documents_reject_literal_credentials(self) -> None:
        credential_values = {
            "manifest provider": "ghp_" + "A" * 24,
            "harness version": "Bearer abcdefghijklmnopqrstuvwxyz",
            "manager version": "ghp_" + "B" * 24,
            "attestor version": "AKIA" + "C" * 16,
        }
        cases: list[
            tuple[
                str,
                str,
                dict[str, object],
                dict[str, object],
                dict[str, object],
            ]
        ] = []

        manifest = valid_expected_case_manifest()
        manifest["route_capability_bindings"][0]["provider_selector"]["plugin_id"] = (
            credential_values["manifest provider"]
        )
        reseal_manifest(manifest)
        bundle = valid_evidence_bundle(manifest)
        cases.append(
            (
                "manifest provider",
                "EXPECTED_CASE_MANIFEST_LITERAL_SECRET",
                manifest,
                bundle,
                valid_attestation_manifest(bundle, manifest),
            )
        )

        for label, version_collection in (
            ("harness version", "harness_versions"),
            ("manager version", "manager_versions"),
        ):
            manifest = valid_expected_case_manifest()
            bundle = valid_evidence_bundle(manifest)
            bundle[version_collection][0]["version"] = credential_values[label]
            reseal_bundle(bundle)
            cases.append(
                (
                    label,
                    "ACCEPTANCE_EVIDENCE_LITERAL_SECRET",
                    manifest,
                    bundle,
                    valid_attestation_manifest(bundle, manifest),
                )
            )

        manifest = valid_expected_case_manifest()
        bundle = valid_evidence_bundle(manifest)
        attestation = valid_attestation_manifest(bundle, manifest)
        attestation["attestors"][0]["version"] = credential_values["attestor version"]
        reseal_attestation(attestation)
        cases.append(
            (
                "attestor version",
                "ACCEPTANCE_ATTESTATION_LITERAL_SECRET",
                manifest,
                bundle,
                attestation,
            )
        )

        for label, expected_code, manifest, bundle, attestation in cases:
            with self.subTest(api=label):
                diagnostics = validation_diagnostics(bundle, manifest, attestation)
                self.assertEqual(
                    {diagnostic.code for diagnostic in diagnostics},
                    {expected_code},
                )
                rendered = "\n".join(
                    f"{diagnostic.path}: {diagnostic.code}: {diagnostic.message}"
                    for diagnostic in diagnostics
                )
                self.assertNotIn(credential_values[label], rendered)

            with self.subTest(cli=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest_path = root / "expected.json"
                bundle_path = root / "bundle.json"
                attestation_path = root / "attestation.json"
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
                attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
                result = subprocess.run(
                    cli_args(
                        manifest_path,
                        bundle_path,
                        attestation_path,
                        expected_case_manifest_digest=manifest[
                            "expected_case_manifest_digest"
                        ],
                        expected_attestation_manifest_digest=attestation[
                            "attestation_manifest_digest"
                        ],
                    ),
                    cwd=ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn(expected_code, result.stderr)
                self.assertNotIn(credential_values[label], result.stderr)

    def test_public_validator_rejects_documents_supplied_in_the_wrong_roles(
        self,
    ) -> None:
        manifest = valid_expected_case_manifest()
        bundle = valid_evidence_bundle(manifest)
        attestation = valid_attestation_manifest(bundle, manifest)
        trusted_digest = manifest["expected_case_manifest_digest"]
        trusted_attestation_digest = attestation["attestation_manifest_digest"]

        swapped = ACCEPTANCE_EVIDENCE.validate_acceptance_evidence(
            manifest,
            bundle,
            attestation,
            expected_candidate_identity=CANDIDATE_IDENTITY,
            expected_implementation_manifest_digest=DIGESTS[
                "implementation_manifest_digest"
            ],
            expected_case_manifest_digest=trusted_digest,
            expected_attestation_manifest_digest=trusted_attestation_digest,
        )
        self.assertEqual(
            [diagnostic.code for diagnostic in swapped],
            ["EXPECTED_CASE_MANIFEST_SCHEMA_INVALID"],
        )

        manifest_in_bundle_position = ACCEPTANCE_EVIDENCE.validate_acceptance_evidence(
            manifest,
            manifest,
            attestation,
            expected_candidate_identity=CANDIDATE_IDENTITY,
            expected_implementation_manifest_digest=DIGESTS[
                "implementation_manifest_digest"
            ],
            expected_case_manifest_digest=trusted_digest,
            expected_attestation_manifest_digest=trusted_attestation_digest,
        )
        self.assertEqual(
            [diagnostic.code for diagnostic in manifest_in_bundle_position],
            ["ACCEPTANCE_EVIDENCE_SCHEMA_INVALID"],
        )

        bundle_in_attestation_position = (
            ACCEPTANCE_EVIDENCE.validate_acceptance_evidence(
                bundle,
                manifest,
                bundle,
                expected_candidate_identity=CANDIDATE_IDENTITY,
                expected_implementation_manifest_digest=DIGESTS[
                    "implementation_manifest_digest"
                ],
                expected_case_manifest_digest=trusted_digest,
                expected_attestation_manifest_digest=(trusted_attestation_digest),
            )
        )
        self.assertEqual(
            [diagnostic.code for diagnostic in bundle_in_attestation_position],
            ["ACCEPTANCE_ATTESTATION_SCHEMA_INVALID"],
        )

    def test_cli_rejects_documents_supplied_in_the_wrong_roles(self) -> None:
        manifest = valid_expected_case_manifest()
        bundle = valid_evidence_bundle(manifest)
        attestation = valid_attestation_manifest(bundle, manifest)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "expected.json"
            bundle_path = root / "bundle.json"
            attestation_path = root / "attestation.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
            trusted_digest = manifest["expected_case_manifest_digest"]
            trusted_attestation_digest = attestation["attestation_manifest_digest"]

            swapped = subprocess.run(
                cli_args(
                    bundle_path,
                    manifest_path,
                    attestation_path,
                    expected_case_manifest_digest=trusted_digest,
                    expected_attestation_manifest_digest=(trusted_attestation_digest),
                ),
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(swapped.returncode, 1)
            self.assertIn(
                "EXPECTED_CASE_MANIFEST_SCHEMA_INVALID",
                swapped.stderr,
            )
            self.assertNotIn("Traceback", swapped.stderr)

            manifest_in_bundle_position = subprocess.run(
                cli_args(
                    manifest_path,
                    manifest_path,
                    attestation_path,
                    expected_case_manifest_digest=trusted_digest,
                    expected_attestation_manifest_digest=(trusted_attestation_digest),
                ),
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(manifest_in_bundle_position.returncode, 1)
            self.assertIn(
                "ACCEPTANCE_EVIDENCE_SCHEMA_INVALID",
                manifest_in_bundle_position.stderr,
            )
            self.assertNotIn("Traceback", manifest_in_bundle_position.stderr)

            bundle_in_attestation_position = subprocess.run(
                cli_args(
                    manifest_path,
                    bundle_path,
                    bundle_path,
                    expected_case_manifest_digest=trusted_digest,
                    expected_attestation_manifest_digest=(trusted_attestation_digest),
                ),
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(bundle_in_attestation_position.returncode, 1)
            self.assertIn(
                "ACCEPTANCE_ATTESTATION_SCHEMA_INVALID",
                bundle_in_attestation_position.stderr,
            )
            self.assertNotIn("Traceback", bundle_in_attestation_position.stderr)

    def test_node_evidence_kinds_distinguish_read_only_and_mutating_boundaries(
        self,
    ) -> None:
        verification_with_mutation_receipt = valid_expected_case_manifest()
        verification_with_mutation_receipt["verification_nodes"][0]["evidence_kind"] = (
            "mutation_receipt"
        )
        reseal_manifest(verification_with_mutation_receipt)
        verification_bundle = valid_evidence_bundle(verification_with_mutation_receipt)
        self.assertEqual(
            diagnostic_codes(
                verification_bundle,
                verification_with_mutation_receipt,
            ),
            {"EXPECTED_CASE_MANIFEST_SCHEMA_INVALID"},
        )

        migration_with_automated_receipt = valid_expected_case_manifest()
        migration_with_automated_receipt["migration_nodes"][0]["evidence_kind"] = (
            "automated_receipt"
        )
        reseal_manifest(migration_with_automated_receipt)
        migration_bundle = valid_evidence_bundle(migration_with_automated_receipt)
        self.assertEqual(
            diagnostic_codes(
                migration_bundle,
                migration_with_automated_receipt,
            ),
            {"EXPECTED_CASE_MANIFEST_SCHEMA_INVALID"},
        )

    def test_migration_requirements_cannot_move_between_node_classes(self) -> None:
        manifest = valid_expected_case_manifest()
        substituted = copy.deepcopy(manifest)
        substituted["verification_nodes"][0]["requirement_ids"] = [
            "MIG-01",
            "MIG-03",
            "MIG-05",
        ]
        substituted["migration_nodes"][0]["requirement_ids"] = [
            "MIG-02",
            "MIG-04",
        ]
        reseal_manifest(substituted)
        bundle = valid_evidence_bundle(substituted)

        self.assertIn(
            "MIGRATION_NODE_CLASS_COVERAGE_INVALID",
            diagnostic_codes(bundle, substituted),
        )

        omitted_mutations = valid_expected_case_manifest()
        omitted_mutations["migration_nodes"][0]["requirement_ids"] = [
            "MIG-03",
            "MIG-04",
        ]
        reseal_manifest(omitted_mutations)
        omitted_bundle = valid_evidence_bundle(omitted_mutations)
        self.assertIn(
            "MIGRATION_NODE_CLASS_COVERAGE_INVALID",
            diagnostic_codes(omitted_bundle, omitted_mutations),
        )

    def test_evidence_references_reject_urls_and_filesystem_paths(self) -> None:
        manifest = valid_expected_case_manifest()
        hostile_references = (
            "artifact:https://example.invalid/receipt",
            "artifact:file:///private/fixture/receipt.json",
            "receipt:https://example.invalid/live",
            "operator:file:///private/fixture/signoff.json",
        )
        for reference in hostile_references:
            with self.subTest(reference=reference):
                bundle = valid_evidence_bundle(manifest)
                if reference.startswith(("receipt:", "operator:")):
                    live_result = next(
                        result
                        for result in bundle["child_results"]
                        if result["requirement_id"] == "LIVE-01"
                    )
                    if reference.startswith("operator:"):
                        live_result["evidence"]["human_signoff"]["signer_identity"] = (
                            reference
                        )
                    else:
                        live_result["evidence"]["live_receipt_reference"] = reference
                else:
                    bundle["child_results"][0]["evidence"]["artifact_reference"] = (
                        reference
                    )
                reseal_bundle(bundle)
                self.assertEqual(
                    diagnostic_codes(bundle, manifest),
                    {"ACCEPTANCE_EVIDENCE_SCHEMA_INVALID"},
                )


if __name__ == "__main__":
    unittest.main()
