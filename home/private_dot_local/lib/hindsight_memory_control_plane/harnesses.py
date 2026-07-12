"""Inactive broker-only harness rendering and reversible activation."""

from dataclasses import dataclass
import hmac
from pathlib import Path
import re
from typing import Any, Mapping

from .canonical import digest
from .model import deep_freeze, deep_thaw


SUPPORTED_HARNESSES = frozenset({"codex", "claude-code", "cursor"})
OWNED_KEYS = frozenset({"schemaVersion", "broker", "adapter", "active"})
RETIRED_DIRECT_KEYS = frozenset(
    {"hindsightApiUrl", "bankId", "tenantToken", "bearerToken", "apiKey", "signingKey"}
)
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
ACTIVATION_REQUIREMENTS = ("broker_healthy", "profile_healthy", "adapter_self_test")


@dataclass(frozen=True)
class RenderedHarness:
    harness_id: str
    rendered: Mapping[str, Any]
    prestate: Mapping[str, Mapping[str, Any]]
    expected_prestate_digest: str
    retired_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "rendered", deep_freeze(self.rendered))
        object.__setattr__(self, "prestate", deep_freeze(self.prestate))
        object.__setattr__(self, "retired_keys", tuple(self.retired_keys))

    def to_dict(self) -> dict[str, Any]:
        return {
            "harness_id": self.harness_id,
            "rendered": deep_thaw(self.rendered),
            "expected_prestate_digest": self.expected_prestate_digest,
            "retired_keys": list(self.retired_keys),
        }


@dataclass(frozen=True)
class ActivationPlan:
    harness_id: str
    inventory_digest: str
    artifact_digest: str
    policy_digest: str
    expected_prestate_digest: str
    expected_owned_prestate_digest: str
    owned_target: Mapping[str, Any]
    retired_keys: tuple[str, ...]
    requirements: tuple[str, ...]
    plan_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "owned_target", deep_freeze(self.owned_target))
        object.__setattr__(self, "retired_keys", tuple(self.retired_keys))
        object.__setattr__(self, "requirements", tuple(self.requirements))

    def body(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "harness_id": self.harness_id,
            "inventory_digest": self.inventory_digest,
            "artifact_digest": self.artifact_digest,
            "policy_digest": self.policy_digest,
            "expected_prestate_digest": self.expected_prestate_digest,
            "expected_owned_prestate_digest": self.expected_owned_prestate_digest,
            "owned_target": deep_thaw(self.owned_target),
            "retired_keys": list(self.retired_keys),
            "requirements": list(self.requirements),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.body(), "plan_digest": self.plan_digest}


@dataclass(frozen=True)
class ActivationOutcome:
    status: str
    reason: str
    configuration: Mapping[str, Any]
    activation_state: str
    plan_digest: str
    rollback_attempted: bool = False
    rollback_succeeded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "configuration": deep_thaw(self.configuration),
            "activation_state": self.activation_state,
            "plan_digest": self.plan_digest,
            "rollback_attempted": self.rollback_attempted,
            "rollback_succeeded": self.rollback_succeeded,
        }


def _socket_path(value: str) -> str:
    if not isinstance(value, str) or not value or "://" in value or not Path(value).is_absolute():
        raise ValueError("broker locator must be an absolute Unix socket path")
    return value


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def render_harness(
    current: Mapping[str, Any], *, harness_id: str, adapter: str, socket_path: str
) -> RenderedHarness:
    """Merge the exact managed keys into one inactive harness configuration."""

    harness_id = _identifier(harness_id, "harness ID")
    if harness_id not in SUPPORTED_HARNESSES:
        raise ValueError(f"unsupported harness: {harness_id}")
    adapter = _identifier(adapter, "adapter identity")
    socket_path = _socket_path(socket_path)
    if not isinstance(current, Mapping):
        raise ValueError("current harness configuration must be an object")

    prestate = {
        key: ({"present": True, "value": deep_thaw(current[key])} if key in current else {"present": False})
        for key in OWNED_KEYS
    }
    rendered = deep_thaw(current)
    retired_keys = tuple(sorted(RETIRED_DIRECT_KEYS.intersection(rendered)))
    for key in retired_keys:
        rendered.pop(key, None)
    rendered.update(
        {
            "schemaVersion": 1,
            "broker": {"transport": "unix", "path": socket_path, "scope": "user"},
            "adapter": adapter,
            "active": False,
        }
    )
    return RenderedHarness(harness_id, rendered, prestate, digest(current), retired_keys)


