from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "docs/agent-equipment/adapter-contract-v1.schema.json"
CAPTURED_STATE_SCHEMA = ROOT / "docs/agent-equipment/captured-state-v1.schema.json"
PROPOSED_CATALOG = ROOT / "docs/agent-equipment/initial-catalog.proposed.json"
FIXTURES = ROOT / "tests/fixtures/agent-equipment/schema"
TRUSTED_CANDIDATE_IDENTITY = "candidate:001"
TRUSTED_IMPLEMENTATION_MANIFEST_DIGEST = "sha256:" + "9" * 64
IMMUTABLE_REVISION = "0123456789abcdef0123456789abcdef01234567"
IMMUTABLE_CONTENT_DIGEST = "sha256:" + "1" * 64
SPEC = importlib.util.spec_from_file_location(
    "agent_equipment_adapter_contract",
    ROOT / "scripts/agent_equipment_adapter_contract.py",
)
assert SPEC is not None and SPEC.loader is not None
CONTRACT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CONTRACT
SPEC.loader.exec_module(CONTRACT)


def run_check_jsonschema(*arguments: str) -> subprocess.CompletedProcess[str]:
    base_uri_arguments = (
        () if "--check-metaschema" in arguments else ("--base-uri", SCHEMA.as_uri())
    )
    return subprocess.run(
        [
            "uvx",
            "--from",
            "check-jsonschema==0.35.0",
            "check-jsonschema",
            *base_uri_arguments,
            *arguments,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def canonical_digest(document: object) -> str:
    payload = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def canonical_action_identity(action: dict[str, object]) -> str:
    identity_payload = {
        "plan_digest": action["plan_digest"],
        "ordinal": action["ordinal"],
        "route_id": action["route_identity"],
        "operation": action["operation"],
        "desired_state_digest": action["desired_state_digest"],
    }
    return f"action:{canonical_digest(identity_payload)}"


def schema_valid_mismatch(field: str, current: object) -> object:
    """Return a different value that still satisfies the field's schema shape."""
    if field in {
        "implementation_manifest_digest",
        "catalog_digest",
        "lock_digest",
        "plan_digest",
        "capability_digest",
        "manager_version_evidence_digest",
        "route_digest",
    }:
        replacement = "sha256:" + "0" * 64
        return "sha256:" + "1" * 64 if current == replacement else replacement
    if field == "action_identity":
        replacement = "action:sha256:" + "0" * 64
        return "action:sha256:" + "1" * 64 if current == replacement else replacement
    if field == "ordinal":
        return 1 if current != 1 else 2
    if field == "harness":
        return "codex" if current != "codex" else "claude"
    if field == "route_identity":
        return "route:claude/schema-valid-mismatch"
    if field == "activation_group":
        return "activation:claude/schema-valid-mismatch"
    if field == "equipment_identities":
        return ["skill:fixture/schema-valid-mismatch"]
    if field == "controlled_equipment_identities":
        return ["skill:fixture/schema-valid-controlled-mismatch"]
    if field == "surface_scope":
        return ["surface:fixture/schema-valid-mismatch"]
    if field == "secret_references":
        return [{"kind": "environment_variable", "name": "FIXTURE_SECRET"}]
    if field == "route_record":
        replacement = copy.deepcopy(current)
        replacement["identity"] = "route:claude/schema-valid-mismatch"
        return replacement
    if field == "operation":
        return "configure" if current != "configure" else "enable"
    if isinstance(current, str):
        return f"schema-valid-mismatch:{field}"
    raise AssertionError(f"No schema-valid mismatch is defined for {field!r}")


def expected_post_normalized_state(
    pre_state: dict[str, object],
    desired_state: dict[str, object],
) -> dict[str, object]:
    expected = copy.deepcopy(pre_state)
    for field, value in desired_state.items():
        if field == "configuration" and value.get("status") == "desired":
            value = {"status": "observed", "digest": value["digest"]}
        expected[field] = copy.deepcopy(value)
    return expected


def set_normalized_state(
    result: dict[str, object],
    normalized_state: dict[str, object],
) -> str:
    result["normalized_state"] = copy.deepcopy(normalized_state)
    state_digest = canonical_digest(normalized_state)
    result["state_digest"] = state_digest
    return state_digest


def load_document(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_record(name: str) -> dict[str, object]:
    document = load_document(name)
    if document["record_type"] == "CapabilityDiscovery":
        return document["result"]["records"][0]
    return document["record"]


def capability_record(document: dict[str, object]) -> dict[str, object]:
    return document["result"]["records"][0]


def valid_sequence() -> tuple[dict[str, object], ...]:
    return tuple(
        load_document(name)
        for name in (
            "valid-adapter-capability-record.json",
            "valid-adapter-observe-request.json",
            "valid-adapter-runtime-observation.json",
            "valid-adapter-planned-action.json",
            "valid-adapter-mutation-receipt.json",
        )
    )


def apply_sequence_document(
    records: tuple[dict[str, object], ...] | list[dict[str, object]],
) -> dict[str, object]:
    (
        discovery,
        request_document,
        observation_document,
        action_document,
        receipt_document,
    ) = copy.deepcopy(records)
    request = request_document["record"]
    observation = observation_document["record"]
    action = action_document["record"]
    receipt = receipt_document["record"]
    phase = receipt["phase"]
    observation_result = observation["result"]
    pre_state = observation_result["normalized_state"]
    captured_state = observation_result["captured_state"]
    if phase == "compensate":
        request["purpose"] = "recovery"
        request["expected_state_digest"] = observation_result["state_digest"]

    verification_request_document = copy.deepcopy(request_document)
    verification_request = verification_request_document["record"]
    verification_request["request_identity"] = "request:verify-post-001"
    verification_request["purpose"] = (
        "verify_post_state" if phase == "apply" else "verify_compensation"
    )
    verification_observation_document = copy.deepcopy(observation_document)
    verification_observation = verification_observation_document["record"]
    verification_observation["request_identity"] = verification_request[
        "request_identity"
    ]
    verification_observation["observed_at"] = "2026-08-12T15:00:02Z"
    verification_observation["result"]["captured_state"] = {"status": "not_applicable"}
    expected_post_state = (
        expected_post_normalized_state(pre_state, action["desired_state"])
        if phase == "apply"
        else copy.deepcopy(pre_state)
    )
    verified_state_digest = set_normalized_state(
        verification_observation["result"], expected_post_state
    )
    verification_request["expected_state_digest"] = verified_state_digest
    verification_observation["result"]["state_digest"] = verified_state_digest

    authority = {
        "contract_version": "adapter-contract-v1",
        "command": request["command"],
        "purpose": request["purpose"],
        "phase": phase,
        "request_identity": request["request_identity"],
        "action_identity": action["action_identity"],
        "correlation_identity": request["correlation_identity"],
        "candidate_identity": request["candidate_identity"],
        "implementation_manifest_digest": request["implementation_manifest_digest"],
        "catalog_digest": request["catalog_digest"],
        "lock_digest": request["lock_digest"],
        "plan_digest": request["plan_digest"],
        "capability_identity": request["capability_identity"],
        "capability_digest": request["capability_digest"],
        "manager_version_evidence_digest": request["manager_version_evidence_digest"],
        "adapter_identity": action["adapter_identity"],
        "adapter_version": action["adapter_version"],
        "harness": request["harness"],
        "route_identity": request["route_identity"],
        "route_digest": request["route_digest"],
        "equipment_identities": copy.deepcopy(request["equipment_identities"]),
        "controlled_equipment_identities": copy.deepcopy(
            request["controlled_equipment_identities"]
        ),
        "activation_group": request["activation_group"],
        "operation": action.get("operation"),
        "read_surface_scope": copy.deepcopy(request["surface_scope"]),
        "write_surface_scope": copy.deepcopy(request["surface_scope"]),
        "selected_component_controls": copy.deepcopy(
            request["route_record"]["component_controls"]
        ),
        "captured_state_identity": captured_state.get("identity"),
        "captured_state_digest": captured_state.get("digest"),
        "captured_pre_state": copy.deepcopy(pre_state),
        "captured_pre_state_digest": observation_result["state_digest"],
        "expected_pre_state_digest": observation_result["state_digest"],
        "expected_post_state": copy.deepcopy(expected_post_state),
        "expected_post_state_digest": verified_state_digest,
        "forward_post_state_digest": verified_state_digest,
        "prepared_checkpoint_reference": receipt["prepared_checkpoint_reference"],
    }
    return {
        "record_type": "ApplySequence",
        "sequence": {
            "authority": authority,
            "capability_discovery": discovery,
            "pre_state_request": request_document,
            "pre_state_observation": observation_document,
            "planned_action": action_document,
            "mutation_receipt": receipt_document,
            "post_state_request": verification_request_document,
            "post_state_observation": verification_observation_document,
        },
    }


def valid_compensation_sequence_document(
    records: tuple[dict[str, object], ...] | list[dict[str, object]] | None = None,
) -> dict[str, object]:
    sequence = list(copy.deepcopy(records if records is not None else valid_sequence()))
    captured_pre_state = copy.deepcopy(
        sequence[2]["record"]["result"]["normalized_state"]
    )
    captured_pre_state_digest = sequence[2]["record"]["result"]["state_digest"]
    forward_post_state = expected_post_normalized_state(
        captured_pre_state,
        sequence[3]["record"]["desired_state"],
    )
    forward_post_state_digest = set_normalized_state(
        sequence[2]["record"]["result"], forward_post_state
    )
    receipt = sequence[4]["record"]
    receipt["phase"] = "compensate"
    receipt["result"]["expected_pre_state_digest"] = forward_post_state_digest
    receipt["result"]["observed_pre_state_digest"] = forward_post_state_digest
    receipt["result"]["expected_post_state_digest"] = captured_pre_state_digest
    receipt["result"]["observed_post_state_digest"] = captured_pre_state_digest
    compensation = receipt["result"]["compensation_evidence"]
    compensation.pop("expected_post_state_digest")
    compensation["status"] = "restored"
    compensation["restored_state_digest"] = captured_pre_state_digest
    compensation["comparison"] = "equal"
    document = apply_sequence_document(sequence)
    document["sequence"]["authority"]["captured_pre_state_digest"] = (
        captured_pre_state_digest
    )
    document["sequence"]["authority"]["captured_pre_state"] = captured_pre_state
    document["sequence"]["authority"]["expected_pre_state_digest"] = (
        forward_post_state_digest
    )
    document["sequence"]["authority"]["expected_post_state"] = captured_pre_state
    document["sequence"]["authority"]["expected_post_state_digest"] = (
        captured_pre_state_digest
    )
    document["sequence"]["authority"]["forward_post_state_digest"] = (
        forward_post_state_digest
    )
    document["sequence"]["post_state_request"]["record"]["expected_state_digest"] = (
        captured_pre_state_digest
    )
    set_normalized_state(
        document["sequence"]["post_state_observation"]["record"]["result"],
        captured_pre_state,
    )
    return document


def rebind_capability_digest(sequence: list[dict[str, object]]) -> None:
    capability = capability_record(sequence[0])
    capability_without_digest = copy.deepcopy(capability)
    capability_without_digest.pop("capability_digest")
    capability["capability_digest"] = canonical_digest(capability_without_digest)
    for index in (1, 2, 3, 4):
        sequence[index]["record"]["capability_digest"] = capability["capability_digest"]
    sequence[3]["record"]["preconditions"]["capability_digest"] = capability[
        "capability_digest"
    ]


def rehash_capability_record(capability: dict[str, object]) -> None:
    capability_without_digest = copy.deepcopy(capability)
    capability_without_digest.pop("capability_digest")
    capability["capability_digest"] = canonical_digest(capability_without_digest)


def append_unrelated_capability(
    sequence: list[dict[str, object]],
) -> dict[str, object]:
    unrelated = copy.deepcopy(capability_record(sequence[0]))
    unrelated["capability_identity"] = "capability:unrelated"
    rehash_capability_record(unrelated)
    sequence[0]["result"]["records"].append(unrelated)
    return unrelated


def rebind_route_digest(sequence: list[dict[str, object]]) -> None:
    controlled_identities = sorted(
        control["equipment_identity"]
        for control in sequence[1]["record"]["route_record"]["component_controls"]
    )
    for index in (1, 2, 3, 4):
        sequence[index]["record"]["controlled_equipment_identities"] = copy.deepcopy(
            controlled_identities
        )
    route_digest = canonical_digest(sequence[1]["record"]["route_record"])
    for index in (1, 2, 3, 4):
        sequence[index]["record"]["route_digest"] = route_digest
    sequence[3]["record"]["preconditions"]["route_digest"] = route_digest


def rebind_surface_scope(
    sequence: list[dict[str, object]],
    surface_scope: list[str],
) -> None:
    for index in (1, 2, 3, 4):
        sequence[index]["record"]["surface_scope"] = copy.deepcopy(surface_scope)
    sequence[3]["record"]["preconditions"]["surface_scope"] = copy.deepcopy(
        surface_scope
    )
    observation_evidence = sequence[2]["record"]["result"]["surface_evidence"]
    observation_digest = observation_evidence[0]["digest"]
    sequence[2]["record"]["result"]["surface_evidence"] = [
        {
            "kind": "manager",
            "identity": identity,
            "digest": observation_digest,
        }
        for identity in surface_scope
    ]
    receipt_evidence = sequence[4]["record"]["result"]["surface_evidence"]
    receipt_digest = receipt_evidence[0]["digest"]
    sequence[4]["record"]["result"]["surface_evidence"] = [
        {
            "kind": "surface",
            "identity": identity,
            "digest": receipt_digest,
        }
        for identity in surface_scope
    ]


def rebind_desired_state(sequence: list[dict[str, object]]) -> None:
    action = sequence[3]["record"]
    desired_digest = canonical_digest(action["desired_state"])
    action["desired_state_digest"] = desired_digest
    action_identity = canonical_action_identity(action)
    action["action_identity"] = action_identity
    sequence[4]["record"]["action_identity"] = action_identity
    post_state = expected_post_normalized_state(
        sequence[2]["record"]["result"]["normalized_state"],
        action["desired_state"],
    )
    post_digest = canonical_digest(post_state)
    result = sequence[4]["record"]["result"]
    result["expected_post_state_digest"] = post_digest
    result["observed_post_state_digest"] = post_digest
    result["compensation_evidence"]["expected_post_state_digest"] = post_digest


def rebind_sequence_provider(
    sequence: list[dict[str, object]],
    capability_provider: dict[str, object],
    evidence_manager: str,
    route_provider: dict[str, object],
) -> None:
    capability = capability_record(sequence[0])
    capability["provider_match"] = capability_provider
    evidence = capability["manager_version_evidence"]
    evidence["manager"] = evidence_manager
    evidence_without_digest = copy.deepcopy(evidence)
    evidence_without_digest.pop("evidence_digest")
    evidence["evidence_digest"] = canonical_digest(evidence_without_digest)
    rebind_capability_digest(sequence)
    for index in (1, 2, 3, 4):
        sequence[index]["record"]["manager_version_evidence_digest"] = evidence[
            "evidence_digest"
        ]
    sequence[3]["record"]["preconditions"]["manager_version_evidence_digest"] = (
        evidence["evidence_digest"]
    )
    for index in (1, 3):
        sequence[index]["record"]["route_record"]["provider"] = copy.deepcopy(
            route_provider
        )
    rebind_route_digest(sequence)


def immutable_sequence() -> list[dict[str, object]]:
    sequence = list(copy.deepcopy(valid_sequence()))
    rebind_sequence_provider(
        sequence,
        {"kind": "standalone_skill", "canonical_root": "agents_skills"},
        "standalone_skills",
        {"kind": "standalone_skill", "canonical_root": "agents_skills"},
    )
    capability = capability_record(sequence[0])
    inspect_support = capability["operation_support"]["inspect"]
    inspect_support["normalized_fields"] = sorted(
        {*inspect_support["normalized_fields"], "immutable_content"}
    )
    capability["native_update_support"] = {
        "native_update_control": "not_applicable",
        "version_observation": "unavailable",
        "baseline_comparison": "unavailable",
        "suppression": {"mode": "unavailable"},
        "suppression_scope": "none",
    }
    capability["operation_support"]["suppress_native_update"] = {"mode": "unavailable"}
    rebind_capability_digest(sequence)

    immutable_restore = {
        "class": "immutable",
        "revision": IMMUTABLE_REVISION,
        "artifact_ref": (
            "git+https://example.invalid/fixture.git@" + IMMUTABLE_REVISION
        ),
        "content_digest": IMMUTABLE_CONTENT_DIGEST,
        "native_update_control": "not_applicable",
    }
    for index in (1, 3):
        sequence[index]["record"]["route_record"]["restore"] = copy.deepcopy(
            immutable_restore
        )
        sequence[index]["record"]["route_record"]["operations"][
            "suppress_native_update"
        ] = {"disposition": "unavailable"}
    rebind_route_digest(sequence)

    normalized_state = sequence[2]["record"]["result"]["normalized_state"]
    normalized_state.update(
        {
            "observed_version": {"status": "not_applicable"},
            "immutable_content": {
                "status": "observed",
                "revision": IMMUTABLE_REVISION,
                "content_digest": IMMUTABLE_CONTENT_DIGEST,
            },
            "native_update_control": "not_applicable",
            "native_update_suppression_state": "not_applicable",
            "manager_drift": {
                "status": "not_applicable",
                "reviewed_baseline": None,
                "observation_source": None,
            },
        }
    )
    pre_state_digest = set_normalized_state(
        sequence[2]["record"]["result"], normalized_state
    )
    receipt_result = sequence[4]["record"]["result"]
    receipt_result["expected_pre_state_digest"] = pre_state_digest
    receipt_result["observed_pre_state_digest"] = pre_state_digest
    rebind_desired_state(sequence)
    return sequence


def replace_pre_state(
    document: dict[str, object], normalized_state: dict[str, object]
) -> None:
    sequence = document["sequence"]
    result = sequence["pre_state_observation"]["record"]["result"]
    state_digest = set_normalized_state(result, normalized_state)
    authority = sequence["authority"]
    authority["captured_pre_state"] = copy.deepcopy(normalized_state)
    authority["captured_pre_state_digest"] = state_digest
    authority["expected_pre_state_digest"] = state_digest
    receipt_result = sequence["mutation_receipt"]["record"]["result"]
    receipt_result["expected_pre_state_digest"] = state_digest
    receipt_result["observed_pre_state_digest"] = state_digest


def replace_verified_post_state(
    document: dict[str, object], normalized_state: dict[str, object]
) -> None:
    sequence = document["sequence"]
    result = sequence["post_state_observation"]["record"]["result"]
    state_digest = set_normalized_state(result, normalized_state)
    sequence["post_state_request"]["record"]["expected_state_digest"] = state_digest
    authority = sequence["authority"]
    authority["expected_post_state"] = copy.deepcopy(normalized_state)
    authority["expected_post_state_digest"] = state_digest
    authority["forward_post_state_digest"] = state_digest
    receipt_result = sequence["mutation_receipt"]["record"]["result"]
    receipt_result["expected_post_state_digest"] = state_digest
    receipt_result["observed_post_state_digest"] = state_digest
    receipt_result["compensation_evidence"]["expected_post_state_digest"] = state_digest


def replace_compensation_restore_state(
    document: dict[str, object], normalized_state: dict[str, object]
) -> None:
    sequence = document["sequence"]
    state_digest = canonical_digest(normalized_state)
    authority = sequence["authority"]
    authority["captured_pre_state"] = copy.deepcopy(normalized_state)
    authority["captured_pre_state_digest"] = state_digest
    authority["expected_post_state"] = copy.deepcopy(normalized_state)
    authority["expected_post_state_digest"] = state_digest
    sequence["post_state_request"]["record"]["expected_state_digest"] = state_digest
    set_normalized_state(
        sequence["post_state_observation"]["record"]["result"], normalized_state
    )
    receipt_result = sequence["mutation_receipt"]["record"]["result"]
    receipt_result["expected_post_state_digest"] = state_digest
    receipt_result["observed_post_state_digest"] = state_digest
    receipt_result["compensation_evidence"]["restored_state_digest"] = state_digest


def diagnostic_codes(sequence: tuple[dict[str, object], ...]) -> set[str]:
    return document_diagnostic_codes(apply_sequence_document(sequence))


def document_diagnostic_codes(document: dict[str, object]) -> set[str]:
    return {diagnostic.code for diagnostic in validate_adapter_sequence(document)}


def validate_adapter_sequence(
    document: dict[str, object],
    *,
    trusted_candidate_identity: str = TRUSTED_CANDIDATE_IDENTITY,
    trusted_implementation_manifest_digest: str = TRUSTED_IMPLEMENTATION_MANIFEST_DIGEST,
) -> tuple[object, ...]:
    return CONTRACT.validate_sequence(
        document,
        trusted_candidate_identity=trusted_candidate_identity,
        trusted_implementation_manifest_digest=trusted_implementation_manifest_digest,
    )


def write_document(path: Path, document: object) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


class AdapterContractSchemaTests(unittest.TestCase):
    def test_public_sequence_rejects_literal_credentials_without_echoing_them(
        self,
    ) -> None:
        secret_canary = "Author" + "ization:" + " Bear" + "er actual-secret-value"
        sequence = valid_sequence()
        capability = capability_record(sequence[0])
        evidence = capability["manager_version_evidence"]
        evidence["observation_source"] = secret_canary
        evidence_without_digest = copy.deepcopy(evidence)
        evidence_without_digest.pop("evidence_digest")
        evidence["evidence_digest"] = canonical_digest(evidence_without_digest)
        rebind_capability_digest(sequence)
        for index in (1, 2, 3, 4):
            sequence[index]["record"]["manager_version_evidence_digest"] = evidence[
                "evidence_digest"
            ]
        sequence[3]["record"]["preconditions"]["manager_version_evidence_digest"] = (
            evidence["evidence_digest"]
        )

        diagnostics = validate_adapter_sequence(apply_sequence_document(sequence))

        self.assertEqual(
            [diagnostic.code for diagnostic in diagnostics],
            ["ADAPTER_SEQUENCE_LITERAL_SECRET"],
        )
        self.assertNotIn(secret_canary, repr(diagnostics))

    def test_semantic_validation_requires_external_implementation_trust(self) -> None:
        with self.assertRaises(TypeError):
            CONTRACT.validate_sequence(apply_sequence_document(valid_sequence()))

    def test_semantic_validation_rejects_a_sequence_for_an_untrusted_implementation(
        self,
    ) -> None:
        document = apply_sequence_document(valid_sequence())
        diagnostics = CONTRACT.validate_sequence(
            document,
            trusted_candidate_identity="candidate:other",
            trusted_implementation_manifest_digest="sha256:" + "0" * 64,
        )

        self.assertIn("TRUSTED_CANDIDATE_MISMATCH", {item.code for item in diagnostics})
        self.assertIn(
            "TRUSTED_IMPLEMENTATION_MANIFEST_MISMATCH",
            {item.code for item in diagnostics},
        )

    def test_coordinated_sequence_substitution_cannot_replace_executor_trust(
        self,
    ) -> None:
        for field, replacement, expected_code in (
            (
                "candidate_identity",
                "candidate:coordinated-other",
                "TRUSTED_CANDIDATE_MISMATCH",
            ),
            (
                "implementation_manifest_digest",
                "sha256:" + "0" * 64,
                "TRUSTED_IMPLEMENTATION_MANIFEST_MISMATCH",
            ),
        ):
            with self.subTest(field=field):
                document = apply_sequence_document(valid_sequence())
                document["sequence"]["authority"][field] = replacement
                for record_name in (
                    "pre_state_request",
                    "pre_state_observation",
                    "planned_action",
                    "mutation_receipt",
                    "post_state_request",
                    "post_state_observation",
                ):
                    document["sequence"][record_name]["record"][field] = replacement
                document["sequence"]["planned_action"]["record"]["preconditions"][
                    field
                ] = replacement

                self.assertIn(expected_code, document_diagnostic_codes(document))

    def test_public_sequence_validation_requires_mutation_safety_preconditions(
        self,
    ) -> None:
        for field in ("prepared_checkpoint_required", "compare_before_mutate"):
            for defect in ("false", "missing"):
                with self.subTest(field=field, defect=defect):
                    document = apply_sequence_document(valid_sequence())
                    preconditions = document["sequence"]["planned_action"]["record"][
                        "preconditions"
                    ]
                    if defect == "false":
                        preconditions[field] = False
                    else:
                        preconditions.pop(field)

                    self.assertIn(
                        "ADAPTER_SCHEMA_INVALID",
                        document_diagnostic_codes(document),
                    )

    def test_public_sequence_validation_rejects_unknown_nested_members(self) -> None:
        locations = (
            ("authority",),
            ("planned_action", "record"),
            ("planned_action", "record", "preconditions"),
            ("pre_state_request", "record", "route_record"),
        )
        for location in locations:
            with self.subTest(location=location):
                document = apply_sequence_document(valid_sequence())
                target = document["sequence"]
                for name in location:
                    target = target[name]
                target["attacker_unknown"] = True

                self.assertIn(
                    "ADAPTER_SCHEMA_INVALID",
                    document_diagnostic_codes(document),
                )

    def test_public_sequence_validation_rejects_excessive_nesting(self) -> None:
        document = apply_sequence_document(valid_sequence())
        nested: object = None
        for _ in range(2_000):
            nested = [nested]
        document["sequence"]["authority"]["attacker_unknown"] = nested

        self.assertIn(
            "ADAPTER_SCHEMA_INVALID",
            document_diagnostic_codes(document),
        )

    def test_public_schema_gate_rejects_malformed_supported_keyword_values(
        self,
    ) -> None:
        invalid_values = {
            "type": None,
            "required": {},
            "properties": [],
            "oneOf": {},
            "items": [],
            "additionalProperties": "false",
            "minItems": -1,
            "uniqueItems": "true",
            "minimum": True,
            "pattern": 1,
            "if": [],
        }
        for keyword, invalid_value in invalid_values.items():
            with (
                self.subTest(keyword=keyword),
                tempfile.TemporaryDirectory() as directory,
            ):
                schema_directory = Path(directory)
                invalid_schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
                invalid_schema[keyword] = invalid_value
                (schema_directory / SCHEMA.name).write_text(
                    json.dumps(invalid_schema), encoding="utf-8"
                )
                catalog_schema = ROOT / "docs/agent-equipment/catalog-v1.schema.json"
                (schema_directory / catalog_schema.name).write_text(
                    catalog_schema.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                original_directory = CONTRACT.SCHEMA_DIRECTORY
                CONTRACT.SCHEMA_DIRECTORY = schema_directory
                try:
                    self.assertIn(
                        "ADAPTER_SCHEMA_INVALID",
                        document_diagnostic_codes(
                            apply_sequence_document(valid_sequence())
                        ),
                    )
                finally:
                    CONTRACT.SCHEMA_DIRECTORY = original_directory

    def test_public_schema_gate_rejects_nested_schema_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            schema_directory = Path(directory)
            invalid_schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
            invalid_schema["$defs"]["digest"]["$id"] = "nested-digest.json"
            (schema_directory / SCHEMA.name).write_text(
                json.dumps(invalid_schema),
                encoding="utf-8",
            )
            catalog_schema = ROOT / "docs/agent-equipment/catalog-v1.schema.json"
            (schema_directory / catalog_schema.name).write_text(
                catalog_schema.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            original_directory = CONTRACT.SCHEMA_DIRECTORY
            CONTRACT.SCHEMA_DIRECTORY = schema_directory
            try:
                diagnostics = document_diagnostic_codes(
                    apply_sequence_document(valid_sequence())
                )
            finally:
                CONTRACT.SCHEMA_DIRECTORY = original_directory

        self.assertEqual({"ADAPTER_SCHEMA_INVALID"}, diagnostics)

    def test_public_sequence_validation_requires_exact_contract_versions(self) -> None:
        locations = (
            ("authority",),
            ("capability_discovery", "result", "records", 0),
            ("pre_state_request", "record"),
            ("pre_state_observation", "record"),
            ("planned_action", "record"),
            ("mutation_receipt", "record"),
            ("post_state_request", "record"),
            ("post_state_observation", "record"),
        )
        for location in locations:
            for defect in ("missing", "wrong"):
                with self.subTest(location=location, defect=defect):
                    document = apply_sequence_document(valid_sequence())
                    target = document["sequence"]
                    for name in location:
                        target = target[name]
                    if defect == "missing":
                        target.pop("contract_version")
                    else:
                        target["contract_version"] = "adapter-contract-v0"

                    self.assertIn(
                        "ADAPTER_SCHEMA_INVALID",
                        document_diagnostic_codes(document),
                    )

    def test_public_sequence_validation_rejects_non_json_numbers(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                document = apply_sequence_document(valid_sequence())
                document["sequence"]["planned_action"]["record"]["ordinal"] = value

                self.assertIn(
                    "ADAPTER_SCHEMA_INVALID",
                    document_diagnostic_codes(document),
                )

    def test_public_sequence_validation_requires_utc_z_timestamps(self) -> None:
        locations = (
            ("pre_state_observation", "observed_at"),
            ("mutation_receipt", "started_at"),
            ("mutation_receipt", "finished_at"),
            ("post_state_observation", "observed_at"),
        )
        for record_name, field in locations:
            with self.subTest(record_name=record_name, field=field):
                document = apply_sequence_document(valid_sequence())
                document["sequence"][record_name]["record"][field] = (
                    "2026-08-12T15:00:00+00:00"
                )

                self.assertIn(
                    "ADAPTER_SCHEMA_INVALID",
                    document_diagnostic_codes(document),
                )

    def test_schema_is_valid_draft_2020_12(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(
            schema["$id"],
            "https://nisavid.github.io/dotfiles/agent-equipment/adapter-contract-v1.schema.json",
        )
        result = run_check_jsonschema("--check-metaschema", str(SCHEMA))

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_valid_records_satisfy_the_closed_contract(self) -> None:
        fixtures = sorted(FIXTURES.glob("valid-adapter-*.json"))
        self.assertTrue(fixtures, "adapter contract needs valid record fixtures")

        result = run_check_jsonschema(
            "--schemafile",
            str(SCHEMA),
            *(str(path) for path in fixtures),
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_execution_record_requires_installed_implementation_manifest_digest(
        self,
    ) -> None:
        document = load_document("valid-adapter-observe-request.json")
        document["record"].pop("implementation_manifest_digest")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing-implementation-manifest.json"
            write_document(path, document)
            result = run_check_jsonschema(
                "--schemafile",
                str(SCHEMA),
                str(path),
            )

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)

    def test_runtime_observation_embeds_one_canonical_normalized_state_payload(
        self,
    ) -> None:
        document = load_document("valid-adapter-runtime-observation.json")
        result_record = document["record"]["result"]
        normalized_state = result_record["normalized_state"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "normalized-observation.json"
            write_document(path, document)
            result = run_check_jsonschema(
                "--schemafile",
                str(SCHEMA),
                str(path),
            )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(
            canonical_digest(normalized_state),
            result_record["state_digest"],
        )

    def test_valid_apply_sequence_satisfies_the_closed_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "valid-apply-sequence.json"
            write_document(path, apply_sequence_document(valid_sequence()))
            result = run_check_jsonschema(
                "--schemafile",
                str(SCHEMA),
                str(path),
            )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_normalized_state_requires_one_closed_immutable_content_tag(self) -> None:
        cases = []
        missing = apply_sequence_document(valid_sequence())
        missing["sequence"]["pre_state_observation"]["record"]["result"][
            "normalized_state"
        ].pop("immutable_content")
        cases.append(missing)

        partial = apply_sequence_document(valid_sequence())
        partial["sequence"]["pre_state_observation"]["record"]["result"][
            "normalized_state"
        ]["immutable_content"] = {
            "status": "observed",
            "revision": IMMUTABLE_REVISION,
        }
        cases.append(partial)

        for document in cases:
            with self.subTest(document=document):
                self.assertIn(
                    "ADAPTER_SCHEMA_INVALID",
                    document_diagnostic_codes(document),
                )

    def test_immutable_route_admits_exact_and_truthfully_unknown_prestate(self) -> None:
        exact = apply_sequence_document(immutable_sequence())
        self.assertEqual((), validate_adapter_sequence(exact))

        for route_presence, immutable_content in (
            ("present", {"status": "unknown"}),
            ("absent", {"status": "route_absent"}),
            ("partial", {"status": "unknown"}),
            ("unknown", {"status": "unknown"}),
        ):
            with self.subTest(route_presence=route_presence):
                document = apply_sequence_document(immutable_sequence())
                pre_state = copy.deepcopy(
                    document["sequence"]["authority"]["captured_pre_state"]
                )
                pre_state["route_presence"] = route_presence
                pre_state["immutable_content"] = immutable_content
                replace_pre_state(document, pre_state)

                self.assertEqual((), validate_adapter_sequence(document))

    def test_restore_classes_reject_crossed_observation_tags(self) -> None:
        immutable_crossings = (
            ("immutable_content", {"status": "not_applicable"}),
            ("observed_version", {"status": "observed", "value": "1.2.3"}),
            (
                "manager_drift",
                {
                    "status": "none",
                    "reviewed_baseline": "1.2.3",
                    "observation_source": "manager --version",
                },
            ),
        )
        for field, value in immutable_crossings:
            with self.subTest(restore_class="immutable", field=field):
                document = apply_sequence_document(immutable_sequence())
                pre_state = copy.deepcopy(
                    document["sequence"]["authority"]["captured_pre_state"]
                )
                pre_state[field] = value
                replace_pre_state(document, pre_state)
                self.assertIn(
                    "RESTORE_OBSERVATION_CLASS_MISMATCH",
                    document_diagnostic_codes(document),
                )

        for field, value in (
            (
                "immutable_content",
                {
                    "status": "observed",
                    "revision": IMMUTABLE_REVISION,
                    "content_digest": IMMUTABLE_CONTENT_DIGEST,
                },
            ),
            ("observed_version", {"status": "not_applicable"}),
        ):
            with self.subTest(restore_class="native_rolling", field=field):
                document = apply_sequence_document(valid_sequence())
                pre_state = copy.deepcopy(
                    document["sequence"]["authority"]["captured_pre_state"]
                )
                pre_state[field] = value
                replace_pre_state(document, pre_state)
                self.assertIn(
                    "RESTORE_OBSERVATION_CLASS_MISMATCH",
                    document_diagnostic_codes(document),
                )

    def test_immutable_observation_presence_tags_must_cohere(self) -> None:
        cases = (
            ("present", {"status": "route_absent"}),
            ("absent", {"status": "unknown"}),
            (
                "partial",
                {
                    "status": "observed",
                    "revision": IMMUTABLE_REVISION,
                    "content_digest": IMMUTABLE_CONTENT_DIGEST,
                },
            ),
            ("unknown", {"status": "route_absent"}),
        )
        for route_presence, immutable_content in cases:
            with self.subTest(route_presence=route_presence):
                document = apply_sequence_document(immutable_sequence())
                pre_state = copy.deepcopy(
                    document["sequence"]["authority"]["captured_pre_state"]
                )
                pre_state["route_presence"] = route_presence
                pre_state["immutable_content"] = immutable_content
                replace_pre_state(document, pre_state)
                self.assertIn(
                    "ADAPTER_SCHEMA_INVALID",
                    document_diagnostic_codes(document),
                )

    def test_absent_observed_version_requires_an_absent_route(self) -> None:
        for route_presence in ("present", "partial", "unknown"):
            with self.subTest(route_presence=route_presence):
                document = apply_sequence_document(valid_sequence())
                pre_state = copy.deepcopy(
                    document["sequence"]["authority"]["captured_pre_state"]
                )
                pre_state["route_presence"] = route_presence
                pre_state["observed_version"] = {"status": "route_absent"}
                replace_pre_state(document, pre_state)

                self.assertIn(
                    "ADAPTER_SCHEMA_INVALID",
                    document_diagnostic_codes(document),
                )

    def test_immutable_route_capability_must_advertise_content_observation(
        self,
    ) -> None:
        sequence = immutable_sequence()
        capability = capability_record(sequence[0])
        capability["operation_support"]["inspect"]["normalized_fields"].remove(
            "immutable_content"
        )
        rebind_capability_digest(sequence)

        self.assertIn(
            "IMMUTABLE_CONTENT_CAPABILITY_MISMATCH",
            diagnostic_codes(tuple(sequence)),
        )

    def test_verified_immutable_post_state_binds_revision_and_content_digest(
        self,
    ) -> None:
        for field, value in (
            ("revision", "f" * 40),
            ("content_digest", "sha256:" + "f" * 64),
        ):
            with self.subTest(field=field):
                document = apply_sequence_document(immutable_sequence())
                post_state = copy.deepcopy(
                    document["sequence"]["authority"]["expected_post_state"]
                )
                post_state["immutable_content"][field] = value
                replace_verified_post_state(document, post_state)

                self.assertIn(
                    "IMMUTABLE_CONTENT_BINDING_MISMATCH",
                    document_diagnostic_codes(document),
                )

    def test_planned_action_identity_uses_the_canonical_digest_vocabulary(self) -> None:
        document = load_document("valid-adapter-planned-action.json")
        document["record"]["action_identity"] = "action:install-arbitrary"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-action-identity.json"
            write_document(path, document)
            result = run_check_jsonschema(
                "--schemafile",
                str(SCHEMA),
                str(path),
            )

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)

    def test_capability_provider_harness_and_manager_evidence_are_bound(self) -> None:
        cases = (
            (
                "claude-native",
                "claude",
                {"kind": "native_plugin", "manager": "claude", "scope": "user"},
                "claude",
                True,
            ),
            (
                "codex-native",
                "codex",
                {"kind": "native_plugin", "manager": "codex", "scope": "user"},
                "codex",
                True,
            ),
            (
                "cursor-native",
                "cursor",
                {"kind": "native_plugin", "manager": "cursor", "scope": "user"},
                "cursor",
                True,
            ),
            (
                "claude-mcp",
                "claude",
                {
                    "kind": "direct_mcp",
                    "transport": "stdio",
                    "overlay_family": "claude_json",
                },
                "direct_mcp",
                True,
            ),
            (
                "codex-mcp",
                "codex",
                {
                    "kind": "direct_mcp",
                    "transport": "stdio",
                    "overlay_family": "codex_toml",
                },
                "direct_mcp",
                True,
            ),
            (
                "cursor-mcp",
                "cursor",
                {
                    "kind": "direct_mcp",
                    "transport": "stdio",
                    "overlay_family": "cursor_json",
                },
                "direct_mcp",
                True,
            ),
            (
                "standalone",
                "claude",
                {"kind": "standalone_skill", "canonical_root": "agents_skills"},
                "standalone_skills",
                True,
            ),
            (
                "wrong-native-manager",
                "claude",
                {"kind": "native_plugin", "manager": "claude", "scope": "user"},
                "codex",
                False,
            ),
            (
                "wrong-native-harness",
                "codex",
                {"kind": "native_plugin", "manager": "claude", "scope": "user"},
                "claude",
                False,
            ),
            (
                "wrong-mcp-overlay",
                "claude",
                {
                    "kind": "direct_mcp",
                    "transport": "stdio",
                    "overlay_family": "codex_toml",
                },
                "direct_mcp",
                False,
            ),
            (
                "wrong-standalone-manager",
                "cursor",
                {"kind": "standalone_skill", "canonical_root": "agents_skills"},
                "cursor",
                False,
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            for name, harness, provider, manager, valid in cases:
                with self.subTest(name=name):
                    document = load_document("valid-adapter-capability-record.json")
                    capability = capability_record(document)
                    capability["harness"] = harness
                    capability["provider_match"] = provider
                    capability["manager_version_evidence"]["manager"] = manager
                    path = Path(directory) / f"{name}.json"
                    write_document(path, document)
                    result = run_check_jsonschema(
                        "--schemafile",
                        str(SCHEMA),
                        str(path),
                    )
                    self.assertEqual(
                        0 if valid else 1,
                        result.returncode,
                        result.stdout + result.stderr,
                    )

    def test_invalid_records_fail_closed(self) -> None:
        fixtures = sorted(FIXTURES.glob("invalid-adapter-*.json"))
        self.assertTrue(fixtures, "adapter contract needs invalid record fixtures")

        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                result = run_check_jsonschema(
                    "--schemafile",
                    str(SCHEMA),
                    str(fixture),
                )
                self.assertEqual(
                    1,
                    result.returncode,
                    result.stdout + result.stderr,
                )

    def test_named_invalid_runtime_observations_have_only_the_named_defect(
        self,
    ) -> None:
        misnamed = load_document("invalid-adapter-misnamed-native-update-state.json")
        normalized_state = misnamed["record"]["result"]["normalized_state"]
        normalized_state["native_update_suppression_state"] = normalized_state.pop(
            "native_update_state"
        )
        self.assertTrue(CONTRACT._matches_checked_in_adapter_schema(misnamed))

        missing_binding = load_document(
            "invalid-adapter-missing-manager-version-binding.json"
        )
        missing_binding["record"]["manager_version_evidence_digest"] = (
            "sha256:" + "e" * 64
        )
        self.assertTrue(CONTRACT._matches_checked_in_adapter_schema(missing_binding))

    def test_valid_sequence_has_canonical_embedded_payload_digests_and_exact_bindings(
        self,
    ) -> None:
        self.assertEqual(
            (),
            validate_adapter_sequence(apply_sequence_document(valid_sequence())),
        )

    def test_sequence_rejects_incomplete_normalized_component_identity(self) -> None:
        document = apply_sequence_document(valid_sequence())
        document["sequence"]["pre_state_observation"]["record"]["result"][
            "normalized_state"
        ]["component_states"].append(
            {"equipment_identity": "plugin:", "state": "enabled"}
        )

        self.assertEqual(
            document_diagnostic_codes(document),
            {"ADAPTER_SCHEMA_INVALID"},
        )

    def test_individual_record_does_not_grant_mutation_authority(self) -> None:
        self.assertEqual(
            {"APPLY_SEQUENCE_INVALID"},
            document_diagnostic_codes(valid_sequence()[3]),
        )

    def test_apply_sequence_rejects_coordinated_authority_counterexamples(self) -> None:
        mismatched_digest = "sha256:" + "0" * 64
        cases: list[tuple[str, str, dict[str, object]]] = []

        non_apply = apply_sequence_document(valid_sequence())
        non_apply["sequence"]["authority"]["command"] = "audit"
        non_apply["sequence"]["authority"]["purpose"] = "inventory"
        non_apply["sequence"]["pre_state_request"]["record"]["command"] = "audit"
        non_apply["sequence"]["pre_state_request"]["record"]["purpose"] = "inventory"
        cases.append(("non-apply command", "ADAPTER_SCHEMA_INVALID", non_apply))

        changed_pre_state = apply_sequence_document(valid_sequence())
        changed_pre_state["sequence"]["authority"]["expected_pre_state_digest"] = (
            mismatched_digest
        )
        receipt_result = changed_pre_state["sequence"]["mutation_receipt"]["record"][
            "result"
        ]
        receipt_result["expected_pre_state_digest"] = mismatched_digest
        receipt_result["observed_pre_state_digest"] = mismatched_digest
        cases.append(
            (
                "coordinated pre-state rewrite",
                "CAPTURE_BINDING_MISMATCH",
                changed_pre_state,
            )
        )

        changed_post_state = apply_sequence_document(valid_sequence())
        changed_post_state["sequence"]["authority"]["expected_post_state_digest"] = (
            mismatched_digest
        )
        changed_post_state["sequence"]["post_state_request"]["record"][
            "expected_state_digest"
        ] = mismatched_digest
        changed_post_state["sequence"]["post_state_observation"]["record"]["result"][
            "state_digest"
        ] = mismatched_digest
        changed_post_state["sequence"]["post_state_observation"]["record"]["result"][
            "normalized_state"
        ]["enablement"] = "disabled"
        changed_post_state["sequence"]["authority"]["expected_post_state"][
            "enablement"
        ] = "disabled"
        coordinated_post_digest = canonical_digest(
            changed_post_state["sequence"]["authority"]["expected_post_state"]
        )
        for target in (
            changed_post_state["sequence"]["authority"],
            changed_post_state["sequence"]["post_state_request"]["record"],
        ):
            target[
                "expected_post_state_digest"
                if "phase" in target
                else "expected_state_digest"
            ] = coordinated_post_digest
        changed_post_state["sequence"]["authority"]["forward_post_state_digest"] = (
            coordinated_post_digest
        )
        changed_post_state["sequence"]["post_state_observation"]["record"]["result"][
            "state_digest"
        ] = coordinated_post_digest
        receipt_result = changed_post_state["sequence"]["mutation_receipt"]["record"][
            "result"
        ]
        receipt_result["expected_post_state_digest"] = coordinated_post_digest
        receipt_result["observed_post_state_digest"] = coordinated_post_digest
        receipt_result["compensation_evidence"]["expected_post_state_digest"] = (
            coordinated_post_digest
        )
        cases.append(
            (
                "coordinated verification rewrite",
                "VERIFIED_STATE_FRAGMENT_MISMATCH",
                changed_post_state,
            )
        )

        update_mismatch = apply_sequence_document(valid_sequence())
        for observation_name in ("pre_state_observation", "post_state_observation"):
            normalized_state = update_mismatch["sequence"][observation_name]["record"][
                "result"
            ]["normalized_state"]
            normalized_state["native_update_control"] = "not_applicable"
            normalized_state["native_update_suppression_state"] = "not_applicable"
        cases.append(
            (
                "native-update classification",
                "NATIVE_UPDATE_CLASSIFICATION_MISMATCH",
                update_mismatch,
            )
        )

        missing_observation_coverage = apply_sequence_document(valid_sequence())
        for observation_name in ("pre_state_observation", "post_state_observation"):
            result = missing_observation_coverage["sequence"][observation_name][
                "record"
            ]["result"]
            result["normalized_state"]["component_states"] = []
            result["surface_evidence"] = []
        cases.append(
            (
                "empty observation coverage",
                "OBSERVATION_COVERAGE_MISMATCH",
                missing_observation_coverage,
            )
        )

        wrong_observation_evidence_kind = apply_sequence_document(valid_sequence())
        wrong_observation_evidence_kind["sequence"]["post_state_observation"]["record"][
            "result"
        ]["surface_evidence"][0]["kind"] = "checkpoint"
        cases.append(
            (
                "observation evidence kind",
                "ADAPTER_SCHEMA_INVALID",
                wrong_observation_evidence_kind,
            )
        )

        wrong_mutation_evidence_kind = apply_sequence_document(valid_sequence())
        wrong_mutation_evidence_kind["sequence"]["mutation_receipt"]["record"][
            "result"
        ]["surface_evidence"][0]["kind"] = "manager"
        cases.append(
            (
                "mutation evidence kind",
                "ADAPTER_SCHEMA_INVALID",
                wrong_mutation_evidence_kind,
            )
        )

        changed_compensation_capture = apply_sequence_document(valid_sequence())
        changed_compensation_capture["sequence"]["mutation_receipt"]["record"][
            "result"
        ]["compensation_evidence"]["captured_state_digest"] = mismatched_digest
        cases.append(
            (
                "compensation capture",
                "COMPENSATION_BINDING_MISMATCH",
                changed_compensation_capture,
            )
        )

        changed_checkpoint = apply_sequence_document(valid_sequence())
        changed_checkpoint["sequence"]["mutation_receipt"]["record"][
            "prepared_checkpoint_reference"
        ] = "checkpoint:unbound"
        cases.append(
            (
                "prepared checkpoint",
                "CHECKPOINT_BINDING_MISMATCH",
                changed_checkpoint,
            )
        )

        failed_mutation = apply_sequence_document(valid_sequence())
        failed_mutation["sequence"]["mutation_receipt"]["record"]["result"] = {
            "status": "error",
            "code": "NATIVE_FAILURE",
            "classification": "native_failure",
            "message": "redacted mutation failure",
            "retry": "after_audit",
            "mutation_state": "unknown",
            "evidence_references": [],
        }
        cases.append(
            (
                "failed mutation",
                "MUTATION_NOT_SUCCESSFUL",
                failed_mutation,
            )
        )

        coordinated_compensation_guard = valid_compensation_sequence_document()
        coordinated_compensation_guard["sequence"]["authority"][
            "expected_pre_state_digest"
        ] = mismatched_digest
        coordinated_compensation_guard["sequence"]["pre_state_request"]["record"][
            "expected_state_digest"
        ] = mismatched_digest
        coordinated_compensation_guard["sequence"]["pre_state_observation"]["record"][
            "result"
        ]["state_digest"] = mismatched_digest
        compensation_result = coordinated_compensation_guard["sequence"][
            "mutation_receipt"
        ]["record"]["result"]
        compensation_result["expected_pre_state_digest"] = mismatched_digest
        compensation_result["observed_pre_state_digest"] = mismatched_digest
        cases.append(
            (
                "coordinated compensation guard rewrite",
                "COMPENSATION_GUARD_MISMATCH",
                coordinated_compensation_guard,
            )
        )

        for label, expected_code, document in cases:
            with self.subTest(label=label):
                self.assertIn(expected_code, document_diagnostic_codes(document))

    def test_apply_sequence_recomputes_action_identity_coordinates(self) -> None:
        coordinated_identity = list(copy.deepcopy(valid_sequence()))
        forged_identity = "action:sha256:" + "0" * 64
        coordinated_identity[3]["record"]["action_identity"] = forged_identity
        coordinated_identity[4]["record"]["action_identity"] = forged_identity

        coordinated_ordinal = list(copy.deepcopy(valid_sequence()))
        coordinated_ordinal[3]["record"]["ordinal"] = 99
        coordinated_ordinal[4]["record"]["ordinal"] = 99

        for label, sequence in (
            ("coordinated action identity", coordinated_identity),
            ("coordinated ordinal", coordinated_ordinal),
        ):
            with self.subTest(label=label):
                self.assertIn(
                    "ACTION_IDENTITY_MISMATCH",
                    diagnostic_codes(tuple(sequence)),
                )

    def test_apply_sequence_rejects_desired_fragment_digest_as_full_state_digest(
        self,
    ) -> None:
        document = apply_sequence_document(valid_sequence())
        partial_digest = document["sequence"]["planned_action"]["record"][
            "desired_state_digest"
        ]
        authority = document["sequence"]["authority"]
        authority["expected_post_state_digest"] = partial_digest
        authority["forward_post_state_digest"] = partial_digest
        document["sequence"]["post_state_request"]["record"][
            "expected_state_digest"
        ] = partial_digest
        document["sequence"]["post_state_observation"]["record"]["result"][
            "state_digest"
        ] = partial_digest
        receipt_result = document["sequence"]["mutation_receipt"]["record"]["result"]
        receipt_result["expected_post_state_digest"] = partial_digest
        receipt_result["observed_post_state_digest"] = partial_digest
        receipt_result["compensation_evidence"]["expected_post_state_digest"] = (
            partial_digest
        )

        self.assertIn(
            "CANONICAL_STATE_DIGEST_MISMATCH",
            document_diagnostic_codes(document),
        )

    def test_apply_sequence_rejects_noncanonical_pre_capture_state_digest(self) -> None:
        document = apply_sequence_document(valid_sequence())
        pre_result = document["sequence"]["pre_state_observation"]["record"]["result"]
        pre_result["normalized_state"]["observed_version"]["value"] = "9.9.9"

        self.assertIn(
            "CANONICAL_STATE_DIGEST_MISMATCH",
            document_diagnostic_codes(document),
        )

    def test_observation_component_states_are_exact_selected_controls(self) -> None:
        base = list(copy.deepcopy(valid_sequence()))
        self.assertEqual(
            [],
            base[2]["record"]["result"]["normalized_state"]["component_states"],
        )
        base[2]["record"]["result"]["normalized_state"]["component_states"] = [
            {
                "equipment_identity": "plugin:mattpocock/claude",
                "state": "enabled",
            }
        ]
        pre_digest = set_normalized_state(
            base[2]["record"]["result"],
            base[2]["record"]["result"]["normalized_state"],
        )
        base[4]["record"]["result"]["expected_pre_state_digest"] = pre_digest
        base[4]["record"]["result"]["observed_pre_state_digest"] = pre_digest

        self.assertIn(
            "OBSERVATION_COVERAGE_MISMATCH",
            diagnostic_codes(tuple(base)),
        )

    def test_codex_github_no_provider_skill_is_controlled_but_not_active(self) -> None:
        catalog = json.loads(PROPOSED_CATALOG.read_text(encoding="utf-8"))
        github_template = next(
            template
            for template in catalog["coverage_templates"]
            if template["identity"] == "template:github/codex-plugin"
        )
        route = copy.deepcopy(
            github_template["record"]["provider_selection"]["routes"][0]
        )
        yeet_equipment = next(
            equipment
            for equipment in catalog["equipment"]
            if equipment["identity"] == "skill:github/yeet"
        )
        omission_template_identity = yeet_equipment["coverage"]["codex"]["template"]
        omission_template = next(
            template
            for template in catalog["coverage_templates"]
            if template["identity"] == omission_template_identity
        )
        self.assertEqual("intentional_omission", omission_template["record"]["outcome"])
        self.assertEqual(
            "no_provider", omission_template["record"]["provider_selection"]
        )

        sequence = list(copy.deepcopy(valid_sequence()))
        controls = copy.deepcopy(route["component_controls"])
        controlled = sorted(control["equipment_identity"] for control in controls)
        active = sorted(
            {
                "plugin:github/codex",
                *(
                    identity
                    for identity in controlled
                    if identity != "skill:github/yeet"
                ),
            }
        )
        self.assertNotIn("skill:github/yeet", active)
        self.assertIn("skill:github/yeet", controlled)

        capability = capability_record(sequence[0])
        capability.update(
            {
                "capability_identity": "capability:codex-native-plugin-v1",
                "adapter_identity": "adapter:codex-native-plugin",
                "harness": "codex",
                "provider_match": {
                    "kind": "native_plugin",
                    "manager": "codex",
                    "scope": "user",
                },
            }
        )
        evidence = capability["manager_version_evidence"]
        evidence.update(
            {
                "manager": "codex",
                "manager_version": "0.147.0",
                "observation_source": "codex --version",
            }
        )
        evidence_without_digest = copy.deepcopy(evidence)
        evidence_without_digest.pop("evidence_digest")
        evidence["evidence_digest"] = canonical_digest(evidence_without_digest)
        support = capability["component_control_support"]
        support.update(
            {
                "mode": "automated",
                "supported_equipment_identities": controlled,
                "supported_states": ["enabled", "disabled"],
                "mutation_boundary": "selected_component",
            }
        )
        capability["native_update_support"].update(
            {
                "native_update_control": "unknown",
                "suppression": {"mode": "unavailable"},
                "suppression_scope": "none",
            }
        )
        capability["operation_support"]["suppress_native_update"] = {
            "mode": "unavailable"
        }

        for index in (1, 3):
            sequence[index]["record"]["route_record"] = copy.deepcopy(route)
        for index in (1, 2, 3, 4):
            record = sequence[index]["record"]
            record["capability_identity"] = capability["capability_identity"]
            record["manager_version_evidence_digest"] = evidence["evidence_digest"]
            record["harness"] = "codex"
            record["route_identity"] = route["identity"]
            record["activation_group"] = route["activation_group"]
            record["equipment_identities"] = copy.deepcopy(active)
        sequence[3]["record"]["adapter_identity"] = capability["adapter_identity"]
        sequence[4]["record"]["adapter_identity"] = capability["adapter_identity"]
        sequence[3]["record"]["preconditions"]["adapter_identity"] = capability[
            "adapter_identity"
        ]
        sequence[3]["record"]["preconditions"]["activation_group"] = route[
            "activation_group"
        ]
        sequence[3]["record"]["preconditions"]["manager_version_evidence_digest"] = (
            evidence["evidence_digest"]
        )
        rebind_route_digest(sequence)
        normalized_state = sequence[2]["record"]["result"]["normalized_state"]
        normalized_state["component_states"] = sorted(
            copy.deepcopy(controls), key=lambda control: control["equipment_identity"]
        )
        normalized_state["native_update_control"] = "unknown"
        normalized_state["native_update_suppression_state"] = "unavailable"
        pre_digest = set_normalized_state(
            sequence[2]["record"]["result"], normalized_state
        )
        sequence[4]["record"]["result"]["expected_pre_state_digest"] = pre_digest
        sequence[4]["record"]["result"]["observed_pre_state_digest"] = pre_digest
        sequence[3]["record"]["desired_state"]["component_states"] = sorted(
            copy.deepcopy(controls), key=lambda control: control["equipment_identity"]
        )
        rebind_desired_state(sequence)
        rebind_capability_digest(sequence)
        scope = [
            f"surface:{route['identity']}/{identity}"
            for identity in sorted(set(active + controlled))
        ]
        rebind_surface_scope(sequence, scope)

        self.assertEqual(
            (),
            validate_adapter_sequence(apply_sequence_document(sequence)),
        )

    def test_sequence_rejects_coordinated_provider_manager_substitution(self) -> None:
        sequence = list(copy.deepcopy(valid_sequence()))
        capability = capability_record(sequence[0])
        evidence = capability["manager_version_evidence"]
        evidence["manager"] = "direct_mcp"
        evidence_without_digest = copy.deepcopy(evidence)
        evidence_without_digest.pop("evidence_digest")
        evidence["evidence_digest"] = canonical_digest(evidence_without_digest)
        rebind_capability_digest(sequence)
        for index in (1, 2, 3, 4):
            sequence[index]["record"]["manager_version_evidence_digest"] = evidence[
                "evidence_digest"
            ]
        sequence[3]["record"]["preconditions"]["manager_version_evidence_digest"] = (
            evidence["evidence_digest"]
        )

        self.assertIn(
            "ADAPTER_SCHEMA_INVALID",
            diagnostic_codes(tuple(sequence)),
        )

    def test_apply_sequence_uses_distinct_observation_request_identities(self) -> None:
        document = apply_sequence_document(valid_sequence())
        pre_identity = document["sequence"]["pre_state_request"]["record"][
            "request_identity"
        ]
        document["sequence"]["post_state_request"]["record"]["request_identity"] = (
            pre_identity
        )
        document["sequence"]["post_state_observation"]["record"]["request_identity"] = (
            pre_identity
        )

        self.assertIn(
            "REQUEST_IDENTITY_REUSE",
            document_diagnostic_codes(document),
        )

    def test_apply_sequence_rejects_receipt_finished_before_started(self) -> None:
        document = apply_sequence_document(valid_sequence())
        receipt = document["sequence"]["mutation_receipt"]["record"]
        receipt["started_at"] = "2026-08-12T15:00:02Z"
        receipt["finished_at"] = "2026-08-12T15:00:01Z"

        self.assertIn(
            "TIMESTAMP_ORDER_INVALID",
            document_diagnostic_codes(document),
        )

    def test_apply_and_compensation_sequences_bind_observation_chronology(self) -> None:
        builders = (
            lambda: apply_sequence_document(valid_sequence()),
            valid_compensation_sequence_document,
        )
        mutations = (
            (
                lambda document: document["sequence"]["pre_state_observation"][
                    "record"
                ].__setitem__("observed_at", "2099-01-01T00:00:00Z"),
                "TIMESTAMP_ORDER_INVALID",
            ),
            (
                lambda document: document["sequence"]["post_state_observation"][
                    "record"
                ].__setitem__("observed_at", "2000-01-01T00:00:00Z"),
                "TIMESTAMP_ORDER_INVALID",
            ),
            (
                lambda document: document["sequence"]["post_state_observation"][
                    "record"
                ].__setitem__("observed_at", "2026-08-12T15:00:02"),
                "ADAPTER_SCHEMA_INVALID",
            ),
            (
                lambda document: document["sequence"]["pre_state_observation"][
                    "record"
                ].__setitem__("observed_at", "2026-08-12T15:00:00Z\n"),
                "ADAPTER_SCHEMA_INVALID",
            ),
        )
        for build in builders:
            for mutate, expected_code in mutations:
                with self.subTest(build=build, mutate=mutate):
                    document = build()
                    mutate(document)

                    self.assertIn(
                        expected_code,
                        document_diagnostic_codes(document),
                    )

    def test_sequence_chronology_accepts_the_schema_utc_domain(self) -> None:
        accepted_timelines = (
            (
                "0000-01-01T00:00:00Z",
                "0000-01-01T00:00:00.1Z",
                "0000-01-01T00:00:00.10Z",
                "0000-01-01T00:00:00.1001Z",
            ),
        )
        for build in (
            lambda: apply_sequence_document(valid_sequence()),
            valid_compensation_sequence_document,
        ):
            for timeline in accepted_timelines:
                with self.subTest(build=build, timeline=timeline):
                    document = build()
                    sequence = document["sequence"]
                    sequence["pre_state_observation"]["record"]["observed_at"] = (
                        timeline[0]
                    )
                    sequence["mutation_receipt"]["record"]["started_at"] = timeline[1]
                    sequence["mutation_receipt"]["record"]["finished_at"] = timeline[2]
                    sequence["post_state_observation"]["record"]["observed_at"] = (
                        timeline[3]
                    )

                    self.assertNotIn(
                        "TIMESTAMP_ORDER_INVALID",
                        document_diagnostic_codes(document),
                    )

    def test_sequence_chronology_preserves_arbitrary_fraction_precision(self) -> None:
        fraction_prefixes = ("000000", "0" * 5000)
        for fraction_prefix in fraction_prefixes:
            with self.subTest(fraction_digits=len(fraction_prefix) + 1):
                document = apply_sequence_document(valid_sequence())
                sequence = document["sequence"]
                sequence["pre_state_observation"]["record"]["observed_at"] = (
                    f"2026-08-12T15:00:01.{fraction_prefix}1Z"
                )
                sequence["mutation_receipt"]["record"]["started_at"] = (
                    f"2026-08-12T15:00:01.{fraction_prefix}3Z"
                )
                sequence["mutation_receipt"]["record"]["finished_at"] = (
                    f"2026-08-12T15:00:01.{fraction_prefix}2Z"
                )
                sequence["post_state_observation"]["record"]["observed_at"] = (
                    f"2026-08-12T15:00:01.{fraction_prefix}4Z"
                )

                self.assertIn(
                    "TIMESTAMP_ORDER_INVALID",
                    document_diagnostic_codes(document),
                )

    def test_apply_sequence_rejects_verification_of_a_different_route(self) -> None:
        document = apply_sequence_document(valid_sequence())
        post_request = document["sequence"]["post_state_request"]["record"]
        post_observation = document["sequence"]["post_state_observation"]["record"]
        route_record = post_request["route_record"]
        route_record["identity"] = "route:claude/unrelated-plugin"
        route_record["activation_group"] = "activation:claude/unrelated-plugin"
        route_digest = canonical_digest(route_record)
        surface_scope = [
            "surface:route:claude/unrelated-plugin/plugin:mattpocock/claude"
        ]
        for record in (post_request, post_observation):
            record["route_identity"] = route_record["identity"]
            record["route_digest"] = route_digest
            record["activation_group"] = route_record["activation_group"]
            record["surface_scope"] = copy.deepcopy(surface_scope)
        post_observation["result"]["surface_evidence"] = [
            {
                "kind": "manager",
                "identity": surface_scope[0],
                "digest": "sha256:" + "8" * 64,
            }
        ]

        self.assertIn(
            "AUTHORITY_BINDING_MISMATCH",
            document_diagnostic_codes(document),
        )

    def test_apply_sequence_rejects_explicit_post_state_conflicting_with_target(
        self,
    ) -> None:
        for field, value in (("route_presence", "absent"), ("enablement", "disabled")):
            with self.subTest(field=field):
                document = apply_sequence_document(valid_sequence())
                result = document["sequence"]["post_state_observation"]["record"][
                    "result"
                ]
                result["normalized_state"][field] = value
                self.assertIn(
                    "VERIFIED_STATE_FRAGMENT_MISMATCH",
                    document_diagnostic_codes(document),
                )

        sequence = list(copy.deepcopy(valid_sequence()))
        control = {
            "equipment_identity": "skill:verification-before-completion",
            "state": "disabled",
        }
        for index in (1, 3):
            sequence[index]["record"]["route_record"]["component_controls"] = [
                copy.deepcopy(control)
            ]
        rebind_route_digest(sequence)
        sequence[3]["record"]["desired_state"]["component_states"] = [
            copy.deepcopy(control)
        ]
        rebind_desired_state(sequence)
        equipment_identities = [
            "plugin:mattpocock/claude",
            "skill:verification-before-completion",
        ]
        for index in (1, 2, 3, 4):
            sequence[index]["record"]["equipment_identities"] = copy.deepcopy(
                equipment_identities
            )
        sequence[2]["record"]["result"]["normalized_state"]["component_states"].append(
            {
                "equipment_identity": control["equipment_identity"],
                "state": "enabled",
            }
        )
        set_normalized_state(
            sequence[2]["record"]["result"],
            sequence[2]["record"]["result"]["normalized_state"],
        )
        rebind_surface_scope(
            sequence,
            [
                f"surface:route:claude/mattpocock-plugin/{identity}"
                for identity in equipment_identities
            ],
        )
        support = capability_record(sequence[0])["component_control_support"]
        support["mode"] = "automated"
        support["mutation_boundary"] = "selected_component"
        rebind_capability_digest(sequence)
        document = apply_sequence_document(sequence)
        document["sequence"]["post_state_observation"]["record"]["result"][
            "normalized_state"
        ]["component_states"][0]["state"] = "enabled"

        self.assertIn(
            "VERIFIED_STATE_FRAGMENT_MISMATCH",
            document_diagnostic_codes(document),
        )

    def test_sequence_selects_the_request_bound_capability_from_plural_discovery(
        self,
    ) -> None:
        sequence = list(copy.deepcopy(valid_sequence()))
        append_unrelated_capability(sequence)

        self.assertEqual(
            (),
            validate_adapter_sequence(apply_sequence_document(sequence)),
        )

    def test_plural_discovery_validates_every_manager_evidence_digest(self) -> None:
        for selected in (True, False):
            with self.subTest(selected=selected):
                sequence = list(copy.deepcopy(valid_sequence()))
                unrelated = append_unrelated_capability(sequence)
                target = capability_record(sequence[0]) if selected else unrelated
                evidence = target["manager_version_evidence"]
                evidence["evidence_digest"] = "sha256:" + "0" * 64
                rehash_capability_record(target)

                self.assertIn(
                    "CANONICAL_DIGEST_MISMATCH",
                    diagnostic_codes(tuple(sequence)),
                )

    def test_plural_discovery_validates_every_capability_digest(self) -> None:
        for selected in (True, False):
            with self.subTest(selected=selected):
                sequence = list(copy.deepcopy(valid_sequence()))
                unrelated = append_unrelated_capability(sequence)
                target = capability_record(sequence[0]) if selected else unrelated
                target["capability_digest"] = "sha256:" + "0" * 64

                self.assertIn(
                    "CANONICAL_DIGEST_MISMATCH",
                    diagnostic_codes(tuple(sequence)),
                )

    def test_plural_discovery_rejects_surrogates_without_raising(self) -> None:
        for selected in (True, False):
            with self.subTest(selected=selected):
                sequence = list(copy.deepcopy(valid_sequence()))
                unrelated = append_unrelated_capability(sequence)
                target = capability_record(sequence[0]) if selected else unrelated
                target["adapter_version"] = "\ud800"

                self.assertEqual(
                    {"ADAPTER_SCHEMA_INVALID"},
                    diagnostic_codes(tuple(sequence)),
                )

    def test_sequence_rejects_uncanonicalizable_integer_without_raising(self) -> None:
        for record_type, record_index in (
            ("PlannedAction", 3),
            ("MutationReceipt", 4),
        ):
            with self.subTest(record_type=record_type):
                sequence = list(copy.deepcopy(valid_sequence()))
                sequence[record_index]["record"]["ordinal"] = 10**5000

                self.assertEqual(
                    {"ADAPTER_SCHEMA_INVALID"},
                    diagnostic_codes(tuple(sequence)),
                )

    def test_plural_discovery_requires_every_provider_manager_binding(self) -> None:
        for selected in (True, False):
            with self.subTest(selected=selected):
                sequence = list(copy.deepcopy(valid_sequence()))
                unrelated = append_unrelated_capability(sequence)
                target = capability_record(sequence[0]) if selected else unrelated
                evidence = target["manager_version_evidence"]
                evidence["manager"] = "direct_mcp"
                evidence_without_digest = copy.deepcopy(evidence)
                evidence_without_digest.pop("evidence_digest")
                evidence["evidence_digest"] = canonical_digest(evidence_without_digest)
                rehash_capability_record(target)

                self.assertEqual(
                    {"ADAPTER_SCHEMA_INVALID"},
                    diagnostic_codes(tuple(sequence)),
                )

    def test_capability_discovery_requires_canonical_record_order(self) -> None:
        sequence = list(copy.deepcopy(valid_sequence()))
        append_unrelated_capability(sequence)
        sequence[0]["result"]["records"].reverse()

        self.assertIn(
            "CAPABILITY_ORDER_INVALID",
            diagnostic_codes(tuple(sequence)),
        )

    def test_capability_discovery_requires_globally_unique_identities(self) -> None:
        for selected in (True, False):
            with self.subTest(selected=selected):
                sequence = list(copy.deepcopy(valid_sequence()))
                original = (
                    capability_record(sequence[0])
                    if selected
                    else append_unrelated_capability(sequence)
                )
                duplicate = copy.deepcopy(original)
                duplicate["adapter_version"] = "duplicate-fixture-version"
                rehash_capability_record(duplicate)
                sequence[0]["result"]["records"].append(duplicate)

                self.assertIn(
                    "DUPLICATE_CAPABILITY_IDENTITY",
                    diagnostic_codes(tuple(sequence)),
                )

    def test_capability_component_identity_support_is_canonically_sorted(
        self,
    ) -> None:
        for selected in (True, False):
            with self.subTest(selected=selected):
                sequence = list(copy.deepcopy(valid_sequence()))
                unrelated = append_unrelated_capability(sequence)
                target = capability_record(sequence[0]) if selected else unrelated
                support = target["component_control_support"]
                support["supported_equipment_identities"] = ["skill:z", "skill:a"]
                rehash_capability_record(target)

                self.assertIn(
                    "CAPABILITY_ORDER_INVALID",
                    diagnostic_codes(tuple(sequence)),
                )

    def test_sequence_rejects_missing_or_duplicate_request_bound_capability(
        self,
    ) -> None:
        for case in ("missing", "duplicate"):
            with self.subTest(case=case):
                sequence = list(copy.deepcopy(valid_sequence()))
                selected = capability_record(sequence[0])
                if case == "missing":
                    selected["capability_identity"] = "capability:unrelated"
                    selected_without_digest = copy.deepcopy(selected)
                    selected_without_digest.pop("capability_digest")
                    selected["capability_digest"] = canonical_digest(
                        selected_without_digest
                    )
                else:
                    duplicate = copy.deepcopy(selected)
                    duplicate["adapter_version"] = "1.0.1"
                    duplicate_without_digest = copy.deepcopy(duplicate)
                    duplicate_without_digest.pop("capability_digest")
                    duplicate["capability_digest"] = canonical_digest(
                        duplicate_without_digest
                    )
                    sequence[0]["result"]["records"].append(duplicate)

                self.assertIn(
                    "CAPABILITY_SELECTION_AMBIGUOUS",
                    diagnostic_codes(tuple(sequence)),
                )

    def test_sequence_rejects_each_request_observation_echo_mismatch(self) -> None:
        fields = (
            "request_identity",
            "correlation_identity",
            "candidate_identity",
            "implementation_manifest_digest",
            "catalog_digest",
            "lock_digest",
            "plan_digest",
            "capability_identity",
            "capability_digest",
            "manager_version_evidence_digest",
            "harness",
            "route_identity",
            "route_digest",
            "equipment_identities",
            "controlled_equipment_identities",
            "activation_group",
            "surface_scope",
        )
        for field in fields:
            with self.subTest(field=field):
                sequence = list(copy.deepcopy(valid_sequence()))
                current = sequence[2]["record"][field]
                sequence[2]["record"][field] = schema_valid_mismatch(field, current)
                self.assertIn(
                    "ECHO_BINDING_MISMATCH", diagnostic_codes(tuple(sequence))
                )

    def test_sequence_rejects_each_request_action_and_action_receipt_echo_mismatch(
        self,
    ) -> None:
        request_action_fields = (
            "correlation_identity",
            "candidate_identity",
            "implementation_manifest_digest",
            "catalog_digest",
            "lock_digest",
            "plan_digest",
            "capability_identity",
            "capability_digest",
            "manager_version_evidence_digest",
            "harness",
            "route_identity",
            "route_digest",
            "route_record",
            "equipment_identities",
            "controlled_equipment_identities",
            "activation_group",
            "surface_scope",
            "secret_references",
        )
        action_receipt_fields = (
            "action_identity",
            "correlation_identity",
            "ordinal",
            "candidate_identity",
            "implementation_manifest_digest",
            "catalog_digest",
            "lock_digest",
            "plan_digest",
            "capability_identity",
            "capability_digest",
            "manager_version_evidence_digest",
            "adapter_identity",
            "adapter_version",
            "harness",
            "route_identity",
            "route_digest",
            "equipment_identities",
            "controlled_equipment_identities",
            "activation_group",
            "surface_scope",
            "operation",
            "operation_disposition",
            "secret_references",
        )
        for index, fields in ((3, request_action_fields), (4, action_receipt_fields)):
            for field in fields:
                with self.subTest(record=index, field=field):
                    sequence = list(copy.deepcopy(valid_sequence()))
                    current = sequence[index]["record"][field]
                    if field == "operation_disposition":
                        sequence[index]["record"][field] = "operator_action"
                        expected_code = "ADAPTER_SCHEMA_INVALID"
                    else:
                        sequence[index]["record"][field] = schema_valid_mismatch(
                            field, current
                        )
                        expected_code = "ECHO_BINDING_MISMATCH"
                    self.assertIn(
                        expected_code,
                        diagnostic_codes(tuple(sequence)),
                    )

    def test_sequence_rejects_canonical_digest_and_action_precondition_mismatches(
        self,
    ) -> None:
        mutations = (
            (
                0,
                ("result", "records", 0, "manager_version_evidence", "evidence_digest"),
            ),
            (0, ("result", "records", 0, "capability_digest")),
            (1, ("record", "route_digest")),
            (3, ("record", "route_digest")),
            (3, ("record", "desired_state_digest")),
        )
        for index, path in mutations:
            with self.subTest(path=path):
                sequence = list(copy.deepcopy(valid_sequence()))
                target: object = sequence[index]
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = "sha256:" + "0" * 64
                self.assertIn(
                    "CANONICAL_DIGEST_MISMATCH",
                    diagnostic_codes(tuple(sequence)),
                )

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
            "control_owner",
            "activation_group",
            "surface_scope",
        ):
            with self.subTest(precondition=field):
                sequence = list(copy.deepcopy(valid_sequence()))
                current = sequence[3]["record"]["preconditions"][field]
                if field == "control_owner":
                    sequence[3]["record"]["preconditions"][field] = "operator_owned"
                    expected_code = "ADAPTER_SCHEMA_INVALID"
                else:
                    sequence[3]["record"]["preconditions"][field] = (
                        schema_valid_mismatch(field, current)
                    )
                    expected_code = "ECHO_BINDING_MISMATCH"
                self.assertIn(expected_code, diagnostic_codes(tuple(sequence)))

    def test_sequence_rejects_ok_state_and_compensation_restore_mismatches(
        self,
    ) -> None:
        for field in (
            "observed_pre_state_digest",
            "expected_post_state_digest",
            "observed_post_state_digest",
        ):
            with self.subTest(field=field):
                sequence = list(copy.deepcopy(valid_sequence()))
                sequence[4]["record"]["result"][field] = "sha256:" + "0" * 64
                expected_code = (
                    "PRE_STATE_MISMATCH"
                    if field.startswith("observed_pre")
                    else "POST_STATE_MISMATCH"
                )
                self.assertIn(expected_code, diagnostic_codes(tuple(sequence)))

        sequence = list(copy.deepcopy(valid_sequence()))
        receipt = sequence[4]["record"]
        receipt["phase"] = "compensate"
        compensation = receipt["result"]["compensation_evidence"]
        compensation.pop("expected_post_state_digest")
        compensation["status"] = "restored"
        compensation["restored_state_digest"] = "sha256:" + "0" * 64
        compensation["comparison"] = "equal"
        self.assertIn(
            "COMPENSATION_RESTORE_MISMATCH",
            diagnostic_codes(tuple(sequence)),
        )

    def test_sequence_accepts_compensation_restored_to_captured_pre_state(self) -> None:
        document = valid_compensation_sequence_document()

        self.assertEqual(
            (),
            validate_adapter_sequence(document),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "valid-compensation-sequence.json"
            write_document(path, document)
            result = run_check_jsonschema(
                "--schemafile",
                str(SCHEMA),
                str(path),
            )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_compensation_preserves_captured_immutable_content(self) -> None:
        document = valid_compensation_sequence_document(immutable_sequence())
        captured_state = copy.deepcopy(
            document["sequence"]["authority"]["captured_pre_state"]
        )
        captured_state["immutable_content"] = {
            "status": "observed",
            "revision": "a" * 40,
            "content_digest": "sha256:" + "a" * 64,
        }
        replace_compensation_restore_state(document, captured_state)

        self.assertEqual((), validate_adapter_sequence(document))

        mismatched = copy.deepcopy(document)
        restored_state = copy.deepcopy(
            mismatched["sequence"]["authority"]["expected_post_state"]
        )
        restored_state["immutable_content"]["content_digest"] = "sha256:" + "b" * 64
        result = mismatched["sequence"]["post_state_observation"]["record"]["result"]
        restored_digest = set_normalized_state(result, restored_state)
        mismatched["sequence"]["post_state_request"]["record"][
            "expected_state_digest"
        ] = restored_digest
        receipt_result = mismatched["sequence"]["mutation_receipt"]["record"]["result"]
        receipt_result["expected_post_state_digest"] = restored_digest
        receipt_result["observed_post_state_digest"] = restored_digest
        receipt_result["compensation_evidence"]["restored_state_digest"] = (
            restored_digest
        )
        mismatched["sequence"]["authority"]["expected_post_state"] = restored_state
        mismatched["sequence"]["authority"]["expected_post_state_digest"] = (
            restored_digest
        )

        self.assertIn(
            "COMPENSATION_RESTORE_MISMATCH",
            document_diagnostic_codes(mismatched),
        )

    def test_compensation_verified_state_mismatch_names_pre_state_observation(
        self,
    ) -> None:
        document = valid_compensation_sequence_document()
        document["sequence"]["pre_state_observation"]["record"]["result"][
            "normalized_state"
        ]["enablement"] = "disabled"

        mismatch = next(
            diagnostic
            for diagnostic in validate_adapter_sequence(document)
            if diagnostic.code == "VERIFIED_STATE_FRAGMENT_MISMATCH"
        )

        self.assertEqual(
            mismatch.path,
            "PreStateObservation.record.result.enablement",
        )

    def test_sequence_rejects_coordinated_route_record_binding_mismatches(self) -> None:
        cases = ("route_identity", "activation_group", "secret_references")
        for field in cases:
            with self.subTest(field=field):
                sequence = list(copy.deepcopy(valid_sequence()))
                mismatched = {
                    "route_identity": "route:claude/coordinated-mismatch",
                    "activation_group": "activation:claude/coordinated-mismatch",
                    "secret_references": [
                        {"kind": "environment_variable", "name": "MISMATCH_TOKEN"}
                    ],
                }[field]
                for index in (1, 3):
                    sequence[index]["record"][field] = mismatched
                if field != "secret_references":
                    sequence[2]["record"][field] = mismatched
                sequence[4]["record"][field] = mismatched
                if field == "activation_group":
                    sequence[3]["record"]["preconditions"][field] = mismatched
                self.assertIn(
                    "ROUTE_BINDING_MISMATCH",
                    diagnostic_codes(tuple(sequence)),
                )

    def test_sequence_rejects_coordinated_surface_scope_outside_capability_rule(
        self,
    ) -> None:
        sequence = list(copy.deepcopy(valid_sequence()))
        rebind_surface_scope(sequence, ["surface:route:claude/outside"])

        self.assertIn("SURFACE_SCOPE_MISMATCH", diagnostic_codes(tuple(sequence)))

    def test_sequence_accepts_each_surface_identity_rule(self) -> None:
        route_identity = "route:claude/mattpocock-plugin"
        equipment_identity = "plugin:mattpocock/claude"
        cases = (
            (
                "shared_equipment_identity",
                [f"surface:shared/{equipment_identity}"],
            ),
            (
                "route_and_equipment_identity",
                [f"surface:{route_identity}/{equipment_identity}"],
            ),
            ("route_identity", [f"surface:{route_identity}"]),
        )
        for rule, expected_scope in cases:
            with self.subTest(rule=rule):
                sequence = list(copy.deepcopy(valid_sequence()))
                capability_record(sequence[0])["surface_identity_rule"] = {
                    "rule": rule,
                    "version": 1,
                }
                rebind_capability_digest(sequence)
                rebind_surface_scope(sequence, expected_scope)

                self.assertEqual(
                    (),
                    validate_adapter_sequence(apply_sequence_document(sequence)),
                )

    def test_sequence_rejects_capability_route_provider_mismatch(self) -> None:
        sequence = list(copy.deepcopy(valid_sequence()))
        provider = {
            "kind": "direct_mcp",
            "server_name": "context7",
            "transport": "stdio",
            "command": "npx",
            "arguments": [
                {"literal": "-y"},
                {"literal": "@upstash/context7-mcp"},
            ],
        }
        for index in (1, 3):
            sequence[index]["record"]["route_record"]["provider"] = provider
        route_digest = canonical_digest(sequence[1]["record"]["route_record"])
        for index in (1, 2, 3, 4):
            sequence[index]["record"]["route_digest"] = route_digest
        sequence[3]["record"]["preconditions"]["route_digest"] = route_digest

        self.assertIn(
            "CAPABILITY_ROUTE_MISMATCH",
            diagnostic_codes(tuple(sequence)),
        )

    def test_sequence_accepts_each_capability_route_provider_family(self) -> None:
        cases = (
            (
                "standalone",
                {"kind": "standalone_skill", "canonical_root": "agents_skills"},
                "standalone_skills",
                {"kind": "standalone_skill", "canonical_root": "agents_skills"},
            ),
            (
                "native",
                {"kind": "native_plugin", "manager": "claude", "scope": "user"},
                "claude",
                {
                    "kind": "native_plugin",
                    "manager": "claude",
                    "plugin_id": "example@marketplace",
                    "scope": "user",
                },
            ),
            (
                "direct-mcp",
                {
                    "kind": "direct_mcp",
                    "transport": "stdio",
                    "overlay_family": "claude_json",
                },
                "direct_mcp",
                {
                    "kind": "direct_mcp",
                    "server_name": "context7",
                    "transport": "stdio",
                    "command": "npx",
                    "arguments": [
                        {"literal": "-y"},
                        {"literal": "@upstash/context7-mcp"},
                    ],
                },
            ),
        )
        for name, capability_provider, manager, route_provider in cases:
            with self.subTest(name=name):
                sequence = list(copy.deepcopy(valid_sequence()))
                rebind_sequence_provider(
                    sequence,
                    capability_provider,
                    manager,
                    route_provider,
                )
                self.assertEqual(
                    (),
                    validate_adapter_sequence(apply_sequence_document(sequence)),
                )

    def test_sequence_rejects_out_of_range_http_provider_ports(self) -> None:
        capability_provider = {
            "kind": "direct_mcp",
            "transport": "http",
            "overlay_family": "claude_json",
        }

        for port in (1, 443, 65535):
            with self.subTest(port=port, validity="valid"):
                sequence = list(copy.deepcopy(valid_sequence()))
                rebind_sequence_provider(
                    sequence,
                    capability_provider,
                    "direct_mcp",
                    {
                        "kind": "direct_mcp",
                        "server_name": "fixture",
                        "transport": "http",
                        "url": f"https://example.invalid:{port}/mcp",
                    },
                )

                self.assertEqual(
                    (),
                    validate_adapter_sequence(apply_sequence_document(sequence)),
                )

        for port in (0, 65536, 99999):
            with self.subTest(port=port, validity="invalid"):
                sequence = list(copy.deepcopy(valid_sequence()))
                rebind_sequence_provider(
                    sequence,
                    capability_provider,
                    "direct_mcp",
                    {
                        "kind": "direct_mcp",
                        "server_name": "fixture",
                        "transport": "http",
                        "url": f"https://example.invalid:{port}/mcp",
                    },
                )

                self.assertIn(
                    "PROVIDER_CONFIGURATION_INVALID",
                    document_diagnostic_codes(apply_sequence_document(sequence)),
                )

    def test_sequence_rejects_conflicting_component_states(self) -> None:
        for record_index in (2, 3):
            with self.subTest(record_index=record_index):
                sequence = list(copy.deepcopy(valid_sequence()))
                if record_index == 2:
                    component_states = sequence[2]["record"]["result"][
                        "normalized_state"
                    ]["component_states"]
                    component_states.extend(
                        [
                            {
                                "equipment_identity": "plugin:mattpocock/claude",
                                "state": "enabled",
                            },
                            {
                                "equipment_identity": "plugin:mattpocock/claude",
                                "state": "disabled",
                            },
                        ]
                    )
                else:
                    component_states = [
                        {
                            "equipment_identity": "plugin:mattpocock/claude",
                            "state": "enabled",
                        },
                        {
                            "equipment_identity": "plugin:mattpocock/claude",
                            "state": "disabled",
                        },
                    ]
                    sequence[3]["record"]["desired_state"]["component_states"] = (
                        component_states
                    )
                    sequence[3]["record"]["desired_state_digest"] = canonical_digest(
                        sequence[3]["record"]["desired_state"]
                    )
                    sequence[4]["record"]["result"]["expected_post_state_digest"] = (
                        sequence[3]["record"]["desired_state_digest"]
                    )
                    sequence[4]["record"]["result"]["observed_post_state_digest"] = (
                        sequence[3]["record"]["desired_state_digest"]
                    )
                    sequence[4]["record"]["result"]["compensation_evidence"][
                        "expected_post_state_digest"
                    ] = sequence[3]["record"]["desired_state_digest"]

                self.assertIn(
                    "COMPONENT_IDENTITY_CONFLICT",
                    diagnostic_codes(tuple(sequence)),
                )

    def test_sequence_rejects_unsupported_or_broadened_component_controls(self) -> None:
        cases = (
            (
                "outside-route",
                "skill:verification-before-completion",
                "enabled",
                None,
                "automated",
                ["enabled", "disabled"],
            ),
            (
                "route-state-mismatch",
                "skill:verification-before-completion",
                "disabled",
                "enabled",
                "automated",
                ["enabled", "disabled"],
            ),
            (
                "unsupported-identity",
                "skill:unapproved",
                "enabled",
                "enabled",
                "automated",
                ["enabled", "disabled"],
            ),
            (
                "unsupported-state",
                "skill:verification-before-completion",
                "disabled",
                "disabled",
                "automated",
                ["enabled"],
            ),
            (
                "non-automated-mode",
                "skill:verification-before-completion",
                "enabled",
                "enabled",
                "operator_action",
                ["enabled", "disabled"],
            ),
        )
        for case, identity, state, route_state, mode, supported_states in cases:
            with self.subTest(case=case):
                sequence = list(copy.deepcopy(valid_sequence()))
                control = {"equipment_identity": identity, "state": state}
                if case != "outside-route":
                    route_control = {
                        "equipment_identity": identity,
                        "state": route_state,
                    }
                    for index in (1, 3):
                        sequence[index]["record"]["route_record"][
                            "component_controls"
                        ] = [copy.deepcopy(route_control)]
                    rebind_route_digest(sequence)
                sequence[3]["record"]["desired_state"]["component_states"] = [
                    copy.deepcopy(control)
                ]
                rebind_desired_state(sequence)

                equipment_identities = sorted(["plugin:mattpocock/claude", identity])
                for index in (1, 2, 3, 4):
                    sequence[index]["record"]["equipment_identities"] = copy.deepcopy(
                        equipment_identities
                    )
                rebind_surface_scope(
                    sequence,
                    [
                        f"surface:route:claude/mattpocock-plugin/{item}"
                        for item in equipment_identities
                    ],
                )

                support = capability_record(sequence[0])["component_control_support"]
                support["mode"] = mode
                support["mutation_boundary"] = (
                    "selected_component" if mode == "automated" else "none"
                )
                support["supported_equipment_identities"] = [
                    "skill:verification-before-completion"
                ]
                support["supported_states"] = supported_states
                rebind_capability_digest(sequence)

                self.assertIn(
                    "COMPONENT_CONTROL_UNAUTHORIZED",
                    diagnostic_codes(tuple(sequence)),
                )

    def test_sequence_rejects_route_control_omitted_from_desired_state(self) -> None:
        sequence = list(copy.deepcopy(valid_sequence()))
        control = {
            "equipment_identity": "skill:verification-before-completion",
            "state": "disabled",
        }
        for index in (1, 3):
            sequence[index]["record"]["route_record"]["component_controls"] = [
                copy.deepcopy(control)
            ]
        rebind_route_digest(sequence)

        equipment_identities = [
            "plugin:mattpocock/claude",
            "skill:verification-before-completion",
        ]
        for index in (1, 2, 3, 4):
            sequence[index]["record"]["equipment_identities"] = copy.deepcopy(
                equipment_identities
            )
        sequence[2]["record"]["result"]["normalized_state"]["component_states"].append(
            copy.deepcopy(control)
        )
        pre_state_digest = set_normalized_state(
            sequence[2]["record"]["result"],
            sequence[2]["record"]["result"]["normalized_state"],
        )
        receipt_result = sequence[4]["record"]["result"]
        receipt_result["expected_pre_state_digest"] = pre_state_digest
        receipt_result["observed_pre_state_digest"] = pre_state_digest
        sequence[2]["record"]["result"]["surface_evidence"].append(
            {
                "kind": "manager",
                "identity": (
                    "surface:route:claude/mattpocock-plugin/"
                    "skill:verification-before-completion"
                ),
                "digest": "sha256:" + "6" * 64,
            }
        )
        sequence[4]["record"]["result"]["surface_evidence"].append(
            {
                "kind": "surface",
                "identity": (
                    "surface:route:claude/mattpocock-plugin/"
                    "skill:verification-before-completion"
                ),
                "digest": "sha256:" + "7" * 64,
            }
        )
        rebind_surface_scope(
            sequence,
            [
                f"surface:route:claude/mattpocock-plugin/{identity}"
                for identity in equipment_identities
            ],
        )

        self.assertIn(
            "COMPONENT_CONTROL_UNAUTHORIZED",
            diagnostic_codes(tuple(sequence)),
        )

    def test_sequence_accepts_exact_automated_component_control(self) -> None:
        sequence = list(copy.deepcopy(valid_sequence()))
        control = {
            "equipment_identity": "skill:verification-before-completion",
            "state": "disabled",
        }
        for index in (1, 3):
            sequence[index]["record"]["route_record"]["component_controls"] = [
                copy.deepcopy(control)
            ]
        rebind_route_digest(sequence)
        sequence[3]["record"]["desired_state"]["component_states"] = [
            copy.deepcopy(control)
        ]
        rebind_desired_state(sequence)
        equipment_identities = [
            "plugin:mattpocock/claude",
            "skill:verification-before-completion",
        ]
        for index in (1, 2, 3, 4):
            sequence[index]["record"]["equipment_identities"] = copy.deepcopy(
                equipment_identities
            )
        sequence[2]["record"]["result"]["normalized_state"]["component_states"].append(
            {
                "equipment_identity": control["equipment_identity"],
                "state": "enabled",
            }
        )
        pre_state_digest = set_normalized_state(
            sequence[2]["record"]["result"],
            sequence[2]["record"]["result"]["normalized_state"],
        )
        receipt_result = sequence[4]["record"]["result"]
        receipt_result["expected_pre_state_digest"] = pre_state_digest
        receipt_result["observed_pre_state_digest"] = pre_state_digest
        rebind_surface_scope(
            sequence,
            [
                f"surface:route:claude/mattpocock-plugin/{identity}"
                for identity in equipment_identities
            ],
        )
        support = capability_record(sequence[0])["component_control_support"]
        support["mode"] = "automated"
        support["mutation_boundary"] = "selected_component"
        rebind_capability_digest(sequence)

        self.assertEqual(
            (),
            validate_adapter_sequence(apply_sequence_document(sequence)),
        )

    def test_sequence_rejects_missing_unknown_and_inspect_actions(self) -> None:
        for operation in (None, "unknown", "inspect"):
            with self.subTest(operation=operation):
                sequence = list(copy.deepcopy(valid_sequence()))
                if operation is None:
                    sequence[3]["record"].pop("operation")
                    sequence[4]["record"].pop("operation")
                else:
                    sequence[3]["record"]["operation"] = operation
                    sequence[4]["record"]["operation"] = operation

                self.assertIn(
                    "ADAPTER_SCHEMA_INVALID",
                    diagnostic_codes(tuple(sequence)),
                )

    def test_sequence_requires_automated_route_and_capability_operation(self) -> None:
        cases = (
            ("route", "operator_action"),
            ("route", "unavailable"),
            ("capability", "operator_action"),
            ("capability", "unavailable"),
        )
        for source, mode in cases:
            with self.subTest(source=source, mode=mode):
                sequence = list(copy.deepcopy(valid_sequence()))
                if source == "route":
                    disposition = {"disposition": mode}
                    for index in (1, 3):
                        sequence[index]["record"]["route_record"]["operations"][
                            "install"
                        ] = copy.deepcopy(disposition)
                    rebind_route_digest(sequence)
                else:
                    support = {"mode": mode}
                    if mode == "operator_action":
                        support["operator_action_reference"] = (
                            "docs/agent-equipment/ARCHITECTURE.md"
                            "#route-and-control-capability-matrix"
                        )
                    capability_record(sequence[0])["operation_support"]["install"] = (
                        support
                    )
                    rebind_capability_digest(sequence)

                self.assertIn(
                    "ACTION_OPERATION_UNAUTHORIZED",
                    diagnostic_codes(tuple(sequence)),
                )

    def test_sequence_rejects_native_rolling_plugin_remove(self) -> None:
        sequence = list(copy.deepcopy(valid_sequence()))
        sequence[3]["record"]["operation"] = "remove"
        sequence[4]["record"]["operation"] = "remove"
        automated_route = {
            "disposition": "automated",
            "compensation": "restore_captured_pre_state",
        }
        for index in (1, 3):
            sequence[index]["record"]["route_record"]["operations"]["remove"] = (
                copy.deepcopy(automated_route)
            )
        rebind_route_digest(sequence)
        capability_record(sequence[0])["operation_support"]["remove"] = {
            "mode": "automated",
            "compare_before_mutate": True,
            "idempotency": "state_convergent",
            "compensation": "restore_captured_pre_state",
        }
        rebind_capability_digest(sequence)

        self.assertIn(
            "NATIVE_ROLLING_REMOVE_UNSAFE",
            diagnostic_codes(tuple(sequence)),
        )

    def test_valid_fixture_bindings_use_canonical_digests(self) -> None:
        capability = load_record("valid-adapter-capability-record.json")
        manager_evidence = copy.deepcopy(capability["manager_version_evidence"])
        manager_digest = manager_evidence.pop("evidence_digest")
        self.assertEqual(manager_digest, canonical_digest(manager_evidence))

        capability_without_digest = copy.deepcopy(capability)
        capability_digest = capability_without_digest.pop("capability_digest")
        self.assertEqual(
            capability_digest,
            canonical_digest(capability_without_digest),
        )

        request = load_record("valid-adapter-observe-request.json")
        action = load_record("valid-adapter-planned-action.json")
        observation = load_record("valid-adapter-runtime-observation.json")
        receipt = load_record("valid-adapter-mutation-receipt.json")

        route_digest = canonical_digest(request["route_record"])
        desired_state_digest = canonical_digest(action["desired_state"])
        for record in (request, action, observation, receipt):
            self.assertEqual(
                TRUSTED_CANDIDATE_IDENTITY,
                record["candidate_identity"],
            )
            self.assertEqual(
                TRUSTED_IMPLEMENTATION_MANIFEST_DIGEST,
                record["implementation_manifest_digest"],
            )
            self.assertEqual(route_digest, record["route_digest"])
            self.assertEqual(capability_digest, record["capability_digest"])
            self.assertEqual(
                manager_digest,
                record["manager_version_evidence_digest"],
            )
        self.assertEqual(request["route_record"], action["route_record"])
        self.assertEqual(
            action["candidate_identity"],
            action["preconditions"]["candidate_identity"],
        )
        self.assertEqual(
            action["implementation_manifest_digest"],
            action["preconditions"]["implementation_manifest_digest"],
        )
        self.assertEqual(desired_state_digest, action["desired_state_digest"])
        normalized_state_digest = canonical_digest(
            observation["result"]["normalized_state"]
        )
        self.assertEqual(normalized_state_digest, observation["result"]["state_digest"])
        expected_post_digest = canonical_digest(
            expected_post_normalized_state(
                observation["result"]["normalized_state"],
                action["desired_state"],
            )
        )
        self.assertEqual(
            expected_post_digest,
            receipt["result"]["expected_post_state_digest"],
        )

    def test_captured_state_version_matches_the_manifest_schema(self) -> None:
        captured_state_schema = json.loads(
            CAPTURED_STATE_SCHEMA.read_text(encoding="utf-8")
        )
        canonical_version = captured_state_schema["properties"]["schema_version"][
            "const"
        ]
        capability = load_record("valid-adapter-capability-record.json")
        action = load_record("valid-adapter-planned-action.json")

        self.assertEqual(
            canonical_version,
            capability["record_versions"]["captured_state"],
        )
        self.assertEqual(
            canonical_version,
            action["compensation"]["captured_state_version"],
        )

    def test_cross_field_safety_invariants_fail_closed(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []

        capability_boundary = load_document("valid-adapter-capability-record.json")
        capability_record(capability_boundary)["component_control_support"][
            "mutation_boundary"
        ] = "selected_component"
        capability_record(capability_boundary)["component_control_support"]["mode"] = (
            "inspect_only"
        )
        cases.append(("inspect control cannot mutate", capability_boundary))

        update_claim = load_document("valid-adapter-capability-record.json")
        capability_record(update_claim)["native_update_support"][
            "native_update_control"
        ] = "unsuppressible"
        cases.append(("unsuppressible update cannot advertise control", update_claim))

        null_apply_plan = load_document("valid-adapter-observe-request.json")
        null_apply_plan["record"]["plan_digest"] = None
        cases.append(("apply requires a plan", null_apply_plan))

        unguarded_verify = load_document("valid-adapter-observe-request.json")
        unguarded_verify["record"]["purpose"] = "verify_post_state"
        unguarded_verify["record"]["expected_state_digest"] = None
        cases.append(("verification requires expected state", unguarded_verify))

        mutating_observation_error = load_document(
            "valid-adapter-runtime-observation.json"
        )
        mutating_observation_error["record"]["result"] = {
            "status": "error",
            "code": "NATIVE_FAILURE",
            "classification": "native_failure",
            "message": "redacted observation failure",
            "retry": "after_audit",
            "mutation_state": "possibly_changed",
            "evidence_references": [],
        }
        cases.append(("observation errors are read only", mutating_observation_error))

        wrong_observation_evidence = load_document(
            "valid-adapter-runtime-observation.json"
        )
        wrong_observation_evidence["record"]["result"]["surface_evidence"][0][
            "kind"
        ] = "checkpoint"
        cases.append(
            (
                "observation surface evidence has a surface kind",
                wrong_observation_evidence,
            )
        )

        operator_action = load_document("valid-adapter-planned-action.json")
        operator_action["record"]["route_record"]["control_owner"] = "operator_owned"
        cases.append(("operator route cannot become an action", operator_action))

        wrong_mutation_evidence = load_document("valid-adapter-mutation-receipt.json")
        wrong_mutation_evidence["record"]["result"]["surface_evidence"][0]["kind"] = (
            "manager"
        )
        cases.append(
            ("mutation surface evidence has the surface kind", wrong_mutation_evidence)
        )

        apply_with_restored_evidence = load_document(
            "valid-adapter-mutation-receipt.json"
        )
        compensation = apply_with_restored_evidence["record"]["result"][
            "compensation_evidence"
        ]
        compensation.pop("expected_post_state_digest")
        compensation["status"] = "restored"
        compensation["restored_state_digest"] = compensation["captured_state_digest"]
        compensation["comparison"] = "equal"
        cases.append(("apply cannot claim compensation", apply_with_restored_evidence))

        with tempfile.TemporaryDirectory() as directory:
            for index, (label, document) in enumerate(cases):
                with self.subTest(label=label):
                    path = Path(directory) / f"invalid-{index}.json"
                    path.write_text(
                        json.dumps(document),
                        encoding="utf-8",
                    )
                    result = run_check_jsonschema(
                        "--schemafile",
                        str(SCHEMA),
                        str(path),
                    )
                    self.assertEqual(
                        1,
                        result.returncode,
                        result.stdout + result.stderr,
                    )


if __name__ == "__main__":
    unittest.main()
