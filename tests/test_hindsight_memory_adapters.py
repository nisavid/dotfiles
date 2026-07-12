import json
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "home/private_dot_local/lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from hindsight_memory_control_plane.adapters import AdapterError, AuthenticationError, FakeAdapter
from hindsight_memory_control_plane.http_adapter import HttpAdapter
from hindsight_memory_control_plane.migration_adapter import AdminMigrationAdapter, MigrationAdapterError
from hindsight_memory_control_plane.canonical import digest
from hindsight_memory_control_plane.model import Action, EndpointIdentity, OperationSnapshot, Plan
from hindsight_memory_control_plane.reconcile import ApplyError, apply_plan, create_rollback_bundle, parse_migration_gate


def plan_for(state, *actions):
    endpoint = EndpointIdentity("core", "http", "127.0.0.1", 7979, "default")
    values = tuple(actions or (Action("01-create", "create_bank", {"bank": {"profile_id": "core", "bank_id": "engineering"}}),))
    body = {
        "schema_version": 1, "inventory_digest": "1" * 64, "artifact_digest": "2" * 64,
        "target_profile": "core", "target_endpoint": endpoint.to_dict(), "live_state_digest": digest(state),
        "operations": {"idle": True, "active": []}, "compatibility": [],
        "actions": [action.to_dict() for action in values], "destructive": False,
    }
    return Plan(1, "1" * 64, "2" * 64, "core", endpoint, digest(state), OperationSnapshot(True), (), values, False, digest(body))


class FakeAdapterContractTest(unittest.TestCase):
    def test_reads_and_mutations_are_explicit_and_record_payload_free_calls(self):
        adapter = FakeAdapter(
            schema=1,
            endpoint={"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"},
            state={"config": {"mode": "safe"}},
        )

        self.assertEqual(adapter.schema_version(), 1)
        self.assertEqual(adapter.read_config(), {"mode": "safe"})
        adapter.patch_config({"mode": "active"})

        self.assertEqual([call["method"] for call in adapter.calls], ["schema_version", "read_config", "patch_config"])
        self.assertEqual(adapter.calls[-1], {"method": "patch_config", "metadata": {"keys": ["mode"]}})

    def test_covers_every_explicit_observable_operation(self):
        adapter = FakeAdapter(
            endpoint={"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"},
        )
        adapter.endpoint_identity()
        for method in (adapter.read_stats, adapter.read_tags, adapter.read_scopes, adapter.read_documents,
                       adapter.read_models, adapter.read_directives, adapter.read_operations,
                       adapter.read_invalidated_memories, adapter.export_template):
            method()
        for method in (adapter.template_dry_run, adapter.import_template, adapter.patch_config,
                       adapter.upsert_model, adapter.upsert_directive, adapter.transfer_documents,
                       adapter.reapply_invalidated_memories, adapter.delete_bank):
            method({"id": "item"})
        serialized = json.dumps(adapter.calls)
        self.assertNotIn('"item"', serialized)
        self.assertNotIn("top-secret", serialized)


