#!/usr/bin/env python3
"""Keep inference credentials outside the trigger-evaluation container."""

from __future__ import annotations

import http.client
import http.server
import json
import os
import re
import socket
import socketserver
import ssl
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

SOCKET_PATH = Path("/broker-socket/inference.sock")
MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_EVENT_BYTES = 1024 * 1024
MAX_REQUESTS = 32
REQUEST_TIMEOUT = 120.0
CLIENT_TIMEOUT = 10.0
UPSTREAMS = {
    "api_key": ("api.openai.com", "/v1/responses"),
    "chatgpt": ("chatgpt.com", "/backend-api/codex/responses"),
}
INVALID_REQUEST = "Inference request rejected by the trigger evaluation broker."
UPSTREAM_ERROR = "Inference failed. Check the selected model and provider, then retry."
AUTH_ERROR = "Inference authentication expired or was rejected. Refresh the host login or API key, then retry."
# Codex ResponsesApiRequest fields, plus the instructions field used by older
# Codex releases. Stored prompts, conversations, and hosted feature switches
# deliberately do not cross this boundary.
REQUEST_FIELDS = frozenset({
    "model", "stream", "service_tier", "input", "tools", "tool_choice",
    "parallel_tool_calls", "reasoning", "store", "stream_options", "include",
    "prompt_cache_key", "text", "client_metadata", "instructions",
})


@dataclass(frozen=True)
class Credentials:
    kind: str
    token: str = field(repr=False)
    account_id: str | None = field(default=None, repr=False)

    @classmethod
    def parse(cls, value: Any) -> "Credentials":
        if not isinstance(value, dict) or set(value) - {"kind", "token", "account_id"}:
            raise ValueError("Invalid broker credential input")
        kind = value.get("kind")
        token = value.get("token")
        account = value.get("account_id")
        if kind not in UPSTREAMS or not isinstance(token, str) or not 1 <= len(token) <= 16384:
            raise ValueError("Invalid broker credential input")
        if not all(33 <= ord(character) <= 126 for character in token):
            raise ValueError("Invalid broker credential input")
        if account is not None and (
            kind != "chatgpt"
            or not isinstance(account, str)
            or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", account)
        ):
            raise ValueError("Invalid broker credential input")
        return cls(kind, token, account)


