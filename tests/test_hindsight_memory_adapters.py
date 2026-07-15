import json
import hashlib
from io import BytesIO
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import ssl
import stat
import subprocess
from urllib.error import HTTPError
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_ARTIFACT_DIGEST = "3" * 64
SOURCE_BANK_REF = {"profile_id": "core", "bank_id": "historical-candidate"}
TARGET_BANK_REF = {"profile_id": "core", "bank_id": "engineering"}
LIB = ROOT / "home/private_dot_local/lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from hindsight_memory_control_plane.adapters import AdapterError, AuthenticationError, FakeAdapter, RollbackBundle
from hindsight_memory_control_plane.http_adapter import HttpAdapter
from hindsight_memory_control_plane.file_evidence import (
    FileEvidenceError,
    reject_symlink_components,
    verified_file_snapshot,
)
from hindsight_memory_control_plane.migration_adapter import (
    AdminMigrationAdapter,
    MigrationAdapterError,
    MigrationApplyAdapter,
    hindsight_admin_argv,
)
from hindsight_memory_control_plane.canonical import digest
from hindsight_memory_control_plane.model import Action, BankRef, EndpointIdentity, Inventory, OperationSnapshot, Plan
from hindsight_memory_control_plane.reconcile import (
    ApplyError,
    apply_plan,
    capture_migration_gate,
    create_rollback_bundle,
    parse_migration_gate,
)


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


def mutation_action(identifier="migrate-1", artifact_digest=MIGRATION_ARTIFACT_DIGEST,
                    archive_digest="4" * 64):
    evidence = restore_evidence(archive_digest)
    return {
        "id": identifier,
        "kind": "migrate_bank",
        "artifact_digest": artifact_digest,
        "archive_digest": archive_digest,
        "restore_evidence_digest": digest(evidence),
        "source_bank": SOURCE_BANK_REF,
        "target_bank": TARGET_BANK_REF,
    }


def restore_evidence(artifact_digest, receipt_digest="7" * 64):
    return {
        "schema_version": 1,
        "artifact_digest": artifact_digest,
        "verification_receipt_digest": receipt_digest,
    }


def admin_argv(executable, operation, archive, bank_id):
    return {
        "export-bank": [
            executable, "export-bank", "--bank", bank_id,
            "--output", archive,
        ],
        "import-bank": [
            executable, "import-bank", "--archive", archive,
            "--target-bank", bank_id,
        ],
        "backup": [
            executable, "backup", archive, "--schema", "public",
        ],
        "restore": [
            executable, "restore", archive, "--schema", "public", "--yes",
        ],
    }[operation]


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


