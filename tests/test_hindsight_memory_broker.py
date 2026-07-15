import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import call, patch


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "home" / "private_dot_local" / "lib"
sys.path.insert(0, str(LIB))

from hindsight_memory_control_plane.adapters import AdapterError, FakeAdapter
from hindsight_memory_control_plane.broker import Broker, BrokerError
from hindsight_memory_control_plane.canonical import canonical_bytes
from hindsight_memory_control_plane.server import JsonRpcClient, UnixJsonRpcServer


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
BANK = {"profile_id": "core", "bank_id": "engineering"}
ENDPOINT = {"profile_id": "core", "scheme": "http", "host": "127.0.0.1", "port": 7979, "tenant": "default"}
METHODS = ["recall", "mental_model_fetch", "transcript_checkpoint", "retain_outcome", "reflect", "session_status", "session_close"]
RESPONSE_KEYS = {"schema_version", "action_id", "action_digest", "policy_digest", "artifact_digest", "disposition", "payload", "diagnostic"}


def authorize_mint(control, requested, ttl):
    if control != "control" or requested.get("harness_id") != "codex" or ttl > 60:
        return {}
    return requested


def claims(**changes):
    value = {
        "session_id": "session-1", "harness_id": "codex", "home_bank": BANK,
        "trust_class": "local", "companion_id": "gui-1",
        "policy_digest": DIGEST_A, "artifact_digest": DIGEST_B,
        "methods": METHODS, "route": "local-core",
    }
    value.update(changes)
    return value


class BrokerSocketTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.socket_path = self.root / "broker.sock"
        self.adapter = FakeAdapter(endpoint=ENDPOINT)
        self.start(self.adapter)

    def start(self, adapter):
        self.broker = Broker(
            state_dir=self.state, signing_key=b"k" * 32,
            routes={"local-core": {"bank": BANK, "adapter": adapter}},
            policy_digest=DIGEST_A, artifact_digest=DIGEST_B,
            mint_authorizer=authorize_mint,
            max_payload_bytes=4096,
        )
        self.server = UnixJsonRpcServer(self.socket_path, self.broker)
        self.server.start()
        self.client = JsonRpcClient(self.socket_path)

    def stop(self):
        self.server.close()
        self.broker.shutdown()

    def tearDown(self):
        self.stop()
        self.temporary.cleanup()

    def exchange(self, **changes):
        minted = self.client.session_mint("control", claims(**changes), ttl_seconds=30)
        self.assert_response(minted, "session-mint")
        exchanged = self.client.session_exchange(minted["payload"]["handle"])
        self.assert_response(exchanged, "session-exchange")
        return exchanged["payload"]["capability"]

    def assert_response(self, response, action_id):
        self.assertEqual(set(response), RESPONSE_KEYS)
        self.assertEqual(response["schema_version"], 1)
        self.assertEqual(response["action_id"], action_id)
        self.assertRegex(response["action_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(response["policy_digest"], DIGEST_A)
        self.assertEqual(response["artifact_digest"], DIGEST_B)

    def run_cli(self, *arguments, env=None):
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "home/private_dot_local/bin/executable_hindsight-memory"),
                "--state-dir",
                str(self.state),
                *map(str, arguments),
            ],
            cwd=ROOT,
            env={**os.environ, **(env or {})},
            text=True,
            capture_output=True,
        )

    def test_stable_cli_clients_use_files_and_environment_for_private_inputs(self):
        claims_path = self.root / "claims.json"
        request_path = self.root / "request.json"
        claims_path.write_text(json.dumps(claims()), encoding="utf-8")
        request_path.write_text(json.dumps({"query": "deployment", "limit": 3}), encoding="utf-8")
        os.chmod(claims_path, 0o600)
        os.chmod(request_path, 0o600)

        minted = self.run_cli(
            "session", "mint", "--socket", self.socket_path,
            "--claims", claims_path, "--ttl-seconds", "30",
            env={"HINDSIGHT_MEMORY_CONTROL_CAPABILITY": "control"},
        )
        self.assertEqual(minted.returncode, 0, minted.stderr)
        handle = json.loads(minted.stdout)["payload"]["handle"]
        exchanged = self.run_cli(
            "session", "exchange", "--socket", self.socket_path,
            env={"HINDSIGHT_MEMORY_SESSION_HANDLE": handle},
        )
        self.assertEqual(exchanged.returncode, 0, exchanged.stderr)
        capability = json.loads(exchanged.stdout)["payload"]["capability"]

        recalled = self.run_cli(
            "recall", "--socket", self.socket_path, "--sequence", "1",
            "--action-id", "cli-recall", "--request", request_path,
            env={"HINDSIGHT_MEMORY_SESSION_CAPABILITY": capability},
        )
        self.assertEqual(recalled.returncode, 0, recalled.stderr)
        self.assertEqual(json.loads(recalled.stdout)["action_id"], "cli-recall")
        status = self.run_cli(
            "session_status", "--socket", self.socket_path, "--sequence", "2",
            "--action-id", "cli-status",
            env={"HINDSIGHT_MEMORY_SESSION_CAPABILITY": capability},
        )
        self.assertEqual(status.returncode, 0, status.stderr)
        closed = self.run_cli(
            "session", "close", "--socket", self.socket_path, "--sequence", "3",
            "--action-id", "cli-close",
            env={"HINDSIGHT_MEMORY_SESSION_CAPABILITY": capability},
        )
        self.assertEqual(closed.returncode, 0, closed.stderr)

        for result in (minted, exchanged, recalled, status, closed):
            self.assertFalse(any("control" in str(arg) for arg in result.args))
            self.assertFalse(any(capability in str(arg) for arg in result.args))

    def test_cli_clients_fail_closed_when_private_environment_is_missing(self):
        claims_path = self.root / "claims.json"
        claims_path.write_text(json.dumps(claims()), encoding="utf-8")
        result = self.run_cli(
            "session", "mint", "--socket", self.socket_path,
            "--claims", claims_path,
            env={"HINDSIGHT_MEMORY_CONTROL_CAPABILITY": ""},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CONTROL_CAPABILITY_UNAVAILABLE", result.stderr)

    def test_server_refuses_to_replace_an_existing_socket_path(self):
        self.stop()
        self.socket_path.write_text("preserve", encoding="utf-8")
        replacement = UnixJsonRpcServer(self.socket_path, self.broker)
        with self.assertRaises(OSError):
            replacement.start()
        self.assertEqual(self.socket_path.read_text(encoding="utf-8"), "preserve")
        self.server = replacement

    def test_server_close_preserves_a_replacement_path(self):
        self.socket_path.unlink()
        self.socket_path.write_text("replacement", encoding="utf-8")
        self.server.close()
        self.assertEqual(self.socket_path.read_text(encoding="utf-8"), "replacement")

    def test_server_start_failure_removes_its_bound_socket_path(self):
        self.stop()
        replacement = UnixJsonRpcServer(self.socket_path, self.broker)
        with patch(
            "hindsight_memory_control_plane.server.os.chmod",
            side_effect=OSError("chmod failed"),
        ):
            with self.assertRaisesRegex(OSError, "chmod failed"):
                replacement.start()
        self.assertFalse(self.socket_path.exists())
        self.server = replacement

    def test_server_restores_restrictive_bind_umask_after_bind_failure(self):
        self.stop()
        self.socket_path.write_text("preserve", encoding="utf-8")
        replacement = UnixJsonRpcServer(self.socket_path, self.broker)
        with patch(
            "hindsight_memory_control_plane.server.os.umask",
            side_effect=(0o022, 0o177),
        ) as umask:
            with self.assertRaises(OSError):
                replacement.start()
        self.assertEqual(
            umask.call_args_list,
            [call(0o177), call(0o022)],
        )
        self.server = replacement

    def test_server_start_is_rollback_safe_and_restartable(self):
        self.stop()
        replacement = UnixJsonRpcServer(self.socket_path, self.broker)
        with patch(
            "hindsight_memory_control_plane.server.threading.Thread.start",
            side_effect=RuntimeError("thread start failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "thread start failed"):
                replacement.start()
        self.assertFalse(self.socket_path.exists())
        self.assertIsNone(replacement._socket)
        self.assertIsNone(replacement._thread)
        self.assertIsNone(replacement._bound_identity)

        replacement.start()
        replacement.close()
        self.assertFalse(self.socket_path.exists())
        replacement.start()
        self.assertTrue(self.socket_path.is_socket())
        self.server = replacement

    def test_server_double_start_preserves_the_live_listener(self):
        identity = self.server._bound_identity
        with self.assertRaisesRegex(RuntimeError, "already started"):
            self.server.start()
        self.assertEqual(self.server._bound_identity, identity)
        self.assertTrue(self.socket_path.is_socket())
        self.assertIsNotNone(self.server._thread)
        self.assertTrue(self.server._thread.is_alive())

    def raw_rpc(self, method, params):
        request = {"jsonrpc": "2.0", "id": 91, "method": method, "params": params}
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        with connection:
            connection.connect(str(self.socket_path))
            connection.sendall(json.dumps(request).encode() + b"\n")
            return json.loads(connection.makefile("rb").readline())

    def test_all_typed_clients_use_private_socket_and_real_adapter(self):
        capability = self.exchange()
        recall = self.client.recall(capability, sequence=1, action_id="recall-1", request={"query": "q", "limit": 2})
        model = self.client.mental_model_fetch(capability, sequence=2, action_id="model-1", request={"model_id": "model1"})
        checkpoint = self.client.transcript_checkpoint(capability, sequence=3, action_id="checkpoint-1", request={"document_id": "doc", "epoch": 1, "checkpoint": 1})
        retain = self.client.retain_outcome(capability, sequence=4, action_id="retain-1", request={"document_id": "doc", "epoch": 1, "checkpoint": 1, "outcome": "done"})
        reflect = self.client.reflect(capability, sequence=5, action_id="reflect-1", request={"reflection": "note"})
        status = self.client.session_status(capability, sequence=6, action_id="status-1")
        closed = self.client.session_close(capability, sequence=7, action_id="close-1", timeout_seconds=1)
        for response, action in ((recall, "recall-1"), (model, "model-1"), (checkpoint, "checkpoint-1"),
                                 (retain, "retain-1"), (reflect, "reflect-1"), (status, "status-1"), (closed, "close-1")):
            self.assert_response(response, action)
        self.assertEqual(os.stat(self.socket_path).st_mode & 0o777, 0o600)
        called = {entry["method"] for entry in self.adapter.calls}
        self.assertTrue({"recall", "mental_model_fetch", "transcript_checkpoint", "retain_outcome", "reflect", "session_status"} <= called)

    def test_action_digest_is_canonical_and_capability_bound(self):
        capability = self.exchange()
        response = self.client.recall(capability, sequence=1, action_id="recall-digest", request={"query": "q"})
        body = json.loads(base64.urlsafe_b64decode(capability.split(".")[0] + "=="))
        expected = hashlib.sha256(canonical_bytes({
            "action_id": "recall-digest", "method": "recall", "sequence": 1,
            "session_id": "session-1", "harness_id": "codex",
            "capability_nonce_digest": hashlib.sha256(body["nonce"].encode()).hexdigest(),
        })).hexdigest()
        self.assertEqual(response["action_digest"], expected)

    def test_socket_rejects_unknown_nested_routing_and_auth_before_adapter(self):
        capability = self.exchange()
        forbidden = ("destination", "bank", "bank_id", "endpoint", "url", "authorization", "bearer", "credential", "token")
        for sequence, key in enumerate(forbidden, 1):
            before = len(self.adapter.calls)
            response = self.raw_rpc("recall", {
                "capability": capability, "sequence": sequence, "action_id": f"bad-{sequence}",
                "request": {"query": {"text": "q", key: "private"}},
            })
            self.assertEqual(response["error"]["message"], "SCHEMA_INVALID")
            self.assertNotIn("private", json.dumps(response))
            self.assertEqual(len(self.adapter.calls), before)
        alias = self.raw_rpc("checkpoint", {})
        self.assertEqual(alias["error"]["message"], "METHOD_DENIED")

    def test_invalid_ttl_and_timeout_are_rejected_before_session_or_adapter_state(self):
        invalid_mint = self.raw_rpc("session_mint", {"control_capability": "control", "claims": claims(), "ttl_seconds": float("nan")})
        self.assertEqual(invalid_mint["error"]["message"], "SCHEMA_INVALID")
        capability = self.exchange()
        invalid_read = self.raw_rpc("recall", {
            "capability": capability, "sequence": 1, "action_id": "timeout-action",
            "request": {"query": "q"}, "timeout_seconds": "invalid",
        })
        self.assertEqual(invalid_read["error"]["message"], "SCHEMA_INVALID")
        valid = self.client.recall(capability, sequence=1, action_id="timeout-action", request={"query": "q"})
        self.assertEqual(valid["disposition"], "ok")

    def test_mint_requires_control_capability_and_verifier_bound_claims(self):
        for control, requested in (("wrong", claims()), ("control", claims(harness_id="other"))):
            response = self.raw_rpc("session_mint", {
                "control_capability": control, "claims": requested, "ttl_seconds": 30,
            })
            self.assertEqual(response["error"]["message"], "MINT_DENIED")

    def test_json_rpc_ids_are_scalar_and_non_boolean(self):
        for identifier in (True, 1.5, [], {}):
            request = {"jsonrpc": "2.0", "id": identifier, "method": "session_mint", "params": {}}
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            with connection:
                connection.connect(str(self.socket_path))
                connection.sendall(json.dumps(request).encode() + b"\n")
                response = json.loads(connection.makefile("rb").readline())
            self.assertEqual(response["error"]["message"], "SCHEMA_INVALID")

    def test_replay_expiry_revocation_sequence_digest_method_and_route_survive_restart(self):
        capability = self.exchange()
        self.client.recall(capability, sequence=1, action_id="once", request={"query": "q"})
        with self.assertRaisesRegex(BrokerError, "ACTION_REPLAY"):
            self.client.recall(capability, sequence=2, action_id="once", request={"query": "q"})
        with self.assertRaisesRegex(BrokerError, "SEQUENCE_ROLLBACK"):
            self.client.recall(capability, sequence=1, action_id="older", request={"query": "q"})
        limited = self.exchange(session_id="limited", methods=["recall"])
        with self.assertRaisesRegex(BrokerError, "METHOD_DENIED"):
            self.client.reflect(limited, sequence=1, action_id="denied", request={"reflection": "x"})
        wrong = self.exchange(session_id="wrong")
        saved_route = self.broker.routes.pop("local-core")
        with self.assertRaisesRegex(BrokerError, "ROUTE_DENIED"):
            self.client.recall(wrong, sequence=1, action_id="route", request={"query": "q"})
        self.broker.routes["local-core"] = saved_route
        expired = self.client.session_mint("control", claims(session_id="expired"), ttl_seconds=0)
        with self.assertRaisesRegex(BrokerError, "EXPIRED"):
            self.client.session_exchange(expired["payload"]["handle"])
        closed = self.exchange(session_id="closed")
        self.client.session_close(closed, sequence=1, action_id="close", timeout_seconds=1)
        self.stop()
        self.start(self.adapter)
        with self.assertRaisesRegex(BrokerError, "REVOKED"):
            self.client.recall(closed, sequence=2, action_id="after-close", request={"query": "q"})
        self.broker.policy_digest = "c" * 64
        with self.assertRaisesRegex(BrokerError, "DIGEST_DRIFT"):
            self.client.recall(capability, sequence=3, action_id="drift", request={"query": "q"})
        for name in ("used_nonces.json", "revoked_nonces.json"):
            path = self.state / name
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertTrue(all(len(value) == 64 for value in json.loads(path.read_text())))
            self.assertNotIn("k" * 32, path.read_text())

    def test_concurrent_handle_exchange_returns_one_capability_and_marks_one_nonce(self):
        minted = self.client.session_mint("control", claims(), ttl_seconds=30)
        handle = minted["payload"]["handle"]
        ready = threading.Barrier(3)
        capabilities = []
        failures = []

        def exchange():
            ready.wait()
            try:
                response = self.broker.session_exchange(handle)
                capabilities.append(response["payload"]["capability"])
            except Exception as error:
                failures.append(error)

        threads = [threading.Thread(target=exchange) for _ in range(2)]
        for thread in threads:
            thread.start()
        ready.wait()
        for thread in threads:
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())

        self.assertEqual(failures, [])
        self.assertEqual(len(capabilities), 2)
        self.assertEqual(len(set(capabilities)), 1)
        work = json.loads((self.state / "durable_work.json").read_text())
        self.assertEqual(len(work["used_nonces"]), 1)
        self.assertEqual(len(work["exchanges"]), 1)

    def test_read_and_model_timeouts_discard_late_payload_and_shutdown_drains(self):
        class SlowFake(FakeAdapter):
            def recall(self, request):
                time.sleep(0.05)
                return {"memories": [{"payload": "private"}]}
            def mental_model_fetch(self, request):
                time.sleep(0.05)
                return {"models": [{"payload": "private"}]}
        self.stop()
        self.adapter = SlowFake(endpoint=ENDPOINT)
        self.start(self.adapter)
        capability = self.exchange()
        recalled = self.client.recall(capability, sequence=1, action_id="slow-recall", request={"query": "q"}, timeout_seconds=0)
        modeled = self.client.mental_model_fetch(capability, sequence=2, action_id="slow-model", request={"model_id": "m"}, timeout_seconds=0)
        self.assertEqual(recalled["payload"], {"memories": []})
        self.assertEqual(modeled["payload"], {"models": []})
        for response in (recalled, modeled):
            self.assertEqual(response["diagnostic"], {"code": "MEMORY_UNAVAILABLE", "visible": True})
            self.assertNotIn("private", json.dumps(response))

    def test_shutdown_has_explicit_bound_and_reports_active_read(self):
        release = threading.Event()
        class HungFake(FakeAdapter):
            def recall(self, request):
                release.wait(1)
                return {"memories": []}
        self.stop()
        self.adapter = HungFake(endpoint=ENDPOINT)
        self.start(self.adapter)
        capability = self.exchange()
        self.client.recall(capability, sequence=1, action_id="hung", request={"query": "q"}, timeout_seconds=0)
        started = time.monotonic()
        status = self.broker.shutdown(timeout_seconds=0)
        self.assertLess(time.monotonic() - started, 0.05)
        self.assertGreaterEqual(status["active_reads"], 1)
        release.set()

    def test_response_payload_is_bounded(self):
        self.adapter.state["recall"] = {"memories": [{"value": "x" * 8192}]}
        capability = self.exchange()
        response = self.client.recall(capability, sequence=1, action_id="large", request={"query": "q"})
        self.assertEqual(response["disposition"], "unavailable")
        self.assertEqual(response["payload"], {"memories": []})
        self.assertEqual(response["diagnostic"]["code"], "RESPONSE_TOO_LARGE")

    def test_reflect_timeout_is_synchronous_and_visible(self):
        class SlowReflect(FakeAdapter):
            def reflect(self, request):
                time.sleep(0.05)
                return super().reflect(request)
        self.stop()
        self.adapter = SlowReflect(endpoint=ENDPOINT)
        self.start(self.adapter)
        capability = self.exchange()
        response = self.client.reflect(capability, sequence=1, action_id="reflect-timeout", request={"reflection": "note"}, timeout_seconds=0)
        self.assertEqual(response["disposition"], "unavailable")
        self.assertEqual(response["diagnostic"]["code"], "REFLECT_UNAVAILABLE")

    def test_adapter_response_cannot_expose_routing_or_credentials(self):
        self.adapter.state["recall"] = {"memories": [{"token": "private"}]}
        capability = self.exchange()
        response = self.client.recall(capability, sequence=1, action_id="redacted", request={"query": "q"})
        self.assertEqual(response["payload"], {"memories": []})
        self.assertEqual(response["diagnostic"]["code"], "RESPONSE_INVALID")
        self.assertNotIn("private", json.dumps(response))


class DurableWorkTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.socket_path = self.root / "broker.sock"
        self.adapter = FakeAdapter(endpoint=ENDPOINT)
        self._start()

    def _start(self):
        self.broker = Broker(state_dir=self.state, signing_key=b"z" * 32,
            routes={"local-core": {"bank": BANK, "adapter": self.adapter}},
            policy_digest=DIGEST_A, artifact_digest=DIGEST_B,
            mint_authorizer=authorize_mint)
        self.server = UnixJsonRpcServer(self.socket_path, self.broker)
        self.server.start()
        self.client = JsonRpcClient(self.socket_path)

    def _stop(self):
        self.server.close()
        self.broker.shutdown()

    def tearDown(self):
        self._stop()
        self.temporary.cleanup()

    def exchange(self):
        mint = self.client.session_mint("control", claims(), ttl_seconds=30)
        return self.client.session_exchange(mint["payload"]["handle"])["payload"]["capability"]

    def work(self):
        return json.loads((self.state / "durable_work.json").read_text())

    def test_queue_and_watermark_are_one_atomic_private_state_before_ack(self):
        capability = self.exchange()
        response = self.client.retain_outcome(capability, sequence=1, action_id="retain", request={"document_id": "doc", "epoch": 1, "checkpoint": 1, "outcome": "done"})
        self.assertEqual(response["disposition"], "queued")
        self.assertEqual(os.stat(self.state / "durable_work.json").st_mode & 0o777, 0o600)
        state = self.work()
        records = state["queue"] + list(state["completed"].values())
        self.assertTrue(any(record["watermark"] == [1, 1] for record in records))
        self.assertTrue(all("idempotency_key" in record for record in records))

    def test_enqueue_failure_leaves_no_orphan_watermark(self):
        capability = self.exchange()
        original = __import__("hindsight_memory_control_plane.broker", fromlist=["_atomic_json"])._atomic_json
        def fail_work(path, value):
            if Path(path).name == "durable_work.json":
                raise OSError("simulated crash")
            return original(path, value)
        with patch("hindsight_memory_control_plane.broker._atomic_json", side_effect=fail_work):
            with self.assertRaisesRegex(BrokerError, "INTERNAL_ERROR"):
                self.client.retain_outcome(capability, sequence=1, action_id="before", request={"document_id": "doc", "epoch": 1, "checkpoint": 1, "outcome": "done"})
        state = self.work()
        self.assertEqual(state["queue"], [])
        self.assertEqual(state["completed"], {})
        retried = self.client.retain_outcome(capability, sequence=1, action_id="before", request={"document_id": "doc", "epoch": 1, "checkpoint": 1, "outcome": "done"})
        self.assertEqual(retried["disposition"], "queued")

    def test_digest_mirror_failure_cannot_undo_canonical_enqueue_ack(self):
        capability = self.exchange()
        original = __import__("hindsight_memory_control_plane.broker", fromlist=["_atomic_json"])._atomic_json
        def fail_mirror(path, value):
            if Path(path).name in {"used_nonces.json", "revoked_nonces.json"}:
                raise OSError("derived mirror unavailable")
            return original(path, value)
        with patch("hindsight_memory_control_plane.broker._atomic_json", side_effect=fail_mirror):
            response = self.client.retain_outcome(capability, sequence=1, action_id="mirror", request={"document_id": "doc", "epoch": 1, "checkpoint": 1, "outcome": "done"})
        self.assertEqual(response["disposition"], "queued")
        state = self.work()
        self.assertEqual(state["sessions"]["session-1"]["sequence"], 1)
        with self.assertRaisesRegex(BrokerError, "ACTION_REPLAY"):
            self.client.retain_outcome(capability, sequence=2, action_id="mirror", request={"document_id": "doc", "epoch": 1, "checkpoint": 1, "outcome": "done"})
        self._stop()
        (self.state / "used_nonces.json").unlink(missing_ok=True)
        (self.state / "revoked_nonces.json").unlink(missing_ok=True)
        self._start()
        self.assertTrue((self.state / "used_nonces.json").exists())
        self.assertEqual(json.loads((self.state / "used_nonces.json").read_text()), self.work()["used_nonces"])

    def test_enqueue_revalidates_when_close_wins_after_preflight(self):
        capability = self.exchange()
        entered = threading.Event()
        release = threading.Event()
        original = self.broker._enqueue_watermarked
        def paused(*args, **kwargs):
            entered.set()
            release.wait(1)
            return original(*args, **kwargs)
        self.broker._enqueue_watermarked = paused
        failure = []
        thread = threading.Thread(target=lambda: self._capture_error(
            failure,
            lambda: self.broker.retain_outcome(capability, sequence=1, action_id="racing-retain", request={"document_id": "doc", "epoch": 1, "checkpoint": 1, "outcome": "done"}),
        ))
        thread.start()
        self.assertTrue(entered.wait(0.2))
        closed = self.broker.session_close(capability, sequence=2, action_id="racing-close", timeout_seconds=0)
        release.set()
        thread.join()
        self.assertEqual(closed["disposition"], "closed")
        self.assertEqual(failure, ["REVOKED"])
        state = self.work()
        self.assertTrue(state["sessions"]["session-1"]["closed"])
        self.assertIn(state["sessions"]["session-1"]["revocation_digest"], state["revoked_nonces"])

    def test_close_is_retryable_before_atomic_commit_and_drainable_after_commit(self):
        capability = self.exchange()
        original_atomic = __import__("hindsight_memory_control_plane.broker", fromlist=["_atomic_json"])._atomic_json
        failed = {"once": False}
        def fail_commit(path, value):
            if Path(path).name == "durable_work.json" and not failed["once"]:
                failed["once"] = True
                raise OSError("before close commit")
            return original_atomic(path, value)
        with patch("hindsight_memory_control_plane.broker._atomic_json", side_effect=fail_commit):
            with self.assertRaises(OSError):
                self.broker.session_close(capability, sequence=1, action_id="close-retry", timeout_seconds=0)
        retried = self.broker.session_close(capability, sequence=1, action_id="close-retry", timeout_seconds=0)
        self.assertEqual(retried["disposition"], "closed")

        mint = self.client.session_mint("control", claims(session_id="close-after"), ttl_seconds=30)
        other = self.client.session_exchange(mint["payload"]["handle"])["payload"]["capability"]
        with patch.object(self.broker, "_submit_write", side_effect=OSError("after close commit")):
            with self.assertRaises(OSError):
                self.broker.session_close(other, sequence=1, action_id="close-after", timeout_seconds=0)
        state = self.work()
        self.assertTrue(state["sessions"]["close-after"]["closed"])
        self.assertTrue(any(item["session_id"] == "close-after" for item in state["queue"]))
        self._stop()
        self._start()
        time.sleep(0.05)
        self.assertFalse(any(item["session_id"] == "close-after" for item in self.work()["queue"]))

    @staticmethod
    def _capture_error(target, operation):
        try:
            operation()
        except BrokerError as error:
            target.append(error.code)

    def test_restart_replays_after_enqueue_with_same_idempotency_key(self):
        class FailOnceFake(FakeAdapter):
            def __init__(self):
                super().__init__(endpoint=ENDPOINT)
                self.fail = True
            def retain_outcome(self, request):
                if self.fail:
                    self.fail = False
                    raise SystemExit("crash after enqueue")
                return super().retain_outcome(request)
        self._stop()
        self.adapter = FailOnceFake()
        self._start()
        capability = self.exchange()
        response = self.client.retain_outcome(capability, sequence=1, action_id="after-enqueue", request={"document_id": "doc", "epoch": 1, "checkpoint": 1, "outcome": "done"})
        key = response["action_digest"]
        time.sleep(0.03)
        self.assertEqual(self.work()["queue"][0]["idempotency_key"], key)
        self._stop()
        self._start()
        time.sleep(0.03)
        self.assertEqual(self.work()["queue"], [])
        retain_calls = [entry for entry in self.adapter.calls if entry["method"] == "retain_outcome"]
        self.assertEqual(len(retain_calls), 1)

    def test_restart_after_adapter_success_before_dequeue_reuses_key(self):
        class CrashAfterSuccess(FakeAdapter):
            def __init__(self):
                super().__init__(endpoint=ENDPOINT)
                self.crash = True
            def retain_outcome(self, request):
                result = super().retain_outcome(request)
                if self.crash:
                    self.crash = False
                    raise SystemExit("crash window")
                return result
        self._stop()
        self.adapter = CrashAfterSuccess()
        self._start()
        capability = self.exchange()
        response = self.client.retain_outcome(capability, sequence=1, action_id="after-success", request={"document_id": "doc", "epoch": 1, "checkpoint": 1, "outcome": "done"})
        time.sleep(0.03)
        self.assertEqual(self.work()["queue"][0]["idempotency_key"], response["action_digest"])
        self._stop()
        self._start()
        time.sleep(0.03)
        self.assertEqual(self.work()["queue"], [])
        self.assertEqual(len([entry for entry in self.adapter.calls if entry["method"] == "retain_outcome"]), 1)

    def test_concurrent_older_watermark_cannot_replace_newer(self):
        capability = self.exchange()
        barrier = threading.Barrier(3)
        outcomes = []
        def send(sequence, action, epoch):
            client = JsonRpcClient(self.socket_path)
            barrier.wait()
            try:
                outcomes.append(client.retain_outcome(capability, sequence=sequence, action_id=action,
                    request={"document_id": "doc", "epoch": epoch, "checkpoint": 1, "outcome": action}))
            except BrokerError as error:
                outcomes.append(error.code)
        threads = [threading.Thread(target=send, args=(1, "older", 1)), threading.Thread(target=send, args=(2, "newer", 2))]
        for thread in threads: thread.start()
        barrier.wait()
        for thread in threads: thread.join()
        time.sleep(0.03)
        records = list(self.work()["completed"].values()) + self.work()["queue"]
        self.assertEqual(max(tuple(record["watermark"]) for record in records), (2, 1))
        self.assertFalse(any(tuple(record["watermark"]) > (2, 1) for record in records))

    def test_stale_and_idempotent_responses_consume_actions(self):
        capability = self.exchange()
        self.client.retain_outcome(capability, sequence=1, action_id="first", request={"document_id": "doc", "epoch": 2, "checkpoint": 1, "outcome": "new"})
        stale = self.client.retain_outcome(capability, sequence=2, action_id="stale", request={"document_id": "doc", "epoch": 1, "checkpoint": 1, "outcome": "old"})
        same = self.client.retain_outcome(capability, sequence=3, action_id="same", request={"document_id": "doc", "epoch": 2, "checkpoint": 1, "outcome": "new"})
        self.assertEqual(stale["disposition"], "stale")
        self.assertEqual(same["disposition"], "idempotent")
        with self.assertRaisesRegex(BrokerError, "ACTION_REPLAY"):
            self.client.recall(capability, sequence=4, action_id="same", request={"query": "q"})

    def test_exchange_recovers_same_capability_after_unlink_crash(self):
        mint = self.client.session_mint("control", claims(), ttl_seconds=30)
        handle = mint["payload"]["handle"]
        original_unlink = Path.unlink
        def fail_handle(path, *args, **kwargs):
            if path.name == f"{handle}.json":
                raise OSError("crash after state commit")
            return original_unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", fail_handle):
            with self.assertRaisesRegex(BrokerError, "INTERNAL_ERROR"):
                self.client.session_exchange(handle)
        recovered = self.client.session_exchange(handle)
        again = self.client.session_exchange(handle)
        self.assertEqual(recovered["payload"]["capability"], again["payload"]["capability"])

    def test_close_reports_slow_undrained_durable_work(self):
        class SlowWriteFake(FakeAdapter):
            def retain_outcome(self, request):
                time.sleep(0.1)
                return super().retain_outcome(request)
        self._stop()
        self.adapter = SlowWriteFake(endpoint=ENDPOINT)
        self._start()
        capability = self.exchange()
        self.client.retain_outcome(capability, sequence=1, action_id="retain-close", request={"document_id": "doc", "epoch": 1, "checkpoint": 1, "outcome": "done"})
        closed = self.client.session_close(capability, sequence=2, action_id="close", timeout_seconds=0)
        self.assertEqual(closed["disposition"], "closed")
        self.assertGreaterEqual(closed["payload"]["undrained"], 1)

    def test_late_retired_worker_cannot_overwrite_replacement_generation(self):
        release = threading.Event()
        started = threading.Event()
        class FencedFake(FakeAdapter):
            def retain_outcome(self, request):
                if not started.is_set():
                    started.set()
                    release.wait(1)
                return super().retain_outcome(request)
        self._stop()
        self.adapter = FencedFake(endpoint=ENDPOINT)
        self._start()
        capability = self.exchange()
        self.client.retain_outcome(capability, sequence=1, action_id="fenced", request={"document_id": "doc", "epoch": 1, "checkpoint": 1, "outcome": "done"})
        self.assertTrue(started.wait(0.2))
        self.server.close()
        stopped = self.broker.shutdown(timeout_seconds=0)
        self.assertGreaterEqual(stopped["undrained"], 1)
        self._start()
        replacement_generation = self.work()["generation"]
        release.set()
        time.sleep(0.05)
        self.assertEqual(self.work()["generation"], replacement_generation)

    def test_replacement_generation_fences_all_old_broker_state_transitions(self):
        capability = self.exchange()
        self.client.recall(capability, sequence=1, action_id="preserved-read", request={"query": "q"})
        mint = self.client.session_mint("control", claims(session_id="pending-exchange"), ttl_seconds=30)
        handle = mint["payload"]["handle"]
        before = self.work()
        replacement = Broker(
            state_dir=self.state, signing_key=b"z" * 32,
            routes={"local-core": {"bank": BANK, "adapter": self.adapter}},
            policy_digest=DIGEST_A, artifact_digest=DIGEST_B, mint_authorizer=authorize_mint,
        )
        try:
            after_start = self.work()
            self.assertEqual(after_start["sessions"], before["sessions"])
            self.assertEqual(after_start["queue"], before["queue"])
            self.assertEqual(after_start["completed"], before["completed"])
            with self.assertRaisesRegex(BrokerError, "BROKER_RETIRED"):
                self.broker.session_exchange(handle)
            for operation in (
                lambda: self.broker.retain_outcome(capability, sequence=2, action_id="old-enqueue", request={"document_id": "doc", "epoch": 2, "checkpoint": 1, "outcome": "old"}),
                lambda: self.broker.retain_outcome(capability, sequence=2, action_id="old-stale", request={"document_id": "doc", "epoch": 0, "checkpoint": 1, "outcome": "old"}),
                lambda: self.broker.session_close(capability, sequence=2, action_id="old-close", timeout_seconds=0),
            ):
                with self.assertRaisesRegex(BrokerError, "BROKER_RETIRED"):
                    operation()
            shutdown = self.broker.shutdown(timeout_seconds=0)
            self.assertTrue(shutdown["retired"])
            self.assertEqual(self.work()["generation"], after_start["generation"])
            self.assertEqual(self.work()["sessions"], after_start["sessions"])
        finally:
            replacement.shutdown(timeout_seconds=1)

    def test_staged_mint_is_generation_bound_and_closed_brokers_cannot_mint(self):
        staged = self.client.session_mint("control", claims(session_id="staged-old"), ttl_seconds=30)
        handle = staged["payload"]["handle"]
        replacement = Broker(
            state_dir=self.state, signing_key=b"z" * 32,
            routes={"local-core": {"bank": BANK, "adapter": self.adapter}},
            policy_digest=DIGEST_A, artifact_digest=DIGEST_B, mint_authorizer=authorize_mint,
        )
        try:
            with self.assertRaisesRegex(BrokerError, "BROKER_RETIRED"):
                replacement.session_exchange(handle)
            handles = set((self.state / "handles").glob("*.json"))
            with self.assertRaisesRegex(BrokerError, "BROKER_RETIRED"):
                self.broker.session_mint("control", claims(session_id="retired-mint"), ttl_seconds=30)
            self.assertEqual(set((self.state / "handles").glob("*.json")), handles)
            current = replacement.session_mint("control", claims(session_id="current-mint"), ttl_seconds=30)
            exchanged = replacement.session_exchange(current["payload"]["handle"])
            self.assertIn("capability", exchanged["payload"])
        finally:
            replacement.shutdown(timeout_seconds=1)
        shutdown = self.broker.shutdown(timeout_seconds=0)
        self.assertTrue(shutdown["retired"])
        with self.assertRaisesRegex(BrokerError, "BROKER_CLOSED"):
            self.broker.session_mint("control", claims(session_id="closed-mint"), ttl_seconds=30)

    def test_staged_mint_holds_generation_lease_against_replacement_race(self):
        entered = threading.Event()
        release = threading.Event()
        original = __import__("hindsight_memory_control_plane.broker", fromlist=["_atomic_json"])._atomic_json
        def pause_handle(path, value):
            if Path(path).parent.name == "handles" and not entered.is_set():
                entered.set()
                release.wait(1)
            return original(path, value)
        minted = []
        replacements = []
        with patch("hindsight_memory_control_plane.broker._atomic_json", side_effect=pause_handle):
            mint_thread = threading.Thread(target=lambda: minted.append(
                self.broker.session_mint("control", claims(session_id="racing-mint"), ttl_seconds=30)
            ))
            mint_thread.start()
            self.assertTrue(entered.wait(0.2))
            replacement_thread = threading.Thread(target=lambda: replacements.append(Broker(
                state_dir=self.state, signing_key=b"z" * 32,
                routes={"local-core": {"bank": BANK, "adapter": self.adapter}},
                policy_digest=DIGEST_A, artifact_digest=DIGEST_B, mint_authorizer=authorize_mint,
            )))
            replacement_thread.start()
            time.sleep(0.02)
            self.assertTrue(replacement_thread.is_alive())
            release.set()
            mint_thread.join()
            replacement_thread.join()
        replacement = replacements[0]
        try:
            handle = minted[0]["payload"]["handle"]
            with self.assertRaisesRegex(BrokerError, "BROKER_RETIRED"):
                replacement.session_exchange(handle)
        finally:
            replacement.shutdown(timeout_seconds=1)


if __name__ == "__main__":
    unittest.main()
