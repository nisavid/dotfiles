import json
from io import BytesIO
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "home/private_dot_local/lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from hindsight_memory_control_plane.adapters import AdapterError, AuthenticationError, FakeAdapter, RollbackBundle
from hindsight_memory_control_plane.http_adapter import HttpAdapter
from hindsight_memory_control_plane.migration_adapter import AdminMigrationAdapter, MigrationAdapterError
from hindsight_memory_control_plane.canonical import digest
from hindsight_memory_control_plane.model import Action, EndpointIdentity, Inventory, OperationSnapshot, Plan
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


def inventory_for(port, *, scheme="http", host="127.0.0.1", approved_tls=False):
    endpoint = {"profile_id": "core", "scheme": scheme, "host": host, "port": port, "tenant": "default"}
    raw = {
        "schema_version": 1, "machine": {"base_port": port}, "archetype": {},
        "profiles": [{"id": "core", "slot": 0, "port": port, "scheme": scheme, "host": host, "tenant": "default"}],
        "providers": [], "banks": [], "harnesses": [], "migration": {},
        "policy": {"approved_tls_endpoints": [endpoint] if approved_tls else []},
    }
    artifact = {key: raw[key] for key in ("schema_version", "archetype", "profiles", "providers", "banks", "harnesses", "policy")}
    return Inventory(1, raw["machine"], raw["archetype"], tuple(raw["profiles"]), (), (), (), raw["migration"], raw["policy"], digest(raw), digest(artifact))


