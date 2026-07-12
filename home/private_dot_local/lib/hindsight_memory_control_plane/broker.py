"""Private runtime memory broker with scoped, one-use session exchange."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Any, Callable, Mapping

from .canonical import canonical_bytes
from .ledger import append_record


CAPABILITY_METHODS = frozenset({
    "recall", "mental_model_fetch", "checkpoint", "retain_outcome", "reflect",
    "session_status", "session_close",
})
CLAIM_KEYS = frozenset({
    "session_id", "harness_id", "home_bank", "trust_class", "companion_id",
    "policy_digest", "artifact_digest", "methods", "route",
})
FORBIDDEN_REQUEST_KEYS = frozenset({
    "endpoint", "token", "api_key", "control_key", "signing_key", "secret",
    "bank", "bank_id", "home_bank", "target_bank", "destination_bank", "route",
})
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


class BrokerError(ValueError):
    """Content-free broker rejection suitable for an operator diagnostic."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    if not isinstance(value, str) or len(value) > 32768:
        raise BrokerError("CAPABILITY_INVALID")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as error:
        raise BrokerError("CAPABILITY_INVALID") from error


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        body = canonical_bytes(value)
        os.write(descriptor, body)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return deepcopy(default)
    except (OSError, json.JSONDecodeError) as error:
        raise BrokerError("STATE_INVALID") from error


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(key in FORBIDDEN_REQUEST_KEYS or _contains_forbidden_key(child) for key, child in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_key(child) for child in value)
    return False