class HttpAdapterContractTest(unittest.TestCase):
    def test_uses_resolved_bearer_token_without_recording_or_exposing_it(self):
        token = "top-secret-token"
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.path, self.headers.get("Authorization")))
                body = json.dumps({"mode": "safe"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        adapter = HttpAdapter(
            endpoint={"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": server.server_port, "tenant": "default"},
            token_resolver=lambda: token,
        )

        self.assertEqual(adapter.read_config(), {"mode": "safe"})
        self.assertEqual(seen, [("/v1/config", f"Bearer {token}")])
        self.assertNotIn(token, repr(adapter))
        self.assertNotIn(token, json.dumps(adapter.recordings))

    def test_all_explicit_operations_use_bearer_auth_and_bounded_json(self):
        seen = []
        identity = {"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 1, "tenant": "default"}

        class Handler(BaseHTTPRequestHandler):
            def _serve(self):
                seen.append((self.command, self.path, self.headers.get("Authorization")))
                if self.path == "/v1/schema":
                    value = {"schema_version": 1}
                elif self.path == "/v1/identity":
                    value = {**identity, "port": self.server.server_port}
                else:
                    value = {}
                body = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _serve
            def log_message(self, *_args): pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        adapter = HttpAdapter(endpoint={**identity, "port": server.server_port}, token_resolver=lambda: "token")
        adapter.schema_version()
        adapter.endpoint_identity()
        for method in (adapter.read_config, adapter.read_stats, adapter.read_tags, adapter.read_scopes,
                       adapter.read_documents, adapter.read_models, adapter.read_directives,
                       adapter.read_operations, adapter.read_invalidated_memories, adapter.export_template):
            method()
        for method in (adapter.template_dry_run, adapter.import_template, adapter.patch_config,
                       adapter.upsert_model, adapter.upsert_directive, adapter.transfer_documents,
                       adapter.reapply_invalidated_memories, adapter.delete_bank):
            method({"id": "item"})
        self.assertTrue(seen)
        self.assertTrue(all(auth == "Bearer token" for _, _, auth in seen))

    def test_preserves_401_redacts_token_and_rejects_oversized_json(self):
        token = "never-print-this-token"
        status = {"code": 401}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"{}" if status["code"] == 401 else b"x" * 2048
                self.send_response(status["code"])
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_args): pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        adapter = HttpAdapter(
            endpoint={"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": server.server_port, "tenant": "default"},
            token_resolver=lambda: token, max_json_bytes=1024, timeout=100,
        )
        with self.assertRaises(AuthenticationError) as auth:
            adapter.read_config()
        self.assertNotIn(token, str(auth.exception))
        status["code"] = 200
        with self.assertRaisesRegex(AdapterError, "size limit"):
            adapter.read_config()
        self.assertEqual(adapter.timeout, 30.0)

    def test_enforces_request_timeout_without_leaking_credentials(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                time.sleep(0.25)
                try:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"{}")
                except BrokenPipeError:
                    pass
            def log_message(self, *_args): pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        adapter = HttpAdapter(
            endpoint={"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": server.server_port, "tenant": "default"},
            token_resolver=lambda: "timeout-secret", timeout=0.1,
        )
        with self.assertRaises(AdapterError) as failure:
            adapter.read_config()
        self.assertNotIn("timeout-secret", str(failure.exception))


class AdminMigrationAdapterContractTest(unittest.TestCase):
    def test_accepts_only_digest_bound_argv_and_requires_restore_evidence(self):
        calls = []
        archive_digest = "a" * 64
        adapter = AdminMigrationAdapter(
            admin_version="1",
            argv_factory=lambda operation, archive, digest: ["hindsight-admin", operation, "--archive", archive, "--sha256", digest],
            runner=lambda argv: calls.append(argv) or {"returncode": 0, "stdout": "{}"},
        )

        adapter.backup("/tmp/bank.tar", archive_digest)
        self.assertEqual(calls[0][:2], ["hindsight-admin", "backup"])
        with self.assertRaisesRegex(MigrationAdapterError, "disposable restore evidence"):
            adapter.restore("/tmp/bank.tar", archive_digest)

    def test_rejects_unknown_versions_shell_strings_missing_digests_and_bad_argv(self):
        with self.assertRaisesRegex(MigrationAdapterError, "unsupported"):
            AdminMigrationAdapter(admin_version="2", argv_factory=lambda *_: [], runner=lambda _: None)
        adapter = AdminMigrationAdapter(admin_version="1", argv_factory=lambda *_: "hindsight-admin backup", runner=lambda _: None)
        with self.assertRaisesRegex(MigrationAdapterError, "argument vector"):
            adapter.backup("/tmp/bank.tar", "a" * 64)
        adapter = AdminMigrationAdapter(admin_version="1", argv_factory=lambda op, path, sha: ["hindsight-admin", op, "--archive", path, "--sha256", sha, "--database-url", "secret"], runner=lambda _: None)
        with self.assertRaisesRegex(MigrationAdapterError, "argv shape"):
            adapter.backup("/tmp/bank.tar", "a" * 64)
        with self.assertRaisesRegex(MigrationAdapterError, "digest"):
            adapter.backup("/tmp/bank.tar", "")

    def test_permits_all_four_exact_operations_with_verified_restore_evidence(self):
        calls = []
        artifact = "b" * 64
        evidence = {"disposable": True, "restore_verified": True, "artifact_digest": artifact}
        adapter = AdminMigrationAdapter(
            admin_version="1",
            argv_factory=lambda operation, archive, sha: ["hindsight-admin", operation, "--archive", archive, "--sha256", sha],
            runner=lambda argv: calls.append(argv) or {"returncode": 0, "stdout": "{}"},
        )
        adapter.export_bank("/tmp/bank.tar", artifact)
        adapter.backup("/tmp/bank.tar", artifact)
        adapter.import_bank("/tmp/bank.tar", artifact, evidence)
        adapter.restore("/tmp/bank.tar", artifact, evidence)
        self.assertEqual([argv[1] for argv in calls], ["export-bank", "backup", "import-bank", "restore"])


class GuardedApplyTest(unittest.TestCase):
    def adapter(self, state=None, **kwargs):
        return FakeAdapter(
            endpoint={"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"},
            state=state or {}, **kwargs,
        )

    def test_requires_exact_approval_and_action_specific_rollback(self):
        adapter = self.adapter()
        plan = plan_for({})
        bundle = create_rollback_bundle(plan, adapter)

        wrong = apply_plan(plan, adapter, "f" * 64, {"rollback_bundle": bundle})
        missing = apply_plan(plan, adapter, plan.plan_digest, {})

        self.assertEqual(wrong.status, "refused")
        self.assertEqual(wrong.reason, "approval_digest_mismatch")
        self.assertEqual(missing.reason, "rollback_bundle_required")

    def test_postcondition_failure_rolls_back_and_rollback_failure_blocks_operator(self):
        adapter = self.adapter()
        plan = plan_for({})
        bundle = create_rollback_bundle(plan, adapter)
        adapter.fail_postcondition_for = "01-create"
        adapter.fail_restore = True

        result = apply_plan(plan, adapter, plan.plan_digest, {"rollback_bundle": bundle})

        self.assertEqual(result.status, "operator_blocked")
        self.assertTrue(result.rollback_attempted)
        self.assertFalse(result.activation_enabled)
        self.assertFalse(adapter.activation_enabled)

    def test_refuses_fresh_state_operation_endpoint_and_restore_proof_failures(self):
        plan = plan_for({})

        drifted = self.adapter(state={"changed": True})
        drift_bundle = create_rollback_bundle(plan, drifted)
        self.assertEqual(apply_plan(plan, drifted, plan.plan_digest, {"rollback_bundle": drift_bundle}).reason, "live_state_drift")

        busy = self.adapter(operations={"idle": False, "active": [{"id": "op"}]})
        busy_bundle = create_rollback_bundle(plan, busy)
        self.assertEqual(apply_plan(plan, busy, plan.plan_digest, {"rollback_bundle": busy_bundle}).reason, "operations_not_idle")

        endpoint = self.adapter()
        endpoint.endpoint = EndpointIdentity("core", "http", "127.0.0.1", 7980, "default")
        endpoint_bundle = create_rollback_bundle(plan, endpoint)
        self.assertEqual(apply_plan(plan, endpoint, plan.plan_digest, {"rollback_bundle": endpoint_bundle}).reason, "endpoint_identity_drift")

        data_plan = plan_for({"documents": []})
        unproved = self.adapter(state={"documents": []}, disposable_restore_verified=False)
        unproved_bundle = create_rollback_bundle(data_plan, unproved)
        self.assertEqual(apply_plan(data_plan, unproved, data_plan.plan_digest, {"rollback_bundle": unproved_bundle}).reason, "disposable_restore_proof_required")

    def test_applies_in_order_and_rolls_back_on_first_failed_postcondition(self):
        actions = (
            Action("01", "create_bank", {"bank": {"profile_id": "core", "bank_id": "engineering"}}),
            Action("02", "reload_profile", {"profile_id": "core", "reason_code": "config_changed"}),
        )
        adapter = self.adapter()
        plan = plan_for({}, *actions)
        bundle = create_rollback_bundle(plan, adapter)
        adapter.fail_postcondition_for = "02"

        result = apply_plan(plan, adapter, plan.plan_digest, {"rollback_bundle": bundle})

        self.assertEqual(result.status, "rolled_back")
        self.assertEqual(result.applied_action_ids, ("01", "02"))
        self.assertEqual([entry["status"] for entry in result.ledger], ["applied", "verified", "applied", "rollback_started", "rollback_succeeded"])

    def test_migration_gate_halves_must_match_run_and_artifact(self):
        artifact = "a" * 64
        self.assertEqual(parse_migration_gate({
            "export": {"run_id": "run-1", "artifact_digest": artifact},
            "import": {"run_id": "run-1", "artifact_digest": artifact},
        }), ("run-1", artifact))
        with self.assertRaisesRegex(ApplyError, "do not match"):
            parse_migration_gate({
                "export": {"run_id": "run-1", "artifact_digest": artifact},
                "import": {"run_id": "run-2", "artifact_digest": artifact},
            })

    def test_refuses_an_ordinary_plan_marked_destructive(self):
        adapter = self.adapter()
        plan = replace(plan_for({}), destructive=True)
        result = apply_plan(plan, adapter, plan.plan_digest, {"rollback_bundle": {}})
        self.assertEqual(result.reason, "invalid_or_destructive_plan")


if __name__ == "__main__":
    unittest.main()
