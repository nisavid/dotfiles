"""Immutable records shared by validation, planning, and apply slices."""

from dataclasses import dataclass
from typing import Any, Mapping, Tuple


class FrozenDict(dict):
    """A JSON-serializable dictionary that cannot change after construction."""

    @staticmethod
    def _immutable(*args: Any, **kwargs: Any) -> None:
        raise TypeError("frozen mapping cannot be modified")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def deep_freeze(value: Any) -> Any:
    if isinstance(value, FrozenDict):
        return value
    if isinstance(value, Mapping):
        return FrozenDict({key: deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze(item) for item in value)
    return value


def deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [deep_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class BankRef:
    profile_id: str
    bank_id: str
    endpoint: "EndpointIdentity | None" = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"profile_id": self.profile_id, "bank_id": self.bank_id}
        if self.endpoint is not None:
            value["endpoint"] = self.endpoint.to_dict()
        return value


@dataclass(frozen=True)
class EndpointIdentity:
    profile_id: str
    scheme: str
    host: str
    port: int
    tenant: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "scheme": self.scheme,
            "host": self.host,
            "port": self.port,
            "tenant": self.tenant,
        }


@dataclass(frozen=True)
class OperationSnapshot:
    idle: bool
    active: Tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "active", tuple(deep_freeze(item) for item in self.active))

    def to_dict(self) -> dict[str, Any]:
        return {"idle": self.idle, "active": [deep_thaw(item) for item in self.active]}


@dataclass(frozen=True)
class Action:
    id: str
    kind: str
    details: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", deep_freeze(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, **deep_thaw(self.details)}


@dataclass(frozen=True)
class Inventory:
    schema_version: int
    machine: Mapping[str, Any]
    archetype: Mapping[str, Any]
    profiles: Tuple[Mapping[str, Any], ...]
    providers: Tuple[Mapping[str, Any], ...]
    banks: Tuple[Mapping[str, Any], ...]
    harnesses: Tuple[Mapping[str, Any], ...]
    migration: Mapping[str, Any]
    policy: Mapping[str, Any]
    inventory_digest: str
    artifact_digest: str

    def __post_init__(self) -> None:
        for field in ("machine", "archetype", "migration", "policy"):
            object.__setattr__(self, field, deep_freeze(getattr(self, field)))
        for field in ("profiles", "providers", "banks", "harnesses"):
            object.__setattr__(self, field, tuple(deep_freeze(item) for item in getattr(self, field)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "machine": deep_thaw(self.machine),
            "archetype": deep_thaw(self.archetype),
            "profiles": [deep_thaw(value) for value in self.profiles],
            "providers": [deep_thaw(value) for value in self.providers],
            "banks": [deep_thaw(value) for value in self.banks],
            "harnesses": [deep_thaw(value) for value in self.harnesses],
            "migration": deep_thaw(self.migration),
            "policy": deep_thaw(self.policy),
        }


@dataclass(frozen=True)
class Plan:
    schema_version: int
    inventory_digest: str
    artifact_digest: str
    target_profile: str
    target_endpoint: EndpointIdentity
    live_state_digest: str
    operations: OperationSnapshot
    compatibility: Tuple[Mapping[str, Any], ...]
    actions: Tuple[Action, ...]
    destructive: bool
    plan_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "compatibility", tuple(deep_freeze(item) for item in self.compatibility))
        object.__setattr__(self, "actions", tuple(self.actions))

    def body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "inventory_digest": self.inventory_digest,
            "artifact_digest": self.artifact_digest,
            "target_profile": self.target_profile,
            "target_endpoint": self.target_endpoint.to_dict(),
            "live_state_digest": self.live_state_digest,
            "operations": self.operations.to_dict(),
            "compatibility": [deep_thaw(value) for value in self.compatibility],
            "actions": [value.to_dict() for value in self.actions],
            "destructive": self.destructive,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.body(), "plan_digest": self.plan_digest}