class Broker:
    """Authorize harness memory calls without exposing route credentials."""

    def __init__(
        self, *, state_dir: str | Path, signing_key: bytes | Callable[[], bytes],
        routes: Mapping[str, Mapping[str, Any]], policy_digest: str,
        artifact_digest: str, ledger_path: str | Path | None = None,
        clock: Callable[[], float] = time.time, max_payload_bytes: int = 64 * 1024,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.state_dir, 0o700)
        key = signing_key() if callable(signing_key) else signing_key
        if not isinstance(key, bytes) or len(key) < 32:
            raise BrokerError("SIGNING_KEY_INVALID")
        self.__signing_key = bytes(key)
        self.routes = {str(name): dict(route) for name, route in routes.items()}
        self.policy_digest = policy_digest
        self.artifact_digest = artifact_digest
        self.ledger_path = Path(ledger_path) if ledger_path else None
        self.clock = clock
        self.max_payload_bytes = max_payload_bytes
        self._lock = threading.RLock()
        self._document_locks: dict[tuple[str, str, str], threading.Lock] = {}
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hindsight-broker")
        self._retain_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hindsight-retain")
        self._used_path = self.state_dir / "used_nonces.json"
        self._revoked_path = self.state_dir / "revoked_nonces.json"
        self._sessions_path = self.state_dir / "sessions.json"
        self._queue_path = self.state_dir / "queue.json"
        self._checkpoint_path = self.state_dir / "checkpoints.json"
        self._outcome_path = self.state_dir / "outcome_watermarks.json"
        self._used = set(_read_json(self._used_path, []))
        self._revoked = set(_read_json(self._revoked_path, []))
        self._sessions = _read_json(self._sessions_path, {})
        self._queue = _read_json(self._queue_path, [])
        self._checkpoints = _read_json(self._checkpoint_path, {})
        self._outcomes = _read_json(self._outcome_path, {})
        self._closed = False
        for item in tuple(self._queue):
            route = self.routes.get(item.get("route")) if isinstance(item, dict) else None
            if route is not None and isinstance(item.get("queue_id"), str):
                self._retain_executor.submit(self._drain_item, item["queue_id"], route)

    def shutdown(self) -> None:
        if not self._closed:
            self._closed = True
            self._executor.shutdown(wait=False, cancel_futures=False)
            self._retain_executor.shutdown(wait=False, cancel_futures=False)

    def _sign(self, claims: Mapping[str, Any]) -> str:
        body = canonical_bytes(claims)
        signature = hmac.new(self.__signing_key, body, hashlib.sha256).digest()
        return f"{_b64encode(body)}.{_b64encode(signature)}"

    def _verify(self, token: str, kind: str) -> dict[str, Any]:
        if not isinstance(token, str) or token.count(".") != 1:
            raise BrokerError("CAPABILITY_INVALID")
        encoded, encoded_signature = token.split(".")
        body, supplied = _b64decode(encoded), _b64decode(encoded_signature)
        expected = hmac.new(self.__signing_key, body, hashlib.sha256).digest()
        if not hmac.compare_digest(supplied, expected):
            raise BrokerError("CAPABILITY_INVALID")
        try:
            claims = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BrokerError("CAPABILITY_INVALID") from error
        if not isinstance(claims, dict) or claims.get("kind") != kind:
            raise BrokerError("CAPABILITY_INVALID")
        if type(claims.get("expires_at")) not in (int, float) or self.clock() >= claims["expires_at"]:
            raise BrokerError("EXPIRED")
        return claims

    def _validate_base_claims(self, claims: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(claims, Mapping) or set(claims) != CLAIM_KEYS:
            raise BrokerError("SCHEMA_INVALID")
        normalized = deepcopy(dict(claims))
        for key in ("session_id", "harness_id", "trust_class", "companion_id", "route"):
            if not isinstance(normalized[key], str) or not IDENTIFIER.fullmatch(normalized[key]):
                raise BrokerError("SCHEMA_INVALID")
        home = normalized["home_bank"]
        if not isinstance(home, dict) or set(home) != {"profile_id", "bank_id"}:
            raise BrokerError("SCHEMA_INVALID")
        if not all(isinstance(home[key], str) and home[key] for key in home):
            raise BrokerError("SCHEMA_INVALID")
        if not all(isinstance(normalized[key], str) and len(normalized[key]) == 64 for key in ("policy_digest", "artifact_digest")):
            raise BrokerError("SCHEMA_INVALID")
        methods = normalized["methods"]
        if not isinstance(methods, list) or len(methods) != len(set(methods)) or not set(methods) <= CAPABILITY_METHODS:
            raise BrokerError("SCHEMA_INVALID")
        normalized["methods"] = sorted(methods)
        return normalized

    def session_mint(self, claims: Mapping[str, Any], *, ttl_seconds: float = 60) -> str:
        normalized = self._validate_base_claims(claims)
        if type(ttl_seconds) not in (int, float) or ttl_seconds < 0 or ttl_seconds > 300:
            raise BrokerError("SCHEMA_INVALID")
        now = self.clock()
        envelope = {
            **normalized, "kind": "exchange", "issued_at": now,
            "expires_at": now + ttl_seconds, "nonce": secrets.token_hex(32),
            "revocation_id": secrets.token_hex(32),
        }
        handle = secrets.token_hex(32)
        _atomic_json(self.state_dir / "handles" / f"{handle}.json", {"envelope": self._sign(envelope)})
        return handle

    def session_exchange(self, handle: str) -> dict[str, Any]:
        if not isinstance(handle, str) or len(handle) != 64 or any(character not in "0123456789abcdef" for character in handle):
            raise BrokerError("HANDLE_INVALID")
        path = self.state_dir / "handles" / f"{handle}.json"
        with self._lock:
            record = _read_json(path, None)
            if not isinstance(record, dict) or set(record) != {"envelope"}:
                raise BrokerError("HANDLE_USED")
            claims = self._verify(record["envelope"], "exchange")
            nonce_digest = _digest(claims["nonce"])
            if nonce_digest in self._used:
                raise BrokerError("HANDLE_USED")
            self._used.add(nonce_digest)
            _atomic_json(self._used_path, sorted(self._used))
            try:
                path.unlink()
            except FileNotFoundError as error:
                raise BrokerError("HANDLE_USED") from error
            now = self.clock()
            capability_claims = {
                **{key: claims[key] for key in CLAIM_KEYS},
                "kind": "capability", "issued_at": now,
                "expires_at": claims["expires_at"], "nonce": secrets.token_hex(32),
                "revocation_id": claims["revocation_id"],
            }
            capability = self._sign(capability_claims)
            self._sessions[claims["session_id"]] = {
                "nonce_digest": _digest(capability_claims["nonce"]),
                "revocation_digest": _digest(claims["revocation_id"]),
                "sequence": 0, "action_ids": [], "closed": False,
            }
            _atomic_json(self._sessions_path, self._sessions)
            return {"capability": capability, "expires_at": claims["expires_at"]}

    def _authorize(self, capability: Any, method: str, sequence: Any, action_id: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        token = capability.get("capability") if isinstance(capability, dict) and set(capability) == {"capability", "expires_at"} else capability
        claims = self._verify(token, "capability")
        if method not in claims.get("methods", []):
            raise BrokerError("METHOD_DENIED")
        if claims.get("policy_digest") != self.policy_digest or claims.get("artifact_digest") != self.artifact_digest:
            raise BrokerError("DIGEST_DRIFT")
        route = self.routes.get(claims.get("route"))
        if not route:
            raise BrokerError("ROUTE_DENIED")
        route_bank = route.get("bank")
        if not isinstance(route_bank, Mapping) or any(route_bank.get(key) != claims["home_bank"].get(key) for key in ("profile_id", "bank_id")):
            raise BrokerError("ROUTE_DENIED")
        if type(sequence) is not int or sequence < 1 or not isinstance(action_id, str) or not IDENTIFIER.fullmatch(action_id):
            raise BrokerError("SCHEMA_INVALID")
        with self._lock:
            state = self._sessions.get(claims["session_id"])
            nonce_digest = _digest(claims["nonce"])
            if not state or state.get("nonce_digest") != nonce_digest:
                raise BrokerError("CAPABILITY_INVALID")
            if state.get("revocation_digest") in self._revoked or state.get("closed"):
                raise BrokerError("REVOKED")
            if action_id in state["action_ids"]:
                raise BrokerError("ACTION_REPLAY")
            if sequence <= state["sequence"]:
                raise BrokerError("SEQUENCE_ROLLBACK")
            state["sequence"] = sequence
            state["action_ids"].append(action_id)
            _atomic_json(self._sessions_path, self._sessions)
        return claims, route

    def _request(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or _contains_forbidden_key(value):
            raise BrokerError("SCHEMA_INVALID")
        if len(canonical_bytes(value)) > self.max_payload_bytes:
            raise BrokerError("REQUEST_TOO_LARGE")
        return deepcopy(value)

    def _invoke(self, route: Mapping[str, Any], method: str, request: Mapping[str, Any], timeout: float) -> tuple[bool, Any]:
        adapter = route.get("adapter")
        operation = getattr(adapter, method, None)
        if operation is None:
            raise BrokerError("ADAPTER_UNAVAILABLE")
        future = self._executor.submit(operation, deepcopy(request))
        try:
            return True, future.result(timeout=max(0, timeout))
        except FutureTimeout:
            future.cancel()
            return False, None
        except Exception as error:
            raise BrokerError("ADAPTER_UNAVAILABLE") from error

    def _read_call(self, method: str, empty: Mapping[str, Any], capability: Any, sequence: int, action_id: str,
                   request: Mapping[str, Any], timeout_seconds: float, unknown: Mapping[str, Any]) -> dict[str, Any]:
        if unknown:
            raise BrokerError("SCHEMA_INVALID")
        _, route = self._authorize(capability, method, sequence, action_id)
        ok, payload = self._invoke(route, method, self._request(request), timeout_seconds)
        if not ok:
            return self._result("unavailable", empty, {"code": "MEMORY_UNAVAILABLE", "visible": True})
        if len(canonical_bytes(payload)) > self.max_payload_bytes:
            return self._result("unavailable", empty, {"code": "MEMORY_UNAVAILABLE", "visible": True})
        return self._result("ok", payload)

    def _result(self, disposition: str, payload: Any = None, diagnostic: Any = None) -> dict[str, Any]:
        value = {
            "schema_version": 1, "policy_digest": self.policy_digest,
            "artifact_digest": self.artifact_digest, "disposition": disposition,
            "payload": deepcopy(payload),
        }
        if diagnostic is not None:
            value["diagnostic"] = diagnostic
        return value

    def recall(self, capability: Any, *, sequence: int, action_id: str, request: Mapping[str, Any],
               timeout_seconds: float = 2, **unknown: Any) -> dict[str, Any]:
        return self._read_call("recall", {"memories": []}, capability, sequence, action_id, request, timeout_seconds, unknown)

    def mental_model_fetch(self, capability: Any, *, sequence: int, action_id: str, request: Mapping[str, Any],
                           timeout_seconds: float = 2, **unknown: Any) -> dict[str, Any]:
        return self._read_call("mental_model_fetch", {"models": []}, capability, sequence, action_id, request, timeout_seconds, unknown)

    def reflect(self, capability: Any, *, sequence: int, action_id: str, request: Mapping[str, Any],
                timeout_seconds: float = 2, **unknown: Any) -> dict[str, Any]:
        if unknown:
            raise BrokerError("SCHEMA_INVALID")
        _, route = self._authorize(capability, "reflect", sequence, action_id)
        ok, payload = self._invoke(route, "reflect", self._request(request), timeout_seconds)
        if ok and len(canonical_bytes(payload)) > self.max_payload_bytes:
            ok, payload = False, None
        return self._result("ok" if ok else "unavailable", payload if ok else None,
                            None if ok else {"code": "MEMORY_UNAVAILABLE", "visible": True})

    def checkpoint(self, capability: Any, *, sequence: int, action_id: str, request: Mapping[str, Any],
                   timeout_seconds: float = 2, **unknown: Any) -> dict[str, Any]:
        if unknown:
            raise BrokerError("SCHEMA_INVALID")
        claims, route = self._authorize(capability, "checkpoint", sequence, action_id)
        value = self._request(request)
        if set(value) != {"document_id", "epoch", "checkpoint"} or not isinstance(value["document_id"], str) or not IDENTIFIER.fullmatch(value["document_id"]) or type(value["epoch"]) is not int or type(value["checkpoint"]) is not int:
            raise BrokerError("SCHEMA_INVALID")
        key = (claims["home_bank"]["profile_id"], claims["home_bank"]["bank_id"], value["document_id"])
        encoded_key = "/".join(key)
        with self._lock:
            document_lock = self._document_locks.setdefault(key, threading.Lock())
        with document_lock:
            previous = self._checkpoints.get(encoded_key)
            watermark = [value["epoch"], value["checkpoint"]]
            if previous == watermark:
                return self._result("idempotent", {"watermark": watermark})
            if previous is not None and tuple(watermark) <= tuple(previous):
                return self._result("stale", {"watermark": previous})
            ok, payload = self._invoke(route, "checkpoint", value, timeout_seconds)
            if not ok:
                return self._result("unavailable", None, {"code": "MEMORY_UNAVAILABLE", "visible": True})
            self._checkpoints[encoded_key] = watermark
            _atomic_json(self._checkpoint_path, self._checkpoints)
            return self._result("applied", {"watermark": watermark, "adapter": payload})

    def retain_outcome(self, capability: Any, *, sequence: int, action_id: str, request: Mapping[str, Any],
                       **unknown: Any) -> dict[str, Any]:
        if unknown:
            raise BrokerError("SCHEMA_INVALID")
        claims, route = self._authorize(capability, "retain_outcome", sequence, action_id)
        value = self._request(request)
        required = {"document_id", "epoch", "checkpoint", "outcome"}
        if set(value) != required or not isinstance(value["document_id"], str) or not IDENTIFIER.fullmatch(value["document_id"]) or type(value["epoch"]) is not int or type(value["checkpoint"]) is not int or not isinstance(value["outcome"], str):
            raise BrokerError("SCHEMA_INVALID")
        queue_id = secrets.token_hex(16)
        document_key = "/".join((claims["home_bank"]["profile_id"], claims["home_bank"]["bank_id"], value["document_id"]))
        watermark = [value["epoch"], value["checkpoint"]]
        request_digest = hashlib.sha256(canonical_bytes(value)).hexdigest()
        with self._lock:
            previous = self._outcomes.get(document_key)
            if previous is not None and previous["watermark"] == watermark:
                if previous["request_digest"] != request_digest:
                    raise BrokerError("DIGEST_DRIFT")
                return self._result("idempotent", {"watermark": watermark})
            if previous is not None and tuple(watermark) <= tuple(previous["watermark"]):
                return self._result("stale", {"watermark": previous["watermark"]})
        item = {
            "queue_id": queue_id, "session_id": claims["session_id"], "route": claims["route"],
            "bank_ref": claims["home_bank"], "document_id": value["document_id"],
            "epoch": value["epoch"], "checkpoint": value["checkpoint"], "request": value,
        }
        with self._lock:
            self._outcomes[document_key] = {"watermark": watermark, "request_digest": request_digest}
            self._queue.append(item)
            _atomic_json(self._outcome_path, self._outcomes)
            _atomic_json(self._queue_path, self._queue)
        self._retain_executor.submit(self._drain_item, queue_id, route)
        return self._result("queued", {"queue_id": queue_id, "watermark": [value["epoch"], value["checkpoint"]]})

    def _drain_item(self, queue_id: str, route: Mapping[str, Any]) -> None:
        # Yield so the durable queued response never waits on the adapter.
        time.sleep(0.01)
        with self._lock:
            item = next((entry for entry in self._queue if entry["queue_id"] == queue_id), None)
        if item is None:
            return
        try:
            operation = getattr(route.get("adapter"), "retain_outcome")
            operation(deepcopy(item["request"]))
        except Exception:
            return
        with self._lock:
            self._queue = [entry for entry in self._queue if entry["queue_id"] != queue_id]
            _atomic_json(self._queue_path, self._queue)

    def session_status(self, capability: Any, *, sequence: int, action_id: str, **unknown: Any) -> dict[str, Any]:
        if unknown:
            raise BrokerError("SCHEMA_INVALID")
        claims, _ = self._authorize(capability, "session_status", sequence, action_id)
        with self._lock:
            queued = sum(entry["session_id"] == claims["session_id"] for entry in self._queue)
        return self._result("active", {"queued": queued})

    def session_close(self, capability: Any, *, sequence: int, action_id: str,
                      timeout_seconds: float = 2, **unknown: Any) -> dict[str, Any]:
        if unknown:
            raise BrokerError("SCHEMA_INVALID")
        claims, route = self._authorize(capability, "session_close", sequence, action_id)
        deadline = time.monotonic() + max(0, timeout_seconds)
        remaining = max(0, deadline - time.monotonic())
        try:
            final_ok, _ = self._invoke(
                route, "checkpoint", {"session_id": claims["session_id"], "final": True}, remaining,
            )
        except BrokerError:
            final_ok = False
        while time.monotonic() < deadline:
            with self._lock:
                pending = sum(entry["session_id"] == claims["session_id"] for entry in self._queue)
            if not pending:
                break
            time.sleep(min(0.005, max(0, deadline - time.monotonic())))
        with self._lock:
            state = self._sessions[claims["session_id"]]
            state["closed"] = True
            self._revoked.add(state["revocation_digest"])
            pending = sum(entry["session_id"] == claims["session_id"] for entry in self._queue)
            _atomic_json(self._revoked_path, sorted(self._revoked))
            _atomic_json(self._sessions_path, self._sessions)
        self._write_ledger(claims, action_id, "apply", "SESSION_CLOSED")
        return self._result("closed", {"undrained": pending, "final_checkpoint": "applied" if final_ok else "unavailable"}) | {"undrained": pending}

    def _write_ledger(self, claims: Mapping[str, Any], action_id: str, decision: str, reason: str) -> None:
        if self.ledger_path is None:
            return
        route = self.routes.get(claims["route"], {})
        bank = route.get("bank")
        if not isinstance(bank, dict) or set(bank) != {"profile_id", "bank_id", "endpoint"}:
            return
        append_record(self.ledger_path, {
            "schema_version": 1, "action_id": action_id, "correlation_id": claims["session_id"],
            "source_bank": bank, "target_bank": bank, "policy_digest": self.policy_digest,
            "artifact_digest": self.artifact_digest, "decision": decision, "reason_code": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "reversible_record_id": None,
        })
