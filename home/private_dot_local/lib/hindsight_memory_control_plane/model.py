"""Immutable records shared by validation, planning, and apply slices."""

from dataclasses import dataclass
from typing import Any, Mapping, Tuple


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

    def to_dict(self) -> dict[str, Any]:
        return {"idle": self.idle, "active": [dict(item) for item in self.active]}


@dataclass(frozen=True)
class Action:
    id: str
    kind: str
    details: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, **dict(self.details)}


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "machine": dict(self.machine),
            "archetype": dict(self.archetype),
            "profiles": [dict(value) for value in self.profiles],
            "providers": [dict(value) for value in self.providers],
            "banks": [dict(value) for value in self.banks],
            "harnesses": [dict(value) for value in self.harnesses],
            "migration": dict(self.migration),
            "policy": dict(self.policy),
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

    def body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "inventory_digest": self.inventory_digest,
            "artifact_digest": self.artifact_digest,
            "target_profile": self.target_profile,
            "target_endpoint": self.target_endpoint.to_dict(),
            "live_state_digest": self.live_state_digest,
            "operations": self.operations.to_dict(),
            "compatibility": [dict(value) for value in self.compatibility],
            "actions": [value.to_dict() for value in self.actions],
            "destructive": self.destructive,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.body(), "plan_digest": self.plan_digest}
