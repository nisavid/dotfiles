#!/usr/bin/env python3
"""Validate one closed agent-equipment acceptance evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

try:
    from agent_equipment_json_schema import validate_document as _validate_schema
except ModuleNotFoundError:  # Loaded as a repo module rather than an executable.
    from scripts.agent_equipment_json_schema import (
        validate_document as _validate_schema,
    )
try:
    from agent_equipment_public_data import (
        contains_literal_credential as _contains_literal_credential,
    )
except ModuleNotFoundError:  # Loaded as a repo module rather than an executable.
    from scripts.agent_equipment_public_data import (
        contains_literal_credential as _contains_literal_credential,
    )


JsonObject = Mapping[str, object]
SCHEMA_DIRECTORY = Path(__file__).resolve().parent.parent / "docs/agent-equipment"
SCHEMA_NAME = "acceptance-evidence-v1.schema.json"

REQUIRED_REQUIREMENTS = tuple(
    f"{prefix}-{number:02d}"
    for prefix, count in (
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
    for number in range(1, count + 1)
)
CHECKPOINT_MATRIX_REQUIREMENTS = tuple(f"CHK-{number:02d}" for number in range(2, 10))
MIGRATION_REQUIREMENTS = tuple(f"MIG-{number:02d}" for number in range(1, 8))
VERIFICATION_MIGRATION_REQUIREMENTS = frozenset({"MIG-01", "MIG-02", "MIG-05"})
MUTATING_MIGRATION_REQUIREMENTS = frozenset(
    {"MIG-01", "MIG-02", "MIG-03", "MIG-04", "MIG-06", "MIG-07"}
)
ATTESTOR_ROLES = ("automated_runner", "live_operator", "release_reviewer")
_DIRECT_MCP_OVERLAY_BY_HARNESS = {
    "claude": "claude_json",
    "codex": "codex_toml",
    "cursor": "cursor_json",
}
_MANAGER_IDENTITY_BY_MANAGER = {
    "claude": "manager:claude",
    "codex": "manager:codex",
    "cursor": "manager:cursor",
    "direct_mcp": "manager:direct_mcp",
    "standalone_skills": "manager:standalone_skills",
}
_UTC_TIMESTAMP_PATTERN = re.compile(
    r"^(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"[Tt](?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
    r"(?P<fraction>[.,][0-9]+)?Z(?:\n)?\Z"
)
_DERIVED_REQUIREMENTS = frozenset(
    CHECKPOINT_MATRIX_REQUIREMENTS + MIGRATION_REQUIREMENTS
)


@dataclass(frozen=True, order=True)
class Diagnostic:
    """One deterministic, secret-free release-gate failure."""

    path: str
    code: str
    message: str


@dataclass(frozen=True, order=True)
class _ExpectedCase:
    requirement_id: str
    fixture_family: str
    subject_identity: str
    case_identity: str
    evidence_kind: str


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(_canonical_bytes(value)).hexdigest()}"


def acceptance_case_identity(
    requirement_id: str,
    fixture_family: str,
    subject_identity: str,
) -> str:
    """Derive the stable identity of one expected acceptance child case."""

    return "case:" + _digest(
        {
            "fixture_family": fixture_family,
            "requirement_id": requirement_id,
            "subject_identity": subject_identity,
        }
    )


def _artifact_digest(document: JsonObject, digest_member: str) -> str:
    return _digest(
        {key: value for key, value in document.items() if key != digest_member}
    )


def _utc_timestamp_key(value: object) -> tuple[int | str, ...] | None:
    """Return a total ordering key for the local schema's UTC timestamps."""

    if not isinstance(value, str):
        return None
    match = _UTC_TIMESTAMP_PATTERN.fullmatch(value)
    if match is None:
        return None
    fraction = match.group("fraction")
    if fraction is None:
        fractional_second = ""
    else:
        fractional_second = fraction[1:].rstrip("0")
    return (
        int(match.group("year")),
        int(match.group("month")),
        int(match.group("day")),
        int(match.group("hour")),
        int(match.group("minute")),
        int(match.group("second")),
        fractional_second,
    )


