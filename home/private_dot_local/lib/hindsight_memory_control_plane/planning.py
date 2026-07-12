"""Construction and verification of immutable reconciliation plans."""

import hmac
from typing import Any, Mapping

from .canonical import digest
from .model import Action, EndpointIdentity, Inventory, OperationSnapshot, Plan


class PlanError(ValueError):
    pass


def _endpoint(value: Any, profile_id: str) -> EndpointIdentity:
    if not isinstance(value, dict):
        raise PlanError("live state endpoint must be an object")
    actual_profile = value.get("profile_id", profile_id)
    scheme = value.get("scheme", "http")
    host = value.get("host")
    port = value.get("port")
    tenant = value.get("tenant", "default")
    if actual_profile != profile_id:
        raise PlanError("endpoint profile identity does not match target profile")
    if not all(isinstance(item, str) and item for item in (actual_profile, scheme, host, tenant)):
        raise PlanError("endpoint identity has invalid string fields")
    if type(port) is not int or not 1 <= port <= 65535:
        raise PlanError("endpoint identity has invalid port")
    return EndpointIdentity(actual_profile, scheme, host, port, tenant)


def _operations(value: Any) -> OperationSnapshot:
    if isinstance(value, OperationSnapshot):
        return value
    if not isinstance(value, dict) or not isinstance(value.get("idle"), bool):
        raise PlanError("operations snapshot must declare boolean idle")
    active = value.get("active", [])
    if not isinstance(active, list) or not all(isinstance(item, dict) for item in active):
        raise PlanError("operations active must be an array of objects")
    if value["idle"] != (len(active) == 0):
        raise PlanError("operations idle state disagrees with active operations")
    return OperationSnapshot(value["idle"], tuple(active))


def _actions(value: Any) -> tuple[Action, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise PlanError("actions must be an array")
    result: list[Action] = []
    ids: set[str] = set()
    for record in value:
        if not isinstance(record, dict):
            raise PlanError("action must be an object")
        identifier = record.get("id")
        kind = record.get("kind")
        if not isinstance(identifier, str) or not identifier or not isinstance(kind, str) or not kind:
            raise PlanError("action requires non-empty id and kind")
        if identifier in ids:
            raise PlanError(f"duplicate action id: {identifier}")
        ids.add(identifier)
        result.append(Action(identifier, kind, {key: item for key, item in record.items() if key not in {"id", "kind"}}))
    return tuple(result)


def build_plan(inventory: Inventory, live_state: Mapping[str, Any], operations: Any) -> Plan:
    if not isinstance(live_state, dict):
        raise PlanError("live state must be an object")
    target_profile = live_state.get("profile_id", live_state.get("target_profile"))
    if not isinstance(target_profile, str) or target_profile not in {item["id"] for item in inventory.profiles}:
        raise PlanError("live state must select a declared target profile")
    endpoint = _endpoint(live_state.get("endpoint", live_state.get("target_endpoint")), target_profile)
    operation_snapshot = _operations(operations)
    compatibility = live_state.get("compatibility", [])
    if not isinstance(compatibility, list) or not all(isinstance(item, dict) for item in compatibility):
        raise PlanError("compatibility must be an array of objects")
    actions = _actions(live_state.get("actions", []))
    destructive = any(bool(action.details.get("destructive", False)) for action in actions)
    if destructive:
        raise PlanError("ordinary plans cannot contain destructive actions")
    state = live_state.get("state", live_state.get("live_state", {}))
    body = {
        "schema_version": 1,
        "inventory_digest": inventory.inventory_digest,
        "artifact_digest": inventory.artifact_digest,
        "target_profile": target_profile,
        "target_endpoint": endpoint.to_dict(),
        "live_state_digest": digest(state),
        "operations": operation_snapshot.to_dict(),
        "compatibility": compatibility,
        "actions": [action.to_dict() for action in actions],
        "destructive": False,
    }
    plan = Plan(
        schema_version=1,
        inventory_digest=inventory.inventory_digest,
        artifact_digest=inventory.artifact_digest,
        target_profile=target_profile,
        target_endpoint=endpoint,
        live_state_digest=body["live_state_digest"],
        operations=operation_snapshot,
        compatibility=tuple(compatibility),
        actions=actions,
        destructive=False,
        plan_digest=digest(body),
    )
    verify_plan(plan)
    return plan


def verify_plan(plan: Plan) -> None:
    if type(plan.schema_version) is not int or plan.schema_version != 1:
        raise PlanError("plan schema_version must be integer 1")
    expected = digest(plan.body())
    if not hmac.compare_digest(expected, plan.plan_digest):
        raise PlanError("plan digest does not match plan body")
