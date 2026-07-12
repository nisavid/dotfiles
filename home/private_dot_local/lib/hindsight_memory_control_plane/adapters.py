"""Explicit data-plane adapter contract and deterministic in-memory test adapter."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from .canonical import digest
from .model import EndpointIdentity, deep_thaw


class AdapterError(RuntimeError):
    """A redacted adapter failure safe to show to an operator."""


class AuthenticationError(AdapterError):
    """The endpoint rejected the resolved bearer token."""


@dataclass(frozen=True)
class RollbackBundle:
    """Opaque adapter-attested handle to an adapter-owned prestate snapshot."""

    rollback_id: str
    plan_digest: str
    action_ids: tuple[str, ...]
    prestate_digest: str
    endpoint_digest: str
    bundle_digest: str
    restore_proof_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rollback_id": self.rollback_id,
            "plan_digest": self.plan_digest,
            "action_ids": list(self.action_ids),
            "prestate_digest": self.prestate_digest,
            "endpoint_digest": self.endpoint_digest,
            "bundle_digest": self.bundle_digest,
            "restore_proof_digest": self.restore_proof_digest,
        }


@runtime_checkable
class Adapter(Protocol):
    def schema_version(self) -> int: ...
    def endpoint_identity(self) -> EndpointIdentity: ...
    def snapshot(self) -> Mapping[str, Any]: ...
    def read_config(self) -> Mapping[str, Any]: ...
    def read_stats(self) -> Mapping[str, Any]: ...
    def read_tags(self) -> Any: ...
    def read_scopes(self) -> Any: ...
    def read_documents(self) -> Any: ...
    def read_models(self) -> Any: ...
    def read_directives(self) -> Any: ...
    def read_operations(self) -> Mapping[str, Any]: ...
    def template_dry_run(self, template: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def export_template(self) -> Mapping[str, Any]: ...
    def import_template(self, template: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def patch_config(self, patch: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def upsert_model(self, model: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def upsert_directive(self, directive: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def transfer_documents(self, transfer: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def read_invalidated_memories(self) -> Any: ...
    def reapply_invalidated_memories(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def delete_bank(self, bank: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def apply_action(self, action: Any) -> None: ...
    def verify_postcondition(self, action: Any) -> bool: ...
    def create_rollback_bundle(self, plan_digest: str, action_ids: tuple[str, ...]) -> RollbackBundle: ...
    def verify_rollback_bundle(self, rollback: RollbackBundle) -> bool: ...
    def restore(self, rollback: RollbackBundle) -> None: ...
    def disable_activation(self) -> None: ...


class FakeAdapter:
    """Adapter fake that records only operation names and bounded structural metadata."""

    def __init__(self, *, schema: int = 1, endpoint: Mapping[str, Any], state: Mapping[str, Any] | None = None,
                 operations: Mapping[str, Any] | None = None, restore_proof_valid: bool = True) -> None:
        self.schema = schema
        self.endpoint = EndpointIdentity(**dict(endpoint))
        self.state = deepcopy(dict(state or {}))
        self.operations = deepcopy(dict(operations or {"idle": True, "active": []}))
        self.restore_proof_valid = restore_proof_valid
        self.calls: list[dict[str, Any]] = []
        self.fail_postcondition_for: str | None = None
        self.fail_restore = False
        self.fail_disable_activation = False
        self.activation_enabled = True
        self._rollbacks: dict[str, dict[str, Any]] = {}

    def _record(self, method: str, metadata: Mapping[str, Any] | None = None) -> None:
        self.calls.append({"method": method, "metadata": dict(metadata or {})})

    @staticmethod
    def _keys(value: Mapping[str, Any]) -> dict[str, Any]:
        return {"keys": sorted(str(key) for key in value)}

    def schema_version(self) -> int:
        self._record("schema_version")
        return self.schema

    def endpoint_identity(self) -> EndpointIdentity:
        self._record("endpoint_identity")
        return self.endpoint

    def snapshot(self) -> Mapping[str, Any]:
        self._record("snapshot")
        return {"endpoint": self.endpoint.to_dict(), "state": deepcopy(self.state), "operations": deepcopy(self.operations)}

    def _read(self, name: str, default: Any) -> Any:
        self._record(f"read_{name}")
        return deepcopy(self.state.get(name, default))

    def read_config(self): return self._read("config", {})
    def read_stats(self): return self._read("stats", {})
    def read_tags(self): return self._read("tags", [])
    def read_scopes(self): return self._read("scopes", [])
    def read_documents(self): return self._read("documents", [])
    def read_models(self): return self._read("models", [])
    def read_directives(self): return self._read("directives", [])

    def read_operations(self) -> Mapping[str, Any]:
        self._record("read_operations")
        return deepcopy(self.operations)

    def template_dry_run(self, template):
        self._record("template_dry_run", self._keys(template))
        return {"valid": True, "digest": digest(template)}

    def export_template(self):
        self._record("export_template")
        return deepcopy(self.state.get("template", {}))

    def import_template(self, template):
        self._record("import_template", self._keys(template))
        self.state["template"] = deep_thaw(template)
        return {"imported": True}

    def patch_config(self, patch):
        self._record("patch_config", self._keys(patch))
        self.state.setdefault("config", {}).update(deep_thaw(patch))
        return deepcopy(self.state["config"])

    def _upsert(self, collection: str, value: Mapping[str, Any]):
        self._record(f"upsert_{collection[:-1]}", self._keys(value))
        identifier = value.get("id", value.get(f"{collection[:-1]}_id"))
        stored = self.state.setdefault(collection, {collection: []})
        items = stored.setdefault(collection, []) if isinstance(stored, dict) else stored
        items[:] = [item for item in items if item.get("id", item.get(f"{collection[:-1]}_id")) != identifier]
        items.append(deep_thaw(value))
        return {"upserted": identifier}

    def upsert_model(self, model): return self._upsert("models", model)
    def upsert_directive(self, directive): return self._upsert("directives", directive)

    def transfer_documents(self, transfer):
        self._record("transfer_documents", self._keys(transfer))
        return {"transferred": transfer.get("count", 0)}

    def read_invalidated_memories(self): return self._read("invalidated_memories", [])

    # Friendly alias matching the brief's inventory vocabulary.
    def invalidated_memory_inventory(self): return self.read_invalidated_memories()

    def reapply_invalidated_memories(self, request):
        self._record("reapply_invalidated_memories", self._keys(request))
        return {"reapplied": request.get("count", 0)}

    def delete_bank(self, bank):
        self._record("delete_bank", self._keys(bank))
        return {"deleted": True}

    def apply_action(self, action) -> None:
        details = dict(action.details)
        methods = {
            "configure_bank": self.patch_config,
            "configure_profile": self.patch_config,
            "set_auto_consolidation": self.patch_config,
            "set_memory_defense": self.patch_config,
            "install_model": self.upsert_model,
            "activate_model": self.upsert_model,
            "upsert_model": self.upsert_model,
            "upsert_directive": self.upsert_directive,
        }
        if action.kind in methods:
            methods[action.kind](details)
        elif action.kind in {"create_bank", "reload_profile", "report_unmanaged", "import_bank", "migrate_bank", "replace_canonical_bank"}:
            self._record(action.kind, self._keys(details))
        else:
            raise AdapterError(f"unsupported apply action: {action.kind}")

    def verify_postcondition(self, action) -> bool:
        self._record("verify_postcondition", {"action_id": action.id})
        return self.fail_postcondition_for != action.id

    def create_rollback_bundle(self, plan_digest: str, action_ids: tuple[str, ...]) -> RollbackBundle:
        prestate = deepcopy(self.state)
        prestate_digest = digest(prestate)
        endpoint_digest = digest(self.endpoint.to_dict())
        rollback_id = f"rollback-{len(self._rollbacks) + 1}"
        body = {
            "rollback_id": rollback_id, "plan_digest": plan_digest, "action_ids": list(action_ids),
            "prestate_digest": prestate_digest, "endpoint_digest": endpoint_digest,
        }
        bundle_digest = digest(body)
        proof_digest = digest({"rollback_id": rollback_id, "bundle_digest": bundle_digest, "attested": "fake-adapter"})
        bundle = RollbackBundle(rollback_id, plan_digest, action_ids, prestate_digest, endpoint_digest, bundle_digest, proof_digest)
        data_bearing = any(key in prestate for key in ("documents", "memories", "invalidated_memories"))
        self._rollbacks[rollback_id] = {
            "bundle": bundle, "state": prestate,
            "verified": self.restore_proof_valid or not data_bearing,
        }
        self._record("create_rollback_bundle", {"action_count": len(action_ids)})
        return bundle

    def verify_rollback_bundle(self, rollback: RollbackBundle) -> bool:
        record = self._rollbacks.get(rollback.rollback_id)
        verified = bool(record and record["bundle"] == rollback and record["verified"])
        self._record("verify_rollback_bundle", {"rollback_id": rollback.rollback_id})
        return verified

    def restore(self, rollback: RollbackBundle):
        self._record("restore", {"rollback_id": rollback.rollback_id})
        if self.fail_restore:
            raise AdapterError("rollback failed")
        record = self._rollbacks.get(rollback.rollback_id)
        if not record or record["bundle"] != rollback:
            raise AdapterError("rollback attestation is unknown")
        self.state = deepcopy(record["state"])

    def disable_activation(self) -> None:
        self._record("disable_activation")
        if self.fail_disable_activation:
            raise AdapterError("activation disable failed")
        self.activation_enabled = False
