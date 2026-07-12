import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "home/private_dot_local/bin/executable_hindsight-memory"
LIB = ROOT / "home/private_dot_local/lib"
if str(LIB) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(LIB))

from hindsight_memory_control_plane import (
    OperationSnapshot,
    PlanError,
    build_plan,
    canonical_bytes,
    load_inventory,
    verify_plan,
)
from hindsight_memory_control_plane.ledger import LedgerError, append_record


def inventory():
    return {
        "schema_version": 1,
        "machine": {"id": "test-mac", "base_port": 7979},
        "archetype": {"id": "trusted-workstation"},
        "profiles": [
            {
                "id": "core",
                "slot": 0,
                "enabled": True,
                "host": "127.0.0.1",
                "roles": {
                    "llm": "local-llm",
                    "embedding": "local-embedding",
                    "reranking": "local-reranker",
                },
                "data_classes": ["engineering", "personal"],
            }
        ],
        "providers": [
            {
                "id": "local-llm",
                "role": "llm",
                "placement": "local",
                "data_classes": ["engineering", "personal"],
            },
            {
                "id": "local-embedding",
                "role": "embedding",
                "placement": "local",
                "data_classes": ["engineering", "personal"],
            },
            {
                "id": "local-reranker",
                "role": "reranking",
                "placement": "local",
                "data_classes": ["engineering", "personal"],
            },
        ],
        "banks": [
            {
                "id": "engineering",
                "profile_id": "core",
                "data_class": "engineering",
                "authority": "authoritative",
                "writable": True,
            }
        ],
        "harnesses": [
            {
                "id": "codex",
                "profile_id": "core",
                "home_bank": {"profile_id": "core", "bank_id": "engineering"},
            }
        ],
        "migration": {
            "artifact_dir": "/tmp/hindsight-artifacts",
            "proposal_log": "/tmp/hindsight-proposals.md",
        },
        "policy": {
            "engineering_memory_enabled": True,
            "allowed_placements": {
                "engineering": ["local", "private-remote"],
                "personal": ["local", "private-remote"],
            },
        },
    }


