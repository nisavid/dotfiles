"""Bounded, redacting HTTP implementation of the data-plane adapter contract."""

import json
import socket
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .adapters import AdapterError, AuthenticationError
from .model import EndpointIdentity


class HttpAdapter:
    READ_PATHS = {
        "schema_version": "/v1/schema",
        "read_config": "/v1/config",
        "read_stats": "/v1/stats",
        "read_tags": "/v1/tags",
        "read_scopes": "/v1/scopes",
        "read_documents": "/v1/documents",
        "read_models": "/v1/models",
        "read_directives": "/v1/directives",
        "read_operations": "/v1/operations",
        "read_invalidated_memories": "/v1/memories/invalidated",
    }
    MUTATION_PATHS = {
        "template_dry_run": ("POST", "/v1/templates/dry-run"),
        "import_template": ("POST", "/v1/templates/import"),
        "patch_config": ("PATCH", "/v1/config"),
        "upsert_model": ("PUT", "/v1/models"),
        "upsert_directive": ("PUT", "/v1/directives"),
        "transfer_documents": ("POST", "/v1/documents/transfer"),
        "reapply_invalidated_memories": ("POST", "/v1/memories/invalidated/reapply"),
        "delete_bank": ("DELETE", "/v1/banks"),
    }

    def __init__(self, *, endpoint: Mapping[str, Any], token_resolver: Callable[[], str], timeout: float = 5.0,
                 max_json_bytes: int = 1_048_576,
                 inventory_approved_tls_endpoints: set[tuple[str, int, str, str]] | None = None) -> None:
        self.endpoint = EndpointIdentity(**dict(endpoint))
        self._token_resolver = token_resolver
        self.timeout = min(max(float(timeout), 0.1), 30.0)
        self.max_json_bytes = min(max(int(max_json_bytes), 1), 8_388_608)
        self._approved_tls_endpoints = frozenset(inventory_approved_tls_endpoints or ())
        self.recordings: list[dict[str, Any]] = []
        self._validate_endpoint()

    def __repr__(self) -> str:
        return f"HttpAdapter(endpoint={self.endpoint!r}, timeout={self.timeout!r}, max_json_bytes={self.max_json_bytes!r})"

    def _validate_endpoint(self) -> None:
        host = self.endpoint.host.strip("[]").lower()
        loopback = host == "localhost"
        try:
            loopback = loopback or __import__("ipaddress").ip_address(host).is_loopback
        except ValueError:
            pass
        if self.endpoint.scheme == "http" and not loopback:
            raise AdapterError("plain HTTP is restricted to loopback endpoints")
        approved_identity = (host, self.endpoint.port, self.endpoint.profile_id, self.endpoint.tenant)
        if self.endpoint.scheme == "https" and not loopback and approved_identity not in self._approved_tls_endpoints:
            raise AdapterError("TLS endpoint is not approved by inventory")

    def _request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        try:
            token = self._token_resolver()
        except Exception:
            raise AuthenticationError("bearer token resolution failed") from None
        if not isinstance(token, str) or not token:
            raise AuthenticationError("bearer token resolver returned no token")
        body = None if payload is None else json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        if body is not None and len(body) > self.max_json_bytes:
            raise AdapterError("JSON request exceeds configured size limit")
        url = f"{self.endpoint.scheme}://{self.endpoint.host}:{self.endpoint.port}{path}"
        request = Request(url, data=body, method=method, headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            **({"Content-Type": "application/json"} if body is not None else {}),
        })
        self.recordings.append({"method": method, "path": path, "payload_keys": sorted(payload) if payload else []})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > self.max_json_bytes:
                    raise AdapterError("JSON response exceeds configured size limit")
                raw = response.read(self.max_json_bytes + 1)
                if len(raw) > self.max_json_bytes:
                    raise AdapterError("JSON response exceeds configured size limit")
        except HTTPError as error:
            if error.code == 401:
                raise AuthenticationError("endpoint authentication failed (HTTP 401)") from None
            raise AdapterError(f"endpoint request failed (HTTP {error.code})") from None
        except (URLError, socket.timeout, TimeoutError, OSError):
            raise AdapterError("endpoint request failed") from None
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AdapterError("endpoint returned invalid JSON") from None

    def schema_version(self) -> int:
        value = self._request("GET", self.READ_PATHS["schema_version"])
        version = value.get("schema_version", value.get("version")) if isinstance(value, dict) else value
        if type(version) is not int:
            raise AdapterError("endpoint schema version is invalid")
        return version

    def endpoint_identity(self) -> EndpointIdentity:
        value = self._request("GET", "/v1/identity")
        try:
            return EndpointIdentity(**value)
        except (TypeError, KeyError):
            raise AdapterError("endpoint identity is invalid") from None

    def snapshot(self) -> Mapping[str, Any]:
        return {"endpoint": self.endpoint_identity().to_dict(), "state": self._request("GET", "/v1/state"), "operations": self.read_operations()}

    def _read(self, name: str): return self._request("GET", self.READ_PATHS[name])
    def read_config(self): return self._read("read_config")
    def read_stats(self): return self._read("read_stats")
    def read_tags(self): return self._read("read_tags")
    def read_scopes(self): return self._read("read_scopes")
    def read_documents(self): return self._read("read_documents")
    def read_models(self): return self._read("read_models")
    def read_directives(self): return self._read("read_directives")
    def read_operations(self): return self._read("read_operations")
    def read_invalidated_memories(self): return self._read("read_invalidated_memories")
    def invalidated_memory_inventory(self): return self.read_invalidated_memories()
    def export_template(self): return self._request("GET", "/v1/templates/export")

    def _mutate(self, name: str, value: Mapping[str, Any]):
        method, path = self.MUTATION_PATHS[name]
        return self._request(method, path, value)

    def template_dry_run(self, value): return self._mutate("template_dry_run", value)
    def import_template(self, value): return self._mutate("import_template", value)
    def patch_config(self, value): return self._mutate("patch_config", value)
    def upsert_model(self, value): return self._mutate("upsert_model", value)
    def upsert_directive(self, value): return self._mutate("upsert_directive", value)
    def transfer_documents(self, value): return self._mutate("transfer_documents", value)
    def reapply_invalidated_memories(self, value): return self._mutate("reapply_invalidated_memories", value)
    def delete_bank(self, value): return self._mutate("delete_bank", value)

    def apply_action(self, action) -> None:
        mapping = {
            "configure_bank": self.patch_config, "configure_profile": self.patch_config,
            "set_auto_consolidation": self.patch_config, "set_memory_defense": self.patch_config,
            "install_model": self.upsert_model, "activate_model": self.upsert_model,
            "upsert_model": self.upsert_model, "upsert_directive": self.upsert_directive,
        }
        direct = {
            "create_bank": ("POST", "/v1/banks"),
            "reload_profile": ("POST", "/v1/profiles/reload"),
            "report_unmanaged": ("POST", "/v1/unmanaged/report"),
        }
        try:
            if action.kind in direct:
                method, path = direct[action.kind]
                self._request(method, path, dict(action.details))
            else:
                mapping[action.kind](dict(action.details))
        except KeyError:
            raise AdapterError(f"unsupported apply action: {action.kind}") from None

    def verify_postcondition(self, action) -> bool:
        result = self._request("POST", "/v1/postconditions/verify", {"action_id": action.id})
        return result.get("verified") is True

    def restore(self, rollback):
        self._request("POST", "/v1/restore", {"bundle_digest": rollback["bundle_digest"]})

    def disable_activation(self):
        self._request("POST", "/v1/activation/disable", {})