def start_http_server(test_case, handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def cleanup():
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    test_case.addCleanup(cleanup)
    return server


class AdapterContractMixin:
    def assert_operation(self, method, path):
        raise NotImplementedError

    def test_schema_version(self):
        self.assertEqual(self.adapter.schema_version(), 1)
        self.assert_operation("GET", "/v1/schema")

    def test_endpoint_identity(self):
        self.assertEqual(self.adapter.endpoint_identity(), self.endpoint)
        self.assert_operation("GET", "/v1/identity")

    def test_snapshot(self):
        self.assertEqual(self.adapter.snapshot(), {"endpoint": self.endpoint.to_dict(), "state": self.state, "operations": self.operations})

    def test_read_config(self):
        self.assertEqual(self.adapter.read_config(), {"mode": "safe"})
        self.assert_operation("GET", "/v1/config")

    def test_read_stats(self):
        self.assertEqual(self.adapter.read_stats(), {"count": 2})
        self.assert_operation("GET", "/v1/stats")

    def test_read_tags(self):
        self.assertEqual(self.adapter.read_tags(), {"tags": ["a"]})
        self.assert_operation("GET", "/v1/tags")

    def test_read_scopes(self):
        self.assertEqual(self.adapter.read_scopes(), {"scopes": ["s"]})
        self.assert_operation("GET", "/v1/scopes")

    def test_read_documents(self):
        self.assertEqual(self.adapter.read_documents(), {"documents": [{"id": "d"}]})
        self.assert_operation("GET", "/v1/documents")

    def test_read_models(self):
        self.assertEqual(self.adapter.read_models(), {"models": [{"id": "m0"}]})
        self.assert_operation("GET", "/v1/models")

    def test_read_directives(self):
        self.assertEqual(self.adapter.read_directives(), {"directives": [{"id": "r0"}]})
        self.assert_operation("GET", "/v1/directives")

    def test_read_operations(self):
        self.assertEqual(self.adapter.read_operations(), self.operations)
        self.assert_operation("GET", "/v1/operations")

    def test_template_dry_run(self):
        value = {"template": "t"}
        self.assertEqual(self.adapter.template_dry_run(value), {"valid": True, "digest": digest(value)})
        self.assert_operation("POST", "/v1/templates/dry-run")

    def test_export_template(self):
        self.assertEqual(self.adapter.export_template(), {"template": "exported"})
        self.assert_operation("GET", "/v1/templates/export")

    def test_import_template(self):
        self.assertEqual(self.adapter.import_template({"template": "new"}), {"imported": True})
        self.assert_operation("POST", "/v1/templates/import")

    def test_patch_config(self):
        self.assertEqual(self.adapter.patch_config({"mode": "active"}), {"mode": "active"})
        self.assert_operation("PATCH", "/v1/config")

    def test_upsert_model(self):
        self.assertEqual(self.adapter.upsert_model({"id": "m"}), {"upserted": "m"})
        self.assert_operation("PUT", "/v1/models")

    def test_upsert_directive(self):
        self.assertEqual(self.adapter.upsert_directive({"id": "r"}), {"upserted": "r"})
        self.assert_operation("PUT", "/v1/directives")

    def test_transfer_documents(self):
        self.assertEqual(self.adapter.transfer_documents({"count": 2}), {"transferred": 2})
        self.assert_operation("POST", "/v1/documents/transfer")

    def test_invalidated_memory_inventory(self):
        self.assertEqual(self.adapter.read_invalidated_memories(), {"invalidated_memories": [{"id": "i"}]})
        self.assert_operation("GET", "/v1/memories/invalidated")

    def test_reapply_invalidated_memories(self):
        self.assertEqual(self.adapter.reapply_invalidated_memories({"count": 2}), {"reapplied": 2})
        self.assert_operation("POST", "/v1/memories/invalidated/reapply")

    def test_delete_bank(self):
        self.assertEqual(self.adapter.delete_bank({"bank_id": "b"}), {"deleted": True})
        self.assert_operation("DELETE", "/v1/banks")

    def test_runtime_memory_reads(self):
        self.assertEqual(self.adapter.recall({"query": "q", "limit": 2}), {"memories": [{"id": "m1"}]})
        self.assert_operation("POST", "/v1/runtime/recall")
        self.assertEqual(self.adapter.mental_model_fetch({"model_id": "model1"}), {"models": [{"id": "model1"}]})
        self.assert_operation("POST", "/v1/runtime/mental-model")
        self.assertEqual(self.adapter.session_status({"session_id": "session-1"}), {"status": "ready"})
        self.assert_operation("POST", "/v1/runtime/session-status")

    def test_runtime_memory_writes_are_idempotent(self):
        checkpoint = {"document_id": "d", "epoch": 1, "checkpoint": 2, "idempotency_key": "a" * 64}
        retain = {**checkpoint, "outcome": "done", "idempotency_key": "c" * 64}
        reflection = {"reflection": "note", "idempotency_key": "b" * 64}
        self.assertEqual(self.adapter.transcript_checkpoint(checkpoint), {"applied": True})
        self.assert_operation("PUT", "/v1/runtime/transcript-checkpoint")
        self.assertEqual(self.adapter.retain_outcome(retain), {"retained": True})
        self.assert_operation("PUT", "/v1/runtime/outcome")
        self.assertEqual(self.adapter.reflect(reflection), {"accepted": True})
        self.assert_operation("PUT", "/v1/runtime/reflection")
        before = len(getattr(self.adapter, "calls", getattr(self, "seen", [])))
        self.assertEqual(self.adapter.retain_outcome(retain), {"retained": True})
        after = len(getattr(self.adapter, "calls", getattr(self, "seen", [])))
        self.assertEqual(after, before)
        with self.assertRaisesRegex(AdapterError, "digest drift"):
            self.adapter.retain_outcome({**retain, "outcome": "changed"})

    def test_runtime_memory_payloads_are_closed(self):
        with self.assertRaisesRegex(AdapterError, "schema"):
            self.adapter.recall({"query": "q", "endpoint": "http://forbidden"})
        with self.assertRaisesRegex(AdapterError, "schema"):
            self.adapter.retain_outcome({
                "document_id": "d", "epoch": 1, "checkpoint": 1, "outcome": "done",
                "idempotency_key": "a" * 64, "token": "forbidden",
            })

    def test_create_verify_and_restore_rollback(self):
        bundle = self.adapter.create_rollback_bundle("a" * 64, ("action-1",))
        self.assertIsInstance(bundle, RollbackBundle)
        self.assertTrue(self.adapter.verify_rollback_bundle(bundle))
        self.adapter.restore(bundle)
        self.assert_rollback_contract(bundle)


class FakeAdapterContractTest(AdapterContractMixin, unittest.TestCase):
    def setUp(self):
        self.endpoint = EndpointIdentity("core", "http", "127.0.0.1", 7979, "default")
        self.operations = {"idle": True, "active": []}
        self.state = {
            "config": {"mode": "safe"}, "stats": {"count": 2}, "tags": {"tags": ["a"]},
            "scopes": {"scopes": ["s"]}, "documents": {"documents": [{"id": "d"}]},
            "models": {"models": [{"id": "m0"}]}, "directives": {"directives": [{"id": "r0"}]},
            "invalidated_memories": {"invalidated_memories": [{"id": "i"}]}, "template": {"template": "exported"},
        }
        self.adapter = FakeAdapter(endpoint=self.endpoint.to_dict(), state=self.state, operations=self.operations)

    def assert_operation(self, method, path):
        expected = {
            "/v1/schema": "schema_version", "/v1/identity": "endpoint_identity", "/v1/config": "read_config" if method == "GET" else "patch_config",
            "/v1/stats": "read_stats", "/v1/tags": "read_tags", "/v1/scopes": "read_scopes", "/v1/documents": "read_documents",
            "/v1/models": "read_models" if method == "GET" else "upsert_model", "/v1/directives": "read_directives" if method == "GET" else "upsert_directive",
            "/v1/operations": "read_operations", "/v1/templates/dry-run": "template_dry_run", "/v1/templates/export": "export_template",
            "/v1/templates/import": "import_template", "/v1/documents/transfer": "transfer_documents",
            "/v1/memories/invalidated": "read_invalidated_memories", "/v1/memories/invalidated/reapply": "reapply_invalidated_memories",
            "/v1/banks": "delete_bank",
            "/v1/runtime/recall": "recall", "/v1/runtime/mental-model": "mental_model_fetch",
            "/v1/runtime/session-status": "session_status", "/v1/runtime/transcript-checkpoint": "transcript_checkpoint",
            "/v1/runtime/outcome": "retain_outcome", "/v1/runtime/reflection": "reflect",
        }[path]
        self.assertEqual(self.adapter.calls[-1]["method"], expected)
        self.assertNotIn("top-secret", json.dumps(self.adapter.calls))

    def assert_rollback_contract(self, bundle):
        self.assertEqual([call["method"] for call in self.adapter.calls[-3:]],
                         ["create_rollback_bundle", "verify_rollback_bundle", "restore"])
        self.assertNotIn("documents", json.dumps(self.adapter.calls[-3:]))


class HttpAdapterContractTest(AdapterContractMixin, unittest.TestCase):
    def setUp(self):
        self.seen = []
        self.operations = {"idle": True, "active": []}
        state = {
            "config": {"mode": "safe"}, "stats": {"count": 2}, "tags": {"tags": ["a"]},
            "scopes": {"scopes": ["s"]}, "documents": {"documents": [{"id": "d"}]},
            "models": {"models": [{"id": "m0"}]}, "directives": {"directives": [{"id": "r0"}]},
            "invalidated_memories": {"invalidated_memories": [{"id": "i"}]}, "template": {"template": "exported"},
        }
        responses = {
            ("GET", "/v1/schema"): {"schema_version": 1}, ("GET", "/v1/state"): state,
            ("GET", "/v1/config"): state["config"], ("GET", "/v1/stats"): state["stats"],
            ("GET", "/v1/tags"): state["tags"], ("GET", "/v1/scopes"): state["scopes"],
            ("GET", "/v1/documents"): state["documents"], ("GET", "/v1/models"): state["models"],
            ("GET", "/v1/directives"): state["directives"], ("GET", "/v1/operations"): self.operations,
            ("GET", "/v1/memories/invalidated"): state["invalidated_memories"], ("GET", "/v1/templates/export"): state["template"],
            ("POST", "/v1/templates/dry-run"): {"valid": True, "digest": digest({"template": "t"})},
            ("POST", "/v1/templates/import"): {"imported": True}, ("PATCH", "/v1/config"): {"mode": "active"},
            ("PUT", "/v1/models"): {"upserted": "m"}, ("PUT", "/v1/directives"): {"upserted": "r"},
            ("POST", "/v1/documents/transfer"): {"transferred": 2},
            ("POST", "/v1/memories/invalidated/reapply"): {"reapplied": 2}, ("DELETE", "/v1/banks"): {"deleted": True},
            ("POST", "/v1/runtime/recall"): {"memories": [{"id": "m1"}]},
            ("POST", "/v1/runtime/mental-model"): {"models": [{"id": "model1"}]},
            ("POST", "/v1/runtime/session-status"): {"status": "ready"},
            ("PUT", "/v1/runtime/transcript-checkpoint"): {"applied": True},
            ("PUT", "/v1/runtime/outcome"): {"retained": True},
            ("PUT", "/v1/runtime/reflection"): {"accepted": True},
        }

        class Handler(BaseHTTPRequestHandler):
            def _serve(handler):
                length = int(handler.headers.get("Content-Length", "0"))
                request_body = json.loads(handler.rfile.read(length) or b"{}")
                self.seen.append((handler.command, handler.path, handler.headers.get("Authorization"), request_body))
                if handler.path == "/v1/identity":
                    value = self.endpoint.to_dict()
                elif handler.path == "/v1/rollbacks":
                    body = {"rollback_id": "server-rb-1", "plan_digest": request_body["plan_digest"], "action_ids": request_body["action_ids"],
                            "prestate_digest": digest(state), "endpoint_digest": digest(self.endpoint.to_dict())}
                    bundle_digest = digest(body)
                    value = {**body, "bundle_digest": bundle_digest, "restore_proof_digest": digest({"bundle_digest": bundle_digest})}
                elif handler.path.endswith("/verify"):
                    value = {"verified": True}
                elif handler.path.endswith("/restore"):
                    value = {"restored": True}
                else:
                    value = responses[(handler.command, handler.path)]
                raw = json.dumps(value).encode()
                handler.send_response(200)
                handler.send_header("Content-Length", str(len(raw)))
                handler.end_headers()
                handler.wfile.write(raw)
            do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _serve
            def log_message(self, *_args): pass

        self.server = start_http_server(self, Handler)
        self.endpoint = EndpointIdentity("core", "http", "127.0.0.1", self.server.server_port, "default")
        self.state = state
        self.adapter = HttpAdapter(inventory=inventory_for(self.server.server_port), profile_id="core", token_resolver=lambda: "contract-token")

    def assert_operation(self, method, path):
        self.assertEqual(self.seen[-1][:3], (method, path, "Bearer contract-token"))

    def assert_rollback_contract(self, bundle):
        self.assertEqual([(item[0], item[1]) for item in self.seen[-3:]], [
            ("POST", "/v1/rollbacks"),
            ("POST", f"/v1/rollbacks/{bundle.rollback_id}/verify"),
            ("POST", f"/v1/rollbacks/{bundle.rollback_id}/restore"),
        ])
        self.assertEqual(self.seen[-1][3], bundle.to_dict())


class HttpAdapterSecurityTest(unittest.TestCase):
    def test_http_error_response_is_closed_after_authentication_failure(self):
        adapter = HttpAdapter(
            inventory=inventory_for(7979),
            profile_id="core",
            token_resolver=lambda: "token",
        )
        response_body = BytesIO(b'{}')
        failure = HTTPError(
            "http://127.0.0.1:7979/v1/schema",
            401,
            "Unauthorized",
            {},
            response_body,
        )
        with patch("hindsight_memory_control_plane.http_adapter.urlopen", side_effect=failure):
            with self.assertRaises(AuthenticationError):
                adapter.schema_version()
        self.assertTrue(response_body.closed)

    def assert_rollback_id_rejected(self, rollback_id):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(self.path)
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length))
                value = {
                    "rollback_id": rollback_id,
                    "plan_digest": request["plan_digest"],
                    "action_ids": request["action_ids"],
                    "prestate_digest": "b" * 64,
                    "endpoint_digest": "c" * 64,
                    "bundle_digest": "d" * 64,
                    "restore_proof_digest": "e" * 64,
                }
                body = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_args): pass

        server = start_http_server(self, Handler)
        adapter = HttpAdapter(inventory=inventory_for(server.server_port), profile_id="core", token_resolver=lambda: "token")
        with self.assertRaisesRegex(AdapterError, "rollback attestation"):
            adapter.create_rollback_bundle("a" * 64, ("action-1",))
        forged = RollbackBundle(rollback_id, "a" * 64, ("action-1",), "b" * 64, "c" * 64, "d" * 64, "e" * 64)
        with self.assertRaisesRegex(AdapterError, "rollback attestation"):
            adapter.verify_rollback_bundle(forged)
        with self.assertRaisesRegex(AdapterError, "rollback attestation"):
            adapter.restore(forged)
        self.assertEqual(requests, ["/v1/rollbacks"])

    def test_rollback_id_rejects_slash(self):
        self.assert_rollback_id_rejected("safe/escape")

    def test_rollback_id_rejects_query(self):
        self.assert_rollback_id_rejected("safe?query=1")

    def test_rollback_id_rejects_fragment(self):
        self.assert_rollback_id_rejected("safe#fragment")

    def test_rollback_id_rejects_control_character(self):
        self.assert_rollback_id_rejected("safe\nprivate")

    def test_rollback_id_rejects_oversized_value(self):
        self.assert_rollback_id_rejected("a" * 129)

    def test_endpoint_must_be_derived_from_inventory_and_scheme_policy(self):
        with self.assertRaisesRegex(AdapterError, "digests"):
            HttpAdapter(inventory=replace(inventory_for(7979), inventory_digest="0" * 64), profile_id="core", token_resolver=lambda: "token")
        with self.assertRaisesRegex(AdapterError, "loopback"):
            HttpAdapter(inventory=inventory_for(80, host="example.com"), profile_id="core", token_resolver=lambda: "token")
        with self.assertRaisesRegex(AdapterError, "scheme"):
            HttpAdapter(inventory=inventory_for(80, scheme="ftp"), profile_id="core", token_resolver=lambda: "token")
        with self.assertRaisesRegex(AdapterError, "approved"):
            HttpAdapter(inventory=inventory_for(443, scheme="https", host="example.com"), profile_id="core", token_resolver=lambda: "token")
        approved = HttpAdapter(inventory=inventory_for(443, scheme="https", host="example.com", approved_tls=True), profile_id="core", token_resolver=lambda: "token")
        self.assertEqual(approved.endpoint.host, "example.com")

    def test_iterencoded_request_is_stopped_at_byte_bound_before_network(self):
        class Handler(BaseHTTPRequestHandler):
            def do_PATCH(self):
                self.send_response(500)
                self.end_headers()
            def log_message(self, *_args): pass
        server = start_http_server(self, Handler)
        adapter = HttpAdapter(inventory=inventory_for(server.server_port), profile_id="core", token_resolver=lambda: "token", max_json_bytes=32)
        with self.assertRaisesRegex(AdapterError, "request exceeds"):
            adapter.patch_config({"value": "x" * 100_000})
        self.assertEqual(adapter.recordings, [])

    def test_invalid_content_length_is_normalized(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "invalid")
                self.end_headers()
                self.wfile.write(b"{}")
            def log_message(self, *_args): pass
        server = start_http_server(self, Handler)
        adapter = HttpAdapter(inventory=inventory_for(server.server_port), profile_id="core", token_resolver=lambda: "token")
        with self.assertRaisesRegex(AdapterError, "Content-Length"):
            adapter.read_config()

    def test_non_object_json_is_normalized(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"[]"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_args): pass
        server = start_http_server(self, Handler)
        adapter = HttpAdapter(inventory=inventory_for(server.server_port), profile_id="core", token_resolver=lambda: "token")
        with self.assertRaisesRegex(AdapterError, "non-object"):
            adapter.read_config()

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

        server = start_http_server(self, Handler)
        adapter = HttpAdapter(inventory=inventory_for(server.server_port), profile_id="core", token_resolver=lambda: token)

        self.assertEqual(adapter.read_config(), {"mode": "safe"})
        self.assertEqual(seen, [("/v1/config", f"Bearer {token}")])
        self.assertNotIn(token, repr(adapter))
        self.assertNotIn(token, json.dumps(adapter.recordings))

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

        server = start_http_server(self, Handler)
        adapter = HttpAdapter(inventory=inventory_for(server.server_port), profile_id="core", token_resolver=lambda: token, max_json_bytes=1024, timeout=100)
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

        server = start_http_server(self, Handler)
        adapter = HttpAdapter(inventory=inventory_for(server.server_port), profile_id="core", token_resolver=lambda: "timeout-secret", timeout=0.1)
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
    def test_adapter_attested_stale_prestate_bundle_is_refused_before_mutation(self):
        plan = plan_for({"version": "fresh"})
        adapter = self.adapter(state={"version": "stale"})
        bundle = create_rollback_bundle(plan, adapter)
        adapter.state = {"version": "fresh"}

        result = apply_plan(plan, adapter, plan.plan_digest, {"rollback_bundle": bundle})

        self.assertEqual(result.reason, "rollback_prestate_mismatch")
        self.assertNotIn("create_bank", [call["method"] for call in adapter.calls])

    def test_adapter_attested_stale_endpoint_bundle_is_refused_before_mutation(self):
        plan = plan_for({})
        adapter = self.adapter()
        adapter.endpoint = EndpointIdentity("core", "http", "127.0.0.1", 7980, "default")
        bundle = create_rollback_bundle(plan, adapter)
        adapter.endpoint = plan.target_endpoint

        result = apply_plan(plan, adapter, plan.plan_digest, {"rollback_bundle": bundle})

        self.assertEqual(result.reason, "rollback_endpoint_mismatch")
        self.assertNotIn("create_bank", [call["method"] for call in adapter.calls])

    def test_fake_applies_digest_verified_migration_only_with_matching_gate(self):
        from hindsight_memory_control_plane.reconcile import build_mutation_plan

        adapter = self.adapter()
        base = plan_for({})
        mutation = build_mutation_plan(
            base,
            migration_run_id="run-1",
            actions=[{"id": "migrate-1", "kind": "migrate_bank", "artifact_digest": base.artifact_digest}],
        )
        rollback = create_rollback_bundle(mutation, adapter)
        matching = {
            "rollback_bundle": rollback,
            "migration_gate": {
                "export": {"run_id": "run-1", "artifact_digest": base.artifact_digest},
                "import": {"run_id": "run-1", "artifact_digest": base.artifact_digest},
            },
        }

        self.assertEqual(apply_plan(mutation, adapter, mutation.plan_digest, matching).status, "applied")
        self.assertEqual(apply_plan(mutation, adapter, mutation.plan_digest, {"rollback_bundle": rollback}).reason, "migration_gate_required")

    def test_mutation_plan_deserialization_is_closed_and_digest_verified(self):
        from hindsight_memory_control_plane.reconcile import build_mutation_plan, mutation_plan_from_dict
        base = plan_for({})
        mutation = build_mutation_plan(base, migration_run_id="run-1", actions=[
            {"id": "migrate-1", "kind": "migrate_bank", "artifact_digest": base.artifact_digest},
        ])
        self.assertEqual(mutation_plan_from_dict(mutation.to_dict()), mutation)
        unknown = {**mutation.to_dict(), "payload": "forbidden"}
        with self.assertRaisesRegex(ApplyError, "closed"):
            mutation_plan_from_dict(unknown)
        tampered = {**mutation.to_dict(), "migration_run_id": "run-2"}
        with self.assertRaisesRegex(ApplyError, "digest"):
            mutation_plan_from_dict(tampered)

    def test_mutation_action_id_rejects_oversized_identifier(self):
        from hindsight_memory_control_plane.reconcile import build_mutation_plan
        base = plan_for({})
        with self.assertRaisesRegex(ApplyError, "action id"):
            build_mutation_plan(base, migration_run_id="run-1", actions=[
                {"id": "a" * 129, "kind": "migrate_bank", "artifact_digest": base.artifact_digest},
            ])

    def test_mutation_action_id_rejects_payload_like_identifier(self):
        from hindsight_memory_control_plane.reconcile import build_mutation_plan
        base = plan_for({})
        with self.assertRaisesRegex(ApplyError, "action id"):
            build_mutation_plan(base, migration_run_id="run-1", actions=[
                {"id": "payload={secret}", "kind": "migrate_bank", "artifact_digest": base.artifact_digest},
            ])

    def test_mutation_action_id_rejects_control_characters(self):
        from hindsight_memory_control_plane.reconcile import build_mutation_plan
        base = plan_for({})
        with self.assertRaisesRegex(ApplyError, "action id"):
            build_mutation_plan(base, migration_run_id="run-1", actions=[
                {"id": "migration\nprivate", "kind": "migrate_bank", "artifact_digest": base.artifact_digest},
            ])

    def test_valid_mutation_action_id_remains_ledger_safe(self):
        from hindsight_memory_control_plane.reconcile import build_mutation_plan
        base = plan_for({})
        adapter = self.adapter()
        mutation = build_mutation_plan(base, migration_run_id="run-1", actions=[
            {"id": "migration-01.safe", "kind": "migrate_bank", "artifact_digest": base.artifact_digest},
        ])
        rollback = create_rollback_bundle(mutation, adapter)
        gate = {"rollback_bundle": rollback, "migration_gate": {
            "export": {"run_id": "run-1", "artifact_digest": base.artifact_digest},
            "import": {"run_id": "run-1", "artifact_digest": base.artifact_digest},
        }}
        result = apply_plan(mutation, adapter, mutation.plan_digest, gate)
        self.assertEqual(result.status, "applied")
        self.assertEqual(result.ledger, (
            {"action_id": "migration-01.safe", "status": "applied"},
            {"action_id": "migration-01.safe", "status": "verified"},
        ))
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
        self.assertIsNone(result.activation_enabled)
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
        unproved = self.adapter(state={"documents": []}, restore_proof_valid=False)
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

    def test_migration_gate_mismatch_is_refused_through_apply_boundary(self):
        from hindsight_memory_control_plane.reconcile import build_mutation_plan
        adapter = self.adapter()
        base = plan_for({})
        mutation = build_mutation_plan(base, migration_run_id="run-1", actions=[
            {"id": "migrate-1", "kind": "migrate_bank", "artifact_digest": base.artifact_digest},
        ])
        rollback = create_rollback_bundle(mutation, adapter)
        gate = {
            "rollback_bundle": rollback,
            "migration_gate": {
                "export": {"run_id": "run-1", "artifact_digest": base.artifact_digest},
                "import": {"run_id": "run-2", "artifact_digest": base.artifact_digest},
            },
        }
        self.assertEqual(apply_plan(mutation, adapter, mutation.plan_digest, gate).reason, "migration_gate_mismatch")

    def test_caller_cannot_forge_restore_proof(self):
        adapter = self.adapter(state={"documents": []}, restore_proof_valid=True)
        plan = plan_for({"documents": []})
        bundle = create_rollback_bundle(plan, adapter)
        forged = replace(bundle, restore_proof_digest="f" * 64)
        result = apply_plan(plan, adapter, plan.plan_digest, {"rollback_bundle": forged})
        self.assertEqual(result.reason, "disposable_restore_proof_required")

    def test_any_ordinary_exception_after_mutation_attempts_rollback(self):
        class ExplodingFake(FakeAdapter):
            def apply_action(self, action):
                self.state["partial"] = True
                raise ValueError("private payload must not escape")
        adapter = ExplodingFake(endpoint={"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"})
        plan = plan_for({})
        bundle = create_rollback_bundle(plan, adapter)
        result = apply_plan(plan, adapter, plan.plan_digest, {"rollback_bundle": bundle})
        self.assertEqual(result.status, "rolled_back")
        self.assertEqual(adapter.state, {})
        self.assertNotIn("private payload", result.reason)

    def test_rollback_and_activation_disable_failure_leave_activation_unknown(self):
        adapter = self.adapter()
        plan = plan_for({})
        bundle = create_rollback_bundle(plan, adapter)
        adapter.fail_postcondition_for = "01-create"
        adapter.fail_restore = True
        adapter.fail_disable_activation = True
        result = apply_plan(plan, adapter, plan.plan_digest, {"rollback_bundle": bundle})
        self.assertEqual(result.status, "operator_blocked")
        self.assertIsNone(result.activation_enabled)


if __name__ == "__main__":
    unittest.main()
