"""Closed-schema inventory loading and cross-reference validation."""

import json
from pathlib import Path
from typing import Any, Mapping

from .canonical import digest
from .model import Inventory


ROOT_KEYS = {
    "schema_version",
    "machine",
    "archetype",
    "profiles",
    "providers",
    "banks",
    "harnesses",
    "migration",
    "policy",
}
ROLES = {"llm", "embedding", "reranking"}
PLACEMENTS = {"local", "third-party-hosted", "private-remote"}


class InventoryError(ValueError):
    pass


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InventoryError(f"{label} must be an object")
    return value


def _records(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise InventoryError(f"{label} must be an array")
    records = [_mapping(record, f"{label} entry") for record in value]
    seen: set[str] = set()
    for record in records:
        identifier = record.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise InventoryError(f"{label} id must be a non-empty string")
        if identifier in seen:
            raise InventoryError(f"duplicate {label} id: {identifier}")
        seen.add(identifier)
    return records


def _reference(value: Any, label: str) -> tuple[str, str]:
    record = _mapping(value, label)
    profile_id = record.get("profile_id", record.get("profile"))
    bank_id = record.get("bank_id", record.get("bank"))
    if not isinstance(profile_id, str) or not isinstance(bank_id, str):
        raise InventoryError(f"{label} must name profile_id and bank_id")
    return profile_id, bank_id


def _enabled(record: Mapping[str, Any]) -> bool:
    value = record.get("enabled", True)
    if not isinstance(value, bool):
        raise InventoryError(f"profile {record.get('id')} enabled must be boolean")
    return value


def _profile_port(profile: Mapping[str, Any], base_port: int) -> int:
    port = profile.get("port")
    if port is None:
        slot = profile.get("slot")
        if type(slot) is not int or slot < 0:
            raise InventoryError(f"profile {profile.get('id')} requires a non-negative integer slot or port")
        port = base_port + slot
    if type(port) is not int or not 1 <= port <= 65535:
        raise InventoryError(f"profile {profile.get('id')} port must be an integer from 1 to 65535")
    return port


def _validate_migration(migration: Mapping[str, Any]) -> None:
    artifact = migration.get("artifact_dir", migration.get("artifact_path"))
    proposal = migration.get("proposal_log", migration.get("proposal_path"))
    for value, label in ((artifact, "migration artifact"), (proposal, "migration proposal")):
        if not isinstance(value, str) or not value.strip():
            raise InventoryError(f"{label} path must be a non-empty absolute path")
        if not Path(value).expanduser().is_absolute():
            raise InventoryError(f"{label} path must be absolute")


def _allowed_placements(policy: Mapping[str, Any], data_class: str) -> set[str] | None:
    table = policy.get("allowed_placements", policy.get("provider_placements"))
    if table is None:
        return None
    if not isinstance(table, dict):
        raise InventoryError("policy allowed_placements must be an object")
    allowed = table.get(data_class)
    if allowed is None:
        return None
    if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
        raise InventoryError(f"allowed placements for {data_class} must be an array of strings")
    return set(allowed)


def _validate(raw: dict[str, Any]) -> Inventory:
    if set(raw) != ROOT_KEYS:
        missing = sorted(ROOT_KEYS - set(raw))
        unknown = sorted(set(raw) - ROOT_KEYS)
        raise InventoryError(f"inventory root keys are closed (missing={missing}, unknown={unknown})")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise InventoryError("schema_version must be integer 1")

    machine = _mapping(raw["machine"], "machine")
    archetype = _mapping(raw["archetype"], "archetype")
    migration = _mapping(raw["migration"], "migration")
    policy = _mapping(raw["policy"], "policy")
    profiles = _records(raw["profiles"], "profiles")
    providers = _records(raw["providers"], "providers")
    banks = _records(raw["banks"], "banks")
    harnesses = _records(raw["harnesses"], "harnesses")
    _validate_migration(migration)

    profile_by_id = {record["id"]: record for record in profiles}
    provider_by_id = {record["id"]: record for record in providers}
    for provider in providers:
        if provider.get("role") not in ROLES:
            raise InventoryError(f"provider {provider['id']} has invalid role")
        if provider.get("placement") not in PLACEMENTS:
            raise InventoryError(f"provider {provider['id']} has invalid placement")
        data_classes = provider.get("data_classes")
        if (
            not isinstance(data_classes, list)
            or not all(isinstance(item, str) and item for item in data_classes)
            or len(set(data_classes)) != len(data_classes)
        ):
            raise InventoryError(
                f"provider {provider['id']} data_classes must be an array of unique non-empty strings"
            )
    base_port = machine.get("base_port", 7979)
    if type(base_port) is not int:
        raise InventoryError("machine base_port must be an integer")
    endpoints: dict[tuple[str, int], str] = {}
    for profile in profiles:
        host = profile.get("host", "127.0.0.1")
        if not isinstance(host, str) or not host:
            raise InventoryError(f"profile {profile['id']} host must be a non-empty string")
        port = _profile_port(profile, base_port)
        if _enabled(profile):
            endpoint = (host, port)
            if endpoint in endpoints:
                raise InventoryError(f"profile endpoint collision: {endpoints[endpoint]} and {profile['id']}")
            endpoints[endpoint] = profile["id"]

        roles = profile.get("roles", profile.get("provider_roles", {}))
        if not isinstance(roles, dict):
            raise InventoryError(f"profile {profile['id']} roles must be an object")
        unknown_roles = set(roles) - ROLES
        if unknown_roles:
            raise InventoryError(f"profile {profile['id']} has unknown provider roles: {sorted(unknown_roles)}")
        data_classes = profile.get("data_classes", [])
        if not isinstance(data_classes, list) or not all(isinstance(item, str) for item in data_classes):
            raise InventoryError(f"profile {profile['id']} data_classes must be an array of strings")
        for role, provider_id in roles.items():
            provider_ids = provider_id if isinstance(provider_id, list) else [provider_id]
            for selected_id in provider_ids:
                if selected_id not in provider_by_id:
                    raise InventoryError(f"profile {profile['id']} references unknown provider {selected_id}")
                provider = provider_by_id[selected_id]
                if provider["role"] != role:
                    raise InventoryError(f"provider {selected_id} cannot serve role {role}")
                placement = provider["placement"]
                permitted = provider["data_classes"]
                for data_class in data_classes:
                    if data_class not in permitted:
                        raise InventoryError(f"provider {selected_id} cannot receive {data_class} data")
                    allowed = _allowed_placements(policy, data_class)
                    if allowed is not None and placement not in allowed:
                        raise InventoryError(f"provider {selected_id} placement is forbidden for {data_class}")

    bank_refs: set[tuple[str, str]] = set()
    engineering_authorities = 0
    for bank in banks:
        profile_id = bank.get("profile_id", bank.get("profile"))
        if profile_id not in profile_by_id:
            raise InventoryError(f"bank {bank['id']} references unknown profile {profile_id}")
        bank_ref = (profile_id, bank["id"])
        if bank_ref in bank_refs:
            raise InventoryError(f"duplicate canonical bank reference: {profile_id}/{bank['id']}")
        bank_refs.add(bank_ref)
        authority = bank.get("authority", "none")
        if authority not in {"authoritative", "replica", "none"}:
            raise InventoryError(f"bank {bank['id']} has invalid authority")
        writable = bank.get("writable", True)
        if not isinstance(writable, bool):
            raise InventoryError(f"bank {bank['id']} writable must be boolean")
        data_class = bank.get("data_class", bank.get("kind"))
        if data_class == "engineering" and authority == "authoritative" and writable:
            engineering_authorities += 1

    engineering_enabled = policy.get("engineering_memory_enabled", machine.get("engineering_memory_enabled", False))
    if not isinstance(engineering_enabled, bool):
        raise InventoryError("engineering_memory_enabled must be boolean")
    if engineering_enabled and engineering_authorities != 1:
        raise InventoryError("engineering memory requires exactly one authoritative write bank")

    for harness in harnesses:
        profile_id = harness.get("profile_id", harness.get("profile"))
        if profile_id not in profile_by_id:
            raise InventoryError(f"harness {harness['id']} references unknown profile {profile_id}")
        for key in ("home_bank", "write_bank", "bank"):
            if key in harness:
                ref = _reference(harness[key], f"harness {harness['id']} {key}")
                if ref not in bank_refs:
                    raise InventoryError(f"harness {harness['id']} references unknown bank {ref[0]}/{ref[1]}")

    artifact = {
        "schema_version": raw["schema_version"],
        "archetype": archetype,
        "profiles": profiles,
        "providers": providers,
        "banks": banks,
        "harnesses": harnesses,
        "policy": policy,
    }
    return Inventory(
        schema_version=1,
        machine=machine,
        archetype=archetype,
        profiles=tuple(profiles),
        providers=tuple(providers),
        banks=tuple(banks),
        harnesses=tuple(harnesses),
        migration=migration,
        policy=policy,
        inventory_digest=digest(raw),
        artifact_digest=digest(artifact),
    )


def load_inventory(path: str | Path) -> Inventory:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InventoryError(f"cannot load inventory: {error}") from error
    return _validate(_mapping(raw, "inventory"))