def _contains_remote_content(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("type") in {"input_image", "input_file", "item_reference"} or {"file_id", "image_url"} & value.keys():
            return True
        return any(_contains_remote_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_remote_content(item) for item in value)
    return False


def _local_tool(tool: Any, depth: int = 0) -> bool:
    if not isinstance(tool, dict) or depth > 8:
        return False
    kind = tool.get("type")
    if kind in {"function", "custom"}:
        return True
    if kind == "namespace":
        children = tool.get("tools")
        return isinstance(children, list) and all(_local_tool(child, depth + 1) for child in children)
    return False


def prepare_request(body: bytes) -> bytes:
    """Permit local function/custom calls, never provider-hosted tools or files."""
    value = json.loads(body)
    if not isinstance(value, dict) or set(value) - REQUEST_FIELDS:
        raise ValueError(INVALID_REQUEST)
    model = value.get("model")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", model):
        raise ValueError(INVALID_REQUEST)
    tools = value.get("tools", [])
    if not isinstance(tools, list) or not all(_local_tool(tool) for tool in tools):
        raise ValueError(INVALID_REQUEST)
    choice = value.get("tool_choice", "auto")
    if isinstance(choice, dict):
        if choice.get("type") not in {"function", "custom"}:
            raise ValueError(INVALID_REQUEST)
    elif choice not in ("auto", "none", "required"):
        raise ValueError(INVALID_REQUEST)
    if value.get("previous_response_id") is not None or value.get("conversation") is not None:
        raise ValueError(INVALID_REQUEST)
    if _contains_remote_content(value.get("input")):
        raise ValueError(INVALID_REQUEST)
    value["store"] = False
    output = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(output) > MAX_REQUEST_BYTES:
        raise ValueError(INVALID_REQUEST)
    return output


def _new_https_connection(host: str, timeout: float) -> http.client.HTTPSConnection:
    # http.client does not consult HTTP(S)_PROXY or perform HTTP redirects.
    return http.client.HTTPSConnection(host, timeout=timeout, context=ssl.create_default_context())


class BrokerServer(socketserver.UnixStreamServer):
    def __init__(
        self,
        path: Path,
        credentials: Credentials,
        *,
        connection_factory: Callable[..., Any] = _new_https_connection,
    ) -> None:
        self.credentials = credentials
        self.connection_factory = connection_factory
        self.requests_started = 0
        super().__init__(str(path), BrokerHandler)
        os.chmod(path, 0o600)

    def get_request(self) -> tuple[socket.socket, Any]:
        connection, address = super().get_request()
        connection.settimeout(CLIENT_TIMEOUT)
        return connection, address

    def handle_error(self, request: Any, client_address: Any) -> None:
        # Exceptions can contain upstream headers; do not print them.
        pass


class BrokerHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "TriggerBroker"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self._error(code, INVALID_REQUEST)

    def _error(self, code: int, message: str) -> None:
        self.close_connection = True
        body = json.dumps({"error": {"message": message, "type": "trigger_eval_broker"}}).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass

    def handle_expect_100(self) -> bool:
        self._error(400, INVALID_REQUEST)
        return False

    def do_POST(self) -> None:
        self.close_connection = True
        self.server.requests_started += 1
        if self.server.requests_started > MAX_REQUESTS:
            self._error(429, "Trigger evaluation inference request limit reached.")
            return
        lengths = self.headers.get_all("Content-Length", [])
        content_types = self.headers.get_all("Content-Type", [])
        if (
            self.path != "/v1/responses"
            or self.requestline.split()[1] != "/v1/responses"
            or self.headers.get("Transfer-Encoding") is not None
            or self.headers.get("Content-Encoding") is not None
            or self.headers.get("Expect") is not None
            or len(lengths) != 1
            or not re.fullmatch(r"[0-9]{1,10}", lengths[0])
            or len(content_types) != 1
            or content_types[0].split(";", 1)[0].strip().lower() != "application/json"
        ):
            self._error(400, INVALID_REQUEST)
            return
        length = int(lengths[0])
        if not 0 < length <= MAX_REQUEST_BYTES:
            self._error(413, INVALID_REQUEST)
            return
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError(INVALID_REQUEST)
            body = prepare_request(body)
        except (OSError, ValueError, TypeError, RecursionError):
            self._error(400, INVALID_REQUEST)
            return
        self._forward(body)

    def _forward(self, body: bytes) -> None:
        credential = self.server.credentials
        host, path = UPSTREAMS[credential.kind]
        connection = None
        started_response = False
        deadline = time.monotonic() + REQUEST_TIMEOUT
        try:
            connection = self.server.connection_factory(host, REQUEST_TIMEOUT)
            headers = {
                "Authorization": f"Bearer {credential.token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream, application/json",
                "User-Agent": "codex-trigger-eval-broker",
                "originator": "codex_cli_rs",
            }
            if credential.account_id:
                headers["ChatGPT-Account-ID"] = credential.account_id
            connection.connect()
            self._set_remaining_timeout(connection, deadline)
            connection.request("POST", path, body=body, headers=headers)
            self._set_remaining_timeout(connection, deadline)
            response = connection.getresponse()
            if response.status != 200:
                self._error(401 if response.status in (401, 403) else 502,
                            AUTH_ERROR if response.status in (401, 403) else UPSTREAM_ERROR)
                return
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type not in {"text/event-stream", "application/json"}:
                self._error(502, UPSTREAM_ERROR)
                return
            total = 0
            buffer = b""
            while True:
                self._set_remaining_timeout(connection, deadline)
                chunk = response.read1(65536)
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise ValueError("Response too large")
                buffer += chunk
                if content_type == "text/event-stream":
                    buffer = buffer.replace(b"\r\n", b"\n")
                    while b"\n\n" in buffer:
                        event, buffer = buffer.split(b"\n\n", 1)
                        output = self._sse_event(event)
                        if output:
                            if not started_response:
                                self._start_success(content_type)
                                started_response = True
                            self.wfile.write(output)
                            self.wfile.flush()
                    if len(buffer) > MAX_EVENT_BYTES:
                        raise ValueError("Event too large")
                if not chunk:
                    break
            if content_type == "application/json":
                value = json.loads(buffer)
                if self._is_error(value):
                    raise ValueError("Upstream error")
                output = self._serialize_success(value)
                self._start_success(content_type)
                started_response = True
                self.wfile.write(output)
            elif buffer.strip() or not started_response:
                raise ValueError("Incomplete event stream")
        except (OSError, ValueError, TypeError, RecursionError, http.client.HTTPException):
            if not started_response:
                self._error(502, UPSTREAM_ERROR)
            else:
                try:
                    error = json.dumps({"type": "error", "message": UPSTREAM_ERROR}, separators=(",", ":"))
                    self.wfile.write(f"event: error\ndata: {error}\n\n".encode())
                except OSError:
                    pass
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _set_remaining_timeout(connection: Any, deadline: float) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        if getattr(connection, "sock", None) is not None:
            connection.sock.settimeout(remaining)

    @staticmethod
    def _is_error(value: Any) -> bool:
        if not isinstance(value, dict):
            return True
        response = value.get("response")
        return bool(
            value.get("error")
            or value.get("type") in {"error", "response.failed"}
            or value.get("status") == "failed"
            or (isinstance(response, dict) and (response.get("error") or response.get("status") == "failed"))
        )

    def _sse_event(self, event: bytes) -> bytes:
        if len(event) > MAX_EVENT_BYTES:
            raise ValueError("Event too large")
        data = b"\n".join(line[5:].lstrip(b" ") for line in event.split(b"\n") if line.startswith(b"data:"))
        if not data:
            return b""
        if data == b"[DONE]":
            return b"data: [DONE]\n\n"
        value = json.loads(data)
        if self._is_error(value) or not isinstance(value.get("type"), str) or not value["type"].startswith("response."):
            raise ValueError("Upstream error")
        # Rebuild SSE framing, dropping all unneeded upstream fields and headers.
        return b"data: " + self._serialize_success(value) + b"\n\n"

    def _serialize_success(self, value: Any) -> bytes:
        if self._contains_token(value):
            raise ValueError("Upstream reflected a credential")
        output = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
        return output

    def _contains_token(self, value: Any) -> bool:
        if isinstance(value, str):
            return self.server.credentials.token in value
        if isinstance(value, dict):
            return any(self._contains_token(key) or self._contains_token(item) for key, item in value.items())
        if isinstance(value, list):
            return any(self._contains_token(item) for item in value)
        return False

    def _start_success(self, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Connection", "close")
        self.end_headers()


def main() -> int:
    try:
        line = sys.stdin.buffer.readline(65537)
        if not line.endswith(b"\n") or len(line) > 65536:
            raise ValueError
        credentials = Credentials.parse(json.loads(line))
        with BrokerServer(SOCKET_PATH, credentials) as server:
            print("READY", flush=True)
            server.serve_forever(poll_interval=0.25)
    except Exception:
        print("Trigger evaluation broker could not start.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