def _diagnostic(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(path=path, code=code, message=message)


def _literal_credential_diagnostic(code: str, label: str) -> Diagnostic:
    return _diagnostic(
        code,
        "$",
        f"The {label} contains credential-shaped literal material; archive only public values and opaque secret references.",
    )


def _schema_valid(document: object) -> bool:
    return _validate_schema(
        document,
        schema_directory=SCHEMA_DIRECTORY,
        root_schema_name=SCHEMA_NAME,
        allowed_schema_names=frozenset({SCHEMA_NAME}),
    )


def _has_schema_version(document: object, version: str) -> bool:
    return isinstance(document, Mapping) and document.get("schema_version") == version


def _case_from_record(record: JsonObject) -> _ExpectedCase:
    return _ExpectedCase(
        requirement_id=str(record["requirement_id"]),
        fixture_family=str(record["fixture_family"]),
        subject_identity=str(record["subject_identity"]),
        case_identity=str(record["case_identity"]),
        evidence_kind=str(record["evidence_kind"]),
    )


def _route_capability_binding_is_coherent(binding: JsonObject) -> bool:
    provider = binding["provider_selector"]
    assert isinstance(provider, Mapping)
    harness = binding["harness"]
    manager_identity = binding["manager_identity"]
    kind = provider["kind"]
    if kind == "standalone_skill":
        return manager_identity == _MANAGER_IDENTITY_BY_MANAGER["standalone_skills"]
    if kind == "native_plugin":
        manager = provider["manager"]
        return (
            manager == harness
            and manager_identity == _MANAGER_IDENTITY_BY_MANAGER[manager]
        )
    if kind == "direct_mcp":
        return (
            provider["overlay_family"] == _DIRECT_MCP_OVERLAY_BY_HARNESS[harness]
            and manager_identity == _MANAGER_IDENTITY_BY_MANAGER["direct_mcp"]
        )
    return False


def _derived_case(
    requirement_id: str,
    fixture_family: str,
    subject_identity: str,
    evidence_kind: str,
) -> _ExpectedCase:
    return _ExpectedCase(
        requirement_id=requirement_id,
        fixture_family=fixture_family,
        subject_identity=subject_identity,
        case_identity=acceptance_case_identity(
            requirement_id,
            fixture_family,
            subject_identity,
        ),
        evidence_kind=evidence_kind,
    )


def _expected_registry(
    manifest: JsonObject,
) -> tuple[tuple[_ExpectedCase, ...], tuple[Diagnostic, ...]]:
    diagnostics: list[Diagnostic] = []
    static_cases = manifest["static_cases"]
    plan_actions = manifest["plan_action_identities"]
    verification_nodes = manifest["verification_nodes"]
    migration_nodes = manifest["migration_nodes"]
    assert isinstance(static_cases, list)
    assert isinstance(plan_actions, list)
    assert isinstance(verification_nodes, list)
    assert isinstance(migration_nodes, list)

    cases: list[_ExpectedCase] = []
    for index, raw_case in enumerate(static_cases):
        assert isinstance(raw_case, Mapping)
        case = _case_from_record(raw_case)
        if case.requirement_id in _DERIVED_REQUIREMENTS:
            diagnostics.append(
                _diagnostic(
                    "DERIVED_CASE_DECLARED_STATIC",
                    f"$.static_cases[{index}].requirement_id",
                    "Repeated checkpoint and migration cases must come from sealed plan or node identities.",
                )
            )
        if case.case_identity != acceptance_case_identity(
            case.requirement_id,
            case.fixture_family,
            case.subject_identity,
        ):
            diagnostics.append(
                _diagnostic(
                    "CASE_IDENTITY_INVALID",
                    f"$.static_cases[{index}].case_identity",
                    "The case identity does not match its stable composite coordinates.",
                )
            )
        if case.requirement_id.startswith("LIVE-"):
            expected_kind = "live_receipt"
            if case.evidence_kind != expected_kind:
                diagnostics.append(
                    _diagnostic(
                        "LIVE_CASE_KIND_INVALID",
                        f"$.static_cases[{index}].evidence_kind",
                        "A live requirement must require a live receipt and human sign-off.",
                    )
                )
        elif case.evidence_kind == "live_receipt":
            diagnostics.append(
                _diagnostic(
                    "AUTOMATED_CASE_KIND_INVALID",
                    f"$.static_cases[{index}].evidence_kind",
                    "A non-live requirement cannot be satisfied by the live-only receipt shape.",
                )
            )
        cases.append(case)

    static_order = sorted(
        cases,
        key=lambda case: (
            case.requirement_id,
            case.fixture_family,
            case.subject_identity,
        ),
    )
    if cases != static_order:
        diagnostics.append(
            _diagnostic(
                "STATIC_CASE_ORDER_INVALID",
                "$.static_cases",
                "Static cases must use canonical requirement, fixture-family, and subject order.",
            )
        )

    if plan_actions != sorted(plan_actions) or len(plan_actions) != len(
        set(plan_actions)
    ):
        diagnostics.append(
            _diagnostic(
                "PLAN_ACTION_IDENTITY_SET_INVALID",
                "$.plan_action_identities",
                "Plan action identities must be unique and canonically sorted.",
            )
        )
    for action_identity in plan_actions:
        assert isinstance(action_identity, str)
        for requirement_id in CHECKPOINT_MATRIX_REQUIREMENTS:
            cases.append(
                _derived_case(
                    requirement_id,
                    "checkpoint-action",
                    action_identity,
                    "checkpoint_trace",
                )
            )

    for node_kind, raw_nodes, family in (
        ("verification", verification_nodes, "verification-node"),
        ("migration", migration_nodes, "migration-boundary"),
    ):
        node_identities = [str(node["node_identity"]) for node in raw_nodes]
        if node_identities != sorted(node_identities) or len(node_identities) != len(
            set(node_identities)
        ):
            diagnostics.append(
                _diagnostic(
                    "NODE_IDENTITY_SET_INVALID",
                    f"$.{node_kind}_nodes",
                    "Node identities must be unique and canonically sorted.",
                )
            )
        for index, node in enumerate(raw_nodes):
            assert isinstance(node, Mapping)
            node_identity = str(node["node_identity"])
            node_requirements = node["requirement_ids"]
            assert isinstance(node_requirements, list)
            if node_requirements != sorted(node_requirements) or any(
                requirement_id not in MIGRATION_REQUIREMENTS
                for requirement_id in node_requirements
            ):
                diagnostics.append(
                    _diagnostic(
                        "NODE_REQUIREMENT_SET_INVALID",
                        f"$.{node_kind}_nodes[{index}].requirement_ids",
                        "A node must name a canonical non-empty subset of migration requirements.",
                    )
                )
            if node_kind == "migration":
                for requirement_id in CHECKPOINT_MATRIX_REQUIREMENTS:
                    cases.append(
                        _derived_case(
                            requirement_id,
                            "migration-checkpoint",
                            node_identity,
                            "checkpoint_trace",
                        )
                    )
            for requirement_id in node_requirements:
                cases.append(
                    _derived_case(
                        str(requirement_id),
                        family,
                        node_identity,
                        str(node["evidence_kind"]),
                    )
                )

    verification_coverage = {
        str(requirement_id)
        for node in verification_nodes
        for requirement_id in node["requirement_ids"]
    }
    migration_coverage = {
        str(requirement_id)
        for node in migration_nodes
        for requirement_id in node["requirement_ids"]
    }
    if (
        not VERIFICATION_MIGRATION_REQUIREMENTS <= verification_coverage
        or not MUTATING_MIGRATION_REQUIREMENTS <= migration_coverage
    ):
        diagnostics.append(
            _diagnostic(
                "MIGRATION_NODE_CLASS_COVERAGE_INVALID",
                "$",
                "Every migration requirement must appear in its required node class.",
            )
        )

    case_keys = [
        (case.requirement_id, case.fixture_family, case.subject_identity)
        for case in cases
    ]
    case_identities = [case.case_identity for case in cases]
    if len(case_keys) != len(set(case_keys)) or len(case_identities) != len(
        set(case_identities)
    ):
        diagnostics.append(
            _diagnostic(
                "EXPECTED_CASE_DUPLICATE",
                "$",
                "The expected-case registry contains a duplicate composite or identity.",
            )
        )

    covered = {case.requirement_id for case in cases}
    if covered != set(REQUIRED_REQUIREMENTS):
        diagnostics.append(
            _diagnostic(
                "EXPECTED_CASE_COVERAGE_INCOMPLETE",
                "$",
                "Every required aggregate must have at least one independently declared child case.",
            )
        )

    return tuple(sorted(cases)), tuple(sorted(diagnostics))


def _validate_expected_manifest(
    manifest: JsonObject,
    *,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_case_manifest_digest: str,
) -> tuple[tuple[_ExpectedCase, ...], tuple[Diagnostic, ...]]:
    diagnostics: list[Diagnostic] = []
    expected_requirements = [
        {
            "requirement_id": requirement_id,
            "evidence_mode": (
                "live" if requirement_id.startswith("LIVE-") else "automated"
            ),
        }
        for requirement_id in REQUIRED_REQUIREMENTS
    ]
    if manifest["requirements"] != expected_requirements:
        diagnostics.append(
            _diagnostic(
                "REQUIREMENT_REGISTRY_INVALID",
                "$.requirements",
                "The manifest must contain the complete canonical v1 requirement registry.",
            )
        )

    recomputed_manifest_digest = _artifact_digest(
        manifest,
        "expected_case_manifest_digest",
    )
    if manifest["expected_case_manifest_digest"] != recomputed_manifest_digest:
        diagnostics.append(
            _diagnostic(
                "EXPECTED_CASE_MANIFEST_DIGEST_INVALID",
                "$.expected_case_manifest_digest",
                "The expected-case manifest digest does not match its closed payload.",
            )
        )
    if recomputed_manifest_digest != expected_case_manifest_digest:
        diagnostics.append(
            _diagnostic(
                "FOREIGN_EXPECTED_CASE_MANIFEST",
                "$.expected_case_manifest_digest",
                "The expected-case manifest does not match the independently trusted sealed manifest digest.",
            )
        )

    bindings = manifest["bindings"]
    assert isinstance(bindings, Mapping)
    if bindings["candidate_identity"] != expected_candidate_identity:
        diagnostics.append(
            _diagnostic(
                "FOREIGN_CANDIDATE_IDENTITY",
                "$.bindings.candidate_identity",
                "The expected-case manifest does not name the independently trusted candidate.",
            )
        )
    if (
        bindings["implementation_manifest_digest"]
        != expected_implementation_manifest_digest
    ):
        diagnostics.append(
            _diagnostic(
                "FOREIGN_IMPLEMENTATION_MANIFEST",
                "$.bindings.implementation_manifest_digest",
                "The expected-case manifest does not bind the independently trusted installed implementation.",
            )
        )

    route_bindings = manifest["route_capability_bindings"]
    assert isinstance(route_bindings, list)
    route_identities = [str(binding["route_identity"]) for binding in route_bindings]
    if route_identities != sorted(route_identities) or len(route_identities) != len(
        set(route_identities)
    ):
        diagnostics.append(
            _diagnostic(
                "ROUTE_CAPABILITY_BINDINGS_INVALID",
                "$.route_capability_bindings",
                "Route capability bindings must be complete, unique, and sorted by route identity.",
            )
        )
    for index, binding in enumerate(route_bindings):
        assert isinstance(binding, Mapping)
        if not _route_capability_binding_is_coherent(binding):
            diagnostics.append(
                _diagnostic(
                    "ROUTE_CAPABILITY_BINDING_COHERENCE_INVALID",
                    f"$.route_capability_bindings[{index}]",
                    "The route capability binding does not match its closed provider-family manager coordinates.",
                )
            )

    registry, registry_diagnostics = _expected_registry(manifest)
    diagnostics.extend(registry_diagnostics)
    return registry, tuple(sorted(diagnostics))


def _validate_attestation_manifest(
    attestation: JsonObject,
    bundle: JsonObject,
    expected_case_manifest: JsonObject,
    *,
    expected_attestation_manifest_digest: str,
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    recomputed_attestation_digest = _artifact_digest(
        attestation,
        "attestation_manifest_digest",
    )
    if attestation["attestation_manifest_digest"] != recomputed_attestation_digest:
        diagnostics.append(
            _diagnostic(
                "ATTESTATION_MANIFEST_DIGEST_INVALID",
                "$.attestation_manifest_digest",
                "The attestation digest does not match its closed payload.",
            )
        )
    if recomputed_attestation_digest != expected_attestation_manifest_digest:
        diagnostics.append(
            _diagnostic(
                "FOREIGN_ATTESTATION_MANIFEST",
                "$.attestation_manifest_digest",
                "The attestation does not match the independently trusted post-run attestation digest.",
            )
        )

    recomputed_bundle_digest = _artifact_digest(bundle, "bundle_digest")
    if attestation["bundle_digest"] != recomputed_bundle_digest:
        diagnostics.append(
            _diagnostic(
                "ATTESTATION_BUNDLE_DIGEST_MISMATCH",
                "$.bundle_digest",
                "The attestation does not bind the complete candidate evidence bundle.",
            )
        )
    if (
        attestation["expected_case_manifest_digest"]
        != expected_case_manifest["expected_case_manifest_digest"]
    ):
        diagnostics.append(
            _diagnostic(
                "ATTESTATION_EXPECTED_CASE_MISMATCH",
                "$.expected_case_manifest_digest",
                "The attestation does not bind the authorized expected-case manifest.",
            )
        )
    if (
        attestation["bindings"] != expected_case_manifest["bindings"]
        or attestation["bindings"] != bundle["bindings"]
    ):
        diagnostics.append(
            _diagnostic(
                "ATTESTATION_BINDINGS_MISMATCH",
                "$.bindings",
                "The attestation does not bind the exact candidate artifact tuple.",
            )
        )

    attestors = attestation["attestors"]
    assert isinstance(attestors, list)
    attestor_roles = [str(attestor["role"]) for attestor in attestors]
    attestor_identities = [str(attestor["identity"]) for attestor in attestors]
    if attestor_roles != list(ATTESTOR_ROLES) or len(set(attestor_identities)) != len(
        ATTESTOR_ROLES
    ):
        diagnostics.append(
            _diagnostic(
                "ATTESTOR_SET_INVALID",
                "$.attestors",
                "The attestor set must contain one distinct identity for each required role in canonical order.",
            )
        )

    evidence_timestamps = [
        _utc_timestamp_key(result["recorded_at"])
        for result in (*bundle["aggregate_results"], *bundle["child_results"])
    ]
    for result in bundle["child_results"]:
        evidence = result["evidence"]
        assert isinstance(evidence, Mapping)
        signoff = evidence.get("human_signoff")
        if isinstance(signoff, Mapping):
            evidence_timestamps.append(_utc_timestamp_key(signoff["signed_at"]))
    attestor_timestamps = [
        _utc_timestamp_key(attestor["attested_at"]) for attestor in attestors
    ]
    if any(
        timestamp is None for timestamp in (*evidence_timestamps, *attestor_timestamps)
    ):
        diagnostics.append(
            _diagnostic(
                "ATTESTATION_TIMESTAMP_INVALID",
                "$.attestors",
                "Attestation chronology requires valid RFC 3339 UTC timestamps.",
            )
        )
    elif min(attestor_timestamps) < max(evidence_timestamps):
        diagnostics.append(
            _diagnostic(
                "ATTESTATION_PRECEDES_EVIDENCE",
                "$.attestors",
                "Every attestation must be recorded at or after the latest bound result and live sign-off.",
            )
        )

    if attestor_roles == list(ATTESTOR_ROLES):
        live_operator_identity = attestor_identities[
            ATTESTOR_ROLES.index("live_operator")
        ]
        for result in bundle["child_results"]:
            if result["status"] != "pass":
                continue
            evidence = result["evidence"]
            assert isinstance(evidence, Mapping)
            if evidence.get("kind") != "live_receipt":
                continue
            signoff = evidence["human_signoff"]
            assert isinstance(signoff, Mapping)
            if signoff["signer_identity"] != live_operator_identity:
                diagnostics.append(
                    _diagnostic(
                        "LIVE_SIGNER_ATTESTOR_MISMATCH",
                        "$.attestors",
                        "Every passing live sign-off must name the canonical live-operator attestor.",
                    )
                )
                break
    return tuple(sorted(diagnostics))


def validate_acceptance_evidence(
    bundle: object,
    expected_case_manifest: object,
    attestation_manifest: object,
    *,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_case_manifest_digest: str,
    expected_attestation_manifest_digest: str,
    expected_apply_authorization_identity: str,
    expected_apply_authorization_digest: str,
    expected_execution_nonce: str,
    expected_run_identity: str,
) -> tuple[Diagnostic, ...]:
    """Validate one bundle against independently supplied release expectations.

    The caller owns authenticating the pre-run expected-case manifest and the
    post-run attestation digests. This pure validator does not authenticate
    signatures or receipts and performs no discovery, native-manager access,
    runtime mutation, or release publication.
    """

    if not _has_schema_version(
        expected_case_manifest,
        "agent-equipment-acceptance-expected-cases/v1",
    ) or not _schema_valid(expected_case_manifest):
        return (
            _diagnostic(
                "EXPECTED_CASE_MANIFEST_SCHEMA_INVALID",
                "$",
                "The expected-case manifest does not satisfy the checked-in closed schema.",
            ),
        )
    if _contains_literal_credential(expected_case_manifest):
        return (
            _literal_credential_diagnostic(
                "EXPECTED_CASE_MANIFEST_LITERAL_SECRET",
                "expected-case manifest",
            ),
        )
    assert isinstance(expected_case_manifest, Mapping)
    registry, manifest_diagnostics = _validate_expected_manifest(
        expected_case_manifest,
        expected_candidate_identity=expected_candidate_identity,
        expected_implementation_manifest_digest=expected_implementation_manifest_digest,
        expected_case_manifest_digest=expected_case_manifest_digest,
    )
    if manifest_diagnostics:
        return manifest_diagnostics

    if not _has_schema_version(
        bundle,
        "agent-equipment-acceptance-evidence/v1",
    ) or not _schema_valid(bundle):
        return (
            _diagnostic(
                "ACCEPTANCE_EVIDENCE_SCHEMA_INVALID",
                "$",
                "The acceptance evidence bundle does not satisfy the checked-in closed schema.",
            ),
        )
    if _contains_literal_credential(bundle):
        return (
            _literal_credential_diagnostic(
                "ACCEPTANCE_EVIDENCE_LITERAL_SECRET",
                "acceptance evidence bundle",
            ),
        )
    assert isinstance(bundle, Mapping)
    if not _has_schema_version(
        attestation_manifest,
        "agent-equipment-acceptance-attestation/v1",
    ) or not _schema_valid(attestation_manifest):
        return (
            _diagnostic(
                "ACCEPTANCE_ATTESTATION_SCHEMA_INVALID",
                "$",
                "The post-run attestation does not satisfy the checked-in closed schema.",
            ),
        )
    if _contains_literal_credential(attestation_manifest):
        return (
            _literal_credential_diagnostic(
                "ACCEPTANCE_ATTESTATION_LITERAL_SECRET",
                "release attestation",
            ),
        )
    assert isinstance(attestation_manifest, Mapping)
    diagnostics: list[Diagnostic] = []

    expected_execution_binding = {
        "apply_authorization_identity": expected_apply_authorization_identity,
        "apply_authorization_digest": expected_apply_authorization_digest,
        "execution_nonce": expected_execution_nonce,
        "run_identity": expected_run_identity,
    }
    if (
        bundle["execution_binding"] != expected_execution_binding
        or attestation_manifest["execution_binding"] != expected_execution_binding
    ):
        diagnostics.append(
            _diagnostic(
                "EXECUTION_BINDING_MISMATCH",
                "$.execution_binding",
                "Evidence and attestation must bind the exact externally trusted apply authorization, nonce, and run.",
            )
        )

    diagnostics.extend(
        _validate_attestation_manifest(
            attestation_manifest,
            bundle,
            expected_case_manifest,
            expected_attestation_manifest_digest=(expected_attestation_manifest_digest),
        )
    )

    if bundle["bundle_digest"] != _artifact_digest(bundle, "bundle_digest"):
        diagnostics.append(
            _diagnostic(
                "ACCEPTANCE_EVIDENCE_DIGEST_INVALID",
                "$.bundle_digest",
                "The evidence bundle digest does not match its closed payload.",
            )
        )
    if bundle["bindings"] != expected_case_manifest["bindings"]:
        diagnostics.append(
            _diagnostic(
                "EVIDENCE_BINDINGS_MISMATCH",
                "$.bindings",
                "The evidence bundle does not use the expected candidate and artifact bindings.",
            )
        )
    if bundle["fixture_version"] != expected_case_manifest["fixture_version"]:
        diagnostics.append(
            _diagnostic(
                "FIXTURE_VERSION_MISMATCH",
                "$.fixture_version",
                "The evidence bundle does not use the expected fixture version.",
            )
        )
    if (
        bundle["expected_case_manifest_digest"]
        != expected_case_manifest["expected_case_manifest_digest"]
    ):
        diagnostics.append(
            _diagnostic(
                "EXPECTED_CASE_BINDING_MISMATCH",
                "$.expected_case_manifest_digest",
                "The evidence bundle does not bind the supplied expected-case manifest.",
            )
        )
    if (
        bundle["route_capability_bindings"]
        != expected_case_manifest["route_capability_bindings"]
    ):
        diagnostics.append(
            _diagnostic(
                "ROUTE_CAPABILITY_BINDING_MISMATCH",
                "$.route_capability_bindings",
                "The bundle does not contain the exact sealed route capability and manager-evidence bindings.",
            )
        )

    if [entry["harness"] for entry in bundle["harness_versions"]] != [
        "claude",
        "codex",
        "cursor",
    ]:
        diagnostics.append(
            _diagnostic(
                "HARNESS_VERSION_SET_INVALID",
                "$.harness_versions",
                "Harness versions must cover the canonical harness set in order.",
            )
        )
    manager_identities = [
        str(entry["manager_identity"]) for entry in bundle["manager_versions"]
    ]
    if manager_identities != sorted(manager_identities) or len(
        manager_identities
    ) != len(set(manager_identities)):
        diagnostics.append(
            _diagnostic(
                "MANAGER_VERSION_SET_INVALID",
                "$.manager_versions",
                "Manager-version evidence must be unique and sorted by manager identity.",
            )
        )
    manager_evidence = {
        (str(entry["manager_identity"]), str(entry["evidence_digest"]))
        for entry in bundle["manager_versions"]
    }
    route_manager_evidence = {
        (
            str(binding["manager_identity"]),
            str(binding["manager_version_evidence_digest"]),
        )
        for binding in bundle["route_capability_bindings"]
    }
    if not route_manager_evidence <= manager_evidence:
        diagnostics.append(
            _diagnostic(
                "MANAGER_EVIDENCE_COVERAGE_INCOMPLETE",
                "$.manager_versions",
                "Every route manager-version evidence binding must have one matching manager-version record.",
            )
        )

    aggregate_results = bundle["aggregate_results"]
    assert isinstance(aggregate_results, list)
    aggregate_ids = [str(result["requirement_id"]) for result in aggregate_results]
    if aggregate_ids != list(REQUIRED_REQUIREMENTS):
        diagnostics.append(
            _diagnostic(
                "AGGREGATE_RESULT_SET_INVALID",
                "$.aggregate_results",
                "The bundle must contain one canonical aggregate result for every required ID.",
            )
        )

    child_results = bundle["child_results"]
    assert isinstance(child_results, list)
    latest_child_timestamps: dict[str, tuple[int | str, ...]] = {}
    for result in child_results:
        timestamp = _utc_timestamp_key(result["recorded_at"])
        assert timestamp is not None
        requirement_id = str(result["requirement_id"])
        prior = latest_child_timestamps.get(requirement_id)
        if prior is None or prior < timestamp:
            latest_child_timestamps[requirement_id] = timestamp
    for index, aggregate in enumerate(aggregate_results):
        requirement_id = str(aggregate["requirement_id"])
        aggregate_timestamp = _utc_timestamp_key(aggregate["recorded_at"])
        assert aggregate_timestamp is not None
        latest_child_timestamp = latest_child_timestamps.get(requirement_id)
        if (
            latest_child_timestamp is not None
            and aggregate_timestamp < latest_child_timestamp
        ):
            diagnostics.append(
                _diagnostic(
                    "AGGREGATE_PRECEDES_CHILD_RESULT",
                    f"$.aggregate_results[{index}].recorded_at",
                    "An aggregate result must be recorded at or after every child result for the same requirement.",
                )
            )
    actual_coordinates = [
        (
            str(result["requirement_id"]),
            str(result["fixture_family"]),
            str(result["subject_identity"]),
            str(result["case_identity"]),
        )
        for result in child_results
    ]
    expected_coordinates = [
        (
            case.requirement_id,
            case.fixture_family,
            case.subject_identity,
            case.case_identity,
        )
        for case in registry
    ]
    actual_counts = Counter(actual_coordinates)
    expected_counts = Counter(expected_coordinates)
    if any(count > 1 for count in actual_counts.values()):
        diagnostics.append(
            _diagnostic(
                "CHILD_RESULT_DUPLICATE",
                "$.child_results",
                "A child case appears more than once.",
            )
        )
    if expected_counts - actual_counts:
        diagnostics.append(
            _diagnostic(
                "CHILD_RESULT_MISSING",
                "$.child_results",
                "At least one expected child case is absent.",
            )
        )
    if actual_counts - expected_counts:
        diagnostics.append(
            _diagnostic(
                "CHILD_RESULT_EXTRA",
                "$.child_results",
                "At least one child case is not present in the sealed expected registry.",
            )
        )
    membership_exact = actual_counts == expected_counts
    if membership_exact and actual_coordinates != expected_coordinates:
        diagnostics.append(
            _diagnostic(
                "CHILD_RESULT_ORDER_INVALID",
                "$.child_results",
                "Child results must use the canonical expected-case order.",
            )
        )
    if membership_exact and actual_coordinates == expected_coordinates:
        child_statuses: dict[str, list[str]] = {
            requirement_id: [] for requirement_id in REQUIRED_REQUIREMENTS
        }
        for index, (result, expected_case) in enumerate(zip(child_results, registry)):
            status = str(result["status"])
            evidence = result["evidence"]
            assert isinstance(evidence, Mapping)
            evidence_kind = str(evidence["kind"])
            child_statuses[expected_case.requirement_id].append(status)
            if status in {"blocked", "not_run"}:
                if evidence_kind != "unavailable":
                    diagnostics.append(
                        _diagnostic(
                            "UNAVAILABLE_EVIDENCE_SHAPE_INVALID",
                            f"$.child_results[{index}].evidence",
                            "Blocked and not-run cases must carry the closed unavailable evidence shape.",
                        )
                    )
            elif evidence_kind != expected_case.evidence_kind:
                diagnostics.append(
                    _diagnostic(
                        "CHILD_EVIDENCE_KIND_MISMATCH",
                        f"$.child_results[{index}].evidence.kind",
                        "The child result does not carry the evidence kind sealed by its expected case.",
                    )
                )
            if status != "pass":
                diagnostics.append(
                    _diagnostic(
                        "CHILD_RESULT_NOT_PASSING",
                        f"$.child_results[{index}].status",
                        "Only a passing child result satisfies the release gate.",
                    )
                )

        if aggregate_ids == list(REQUIRED_REQUIREMENTS):
            for index, aggregate in enumerate(aggregate_results):
                requirement_id = str(aggregate["requirement_id"])
                aggregate_status = str(aggregate["status"])
                all_children_pass = all(
                    status == "pass" for status in child_statuses[requirement_id]
                )
                if (aggregate_status == "pass") != all_children_pass:
                    diagnostics.append(
                        _diagnostic(
                            "AGGREGATE_STATUS_INVALID",
                            f"$.aggregate_results[{index}].status",
                            "An aggregate passes if and only if every expected child passes.",
                        )
                    )
                if aggregate_status != "pass":
                    diagnostics.append(
                        _diagnostic(
                            "REQUIREMENT_NOT_PASSING",
                            f"$.aggregate_results[{index}].status",
                            "Only a passing aggregate result satisfies the release gate.",
                        )
                    )

    return tuple(sorted(diagnostics))


def _strict_json_load(stream: object) -> object:
    def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate object member")
            result[key] = value
        return result

    def reject_nonfinite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("non-finite JSON number")
        return parsed

    return json.load(
        stream,
        object_pairs_hook=reject_duplicate_pairs,
        parse_float=reject_nonfinite_float,
        parse_constant=lambda _value: (_ for _ in ()).throw(
            ValueError("non-JSON numeric constant")
        ),
    )


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate one release evidence bundle against an independently "
            "supplied closed expected-case manifest."
        )
    )
    parser.add_argument(
        "--expected-case-manifest",
        required=True,
        type=Path,
        help="sealed expected cases emitted from the validated production plan",
    )
    parser.add_argument(
        "--expected-candidate-identity",
        required=True,
        help="release-launcher-trusted immutable candidate identity",
    )
    parser.add_argument(
        "--expected-implementation-manifest-digest",
        required=True,
        help="release-launcher-trusted installed implementation manifest digest",
    )
    parser.add_argument(
        "--expected-case-manifest-digest",
        required=True,
        help="release-launcher-trusted digest of the authorized expected-case projection",
    )
    parser.add_argument(
        "--attestation-manifest",
        required=True,
        type=Path,
        help="separately attested post-run binding of the complete evidence bundle",
    )
    parser.add_argument(
        "--expected-attestation-manifest-digest",
        required=True,
        help="release-launcher-trusted digest of the authorized post-run attestation",
    )
    parser.add_argument(
        "--expected-apply-authorization-identity",
        required=True,
        help="executor-trusted identity of the exact apply authorization",
    )
    parser.add_argument(
        "--expected-apply-authorization-digest",
        required=True,
        help="executor-trusted canonical digest of the complete apply authorization record",
    )
    parser.add_argument(
        "--expected-execution-nonce",
        required=True,
        help="executor-trusted fresh nonce claimed for this apply run",
    )
    parser.add_argument(
        "--expected-run-identity",
        required=True,
        help="executor-trusted identity of this apply run",
    )
    parser.add_argument("bundle", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        with args.expected_case_manifest.open(encoding="utf-8") as stream:
            expected_case_manifest = _strict_json_load(stream)
    except (OSError, UnicodeError, ValueError):
        print(
            "EXPECTED_CASE_MANIFEST_READ_FAILED: expected cases could not be read as strict UTF-8 JSON.",
            file=sys.stderr,
        )
        return 1
    try:
        with args.bundle.open(encoding="utf-8") as stream:
            bundle = _strict_json_load(stream)
    except (OSError, UnicodeError, ValueError):
        print(
            "ACCEPTANCE_EVIDENCE_READ_FAILED: evidence could not be read as strict UTF-8 JSON.",
            file=sys.stderr,
        )
        return 1
    try:
        with args.attestation_manifest.open(encoding="utf-8") as stream:
            attestation_manifest = _strict_json_load(stream)
    except (OSError, UnicodeError, ValueError):
        print(
            "ACCEPTANCE_ATTESTATION_READ_FAILED: attestation could not be read as strict UTF-8 JSON.",
            file=sys.stderr,
        )
        return 1

    diagnostics = validate_acceptance_evidence(
        bundle,
        expected_case_manifest,
        attestation_manifest,
        expected_candidate_identity=args.expected_candidate_identity,
        expected_implementation_manifest_digest=(
            args.expected_implementation_manifest_digest
        ),
        expected_case_manifest_digest=args.expected_case_manifest_digest,
        expected_attestation_manifest_digest=(
            args.expected_attestation_manifest_digest
        ),
        expected_apply_authorization_identity=(
            args.expected_apply_authorization_identity
        ),
        expected_apply_authorization_digest=args.expected_apply_authorization_digest,
        expected_execution_nonce=args.expected_execution_nonce,
        expected_run_identity=args.expected_run_identity,
    )
    for diagnostic in diagnostics:
        print(
            f"{diagnostic.path}: {diagnostic.code}: {diagnostic.message}",
            file=sys.stderr,
        )
    return 1 if diagnostics else 0


if __name__ == "__main__":
    raise SystemExit(main())
