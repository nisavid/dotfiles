"""Bounded newline-delimited JSON-RPC over a private Unix socket."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import threading
from typing import Any, Mapping

from .broker import Broker, BrokerError


MAX_REQUEST_BYTES = 128 * 1024
RPC_METHODS = {
    "session_exchange": "session_exchange",
    "exchange": "session_exchange",
    "session_close": "session_close",
    "close": "session_close",
    "recall": "recall",
    "mental_model_fetch": "mental_model_fetch",
    "checkpoint": "checkpoint",
    "retain_outcome": "retain_outcome",
    "reflect": "reflect",
    "session_status": "session_status",
    "status": "session_status",
}


class UnixJsonRpcServer:
    def __init__(self, path: str | Path, broker: Broker, *, max_request_bytes: int = MAX_REQUEST_BYTES) -> None:
        self.path = Path(path)
        self.broker = broker
        self.max_request_bytes = max_request_bytes
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._closing = threading.Event()

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.path))
        os.chmod(self.path, 0o600)
        listener.listen(16)
        listener.settimeout(0.1)
        self._socket = listener
        self._thread = threading.Thread(target=self._serve, name="hindsight-json-rpc", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        assert self._socket is not None
        while not self._closing.is_set():
            try:
                connection, _ = self._socket.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(target=self._connection, args=(connection,), daemon=True).start()

    def _connection(self, connection: socket.socket) -> None:
        with connection:
            stream = connection.makefile("rwb")
            line = stream.readline(self.max_request_bytes + 1)
            if len(line) > self.max_request_bytes or not line.endswith(b"\n"):
                response = self._error(None, -32600, "REQUEST_INVALID")
            else:
                response = self.dispatch(line)
            stream.write(json.dumps(response, sort_keys=True, separators=(",", ":")).encode() + b"\n")
            stream.flush()

    def dispatch(self, line: bytes) -> dict[str, Any]:
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or set(request) != {"jsonrpc", "id", "method", "params"}:
                raise BrokerError("SCHEMA_INVALID")
            if request["jsonrpc"] != "2.0" or not isinstance(request["method"], str) or not isinstance(request["params"], dict):
                raise BrokerError("SCHEMA_INVALID")
            target = RPC_METHODS.get(request["method"])
            if target is None:
                raise BrokerError("METHOD_DENIED")
            result = getattr(self.broker, target)(**request["params"])
            return {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._error(None, -32700, "PARSE_ERROR")
        except BrokerError as error:
            identifier = request.get("id") if isinstance(locals().get("request"), dict) else None
            return self._error(identifier, -32000, error.code)
        except Exception:
            identifier = request.get("id") if isinstance(locals().get("request"), dict) else None
            return self._error(identifier, -32603, "INTERNAL_ERROR")

    @staticmethod
    def _error(identifier: Any, number: int, code: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": identifier, "error": {"code": number, "message": code}}

    def close(self) -> None:
        self._closing.set()
        if self._socket is not None:
            self._socket.close()
        if self._thread is not None:
            self._thread.join(timeout=1)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class JsonRpcClient:
    def __init__(self, path: str | Path, *, timeout_seconds: float = 2) -> None:
        self.path = Path(path)
        self.timeout_seconds = timeout_seconds
        self._next_id = 0

    def call(self, method: str, params: Mapping[str, Any]) -> Any:
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
        try:
            decoded = json.loads(response)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise BrokerError("RESPONSE_INVALID") from error
        if set(decoded) == {"jsonrpc", "id", "error"}:
            raise BrokerError(decoded["error"].get("message", "RPC_ERROR"))
        if set(decoded) != {"jsonrpc", "id", "result"}:
            raise BrokerError("RESPONSE_INVALID")
        return decoded["result"]
