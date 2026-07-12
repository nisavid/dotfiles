import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "home" / "private_dot_local" / "lib"
sys.path.insert(0, str(LIB))

from hindsight_memory_control_plane.broker import Broker, BrokerError
from hindsight_memory_control_plane.server import JsonRpcClient, UnixJsonRpcServer


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
BANK = {"profile_id": "core", "bank_id": "engineering"}


class MemoryAdapter:
    def __init__(self):
        self.calls = []
        self.retained = []

    def recall(self, request):
        self.calls.append(("recall", request))
        return {"memories": [{"id": "m1"}]}

    def mental_model_fetch(self, request):
        self.calls.append(("mental_model_fetch", request))
        return {"models": [{"id": "model1"}]}

    def checkpoint(self, request):
        self.calls.append(("checkpoint", request))
        return {"applied": True}

    def retain_outcome(self, request):
        self.calls.append(("retain_outcome", request))
        self.retained.append(request)
        return {"retained": True}

    def reflect(self, request):
        self.calls.append(("reflect", request))
        return {"accepted": True}


def claims(**changes):
    value = {
        "session_id": "session-1",
        "harness_id": "codex",
        "home_bank": BANK,
        "trust_class": "local",
        "companion_id": "gui-1",
        "policy_digest": DIGEST_A,
        "artifact_digest": DIGEST_B,
        "methods": ["recall", "mental_model_fetch", "checkpoint", "retain_outcome", "reflect", "session_status", "session_close"],
        "route": "local-core",
    }
    value.update(changes)
    return value


class BrokerContractTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.adapter = MemoryAdapter()
        self.broker = Broker(
            state_dir=self.root / "state",
            signing_key=b"k" * 32,
            routes={"local-core": {"bank": BANK, "adapter": self.adapter}},
            policy_digest=DIGEST_A,
            artifact_digest=DIGEST_B,
        )

    def tearDown(self):
        self.broker.shutdown()
        self.temporary.cleanup()

    def exchange(self, **changes):
        staged = self.broker.session_mint(claims(**changes), ttl_seconds=30)
        return self.broker.session_exchange(staged)

    def test_socket_exchange_is_private_and_consumes_staged_handle(self):
        socket_path = self.root / "broker.sock"
        server = UnixJsonRpcServer(socket_path, self.broker)
        server.start()
        self.addCleanup(server.close)
        staged = self.broker.session_mint(claims(), ttl_seconds=30)
        handle_path = self.root / "state" / "handles" / f"{staged}.json"
        self.assertTrue(handle_path.exists())
        client = JsonRpcClient(socket_path)
        result = client.call("session_exchange", {"handle": staged})
        self.assertIn("capability", result)
        self.assertEqual(os.stat(socket_path).st_mode & 0o777, 0o600)
        self.assertFalse(handle_path.exists())
        with self.assertRaises(BrokerError):
            self.broker.session_exchange(staged)

    def test_capability_rejects_replay_sequence_and_binding_drift(self):
        capability = self.exchange()
        first = self.broker.recall(capability, sequence=1, action_id="recall-1", request={"query": "bounded"})
        self.assertEqual(first["disposition"], "ok")
        with self.assertRaisesRegex(BrokerError, "ACTION_REPLAY"):
            self.broker.recall(capability, sequence=2, action_id="recall-1", request={"query": "bounded"})
        with self.assertRaisesRegex(BrokerError, "SEQUENCE_ROLLBACK"):
            self.broker.recall(capability, sequence=1, action_id="recall-2", request={"query": "bounded"})
        self.broker.policy_digest = "c" * 64
        with self.assertRaisesRegex(BrokerError, "DIGEST_DRIFT"):
            self.broker.recall(capability, sequence=3, action_id="recall-3", request={"query": "bounded"})

    def test_method_route_expiry_and_revocation_are_bound(self):
        limited = self.exchange(methods=["recall"])
        with self.assertRaisesRegex(BrokerError, "METHOD_DENIED"):
            self.broker.reflect(limited, sequence=1, action_id="reflect-1", request={})
        wrong_route = self.exchange(route="unknown")
        with self.assertRaisesRegex(BrokerError, "ROUTE_DENIED"):
            self.broker.recall(wrong_route, sequence=1, action_id="route-1", request={})
        expired_handle = self.broker.session_mint(claims(), ttl_seconds=0)
        time.sleep(0.01)
        with self.assertRaisesRegex(BrokerError, "EXPIRED"):
            self.broker.session_exchange(expired_handle)
        revoked = self.exchange(session_id="session-revoked")
        self.broker.session_close(revoked, sequence=1, action_id="close-1", timeout_seconds=0.01)
        with self.assertRaisesRegex(BrokerError, "REVOKED"):
            self.broker.recall(revoked, sequence=2, action_id="closed-1", request={})

    def test_persisted_nonce_state_is_private_digest_only_and_route_bank_is_exact(self):
        capability = self.exchange()
        used_path = self.root / "state" / "used_nonces.json"
        session_path = self.root / "state" / "sessions.json"
        for path in (used_path, session_path):
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertNotIn("k" * 32, path.read_text(encoding="utf-8"))
        used = json.loads(used_path.read_text(encoding="utf-8"))
        self.assertTrue(all(len(value) == 64 for value in used))
        self.broker.routes["local-core"]["bank"] = {"profile_id": "core", "bank_id": "other"}
        with self.assertRaisesRegex(BrokerError, "ROUTE_DENIED"):
            self.broker.recall(capability, sequence=1, action_id="wrong-bank-1", request={})

    def test_closed_rpc_schema_and_content_free_diagnostics(self):
        capability = self.exchange()
        with self.assertRaisesRegex(BrokerError, "SCHEMA_INVALID") as caught:
            self.broker.recall(capability, sequence=1, action_id="bad-1", request={"query": "secret"}, extra="secret")
        self.assertNotIn("secret", str(caught.exception))


class BrokerOrderingTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.adapter = MemoryAdapter()
        self.broker = Broker(
            state_dir=self.root / "state", signing_key=b"z" * 32,
            routes={"local-core": {"bank": BANK, "adapter": self.adapter}},
            policy_digest=DIGEST_A, artifact_digest=DIGEST_B,
        )
        staged = self.broker.session_mint(claims(), ttl_seconds=30)
        self.capability = self.broker.session_exchange(staged)

    def tearDown(self):
        self.broker.shutdown()
        self.temporary.cleanup()

    def test_retain_returns_durable_watermark_and_checkpoint_is_monotonic_idempotent(self):
        queued = self.broker.retain_outcome(
            self.capability, sequence=1, action_id="retain-1",
            request={"document_id": "transcript", "epoch": 1, "checkpoint": 1, "outcome": "done"},
        )
        self.assertEqual(queued["disposition"], "queued")
        self.assertTrue((self.root / "state" / "queue.json").exists())
        first = self.broker.checkpoint(
            self.capability, sequence=2, action_id="checkpoint-1",
            request={"document_id": "transcript", "epoch": 1, "checkpoint": 2},
        )
        retry = self.broker.checkpoint(
            self.capability, sequence=3, action_id="checkpoint-2",
            request={"document_id": "transcript", "epoch": 1, "checkpoint": 2},
        )
        stale = self.broker.checkpoint(
            self.capability, sequence=4, action_id="checkpoint-3",
            request={"document_id": "transcript", "epoch": 1, "checkpoint": 1},
        )
        self.assertEqual(first["disposition"], "applied")
        self.assertEqual(retry["disposition"], "idempotent")
        self.assertEqual(stale["disposition"], "stale")
        self.assertEqual([call[0] for call in self.adapter.calls].count("checkpoint"), 1)

    def test_retain_replacement_accepts_only_newer_watermarks_and_retries_idempotently(self):
        first = self.broker.retain_outcome(
            self.capability, sequence=1, action_id="retain-order-1",
            request={"document_id": "transcript", "epoch": 3, "checkpoint": 4, "outcome": "first"},
        )
        retry = self.broker.retain_outcome(
            self.capability, sequence=2, action_id="retain-order-2",
            request={"document_id": "transcript", "epoch": 3, "checkpoint": 4, "outcome": "first"},
        )
        stale = self.broker.retain_outcome(
            self.capability, sequence=3, action_id="retain-order-3",
            request={"document_id": "transcript", "epoch": 3, "checkpoint": 3, "outcome": "stale"},
        )
        newer = self.broker.retain_outcome(
            self.capability, sequence=4, action_id="retain-order-4",
            request={"document_id": "transcript", "epoch": 4, "checkpoint": 1, "outcome": "newer"},
        )
        self.assertEqual(first["disposition"], "queued")
        self.assertEqual(retry["disposition"], "idempotent")
        self.assertEqual(stale["disposition"], "stale")
        self.assertEqual(newer["disposition"], "queued")

    def test_timeout_returns_no_memory_and_visible_payload_free_diagnostic(self):
        class SlowAdapter(MemoryAdapter):
            def recall(self, request):
                time.sleep(0.1)
                return {"memories": [{"payload": "private"}]}
        self.broker.routes["local-core"]["adapter"] = SlowAdapter()
        result = self.broker.recall(
            self.capability, sequence=1, action_id="timeout-1", request={"query": "private"}, timeout_seconds=0.01,
        )
        self.assertEqual(result["payload"], {"memories": []})
        self.assertEqual(result["diagnostic"]["code"], "MEMORY_UNAVAILABLE")
        self.assertNotIn("private", json.dumps(result["diagnostic"]))

    def test_close_is_bounded_and_reports_undrained_work(self):
        self.broker.retain_outcome(
            self.capability, sequence=1, action_id="retain-close",
            request={"document_id": "transcript", "epoch": 2, "checkpoint": 1, "outcome": "done"},
        )
        result = self.broker.session_close(
            self.capability, sequence=2, action_id="close-2", timeout_seconds=0,
        )
        self.assertEqual(result["disposition"], "closed")
        self.assertGreaterEqual(result["undrained"], 1)


if __name__ == "__main__":
    unittest.main()
