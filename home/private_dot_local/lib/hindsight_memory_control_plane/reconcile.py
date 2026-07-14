"""Digest-bound reconciliation with adapter-attested rollback and migration gates."""

from dataclasses import dataclass
import hmac
from pathlib import Path
import re
from typing import Any, Mapping

from .action_contracts import MUTATION_ACTION_KINDS
from .adapters import Adapter, RollbackBundle
from .canonical import digest
from .file_evidence import FileEvidenceError, read_file_evidence
from .model import Action, EndpointIdentity, OperationSnapshot, Plan, deep_freeze, deep_thaw
from .planning import PlanError, plan_from_dict, verify_plan


DIGEST = re.compile(r"[0-9a-f]{64}\Z")
SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
MAX_GATE_FILE_BYTES = 1024 * 1024


class ApplyError(ValueError):
    pass


@dataclass(frozen=True)
class MigrationGateDescriptor:
    completion_marker: str
    proposal_log: str
    completion_marker_digest: str
    proposal_log_digest: str


@dataclass(frozen=True)
class MutationPlan:
    """Closed destructive plan isolated from ordinary non-destructive plans."""

    base_plan: Plan
    plan_kind: str
    migration_run_id: str
    migration_artifact_digest: str
    rollback_archive_digest: str
    actions: tuple[Action, ...]
    plan_digest: str

    @property
    def target_endpoint(self): return self.base_plan.target_endpoint
    @property
    def live_state_digest(self): return self.base_plan.live_state_digest

    def body(self) -> dict[str, Any]:
        return {
            "base_plan": self.base_plan.to_dict(), "plan_kind": self.plan_kind,
            "migration_run_id": self.migration_run_id,
            "migration_artifact_digest": self.migration_artifact_digest,
            "rollback_archive_digest": self.rollback_archive_digest,
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
        if kind not in MUTATION_ACTION_KINDS:
            raise ApplyError("mutation action kind is not permitted")
        artifact = value.get("artifact_digest")
        if not isinstance(artifact, str) or DIGEST.fullmatch(artifact) is None:
            raise ApplyError("mutation action artifact digest is required")
        details = {key: deep_thaw(item) for key, item in value.items() if key not in {"id", "kind"}}
        if not isinstance(details.get("archive_digest"), str) or DIGEST.fullmatch(details["archive_digest"]) is None:
            raise ApplyError("mutation archive digest is required")
        for bank_key in ("source_bank", "target_bank"):
            if bank_key in details and (not isinstance(details[bank_key], dict) or set(details[bank_key]) != {"profile_id", "bank_id"}):
                raise ApplyError("mutation bank reference is closed")
            if bank_key in details and not all(isinstance(item, str) and item for item in details[bank_key].values()):
                raise ApplyError("mutation bank reference is invalid")
        result.append(Action(identifier, kind, deep_freeze(details)))
        seen.add(identifier)
    return tuple(result)


def build_mutation_plan(base_plan: Plan, *, migration_run_id: str, migration_artifact_digest: str,
                        rollback_archive_digest: str, actions: Any) -> MutationPlan:
    verify_plan(base_plan)
    if not isinstance(migration_run_id, str) or SAFE_IDENTIFIER.fullmatch(migration_run_id) is None:
        raise ApplyError("migration run ID is invalid")
    if not isinstance(migration_artifact_digest, str) or DIGEST.fullmatch(migration_artifact_digest) is None:
        raise ApplyError("migration artifact digest is invalid")
    if not isinstance(rollback_archive_digest, str) or DIGEST.fullmatch(rollback_archive_digest) is None:
        raise ApplyError("rollback archive digest is invalid")
    normalized = _mutation_actions(actions)
    body = {
        "base_plan": base_plan.to_dict(), "plan_kind": "migration", "migration_run_id": migration_run_id,
        "migration_artifact_digest": migration_artifact_digest,
        "rollback_archive_digest": rollback_archive_digest,
        "actions": [action.to_dict() for action in normalized], "destructive": True,
    }
    return MutationPlan(
        base_plan, "migration", migration_run_id, migration_artifact_digest,
        rollback_archive_digest, normalized, digest(body),
    )


def verify_mutation_plan(plan: MutationPlan) -> None:
    if not isinstance(plan, MutationPlan) or plan.plan_kind != "migration":
        raise ApplyError("mutation plan kind is invalid")
    rebuilt = build_mutation_plan(plan.base_plan, migration_run_id=plan.migration_run_id,
                                  migration_artifact_digest=plan.migration_artifact_digest,
                                  rollback_archive_digest=plan.rollback_archive_digest,
                                  actions=[action.to_dict() for action in plan.actions])
    if not hmac.compare_digest(rebuilt.plan_digest, plan.plan_digest):
        raise ApplyError("mutation plan digest does not match")


def mutation_plan_from_dict(value: Any) -> MutationPlan:
    keys = {"base_plan", "plan_kind", "migration_run_id", "migration_artifact_digest", "rollback_archive_digest", "actions", "destructive", "plan_digest"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ApplyError("mutation plan schema is closed")
    if value["plan_kind"] != "migration" or value["destructive"] is not True:
        raise ApplyError("mutation plan kind and destructive marker are required")
    try:
        base = plan_from_dict(value["base_plan"])
    except PlanError as error:
        raise ApplyError("mutation base plan is invalid") from error
    plan = build_mutation_plan(
        base, migration_run_id=value["migration_run_id"],
        migration_artifact_digest=value["migration_artifact_digest"],
        rollback_archive_digest=value["rollback_archive_digest"],
        actions=value["actions"],
    )
    if not isinstance(value["plan_digest"], str) or not hmac.compare_digest(plan.plan_digest, value["plan_digest"]):
        raise ApplyError("mutation plan digest does not match")
    return plan


def _absolute_gate_path(value: str | Path, label: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise ApplyError(f"{label} path must be absolute")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ApplyError(f"{label} path must be absolute")
    return path


def _read_gate_file(path: Path, label: str) -> tuple[str, str]:
    try:
        evidence = read_file_evidence(path, label, max_bytes=MAX_GATE_FILE_BYTES)
    except FileEvidenceError as error:
        raise ApplyError(str(error)) from None
    assert evidence is not None
    raw, artifact_digest = evidence
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ApplyError(f"{label} must be UTF-8 text") from None
    return text, artifact_digest


def _gate_record(lines: list[str], label: str) -> tuple[str, str]:
    content = [line for line in lines if line]
    if len(content) != 2 or any("=" not in line for line in content):
        raise ApplyError(f"{label} must contain run and artifact")
    fields: dict[str, str] = {}
    for line in content:
        key, value = line.split("=", 1)
        if key in fields or key not in {"run", "artifact"}:
            raise ApplyError(f"{label} fields are closed")
        fields[key] = value
    if set(fields) != {"run", "artifact"}:
        raise ApplyError(f"{label} must contain run and artifact")
    run_id, artifact = fields["run"], fields["artifact"]
    if SAFE_IDENTIFIER.fullmatch(run_id) is None or DIGEST.fullmatch(artifact) is None:
        raise ApplyError(f"{label} run or artifact is invalid")
    return run_id, artifact


def _parse_completion_marker(value: str) -> tuple[str, str]:
    return _gate_record(value.splitlines(), "completion marker")


def _parse_proposal_log(value: str) -> tuple[tuple[str, str], ...]:
    lines = value.splitlines()
    entries: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        if line != "## Migration complete":
            continue
        end = index + 1
        while end < len(lines) and not lines[end].startswith("## "):
            end += 1
        entries.append(_gate_record(lines[index + 1:end], "proposal log migration-complete entry"))
    if not entries:
        raise ApplyError("proposal log has no Migration complete entry")
    return tuple(entries)


def capture_migration_gate(completion_marker: str | Path, proposal_log: str | Path) -> MigrationGateDescriptor:
    marker_path = _absolute_gate_path(completion_marker, "completion marker")
    proposal_path = _absolute_gate_path(proposal_log, "proposal log")
    marker_text, marker_digest = _read_gate_file(marker_path, "completion marker")
    proposal_text, proposal_digest = _read_gate_file(proposal_path, "proposal log")
    marker = _parse_completion_marker(marker_text)
    if marker not in _parse_proposal_log(proposal_text):
        raise ApplyError("migration gate sources do not match")
    return MigrationGateDescriptor(
        str(marker_path),
        str(proposal_path),
        marker_digest,
        proposal_digest,
    )


def parse_migration_gate(gate: MigrationGateDescriptor) -> tuple[str, str]:
    if type(gate) is not MigrationGateDescriptor:
        raise ApplyError("migration gate requires a file-backed descriptor")
    if not all(
        isinstance(value, str) and DIGEST.fullmatch(value) is not None
        for value in (gate.completion_marker_digest, gate.proposal_log_digest)
    ):
        raise ApplyError("migration gate descriptor digests are invalid")
    marker_path = _absolute_gate_path(gate.completion_marker, "completion marker")
    proposal_path = _absolute_gate_path(gate.proposal_log, "proposal log")
    marker_text, marker_digest = _read_gate_file(marker_path, "completion marker")
    proposal_text, proposal_digest = _read_gate_file(proposal_path, "proposal log")
    if not hmac.compare_digest(marker_digest, gate.completion_marker_digest) or not hmac.compare_digest(
        proposal_digest, gate.proposal_log_digest
    ):
        raise ApplyError("migration gate sources changed")
    marker = _parse_completion_marker(marker_text)
    if marker not in _parse_proposal_log(proposal_text):
        raise ApplyError("migration gate sources do not match")
    return marker


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
    migration_gate: MigrationGateDescriptor | None = None
    try:
        _verify_execution_plan(plan)
    except (ApplyError, PlanError, TypeError, AttributeError):
        return _refused("invalid_or_destructive_plan")
    if not isinstance(approval_digest, str) or not hmac.compare_digest(approval_digest, plan.plan_digest):
        return _refused("approval_digest_mismatch")
    compatibility = (
        plan.base_plan.compatibility
        if isinstance(plan, MutationPlan)
        else plan.compatibility
    )
    if any(
        result.get("compatible") is not True
        or result.get("status") in {"fail", "blocked", "unknown", "degraded"}
        for result in compatibility
    ):
        return _refused("compatibility_not_satisfied")
    if isinstance(plan, MutationPlan):
        if not isinstance(gate, Mapping) or "migration_gate" not in gate:
            return _refused("migration_gate_required")
        if set(gate) != {"rollback_bundle", "migration_gate"}:
            return _refused("migration_gate_mismatch")
        migration_gate = gate["migration_gate"]
        try:
            run_id, artifact = parse_migration_gate(migration_gate)
        except ApplyError:
            return _refused("migration_gate_mismatch")
        if run_id != plan.migration_run_id or artifact != plan.migration_artifact_digest:
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
    if migration_gate is not None:
        try:
            run_id, artifact = parse_migration_gate(migration_gate)
        except ApplyError:
            return _refused("migration_gate_mismatch")
        if run_id != plan.migration_run_id or artifact != plan.migration_artifact_digest:
            return _refused("migration_gate_mismatch")

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
