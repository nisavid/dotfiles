"""Authenticated, redacted loopback HTTP control surface."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import ipaddress
import json
import re
import socket
import threading
from typing import Any, Callable, Mapping


DEFAULT_MAX_REQUEST_BYTES = 16 * 1024
DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
SESSION_OPERATIONS = frozenset({"mint", "status", "close"})
STATUS_KEYS = frozenset(
    {"schema_version", "state", "policy_digest", "active_sessions"}
)
PLAN_SUMMARY_KEYS = frozenset(
    {"schema_version", "plan_digest", "destructive", "actions"}
)
PLAN_ACTION_KEYS = frozenset({"id", "kind"})
FORBIDDEN_RESPONSE_KEYS = frozenset(
    {
        "access_key",
        "api_key",
        "authorization",
        "bearer",
        "capability",
        "control_key",
        "credential",
        "credentials",
        "data_plane_key",
        "data_plane_token",
        "envelope_handle",
        "handle",
        "password",
        "private_key",
        "profile_bearer",
        "proxy_authorization",
        "secret",
        "signing_key",
        "signing_material",
        "session_capability",
        "token",
    }
)
FORBIDDEN_RESPONSE_KEY_TOKENS = frozenset(
    key.replace("_", "") for key in FORBIDDEN_RESPONSE_KEYS
)
ERROR_STATUSES = {
    "NOT_FOUND": 404,
    "METHOD_DENIED": 405,
    "REQUEST_TOO_LARGE": 413,
    "SCHEMA_INVALID": 400,
    "RESPONSE_INVALID": 500,
}


class ControlServerError(ValueError):
    """Content-free control service rejection."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class _IPv6ThreadingHTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                return True
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if normalized in FORBIDDEN_RESPONSE_KEY_TOKENS:
                return True
            if _contains_forbidden_key(child):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_key(child) for child in value)
    return False


