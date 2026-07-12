"""Private runtime memory broker with scoped capabilities and durable writes."""

from __future__ import annotations

import base64
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
import fcntl
import json
import math
import os
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Any, Callable, Mapping

from .adapters import Adapter
from .canonical import canonical_bytes
from .ledger import append_record


CAPABILITY_METHODS = frozenset({
    "recall", "mental_model_fetch", "transcript_checkpoint", "retain_outcome",
    "reflect", "session_status", "session_close",
})
CLAIM_KEYS = frozenset({
    "session_id", "harness_id", "home_bank", "trust_class", "companion_id",
    "policy_digest", "artifact_digest", "methods", "route",
})
ENVELOPE_KEYS = CLAIM_KEYS | {"kind", "issued_at", "expires_at", "nonce", "revocation_id", "broker_generation"}
CAPABILITY_KEYS = CLAIM_KEYS | {"kind", "issued_at", "expires_at", "nonce", "revocation_id"}
FORBIDDEN_KEYS = frozenset({
    "destination", "destination_bank", "target_bank", "home_bank", "bank", "bank_id",
    "endpoint", "url", "authorization", "bearer", "credential", "credentials", "token",
    "api_key", "control_key", "signing_key", "secret", "route",
})
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
REQUEST_SCHEMAS = {
    "recall": ({"query"}, {"limit"}),
    "mental_model_fetch": ({"model_id"}, set()),
    "transcript_checkpoint": ({"document_id", "epoch", "checkpoint"}, set()),
    "retain_outcome": ({"document_id", "epoch", "checkpoint", "outcome"}, set()),
    "reflect": ({"reflection"}, set()),
}


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
        written = 0
        while written < len(body):
            count = os.write(descriptor, body[written:])
            if count <= 0:
                raise OSError("state write failed")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    os.chmod(path, 0o600)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return deepcopy(default)
    except (OSError, json.JSONDecodeError) as error:
        raise BrokerError("STATE_INVALID") from error


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _has_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(not isinstance(key, str) or key.lower() in FORBIDDEN_KEYS or _has_forbidden_key(child)
                   for key, child in value.items())
    if isinstance(value, (list, tuple)):
        return any(_has_forbidden_key(child) for child in value)
    return False


