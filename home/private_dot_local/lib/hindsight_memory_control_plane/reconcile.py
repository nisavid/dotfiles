"""Digest-bound reconciliation with fresh-state checks and automatic rollback."""

from dataclasses import dataclass
import hmac
import re
from typing import Any, Mapping

from .adapters import Adapter, AdapterError
from .canonical import digest
from .model import Plan
from .planning import PlanError, verify_plan


BUNDLE_KEYS = {"schema_version", "plan_digest", "action_ids", "state", "data_bearing", "disposable_restore_verified", "bundle_digest"}


class ApplyError(ValueError):
    pass


@dataclass(frozen=True)
class ApplyResult:
    status: str
    reason: str
    applied_action_ids: tuple[str, ...] = ()
    rollback_attempted: bool = False
    rollback_succeeded: bool = False
    activation_enabled: bool = True
    ledger: tuple[Mapping[str, str], ...] = ()


def _bundle_body(bundle: Mapping[str, Any]) -> dict[str, Any]:
    return {key: bundle[key] for key in BUNDLE_KEYS - {"bundle_digest"}}


def create_rollback_bundle(plan: Plan, adapter: Adapter) -> dict[str, Any]:
    """Capture the action-specific pre-apply state and bind it to the plan."""
    verify_plan(plan)
    snapshot = adapter.snapshot()
    state = snapshot.get("state")
    if not isinstance(state, Mapping):
        raise ApplyError("adapter snapshot state must be an object")
    data_bearing = any(key in state for key in ("documents", "memories", "invalidated_memories"))
    body = {
        "schema_version": 1,
        "plan_digest": plan.plan_digest,
        "action_ids": [action.id for action in plan.actions],
        "state": dict(state),
        "data_bearing": data_bearing,
        "disposable_restore_verified": bool(getattr(adapter, "disposable_restore_verified", False)) if data_bearing else True,
    }
    return {**body, "bundle_digest": digest(body)}


def parse_migration_gate(gate: Mapping[str, Any]) -> tuple[str, str]:
    """Require export and import halves to bind the same run and artifact."""
    if not isinstance(gate, Mapping) or set(gate) != {"export", "import"}:
        raise ApplyError("migration gate requires export and import halves")
    halves = []
    for name in ("export", "import"):
        half = gate[name]
        if not isinstance(half, Mapping) or set(half) != {"run_id", "artifact_digest"}:
            raise ApplyError(f"migration gate {name} half is closed")
        if not isinstance(half["run_id"], str) or not half["run_id"]:
            raise ApplyError("migration gate run ID is required")
        if not isinstance(half["artifact_digest"], str) or re.fullmatch(r"[0-9a-f]{64}", half["artifact_digest"]) is None:
            raise ApplyError("migration gate artifact digest is required")
        halves.append((half["run_id"], half["artifact_digest"]))
    if halves[0] != halves[1]:
        raise ApplyError("migration gate halves do not match")
    return halves[0]


def _result(reason: str) -> ApplyResult:
    return ApplyResult("refused", reason)


def _validate_bundle(plan: Plan, value: Any) -> str | None:
    if not isinstance(value, Mapping) or set(value) != BUNDLE_KEYS:
        return "rollback_bundle_required"
    if value.get("schema_version") != 1 or value.get("plan_digest") != plan.plan_digest:
        return "rollback_bundle_mismatch"
    if value.get("action_ids") != [action.id for action in plan.actions]:
        return "rollback_bundle_action_mismatch"
    if not hmac.compare_digest(str(value.get("bundle_digest", "")), digest(_bundle_body(value))):
        return "rollback_bundle_digest_mismatch"
    if value.get("data_bearing") is True and value.get("disposable_restore_verified") is not True:
        return "disposable_restore_proof_required"
    return None


def apply_plan(plan: Plan, adapter: Adapter, approval_digest: str, gate: Mapping[str, Any] | None) -> ApplyResult:
    """Apply an immutable ordinary plan only after all live safety checks pass."""
    migration_kinds = {"import_bank", "migrate_bank", "replace_canonical_bank"}
    requested_migration = any(getattr(action, "kind", None) in migration_kinds for action in getattr(plan, "actions", ()))
    if requested_migration:
        if not isinstance(gate, Mapping) or "migration_gate" not in gate:
            return _result("migration_gate_required")
        try:
            run_id, artifact_digest = parse_migration_gate(gate["migration_gate"])
        except ApplyError:
            return _result("migration_gate_mismatch")
        if artifact_digest != getattr(plan, "artifact_digest", None) or run_id != gate.get("migration_run_id"):
            return _result("migration_gate_mismatch")
    try:
        verify_plan(plan)
    except (PlanError, TypeError, AttributeError):
        return _result("invalid_or_destructive_plan")
    if not isinstance(approval_digest, str) or not hmac.compare_digest(approval_digest, plan.plan_digest):
        return _result("approval_digest_mismatch")
    if not isinstance(gate, Mapping):
        return _result("rollback_bundle_required")
    bundle = gate.get("rollback_bundle")
    bundle_error = _validate_bundle(plan, bundle)
    if bundle_error:
        return _result(bundle_error)
    try:
        fresh = adapter.snapshot()
    except AdapterError:
        return _result("fresh_state_unavailable")
    if fresh.get("endpoint") != plan.target_endpoint.to_dict():
        return _result("endpoint_identity_drift")
    if digest(fresh.get("state")) != plan.live_state_digest:
        return _result("live_state_drift")
    operations = fresh.get("operations")
    if not isinstance(operations, Mapping) or operations.get("idle") is not True or operations.get("active") != []:
        return _result("operations_not_idle")

    ledger: list[Mapping[str, str]] = []
    applied: list[str] = []
    try:
        for action in plan.actions:
            adapter.apply_action(action)  # type: ignore[attr-defined]
            applied.append(action.id)
            ledger.append({"action_id": action.id, "status": "applied"})
            if adapter.verify_postcondition(action) is not True:  # type: ignore[attr-defined]
                raise ApplyError("postcondition_failed")
            ledger.append({"action_id": action.id, "status": "verified"})
    except (AdapterError, ApplyError, RuntimeError):
        ledger.append({"status": "rollback_started"})
        try:
            adapter.restore(bundle)
            ledger.append({"status": "rollback_succeeded"})
            return ApplyResult("rolled_back", "apply_or_postcondition_failed", tuple(applied), True, True, True, tuple(ledger))
        except (AdapterError, RuntimeError):
            try:
                adapter.disable_activation()  # type: ignore[attr-defined]
            except (AdapterError, RuntimeError):
                pass
            ledger.append({"status": "operator_blocked"})
            return ApplyResult("operator_blocked", "rollback_failed", tuple(applied), True, False, False, tuple(ledger))
    return ApplyResult("applied", "ok", tuple(applied), False, False, True, tuple(ledger))
