"""Explicit data-plane adapter contract and deterministic in-memory test adapter."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from .action_contracts import ACTION_METHODS, DIRECT_ACTION_KINDS
from .canonical import digest
from .model import BankRef, EndpointIdentity, deep_thaw


RUNTIME_SCHEMAS = {
    "recall": ({"query"}, {"limit"}),
    "mental_model_fetch": ({"model_id"}, set()),
    "session_status": ({"session_id"}, set()),
    "transcript_checkpoint": ({"document_id", "epoch", "checkpoint", "idempotency_key"}, set()),
    "retain_outcome": ({"document_id", "epoch", "checkpoint", "outcome", "idempotency_key"}, set()),
    "reflect": ({"reflection", "idempotency_key"}, set()),
}


def validate_runtime_request(method: str, request: Mapping[str, Any]) -> dict[str, Any]:
    if method not in RUNTIME_SCHEMAS or not isinstance(request, Mapping):
        raise AdapterError("runtime request schema is invalid")
    required, optional = RUNTIME_SCHEMAS[method]
    if not required <= set(request) or set(request) - required - optional:
        raise AdapterError("runtime request schema is invalid")
    value = deepcopy(dict(request))
    for key, item in value.items():
        if key in {"epoch", "checkpoint", "limit"}:
            if type(item) is not int or item < 0 or item > 1_000_000:
                raise AdapterError("runtime request schema is invalid")
        elif key == "idempotency_key":
            if not isinstance(item, str) or len(item) != 64 or any(char not in "0123456789abcdef" for char in item):
                raise AdapterError("runtime request schema is invalid")
        elif not isinstance(item, str) or not item or len(item.encode("utf-8")) > 65_536:
            raise AdapterError("runtime request schema is invalid")
    return value


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
    # Opaque monotonic revision that changes on every committed live-bank mutation.
    def read_migration_generation(self) -> str: ...
    def read_migration_inventory(self, source_bank: BankRef, candidate_bank: BankRef) -> Mapping[str, Any]: ...
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
    def recall(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def mental_model_fetch(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def transcript_checkpoint(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def retain_outcome(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def reflect(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def session_status(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


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
        self._runtime_results: dict[str, tuple[str, Mapping[str, Any]]] = {}
        self._migration_generation_seed = self.state.get("migration_generation")
        self._migration_generation_index = 0

    def _record(self, method: str, metadata: Mapping[str, Any] | None = None) -> None:
        self.calls.append({"method": method, "metadata": dict(metadata or {})})

    def _advance_migration_generation(self) -> None:
        if not isinstance(self._migration_generation_seed, str):
            return
        self._migration_generation_index += 1
        self.state["migration_generation"] = (
            f"{self._migration_generation_seed}:{self._migration_generation_index}"
        )

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

    def read_migration_generation(self) -> str:
        self._record("read_migration_generation")
        value = self.state.get("migration_generation")
        if not isinstance(value, str) or not value:
            raise AdapterError("migration generation is unavailable")
        return value

    def read_migration_inventory(self, source_bank: BankRef, candidate_bank: BankRef) -> Mapping[str, Any]:
        if not isinstance(source_bank, BankRef) or not isinstance(candidate_bank, BankRef):
            raise AdapterError("migration inventory requires explicit bank references")
        if "migration_inventory" not in self.state:
            raise AdapterError("migration inventory is unavailable")
        self._record(
            "read_migration_inventory",
            {"source_bank": source_bank.to_dict(), "candidate_bank": candidate_bank.to_dict()},
        )
        return deepcopy(self.state["migration_inventory"])

    def template_dry_run(self, template):
        self._record("template_dry_run", self._keys(template))
        return {"valid": True, "digest": digest(template)}

    def export_template(self):
        self._record("export_template")
        return deepcopy(self.state.get("template", {}))

    def import_template(self, template):
        self._record("import_template", self._keys(template))
        self.state["template"] = deep_thaw(template)
        self._advance_migration_generation()
        return {"imported": True}

    def patch_config(self, patch):
        self._record("patch_config", self._keys(patch))
        self.state.setdefault("config", {}).update(deep_thaw(patch))
        self._advance_migration_generation()
        return deepcopy(self.state["config"])

    def _upsert(self, collection: str, value: Mapping[str, Any]):
        self._record(f"upsert_{collection[:-1]}", self._keys(value))
        identifier = value.get("id", value.get(f"{collection[:-1]}_id"))
        stored = self.state.setdefault(collection, {collection: []})
        items = stored.setdefault(collection, []) if isinstance(stored, dict) else stored
        items[:] = [item for item in items if item.get("id", item.get(f"{collection[:-1]}_id")) != identifier]
        items.append(deep_thaw(value))
        self._advance_migration_generation()
        return {"upserted": identifier}

    def upsert_model(self, model): return self._upsert("models", model)
    def upsert_directive(self, directive): return self._upsert("directives", directive)

    def transfer_documents(self, transfer):
        self._record("transfer_documents", self._keys(transfer))
        self._advance_migration_generation()
        return {"transferred": transfer.get("count", 0)}

    def read_invalidated_memories(self): return self._read("invalidated_memories", [])

    # The migration inventory contract names this read by its domain surface.
    def invalidated_memory_inventory(self): return self.read_invalidated_memories()

    def reapply_invalidated_memories(self, request):
        self._record("reapply_invalidated_memories", self._keys(request))
        self._advance_migration_generation()
        return {"reapplied": request.get("count", 0)}

    def delete_bank(self, bank):
        self._record("delete_bank", self._keys(bank))
        self._advance_migration_generation()
        return {"deleted": True}

    def apply_action(self, action) -> None:
        details = dict(action.details)
        method_name = ACTION_METHODS.get(action.kind)
        if method_name is not None:
            getattr(self, method_name)(details)
        elif action.kind in DIRECT_ACTION_KINDS:
            self._record(action.kind, self._keys(details))
            self._advance_migration_generation()
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
        self._advance_migration_generation()

    def disable_activation(self) -> None:
        self._record("disable_activation")
        if self.fail_disable_activation:
            raise AdapterError("activation disable failed")
        self.activation_enabled = False

    def recall(self, request):
        request = validate_runtime_request("recall", request)
        self._record("recall", self._keys(request))
        return deepcopy(self.state.get("recall", {"memories": [{"id": "m1"}]}))

    def mental_model_fetch(self, request):
        request = validate_runtime_request("mental_model_fetch", request)
        self._record("mental_model_fetch", self._keys(request))
        return deepcopy(self.state.get("mental_model_fetch", {"models": [{"id": "model1"}]}))

    def session_status(self, request):
        request = validate_runtime_request("session_status", request)
        self._record("session_status", self._keys(request))
        return deepcopy(self.state.get("session_status", {"status": "ready"}))

    def _runtime_write(self, method: str, request: Mapping[str, Any], result: Mapping[str, Any]):
        request = validate_runtime_request(method, request)
        key = request["idempotency_key"]
        request_digest = digest(request)
        if key in self._runtime_results:
            stored_digest, stored_result = self._runtime_results[key]
            if stored_digest != request_digest:
                raise AdapterError("runtime idempotency digest drift")
            return deepcopy(stored_result)
        self._record(method, self._keys(request))
        self._runtime_results[key] = (request_digest, deepcopy(result))
        self._advance_migration_generation()
        return deepcopy(result)

    def transcript_checkpoint(self, request):
        return self._runtime_write("transcript_checkpoint", request, {"applied": True})

    def retain_outcome(self, request):
        return self._runtime_write("retain_outcome", request, {"retained": True})

    def reflect(self, request):
        return self._runtime_write("reflect", request, {"accepted": True})
