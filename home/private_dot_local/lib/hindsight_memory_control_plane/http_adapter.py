"""Bounded, redacting HTTP implementation of the data-plane adapter contract."""

import json
import hashlib
import re
import socket
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .adapters import AdapterError, AuthenticationError, RollbackBundle, validate_runtime_request
from .canonical import digest
from .model import BankRef, EndpointIdentity, Inventory
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
    PAGE_LIMIT = 1000
    SECRET_KEY_PARTS = frozenset(
        {"access", "authorization", "bearer", "credential", "key", "password", "secret", "token"}
    )

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
        self._runtime_results: dict[str, tuple[str, Mapping[str, Any]]] = {}
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
            try:
                if error.code == 401:
                    raise AuthenticationError("endpoint authentication failed (HTTP 401)") from None
                raise AdapterError(f"endpoint request failed (HTTP {error.code})") from None
            finally:
                error.close()
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

    def read_migration_inventory(self, source_bank: BankRef, candidate_bank: BankRef):
        if not isinstance(source_bank, BankRef) or not isinstance(candidate_bank, BankRef):
            raise AdapterError("migration inventory requires explicit bank references")
        if source_bank.profile_id != self.endpoint.profile_id or candidate_bank.profile_id != self.endpoint.profile_id:
            raise AdapterError("migration banks must use the selected profile")
        version = self._request("GET", "/version")
        banks: dict[str, Any] = {}
        hooks: list[dict[str, Any]] = []
        schedules: list[dict[str, Any]] = []
        active_operations: list[dict[str, Any]] = []
        for role, bank in (("source", source_bank), ("candidate", candidate_bank)):
            bank_snapshot, bank_hooks, bank_schedules, bank_operations = self._read_migration_bank(role, bank)
            banks[role] = bank_snapshot
            hooks.extend(bank_hooks)
            schedules.extend(bank_schedules)
            active_operations.extend(bank_operations)
        active_operations.sort(key=lambda item: (item["bank_role"], item["operation_id"]))
        return {
            "schema_version": 1,
            "endpoint": self.endpoint.to_dict(),
            "provider_identity": self._declared_provider_identity(),
            "versions": {
                "adapter": 1,
                "hindsight": version.get("api_version"),
                "features": version.get("features"),
            },
            "banks": banks,
            "operations": {"idle": not active_operations, "active": active_operations},
            "hooks": sorted(hooks, key=lambda item: (item["bank_role"], item["hook_id"])),
            "schedules": sorted(schedules, key=lambda item: (item["bank_role"], item["model_id"])),
        }

    @classmethod
    def _secret_config_key(cls, key: Any) -> bool:
        parts = set(filter(None, re.split(r"[^a-z0-9]+", str(key).lower())))
        return bool(parts & cls.SECRET_KEY_PARTS)

    @classmethod
    def _safe_config_value(cls, value: Any, path: str, redacted: list[str]) -> Any:
        if isinstance(value, Mapping):
            safe: dict[str, Any] = {}
            for key, item in value.items():
                name = str(key)
                child_path = f"{path}.{name}" if path else name
                if cls._secret_config_key(name):
                    redacted.append(child_path)
                else:
                    safe[name] = cls._safe_config_value(item, child_path, redacted)
            return safe
        if isinstance(value, list):
            return [cls._safe_config_value(item, f"{path}[{index}]", redacted) for index, item in enumerate(value)]
        return value

    @classmethod
    def _safe_config(cls, value: Any) -> Mapping[str, Any]:
        if not isinstance(value, Mapping) or set(value) != {"bank_id", "config", "overrides"}:
            raise AdapterError("bank configuration response is invalid")
        result: dict[str, Any] = {"bank_id": value["bank_id"]}
        redacted: list[str] = []
        for section in ("config", "overrides"):
            raw = value[section]
            if not isinstance(raw, Mapping):
                raise AdapterError("bank configuration response is invalid")
            result[section] = cls._safe_config_value(raw, section, redacted)
        result["redacted_keys"] = sorted(redacted)
        return result

    def _declared_provider_identity(self) -> Mapping[str, Any]:
        profiles = [profile for profile in self._inventory.profiles if profile.get("id") == self.endpoint.profile_id]
        if len(profiles) != 1:
            raise AdapterError("selected profile identity is unavailable")
        roles = profiles[0].get("roles", profiles[0].get("provider_roles", {}))
        if not isinstance(roles, Mapping):
            raise AdapterError("selected profile provider roles are invalid")
        providers = {provider.get("id"): provider for provider in self._inventory.providers}
        result: dict[str, Any] = {}
        for role, selected in sorted(roles.items()):
            identifiers = selected if isinstance(selected, (list, tuple)) else [selected]
            if not identifiers or any(identifier not in providers for identifier in identifiers):
                raise AdapterError("selected provider identity is unavailable")
            result[str(role)] = [
                {"provider_id": identifier, "provider_record_digest": digest(providers[identifier])}
                for identifier in identifiers
            ]
        return {
            "inventory_digest": self._inventory.inventory_digest,
            "profile_id": self.endpoint.profile_id,
            "roles": result,
        }

    @staticmethod
    def _bank_path(bank: BankRef, suffix: str = "") -> str:
        return f"/v1/default/banks/{quote(bank.bank_id, safe='')}{suffix}"

    def _read_items(
        self,
        path: str,
        *,
        collection: str = "items",
        total_required: bool = True,
        limit: int | None = None,
    ) -> list[Any]:
        page_limit = self.PAGE_LIMIT if limit is None else limit
        items: list[Any] = []
        offset = 0
        while True:
            separator = "&" if "?" in path else "?"
            page_path = f"{path}{separator}{urlencode({'limit': page_limit, 'offset': offset})}"
            page = self._request("GET", page_path)
            page_items = page.get(collection)
            if not isinstance(page_items, list):
                raise AdapterError("paginated discovery response is invalid")
            if page.get("offset", offset) != offset:
                raise AdapterError("paginated discovery response offset drifted")
            items.extend(page_items)
            if total_required:
                total = page.get("total")
                if type(total) is not int or total < 0 or len(items) > total:
                    raise AdapterError("paginated discovery response total is invalid")
                if len(items) == total:
                    return items
                if not page_items:
                    raise AdapterError("paginated discovery response is incomplete")
            elif len(page_items) < page_limit:
                return items
            offset = len(items)

    @staticmethod
    def _migration_document(item: Any) -> Mapping[str, Any]:
        if not isinstance(item, Mapping):
            raise AdapterError("migration document response is invalid")
        identifier = item.get("id")
        updated_at = item.get("updated_at")
        content_hash = item.get("content_hash")
        if not isinstance(identifier, str) or not isinstance(updated_at, str) or not isinstance(content_hash, str):
            raise AdapterError("migration document response is incomplete")
        return {
            "document_id": identifier,
            "updated_at": updated_at,
            "content_digest": content_hash,
            "created_at": item.get("created_at"),
            "text_length": item.get("text_length"),
            "memory_unit_count": item.get("memory_unit_count"),
            "tags": item.get("tags"),
            "document_metadata": item.get("document_metadata"),
            "retain_params": item.get("retain_params"),
        }

    @staticmethod
    def _migration_invalidation(item: Any) -> Mapping[str, Any]:
        if not isinstance(item, Mapping):
            raise AdapterError("invalidated memory response is invalid")
        identifier = item.get("id")
        document_id = item.get("document_id")
        content = item.get("text")
        reason = item.get("invalidation_reason")
        if not all(isinstance(value, str) and value for value in (identifier, document_id, content)):
            raise AdapterError("invalidated memory response is incomplete")
        if reason is None:
            reason = ""
        if not isinstance(reason, str):
            raise AdapterError("invalidated memory response is invalid")
        return {
            "item_id": identifier,
            "source_document_id": document_id,
            "reason_digest": hashlib.sha256(reason.encode("utf-8")).hexdigest(),
            "content_digest": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }

    def _read_migration_bank(self, role: str, bank: BankRef):
        base = self._bank_path(bank)
        config = self._safe_config(self._request("GET", f"{base}/config"))
        stats = self._request("GET", f"{base}/stats")
        scopes_response = self._request("GET", f"{base}/observations/scopes")
        tags = self._read_items(f"{base}/tags")
        documents = [self._migration_document(item) for item in self._read_items(f"{base}/documents")]
        models = self._read_items(f"{base}/mental-models?detail=full", total_required=False)
        directives = self._read_items(
            f"{base}/directives?active_only=false",
            total_required=False,
        )
        webhooks_response = self._request("GET", f"{base}/webhooks")
        invalidations = [
            self._migration_invalidation(item)
            for item in self._read_items(f"{base}/memories/list?state=invalidated")
        ]
        active: list[dict[str, Any]] = []
        for status in ("pending", "processing"):
            for operation in self._read_items(
                f"{base}/operations?{urlencode({'status': status})}",
                collection="operations",
                limit=100,
            ):
                if not isinstance(operation, Mapping) or not isinstance(operation.get("id"), str):
                    raise AdapterError("migration operation response is invalid")
                active.append(
                    {
                        "bank_role": role,
                        "operation_id": operation["id"],
                        "status": operation.get("status"),
                        "task_type": operation.get("task_type"),
                        "updated_at": operation.get("updated_at"),
                    }
                )
        if not isinstance(scopes_response.get("scopes"), list):
            raise AdapterError("observation scope response is invalid")
        if not isinstance(webhooks_response.get("items"), list):
            raise AdapterError("webhook response is invalid")
        hooks = []
        for item in webhooks_response["items"]:
            if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
                raise AdapterError("webhook response is invalid")
            hooks.append({"bank_role": role, "hook_id": item["id"], **dict(item)})
        schedules = []
        for item in models:
            if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
                raise AdapterError("mental model response is invalid")
            trigger = item.get("trigger")
            if trigger is not None:
                if not isinstance(trigger, Mapping):
                    raise AdapterError("mental model trigger is invalid")
                schedules.append({"bank_role": role, "model_id": item["id"], "trigger": dict(trigger)})
        return (
            {
                "bank_ref": bank.to_dict(),
                "config": config,
                "stats": stats,
                "scopes": scopes_response["scopes"],
                "tags": tags,
                "documents": documents,
                "models": models,
                "directives": directives,
                "invalidated_memories": invalidations,
            },
            hooks,
            schedules,
            active,
        )

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

    def recall(self, request): return self._request("POST", "/v1/runtime/recall", validate_runtime_request("recall", request))
    def mental_model_fetch(self, request): return self._request("POST", "/v1/runtime/mental-model", validate_runtime_request("mental_model_fetch", request))
    def session_status(self, request): return self._request("POST", "/v1/runtime/session-status", validate_runtime_request("session_status", request))

    def _runtime_write(self, path: str, request: Mapping[str, Any]):
        method = {
            "/v1/runtime/transcript-checkpoint": "transcript_checkpoint",
            "/v1/runtime/outcome": "retain_outcome",
            "/v1/runtime/reflection": "reflect",
        }[path]
        request = validate_runtime_request(method, request)
        key = request["idempotency_key"]
        request_digest = digest(request)
        if key in self._runtime_results:
            stored_digest, result = self._runtime_results[key]
            if stored_digest != request_digest:
                raise AdapterError("runtime idempotency digest drift")
            return result
        result = self._request("PUT", path, request)
        self._runtime_results[key] = (request_digest, result)
        return result

    def transcript_checkpoint(self, request): return self._runtime_write("/v1/runtime/transcript-checkpoint", request)
    def retain_outcome(self, request): return self._runtime_write("/v1/runtime/outcome", request)
    def reflect(self, request): return self._runtime_write("/v1/runtime/reflection", request)