class ControllerCliTest(unittest.TestCase):
    def run_cli(self, state_dir, *args):
        return subprocess.run(
            ["python3", str(CLI), "--state-dir", str(state_dir), *map(str, args)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def write_json(self, path, value, *, pretty=False):
        path.write_text(
            json.dumps(value, indent=2 if pretty else None, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_validate_is_closed_and_reports_a_known_canonical_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            compact = tmp / "compact.json"
            pretty = tmp / "pretty.json"
            self.write_json(compact, inventory())
            self.write_json(pretty, inventory(), pretty=True)

            expected = "e240cb5a96a1ea63de338e695798b4e190414ead42db0ac107a2858bbf83fad7"
            for fixture in (compact, pretty):
                result = self.run_cli(tmp, "validate", "--inventory", fixture)
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)
                self.assertEqual(output["inventory_digest"], expected)
                self.assertRegex(output["artifact_digest"], r"^[0-9a-f]{64}$")

            for key in ("policy",):
                invalid = inventory()
                del invalid[key]
                fixture = tmp / f"missing-{key}.json"
                self.write_json(fixture, invalid)
                result = self.run_cli(tmp, "validate", "--inventory", fixture)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("root keys", result.stderr)

            invalid = inventory()
            invalid["surprise"] = True
            fixture = tmp / "unknown.json"
            self.write_json(fixture, invalid)
            result = self.run_cli(tmp, "validate", "--inventory", fixture)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("root keys", result.stderr)

            invalid = inventory()
            invalid["banks"].append(dict(invalid["banks"][0]))
            fixture = tmp / "duplicate.json"
            self.write_json(fixture, invalid)
            result = self.run_cli(tmp, "validate", "--inventory", fixture)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate banks id", result.stderr)

    def test_validate_rejects_references_authority_ports_placement_and_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            invalid_cases = []

            disabled_reference = inventory()
            disabled_reference["profiles"][0]["enabled"] = False
            disabled_reference["profiles"][0]["roles"]["llm"] = "missing-provider"
            invalid_cases.append((disabled_reference, "unknown provider"))

            split_brain = inventory()
            split_brain["banks"].append({"id": "engineering-2", "profile_id": "core", "data_class": "engineering", "authority": "authoritative", "writable": True})
            invalid_cases.append((split_brain, "exactly one authoritative write bank"))

            collision = inventory()
            collision["profiles"].append({**collision["profiles"][0], "id": "other", "slot": 1, "port": 7979})
            invalid_cases.append((collision, "endpoint collision"))

            forbidden = inventory()
            forbidden["providers"][0]["placement"] = "third-party-hosted"
            invalid_cases.append((forbidden, "placement is forbidden"))

            relative_path = inventory()
            relative_path["migration"]["artifact_dir"] = "artifacts"
            invalid_cases.append((relative_path, "path must be absolute"))

            for index, (value, message) in enumerate(invalid_cases):
                fixture = tmp / f"invalid-{index}.json"
                self.write_json(fixture, value)
                result = self.run_cli(tmp, "validate", "--inventory", fixture)
                self.assertNotEqual(result.returncode, 0, f"case {index} unexpectedly passed")
                self.assertIn(message, result.stderr)

    def test_validate_rejects_invalid_unreferenced_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            invalid_providers = [
                {"id": "unused", "role": "secret", "placement": "local", "data_classes": ["engineering"]},
                {"id": "unused", "role": "llm", "placement": "elsewhere", "data_classes": ["engineering"]},
                {"id": "unused", "role": "llm", "placement": "local", "data_classes": "engineering"},
                {"id": "unused", "role": "llm", "placement": "local", "data_classes": ["engineering", 7]},
            ]
            for index, provider in enumerate(invalid_providers):
                value = inventory()
                value["providers"].append(provider)
                fixture = tmp / f"provider-{index}.json"
                self.write_json(fixture, value)
                result = self.run_cli(tmp, "validate", "--inventory", fixture)
                self.assertNotEqual(result.returncode, 0, f"unreferenced provider case {index} unexpectedly passed")
                self.assertIn("provider unused", result.stderr)

    def test_validate_requires_boolean_bank_writable(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            for index, writable in enumerate(("false", 1, 0, None, [], {})):
                value = inventory()
                value["banks"][0]["writable"] = writable
                fixture = tmp / f"writable-{index}.json"
                self.write_json(fixture, value)
                result = self.run_cli(tmp, "validate", "--inventory", fixture)
                self.assertNotEqual(result.returncode, 0, f"non-boolean writable case {index} unexpectedly passed")
                self.assertIn("writable must be boolean", result.stderr)

    def test_plan_is_digest_bound_canonical_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            fixture = tmp / "inventory.json"
            live = tmp / "live.json"
            operations = tmp / "operations.json"
            output = tmp / "plan.json"
            self.write_json(fixture, inventory())
            self.write_json(
                live,
                {
                    "profile_id": "core",
                    "endpoint": {
                        "profile_id": "core",
                        "scheme": "http",
                        "host": "127.0.0.1",
                        "port": 7979,
                        "tenant": "default",
                    },
                    "state": {"banks": []},
                    "compatibility": [{"check": "provider-contract", "compatible": True}],
                    "actions": [
                        {"id": "01-create-engineering", "kind": "create_bank", "bank": {"profile_id": "core", "bank_id": "engineering"}},
                        {"id": "02-configure-engineering", "kind": "configure_bank", "bank": {"profile_id": "core", "bank_id": "engineering"}},
                    ],
                },
            )
            self.write_json(operations, {"idle": True, "active": []})

            result = self.run_cli(
                tmp,
                "plan",
                "--inventory", fixture,
                "--live-state", live,
                "--operations", operations,
                "--output", output,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                set(value),
                {
                    "schema_version", "inventory_digest", "artifact_digest",
                    "target_profile", "target_endpoint", "live_state_digest",
                    "operations", "compatibility", "actions", "destructive",
                    "plan_digest",
                },
            )
            self.assertEqual(value["target_endpoint"]["port"], 7979)
            self.assertEqual(value["operations"], {"active": [], "idle": True})
            self.assertEqual([a["id"] for a in value["actions"]], ["01-create-engineering", "02-configure-engineering"])
            self.assertFalse(value["destructive"])
            body = dict(value)
            plan_digest = body.pop("plan_digest")
            canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            self.assertEqual(plan_digest, hashlib.sha256(canonical).hexdigest())
            self.assertEqual(output.read_bytes(), json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n")
            self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)

            status = self.run_cli(
                tmp,
                "status",
                "--inventory", fixture,
                "--live-state", live,
                "--plan", output,
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(
                {key: json.loads(status.stdout)[key] for key in ("desired_agrees", "live_agrees", "plan_agrees")},
                {"desired_agrees": True, "live_agrees": True, "plan_agrees": True},
            )

    def test_plan_rejects_destructive_kinds_even_when_the_flag_is_missing_or_false(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            fixture = tmp / "inventory.json"
            operations = tmp / "operations.json"
            self.write_json(fixture, inventory())
            self.write_json(operations, {"idle": True, "active": []})
            for suffix in ({}, {"destructive": False}):
                live = tmp / f"live-{len(suffix)}.json"
                self.write_json(
                    live,
                    {
                        "profile_id": "core",
                        "endpoint": {"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"},
                        "state": {},
                        "compatibility": [],
                        "actions": [{"id": "delete-1", "kind": "delete_bank", "bank": {"profile_id": "core", "bank_id": "engineering"}, **suffix}],
                    },
                )
                result = self.run_cli(tmp, "plan", "--inventory", fixture, "--live-state", live, "--operations", operations)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("destructive action kind", result.stderr)

    def test_plan_artifacts_reject_private_and_payload_carriers(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            fixture = tmp / "inventory.json"
            live = tmp / "live.json"
            operations = tmp / "operations.json"
            self.write_json(fixture, inventory())
            base_live = {
                "profile_id": "core",
                "endpoint": {"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"},
                "state": {},
                "compatibility": [{"check": "provider-contract", "compatible": True}],
                "actions": [{"id": "create-1", "kind": "create_bank", "bank": {"profile_id": "core", "bank_id": "engineering"}}],
            }
            adversarial = [
                ({"idle": False, "active": [{"id": "op-1", "kind": "retain", "status": "running", "token": "private"}]}, base_live, "operations"),
                ({"idle": True, "active": []}, {**base_live, "compatibility": [{"check": "provider-contract", "compatible": True, "api_key": "private"}]}, "compatibility"),
                ({"idle": True, "active": []}, {**base_live, "actions": [{"id": "create-1", "kind": "create_bank", "bank": {"profile_id": "core", "bank_id": "engineering"}, "control_key": "private"}]}, "action"),
                ({"idle": True, "active": []}, {**base_live, "actions": [{"id": "create-1", "kind": "create_bank", "bank": {"profile_id": "core", "bank_id": "engineering"}, "metadata": {"note": "innocuous nested payload"}}]}, "action"),
            ]
            for index, (operation_value, live_value, message) in enumerate(adversarial):
                self.write_json(operations, operation_value)
                self.write_json(live, live_value)
                result = self.run_cli(tmp, "plan", "--inventory", fixture, "--live-state", live, "--operations", operations)
                self.assertNotEqual(result.returncode, 0, f"adversarial case {index} unexpectedly passed")
                self.assertIn(message, result.stderr)

            desired = load_inventory(fixture)
            with self.assertRaisesRegex(PlanError, "operations entry"):
                build_plan(
                    desired,
                    base_live,
                    OperationSnapshot(False, ({"id": "op-1", "kind": "retain", "status": "running", "signing_key": "private"},)),
                )

    def test_plan_owns_immutable_copies_of_all_nested_values(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            fixture = tmp / "inventory.json"
            self.write_json(fixture, inventory())
            desired = load_inventory(fixture)
            live = {
                "profile_id": "core",
                "endpoint": {"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"},
                "state": {},
                "compatibility": [{"check": "provider-contract", "compatible": True}],
                "actions": [{"id": "create-1", "kind": "create_bank", "bank": {"profile_id": "core", "bank_id": "engineering"}}],
            }
            operations = {"idle": False, "active": [{"id": "op-1", "kind": "retain", "status": "running", "profile_id": "core"}]}
            plan = build_plan(desired, live, operations)
            before = canonical_bytes(plan.to_dict())

            live["compatibility"][0]["compatible"] = False
            live["actions"][0]["bank"]["bank_id"] = "personal"
            operations["active"][0]["status"] = "failed"
            with self.assertRaises(TypeError):
                plan.compatibility[0]["compatible"] = False
            with self.assertRaises(TypeError):
                plan.actions[0].details["bank"] = {"bank_id": "personal"}
            with self.assertRaises(TypeError):
                plan.operations.active[0]["status"] = "failed"
            with self.assertRaises(TypeError):
                desired.profiles[0]["id"] = "changed"

            self.assertEqual(canonical_bytes(plan.to_dict()), before)
            verify_plan(plan)

    def test_plan_rejects_live_endpoint_drift_from_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            fixture = tmp / "inventory.json"
            live = tmp / "live.json"
            operations = tmp / "operations.json"
            self.write_json(fixture, inventory())
            self.write_json(operations, {"idle": True, "active": []})
            self.write_json(live, {"profile_id": "core", "endpoint": {"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7980, "tenant": "default"}, "state": {}, "compatibility": [], "actions": []})
            result = self.run_cli(tmp, "plan", "--inventory", fixture, "--live-state", live, "--operations", operations)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("endpoint identity does not match inventory", result.stderr)

    def test_status_rejects_unknown_and_malformed_plan_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            fixture = tmp / "inventory.json"
            live = tmp / "live.json"
            operations = tmp / "operations.json"
            plan = tmp / "plan.json"
            self.write_json(fixture, inventory())
            self.write_json(operations, {"idle": True, "active": []})
            self.write_json(live, {"profile_id": "core", "endpoint": {"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"}, "state": {}, "compatibility": [], "actions": []})
            self.assertEqual(self.run_cli(tmp, "plan", "--inventory", fixture, "--live-state", live, "--operations", operations, "--output", plan).returncode, 0)

            value = json.loads(plan.read_text())
            value["secret"] = "private"
            self.write_json(plan, value)
            unknown = self.run_cli(tmp, "status", "--inventory", fixture, "--live-state", live, "--plan", plan)
            self.assertNotEqual(unknown.returncode, 0)
            self.assertIn("plan keys", unknown.stderr)

            del value["secret"]
            value["plan_digest"] = "not-a-digest"
            self.write_json(plan, value)
            malformed = self.run_cli(tmp, "status", "--inventory", fixture, "--live-state", live, "--plan", plan)
            self.assertNotEqual(malformed.returncode, 0)
            self.assertIn("plan_digest", malformed.stderr)

            value["plan_digest"] = "0" * 64
            self.write_json(plan, value)
            tampered = self.run_cli(tmp, "status", "--inventory", fixture, "--live-state", live, "--plan", plan)
            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("plan digest does not match plan body", tampered.stderr)

    def test_ledger_is_canonical_private_and_payload_free(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "controller.jsonl"
            record = {
                "schema_version": 1,
                "action_id": "retain-1",
                "correlation_id": "session-1",
                "source_bank": {"profile_id": "core", "bank_id": "engineering", "endpoint": {"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"}},
                "target_bank": {"profile_id": "core", "bank_id": "personal", "endpoint": {"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"}},
                "policy_digest": "1" * 64,
                "artifact_digest": "2" * 64,
                "decision": "deny",
                "reason_code": "CROSS_BANK_POLICY_DENY",
                "timestamp": "2026-07-12T17:00:00Z",
                "reversible_record_id": None,
            }
            append_record(ledger, record)
            self.assertEqual(ledger.read_bytes(), json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n")
            self.assertEqual(os.stat(ledger).st_mode & 0o777, 0o600)

            for key in ("token", "api_key", "control_key", "signing_key", "secret"):
                contaminated = dict(record)
                contaminated["source_bank"] = {**record["source_bank"], key: "private"}
                with self.assertRaisesRegex(LedgerError, "bank reference keys"):
                    append_record(ledger, contaminated)

            contaminated = dict(record)
            contaminated["source_bank"] = {**record["source_bank"], "metadata": {"note": "innocuous nested payload"}}
            with self.assertRaisesRegex(LedgerError, "bank reference keys"):
                append_record(ledger, contaminated)

            for missing in ("source_bank", "target_bank", "reversible_record_id"):
                incomplete = dict(record)
                del incomplete[missing]
                with self.assertRaisesRegex(LedgerError, "missing keys"):
                    append_record(ledger, incomplete)


if __name__ == "__main__":
    unittest.main()