def render_harnesses(
    current_by_harness: Mapping[str, Mapping[str, Any]],
    bindings: Mapping[str, str],
    *,
    socket_path: str,
) -> Mapping[str, RenderedHarness]:
    """Render every declared Codex, Claude Code, or Cursor binding inactive."""

    if not isinstance(current_by_harness, Mapping) or not isinstance(bindings, Mapping):
        raise ValueError("harness configurations and bindings must be objects")
    unsupported = set(bindings) - SUPPORTED_HARNESSES
    if unsupported:
        raise ValueError(f"unsupported harness: {sorted(unsupported)[0]}")
    return deep_freeze(
        {
            harness_id: render_harness(
                current_by_harness.get(harness_id, {}),
                harness_id=harness_id,
                adapter=adapter,
                socket_path=socket_path,
            )
            for harness_id, adapter in bindings.items()
        }
    )


def _validate_digest(value: str, label: str) -> str:
    if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _owned_prestate(configuration: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        key: (
            {"present": True, "value": deep_thaw(configuration[key])}
            if key in configuration
            else {"present": False}
        )
        for key in OWNED_KEYS
    }


def _activation_surface(
    configuration: Mapping[str, Any], retired_keys: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    keys = OWNED_KEYS.union(retired_keys)
    return {
        key: (
            {"present": True, "value": deep_thaw(configuration[key])}
            if key in configuration
            else {"present": False}
        )
        for key in keys
    }


def _validate_prestate(value: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping) or set(value) != OWNED_KEYS:
        raise ValueError("owned prestate must contain the exact owned-key set")
    result: dict[str, dict[str, Any]] = {}
    for key in OWNED_KEYS:
        record = value[key]
        if not isinstance(record, Mapping) or record.get("present") not in {True, False}:
            raise ValueError("owned prestate entry is invalid")
        expected = {"present", "value"} if record["present"] is True else {"present"}
        if set(record) != expected:
            raise ValueError("owned prestate entry is invalid")
        result[key] = deep_thaw(record)
    return result


def activation_plan(
    rendered: RenderedHarness,
    *,
    inventory_digest: str,
    artifact_digest: str,
    policy_digest: str,
    current: Mapping[str, Any] | None = None,
) -> ActivationPlan:
    """Build an immutable activation plan without activating the harness."""

    if not isinstance(rendered, RenderedHarness):
        raise ValueError("rendered harness is required")
    digests = {
        "inventory_digest": _validate_digest(inventory_digest, "inventory digest"),
        "artifact_digest": _validate_digest(artifact_digest, "artifact digest"),
        "policy_digest": _validate_digest(policy_digest, "policy digest"),
    }
    if current is None:
        prestate = _validate_prestate(rendered.prestate)
        expected_prestate_digest = rendered.expected_prestate_digest
    else:
        if not isinstance(current, Mapping):
            raise ValueError("current harness configuration must be an object")
        expected_prestate_digest = digest(current)
        if not hmac.compare_digest(expected_prestate_digest, rendered.expected_prestate_digest):
            raise ValueError("current harness configuration does not match rendered prestate")
        prestate = _owned_prestate(current)
    target = {key: deep_thaw(rendered.rendered[key]) for key in OWNED_KEYS}
    target["active"] = True
    body = {
        "schema_version": 1,
        "harness_id": rendered.harness_id,
        **digests,
        "expected_prestate_digest": expected_prestate_digest,
        "expected_owned_prestate_digest": digest(prestate),
        "owned_target": target,
        "retired_keys": list(rendered.retired_keys),
        "requirements": list(ACTIVATION_REQUIREMENTS),
    }
    return ActivationPlan(
        rendered.harness_id,
        inventory_digest,
        artifact_digest,
        policy_digest,
        expected_prestate_digest,
        body["expected_owned_prestate_digest"],
        target,
        rendered.retired_keys,
        ACTIVATION_REQUIREMENTS,
        digest(body),
    )


def _valid_plan(plan: ActivationPlan) -> bool:
    if not isinstance(plan, ActivationPlan):
        return False
    try:
        _validate_digest(plan.inventory_digest, "inventory digest")
        _validate_digest(plan.artifact_digest, "artifact digest")
        _validate_digest(plan.policy_digest, "policy digest")
        _validate_digest(plan.expected_prestate_digest, "prestate digest")
        _validate_digest(plan.expected_owned_prestate_digest, "owned prestate digest")
    except (TypeError, ValueError):
        return False
    if set(plan.owned_target) != OWNED_KEYS or plan.owned_target.get("active") is not True:
        return False
    if len(set(plan.retired_keys)) != len(plan.retired_keys) or not set(plan.retired_keys).issubset(
        RETIRED_DIRECT_KEYS
    ):
        return False
    if plan.requirements != ACTIVATION_REQUIREMENTS:
        return False
    return hmac.compare_digest(digest(plan.body()), plan.plan_digest)


def _state(configuration: Mapping[str, Any]) -> str:
    active = configuration.get("active") if isinstance(configuration, Mapping) else None
    if active is True:
        return "active"
    if active is False:
        return "inactive"
    return "unknown"


def _outcome(
    status: str,
    reason: str,
    configuration: Mapping[str, Any],
    plan: ActivationPlan,
    *,
    rollback_attempted: bool = False,
    rollback_succeeded: bool = False,
) -> ActivationOutcome:
    copied = deep_thaw(deep_freeze(configuration))
    return ActivationOutcome(
        status,
        reason,
        copied,
        _state(copied),
        plan.plan_digest,
        rollback_attempted,
        rollback_succeeded,
    )


def apply_activation(
    plan: ActivationPlan,
    current: Mapping[str, Any],
    *,
    approved_plan_digest: str,
    inventory_digest: str,
    artifact_digest: str,
    policy_digest: str,
    broker_healthy: bool,
    profile_healthy: bool,
    adapter_self_test: bool,
    postcheck: bool,
) -> ActivationOutcome:
    """Apply only the plan's owned target after every fresh gate passes."""

    if not isinstance(current, Mapping):
        raise ValueError("current harness configuration must be an object")
    if not _valid_plan(plan):
        return _outcome("refused", "invalid_plan", current, plan)
    if not isinstance(approved_plan_digest, str) or not hmac.compare_digest(
        approved_plan_digest, plan.plan_digest
    ):
        return _outcome("refused", "plan_not_approved", current, plan)
    for label, actual, expected in (
        ("inventory", inventory_digest, plan.inventory_digest),
        ("artifact", artifact_digest, plan.artifact_digest),
        ("policy", policy_digest, plan.policy_digest),
    ):
        if not isinstance(actual, str) or not hmac.compare_digest(actual, expected):
            return _outcome("refused", f"{label}_digest_changed", current, plan)
    for healthy, reason in (
        (broker_healthy, "broker_unhealthy"),
        (profile_healthy, "profile_unhealthy"),
        (adapter_self_test, "adapter_self_test_failed"),
    ):
        if healthy is not True:
            return _outcome("refused", reason, current, plan)
    if not hmac.compare_digest(digest(_owned_prestate(current)), plan.expected_owned_prestate_digest):
        return _outcome("refused", "owned_prestate_changed", current, plan)
    if not hmac.compare_digest(digest(current), plan.expected_prestate_digest):
        return _outcome("refused", "prestate_changed", current, plan)

    activated = deep_thaw(deep_freeze(current))
    for key in plan.retired_keys:
        activated.pop(key, None)
    for key in OWNED_KEYS:
        activated[key] = deep_thaw(plan.owned_target[key])
    if postcheck is not True:
        rolled_back = rollback_activation(
            plan,
            activated,
            approved_plan_digest=approved_plan_digest,
            prestate=current,
        )
        configuration = deep_thaw(rolled_back.configuration)
        contained = configuration.get("active") is True
        if contained:
            configuration["active"] = False
        return ActivationOutcome(
            "rolled_back",
            "postcheck_failed",
            configuration,
            _state(configuration),
            plan.plan_digest,
            True,
            rolled_back.status == "rolled_back" and not contained,
        )
    return _outcome("activated", "ok", activated, plan)


def rollback_activation(
    plan: ActivationPlan,
    current: Mapping[str, Any],
    *,
    approved_plan_digest: str,
    prestate: Mapping[str, Any],
) -> ActivationOutcome:
    """Restore activation-owned fields from a digest-bound prestate snapshot."""

    if not isinstance(current, Mapping) or not isinstance(prestate, Mapping):
        raise ValueError("current and prestate harness configurations must be objects")
    if not _valid_plan(plan):
        return _outcome("refused", "invalid_plan", current, plan)
    if not isinstance(approved_plan_digest, str) or not hmac.compare_digest(
        approved_plan_digest, plan.plan_digest
    ):
        return _outcome("refused", "plan_not_approved", current, plan)
    if not hmac.compare_digest(digest(prestate), plan.expected_prestate_digest):
        return _outcome("refused", "rollback_prestate_changed", current, plan)

    expected_surface = {
        **{
            key: {"present": True, "value": deep_thaw(value)}
            for key, value in plan.owned_target.items()
        },
        **{key: {"present": False} for key in plan.retired_keys},
    }
    if not hmac.compare_digest(
        digest(_activation_surface(current, plan.retired_keys)), digest(expected_surface)
    ):
        return _outcome("refused", "activation_state_changed", current, plan)

    restored = deep_thaw(deep_freeze(current))
    for key in OWNED_KEYS.union(plan.retired_keys):
        if key in prestate:
            restored[key] = deep_thaw(prestate[key])
        else:
            restored.pop(key, None)
    return _outcome("rolled_back", "ok", restored, plan, rollback_attempted=True, rollback_succeeded=True)
