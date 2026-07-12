"""Construction, closed deserialization, and verification of immutable plans."""

import hmac
import re
from typing import Any, Mapping

from .canonical import digest
from .model import Action, EndpointIdentity, Inventory, OperationSnapshot, Plan


PLAN_KEYS = {
    "schema_version", "inventory_digest", "artifact_digest", "target_profile",
    "target_endpoint", "live_state_digest", "operations", "compatibility",
    "actions", "destructive", "plan_digest",
}
ENDPOINT_KEYS = {"profile_id", "scheme", "host", "port", "tenant"}
BANK_KEYS = {"profile_id", "bank_id"}
OPERATION_KEYS = {"id", "kind", "status", "profile_id", "bank", "endpoint", "artifact_digest"}
OPERATION_KINDS = {"apply", "consolidate", "export", "import", "migration", "reflect", "refresh", "retain"}
OPERATION_STATUSES = {"pending", "running", "succeeded", "failed", "cancelled"}
COMPATIBILITY_KEYS = {"check", "compatible", "reason_code", "profile_id", "provider_id", "model_id", "artifact_digest", "endpoint", "status"}
COMPATIBILITY_STATUSES = {"pass", "fail", "blocked", "unknown", "degraded"}
DESTRUCTIVE_ACTION_KINDS = {
    "delete_bank", "delete_directive", "delete_model", "delete_profile",
    "import_bank", "migrate_bank", "prune_bank", "prune_model",
    "replace_canonical_bank", "retire_artifact",
}
ACTION_SCHEMAS = {
    "activate_model": ({"profile_id", "provider_id", "model_id", "revision"}, {"profile_id", "provider_id", "model_id", "revision"}),
    "configure_bank": ({"bank", "artifact_digest"}, {"bank"}),
    "configure_profile": ({"profile_id", "artifact_digest"}, {"profile_id"}),
    "create_bank": ({"bank"}, {"bank"}),
    "install_model": ({"profile_id", "provider_id", "model_id", "revision", "artifact_digest"}, {"profile_id", "provider_id", "model_id", "revision", "artifact_digest"}),
    "reload_profile": ({"profile_id", "reason_code"}, {"profile_id", "reason_code"}),
    "report_unmanaged": ({"profile_id", "reason_code"}, {"profile_id", "reason_code"}),
    "set_auto_consolidation": ({"bank", "enabled"}, {"bank", "enabled"}),
    "set_memory_defense": ({"bank", "enabled"}, {"bank", "enabled"}),
    "upsert_directive": ({"bank", "directive_id", "artifact_digest"}, {"bank", "directive_id", "artifact_digest"}),
    "upsert_model": ({"bank", "model_id", "revision", "artifact_digest"}, {"bank", "model_id", "revision", "artifact_digest"}),
}
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class PlanError(ValueError):
    pass


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise PlanError(f"{label} must be a bounded identifier")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise PlanError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _exact_mapping(value: Any, keys: set[str], label: str, required: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanError(f"{label} must be an object")
    unknown = set(value) - keys
    missing = (required or set()) - set(value)
    if unknown or missing:
        raise PlanError(f"{label} keys are closed (missing={sorted(missing)}, unknown={sorted(unknown)})")
    return value


def _endpoint(value: Any, profile_id: str | None = None) -> EndpointIdentity:
    record = _exact_mapping(value, ENDPOINT_KEYS, "endpoint", ENDPOINT_KEYS)
    actual_profile = _identifier(record["profile_id"], "endpoint profile_id")
    if profile_id is not None and actual_profile != profile_id:
        raise PlanError("endpoint profile identity does not match target profile")
    scheme = record["scheme"]
    if scheme not in {"http", "https"}:
        raise PlanError("endpoint scheme must be http or https")
    host = record["host"]
    if not isinstance(host, str) or not host or len(host) > 253:
        raise PlanError("endpoint host must be a bounded non-empty string")
    port = record["port"]
    if type(port) is not int or not 1 <= port <= 65535:
        raise PlanError("endpoint port must be an integer from 1 to 65535")
    tenant = _identifier(record["tenant"], "endpoint tenant")
    return EndpointIdentity(actual_profile, scheme, host, port, tenant)


def _bank(value: Any, label: str) -> dict[str, str]:
    record = _exact_mapping(value, BANK_KEYS, label, BANK_KEYS)
    return {
        "profile_id": _identifier(record["profile_id"], f"{label} profile_id"),
        "bank_id": _identifier(record["bank_id"], f"{label} bank_id"),
    }


def _operations(value: Any) -> OperationSnapshot:
    if isinstance(value, OperationSnapshot):
        value = value.to_dict()
    record = _exact_mapping(value, {"idle", "active"}, "operations snapshot", {"idle", "active"})
    if not isinstance(record["idle"], bool):
        raise PlanError("operations idle must be boolean")
    active = record["active"]
    if not isinstance(active, list):
        raise PlanError("operations active must be an array")
    resolved = []
    for item in active:
        operation = _exact_mapping(item, OPERATION_KEYS, "operations entry", {"id", "kind", "status"})
        normalized: dict[str, Any] = {
            "id": _identifier(operation["id"], "operations id"),
            "kind": operation["kind"],
            "status": operation["status"],
        }
        if normalized["kind"] not in OPERATION_KINDS:
            raise PlanError("operations kind is not a supported enum")
        if normalized["status"] not in OPERATION_STATUSES:
            raise PlanError("operations status is not a supported enum")
        if "profile_id" in operation:
            normalized["profile_id"] = _identifier(operation["profile_id"], "operations profile_id")
        if "bank" in operation:
            normalized["bank"] = _bank(operation["bank"], "operations bank")
        if "endpoint" in operation:
            normalized["endpoint"] = _endpoint(operation["endpoint"]).to_dict()
        if "artifact_digest" in operation:
            normalized["artifact_digest"] = _digest(operation["artifact_digest"], "operations artifact_digest")
        resolved.append(normalized)
    if record["idle"] != (len(resolved) == 0):
        raise PlanError("operations idle state disagrees with active operations")
    return OperationSnapshot(record["idle"], tuple(resolved))


def _compatibility(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        raise PlanError("compatibility must be an array")
    resolved = []
    for item in value:
        result = _exact_mapping(item, COMPATIBILITY_KEYS, "compatibility result", {"check", "compatible"})
        if not isinstance(result["compatible"], bool):
            raise PlanError("compatibility compatible must be boolean")
        normalized: dict[str, Any] = {
            "check": _identifier(result["check"], "compatibility check"),
            "compatible": result["compatible"],
        }
        for key in ("reason_code", "profile_id", "provider_id", "model_id"):
            if key in result:
                normalized[key] = _identifier(result[key], f"compatibility {key}")
        if "artifact_digest" in result:
            normalized["artifact_digest"] = _digest(result["artifact_digest"], "compatibility artifact_digest")
        if "endpoint" in result:
            normalized["endpoint"] = _endpoint(result["endpoint"]).to_dict()
        if "status" in result:
            if result["status"] not in COMPATIBILITY_STATUSES:
                raise PlanError("compatibility status is not a supported enum")
            normalized["status"] = result["status"]
        resolved.append(normalized)
    return tuple(resolved)


def _actions(value: Any) -> tuple[Action, ...]:
    if not isinstance(value, list):
        raise PlanError("actions must be an array")
    result: list[Action] = []
    ids: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise PlanError("action must be an object")
        identifier = _identifier(item.get("id"), "action id")
        kind = item.get("kind")
        if kind in DESTRUCTIVE_ACTION_KINDS:
            raise PlanError(f"ordinary plan contains destructive action kind: {kind}")
        if kind not in ACTION_SCHEMAS:
            raise PlanError(f"action kind is not supported: {kind}")
        if identifier in ids:
            raise PlanError(f"duplicate action id: {identifier}")
        ids.add(identifier)
        allowed, required = ACTION_SCHEMAS[kind]
        details = {key: value for key, value in item.items() if key not in {"id", "kind"}}
        _exact_mapping(details, allowed, "action details", required)
        normalized: dict[str, Any] = {}
        for key, value in details.items():
            if key == "bank":
                normalized[key] = _bank(value, "action bank")
            elif key.endswith("_digest"):
                normalized[key] = _digest(value, f"action {key}")
            elif key == "enabled":
                if not isinstance(value, bool):
                    raise PlanError("action enabled must be boolean")
                normalized[key] = value
            else:
                normalized[key] = _identifier(value, f"action {key}")
        result.append(Action(identifier, kind, normalized))
    return tuple(result)


def inventory_endpoint(inventory: Inventory, profile_id: str) -> EndpointIdentity:
    profile = next((item for item in inventory.profiles if item["id"] == profile_id), None)
    if profile is None:
        raise PlanError("target profile is not declared")
    base_port = inventory.machine.get("base_port", 7979)
    port = profile.get("port")
    if port is None:
        port = base_port + profile["slot"]
    return EndpointIdentity(
        profile_id=profile_id,
        scheme=profile.get("scheme", "http"),
        host=profile.get("host", "127.0.0.1"),
        port=port,
        tenant=profile.get("tenant", "default"),
    )


def build_plan(inventory: Inventory, live_state: Mapping[str, Any], operations: Any) -> Plan:
    if not isinstance(live_state, dict):
        raise PlanError("live state must be an object")
    target_profile = _identifier(live_state.get("profile_id", live_state.get("target_profile")), "target profile")
    expected_endpoint = inventory_endpoint(inventory, target_profile)
    live_endpoint = _endpoint(live_state.get("endpoint", live_state.get("target_endpoint")), target_profile)
    if live_endpoint != expected_endpoint:
        raise PlanError("live endpoint identity does not match inventory")
    operation_snapshot = _operations(operations)
    compatibility = _compatibility(live_state.get("compatibility", []))
    actions = _actions(live_state.get("actions", []))
    state = live_state.get("state", live_state.get("live_state", {}))
    body = {
        "schema_version": 1,
        "inventory_digest": inventory.inventory_digest,
        "artifact_digest": inventory.artifact_digest,
        "target_profile": target_profile,
        "target_endpoint": expected_endpoint.to_dict(),
        "live_state_digest": digest(state),
        "operations": operation_snapshot.to_dict(),
        "compatibility": [dict(value) for value in compatibility],
        "actions": [action.to_dict() for action in actions],
        "destructive": False,
    }
    plan = Plan(
        schema_version=1,
        inventory_digest=inventory.inventory_digest,
        artifact_digest=inventory.artifact_digest,
        target_profile=target_profile,
        target_endpoint=expected_endpoint,
        live_state_digest=body["live_state_digest"],
        operations=operation_snapshot,
        compatibility=compatibility,
        actions=actions,
        destructive=False,
        plan_digest=digest(body),
    )
    verify_plan(plan)
    return plan


def plan_from_dict(value: Any) -> Plan:
    record = _exact_mapping(value, PLAN_KEYS, "plan", PLAN_KEYS)
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise PlanError("plan schema_version must be integer 1")
    if record["destructive"] is not False:
        raise PlanError("ordinary plan destructive must be false")
    target_profile = _identifier(record["target_profile"], "target profile")
    plan = Plan(
        schema_version=1,
        inventory_digest=_digest(record["inventory_digest"], "inventory_digest"),
        artifact_digest=_digest(record["artifact_digest"], "artifact_digest"),
        target_profile=target_profile,
        target_endpoint=_endpoint(record["target_endpoint"], target_profile),
        live_state_digest=_digest(record["live_state_digest"], "live_state_digest"),
        operations=_operations(record["operations"]),
        compatibility=_compatibility(record["compatibility"]),
        actions=_actions(record["actions"]),
        destructive=False,
        plan_digest=_digest(record["plan_digest"], "plan_digest"),
    )
    verify_plan(plan)
    return plan


def verify_plan(plan: Plan) -> None:
    if type(plan.schema_version) is not int or plan.schema_version != 1:
        raise PlanError("plan schema_version must be integer 1")
    _digest(plan.inventory_digest, "inventory_digest")
    _digest(plan.artifact_digest, "artifact_digest")
    _identifier(plan.target_profile, "target profile")
    _endpoint(plan.target_endpoint.to_dict(), plan.target_profile)
    _digest(plan.live_state_digest, "live_state_digest")
    _operations(plan.operations)
    _compatibility([dict(value) for value in plan.compatibility])
    _actions([action.to_dict() for action in plan.actions])
    if plan.destructive is not False:
        raise PlanError("ordinary plan destructive must be false")
    _digest(plan.plan_digest, "plan_digest")
    expected = digest(plan.body())
    if not hmac.compare_digest(expected, plan.plan_digest):
        raise PlanError("plan digest does not match plan body")