class Broker:
    """Authorize memory calls and persist writes before adapter dispatch."""

    def __init__(
        self, *, state_dir: str | Path, signing_key: bytes | Callable[[], bytes],
        routes: Mapping[str, Mapping[str, Any]], policy_digest: str,
        artifact_digest: str, ledger_path: str | Path | None = None,
        mint_authorizer: Callable[[str, Mapping[str, Any], float], Mapping[str, Any]] | None = None,
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
        for route in self.routes.values():
            if not isinstance(route.get("adapter"), Adapter):
                raise BrokerError("ADAPTER_INVALID")
        self.policy_digest = policy_digest
        self.artifact_digest = artifact_digest
        self.ledger_path = Path(ledger_path) if ledger_path else None
        self._mint_authorizer = mint_authorizer
        self.clock = clock
        self.max_payload_bytes = max_payload_bytes
        self._lock = threading.RLock()
        self._document_locks: dict[tuple[str, str, str], threading.Lock] = {}
        self._work_locks: dict[str, threading.Lock] = {}
        self._read_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hindsight-read")
        self._write_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hindsight-write")
        self._read_futures: set[Future[Any]] = set()
        self._write_futures: set[Future[Any]] = set()
        self._used_path = self.state_dir / "used_nonces.json"
        self._revoked_path = self.state_dir / "revoked_nonces.json"
        self._work_path = self.state_dir / "durable_work.json"
        self._lease_path = self.state_dir / "broker.lease"
        self._generation = secrets.token_hex(32)
        self._work = self._install_generation()
        self._used = set(self._work["used_nonces"])
        self._revoked = set(self._work["revoked_nonces"])
        self._closed = False
        for item in tuple(self._work["queue"]):
            self._submit_write(item["queue_id"])

    def shutdown(self, *, timeout_seconds: float = 2) -> dict[str, int]:
        if self._closed:
            return {"undrained": len(self._work["queue"]), "active_reads": 0, "active_writes": 0, "retired": False}
        timeout = self._timeout(timeout_seconds)
        retired = False
        with self._lock:
            try:
                self._transaction(lambda work: work.__setitem__("generation", f"stopped-{secrets.token_hex(24)}"))
            except BrokerError as error:
                if error.code != "BROKER_RETIRED":
                    raise
                retired = True
            self._closed = True
            for future in self._read_futures:
                future.cancel()
            for future in self._write_futures:
                future.cancel()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if not self._read_futures and not self._write_futures:
                    break
            time.sleep(min(0.005, max(0, deadline - time.monotonic())))
        self._read_executor.shutdown(wait=False, cancel_futures=True)
        self._write_executor.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            return {
                "undrained": len(self._work["queue"]),
                "active_reads": sum(not future.done() for future in self._read_futures),
                "active_writes": sum(not future.done() for future in self._write_futures),
                "retired": retired,
            }

    def _owns_generation(self) -> bool:
        try:
            return _read_json(self._work_path, {}).get("generation") == self._generation
        except BrokerError:
            return False

    def _lease_descriptor(self) -> int:
        descriptor = os.open(self._lease_path, os.O_RDWR | os.O_CREAT, 0o600)
        os.fchmod(descriptor, 0o600)
        return descriptor

    @staticmethod
    def _empty_work() -> dict[str, Any]:
        return {
            "queue": [], "completed": {}, "sessions": {}, "used_nonces": [],
            "revoked_nonces": [], "exchanges": {}, "generation": "initial",
        }

    def _validate_work(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) != set(self._empty_work()):
            raise BrokerError("STATE_INVALID")
        return value

    def _sync_digest_mirrors(self, value: Mapping[str, Any]) -> None:
        _atomic_json(self._used_path, value["used_nonces"])
        _atomic_json(self._revoked_path, value["revoked_nonces"])

    def _install_generation(self) -> dict[str, Any]:
        descriptor = self._lease_descriptor()
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            current = self._validate_work(_read_json(self._work_path, self._empty_work()))
            value = deepcopy(current)
            value["generation"] = self._generation
            _atomic_json(self._work_path, value)
            try:
                self._sync_digest_mirrors(value)
            except OSError:
                pass
            return value
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _transaction(self, mutation: Callable[[dict[str, Any]], Any]) -> Any:
        descriptor = self._lease_descriptor()
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            current = self._validate_work(_read_json(self._work_path, self._empty_work()))
            if current.get("generation") != self._generation:
                raise BrokerError("BROKER_RETIRED")
            value = deepcopy(current)
            result = mutation(value)
            _atomic_json(self._work_path, value)
            self._work = value
            self._used = set(value["used_nonces"])
            self._revoked = set(value["revoked_nonces"])
            try:
                self._sync_digest_mirrors(value)
            except OSError:
                pass
            return result
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

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
        expected = ENVELOPE_KEYS if kind == "exchange" else CAPABILITY_KEYS
        if set(claims) != expected:
            raise BrokerError("CAPABILITY_INVALID")
        if type(claims.get("expires_at")) not in (int, float) or self.clock() >= claims["expires_at"]:
            raise BrokerError("EXPIRED")
        return claims

    def _validate_claims(self, claims: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(claims, Mapping) or set(claims) != CLAIM_KEYS:
            raise BrokerError("SCHEMA_INVALID")
        value = deepcopy(dict(claims))
        for key in ("session_id", "harness_id", "trust_class", "companion_id", "route"):
            if not isinstance(value[key], str) or not IDENTIFIER.fullmatch(value[key]):
                raise BrokerError("SCHEMA_INVALID")
        if not isinstance(value["home_bank"], dict) or set(value["home_bank"]) != {"profile_id", "bank_id"}:
            raise BrokerError("SCHEMA_INVALID")
        if not all(isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in value["home_bank"].values()):
            raise BrokerError("SCHEMA_INVALID")
        if not all(isinstance(value[key], str) and DIGEST.fullmatch(value[key]) for key in ("policy_digest", "artifact_digest")):
            raise BrokerError("SCHEMA_INVALID")
        methods = value["methods"]
        if not isinstance(methods, list) or len(methods) != len(set(methods)) or not set(methods) <= CAPABILITY_METHODS:
            raise BrokerError("SCHEMA_INVALID")
        value["methods"] = sorted(methods)
        return value

    def _bootstrap_response(self, action_id: str, method: str, session_id: str, payload: Any) -> dict[str, Any]:
        action_digest = hashlib.sha256(canonical_bytes({
            "action_id": action_id, "method": method, "sequence": 0,
            "session_id": session_id, "capability_nonce_digest": None,
        })).hexdigest()
        return self._response(action_id, action_digest, "ok", payload)

    def session_mint(self, control_capability: str, claims: Mapping[str, Any], *, ttl_seconds: float = 60) -> dict[str, Any]:
        value = self._validate_claims(claims)
        if type(ttl_seconds) not in (int, float) or not math.isfinite(ttl_seconds) or ttl_seconds < 0 or ttl_seconds > 300:
            raise BrokerError("SCHEMA_INVALID")
        if self._mint_authorizer is None or not isinstance(control_capability, str) or not control_capability:
            raise BrokerError("MINT_DENIED")
        try:
            authorized = self._validate_claims(self._mint_authorizer(control_capability, deepcopy(value), ttl_seconds))
        except Exception:
            raise BrokerError("MINT_DENIED") from None
        route = self.routes.get(value["route"])
        if (
            authorized != value or value["policy_digest"] != self.policy_digest
            or value["artifact_digest"] != self.artifact_digest or route is None
            or any(route.get("bank", {}).get(key) != value["home_bank"][key] for key in ("profile_id", "bank_id"))
        ):
            raise BrokerError("MINT_DENIED")
        with self._lock:
            if self._closed:
                raise BrokerError("BROKER_CLOSED")
            descriptor = self._lease_descriptor()
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                current = self._validate_work(_read_json(self._work_path, self._empty_work()))
                if current["generation"] != self._generation:
                    raise BrokerError("BROKER_RETIRED")
                now = self.clock()
                envelope = {
                    **value, "kind": "exchange", "issued_at": now, "expires_at": now + ttl_seconds,
                    "nonce": secrets.token_hex(32), "revocation_id": secrets.token_hex(32),
                    "broker_generation": current["generation"],
                }
                handle = secrets.token_hex(32)
                _atomic_json(self.state_dir / "handles" / f"{handle}.json", {"envelope": self._sign(envelope)})
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
        return self._bootstrap_response("session-mint", "session_mint", value["session_id"], {"handle": handle})

    def session_exchange(self, handle: str) -> dict[str, Any]:
        if not isinstance(handle, str) or not re.fullmatch(r"[0-9a-f]{64}", handle):
            raise BrokerError("HANDLE_INVALID")
        path = self.state_dir / "handles" / f"{handle}.json"
        with self._lock:
            record = _read_json(path, None)
            if not isinstance(record, dict) or set(record) != {"envelope"}:
                def recover(work):
                    recovered = work["exchanges"].get(handle)
                    if not recovered:
                        raise BrokerError("HANDLE_USED")
                    return deepcopy(recovered)
                recovered = self._transaction(recover)
                return self._exchange_response(recovered)
            claims = self._verify(record["envelope"], "exchange")
            nonce_digest = _sha256_text(claims["nonce"])
            now = self.clock()
            capability_claims = {
                **{key: claims[key] for key in CLAIM_KEYS}, "kind": "capability",
                "issued_at": now, "expires_at": claims["expires_at"],
                "nonce": secrets.token_hex(32), "revocation_id": claims["revocation_id"],
            }
            capability = self._sign(capability_claims)
            def exchange(work):
                if claims["broker_generation"] != work["generation"]:
                    raise BrokerError("BROKER_RETIRED")
                recovered = work["exchanges"].get(handle)
                if nonce_digest in work["used_nonces"]:
                    if recovered:
                        return deepcopy(recovered)
                    raise BrokerError("HANDLE_USED")
                work["used_nonces"].append(nonce_digest)
                work["sessions"][claims["session_id"]] = {
                    "nonce_digest": _sha256_text(capability_claims["nonce"]),
                    "revocation_digest": _sha256_text(claims["revocation_id"]),
                    "sequence": 0, "action_ids": [], "closed": False,
                }
                recovered = {
                    "session_id": claims["session_id"], "capability": capability,
                    "expires_at": claims["expires_at"], "nonce_digest": nonce_digest,
                }
                work["exchanges"][handle] = recovered
                return deepcopy(recovered)
            recovered = self._transaction(exchange)
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        return self._exchange_response(recovered)

    def _exchange_response(self, recovered: Mapping[str, Any]) -> dict[str, Any]:
        return self._bootstrap_response("session-exchange", "session_exchange", recovered["session_id"], {
            "capability": recovered["capability"], "expires_at": recovered["expires_at"],
        })

    def _authorize(self, capability: str, method: str, sequence: Any, action_id: Any,
                   *, commit: bool = True) -> tuple[dict[str, Any], dict[str, Any], str]:
        claims = self._verify(capability, "capability")
        if method not in claims.get("methods", []):
            raise BrokerError("METHOD_DENIED")
        if claims.get("policy_digest") != self.policy_digest or claims.get("artifact_digest") != self.artifact_digest:
            raise BrokerError("DIGEST_DRIFT")
        route = self.routes.get(claims.get("route"))
        if not route:
            raise BrokerError("ROUTE_DENIED")
        bank = route.get("bank")
        if not isinstance(bank, Mapping) or any(bank.get(key) != claims["home_bank"].get(key) for key in ("profile_id", "bank_id")):
            raise BrokerError("ROUTE_DENIED")
        if not isinstance(route.get("adapter"), Adapter):
            raise BrokerError("ADAPTER_INVALID")
        if type(sequence) is not int or sequence < 1 or not isinstance(action_id, str) or not IDENTIFIER.fullmatch(action_id):
            raise BrokerError("SCHEMA_INVALID")
        nonce_digest = _sha256_text(claims["nonce"])
        action_digest = hashlib.sha256(canonical_bytes({
            "action_id": action_id, "method": method, "sequence": sequence,
            "session_id": claims["session_id"], "harness_id": claims["harness_id"],
            "capability_nonce_digest": nonce_digest,
        })).hexdigest()
        if commit:
            with self._lock:
                def authorize(work):
                    self._commit_action(work, claims, sequence, action_id)
                self._transaction(authorize)
        return claims, route, action_digest

    @staticmethod
    def _commit_action(work: dict[str, Any], claims: Mapping[str, Any], sequence: int, action_id: str) -> None:
        state = work["sessions"].get(claims["session_id"])
        if not state or state.get("nonce_digest") != _sha256_text(claims["nonce"]):
            raise BrokerError("CAPABILITY_INVALID")
        if state.get("revocation_digest") in work["revoked_nonces"] or state.get("closed"):
            raise BrokerError("REVOKED")
        if action_id in state["action_ids"]:
            raise BrokerError("ACTION_REPLAY")
        if sequence <= state["sequence"]:
            raise BrokerError("SEQUENCE_ROLLBACK")
        state["sequence"] = sequence
        state["action_ids"].append(action_id)

    def _validate_request(self, method: str, request: Any) -> dict[str, Any]:
        if not isinstance(request, dict) or _has_forbidden_key(request):
            raise BrokerError("SCHEMA_INVALID")
        required, optional = REQUEST_SCHEMAS[method]
        if not required <= set(request) or set(request) - required - optional:
            raise BrokerError("SCHEMA_INVALID")
        value = deepcopy(request)
        for key in required | optional:
            if key not in value:
                continue
            item = value[key]
            if key in {"epoch", "checkpoint", "limit"}:
                if type(item) is not int or item < 0 or item > 1_000_000:
                    raise BrokerError("SCHEMA_INVALID")
            elif key == "document_id":
                if not isinstance(item, str) or not IDENTIFIER.fullmatch(item):
                    raise BrokerError("SCHEMA_INVALID")
            elif not isinstance(item, str) or not item or len(item.encode("utf-8")) > self.max_payload_bytes:
                raise BrokerError("SCHEMA_INVALID")
        if len(canonical_bytes(value)) > self.max_payload_bytes:
            raise BrokerError("REQUEST_TOO_LARGE")
        return value

    def _response(self, action_id: str, action_digest: str, disposition: str, payload: Any,
                  diagnostic: Mapping[str, Any] | None = None) -> dict[str, Any]:
        try:
            if payload is not None and len(canonical_bytes(payload)) > self.max_payload_bytes:
                payload = None
                disposition = "unavailable"
                diagnostic = {"code": "RESPONSE_TOO_LARGE", "visible": True}
        except (TypeError, ValueError):
            payload = None
            disposition = "unavailable"
            diagnostic = {"code": "RESPONSE_INVALID", "visible": True}
        return {
            "schema_version": 1, "action_id": action_id, "action_digest": action_digest,
            "policy_digest": self.policy_digest, "artifact_digest": self.artifact_digest,
            "disposition": disposition, "payload": deepcopy(payload),
            "diagnostic": deepcopy(diagnostic),
        }

    def _adapter_payload(self, method: str, payload: Any) -> dict[str, Any]:
        expected = {
            "recall": {"memories"}, "mental_model_fetch": {"models"}, "session_status": {"status"}, "reflect": {"accepted"},
        }[method]
        if not isinstance(payload, dict) or set(payload) != expected or _has_forbidden_key(payload):
            raise BrokerError("RESPONSE_INVALID")
        if method in {"recall", "mental_model_fetch"} and not isinstance(next(iter(payload.values())), list):
            raise BrokerError("RESPONSE_INVALID")
        if method == "session_status" and not isinstance(payload["status"], str):
            raise BrokerError("RESPONSE_INVALID")
        if method == "reflect" and type(payload["accepted"]) is not bool:
            raise BrokerError("RESPONSE_INVALID")
        if len(canonical_bytes(payload)) > self.max_payload_bytes:
            raise BrokerError("RESPONSE_TOO_LARGE")
        return deepcopy(payload)

    def _read_call(self, method: str, empty: Mapping[str, Any], capability: str, sequence: int,
                   action_id: str, request: Mapping[str, Any], timeout_seconds: float) -> dict[str, Any]:
        timeout = self._timeout(timeout_seconds)
        value = self._validate_request(method, request)
        _, route, action_digest = self._authorize(capability, method, sequence, action_id)
        operation = getattr(route["adapter"], method)
        future = self._read_executor.submit(operation, value)
        with self._lock:
            self._read_futures.add(future)
        future.add_done_callback(self._discard_read_future)
        try:
            payload = future.result(timeout=timeout)
        except FutureTimeout:
            return self._response(action_id, action_digest, "unavailable", empty, {"code": "MEMORY_UNAVAILABLE", "visible": True})
        except Exception:
            return self._response(action_id, action_digest, "unavailable", empty, {"code": "MEMORY_UNAVAILABLE", "visible": True})
        try:
            payload = self._adapter_payload(method, payload)
        except BrokerError as error:
            return self._response(action_id, action_digest, "unavailable", empty, {"code": error.code, "visible": True})
        return self._response(action_id, action_digest, "ok", payload)

    def _discard_read_future(self, future: Future[Any]) -> None:
        with self._lock:
            self._read_futures.discard(future)

    def _submit_write(self, queue_id: str) -> None:
        future = self._write_executor.submit(self._drain_item, queue_id)
        with self._lock:
            self._write_futures.add(future)
        future.add_done_callback(self._discard_write_future)

    def _discard_write_future(self, future: Future[Any]) -> None:
        with self._lock:
            self._write_futures.discard(future)

    @staticmethod
    def _timeout(value: Any) -> float:
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or value > 30:
            raise BrokerError("SCHEMA_INVALID")
        return float(value)

    def recall(self, capability: str, *, sequence: int, action_id: str, request: Mapping[str, Any], timeout_seconds: float = 2) -> dict[str, Any]:
        return self._read_call("recall", {"memories": []}, capability, sequence, action_id, request, timeout_seconds)

    def mental_model_fetch(self, capability: str, *, sequence: int, action_id: str, request: Mapping[str, Any], timeout_seconds: float = 2) -> dict[str, Any]:
        return self._read_call("mental_model_fetch", {"models": []}, capability, sequence, action_id, request, timeout_seconds)

    def _document_lock(self, claims: Mapping[str, Any], document_id: str) -> threading.Lock:
        key = (claims["home_bank"]["profile_id"], claims["home_bank"]["bank_id"], document_id)
        with self._lock:
            return self._document_locks.setdefault(key, threading.Lock())

    def _enqueue_watermarked(self, method: str, claims: Mapping[str, Any], route: Mapping[str, Any],
                             sequence: int, action_id: str, action_digest: str,
                             request: Mapping[str, Any]) -> dict[str, Any]:
        document_id = request["document_id"]
        state_key = "/".join((method, claims["home_bank"]["profile_id"], claims["home_bank"]["bank_id"], document_id))
        watermark = [request["epoch"], request["checkpoint"]]
        request_digest = hashlib.sha256(canonical_bytes(request)).hexdigest()
        with self._document_lock(claims, document_id):
            with self._lock:
                def enqueue(work):
                    records = [entry for entry in work["queue"] if entry.get("state_key") == state_key]
                    completed = work["completed"].get(state_key)
                    if completed:
                        records.append(completed)
                    if records:
                        latest = max(records, key=lambda entry: tuple(entry["watermark"]))
                        if latest["watermark"] == watermark:
                            if latest["request_digest"] != request_digest:
                                raise BrokerError("DIGEST_DRIFT")
                            self._commit_action(work, claims, sequence, action_id)
                            return {"disposition": "idempotent", "payload": {"watermark": watermark}, "queue_id": None}
                        if tuple(watermark) < tuple(latest["watermark"]):
                            self._commit_action(work, claims, sequence, action_id)
                            return {"disposition": "stale", "payload": {"watermark": latest["watermark"]}, "queue_id": None}
                    item = {
                        "queue_id": secrets.token_hex(16), "session_id": claims["session_id"],
                        "route": claims["route"], "method": method, "state_key": state_key,
                        "watermark": watermark, "request_digest": request_digest,
                        "idempotency_key": action_digest,
                        "adapter_request": {**request, "idempotency_key": action_digest},
                        "attempts": 0, "last_error": None, "next_retry": None,
                    }
                    self._commit_action(work, claims, sequence, action_id)
                    work["queue"].append(item)
                    return {"disposition": "queued", "payload": {"watermark": watermark, "queue_id": item["queue_id"]}, "queue_id": item["queue_id"]}
                result = self._transaction(enqueue)
            if result["queue_id"]:
                self._submit_write(result["queue_id"])
        return self._response(action_id, action_digest, result["disposition"], result["payload"])

    def transcript_checkpoint(self, capability: str, *, sequence: int, action_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        value = self._validate_request("transcript_checkpoint", request)
        claims, route, action_digest = self._authorize(capability, "transcript_checkpoint", sequence, action_id, commit=False)
        return self._enqueue_watermarked("transcript_checkpoint", claims, route, sequence, action_id, action_digest, value)

    def retain_outcome(self, capability: str, *, sequence: int, action_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        value = self._validate_request("retain_outcome", request)
        claims, route, action_digest = self._authorize(capability, "retain_outcome", sequence, action_id, commit=False)
        return self._enqueue_watermarked("retain_outcome", claims, route, sequence, action_id, action_digest, value)

    def reflect(self, capability: str, *, sequence: int, action_id: str, request: Mapping[str, Any], timeout_seconds: float = 2) -> dict[str, Any]:
        timeout = self._timeout(timeout_seconds)
        value = self._validate_request("reflect", request)
        _, route, action_digest = self._authorize(capability, "reflect", sequence, action_id)
        future = self._read_executor.submit(route["adapter"].reflect, {**value, "idempotency_key": action_digest})
        with self._lock:
            self._read_futures.add(future)
        future.add_done_callback(self._discard_read_future)
        try:
            payload = self._adapter_payload("reflect", future.result(timeout=timeout))
            return self._response(action_id, action_digest, "ok", payload)
        except Exception:
            return self._response(action_id, action_digest, "unavailable", None, {"code": "REFLECT_UNAVAILABLE", "visible": True})

    def _drain_item(self, queue_id: str) -> None:
        with self._lock:
            item = next((entry for entry in self._work["queue"] if entry["queue_id"] == queue_id), None)
            work_lock = self._work_locks.setdefault(item["state_key"] if item else queue_id, threading.Lock())
        if item is None:
            return
        while not self._closed:
            wait_for_older = False
            retry_delay = 0.0
            with work_lock:
                with self._lock:
                    item = next((entry for entry in self._work["queue"] if entry["queue_id"] == queue_id), None)
                if item is None:
                    return
                with self._lock:
                    same_key = [entry for entry in self._work["queue"] if entry["state_key"] == item["state_key"]]
                if item["watermark"] != min((entry["watermark"] for entry in same_key), key=tuple):
                    wait_for_older = True
                if wait_for_older:
                    pass
                else:
                    route = self.routes.get(item["route"])
                    if route is None or not isinstance(route.get("adapter"), Adapter):
                        return
                    try:
                        getattr(route["adapter"], item["method"])(deepcopy(item["adapter_request"]))
                    except Exception:
                        retry_delay = min(0.1, 0.01 * (2 ** min(item["attempts"], 4)))
                        with self._lock:
                            def fail(work):
                                current = next(entry for entry in work["queue"] if entry["queue_id"] == queue_id)
                                current["attempts"] += 1
                                current["last_error"] = "ADAPTER_UNAVAILABLE"
                                current["next_retry"] = self.clock() + retry_delay
                            try:
                                self._transaction(fail)
                            except (BrokerError, StopIteration):
                                return
                    else:
                        if self._closed:
                            return
                        with self._lock:
                            def complete(work):
                                current = next(entry for entry in work["queue"] if entry["queue_id"] == queue_id)
                                work["queue"] = [entry for entry in work["queue"] if entry["queue_id"] != queue_id]
                                work["completed"][current["state_key"]] = {
                                    "watermark": current["watermark"], "request_digest": current["request_digest"],
                                    "idempotency_key": current["idempotency_key"],
                                }
                            try:
                                self._transaction(complete)
                            except (BrokerError, StopIteration):
                                return
                        return
            time.sleep(0.005 if wait_for_older else retry_delay)

    def session_status(self, capability: str, *, sequence: int, action_id: str, timeout_seconds: float = 2) -> dict[str, Any]:
        timeout = self._timeout(timeout_seconds)
        claims, route, action_digest = self._authorize(capability, "session_status", sequence, action_id)
        future = self._read_executor.submit(route["adapter"].session_status, {"session_id": claims["session_id"]})
        with self._lock:
            self._read_futures.add(future)
            queued = sum(entry["session_id"] == claims["session_id"] for entry in self._work["queue"])
            failures = [{"attempts": entry["attempts"], "last_error": entry["last_error"], "next_retry": entry["next_retry"]}
                        for entry in self._work["queue"] if entry["session_id"] == claims["session_id"] and entry["last_error"]]
        future.add_done_callback(self._discard_read_future)
        try:
            adapter_status = future.result(timeout=timeout)
            adapter_status = self._adapter_payload("session_status", adapter_status)
            return self._response(action_id, action_digest, "active", {"queued": queued, "failures": failures, "adapter": adapter_status})
        except (FutureTimeout, Exception):
            return self._response(action_id, action_digest, "unavailable", {"queued": queued, "failures": failures}, {"code": "MEMORY_UNAVAILABLE", "visible": True})

    def session_close(self, capability: str, *, sequence: int, action_id: str, timeout_seconds: float = 2) -> dict[str, Any]:
        timeout = self._timeout(timeout_seconds)
        claims, _, action_digest = self._authorize(capability, "session_close", sequence, action_id, commit=False)
        final_document = f"final-{hashlib.sha256(claims['session_id'].encode()).hexdigest()[:32]}"
        final_request = {"document_id": final_document, "epoch": 0, "checkpoint": sequence}
        queue_id = secrets.token_hex(16)
        state_key = "/".join(("transcript_checkpoint", claims["home_bank"]["profile_id"], claims["home_bank"]["bank_id"], final_document))
        item = {
            "queue_id": queue_id, "session_id": claims["session_id"], "route": claims["route"],
            "method": "transcript_checkpoint", "state_key": state_key, "watermark": [0, sequence],
            "request_digest": hashlib.sha256(canonical_bytes(final_request)).hexdigest(),
            "idempotency_key": action_digest,
            "adapter_request": {**final_request, "idempotency_key": action_digest},
            "attempts": 0, "last_error": None, "next_retry": None,
        }
        with self._lock:
            def close(work):
                self._commit_action(work, claims, sequence, action_id)
                work["queue"].append(item)
                state = work["sessions"][claims["session_id"]]
                state["closed"] = True
                if state["revocation_digest"] not in work["revoked_nonces"]:
                    work["revoked_nonces"].append(state["revocation_digest"])
            self._transaction(close)
        self._submit_write(queue_id)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                pending = sum(entry["session_id"] == claims["session_id"] for entry in self._work["queue"])
            if not pending:
                break
            time.sleep(min(0.005, max(0, deadline - time.monotonic())))
        with self._lock:
            pending = sum(entry["session_id"] == claims["session_id"] for entry in self._work["queue"])
        self._write_ledger(claims, action_id)
        return self._response(action_id, action_digest, "closed", {
            "undrained": pending, "final_checkpoint": "drained" if pending == 0 else "queued",
        })

    def _write_ledger(self, claims: Mapping[str, Any], action_id: str) -> None:
        if self.ledger_path is None:
            return
        bank = self.routes.get(claims["route"], {}).get("bank")
        if not isinstance(bank, dict) or set(bank) != {"profile_id", "bank_id", "endpoint"}:
            return
        append_record(self.ledger_path, {
            "schema_version": 1, "action_id": action_id, "correlation_id": claims["session_id"],
            "source_bank": bank, "target_bank": bank, "policy_digest": self.policy_digest,
            "artifact_digest": self.artifact_digest, "decision": "apply", "reason_code": "SESSION_CLOSED",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "reversible_record_id": None,
        })
