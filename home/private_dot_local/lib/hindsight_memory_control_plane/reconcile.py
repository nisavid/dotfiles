"""Digest-bound reconciliation with adapter-attested rollback and migration gates."""

from dataclasses import dataclass
import hmac
import re
from typing import Any, Mapping

from .adapters import Adapter, RollbackBundle
from .canonical import digest
from .model import Action, EndpointIdentity, OperationSnapshot, Plan, deep_freeze, deep_thaw
from .planning import PlanError, plan_from_dict, verify_plan


DIGEST = re.compile(r"[0-9a-f]{64}\Z")
SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
MUTATION_KINDS = {"import_bank", "migrate_bank", "replace_canonical_bank"}


class ApplyError(ValueError):
    pass


@dataclass(frozen=True)
class MutationPlan:
    """Closed destructive plan kept separate from Task 1 ordinary plans."""

    base_plan: Plan
    plan_kind: str
    migration_run_id: str
    actions: tuple[Action, ...]
    plan_digest: str

    @property
    def artifact_digest(self): return self.base_plan.artifact_digest
    @property
    def target_endpoint(self): return self.base_plan.target_endpoint
    @property
    def live_state_digest(self): return self.base_plan.live_state_digest

    def body(self) -> dict[str, Any]:
        return {
            "base_plan": self.base_plan.to_dict(), "plan_kind": self.plan_kind,
            "migration_run_id": self.migration_run_id,
            "actions": [action.to_dict() for action in self.actions], "destructive": True,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.body(), "plan_digest": self.plan_digest}


@dataclass(frozen=True)
class ApplyResult:
    status: str
    reason: str
    applied_action_ids: tuple[str, ...] = ()
    rollback_attempted: bool = False
    rollback_succeeded: bool = False
    activation_enabled: bool | None = True
    ledger: tuple[Mapping[str, str], ...] = ()


def _mutation_actions(values: Any) -> tuple[Action, ...]:
    if not isinstance(values, (list, tuple)) or not values:
        raise ApplyError("mutation actions must be a non-empty array")
    result = []
    seen = set()
    for value in values:
        if not isinstance(value, Mapping) or set(value) - {"id", "kind", "artifact_digest", "archive_digest", "source_bank", "target_bank"}:
            raise ApplyError("mutation action schema is closed")
        identifier, kind = value.get("id"), value.get("kind")
        if not isinstance(identifier, str) or SAFE_IDENTIFIER.fullmatch(identifier) is None or identifier in seen:
            raise ApplyError("mutation action id is invalid or duplicated")
        if kind not in MUTATION_KINDS:
            raise ApplyError("mutation action kind is not permitted")
        artifact = value.get("artifact_digest")
        if not isinstance(artifact, str) or DIGEST.fullmatch(artifact) is None:
            raise ApplyError("mutation action artifact digest is required")
        details = {key: deep_thaw(item) for key, item in value.items() if key not in {"id", "kind"}}
        if "archive_digest" in details and (not isinstance(details["archive_digest"], str) or DIGEST.fullmatch(details["archive_digest"]) is None):
            raise ApplyError("mutation archive digest is invalid")
        for bank_key in ("source_bank", "target_bank"):
            if bank_key in details and (not isinstance(details[bank_key], dict) or set(details[bank_key]) != {"profile_id", "bank_id"}):
                raise ApplyError("mutation bank reference is closed")
            if bank_key in details and not all(isinstance(item, str) and item for item in details[bank_key].values()):
                raise ApplyError("mutation bank reference is invalid")
        result.append(Action(identifier, kind, deep_freeze(details)))
        seen.add(identifier)
    return tuple(result)


def build_mutation_plan(base_plan: Plan, *, migration_run_id: str, actions: Any) -> MutationPlan:
    verify_plan(base_plan)
    if not isinstance(migration_run_id, str) or SAFE_IDENTIFIER.fullmatch(migration_run_id) is None:
        raise ApplyError("migration run ID is invalid")
    normalized = _mutation_actions(actions)
    body = {
        "base_plan": base_plan.to_dict(), "plan_kind": "migration", "migration_run_id": migration_run_id,
        "actions": [action.to_dict() for action in normalized], "destructive": True,
    }
    return MutationPlan(base_plan, "migration", migration_run_id, normalized, digest(body))


def verify_mutation_plan(plan: MutationPlan) -> None:
    if not isinstance(plan, MutationPlan) or plan.plan_kind != "migration":
        raise ApplyError("mutation plan kind is invalid")
    rebuilt = build_mutation_plan(plan.base_plan, migration_run_id=plan.migration_run_id,
                                  actions=[action.to_dict() for action in plan.actions])
    if not hmac.compare_digest(rebuilt.plan_digest, plan.plan_digest):
        raise ApplyError("mutation plan digest does not match")