def _closed_mapping(
    value: Any, keys: frozenset[str], label: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ControlServerError(f"{label}_INVALID")
    return value


def _status_response(value: Any) -> Mapping[str, Any]:
    result = _closed_mapping(value, STATUS_KEYS, "RESPONSE")
    if (
        type(result["schema_version"]) is not int
        or result["schema_version"] != 1
        or not isinstance(result["state"], str)
        or not IDENTIFIER.fullmatch(result["state"])
        or not isinstance(result["policy_digest"], str)
        or not DIGEST.fullmatch(result["policy_digest"])
        or type(result["active_sessions"]) is not int
        or result["active_sessions"] < 0
    ):
        raise ControlServerError("RESPONSE_INVALID")
    return result


def _plan_response(value: Any, plan_digest: str) -> Mapping[str, Any]:
    result = _closed_mapping(value, PLAN_SUMMARY_KEYS, "RESPONSE")
    if (
        type(result["schema_version"]) is not int
        or result["schema_version"] != 1
        or result["plan_digest"] != plan_digest
        or result["destructive"] is not False
        or not isinstance(result["actions"], (list, tuple))
    ):
        raise ControlServerError("RESPONSE_INVALID")
    for action in result["actions"]:
        record = _closed_mapping(action, PLAN_ACTION_KEYS, "RESPONSE")
        if any(
            not isinstance(record[key], str)
            or not IDENTIFIER.fullmatch(record[key])
            for key in PLAN_ACTION_KEYS
        ):
            raise ControlServerError("RESPONSE_INVALID")
    return result


class ControlServer:
    """Serve a closed, secret-free control API on a literal loopback address."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        access_key_resolver: Callable[[], str | bytes],
        forbidden_material_resolver: Callable[[], tuple[str | bytes, ...]],
        status_provider: Callable[[], Mapping[str, Any]],
        plan_provider: Callable[[str], Mapping[str, Any] | None],
        session_operator: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
        max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        try:
            address = ipaddress.ip_address(host)
        except ValueError as error:
            raise ControlServerError("BIND_DENIED") from error
        if not address.is_loopback or host not in {"127.0.0.1", "::1"}:
            raise ControlServerError("BIND_DENIED")
        if type(port) is not int or not 0 <= port <= 65535:
            raise ControlServerError("PORT_INVALID")
        if not callable(access_key_resolver) or not callable(
            forbidden_material_resolver
        ):
            raise ControlServerError("ACCESS_KEY_RESOLVER_INVALID")
        if not all(
            callable(value)
            for value in (status_provider, plan_provider, session_operator)
        ):
            raise ControlServerError("PROVIDER_INVALID")
        if type(max_request_bytes) is not int or max_request_bytes < 256:
            raise ControlServerError("REQUEST_LIMIT_INVALID")
        if type(max_response_bytes) is not int or max_response_bytes < 128:
            raise ControlServerError("RESPONSE_LIMIT_INVALID")

        self.host = host
        self.port = port
        self.access_key_resolver = access_key_resolver
        self.forbidden_material_resolver = forbidden_material_resolver
        self.status_provider = status_provider
        self.plan_provider = plan_provider
        self.session_operator = session_operator
        self.max_request_bytes = max_request_bytes
        self.max_response_bytes = max_response_bytes
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            raise ControlServerError("ALREADY_STARTED")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:
                owner._handle(self, "GET")

            def do_POST(self) -> None:
                owner._handle(self, "POST")

            def do_PUT(self) -> None:
                owner._handle(self, "PUT")

            def do_PATCH(self) -> None:
                owner._handle(self, "PATCH")

            def do_DELETE(self) -> None:
                owner._handle(self, "DELETE")

            def do_OPTIONS(self) -> None:
                owner._handle(self, "OPTIONS")

            def do_HEAD(self) -> None:
                owner._handle(self, "HEAD")

            def log_message(self, format: str, *args: Any) -> None:
                return

        server_type = (
            _IPv6ThreadingHTTPServer
            if self.host == "::1"
            else ThreadingHTTPServer
        )
        try:
            server = server_type((self.host, self.port), Handler)
        except OSError as error:
            raise ControlServerError("BIND_FAILED") from error
        server.daemon_threads = True
        self._server = server
        self.port = int(server.server_address[1])
        self._thread = threading.Thread(
            target=server.serve_forever,
            name="hindsight-control-http",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=1)
        self._thread = None
        self._server = None

    def _handle(self, handler: BaseHTTPRequestHandler, method: str) -> None:
        if not self._authenticated(handler):
            self._send(handler, 401, {"error": "AUTH_REQUIRED"})
            return
        try:
            status, result = self._dispatch(handler, method)
            self._send(handler, status, result)
        except ControlServerError as error:
            if error.code in ERROR_STATUSES:
                self._send(
                    handler,
                    ERROR_STATUSES[error.code],
                    {"error": error.code},
                    validate=False,
                )
            else:
                self._send(
                    handler, 500, {"error": "INTERNAL_ERROR"}, validate=False
                )
        except Exception:
            self._send(
                handler, 500, {"error": "INTERNAL_ERROR"}, validate=False
            )

    def _authenticated(self, handler: BaseHTTPRequestHandler) -> bool:
        try:
            resolved = self.access_key_resolver()
        except Exception:
            return False
        if isinstance(resolved, str):
            expected = resolved.encode("utf-8")
        elif isinstance(resolved, bytes):
            expected = resolved
        else:
            return False
        if len(expected) < 32 or len(expected) > 4096:
            return False
        handler._hindsight_control_secret = expected
        names = {name.lower() for name in handler.headers.keys()}
        if (
            "proxy-authorization" in names
            or "forwarded" in names
            or any(name.startswith("x-forwarded-") for name in names)
        ):
            return False
        values = handler.headers.get_all("Authorization", [])
        if len(values) != 1 or not values[0].startswith("Bearer "):
            return False
        supplied = values[0][7:].encode("utf-8")
        return hmac.compare_digest(supplied, expected)

    def _dispatch(
        self, handler: BaseHTTPRequestHandler, method: str
    ) -> tuple[int, Mapping[str, Any]]:
        header_bytes = self._header_bytes(handler)
        if header_bytes > self.max_request_bytes:
            raise ControlServerError("REQUEST_TOO_LARGE")
        path = handler.path.split("?", 1)[0]
        if method == "GET":
            if path == "/health":
                return 200, {"schema_version": 1, "status": "ok"}
            if path == "/v1/status":
                return 200, _status_response(self.status_provider())
            prefix = "/v1/plans/"
            if path.startswith(prefix):
                plan_digest = path[len(prefix) :]
                if not DIGEST.fullmatch(plan_digest):
                    raise ControlServerError("NOT_FOUND")
                result = self.plan_provider(plan_digest)
                if result is None:
                    raise ControlServerError("NOT_FOUND")
                return 200, _plan_response(result, plan_digest)
            raise ControlServerError("NOT_FOUND")

        if method != "POST":
            raise ControlServerError("METHOD_DENIED")
        prefix = "/v1/sessions/"
        if not path.startswith(prefix):
            raise ControlServerError(
                "METHOD_DENIED"
                if path in {"/health", "/v1/status"}
                else "NOT_FOUND"
            )
        operation = path[len(prefix) :]
        if operation not in SESSION_OPERATIONS:
            raise ControlServerError("NOT_FOUND")
        request = self._read_request(handler)
        if (
            set(request) != {"session_id"}
            or not isinstance(request["session_id"], str)
            or not IDENTIFIER.fullmatch(request["session_id"])
        ):
            raise ControlServerError("SCHEMA_INVALID")
        result = self.session_operator(operation, request)
        if (
            not isinstance(result, Mapping)
            or set(result) != {"session_id", "state"}
            or result["session_id"] != request["session_id"]
            or result["state"] not in {"staged", "active", "closed"}
        ):
            raise ControlServerError("RESPONSE_INVALID")
        return 200, result

    def _read_request(self, handler: BaseHTTPRequestHandler) -> dict[str, Any]:
        if handler.headers.get("Transfer-Encoding") is not None:
            raise ControlServerError("SCHEMA_INVALID")
        lengths = handler.headers.get_all("Content-Length", [])
        if len(lengths) != 1:
            raise ControlServerError("SCHEMA_INVALID")
        try:
            length = int(lengths[0])
        except ValueError as error:
            raise ControlServerError("SCHEMA_INVALID") from error
        if length < 0:
            raise ControlServerError("SCHEMA_INVALID")
        header_bytes = self._header_bytes(handler)
        if length > self.max_request_bytes - header_bytes:
            raise ControlServerError("REQUEST_TOO_LARGE")
        if handler.headers.get_content_type() != "application/json":
            raise ControlServerError("SCHEMA_INVALID")
        body = handler.rfile.read(length)
        if len(body) != length:
            raise ControlServerError("SCHEMA_INVALID")
        try:
            value = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ControlServerError("SCHEMA_INVALID") from error
        if not isinstance(value, dict):
            raise ControlServerError("SCHEMA_INVALID")
        return value

    @staticmethod
    def _header_bytes(handler: BaseHTTPRequestHandler) -> int:
        return (
            len(handler.raw_requestline)
            + sum(
                len(name.encode("utf-8")) + len(value.encode("utf-8")) + 4
                for name, value in handler.headers.items()
            )
            + 2
        )

    def _forbidden_material(self) -> tuple[bytes, ...] | None:
        try:
            resolved = self.forbidden_material_resolver()
        except Exception:
            return None
        if not isinstance(resolved, (list, tuple)):
            return None
        materials: list[bytes] = []
        for value in resolved:
            if isinstance(value, str):
                material = value.encode("utf-8")
            elif isinstance(value, bytes):
                material = value
            else:
                return None
            if not material:
                return None
            materials.append(material)
        return tuple(materials)

    def _send(
        self,
        handler: BaseHTTPRequestHandler,
        status: int,
        value: Mapping[str, Any],
        *,
        validate: bool = True,
    ) -> None:
        if validate and not isinstance(value, Mapping):
            status, value, validate = 500, {"error": "RESPONSE_INVALID"}, False
        try:
            body = json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError):
            status, body, validate = 500, b'{"error":"RESPONSE_INVALID"}', False
        if validate:
            secret = getattr(handler, "_hindsight_control_secret", None)
            forbidden_material = self._forbidden_material()
            decoded = json.loads(body)
            if (
                _contains_forbidden_key(decoded)
                or (isinstance(secret, bytes) and secret and secret in body)
                or forbidden_material is None
                or any(material in body for material in forbidden_material)
            ):
                status, body = 500, b'{"error":"RESPONSE_INVALID"}'
        if len(body) > self.max_response_bytes:
            status, body = 500, b'{"error":"RESPONSE_INVALID"}'
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Pragma", "no-cache")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.end_headers()
        if handler.command != "HEAD":
            handler.wfile.write(body)