def write_migration_gate(root, run_id, artifact_digest):
    artifact_dir = root / "artifacts"
    artifact_dir.mkdir(parents=True)
    marker = artifact_dir / "distillation-complete.marker"
    proposal = root / "proposal-log.md"
    marker.write_text(f"run={run_id}\nartifact={artifact_digest}\n", encoding="utf-8")
    proposal.write_text(
        f"# Migration proposals\n\n## Migration complete\nrun={run_id}\nartifact={artifact_digest}\n",
        encoding="utf-8",
    )
    return capture_migration_gate(marker, proposal), marker, proposal


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
            "migration_inventory": {"schema_version": 1, "banks": ["engineering", "historical-candidate"]},
        }
        self.adapter = FakeAdapter(endpoint=self.endpoint.to_dict(), state=self.state, operations=self.operations)

    def test_read_migration_inventory_is_bank_scoped_and_read_only(self):
        source = BankRef("core", "engineering")
        candidate = BankRef("core", "historical-candidate")
        self.assertEqual(
            self.adapter.read_migration_inventory(source, candidate),
            {"schema_version": 1, "banks": ["engineering", "historical-candidate"]},
        )
        self.assertEqual(self.adapter.calls[-1]["method"], "read_migration_inventory")
        self.assertEqual(
            self.adapter.calls[-1]["metadata"],
            {"source_bank": source.to_dict(), "candidate_bank": candidate.to_dict()},
        )

    def test_committed_mutations_advance_migration_generation(self):
        adapter = FakeAdapter(
            endpoint=self.endpoint.to_dict(),
            state={"migration_generation": "generation-1"},
        )
        generations = [adapter.read_migration_generation()]
        mutations = (
            lambda: adapter.import_template({"template": "value"}),
            lambda: adapter.patch_config({"mode": "active"}),
            lambda: adapter.upsert_model({"id": "model-1"}),
            lambda: adapter.upsert_directive({"id": "directive-1"}),
            lambda: adapter.transfer_documents({"count": 1}),
            lambda: adapter.reapply_invalidated_memories({"count": 1}),
            lambda: adapter.delete_bank({"bank_id": "retired"}),
        )
        for mutate in mutations:
            mutate()
            generations.append(adapter.read_migration_generation())

        runtime_writes = (
            (
                adapter.transcript_checkpoint,
                {
                    "document_id": "document-1",
                    "epoch": 1,
                    "checkpoint": 1,
                    "idempotency_key": "a" * 64,
                },
            ),
            (
                adapter.retain_outcome,
                {
                    "document_id": "document-1",
                    "epoch": 1,
                    "checkpoint": 1,
                    "outcome": "done",
                    "idempotency_key": "b" * 64,
                },
            ),
            (
                adapter.reflect,
                {"reflection": "note", "idempotency_key": "c" * 64},
            ),
        )
        for mutate, request in runtime_writes:
            mutate(request)
            committed_generation = adapter.read_migration_generation()
            generations.append(committed_generation)
            mutate(request)
            self.assertEqual(
                adapter.read_migration_generation(), committed_generation
            )

        self.assertEqual(len(generations), len(set(generations)))

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
        responses[("GET", "/version")] = {"api_version": "0.8.4", "features": {"observations": True}}
        responses[("GET", "/v1/migration/generation")] = {"generation": "commit-42"}
        for index, bank_id in enumerate(("engineering", "historical-candidate"), start=1):
            base = f"/v1/default/banks/{bank_id}"
            responses[("GET", f"{base}/config")] = {
                "bank_id": bank_id,
                "config": {
                    "recall_max_tokens": 4096,
                    "api_key": "top-secret",
                    "provider": {"api_key": "nested-secret", "model": "safe-model"},
                },
                "overrides": {},
            }
            responses[("GET", f"{base}/stats")] = {"bank_id": bank_id, "total_documents": 1}
            responses[("GET", f"{base}/observations/scopes")] = {"scopes": []}
            responses[("GET", f"{base}/tags?limit=1000&offset=0")] = {
                "items": [{"tag": "repo:dotfiles", "count": 1}], "total": 1, "limit": 1000, "offset": 0,
            }
            responses[("GET", f"{base}/documents?limit=1000&offset=0")] = {
                "items": [{
                    "id": f"document-{index}", "updated_at": "2026-07-13T12:00:00Z",
                    "content_hash": str(index) * 64, "created_at": "2026-07-13T11:00:00Z",
                    "text_length": 12, "memory_unit_count": 1, "tags": [],
                    "document_metadata": {}, "retain_params": {},
                }],
                "total": 1, "limit": 1000, "offset": 0,
            }
            responses[("GET", f"{base}/mental-models?detail=full&limit=1000&offset=0")] = {"items": []}
            responses[("GET", f"{base}/directives?active_only=false&limit=1000&offset=0")] = {"items": []}
            responses[("GET", f"{base}/webhooks")] = {"items": []}
            responses[("GET", f"{base}/memories/list?state=invalidated&limit=1000&offset=0")] = {
                "items": [], "total": 0, "limit": 1000, "offset": 0,
            }
            for status in ("pending", "processing"):
                responses[("GET", f"{base}/operations?status={status}&limit=100&offset=0")] = {
                    "bank_id": bank_id, "operations": [], "total": 0, "limit": 100, "offset": 0,
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

    def test_read_migration_inventory_composes_documented_get_surfaces(self):
        before = len(self.seen)
        result = self.adapter.read_migration_inventory(
            BankRef("core", "engineering"),
            BankRef("core", "historical-candidate"),
        )
        self.assertEqual(result["schema_version"], 1)
        self.assertTrue(result["operations"]["idle"])
        self.assertEqual(result["versions"]["hindsight"], "0.8.4")
        self.assertEqual(result["provider_identity"]["profile_id"], "core")
        self.assertEqual(result["banks"]["source"]["bank_ref"]["bank_id"], "engineering")
        self.assertEqual(result["banks"]["candidate"]["bank_ref"]["bank_id"], "historical-candidate")
        self.assertEqual(result["banks"]["source"]["config"]["config"]["recall_max_tokens"], 4096)
        self.assertNotIn("api_key", result["banks"]["source"]["config"]["config"])
        self.assertNotIn("api_key", result["banks"]["source"]["config"]["config"]["provider"])
        self.assertEqual(result["banks"]["source"]["config"]["config"]["provider"]["model"], "safe-model")
        self.assertIn("config.provider.api_key", result["banks"]["source"]["config"]["redacted_keys"])
        calls = self.seen[before:]
        self.assertTrue(calls)
        self.assertTrue(all(method == "GET" for method, _path, _auth, _body in calls))
        self.assertFalse(any(path.startswith("/v1/migrations/") for _method, path, _auth, _body in calls))
        self.assertTrue(all(auth == "Bearer contract-token" for _method, _path, auth, _body in calls))

    def test_migration_generation_is_read_from_the_server(self):
        self.assertEqual(self.adapter.read_migration_generation(), "commit-42")
        self.assert_operation("GET", "/v1/migration/generation")

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
    def test_ambient_http_proxy_is_ignored(self):
        direct_requests = []
        proxy_requests = []

        class DirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                direct_requests.append(self.path)
                body = b'{"mode":"direct"}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_args): pass

        class ProxyHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                proxy_requests.append(self.path)
                body = b'{"mode":"proxied"}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_args): pass

        direct = start_http_server(self, DirectHandler)
        proxy = start_http_server(self, ProxyHandler)
        proxy_url = f"http://127.0.0.1:{proxy.server_port}"
        with patch.dict(
            os.environ,
            {"HTTP_PROXY": proxy_url, "http_proxy": proxy_url, "NO_PROXY": "", "no_proxy": ""},
            clear=False,
        ):
            adapter = HttpAdapter(
                inventory=inventory_for(direct.server_port), profile_id="core",
                token_resolver=lambda: "token",
            )
            self.assertEqual(adapter.read_config(), {"mode": "direct"})
        self.assertEqual(direct_requests, ["/v1/config"])
        self.assertEqual(proxy_requests, [])

    def test_redirect_is_rejected_before_bearer_token_reaches_another_hop(self):
        redirected_headers = []

        class TargetHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                redirected_headers.append(self.headers.get("Authorization"))
                body = b"{}"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_args): pass

        target = start_http_server(self, TargetHandler)

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{target.server_port}/redirected")
                self.end_headers()
            def log_message(self, *_args): pass

        source = start_http_server(self, RedirectHandler)
        adapter = HttpAdapter(
            inventory=inventory_for(source.server_port), profile_id="core",
            token_resolver=lambda: "do-not-forward",
        )
        with self.assertRaisesRegex(AdapterError, "redirect"):
            adapter.read_config()
        self.assertEqual(redirected_headers, [])

    def test_http_response_json_rejects_duplicate_keys_and_non_finite_numbers(self):
        bodies = iter((b'{"mode":"safe","mode":"changed"}', b'{"value":NaN}'))

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = next(bodies)
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_args): pass

        server = start_http_server(self, Handler)
        adapter = HttpAdapter(
            inventory=inventory_for(server.server_port), profile_id="core",
            token_resolver=lambda: "token",
        )
        for _ in range(2):
            with self.assertRaisesRegex(AdapterError, "invalid JSON"):
                adapter.read_config()

    def test_dedicated_tls_context_requires_certificate_and_hostname_validation(self):
        adapter = HttpAdapter(
            inventory=inventory_for(443, scheme="https", host="example.com", approved_tls=True),
            profile_id="core", token_resolver=lambda: "token",
        )
        context = adapter._tls_context
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_migration_generation_rejects_missing_or_malformed_server_tokens(self):
        responses = iter((
            b"{}",
            b'{"generation":""}',
            b'{"generation":"ok","extra":1}',
            b'{"generation":"\\ud800"}',
            b'{"generation":"control\\u001f"}',
        ))

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = next(responses)
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_args): pass

        server = start_http_server(self, Handler)
        adapter = HttpAdapter(
            inventory=inventory_for(server.server_port), profile_id="core",
            token_resolver=lambda: "token",
        )
        for _ in range(5):
            with self.assertRaisesRegex(AdapterError, "migration generation"):
                adapter.read_migration_generation()

    def test_artifact_action_resolves_and_verifies_desired_payload(self):
        desired = {"mode": "active", "limits": {"recall": 10}}
        action = Action(
            "configure-core", "configure_profile",
            {"profile_id": "core", "artifact_digest": digest(desired)},
        )
        adapter = HttpAdapter(
            inventory=inventory_for(7979), profile_id="core",
            token_resolver=lambda: "token", artifact_resolver=lambda _action: desired,
        )
        with patch.object(adapter, "patch_config", return_value={}) as mutate:
            adapter.apply_action(action)
        mutate.assert_called_once_with({"profile_id": "core", "desired": desired})

    def test_artifact_action_refuses_missing_or_mismatched_resolution(self):
        desired = {"mode": "active"}
        action = Action(
            "configure-core", "configure_profile",
            {"profile_id": "core", "artifact_digest": digest(desired)},
        )
        adapter = HttpAdapter(
            inventory=inventory_for(7979), profile_id="core", token_resolver=lambda: "token",
        )
        with self.assertRaisesRegex(AdapterError, "resolver is required"):
            adapter.apply_action(action)
        mismatched = HttpAdapter(
            inventory=inventory_for(7979), profile_id="core", token_resolver=lambda: "token",
            artifact_resolver=lambda _action: {"mode": "different"},
        )
        with self.assertRaisesRegex(AdapterError, "digest does not match"):
            mismatched.apply_action(action)

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
        with patch.object(adapter._opener, "open", side_effect=failure):
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
    def trusted_admin(self, root):
        executable = Path(root) / "hindsight-admin"
        executable.write_text(
            f"#!{sys.executable}\nraise SystemExit('test seam only')\n",
            encoding="utf-8",
        )
        executable.chmod(0o700)
        return executable

    @staticmethod
    def versioned_runner(calls, *, version="0.8.4", operation=None):
        def run(argv, **kwargs):
            calls.append((list(argv), kwargs))
            if "importlib.metadata" in argv[-1]:
                return subprocess.CompletedProcess(argv, 0, version + "\n", "")
            if operation is not None:
                operation(argv)
            return subprocess.CompletedProcess(argv, 0, "Complete", "")
        return run

    def make_admin(self, runner, *, argv_factory=admin_argv, version="0.8.4"):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        executable = self.trusted_admin(root)

        def routed(argv, **_kwargs):
            if "importlib.metadata" in argv[-1]:
                return subprocess.CompletedProcess(argv, 0, version + "\n", "")
            return runner(argv)

        return AdminMigrationAdapter(
            admin_executable=str(executable),
            argv_factory=argv_factory,
            runner=routed,
        ), str(executable)

    def test_binds_trusted_executable_probes_version_and_sanitizes_process_context(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        executable = self.trusted_admin(root)
        calls = []
        adapter = AdminMigrationAdapter(
            admin_executable=str(executable),
            argv_factory=hindsight_admin_argv,
            runner=self.versioned_runner(calls),
            environment={
                "HINDSIGHT_API_DATABASE_URL": "postgresql://approved",
                "PATH": "/attacker/bin",
                "PYTHONPATH": "/attacker/python",
                "UNRELATED_SECRET": "must-not-flow",
            },
        )
        adapter.backup("/tmp/bank.zip", "a" * 64)

        self.assertEqual(adapter.admin_version, "0.8.4")
        self.assertEqual(len(calls), 2)
        operation_argv, operation_kwargs = calls[1]
        self.assertEqual(operation_argv[0], str(executable))
        self.assertEqual(operation_argv[1:], ["backup", "/tmp/bank.zip", "--schema", "public"])
        for _argv, kwargs in calls:
            self.assertEqual(kwargs["cwd"], "/")
            self.assertEqual(
                kwargs["env"],
                {"HINDSIGHT_API_DATABASE_URL": "postgresql://approved"},
            )

    def test_revalidates_executable_identity_before_each_operation(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        executable = self.trusted_admin(root)
        calls = []
        adapter = AdminMigrationAdapter(
            admin_executable=str(executable), argv_factory=hindsight_admin_argv,
            runner=self.versioned_runner(calls),
        )
        replacement = root / "replacement"
        replacement.write_text(
            f"#!{sys.executable}\nraise SystemExit('replacement')\n",
            encoding="utf-8",
        )
        replacement.chmod(0o700)
        os.replace(replacement, executable)

        with self.assertRaisesRegex(MigrationAdapterError, "identity changed"):
            adapter.backup("/tmp/bank.zip", "a" * 64)
        self.assertEqual(len(calls), 1)

    def test_reports_admin_operation_timeout_without_process_output(self):
        def timeout(_argv):
            raise subprocess.TimeoutExpired(
                cmd=["hindsight-admin"], timeout=300, output="private output"
            )

        adapter, _ = self.make_admin(timeout)
        with self.assertRaisesRegex(MigrationAdapterError, "operation timed out"):
            adapter.backup("/tmp/bank.zip", "a" * 64)

    def test_rejects_relative_symlink_untrusted_and_unknown_version_executables(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        executable = self.trusted_admin(root)
        runner = self.versioned_runner([])
        with self.assertRaisesRegex(MigrationAdapterError, "absolute"):
            AdminMigrationAdapter(
                admin_executable="hindsight-admin", argv_factory=hindsight_admin_argv,
                runner=runner,
            )
        symlink = root / "admin-link"
        symlink.symlink_to(executable)
        with self.assertRaisesRegex(MigrationAdapterError, "symlink"):
            AdminMigrationAdapter(
                admin_executable=str(symlink), argv_factory=hindsight_admin_argv,
                runner=runner,
            )
        executable.chmod(0o722)
        with self.assertRaisesRegex(MigrationAdapterError, "writable"):
            AdminMigrationAdapter(
                admin_executable=str(executable), argv_factory=hindsight_admin_argv,
                runner=runner,
            )
        executable.chmod(0o700)
        with self.assertRaisesRegex(MigrationAdapterError, "unsupported"):
            AdminMigrationAdapter(
                admin_executable=str(executable), argv_factory=hindsight_admin_argv,
                runner=self.versioned_runner([], version="0.9.0"),
            )

    def test_mutation_apply_adapter_imports_the_digest_selected_archive(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        approved_archive = root / "approved-bank.zip"
        approved_payload = b"approved migration archive"
        approved_archive.write_bytes(approved_payload)
        approved_archive.chmod(0o600)
        archive_digest = hashlib.sha256(approved_payload).hexdigest()
        evidence = restore_evidence(archive_digest)
        rollback_digest = "f" * 64
        rollback_evidence = restore_evidence(rollback_digest, "8" * 64)
        observed = {}

        def run_admin(argv):
            snapshot = Path(argv[3])
            observed.update({
                "path": snapshot,
                "payload": snapshot.read_bytes(),
                "mode": snapshot.stat().st_mode & 0o777,
                "parent_mode": snapshot.parent.stat().st_mode & 0o777,
            })
            return {"returncode": 0, "stdout": "Import complete"}

        admin, _ = self.make_admin(run_admin)
        data_plane = FakeAdapter(
            endpoint={"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"},
        )
        adapter = MigrationApplyAdapter(
            data_plane=data_plane, admin=admin,
            archives={archive_digest: str(approved_archive)},
            restore_evidence={archive_digest: evidence},
            rollback_archive=str(root / "pre-state-backup.zip"),
            rollback_archive_digest=rollback_digest,
            rollback_restore_evidence_digest=digest(rollback_evidence),
            archive_verifier=lambda _path, _digest: True,
        )
        action = Action(
            "migrate", "migrate_bank",
            {
                "artifact_digest": "b" * 64,
                "archive_digest": archive_digest,
                "restore_evidence_digest": digest(evidence),
                "source_bank": SOURCE_BANK_REF,
                "target_bank": TARGET_BANK_REF,
            },
        )

        adapter.apply_action(action)

        self.assertEqual(admin.calls, [{
            "operation": "import-bank",
            "archive_digest": archive_digest,
            "bank_id": "engineering",
        }])
        self.assertNotEqual(observed["path"], approved_archive)
        self.assertEqual(observed["payload"], approved_payload)
        self.assertEqual(observed["mode"], 0o400)
        self.assertEqual(observed["parent_mode"], 0o700)
        self.assertFalse(observed["path"].exists())
        self.assertNotIn("migrate_bank", [call["method"] for call in data_plane.calls])
        missing = MigrationApplyAdapter(
            data_plane=data_plane, admin=admin, archives={}, restore_evidence={},
            rollback_archive=str(root / "pre-state-backup.zip"),
            rollback_archive_digest=rollback_digest,
            rollback_restore_evidence_digest=digest(rollback_evidence),
            archive_verifier=lambda _path, _digest: True,
        )
        with self.assertRaisesRegex(MigrationAdapterError, "unavailable"):
            missing.apply_action(action)

        unverified = MigrationApplyAdapter(
            data_plane=data_plane, admin=admin,
            archives={archive_digest: str(approved_archive)},
            restore_evidence={archive_digest: evidence},
            rollback_archive=str(root / "pre-state-backup.zip"),
            rollback_archive_digest=rollback_digest,
            rollback_restore_evidence_digest=digest(rollback_evidence),
            archive_verifier=lambda _path, _digest: False,
        )
        with self.assertRaisesRegex(MigrationAdapterError, "archive digest"):
            unverified.apply_action(action)

    def test_mutation_apply_adapter_creates_and_uses_admin_rollback(self):
        from hindsight_memory_control_plane.reconcile import build_mutation_plan

        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        incoming_archive = root / "incoming-bank.zip"
        incoming_payload = b"incoming migration archive"
        incoming_archive.write_bytes(incoming_payload)
        incoming_archive.chmod(0o600)
        rollback_archive = root / "pre-state-backup.zip"
        rollback_payload = b"rollback schema archive"
        incoming_digest = hashlib.sha256(incoming_payload).hexdigest()
        rollback_digest = hashlib.sha256(rollback_payload).hexdigest()
        evidence = {
            incoming_digest: restore_evidence(incoming_digest),
            rollback_digest: restore_evidence(rollback_digest),
        }
        operations = []
        def run_admin(argv):
            operations.append(argv[1])
            if argv[1] == "backup":
                Path(argv[2]).write_bytes(rollback_payload)
                Path(argv[2]).chmod(0o600)
            return {"returncode": 0, "stdout": "Complete"}

        admin, _ = self.make_admin(run_admin)
        data_plane = FakeAdapter(
            endpoint={"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"},
        )
        data_plane.fail_postcondition_for = "migrate"
        adapter = MigrationApplyAdapter(
            data_plane=data_plane, admin=admin,
            archives={incoming_digest: str(incoming_archive)},
            restore_evidence=evidence,
            rollback_archive=str(rollback_archive),
            rollback_archive_digest=rollback_digest,
            rollback_restore_evidence_digest=digest(evidence[rollback_digest]),
            archive_verifier=lambda _path, _digest: True,
        )
        base = plan_for({})
        plan = build_mutation_plan(
            base, migration_run_id="run-1",
            migration_artifact_digest=MIGRATION_ARTIFACT_DIGEST,
            rollback_archive_digest=rollback_digest,
            rollback_restore_evidence_digest=digest(evidence[rollback_digest]),
            actions=[mutation_action("migrate", archive_digest=incoming_digest)],
        )
        with tempfile.TemporaryDirectory() as temporary:
            descriptor, _, _ = write_migration_gate(
                Path(temporary), "run-1", MIGRATION_ARTIFACT_DIGEST,
            )
            rollback = create_rollback_bundle(plan, adapter)
            result = apply_plan(
                plan, adapter, plan.plan_digest,
                {"rollback_bundle": rollback, "migration_gate": descriptor},
            )

        self.assertEqual(result.status, "rolled_back")
        self.assertEqual(operations, ["backup", "import-bank", "restore"])

        changed_evidence = dict(evidence)
        changed_evidence[rollback_digest] = restore_evidence(
            rollback_digest, "9" * 64,
        )
        changed_adapter = MigrationApplyAdapter(
            data_plane=FakeAdapter(
                endpoint={
                    "profile_id": "core", "scheme": "http",
                    "host": "127.0.0.1", "port": 7979, "tenant": "default",
                },
            ),
            admin=admin,
            archives={incoming_digest: str(incoming_archive)},
            restore_evidence=changed_evidence,
            rollback_archive=str(rollback_archive),
            rollback_archive_digest=rollback_digest,
            rollback_restore_evidence_digest=digest(evidence[rollback_digest]),
            archive_verifier=lambda _path, _digest: True,
        )
        changed_bundle = changed_adapter.create_rollback_bundle(
            plan.plan_digest, ("migrate",),
        )
        self.assertFalse(changed_adapter.verify_rollback_bundle(changed_bundle))

    def test_accepts_only_digest_bound_argv_and_requires_restore_evidence(self):
        calls = []
        archive_digest = "a" * 64
        adapter, executable = self.make_admin(
            lambda argv: calls.append(argv) or {"returncode": 0, "stdout": "Complete"},
        )

        adapter.backup("/tmp/bank.zip", archive_digest)
        self.assertEqual(calls[0][:2], [executable, "backup"])
        with self.assertRaisesRegex(MigrationAdapterError, "disposable restore evidence"):
            adapter.restore(
                "/tmp/bank.zip",
                archive_digest,
                digest(restore_evidence(archive_digest)),
            )

    def test_rechecks_rollback_archive_immediately_before_restore(self):
        rollback_digest = "5" * 64
        evidence = restore_evidence(rollback_digest)
        checks = iter((True, False))
        calls = []
        admin, _ = self.make_admin(
            lambda argv: calls.append(argv[1])
            or {"returncode": 0, "stdout": "Complete"},
        )
        adapter = MigrationApplyAdapter(
            data_plane=FakeAdapter(
                endpoint={
                    "profile_id": "core", "scheme": "http",
                    "host": "127.0.0.1", "port": 7979, "tenant": "default",
                },
            ),
            admin=admin,
            archives={},
            restore_evidence={rollback_digest: evidence},
            rollback_archive="/tmp/pre-state-backup.tar",
            rollback_archive_digest=rollback_digest,
            rollback_restore_evidence_digest=digest(evidence),
            archive_verifier=lambda _path, _digest: next(checks),
        )
        rollback = adapter.create_rollback_bundle("6" * 64, ())

        with self.assertRaisesRegex(MigrationAdapterError, "archive digest"):
            adapter.restore(rollback)

        self.assertEqual(calls, ["backup"])

    def test_rejects_unknown_versions_shell_strings_missing_digests_and_bad_argv(self):
        with self.assertRaisesRegex(MigrationAdapterError, "unsupported"):
            self.make_admin(lambda _argv: None, version="0.9.0")
        adapter, _ = self.make_admin(
            lambda _argv: None, argv_factory=lambda *_: "hindsight-admin backup",
        )
        with self.assertRaisesRegex(MigrationAdapterError, "argument vector"):
            adapter.backup("/tmp/bank.zip", "a" * 64)
        adapter, _ = self.make_admin(
            lambda _argv: None,
            argv_factory=lambda executable, op, path, bank: [
                *admin_argv(executable, op, path, bank),
                "--database-url", "secret",
            ],
        )
        with self.assertRaisesRegex(MigrationAdapterError, "argv shape"):
            adapter.backup("/tmp/bank.zip", "a" * 64)
        with self.assertRaisesRegex(MigrationAdapterError, "digest"):
            adapter.backup("/tmp/bank.zip", "")
        with self.assertRaisesRegex(MigrationAdapterError, "bank ID"):
            hindsight_admin_argv("/trusted/hindsight-admin", "import-bank", "/tmp/bank.zip", None)
        with self.assertRaisesRegex(MigrationAdapterError, "bank ID"):
            hindsight_admin_argv("/trusted/hindsight-admin", "export-bank", "/tmp/bank.zip", "bad bank")

    def test_permits_all_four_exact_operations_with_verified_restore_evidence(self):
        calls = []
        artifact = "b" * 64
        evidence = restore_evidence(artifact)
        adapter, executable = self.make_admin(
            lambda argv: calls.append(argv) or {"returncode": 0, "stdout": "Complete"},
        )
        adapter.export_bank("/tmp/bank.zip", artifact, "historical-candidate")
        adapter.backup("/tmp/postgres-bank.zip", artifact)
        adapter.import_bank(
            "/tmp/bank.zip", artifact, "engineering", digest(evidence), evidence,
        )
        adapter.restore(
            "/tmp/postgres-bank.zip", artifact, digest(evidence), evidence,
        )
        self.assertEqual([argv[1] for argv in calls], ["export-bank", "backup", "import-bank", "restore"])
        self.assertEqual(calls, [
            [executable, "export-bank", "--bank", "historical-candidate", "--output", "/tmp/bank.zip"],
            [executable, "backup", "/tmp/postgres-bank.zip", "--schema", "public"],
            [executable, "import-bank", "--archive", "/tmp/bank.zip", "--target-bank", "engineering"],
            [executable, "restore", "/tmp/postgres-bank.zip", "--schema", "public", "--yes"],
        ])
        changed = {**evidence, "verification_receipt_digest": "8" * 64}
        with self.assertRaisesRegex(MigrationAdapterError, "evidence digest"):
            adapter.import_bank(
                "/tmp/bank.zip", artifact, "engineering", digest(evidence), changed,
            )


class GuardedApplyTest(unittest.TestCase):
    def test_apply_refuses_unsatisfied_compatibility_results(self):
        base = plan_for({})
        compatibility = ({"check": "provider-contract", "compatible": False, "status": "blocked"},)
        body = base.body()
        body["compatibility"] = [dict(value) for value in compatibility]
        plan = replace(base, compatibility=compatibility, plan_digest=digest(body))
        adapter = self.adapter()
        rollback = create_rollback_bundle(plan, adapter)
        result = apply_plan(
            plan,
            adapter,
            plan.plan_digest,
            {"rollback_bundle": rollback},
        )
        self.assertEqual(result.reason, "compatibility_not_satisfied")
        self.assertNotIn("create_bank", [call["method"] for call in adapter.calls])

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

        with tempfile.TemporaryDirectory() as temporary:
            adapter = self.adapter()
            base = plan_for({})
            mutation = build_mutation_plan(
                base,
                migration_run_id="run-1",
                migration_artifact_digest=MIGRATION_ARTIFACT_DIGEST,
                rollback_archive_digest="5" * 64,
                rollback_restore_evidence_digest=digest(
                    restore_evidence("5" * 64)
                ),
                actions=[mutation_action()],
            )
            rollback = create_rollback_bundle(mutation, adapter)
            descriptor, _, _ = write_migration_gate(Path(temporary), "run-1", MIGRATION_ARTIFACT_DIGEST)
            matching = {"rollback_bundle": rollback, "migration_gate": descriptor}

            self.assertEqual(apply_plan(mutation, adapter, mutation.plan_digest, matching).status, "applied")
            self.assertEqual(apply_plan(mutation, adapter, mutation.plan_digest, {"rollback_bundle": rollback}).reason, "migration_gate_required")

    def test_mutation_plan_deserialization_is_closed_and_digest_verified(self):
        from hindsight_memory_control_plane.reconcile import build_mutation_plan, mutation_plan_from_dict
        base = plan_for({})
        mutation = build_mutation_plan(base, migration_run_id="run-1", migration_artifact_digest=MIGRATION_ARTIFACT_DIGEST, rollback_archive_digest="5" * 64, rollback_restore_evidence_digest=digest(restore_evidence("5" * 64)), actions=[
            mutation_action(),
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
            build_mutation_plan(base, migration_run_id="run-1", migration_artifact_digest=MIGRATION_ARTIFACT_DIGEST, rollback_archive_digest="5" * 64, rollback_restore_evidence_digest=digest(restore_evidence("5" * 64)), actions=[
                {"id": "a" * 129, "kind": "migrate_bank", "artifact_digest": base.artifact_digest, "archive_digest": "4" * 64},
            ])

    def test_mutation_actions_require_plan_bound_source_and_target_banks(self):
        from hindsight_memory_control_plane.reconcile import build_mutation_plan

        base = plan_for({})
        for missing in ("source_bank", "target_bank"):
            with self.subTest(missing=missing):
                action = mutation_action()
                del action[missing]
                with self.assertRaisesRegex(ApplyError, "source and target bank"):
                    build_mutation_plan(
                        base,
                        migration_run_id="run-1",
                        migration_artifact_digest=MIGRATION_ARTIFACT_DIGEST,
                        rollback_archive_digest="5" * 64,
                        rollback_restore_evidence_digest=digest(
                            restore_evidence("5" * 64)
                        ),
                        actions=[action],
                    )

        wrong_profile = mutation_action()
        wrong_profile["target_bank"] = {
            "profile_id": "other", "bank_id": "engineering",
        }
        with self.assertRaisesRegex(ApplyError, "target profile"):
            build_mutation_plan(
                base,
                migration_run_id="run-1",
                migration_artifact_digest=MIGRATION_ARTIFACT_DIGEST,
                rollback_archive_digest="5" * 64,
                rollback_restore_evidence_digest=digest(
                    restore_evidence("5" * 64)
                ),
                actions=[wrong_profile],
            )

        missing_evidence = mutation_action()
        del missing_evidence["restore_evidence_digest"]
        with self.assertRaisesRegex(ApplyError, "restore evidence digest"):
            build_mutation_plan(
                base,
                migration_run_id="run-1",
                migration_artifact_digest=MIGRATION_ARTIFACT_DIGEST,
                rollback_archive_digest="5" * 64,
                rollback_restore_evidence_digest=digest(
                    restore_evidence("5" * 64)
                ),
                actions=[missing_evidence],
            )

        wrong_artifact = mutation_action()
        wrong_artifact["artifact_digest"] = "2" * 64
        with self.assertRaisesRegex(ApplyError, "migration artifact"):
            build_mutation_plan(
                base,
                migration_run_id="run-1",
                migration_artifact_digest=MIGRATION_ARTIFACT_DIGEST,
                rollback_archive_digest="5" * 64,
                rollback_restore_evidence_digest=digest(
                    restore_evidence("5" * 64)
                ),
                actions=[wrong_artifact],
            )

        rollback_collision = mutation_action(archive_digest="5" * 64)
        with self.assertRaisesRegex(ApplyError, "rollback archive"):
            build_mutation_plan(
                base,
                migration_run_id="run-1",
                migration_artifact_digest=MIGRATION_ARTIFACT_DIGEST,
                rollback_archive_digest="5" * 64,
                rollback_restore_evidence_digest=digest(
                    restore_evidence("5" * 64)
                ),
                actions=[rollback_collision],
            )

        evidence_collision = mutation_action()
        evidence_collision["restore_evidence_digest"] = digest(
            restore_evidence("5" * 64)
        )
        with self.assertRaisesRegex(ApplyError, "rollback evidence"):
            build_mutation_plan(
                base,
                migration_run_id="run-1",
                migration_artifact_digest=MIGRATION_ARTIFACT_DIGEST,
                rollback_archive_digest="5" * 64,
                rollback_restore_evidence_digest=digest(
                    restore_evidence("5" * 64)
                ),
                actions=[evidence_collision],
            )

    def test_mutation_action_id_rejects_payload_like_identifier(self):
        from hindsight_memory_control_plane.reconcile import build_mutation_plan
        base = plan_for({})
        with self.assertRaisesRegex(ApplyError, "action id"):
            build_mutation_plan(base, migration_run_id="run-1", migration_artifact_digest=MIGRATION_ARTIFACT_DIGEST, rollback_archive_digest="5" * 64, rollback_restore_evidence_digest=digest(restore_evidence("5" * 64)), actions=[
                {"id": "payload={secret}", "kind": "migrate_bank", "artifact_digest": base.artifact_digest, "archive_digest": "4" * 64},
            ])

    def test_mutation_action_id_rejects_control_characters(self):
        from hindsight_memory_control_plane.reconcile import build_mutation_plan
        base = plan_for({})
        with self.assertRaisesRegex(ApplyError, "action id"):
            build_mutation_plan(base, migration_run_id="run-1", migration_artifact_digest=MIGRATION_ARTIFACT_DIGEST, rollback_archive_digest="5" * 64, rollback_restore_evidence_digest=digest(restore_evidence("5" * 64)), actions=[
                {"id": "migration\nprivate", "kind": "migrate_bank", "artifact_digest": base.artifact_digest, "archive_digest": "4" * 64},
            ])

    def test_valid_mutation_action_id_remains_ledger_safe(self):
        from hindsight_memory_control_plane.reconcile import build_mutation_plan
        with tempfile.TemporaryDirectory() as temporary:
            base = plan_for({})
            adapter = self.adapter()
            mutation = build_mutation_plan(base, migration_run_id="run-1", migration_artifact_digest=MIGRATION_ARTIFACT_DIGEST, rollback_archive_digest="5" * 64, rollback_restore_evidence_digest=digest(restore_evidence("5" * 64)), actions=[
                mutation_action("migration-01.safe"),
            ])
            rollback = create_rollback_bundle(mutation, adapter)
            descriptor, _, _ = write_migration_gate(Path(temporary), "run-1", MIGRATION_ARTIFACT_DIGEST)
            gate = {"rollback_bundle": rollback, "migration_gate": descriptor}
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

    def test_migration_gate_reads_matching_external_marker_and_proposal(self):
        artifact = "a" * 64
        with tempfile.TemporaryDirectory() as temporary:
            descriptor, _, _ = write_migration_gate(Path(temporary), "run-1", artifact)
            self.assertEqual(parse_migration_gate(descriptor), ("run-1", artifact))

    def test_migration_gate_requires_present_well_formed_files(self):
        artifact = "a" * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_dir = root / "artifacts"
            artifact_dir.mkdir()
            proposal = root / "proposal-log.md"
            proposal.write_text(
                f"## Migration complete\nrun=run-1\nartifact={artifact}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ApplyError, "completion marker"):
                capture_migration_gate(artifact_dir / "distillation-complete.marker", proposal)

            marker = artifact_dir / "distillation-complete.marker"
            marker.write_text("not a gate\n", encoding="utf-8")
            with self.assertRaisesRegex(ApplyError, "completion marker"):
                capture_migration_gate(marker, proposal)

            marker.write_text(f"run=run-1\nartifact={artifact}\n", encoding="utf-8")
            proposal.write_text("## Migration complete\nrun=run-1\n", encoding="utf-8")
            with self.assertRaisesRegex(ApplyError, "proposal log"):
                capture_migration_gate(marker, proposal)

    def test_migration_gate_rejects_mismatched_run_or_artifact(self):
        artifact = "a" * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            descriptor, _, proposal = write_migration_gate(root, "run-1", artifact)
            self.assertEqual(parse_migration_gate(descriptor), ("run-1", artifact))
            proposal.write_text(
                f"## Migration complete\nrun=run-2\nartifact={artifact}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ApplyError, "changed"):
                parse_migration_gate(descriptor)
            with self.assertRaisesRegex(ApplyError, "do not match"):
                capture_migration_gate(root / "artifacts/distillation-complete.marker", proposal)

            proposal.write_text(
                f"## Migration complete\nrun=run-1\nartifact={'b' * 64}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ApplyError, "do not match"):
                capture_migration_gate(root / "artifacts/distillation-complete.marker", proposal)

    def test_migration_gate_rejects_symlink_and_non_regular_sources(self):
        artifact = "a" * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_dir = root / "artifacts"
            artifact_dir.mkdir()
            real_marker = root / "real.marker"
            real_marker.write_text(f"run=run-1\nartifact={artifact}\n", encoding="utf-8")
            (artifact_dir / "distillation-complete.marker").symlink_to(real_marker)
            proposal = root / "proposal-log.md"
            proposal.write_text(
                f"## Migration complete\nrun=run-1\nartifact={artifact}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ApplyError, "symlink"):
                capture_migration_gate(artifact_dir / "distillation-complete.marker", proposal)

            (artifact_dir / "distillation-complete.marker").unlink()
            (artifact_dir / "distillation-complete.marker").mkdir()
            with self.assertRaisesRegex(ApplyError, "regular file"):
                capture_migration_gate(artifact_dir / "distillation-complete.marker", proposal)

    def test_migration_gate_rejects_writable_files_and_ancestors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, marker, proposal = write_migration_gate(
                root, "run-1", MIGRATION_ARTIFACT_DIGEST,
            )
            marker.chmod(0o666)
            with self.assertRaisesRegex(ApplyError, "group or world writable"):
                capture_migration_gate(marker, proposal)
            marker.chmod(0o600)
            linked_marker = root / "linked-marker"
            linked_marker.hardlink_to(marker)
            with self.assertRaisesRegex(ApplyError, "hard links"):
                capture_migration_gate(linked_marker, proposal)

        with tempfile.TemporaryDirectory() as temporary:
            unsafe = Path(temporary) / "unsafe"
            unsafe.mkdir()
            unsafe.chmod(0o777)
            marker = unsafe / "artifacts" / "distillation-complete.marker"
            marker.parent.mkdir()
            marker.write_text(
                f"run=run-1\nartifact={MIGRATION_ARTIFACT_DIGEST}\n",
                encoding="utf-8",
            )
            proposal = unsafe / "proposal-log.md"
            proposal.write_text(
                f"## Migration complete\nrun=run-1\nartifact={MIGRATION_ARTIFACT_DIGEST}\n",
                encoding="utf-8",
            )
            marker.chmod(0o600)
            proposal.chmod(0o600)
            with self.assertRaisesRegex(ApplyError, "writable ancestor"):
                capture_migration_gate(marker, proposal)

    def test_verified_file_snapshot_binds_bytes_in_a_private_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "approved-bank.zip"
            approved = b"approved migration archive"
            source.write_bytes(approved)
            source.chmod(0o600)
            expected = hashlib.sha256(approved).hexdigest()

            with verified_file_snapshot(
                source, "migration archive", expected,
            ) as snapshot_value:
                snapshot = Path(snapshot_value)
                self.assertNotEqual(snapshot, source)
                self.assertEqual(snapshot.read_bytes(), approved)
                self.assertEqual(snapshot.stat().st_mode & 0o777, 0o400)
                self.assertEqual(snapshot.parent.stat().st_mode & 0o777, 0o700)
                source.write_bytes(b"changed after verification")
                self.assertEqual(snapshot.read_bytes(), approved)

            self.assertFalse(snapshot.exists())
            source.write_bytes(approved)
            source.chmod(0o600)
            with self.assertRaisesRegex(OSError, "consumer failure"):
                with verified_file_snapshot(
                    source, "migration archive", expected,
                ) as failed_snapshot_value:
                    failed_snapshot = Path(failed_snapshot_value)
                    raise OSError("consumer failure")
            self.assertFalse(failed_snapshot.exists())

            with self.assertRaisesRegex(FileEvidenceError, "absolute"):
                with verified_file_snapshot(
                    "~/approved-bank.zip", "migration archive", expected,
                ):
                    pass

            with self.assertRaisesRegex(FileEvidenceError, "too large"):
                with verified_file_snapshot(
                    source,
                    "migration archive",
                    expected,
                    max_bytes=len(approved) - 1,
                ):
                    pass

    def test_root_owned_root_symlink_checks_resolved_target_ancestors(self):
        original_lstat = Path.lstat
        original_resolve = Path.resolve
        root_link = Path("/virtual-evidence-root")

        with tempfile.TemporaryDirectory() as temporary:
            unsafe_target = Path(temporary) / "unsafe"
            unsafe_target.mkdir()
            unsafe_target.chmod(0o777)

            def fake_lstat(path):
                if path == root_link:
                    return type(
                        "RootLinkMetadata", (),
                        {"st_mode": stat.S_IFLNK | 0o777, "st_uid": 0},
                    )()
                return original_lstat(path)

            def fake_resolve(path, *args, **kwargs):
                if path == root_link:
                    return unsafe_target
                return original_resolve(path, *args, **kwargs)

            with patch.object(Path, "lstat", fake_lstat), patch.object(
                Path, "resolve", fake_resolve,
            ):
                with self.assertRaisesRegex(
                    FileEvidenceError, "writable ancestor",
                ):
                    reject_symlink_components(
                        root_link / "evidence.json",
                        "evidence",
                        allow_missing=False,
                    )

            trusted_target = Path(temporary) / "trusted"
            trusted_target.mkdir(mode=0o700)
            trusted_evidence = trusted_target / "evidence.json"
            trusted_evidence.write_text("{}", encoding="utf-8")
            trusted_evidence.chmod(0o600)
            requested_evidence = root_link / "evidence.json"

            def trusted_lstat(path):
                if path == root_link:
                    return type(
                        "RootLinkMetadata", (),
                        {"st_mode": stat.S_IFLNK | 0o777, "st_uid": 0},
                    )()
                if path == requested_evidence:
                    return trusted_evidence.lstat()
                return original_lstat(path)

            def trusted_resolve(path, *args, **kwargs):
                if path == root_link:
                    return trusted_target
                return original_resolve(path, *args, **kwargs)

            with patch.object(Path, "lstat", trusted_lstat), patch.object(
                Path, "resolve", trusted_resolve,
            ):
                self.assertIsNone(
                    reject_symlink_components(
                        requested_evidence,
                        "evidence",
                        allow_missing=False,
                    )
                )

    def test_root_symlink_resolution_errors_fail_closed_when_missing_is_allowed(self):
        original_lstat = Path.lstat
        root_link = Path("/virtual-broken-evidence-root")

        def fake_lstat(path):
            if path == root_link:
                return type(
                    "RootLinkMetadata", (),
                    {"st_mode": stat.S_IFLNK | 0o777, "st_uid": 0},
                )()
            return original_lstat(path)

        for error, message in (
            (PermissionError("denied"), "unavailable"),
            (RuntimeError("cycle"), "symlink cycle"),
        ):
            with self.subTest(error=type(error).__name__):
                with patch.object(Path, "lstat", fake_lstat), patch.object(
                    Path, "resolve", side_effect=error,
                ):
                    with self.assertRaisesRegex(FileEvidenceError, message):
                        reject_symlink_components(
                            root_link / "evidence.json",
                            "evidence",
                            allow_missing=True,
                        )

    def test_evidence_rejects_foreign_owned_read_only_ancestor(self):
        original_lstat = Path.lstat
        foreign_ancestor = Path("/virtual-foreign-evidence")

        def fake_lstat(path):
            if path == foreign_ancestor:
                return type(
                    "ForeignDirectoryMetadata", (),
                    {
                        "st_mode": stat.S_IFDIR | 0o755,
                        "st_uid": os.geteuid() + 1,
                    },
                )()
            return original_lstat(path)

        with patch.object(Path, "lstat", fake_lstat):
            with self.assertRaisesRegex(FileEvidenceError, "untrusted"):
                reject_symlink_components(
                    foreign_ancestor / "evidence.json",
                    "evidence",
                    allow_missing=False,
                )

    def test_apply_rechecks_gate_files_and_refuses_absent_or_changed_evidence(self):
        from hindsight_memory_control_plane.reconcile import build_mutation_plan

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = plan_for({})
            adapter = self.adapter()
            mutation = build_mutation_plan(base, migration_run_id="run-1", migration_artifact_digest=MIGRATION_ARTIFACT_DIGEST, rollback_archive_digest="5" * 64, rollback_restore_evidence_digest=digest(restore_evidence("5" * 64)), actions=[
                mutation_action(),
            ])
            rollback = create_rollback_bundle(mutation, adapter)
            descriptor, marker, proposal = write_migration_gate(root, "run-1", MIGRATION_ARTIFACT_DIGEST)
            gate = {"rollback_bundle": rollback, "migration_gate": descriptor}

            proposal.write_text(proposal.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            self.assertEqual(
                apply_plan(mutation, adapter, mutation.plan_digest, gate).reason,
                "migration_gate_mismatch",
            )
            self.assertNotIn("migrate_bank", [call["method"] for call in adapter.calls])

            descriptor, marker, _ = write_migration_gate(root / "second", "run-1", MIGRATION_ARTIFACT_DIGEST)
            marker.unlink()
            missing_gate = {"rollback_bundle": rollback, "migration_gate": descriptor}
            self.assertEqual(
                apply_plan(mutation, adapter, mutation.plan_digest, missing_gate).reason,
                "migration_gate_mismatch",
            )

    def test_apply_rechecks_gate_again_immediately_before_mutation(self):
        from hindsight_memory_control_plane.reconcile import build_mutation_plan

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = plan_for({})
            descriptor, _, proposal = write_migration_gate(root, "run-1", MIGRATION_ARTIFACT_DIGEST)

            class GateChangingAdapter(FakeAdapter):
                def verify_rollback_bundle(self, rollback):
                    verified = super().verify_rollback_bundle(rollback)
                    proposal.write_text(
                        proposal.read_text(encoding="utf-8") + "\n",
                        encoding="utf-8",
                    )
                    return verified

            adapter = GateChangingAdapter(
                endpoint={"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"},
            )
            mutation = build_mutation_plan(base, migration_run_id="run-1", migration_artifact_digest=MIGRATION_ARTIFACT_DIGEST, rollback_archive_digest="5" * 64, rollback_restore_evidence_digest=digest(restore_evidence("5" * 64)), actions=[
                mutation_action(),
            ])
            rollback = create_rollback_bundle(mutation, adapter)
            gate = {"rollback_bundle": rollback, "migration_gate": descriptor}

            result = apply_plan(mutation, adapter, mutation.plan_digest, gate)

            self.assertEqual(result.reason, "migration_gate_mismatch")
            self.assertNotIn("migrate_bank", [call["method"] for call in adapter.calls])

    def test_refuses_an_ordinary_plan_marked_destructive(self):
        adapter = self.adapter()
        plan = replace(plan_for({}), destructive=True)
        result = apply_plan(plan, adapter, plan.plan_digest, {"rollback_bundle": {}})
        self.assertEqual(result.reason, "invalid_or_destructive_plan")

    def test_migration_gate_mismatch_is_refused_through_apply_boundary(self):
        from hindsight_memory_control_plane.reconcile import build_mutation_plan
        adapter = self.adapter()
        base = plan_for({})
        mutation = build_mutation_plan(base, migration_run_id="run-1", migration_artifact_digest=MIGRATION_ARTIFACT_DIGEST, rollback_archive_digest="5" * 64, rollback_restore_evidence_digest=digest(restore_evidence("5" * 64)), actions=[
            mutation_action(),
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
