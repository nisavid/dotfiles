from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "docs/agent-equipment/adapter-contract-v1.schema.json"
FIXTURES = ROOT / "tests/fixtures/agent-equipment/schema"
SCHEMA_BASE_URI = SCHEMA.resolve().as_uri()


def run_check_jsonschema(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uvx",
            "--from",
            "check-jsonschema==0.35.0",
            "check-jsonschema",
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


def load_document(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_record(name: str) -> dict[str, object]:
    document = load_document(name)
    return document["record"]


class AdapterContractSchemaTests(unittest.TestCase):
    def test_schema_is_valid_draft_2020_12(self) -> None:
        result = run_check_jsonschema("--check-metaschema", str(SCHEMA))

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_valid_records_satisfy_the_closed_contract(self) -> None:
        fixtures = sorted(FIXTURES.glob("valid-adapter-*.json"))
        self.assertTrue(fixtures, "adapter contract needs valid record fixtures")

        result = run_check_jsonschema(
            "--schemafile",
            str(SCHEMA),
            "--base-uri",
            SCHEMA_BASE_URI,
            *(str(path) for path in fixtures),
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_invalid_records_fail_closed(self) -> None:
        fixtures = sorted(FIXTURES.glob("invalid-adapter-*.json"))
        self.assertTrue(fixtures, "adapter contract needs invalid record fixtures")

        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                result = run_check_jsonschema(
                    "--schemafile",
                    str(SCHEMA),
                    "--base-uri",
                    SCHEMA_BASE_URI,
                    str(fixture),
                )
                self.assertNotEqual(
                    0,
                    result.returncode,
                    f"{fixture.name} unexpectedly satisfied the adapter contract",
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
            self.assertEqual(route_digest, record["route_digest"])
            self.assertEqual(capability_digest, record["capability_digest"])
            self.assertEqual(
                manager_digest,
                record["manager_version_evidence_digest"],
            )
        self.assertEqual(request["route_record"], action["route_record"])
        self.assertEqual(desired_state_digest, action["desired_state_digest"])
        self.assertEqual(
            desired_state_digest,
            receipt["result"]["expected_post_state_digest"],
        )

    def test_cross_field_safety_invariants_fail_closed(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []

        capability_boundary = load_document(
            "valid-adapter-capability-record.json"
        )
        capability_boundary["record"]["component_control_support"][
            "mutation_boundary"
        ] = "selected_component"
        capability_boundary["record"]["component_control_support"][
            "mode"
        ] = "inspect_only"
        cases.append(("inspect control cannot mutate", capability_boundary))

        update_claim = load_document("valid-adapter-capability-record.json")
        update_claim["record"]["native_update_support"][
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

        operator_action = load_document("valid-adapter-planned-action.json")
        operator_action["record"]["route_record"][
            "control_owner"
        ] = "operator_owned"
        cases.append(("operator route cannot become an action", operator_action))

        apply_with_restored_evidence = load_document(
            "valid-adapter-mutation-receipt.json"
        )
        compensation = apply_with_restored_evidence["record"]["result"][
            "compensation_evidence"
        ]
        compensation.pop("expected_post_state_digest")
        compensation["status"] = "restored"
        compensation["restored_state_digest"] = compensation[
            "captured_state_digest"
        ]
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
                        "--base-uri",
                        SCHEMA_BASE_URI,
                        str(path),
                    )
                    self.assertNotEqual(
                        0,
                        result.returncode,
                        f"{label} unexpectedly satisfied the adapter contract",
                    )


if __name__ == "__main__":
    unittest.main()
