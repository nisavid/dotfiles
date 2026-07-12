"""Bounded, redacting HTTP implementation of the data-plane adapter contract."""

import json
import re
import socket
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .adapters import AdapterError, AuthenticationError, RollbackBundle
from .canonical import digest
from .model import EndpointIdentity, Inventory
from .planning import inventory_endpoint


class HttpAdapter:
    ROLLBACK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
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

    def __init__(self, *, inventory: Inventory, profile_id: str, token_resolver: Callable[[], str],
                 timeout: float = 5.0, max_json_bytes: int = 1_048_576) -> None:
        if not isinstance(inventory, Inventory):
            raise AdapterError("validated inventory is required")
        raw = inventory.to_dict()
        artifact = {key: raw[key] for key in ("schema_version", "archetype", "profiles", "providers", "banks", "harnesses", "policy")}
        if digest(raw) != inventory.inventory_digest or digest(artifact) != inventory.artifact_digest:
            raise AdapterError("validated inventory digests do not match")
        self.endpoint = inventory_endpoint(inventory, profile_id)
        self._inventory = inventory
        self._token_resolver = token_resolver
        self.timeout = min(max(float(timeout), 0.1), 30.0)
        self.max_json_bytes = min(max(int(max_json_bytes), 1), 8_388_608)
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
        if self.endpoint.scheme not in {"http", "https"}:
            raise AdapterError("endpoint scheme is not permitted")
        if self.endpoint.scheme == "http" and not loopback:
            raise AdapterError("plain HTTP is restricted to loopback endpoints")
        approved = self._inventory.policy.get("approved_tls_endpoints", [])
        if self.endpoint.scheme == "https" and not loopback and self.endpoint.to_dict() not in approved:
            raise AdapterError("TLS endpoint is not approved by inventory")

    def _encode(self, payload: Mapping[str, Any]) -> bytes:
        chunks: list[bytes] = []
        size = 0
        encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        try:
            for chunk in encoder.iterencode(payload):
                remaining = self.max_json_bytes - size
                if len(chunk) > remaining:
                    raise AdapterError("JSON request exceeds configured size limit")
                encoded = chunk.encode("utf-8")
                if len(encoded) > remaining:
                    raise AdapterError("JSON request exceeds configured size limit")
                chunks.append(encoded)
                size += len(encoded)
        except (TypeError, ValueError, UnicodeEncodeError):
            raise AdapterError("JSON request is invalid") from None
        return b"".join(chunks)

    def _request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        try:
            token = self._token_resolver()
        except Exception:
            raise AuthenticationError("bearer token resolution failed") from None
        if not isinstance(token, str) or not token:
            raise AuthenticationError("bearer token resolver returned no token")
        body = None if payload is None else self._encode(payload)
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
                if content_length:
                    try:
                        declared_length = int(content_length)
                    except ValueError:
                        raise AdapterError("endpoint returned invalid Content-Length") from None
                    if declared_length < 0 or declared_length > self.max_json_bytes:
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
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AdapterError("endpoint returned invalid JSON") from None
        if not isinstance(value, dict):
            raise AdapterError("endpoint returned non-object JSON")
        return value

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
            "import_bank": ("POST", "/v1/migrations/import"),
            "migrate_bank": ("POST", "/v1/migrations/apply"),
            "replace_canonical_bank": ("POST", "/v1/migrations/replace"),
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

    def create_rollback_bundle(self, plan_digest: str, action_ids: tuple[str, ...]) -> RollbackBundle:
        value = self._request("POST", "/v1/rollbacks", {"plan_digest": plan_digest, "action_ids": list(action_ids)})
        if set(value) != set(RollbackBundle.__dataclass_fields__):
            raise AdapterError("rollback attestation schema is invalid")
        try:
            bundle = RollbackBundle(
                rollback_id=value["rollback_id"], plan_digest=value["plan_digest"],
                action_ids=tuple(value["action_ids"]), prestate_digest=value["prestate_digest"],
                endpoint_digest=value["endpoint_digest"], bundle_digest=value["bundle_digest"],
                restore_proof_digest=value["restore_proof_digest"],
            )
        except (KeyError, TypeError):
            raise AdapterError("rollback attestation schema is invalid") from None
        digests = (bundle.plan_digest, bundle.prestate_digest, bundle.endpoint_digest,
                   bundle.bundle_digest, bundle.restore_proof_digest)
        if (
            not isinstance(bundle.rollback_id, str) or self.ROLLBACK_ID.fullmatch(bundle.rollback_id) is None
            or bundle.plan_digest != plan_digest or bundle.action_ids != action_ids
            or not all(isinstance(item, str) and len(item) == 64 and all(char in "0123456789abcdef" for char in item) for item in digests)
        ):
            raise AdapterError("rollback attestation is not bound to the request")
        return bundle

    def _rollback_path(self, rollback: RollbackBundle, operation: str) -> str:
        if not isinstance(rollback, RollbackBundle) or self.ROLLBACK_ID.fullmatch(rollback.rollback_id) is None:
            raise AdapterError("rollback attestation ID is invalid")
        return f"/v1/rollbacks/{rollback.rollback_id}/{operation}"

    def verify_rollback_bundle(self, rollback: RollbackBundle) -> bool:
        value = self._request("POST", self._rollback_path(rollback, "verify"), rollback.to_dict())
        return value.get("verified") is True

    def restore(self, rollback: RollbackBundle):
        self._request("POST", self._rollback_path(rollback, "restore"), rollback.to_dict())

    def disable_activation(self):
        self._request("POST", "/v1/activation/disable", {})
