"""Bounded newline-delimited JSON-RPC over a private Unix socket."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import stat
import threading
from typing import Any, Mapping

from .broker import Broker, BrokerError


MAX_REQUEST_BYTES = 128 * 1024
RPC_METHODS = {
    "session_mint": "session_mint",
    "session_exchange": "session_exchange",
    "session_close": "session_close",
    "recall": "recall",
    "mental_model_fetch": "mental_model_fetch",
    "transcript_checkpoint": "transcript_checkpoint",
    "retain_outcome": "retain_outcome",
    "reflect": "reflect",
    "session_status": "session_status",
}
SOCKET_LIFECYCLE_LOCK = threading.RLock()


class UnixJsonRpcServer:
    def __init__(self, path: str | Path, broker: Broker, *, max_request_bytes: int = MAX_REQUEST_BYTES) -> None:
        self.path = Path(path)
        self.broker = broker
        self.max_request_bytes = max_request_bytes
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._closing = threading.Event()
        self._bound_identity: tuple[int, int] | None = None

    def start(self) -> None:
        with SOCKET_LIFECYCLE_LOCK:
            if self._socket is not None or self._thread is not None or self._bound_identity is not None:
                raise RuntimeError("Unix JSON-RPC server is already started")
            self._closing.clear()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            bound_identity: tuple[int, int] | None = None
            try:
                previous_umask = os.umask(0o177)
                try:
                    listener.bind(str(self.path))
                finally:
                    os.umask(previous_umask)
                metadata = self.path.lstat()
                bound_identity = (metadata.st_dev, metadata.st_ino)
                os.chmod(self.path, 0o600)
                listener.listen(16)
                listener.settimeout(0.1)
                thread = threading.Thread(
                    target=self._serve,
                    args=(listener,),
                    name="hindsight-json-rpc",
                    daemon=True,
                )
                thread.start()
            except Exception:
                listener.close()
                self._unlink_bound_path(bound_identity)
                self._bound_identity = None
                raise
            self._socket = listener
            self._thread = thread
            self._bound_identity = bound_identity

    def _serve(self, listener: socket.socket) -> None:
        while not self._closing.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(target=self._connection, args=(connection,), daemon=True).start()

    def _connection(self, connection: socket.socket) -> None:
        with connection:
            stream = connection.makefile("rwb")
            line = stream.readline(self.max_request_bytes + 1)
            response = self._error(None, -32600, "REQUEST_INVALID")
            if len(line) <= self.max_request_bytes and line.endswith(b"\n"):
                response = self.dispatch(line)
            stream.write(json.dumps(response, sort_keys=True, separators=(",", ":")).encode() + b"\n")
            stream.flush()

    def dispatch(self, line: bytes) -> dict[str, Any]:
        request: Any = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or set(request) != {"jsonrpc", "id", "method", "params"}:
                raise BrokerError("SCHEMA_INVALID")
            if request["jsonrpc"] != "2.0" or not isinstance(request["method"], str) or not isinstance(request["params"], dict):
                raise BrokerError("SCHEMA_INVALID")
            if request["id"] is not None and type(request["id"]) not in {str, int}:
                raise BrokerError("SCHEMA_INVALID")
            target = RPC_METHODS.get(request["method"])
            if target is None:
                raise BrokerError("METHOD_DENIED")
            result = getattr(self.broker, target)(**request["params"])
            return {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._error(None, -32700, "PARSE_ERROR")
        except BrokerError as error:
            return self._error(request.get("id") if isinstance(request, dict) else None, -32000, error.code)
        except (TypeError, ValueError):
            return self._error(request.get("id") if isinstance(request, dict) else None, -32602, "SCHEMA_INVALID")
        except Exception:
            return self._error(request.get("id") if isinstance(request, dict) else None, -32603, "INTERNAL_ERROR")

    @staticmethod
    def _error(identifier: Any, number: int, code: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": identifier, "error": {"code": number, "message": code}}

    def close(self) -> None:
        with SOCKET_LIFECYCLE_LOCK:
            self._closing.set()
            if self._socket is not None:
                self._socket.close()
            if self._thread is not None:
                self._thread.join(timeout=1)
            self._unlink_bound_path(self._bound_identity)
            self._socket = None
            self._thread = None
            self._bound_identity = None

    def _unlink_bound_path(self, identity: tuple[int, int] | None) -> None:
        with SOCKET_LIFECYCLE_LOCK:
            if identity is None:
                return
            try:
                metadata = self.path.lstat()
                if (
                    stat.S_ISSOCK(metadata.st_mode)
                    and identity == (metadata.st_dev, metadata.st_ino)
                ):
                    self.path.unlink()
            except OSError:
                return


class JsonRpcClient:
    def __init__(self, path: str | Path, *, timeout_seconds: float = 2) -> None:
        self.path = Path(path)
        self.timeout_seconds = timeout_seconds
        self._next_id = 0

    def _call(self, method: str, params: Mapping[str, Any]) -> Any:
        self._next_id += 1
        request = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": dict(params)}
        body = json.dumps(request, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        if len(body) > MAX_REQUEST_BYTES:
            raise BrokerError("REQUEST_TOO_LARGE")
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout_seconds)
        with connection:
            connection.connect(str(self.path))
            connection.sendall(body)
            response = connection.makefile("rb").readline(MAX_REQUEST_BYTES + 1)
        if len(response) > MAX_REQUEST_BYTES or not response.endswith(b"\n"):
            raise BrokerError("RESPONSE_INVALID")
        try:
            decoded = json.loads(response)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise BrokerError("RESPONSE_INVALID") from error
        if not isinstance(decoded, dict) or decoded.get("jsonrpc") != "2.0" or decoded.get("id") != self._next_id:
            raise BrokerError("RESPONSE_INVALID")
        if set(decoded) == {"jsonrpc", "id", "error"}:
            error = decoded["error"]
            if not isinstance(error, dict) or set(error) != {"code", "message"} or type(error["code"]) is not int or not isinstance(error["message"], str):
                raise BrokerError("RESPONSE_INVALID")
            raise BrokerError(error["message"])
        if set(decoded) != {"jsonrpc", "id", "result"} or not isinstance(decoded["result"], dict):
            raise BrokerError("RESPONSE_INVALID")
        return decoded["result"]

    def session_mint(self, control_capability: str, claims: Mapping[str, Any], *, ttl_seconds: float = 60):
        return self._call("session_mint", {"control_capability": control_capability, "claims": dict(claims), "ttl_seconds": ttl_seconds})

    def session_exchange(self, handle: str):
        return self._call("session_exchange", {"handle": handle})

    def session_close(self, capability: str, *, sequence: int, action_id: str, timeout_seconds: float = 2):
        return self._call("session_close", {"capability": capability, "sequence": sequence, "action_id": action_id, "timeout_seconds": timeout_seconds})

    def recall(self, capability: str, *, sequence: int, action_id: str, request: Mapping[str, Any], timeout_seconds: float = 2):
        return self._call("recall", {"capability": capability, "sequence": sequence, "action_id": action_id, "request": dict(request), "timeout_seconds": timeout_seconds})

    def mental_model_fetch(self, capability: str, *, sequence: int, action_id: str, request: Mapping[str, Any], timeout_seconds: float = 2):
        return self._call("mental_model_fetch", {"capability": capability, "sequence": sequence, "action_id": action_id, "request": dict(request), "timeout_seconds": timeout_seconds})

    def transcript_checkpoint(self, capability: str, *, sequence: int, action_id: str, request: Mapping[str, Any]):
        return self._call("transcript_checkpoint", {"capability": capability, "sequence": sequence, "action_id": action_id, "request": dict(request)})

    def retain_outcome(self, capability: str, *, sequence: int, action_id: str, request: Mapping[str, Any]):
        return self._call("retain_outcome", {"capability": capability, "sequence": sequence, "action_id": action_id, "request": dict(request)})

    def reflect(self, capability: str, *, sequence: int, action_id: str, request: Mapping[str, Any], timeout_seconds: float = 2):
        return self._call("reflect", {"capability": capability, "sequence": sequence, "action_id": action_id, "request": dict(request), "timeout_seconds": timeout_seconds})

    def session_status(self, capability: str, *, sequence: int, action_id: str, timeout_seconds: float = 2):
        return self._call("session_status", {"capability": capability, "sequence": sequence, "action_id": action_id, "timeout_seconds": timeout_seconds})