def mutation_plan_from_dict(value: Any) -> MutationPlan:
    keys = {"base_plan", "plan_kind", "migration_run_id", "actions", "destructive", "plan_digest"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ApplyError("mutation plan schema is closed")
    if value["plan_kind"] != "migration" or value["destructive"] is not True:
        raise ApplyError("mutation plan kind and destructive marker are required")
    try:
        base = plan_from_dict(value["base_plan"])
    except PlanError as error:
        raise ApplyError("mutation base plan is invalid") from error
    plan = build_mutation_plan(base, migration_run_id=value["migration_run_id"], actions=value["actions"])
    if not isinstance(value["plan_digest"], str) or not hmac.compare_digest(plan.plan_digest, value["plan_digest"]):
        raise ApplyError("mutation plan digest does not match")
    return plan


def parse_migration_gate(gate: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(gate, Mapping) or set(gate) != {"export", "import"}:
        raise ApplyError("migration gate requires export and import halves")
    halves = []
    for name in ("export", "import"):
        half = gate[name]
        if not isinstance(half, Mapping) or set(half) != {"run_id", "artifact_digest"}:
            raise ApplyError(f"migration gate {name} half is closed")
        run_id, artifact = half["run_id"], half["artifact_digest"]
        if not isinstance(run_id, str) or not run_id or not isinstance(artifact, str) or DIGEST.fullmatch(artifact) is None:
            raise ApplyError("migration gate run and artifact digests are required")
        halves.append((run_id, artifact))
    if halves[0] != halves[1]:
        raise ApplyError("migration gate halves do not match")
    return halves[0]


def _verify_execution_plan(plan: Plan | MutationPlan) -> None:
    if isinstance(plan, MutationPlan):
        verify_mutation_plan(plan)
    else:
        verify_plan(plan)


def create_rollback_bundle(plan: Plan | MutationPlan, adapter: Adapter) -> RollbackBundle:
    _verify_execution_plan(plan)
    return adapter.create_rollback_bundle(plan.plan_digest, tuple(action.id for action in plan.actions))


def _refused(reason: str) -> ApplyResult:
    return ApplyResult("refused", reason)


def apply_plan(plan: Plan | MutationPlan, adapter: Adapter, approval_digest: str,
               gate: Mapping[str, Any] | None) -> ApplyResult:
    try:
        _verify_execution_plan(plan)
    except (ApplyError, PlanError, TypeError, AttributeError):
        return _refused("invalid_or_destructive_plan")
    if not isinstance(approval_digest, str) or not hmac.compare_digest(approval_digest, plan.plan_digest):
        return _refused("approval_digest_mismatch")
    if isinstance(plan, MutationPlan):
        if not isinstance(gate, Mapping) or "migration_gate" not in gate:
            return _refused("migration_gate_required")
        if set(gate) != {"rollback_bundle", "migration_gate"}:
            return _refused("migration_gate_mismatch")
        try:
            run_id, artifact = parse_migration_gate(gate["migration_gate"])
        except ApplyError:
            return _refused("migration_gate_mismatch")
        if run_id != plan.migration_run_id or artifact != plan.artifact_digest:
            return _refused("migration_gate_mismatch")
    elif isinstance(gate, Mapping) and set(gate) - {"rollback_bundle"}:
        return _refused("apply_gate_invalid")
    if not isinstance(gate, Mapping) or not isinstance(gate.get("rollback_bundle"), RollbackBundle):
        return _refused("rollback_bundle_required")
    rollback = gate["rollback_bundle"]
    if rollback.plan_digest != plan.plan_digest or rollback.action_ids != tuple(action.id for action in plan.actions):
        return _refused("rollback_bundle_mismatch")
    try:
        fresh = adapter.snapshot()
    except Exception:
        return _refused("fresh_state_unavailable")
    if fresh.get("endpoint") != plan.target_endpoint.to_dict():
        return _refused("endpoint_identity_drift")
    fresh_state_digest = digest(fresh.get("state"))
    if fresh_state_digest != plan.live_state_digest:
        return _refused("live_state_drift")
    operations = fresh.get("operations")
    if not isinstance(operations, Mapping) or operations.get("idle") is not True or operations.get("active") != []:
        return _refused("operations_not_idle")
    if rollback.prestate_digest != plan.live_state_digest or rollback.prestate_digest != fresh_state_digest:
        return _refused("rollback_prestate_mismatch")
    fresh_endpoint_digest = digest(fresh.get("endpoint"))
    expected_endpoint_digest = digest(plan.target_endpoint.to_dict())
    if rollback.endpoint_digest != expected_endpoint_digest or rollback.endpoint_digest != fresh_endpoint_digest:
        return _refused("rollback_endpoint_mismatch")
    try:
        if adapter.verify_rollback_bundle(rollback) is not True:
            return _refused("disposable_restore_proof_required")
    except Exception:
        return _refused("disposable_restore_proof_required")

    ledger: list[Mapping[str, str]] = []
    applied: list[str] = []
    mutation_started = False
    try:
        for action in plan.actions:
            mutation_started = True
            adapter.apply_action(action)
            applied.append(action.id)
            ledger.append({"action_id": action.id, "status": "applied"})
            if adapter.verify_postcondition(action) is not True:
                raise ApplyError("postcondition failed")
            ledger.append({"action_id": action.id, "status": "verified"})
    except Exception:
        if not mutation_started:
            return _refused("mutation_failed_before_start")
        ledger.append({"status": "rollback_started"})
        try:
            adapter.restore(rollback)
            ledger.append({"status": "rollback_succeeded"})
            return ApplyResult("rolled_back", "apply_or_postcondition_failed", tuple(applied), True, True, True, tuple(ledger))
        except Exception:
            try:
                adapter.disable_activation()
            except Exception:
                pass
            ledger.append({"status": "operator_blocked"})
            return ApplyResult("operator_blocked", "rollback_failed", tuple(applied), True, False, None, tuple(ledger))
    return ApplyResult("applied", "ok", tuple(applied), False, False, True, tuple(ledger))
