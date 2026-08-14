"""Shared deterministic fixtures for agent-equipment acceptance evidence tests."""

from __future__ import annotations

import copy
import hashlib
import json

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
EXECUTION_BINDING = {
    "apply_authorization_identity": "apply-authorization:sha256:" + "4" * 64,
    "apply_authorization_digest": "sha256:" + "5" * 64,
    "execution_domain_identity": "execution-domain:fixture/global-ledger-v1",
    "execution_nonce": "execution-nonce:sha256:" + "6" * 64,
    "run_identity": "run:sha256:" + "7" * 64,
}


def trusted_execution_inputs() -> dict[str, str]:
    return {
        "expected_apply_authorization_identity": EXECUTION_BINDING[
            "apply_authorization_identity"
        ],
        "expected_apply_authorization_digest": EXECUTION_BINDING[
            "apply_authorization_digest"
        ],
        "expected_execution_domain_identity": EXECUTION_BINDING[
            "execution_domain_identity"
        ],
        "expected_execution_nonce": EXECUTION_BINDING["execution_nonce"],
        "expected_run_identity": EXECUTION_BINDING["run_identity"],
    }


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
        ("CHK", 11),
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
        elif requirement_id in {"CHK-01", "CHK-10", "CHK-11"}:
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
        "execution_binding": copy.deepcopy(EXECUTION_BINDING),
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
        "execution_binding": copy.deepcopy(bundle["execution_binding"]),
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
