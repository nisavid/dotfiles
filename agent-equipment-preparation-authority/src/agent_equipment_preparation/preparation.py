"""Fail-closed production of Agent Equipment preparation authority.

This package deliberately has no import-time or runtime dependency on the
candidate controller.  The gate accepts exact schema and manifest byte streams
from an independently protected deployment binding, admits one read-only
``prepare`` call for each planned action, and commits one complete preparation
bundle.  It has no mutation, checkpoint, nonce, or release interface.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from jsonschema import Draft202012Validator

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PROVIDER_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9_]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"(?:AKIA|ASIA)[0-9A-Z]{16}|"
    r"sk-[A-Za-z0-9_-]{20,}|"
    r"pst_[A-Za-z0-9_-]{12,}::[A-Za-z0-9_-]{8,})(?![A-Za-z0-9_])"
)
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._~+/-]+)")
_AUTHORIZATION_SCHEME = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])(?:authorization|proxy-authorization)\s*[:=]\s*"
    r"(?:bearer|basic|digest)\s+[A-Za-z0-9][^\s,\]\}\"']*"
)
_OPAQUE_AUTHORIZATION_HEADER = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])(?:authorization|proxy-authorization)\s*[:=]\s*"
    r"(?!fixture/|sha256:|validated_record\b)"
    r"[A-Za-z0-9][A-Za-z0-9._~+/@:-]{7,}"
)
_CREDENTIAL_QUERY = re.compile(
    r"(?i)[?&](?:x-api-key|api[_-]?key|access[_-]?token|token|secret|"
    r"password|client[_-]?secret)=[A-Za-z0-9][^&#\s,\]\}\"']*"
)
_PRIVATE_KEY_MARKER = re.compile(
    r"-----BEGIN (?:(?:ENCRYPTED|RSA|EC|DSA|OPENSSH) )?PRIVATE KEY-----|"
    r"-----BEGIN " + r"PGP PRIVATE KEY BLOCK-----|"
    r"-----BEGIN " + r"SSH2 ENCRYPTED PRIVATE KEY-----|"
    r"---- BEGIN " + r"SSH2 ENCRYPTED PRIVATE KEY ----|"
    r"PuTTY-User-" + r"Key-File-[0-9]+[ \t]*:|"
    r"AGE-"
    r"SECRET-KEY-"
)
_MAX_INPUT_BYTES = 16 * 1024 * 1024
_MAX_ADAPTER_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_STORE_ENTRY_BYTES = 64 * 1024 * 1024
_MAX_ACTIONS = 1024
_CREDENTIAL_FIELD_ROLES = frozenset(
    {
        "personalaccesstoken",
        "secretaccesskey",
        "accesskeyid",
        "proxyauthorization",
        "servicerolekey",
        "enterprisetoken",
        "sessiontoken",
        "accesstoken",
        "clientsecret",
        "secretkey",
        "authtoken",
        "apitoken",
        "bottoken",
        "oauthtoken",
        "xapikey",
        "apikey",
        "authorization",
        "password",
        "secret",
        "token",
        "pat",
        "credential",
        "credentials",
    }
)


class _InvalidPreparation(ValueError):
    """Internal secret-free rejection."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _byte_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _digest(value: object) -> str:
    return _byte_digest(_canonical_bytes(value))


def _strict_object(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, member in pairs:
        if key in value:
            raise _InvalidPreparation("duplicate JSON object member")
        value[key] = member
    return value


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise _InvalidPreparation("non-finite JSON number")
    return parsed


def _reject_constant(_: str) -> object:
    raise _InvalidPreparation("non-JSON numeric constant")


def _parse_exact_object(
    raw: object,
    *,
    maximum_bytes: int,
    canonical: bool = True,
) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > maximum_bytes:
        raise _InvalidPreparation("invalid byte stream")
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as error:
        raise _InvalidPreparation("invalid JSON byte stream") from error
    if not isinstance(value, dict):
        raise _InvalidPreparation("top-level JSON value must be an object")
    if canonical and _canonical_bytes(value) != raw:
        raise _InvalidPreparation("JSON byte stream is not canonical")
    return value


def _require_closed(value: Mapping[str, object], fields: frozenset[str]) -> None:
    if frozenset(value) != fields:
        raise _InvalidPreparation("record does not use its closed field set")


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise _InvalidPreparation("invalid digest")
    return value


def _require_text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise _InvalidPreparation("invalid identity")
    return value


def _verify_sealed_record(
    value: Mapping[str, object],
    *,
    identity_field: str,
    identity_prefix: str,
    digest_field: str,
) -> None:
    identity = _require_text(value.get(identity_field))
    digest = _require_digest(value.get(digest_field))
    identity_payload = copy.deepcopy(dict(value))
    identity_payload.pop(identity_field, None)
    identity_payload.pop(digest_field, None)
    if identity != identity_prefix + _digest(identity_payload):
        raise _InvalidPreparation("record identity does not match its content")
    digest_payload = copy.deepcopy(dict(value))
    digest_payload.pop(digest_field, None)
    if digest != _digest(digest_payload):
        raise _InvalidPreparation("record digest does not match its content")


def _seal_record(
    value: dict[str, object],
    *,
    identity_field: str,
    identity_prefix: str,
    digest_field: str,
) -> None:
    identity_payload = copy.deepcopy(value)
    identity_payload.pop(identity_field, None)
    identity_payload.pop(digest_field, None)
    value[identity_field] = identity_prefix + _digest(identity_payload)
    digest_payload = copy.deepcopy(value)
    digest_payload.pop(digest_field, None)
    value[digest_field] = _digest(digest_payload)


def _contains_literal_secret(value: object, *, key: str = "") -> bool:
    """Reject obvious literal credentials without rejecting named references."""

    normalized_key = key.lower().replace("-", "_")
    reference_key = normalized_key.endswith(
        ("_reference", "_references", "_identity", "_digest")
    )
    key_components = tuple(
        component
        for component in re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).lower().split("_")
        if component
    )
    compact_key = "".join(key_components)
    sensitive_field = any(
        marker in normalized_key
        for marker in (
            "pass" + "word",
            "pass" + "wd",
            "access_" + "token",
            "private_" + "key",
            "api_" + "key",
        )
    ) or compact_key in _CREDENTIAL_FIELD_ROLES
    if isinstance(value, Mapping):
        return any(
            _contains_literal_secret(member, key=str(member_key))
            for member_key, member in value.items()
        )
    if isinstance(value, list):
        return any(_contains_literal_secret(member, key=key) for member in value)
    if sensitive_field and not reference_key and value not in (None, "", [], {}):
        return True
    if isinstance(value, str):
        if (
            _PRIVATE_KEY_MARKER.search(value)
            or _PROVIDER_TOKEN.search(value)
            or _AUTHORIZATION_SCHEME.search(value)
            or _OPAQUE_AUTHORIZATION_HEADER.search(value)
            or _CREDENTIAL_QUERY.search(value)
        ):
            return True
        for match in _BEARER_VALUE.finditer(value):
            token = match.group(1)
            if (
                len(token) >= 20
                or re.fullmatch(
                    r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
                    token,
                )
                is not None
                or (
                    len(token) >= 16
                    and re.search(r"[0-9._~+/-]", token) is not None
                )
            ):
                return True
    return False


def _schema_validator(
    raw_schema: bytes,
) -> tuple[dict[str, object], Draft202012Validator]:
    schema = _parse_exact_object(
        raw_schema, maximum_bytes=_MAX_INPUT_BYTES, canonical=False
    )
    Draft202012Validator.check_schema(schema)
    return schema, Draft202012Validator(schema)


def _schema_definition_validator(
    schema: Mapping[str, object],
    definition: str,
) -> Draft202012Validator:
    definitions = schema.get("$defs")
    if not isinstance(definitions, Mapping) or definition not in definitions:
        raise _InvalidPreparation("required schema definition is missing")
    definition_schema: dict[str, object] = {
        "$schema": schema.get(
            "$schema",
            "https://json-schema.org/draft/2020-12/schema",
        ),
        "$defs": copy.deepcopy(dict(definitions)),
        "$ref": f"#/$defs/{definition}",
    }
    Draft202012Validator.check_schema(definition_schema)
    return Draft202012Validator(definition_schema)


def _validate_schema(
    validators: Mapping[str, Draft202012Validator],
    name: str,
    value: object,
) -> None:
    validator = validators.get(name)
    if validator is None or not validator.is_valid(value):
        raise _InvalidPreparation("schema validation failed")


def _plan_action_set_digest(plan: Mapping[str, object]) -> str:
    actions = plan.get("actions")
    if not isinstance(actions, list):
        raise _InvalidPreparation("plan actions must be an array")
    ordered = sorted(
        actions,
        key=lambda evidence: (
            int(evidence["action_payload"]["ordinal"]),
            str(evidence["action_payload"]["action_identity"]),
        ),
    )
    payload = {
        "schema_version": "agent-equipment-plan-action-set/v1",
        "candidate_identity": plan.get("candidate_identity"),
        "implementation_manifest_digest": plan.get("implementation_manifest_digest"),
        "plan_digest": plan.get("plan_digest"),
        "actions": ordered,
    }
    return _digest(payload)


def _plan_action_identity(action: Mapping[str, object]) -> str:
    return "action:" + _digest(
        {
            "plan_digest": action.get("plan_digest"),
            "ordinal": action.get("ordinal"),
            "route_id": action.get("route_identity"),
            "operation": action.get("operation"),
            "desired_state_digest": action.get("desired_state_digest"),
        }
    )


def _logical_surface_rule(
    surface: object,
    *,
    route_identity: object,
    equipment_identity: object,
) -> str | None:
    if not all(
        isinstance(value, str)
        for value in (surface, route_identity, equipment_identity)
    ):
        return None
    expected = {
        "route_identity": f"surface:{route_identity}",
        "shared_equipment_identity": f"surface:shared/{equipment_identity}",
        "route_and_equipment_identity": (
            f"surface:{route_identity}/{equipment_identity}"
        ),
    }
    for rule, expected_surface in expected.items():
        if surface == expected_surface:
            return rule
    return None


def _surface_rule_for_action(action: Mapping[str, object]) -> str | None:
    route_identity = action.get("route_identity")
    active = action.get("equipment_identities")
    controlled = action.get("controlled_equipment_identities")
    surface_scope = action.get("surface_scope")
    if (
        not isinstance(route_identity, str)
        or not isinstance(active, list)
        or not isinstance(controlled, list)
        or not isinstance(surface_scope, list)
        or any(not isinstance(identity, str) for identity in [*active, *controlled])
        or active != sorted(set(active))
        or controlled != sorted(set(controlled))
    ):
        return None
    identities = sorted(set(active) | set(controlled))
    if not identities:
        return None
    expected_scopes = {
        "route_identity": [f"surface:{route_identity}"],
        "shared_equipment_identity": [
            f"surface:shared/{identity}" for identity in identities
        ],
        "route_and_equipment_identity": [
            f"surface:{route_identity}/{identity}" for identity in identities
        ],
    }
    for rule, expected_scope in expected_scopes.items():
        if surface_scope == expected_scope:
            return rule
    return None


def _logical_surface_rule_for_target(
    action: Mapping[str, object],
    target: Mapping[str, object],
) -> str | None:
    equipment = target.get("equipment_identity")
    if equipment is None:
        active = action.get("equipment_identities")
        controlled = action.get("controlled_equipment_identities")
        if not isinstance(active, list) or not isinstance(controlled, list):
            return None
        plugin_equipment = {
            identity
            for identity in [*active, *controlled]
            if isinstance(identity, str) and identity.startswith("plugin:")
        }
        if len(plugin_equipment) != 1:
            return None
        equipment = next(iter(plugin_equipment))
    return _logical_surface_rule(
        target.get("write_surface_identity"),
        route_identity=action.get("route_identity"),
        equipment_identity=equipment,
    )


def _write_target_matches_action_authority(
    target: Mapping[str, object],
    action: Mapping[str, object],
) -> bool:
    provider = action.get("provider")
    locator = target.get("locator")
    surface_scope = action.get("surface_scope")
    active = action.get("equipment_identities")
    controlled = action.get("controlled_equipment_identities")
    if (
        not isinstance(provider, Mapping)
        or not isinstance(locator, Mapping)
        or not isinstance(surface_scope, list)
        or not isinstance(active, list)
        or not isinstance(controlled, list)
        or target.get("write_surface_identity") not in surface_scope
    ):
        return False
    equipment = target.get("equipment_identity")
    authoritative_equipment = set(active) | set(controlled)
    if isinstance(equipment, str) and equipment not in authoritative_equipment:
        return False
    kind = target.get("surface_kind")
    harness = action.get("harness")
    operation = action.get("operation")
    provider_kind = provider.get("kind")
    if kind in {"plugin_installation", "plugin_enablement"}:
        manager = provider.get("manager")
        expected_kind = {
            "claude": {
                "install": "plugin_installation",
                "enable": "plugin_enablement",
                "disable": "plugin_enablement",
            },
            "codex": {
                "install": "plugin_installation",
                "enable": "plugin_enablement",
                "disable": "plugin_enablement",
            },
            "cursor": {},
        }.get(str(manager), {}).get(str(operation))
        plugin_equipment = {
            identity
            for identity in authoritative_equipment
            if isinstance(identity, str) and identity.startswith("plugin:")
        }
        return (
            provider_kind == "native_plugin"
            and kind == expected_kind
            and equipment is None
            and harness == manager
            and dict(locator)
            == {
                "manager": manager,
                "native_identity": provider.get("plugin_id"),
                "scope": provider.get("scope"),
            }
            and len(plugin_equipment) == 1
            and _logical_surface_rule(
                target.get("write_surface_identity"),
                route_identity=action.get("route_identity"),
                equipment_identity=next(iter(plugin_equipment), None),
            )
            is not None
        )
    if kind == "claude_skill_entry":
        path = locator.get("path")
        allowed_operations = {
            "native_plugin": {"install"},
            "standalone_skill": {"install", "remove", "restore"},
        }
        return (
            provider_kind in allowed_operations
            and operation in allowed_operations[str(provider_kind)]
            and harness == "claude"
            and isinstance(equipment, str)
            and equipment.startswith("skill:")
            and isinstance(path, str)
            and path.removeprefix("~/.claude/skills/")
            == equipment.rsplit("/", 1)[-1]
            and _logical_surface_rule(
                target.get("write_surface_identity"),
                route_identity=action.get("route_identity"),
                equipment_identity=equipment,
            )
            is not None
        )
    if kind == "mcp_selection":
        server_name = provider.get("server_name")
        coordinates = {
            "claude": ("settings", "mcpServers"),
            "codex": ("config", "mcp_servers"),
            "cursor": ("config", "mcpServers"),
        }.get(str(harness))
        return (
            provider_kind == "direct_mcp"
            and operation in {"configure", "enable", "disable", "remove", "restore"}
            and isinstance(equipment, str)
            and equipment.startswith("mcp:")
            and isinstance(server_name, str)
            and coordinates is not None
            and dict(locator)
            == {
                "owner": harness,
                "source": coordinates[0],
                "key_path": [coordinates[1], server_name],
            }
            and _logical_surface_rule(
                target.get("write_surface_identity"),
                route_identity=action.get("route_identity"),
                equipment_identity=equipment,
            )
            is not None
        )
    if kind == "plugin_selection":
        plugin_id = provider.get("plugin_id")
        return (
            provider_kind == "native_plugin"
            and operation == "configure"
            and harness == "codex"
            and isinstance(equipment, str)
            and equipment.startswith("plugin:")
            and isinstance(plugin_id, str)
            and dict(locator)
            == {
                "owner": "codex",
                "source": "config",
                "key_path": ["plugins", plugin_id],
            }
            and _logical_surface_rule(
                target.get("write_surface_identity"),
                route_identity=action.get("route_identity"),
                equipment_identity=equipment,
            )
            is not None
        )
    return False


def _plan_action_graph_is_closed(action: Mapping[str, object]) -> bool:
    targets = action.get("write_targets")
    dependencies = action.get("verification_dependencies")
    surface_scope = action.get("surface_scope")
    if (
        not isinstance(targets, list)
        or not isinstance(dependencies, list)
        or not isinstance(surface_scope, list)
    ):
        return False
    identities: list[str] = []
    surfaces: list[str] = []
    surface_rules: list[str] = []
    target_by_surface: dict[str, Mapping[str, object]] = {}
    claude_target_surfaces: set[str] = set()
    for target in targets:
        if not isinstance(target, Mapping):
            return False
        identity_payload = {
            "surface_kind": target.get("surface_kind"),
            "locator": target.get("locator"),
        }
        if "equipment_identity" in target:
            identity_payload["equipment_identity"] = target["equipment_identity"]
        identity = target.get("target_identity")
        surface = target.get("write_surface_identity")
        rule = _logical_surface_rule_for_target(action, target)
        if (
            identity != "target:" + _digest(identity_payload)
            or not isinstance(identity, str)
            or not isinstance(surface, str)
            or surface in target_by_surface
            or rule is None
            or not _write_target_matches_action_authority(target, action)
        ):
            return False
        identities.append(identity)
        surfaces.append(surface)
        surface_rules.append(rule)
        target_by_surface[surface] = target
        if target.get("surface_kind") == "claude_skill_entry":
            claude_target_surfaces.add(surface)
    expected_surface_rule = _surface_rule_for_action(action)
    if (
        identities != sorted(set(identities))
        or sorted(surfaces) != surface_scope
        or not surface_rules
        or set(surface_rules) != {expected_surface_rule}
    ):
        return False

    claimed_surfaces: set[str] = set()
    claimed_identities: set[str] = set()
    canonical_dependencies: list[bytes] = []
    for dependency in dependencies:
        if not isinstance(dependency, Mapping):
            return False
        surface = dependency.get("write_surface_identity")
        identity = dependency.get("dependency_identity")
        if (
            not isinstance(surface, str)
            or surface in claimed_surfaces
            or not isinstance(identity, str)
            or identity in claimed_identities
        ):
            return False
        target = target_by_surface.get(surface)
        target_locator = target.get("locator") if target is not None else None
        dependency_locator = dependency.get("target_locator")
        if (
            target is None
            or target.get("surface_kind") != "claude_skill_entry"
            or target.get("equipment_identity")
            != dependency.get("equipment_identity")
            or not isinstance(target_locator, Mapping)
            or not isinstance(dependency_locator, Mapping)
        ):
            return False
        expected_identity = "dependency:" + _digest(
            {
                "relationship": dependency.get("relationship"),
                "write_surface_identity": surface,
                "equipment_identity": dependency.get("equipment_identity"),
                "target_locator": dependency_locator,
            }
        )
        write_path = target_locator.get("path")
        dependency_path = dependency_locator.get("path")
        if (
            dependency.get("relationship") != "canonical_skill_projection"
            or identity != expected_identity
            or not isinstance(write_path, str)
            or not isinstance(dependency_path, str)
            or write_path.removeprefix("~/.claude/skills/")
            != dependency_path.removeprefix("~/.agents/skills/")
        ):
            return False
        claimed_surfaces.add(surface)
        claimed_identities.add(identity)
        canonical_dependencies.append(_canonical_bytes(dependency))
    return (
        claimed_surfaces == claude_target_surfaces
        and canonical_dependencies == sorted(set(canonical_dependencies))
    )


def _desired_state_matches_action(action: Mapping[str, object]) -> bool:
    operation = action.get("operation")
    desired = action.get("desired_state")
    if not isinstance(desired, Mapping):
        return False
    operation_states: dict[str, dict[str, object]] = {
        "install": {"route_presence": "present"},
        "enable": {"enablement": "enabled"},
        "disable": {"enablement": "disabled"},
        "remove": {"route_presence": "absent"},
        "restore": {"route_presence": "present"},
    }
    if operation in operation_states:
        return dict(desired) == operation_states[str(operation)]
    if operation != "configure":
        return False
    provider = action.get("provider")
    controlled = action.get("controlled_equipment_identities")
    components = desired.get("component_states", [])
    if (
        not isinstance(provider, Mapping)
        or not isinstance(controlled, list)
        or not isinstance(components, list)
        or any(
            not isinstance(component, Mapping)
            or set(component) != {"equipment_identity", "state"}
            or component.get("state") not in {"enabled", "disabled"}
            for component in components
        )
    ):
        return False
    identities = [str(component["equipment_identity"]) for component in components]
    if identities != sorted(set(identities)) or identities != controlled:
        return False
    expected: dict[str, object] = {
        "configuration": {
            "status": "desired",
            "digest": _digest(
                {
                    "provider": provider,
                    "component_controls": components,
                }
            ),
        }
    }
    if components:
        expected["component_states"] = components
    return dict(desired) == expected


def _secret_references_match(action: Mapping[str, object]) -> bool:
    provider = action.get("provider")
    declared = action.get("secret_references")
    if not isinstance(provider, Mapping) or not isinstance(declared, list):
        return False
    consumed: set[tuple[str, str]] = set()
    arguments = provider.get("arguments")
    if isinstance(arguments, list):
        for argument in arguments:
            if not isinstance(argument, Mapping):
                return False
            environment = argument.get("secret_reference")
            profile = argument.get("secret_profile_reference")
            if isinstance(environment, str):
                consumed.add(("environment_variable", environment))
            if isinstance(profile, str):
                consumed.add(("secret_profile", profile))
    declared_set = {
        (str(reference.get("kind")), str(reference.get("name")))
        for reference in declared
        if isinstance(reference, Mapping)
    }
    declared_order = [
        _canonical_bytes(reference)
        for reference in declared
        if isinstance(reference, Mapping)
    ]
    return (
        len(declared_order) == len(declared)
        and consumed == declared_set
        and len(declared_set) == len(declared)
        and declared_order == sorted(set(declared_order))
    )


def _captured_surface_recovery_is_valid(surface: Mapping[str, object]) -> bool:
    kind = surface.get("kind")
    observation = surface.get("observation")
    recovery = surface.get("recovery")
    if not isinstance(observation, Mapping) or not isinstance(recovery, Mapping):
        return False
    if kind == "canonical_skill_entry":
        return dict(recovery) == {"kind": "none", "reason": "verification_only"}
    if kind == "claude_skill_entry":
        if observation.get("entry_type") == "absent":
            return dict(recovery) == {"kind": "none", "reason": "absent_noop"}
        return recovery.get("kind") == "private_blob"
    if kind in {"mcp_selection", "plugin_selection"}:
        if observation.get("present") is False:
            return dict(recovery) == {"kind": "none", "reason": "absent_noop"}
        return recovery.get("kind") == "private_blob"
    if kind in {"plugin_enablement", "legacy_projector"}:
        if (
            kind == "plugin_enablement"
            and observation.get("applicable") is False
            and observation.get("reason") == "not_installed"
        ):
            return dict(recovery) == {"kind": "none", "reason": "absent_noop"}
        return recovery.get("kind") in {"structured_snapshot", "private_blob"}
    return kind == "plugin_installation"


def _native_route_capture_is_coherent(
    route: Mapping[str, object],
    surface_by_identity: Mapping[str, Mapping[str, object]],
    actions: Sequence[Mapping[str, object]],
) -> bool:
    references = route.get("surface_references")
    restore = route.get("restore_evidence")
    if not isinstance(references, Mapping) or not isinstance(restore, Mapping):
        return False
    installation_reference = references.get("installation")
    if not isinstance(installation_reference, Mapping):
        return False
    install_actions = [action for action in actions if action.get("operation") == "install"]
    native_actions = [
        action
        for action in actions
        if isinstance(action.get("provider"), Mapping)
        and action["provider"].get("kind") == "native_plugin"
    ]
    requires_installation = restore.get("restore_class") == "native_rolling" or bool(
        native_actions
    )
    if not requires_installation:
        return installation_reference.get("status") == "not_applicable"
    surface_id = installation_reference.get("surface_id")
    installation = (
        surface_by_identity.get(str(surface_id))
        if installation_reference.get("status") == "captured"
        else None
    )
    if (
        not isinstance(installation, Mapping)
        or installation.get("kind") != "plugin_installation"
        or installation.get("route_id") != route.get("route_id")
        or restore.get("restore_class") != "native_rolling"
    ):
        return False
    observation = installation.get("observation")
    recovery = installation.get("recovery")
    observed_version = restore.get("observed_version")
    if not all(
        isinstance(value, Mapping)
        for value in (observation, recovery, observed_version)
    ):
        return False
    assert isinstance(observation, Mapping)
    assert isinstance(recovery, Mapping)
    assert isinstance(observed_version, Mapping)
    if observed_version.get("status") == "route_absent":
        if observation.get("installed") is not False:
            return False
    elif observed_version.get("status") == "observed":
        if (
            observation.get("installed") is not True
            or observation.get("observed_version") != observed_version.get("value")
            or observation.get("channel") != restore.get("channel")
            or observation.get("observation_source")
            != restore.get("observation_source")
        ):
            return False
    else:
        return False
    if len(install_actions) > 1:
        return False
    if install_actions:
        return (
            observation.get("installed") is False
            and recovery.get("kind") == "native_inverse"
            and recovery.get("inverse_operation") == "remove"
        )
    if observation.get("installed") is False:
        return dict(recovery) == {"kind": "none", "reason": "absent_noop"}
    return dict(recovery) == {
        "kind": "none",
        "reason": (
            "operator_owned"
            if route.get("control_owner") == "operator_owned"
            else "already_desired"
        ),
    }


def _captured_references(route: Mapping[str, object]) -> list[tuple[str, str]]:
    references = route.get("surface_references")
    if not isinstance(references, Mapping):
        raise _InvalidPreparation("captured route references are missing")
    candidates: list[tuple[str, object]] = [
        ("plugin_installation", references.get("installation")),
        ("plugin_enablement", references.get("enablement")),
        ("legacy_projector", references.get("projector")),
    ]
    for expected_kind, slot in (
        ("mcp_selection", "mcp_selections"),
        ("plugin_selection", "plugin_selections"),
        ("claude_skill_entry", "skill_entries"),
        ("canonical_skill_entry", "canonical_skill_dependencies"),
    ):
        members = references.get(slot)
        if not isinstance(members, list):
            raise _InvalidPreparation("captured route reference collection is invalid")
        candidates.extend((expected_kind, member) for member in members)
    captured: list[tuple[str, str]] = []
    for expected_kind, reference in candidates:
        if not isinstance(reference, Mapping):
            raise _InvalidPreparation("captured route reference is invalid")
        if reference.get("status") == "captured":
            surface_id = reference.get("surface_id")
            if not isinstance(surface_id, str):
                raise _InvalidPreparation("captured route reference is dangling")
            captured.append((expected_kind, surface_id))
    return captured


def _capability_set_digest(bindings: Sequence[Mapping[str, object]]) -> str:
    fields = frozenset(
        {
            "capability_identity",
            "capability_digest",
            "manager_version_evidence_digest",
        }
    )
    if not all(frozenset(binding) == fields for binding in bindings):
        raise _InvalidPreparation("capability bindings are not closed")
    records = [dict(binding) for binding in bindings]
    ordered = sorted(
        records,
        key=lambda binding: (
            str(binding["capability_identity"]),
            str(binding["capability_digest"]),
            str(binding["manager_version_evidence_digest"]),
        ),
    )
    identities = [str(binding["capability_identity"]) for binding in records]
    if records != ordered or len(identities) != len(set(identities)):
        raise _InvalidPreparation("capability bindings are not canonical and unique")
    return _digest(records)


def _normalized_component_identities(state: object) -> tuple[str, ...] | None:
    if not isinstance(state, Mapping):
        return None
    components = state.get("component_states")
    if not isinstance(components, list):
        return None
    identities = [
        component.get("equipment_identity")
        for component in components
        if isinstance(component, Mapping)
    ]
    if (
        len(identities) != len(components)
        or any(not isinstance(identity, str) for identity in identities)
        or identities != sorted(set(identities))
    ):
        return None
    return tuple(identities)


def build_gate_manifest(
    *,
    gate_identity: str,
    runtime_identity: str,
    runtime_executable_digest: str,
    files: Mapping[str, bytes],
    schema_documents: Mapping[str, bytes],
) -> bytes:
    """Build the exact installed-manifest input for a protected gate deployment."""

    _require_text(gate_identity)
    _require_text(runtime_identity)
    _require_digest(runtime_executable_digest)
    if not files or not schema_documents:
        raise ValueError("gate file and schema inventories must be nonempty")
    file_records: list[dict[str, object]] = []
    for path, raw in sorted(files.items()):
        if (
            not isinstance(path, str)
            or not path
            or path.startswith("/")
            or ".." in Path(path).parts
            or type(raw) is not bytes
        ):
            raise ValueError("gate manifest path or bytes are invalid")
        file_records.append({"path": path, "digest": _byte_digest(raw)})
    schema_records: list[dict[str, object]] = []
    for name, raw in sorted(schema_documents.items()):
        if (
            not isinstance(name, str)
            or not name
            or "/" in name
            or type(raw) is not bytes
        ):
            raise ValueError("gate schema name or bytes are invalid")
        _schema_validator(raw)
        schema_records.append({"name": name, "digest": _byte_digest(raw)})
    value: dict[str, object] = {
        "schema_version": "agent-equipment-preparation-gate-manifest/v1",
        "gate_identity": gate_identity,
        "runtime_identity": runtime_identity,
        "runtime_executable_digest": runtime_executable_digest,
        "files": file_records,
        "schema_digests": schema_records,
        "manifest_digest": "sha256:" + "0" * 64,
    }
    payload = copy.deepcopy(value)
    payload.pop("manifest_digest")
    value["manifest_digest"] = _digest(payload)
    return _canonical_bytes(value)


def build_adapter_manifest(
    *,
    adapter_identity: str,
    adapter_version: str,
    implementation_identity: str,
    implementation_manifest_digest: str,
    capability_binding: Mapping[str, object],
) -> bytes:
    """Build one closed manifest for an independently measured adapter."""

    _require_text(adapter_identity)
    _require_text(adapter_version)
    _require_text(implementation_identity)
    _require_digest(implementation_manifest_digest)
    binding = copy.deepcopy(dict(capability_binding))
    _require_closed(
        binding,
        frozenset(
            {
                "capability_identity",
                "capability_digest",
                "manager_version_evidence_digest",
            }
        ),
    )
    _require_text(binding.get("capability_identity"))
    _require_digest(binding.get("capability_digest"))
    _require_digest(binding.get("manager_version_evidence_digest"))
    value: dict[str, object] = {
        "adapter_manifest_identity": (
            "preparation-adapter-manifest:sha256:" + "0" * 64
        ),
        "adapter_identity": adapter_identity,
        "adapter_version": adapter_version,
        "adapter_implementation_identity": implementation_identity,
        "adapter_implementation_manifest_digest": implementation_manifest_digest,
        "capability_binding": binding,
        "prepare_seam": {
            "entrypoint": "prepare",
            "effect": "read_only",
            "request_record": "PrepareRequest",
            "response_record": "PreparedStateFacts",
        },
        "adapter_manifest_digest": "sha256:" + "0" * 64,
    }
    _seal_record(
        value,
        identity_field="adapter_manifest_identity",
        identity_prefix="preparation-adapter-manifest:",
        digest_field="adapter_manifest_digest",
    )
    return _canonical_bytes(value)


def build_adapter_manifest_set(manifest_documents: Sequence[bytes]) -> bytes:
    """Build the canonical set of exact preparation adapter manifests."""

    manifests = [
        PreparationGate._validate_adapter_manifest(raw) for raw in manifest_documents
    ]
    identities = [str(manifest["adapter_manifest_identity"]) for manifest in manifests]
    if len(identities) != len(set(identities)):
        raise ValueError("adapter manifest set contains duplicates")
    return _canonical_bytes(PreparationGate._adapter_manifest_set(manifests))


@dataclass(frozen=True, slots=True)
class PreparationTrust:
    """Exact independently supplied bindings for one preparation."""

    expected_candidate_identity: str
    expected_implementation_manifest_digest: str
    expected_plan_digest: str
    expected_plan_action_set_digest: str
    expected_captured_state_identity: str
    expected_captured_state_digest: str
    expected_capability_set_digest: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@runtime_checkable
class PreparationAdapter(Protocol):
    """The only adapter capability visible to the preparation gate."""

    def prepare(self, request_bytes: bytes) -> bytes: ...


@dataclass(frozen=True, slots=True)
class BoundPreparationAdapter:
    """Deployment-attested manifest plus a prepare-only object capability."""

    manifest_bytes: bytes
    adapter: PreparationAdapter


@dataclass(frozen=True)
class VerifiedPreparationNoOp:
    plan_action_set_digest: str
    status: str = "verified_noop"


@dataclass(frozen=True)
class PreparationRejection:
    code: str
    message: str


@dataclass(frozen=True)
class PreparedBundleCommit:
    bundle_bytes: bytes
    receipt_bytes: bytes
    reused: bool = False


@dataclass(frozen=True)
class ResolvedPreparation:
    bundle_bytes: bytes
    receipt_bytes: bytes


class FilePreparationStore:
    """Descriptor-held, create-only store for complete bundle envelopes."""

    def __init__(self, root: Path, *, store_identity: str) -> None:
        self._root = Path(root)
        self.store_identity = _require_text(store_identity)
        # A durability failure after link is deliberately uncertain. The caller
        # receives no receipt and must resolve before retrying.
        try:
            self._directory_fd = os.open(
                self._root,
                os.O_RDONLY
                | os.O_DIRECTORY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
        except OSError as error:
            raise ValueError(
                "preparation store root must already be provisioned"
            ) from error
        metadata = os.fstat(self._directory_fd)
        if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
            os.close(self._directory_fd)
            self._directory_fd = -1
            raise ValueError("preparation store root is not owner-protected")

    def __del__(self) -> None:
        descriptor = getattr(self, "_directory_fd", None)
        if isinstance(descriptor, int):
            try:
                os.close(descriptor)
            except OSError:
                pass
            self._directory_fd = -1

    @staticmethod
    def _entry_name(bundle_digest: str) -> str:
        _require_digest(bundle_digest)
        return bundle_digest.removeprefix("sha256:") + ".json"

    def entry_count(self) -> int:
        return sum(
            1 for name in os.listdir(self._directory_fd) if name.endswith(".json")
        )

    def _read_entry(self, name: str) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(name, flags, dir_fd=self._directory_fd)
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size > _MAX_STORE_ENTRY_BYTES
            ):
                raise _InvalidPreparation("invalid store entry")
            chunks: list[bytes] = []
            remaining = metadata.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    raise _InvalidPreparation("truncated store entry")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise _InvalidPreparation("store entry changed while read")
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    def commit(
        self,
        bundle_bytes: bytes,
        *,
        preparation_gate_identity: str,
        preparation_gate_manifest_digest: str,
    ) -> PreparedBundleCommit:
        bundle = _parse_exact_object(
            bundle_bytes,
            maximum_bytes=_MAX_STORE_ENTRY_BYTES,
        )
        bundle_digest = _require_digest(bundle.get("preparation_bundle_digest"))
        bundle_identity = _require_text(bundle.get("preparation_bundle_identity"))
        _verify_sealed_record(
            bundle,
            identity_field="preparation_bundle_identity",
            identity_prefix="preparation-bundle:",
            digest_field="preparation_bundle_digest",
        )
        bindings = bundle.get("bindings")
        if not isinstance(bindings, Mapping):
            raise _InvalidPreparation("bundle store or gate binding is missing")
        if (
            bindings.get("store_identity") != self.store_identity
            or bindings.get("store_generation") != 1
        ):
            raise _InvalidPreparation("bundle names another preparation store")
        if (
            bindings.get("preparation_gate_identity") != preparation_gate_identity
            or bindings.get("preparation_gate_manifest_digest")
            != preparation_gate_manifest_digest
        ):
            raise _InvalidPreparation("bundle gate binding mismatch")
        payload: dict[str, object] = {
            "outcome": "committed",
            "preparation_bundle_identity": bundle_identity,
            "preparation_bundle_digest": bundle_digest,
            "preparation_bundle_bytes_digest": _byte_digest(bundle_bytes),
            "preparation_gate_identity": _require_text(preparation_gate_identity),
            "preparation_gate_manifest_digest": _require_digest(
                preparation_gate_manifest_digest
            ),
            "store_identity": self.store_identity,
            "store_generation": 1,
        }
        receipt: dict[str, object] = {
            "schema_version": "agent-equipment-preparation-receipt/v1",
            "receipt_identity": "preparation-receipt:" + _digest(payload),
            "payload": payload,
        }
        receipt_bytes = _canonical_bytes(receipt)
        envelope = {
            "schema_version": "agent-equipment-preparation-store-entry/v1",
            "bundle_bytes_base64": base64.b64encode(bundle_bytes).decode("ascii"),
            "bundle_bytes_digest": _byte_digest(bundle_bytes),
            "receipt_bytes_base64": base64.b64encode(receipt_bytes).decode("ascii"),
            "receipt_bytes_digest": _byte_digest(receipt_bytes),
        }
        envelope_bytes = _canonical_bytes(envelope)
        if len(envelope_bytes) > _MAX_STORE_ENTRY_BYTES:
            raise _InvalidPreparation("store entry exceeds size limit")
        final_name = self._entry_name(bundle_digest)
        temporary_name = f".{final_name}.{os.getpid()}.{id(envelope)}.tmp"
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor: int | None = None
        linked = False
        try:
            descriptor = os.open(
                temporary_name, flags, 0o600, dir_fd=self._directory_fd
            )
            view = memoryview(envelope_bytes)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short store write")
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            try:
                os.link(
                    temporary_name,
                    final_name,
                    src_dir_fd=self._directory_fd,
                    dst_dir_fd=self._directory_fd,
                    follow_symlinks=False,
                )
                linked = True
            except FileExistsError:
                if self._read_entry(final_name) != envelope_bytes:
                    raise _InvalidPreparation("content-addressed store collision")
            os.fsync(self._directory_fd)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary_name, dir_fd=self._directory_fd)
            except FileNotFoundError:
                pass
        return PreparedBundleCommit(
            bundle_bytes=bundle_bytes,
            receipt_bytes=receipt_bytes,
            reused=not linked,
        )

    def resolve_receipt(self, receipt_bytes: bytes) -> ResolvedPreparation | None:
        try:
            receipt = _parse_exact_object(
                receipt_bytes,
                maximum_bytes=_MAX_INPUT_BYTES,
            )
            _require_closed(
                receipt,
                frozenset(
                    {
                        "schema_version",
                        "receipt_identity",
                        "payload",
                    }
                ),
            )
            if receipt["schema_version"] != "agent-equipment-preparation-receipt/v1":
                raise _InvalidPreparation("unsupported receipt version")
            payload = receipt.get("payload")
            if not isinstance(payload, Mapping):
                raise _InvalidPreparation("invalid receipt payload")
            _require_closed(
                payload,
                frozenset(
                    {
                        "outcome",
                        "preparation_bundle_identity",
                        "preparation_bundle_digest",
                        "preparation_bundle_bytes_digest",
                        "preparation_gate_identity",
                        "preparation_gate_manifest_digest",
                        "store_identity",
                        "store_generation",
                    }
                ),
            )
            if (
                payload.get("outcome") != "committed"
                or payload.get("store_identity") != self.store_identity
                or payload.get("store_generation") != 1
                or receipt.get("receipt_identity")
                != "preparation-receipt:" + _digest(payload)
            ):
                raise _InvalidPreparation("receipt names another store")
            bundle_digest = _require_digest(payload.get("preparation_bundle_digest"))
            envelope_bytes = self._read_entry(self._entry_name(bundle_digest))
            envelope = _parse_exact_object(
                envelope_bytes,
                maximum_bytes=_MAX_STORE_ENTRY_BYTES,
            )
            _require_closed(
                envelope,
                frozenset(
                    {
                        "schema_version",
                        "bundle_bytes_base64",
                        "bundle_bytes_digest",
                        "receipt_bytes_base64",
                        "receipt_bytes_digest",
                    }
                ),
            )
            if (
                envelope["schema_version"]
                != "agent-equipment-preparation-store-entry/v1"
            ):
                raise _InvalidPreparation("unsupported store entry version")
            stored_bundle = base64.b64decode(
                str(envelope["bundle_bytes_base64"]),
                validate=True,
            )
            stored_receipt = base64.b64decode(
                str(envelope["receipt_bytes_base64"]),
                validate=True,
            )
            if (
                stored_receipt != receipt_bytes
                or envelope["receipt_bytes_digest"] != _byte_digest(stored_receipt)
                or envelope["bundle_bytes_digest"] != _byte_digest(stored_bundle)
                or _byte_digest(stored_bundle)
                != payload.get("preparation_bundle_bytes_digest")
            ):
                raise _InvalidPreparation(
                    "stored preparation bytes do not match receipt"
                )
            bundle = _parse_exact_object(
                stored_bundle,
                maximum_bytes=_MAX_STORE_ENTRY_BYTES,
            )
            _verify_sealed_record(
                bundle,
                identity_field="preparation_bundle_identity",
                identity_prefix="preparation-bundle:",
                digest_field="preparation_bundle_digest",
            )
            if (
                bundle.get("preparation_bundle_identity")
                != payload.get("preparation_bundle_identity")
                or bundle.get("preparation_bundle_digest") != bundle_digest
            ):
                raise _InvalidPreparation("stored bundle tuple does not match receipt")
            return ResolvedPreparation(
                bundle_bytes=stored_bundle,
                receipt_bytes=stored_receipt,
            )
        except (OSError, ValueError, TypeError, KeyError, binascii.Error):
            return None


class PreparationGate:
    """Prebound, candidate-independent production gate."""

    def __init__(
        self,
        *,
        gate_manifest_bytes: bytes,
        expected_gate_manifest_digest: str,
        schema_documents: Mapping[str, bytes],
        adapters: Sequence[BoundPreparationAdapter],
        expected_adapter_manifest_set_digest: str,
        store: FilePreparationStore,
    ) -> None:
        schema_items = tuple(schema_documents.items())
        if (
            not schema_items
            or any(
                type(name) is not str or type(raw_schema) is not bytes
                for name, raw_schema in schema_items
            )
            or len({name for name, _ in schema_items}) != len(schema_items)
        ):
            raise _InvalidPreparation("schema document set is not exact")
        schema_snapshot = dict(schema_items)
        self._schema_roots: dict[str, dict[str, object]] = {}
        self._validators: dict[str, Draft202012Validator] = {}
        for name, raw_schema in schema_snapshot.items():
            schema, validator = _schema_validator(raw_schema)
            self._schema_roots[name] = schema
            self._validators[name] = validator
        self._gate_manifest_bytes = gate_manifest_bytes
        self._gate_manifest = self._validate_gate_manifest(
            gate_manifest_bytes,
            expected_gate_manifest_digest,
            schema_snapshot,
        )
        self._validate_definition(
            "adapter-contract-v1.schema.json",
            "gateManifest",
            self._gate_manifest,
        )
        if type(store) is not FilePreparationStore:
            raise _InvalidPreparation("preparation store must be the protected store")
        self._store_identity = store.store_identity
        self._store_commit = store.commit
        self._store_resolve_receipt = store.resolve_receipt
        self._adapters: dict[
            tuple[str, str, str, str, str],
            tuple[dict[str, object], Callable[[bytes], bytes]],
        ] = {}
        manifest_documents: list[dict[str, object]] = []
        for binding in adapters:
            if type(binding) is not BoundPreparationAdapter:
                raise _InvalidPreparation("adapter binding is not exact")
            manifest = self._validate_adapter_manifest(binding.manifest_bytes)
            self._validate_definition(
                "adapter-contract-v1.schema.json",
                "adapterManifest",
                manifest,
            )
            if not isinstance(binding.adapter, PreparationAdapter):
                raise _InvalidPreparation("bound adapter lacks prepare")
            if self._public_adapter_callables(binding.adapter) != {"prepare"}:
                raise _InvalidPreparation(
                    "bound adapter is not a prepare-only object capability"
                )
            capability = manifest["capability_binding"]
            assert isinstance(capability, Mapping)
            key = (
                str(manifest["adapter_identity"]),
                str(manifest["adapter_version"]),
                str(capability["capability_identity"]),
                str(capability["capability_digest"]),
                str(capability["manager_version_evidence_digest"]),
            )
            if key in self._adapters:
                raise _InvalidPreparation("duplicate adapter binding")
            prepare_call = binding.adapter.prepare
            if not callable(prepare_call):
                raise _InvalidPreparation("bound adapter prepare seam is not callable")
            self._adapters[key] = (manifest, prepare_call)
            manifest_documents.append(manifest)
        manifest_set = self._adapter_manifest_set(manifest_documents)
        if (
            manifest_set["adapter_manifest_set_digest"]
            != expected_adapter_manifest_set_digest
        ):
            raise _InvalidPreparation(
                "adapter manifest set does not match trusted digest"
            )
        if manifest_documents:
            self._validate_definition(
                "adapter-contract-v1.schema.json",
                "adapterManifestSet",
                manifest_set,
            )
        self._adapter_manifest_set = manifest_set
        self._adapter_manifest_set_bytes = _canonical_bytes(manifest_set)

    @staticmethod
    def _public_adapter_callables(adapter: object) -> set[str]:
        callables: set[str] = set()
        for adapter_type in type(adapter).__mro__:
            for name, member in vars(adapter_type).items():
                if not name.startswith("_") and callable(member):
                    callables.add(name)
        try:
            instance_members = object.__getattribute__(adapter, "__dict__")
        except (AttributeError, TypeError):
            instance_members = {}
        if isinstance(instance_members, Mapping):
            callables.update(
                name
                for name, member in instance_members.items()
                if not name.startswith("_") and callable(member)
            )
        return callables

    def _validate_definition(
        self,
        schema_name: str,
        definition: str,
        value: object,
    ) -> None:
        schema = self._schema_roots.get(schema_name)
        if schema is None:
            raise _InvalidPreparation("required schema is missing")
        validator = _schema_definition_validator(schema, definition)
        if not validator.is_valid(value):
            raise _InvalidPreparation("schema definition validation failed")

    @staticmethod
    def _validate_gate_manifest(
        raw: bytes,
        expected_digest: str,
        schemas: Mapping[str, bytes],
    ) -> dict[str, object]:
        manifest = _parse_exact_object(raw, maximum_bytes=_MAX_INPUT_BYTES)
        _require_closed(
            manifest,
            frozenset(
                {
                    "schema_version",
                    "gate_identity",
                    "runtime_identity",
                    "runtime_executable_digest",
                    "files",
                    "schema_digests",
                    "manifest_digest",
                }
            ),
        )
        if manifest["schema_version"] != "agent-equipment-preparation-gate-manifest/v1":
            raise _InvalidPreparation("unsupported gate manifest version")
        if _contains_literal_secret(manifest):
            raise _InvalidPreparation(
                "gate manifest contains literal credential material"
            )
        if manifest.get("manifest_digest") != _require_digest(expected_digest):
            raise _InvalidPreparation("gate manifest trust mismatch")
        payload = copy.deepcopy(manifest)
        payload.pop("manifest_digest", None)
        if manifest["manifest_digest"] != _digest(payload):
            raise _InvalidPreparation("gate manifest digest mismatch")
        _require_text(manifest.get("gate_identity"))
        _require_text(manifest.get("runtime_identity"))
        _require_digest(manifest.get("runtime_executable_digest"))
        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            raise _InvalidPreparation("gate manifest file inventory is empty")
        file_paths: list[str] = []
        for file_record in files:
            if not isinstance(file_record, Mapping):
                raise _InvalidPreparation("invalid gate file record")
            _require_closed(file_record, frozenset({"path", "digest"}))
            file_paths.append(_require_text(file_record.get("path")))
            _require_digest(file_record.get("digest"))
        if file_paths != sorted(set(file_paths)):
            raise _InvalidPreparation("gate file inventory is not a sorted set")
        schema_records = manifest.get("schema_digests")
        if not isinstance(schema_records, list):
            raise _InvalidPreparation("invalid schema inventory")
        expected_schema_records = [
            {"name": name, "digest": _byte_digest(raw_schema)}
            for name, raw_schema in sorted(schemas.items())
        ]
        if schema_records != expected_schema_records:
            raise _InvalidPreparation("schema inventory does not match exact bytes")
        return manifest

    @staticmethod
    def _validate_adapter_manifest(raw: bytes) -> dict[str, object]:
        manifest = _parse_exact_object(raw, maximum_bytes=_MAX_INPUT_BYTES)
        _require_closed(
            manifest,
            frozenset(
                {
                    "adapter_manifest_identity",
                    "adapter_identity",
                    "adapter_version",
                    "adapter_implementation_identity",
                    "adapter_implementation_manifest_digest",
                    "capability_binding",
                    "prepare_seam",
                    "adapter_manifest_digest",
                }
            ),
        )
        if manifest.get("prepare_seam") != {
            "entrypoint": "prepare",
            "effect": "read_only",
            "request_record": "PrepareRequest",
            "response_record": "PreparedStateFacts",
        }:
            raise _InvalidPreparation("unsupported preparation adapter manifest")
        if _contains_literal_secret(manifest):
            raise _InvalidPreparation(
                "adapter manifest contains literal credential material"
            )
        _verify_sealed_record(
            manifest,
            identity_field="adapter_manifest_identity",
            identity_prefix="preparation-adapter-manifest:",
            digest_field="adapter_manifest_digest",
        )
        for field in (
            "adapter_identity",
            "adapter_version",
            "adapter_implementation_identity",
        ):
            _require_text(manifest.get(field))
        _require_digest(manifest.get("adapter_implementation_manifest_digest"))
        capability = manifest.get("capability_binding")
        if not isinstance(capability, Mapping):
            raise _InvalidPreparation("invalid adapter capability binding")
        _require_closed(
            capability,
            frozenset(
                {
                    "capability_identity",
                    "capability_digest",
                    "manager_version_evidence_digest",
                }
            ),
        )
        _require_text(capability.get("capability_identity"))
        _require_digest(capability.get("capability_digest"))
        _require_digest(capability.get("manager_version_evidence_digest"))
        return manifest

    @staticmethod
    def _adapter_manifest_set(
        manifests: Sequence[dict[str, object]],
    ) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": "agent-equipment-preparation-adapter-manifest-set/v1",
            "adapter_manifest_set_identity": (
                "preparation-adapter-manifest-set:sha256:" + "0" * 64
            ),
            "manifests": sorted(
                (copy.deepcopy(manifest) for manifest in manifests),
                key=lambda manifest: str(manifest["adapter_manifest_identity"]),
            ),
            "adapter_manifest_set_digest": "sha256:" + "0" * 64,
        }
        _seal_record(
            value,
            identity_field="adapter_manifest_set_identity",
            identity_prefix="preparation-adapter-manifest-set:",
            digest_field="adapter_manifest_set_digest",
        )
        return value

    def prepare(
        self,
        plan_action_set_bytes: bytes,
        captured_state_bytes: bytes,
        trust: PreparationTrust,
        *,
        reuse_receipt_bytes: bytes | None = None,
    ) -> VerifiedPreparationNoOp | PreparationRejection | PreparedBundleCommit:
        try:
            if type(trust) is not PreparationTrust:
                raise _InvalidPreparation("preparation trust must be exact")
            trusted = PreparationTrust(
                expected_candidate_identity=trust.expected_candidate_identity,
                expected_implementation_manifest_digest=(
                    trust.expected_implementation_manifest_digest
                ),
                expected_plan_digest=trust.expected_plan_digest,
                expected_plan_action_set_digest=(
                    trust.expected_plan_action_set_digest
                ),
                expected_captured_state_identity=trust.expected_captured_state_identity,
                expected_captured_state_digest=trust.expected_captured_state_digest,
                expected_capability_set_digest=trust.expected_capability_set_digest,
            )
            plan, capture, action_contexts = self._static_preflight(
                plan_action_set_bytes,
                captured_state_bytes,
                trusted,
            )
            actions = plan["actions"]
            assert isinstance(actions, list)
            if not actions:
                if reuse_receipt_bytes is not None:
                    raise _InvalidPreparation("empty plans cannot reuse authority")
                return VerifiedPreparationNoOp(trusted.expected_plan_action_set_digest)
            if reuse_receipt_bytes is not None:
                resolved = self._store_resolve_receipt(reuse_receipt_bytes)
                if resolved is None:
                    raise _InvalidPreparation(
                        "preparation receipt could not be resolved"
                    )
                self._validate_reused_bundle(
                    resolved.bundle_bytes,
                    plan_action_set_bytes,
                    captured_state_bytes,
                    trusted,
                )
                return PreparedBundleCommit(
                    bundle_bytes=resolved.bundle_bytes,
                    receipt_bytes=resolved.receipt_bytes,
                    reused=True,
                )
            facts = [
                self._prepare_action(context, trusted, captured_state_bytes)
                for context in action_contexts
            ]
            capture_set = self._capture_authority_set(plan, capture, facts, trusted)
            prepared_set = self._prepared_authority_set(
                plan,
                capture,
                facts,
                capture_set,
                trusted,
            )
            bundle_bytes = self._bundle_bytes(
                plan_action_set_bytes,
                captured_state_bytes,
                capture,
                capture_set,
                prepared_set,
                trusted,
            )
            commit = self._store_commit(
                bundle_bytes,
                preparation_gate_identity=str(self._gate_manifest["gate_identity"]),
                preparation_gate_manifest_digest=str(
                    self._gate_manifest["manifest_digest"]
                ),
            )
            receipt = _parse_exact_object(
                commit.receipt_bytes,
                maximum_bytes=_MAX_INPUT_BYTES,
            )
            self._validate_definition(
                "execution-authority-v1.schema.json",
                "preparationReceipt",
                receipt,
            )
            return commit
        except Exception:  # noqa: BLE001 - external seams always fail closed.
            return PreparationRejection(
                code="PREPARATION_REJECTED",
                message="preparation failed closed",
            )

    def _static_preflight(
        self,
        plan_bytes: bytes,
        capture_bytes: bytes,
        trust: PreparationTrust,
    ) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
        for field, value in trust.as_dict().items():
            if field.endswith("_digest"):
                _require_digest(value)
            else:
                _require_text(value)
        plan = _parse_exact_object(plan_bytes, maximum_bytes=_MAX_INPUT_BYTES)
        capture = _parse_exact_object(capture_bytes, maximum_bytes=_MAX_INPUT_BYTES)
        _validate_schema(self._validators, "plan-action-set-v1.schema.json", plan)
        actions = plan.get("actions")
        if not isinstance(actions, list):
            raise _InvalidPreparation("plan actions must be an array")
        if len(actions) > _MAX_ACTIONS:
            raise _InvalidPreparation("plan has too many actions")
        # The existing captured-state contract describes one or more affected
        # routes.  A verified empty plan has no affected route and therefore
        # terminates after exact binding checks, without manufacturing an
        # otherwise meaningless captured-state artifact.
        if actions:
            _validate_schema(self._validators, "captured-state-v1.schema.json", capture)
        if _contains_literal_secret(plan) or _contains_literal_secret(capture):
            raise _InvalidPreparation("literal credential material is forbidden")
        if (
            plan.get("candidate_identity") != trust.expected_candidate_identity
            or plan.get("implementation_manifest_digest")
            != trust.expected_implementation_manifest_digest
            or plan.get("plan_digest") != trust.expected_plan_digest
            or plan.get("action_set_digest") != trust.expected_plan_action_set_digest
            or _plan_action_set_digest(plan) != trust.expected_plan_action_set_digest
            or _byte_digest(capture_bytes) != trust.expected_captured_state_digest
        ):
            raise _InvalidPreparation("trusted preparation binding mismatch")
        bindings = capture.get("bindings")
        if not isinstance(bindings, Mapping):
            raise _InvalidPreparation("captured state bindings are missing")
        capability_bindings = bindings.get("capability_bindings")
        if not isinstance(capability_bindings, list):
            raise _InvalidPreparation("captured capability bindings are missing")
        if (
            bindings.get("candidate_identity") != trust.expected_candidate_identity
            or bindings.get("implementation_manifest_digest")
            != trust.expected_implementation_manifest_digest
            or bindings.get("plan_digest") != trust.expected_plan_digest
            or bindings.get("plan_action_set_digest")
            != trust.expected_plan_action_set_digest
            or bindings.get("capability_set_digest")
            != trust.expected_capability_set_digest
            or _capability_set_digest(capability_bindings)
            != trust.expected_capability_set_digest
        ):
            raise _InvalidPreparation("captured binding mismatch")
        contexts = self._action_contexts(plan, capture, trust)
        captured_capabilities = {
            (
                str(binding["capability_identity"]),
                str(binding["capability_digest"]),
                str(binding["manager_version_evidence_digest"]),
            )
            for binding in capability_bindings
        }
        used_capabilities = {
            (
                str(context["action"]["capability_identity"]),
                str(context["action"]["capability_digest"]),
                str(context["action"]["manager_version_evidence_digest"]),
            )
            for context in contexts
        }
        if not used_capabilities.issubset(captured_capabilities):
            raise _InvalidPreparation("planned capability is not captured")
        used_manifest_identities = {
            str(context["adapter_manifest"]["adapter_manifest_identity"])
            for context in contexts
        }
        all_manifest_identities = {
            str(manifest["adapter_manifest_identity"])
            for manifest, _ in self._adapters.values()
        }
        if used_manifest_identities != all_manifest_identities:
            raise _InvalidPreparation("adapter manifest set is not exact for this plan")
        return plan, capture, contexts

    def _action_contexts(
        self,
        plan: Mapping[str, object],
        capture: Mapping[str, object],
        trust: PreparationTrust,
    ) -> list[dict[str, object]]:
        actions = plan.get("actions")
        routes = capture.get("provider_routes")
        surfaces = capture.get("surfaces")
        if (
            not isinstance(actions, list)
            or not isinstance(routes, list)
            or not isinstance(surfaces, list)
        ):
            raise _InvalidPreparation("invalid preparation collections")
        route_by_identity = {
            route["route_id"]: route for route in routes if isinstance(route, Mapping)
        }
        surface_by_identity = {
            surface["surface_id"]: surface
            for surface in surfaces
            if isinstance(surface, Mapping)
        }
        if len(route_by_identity) != len(routes) or len(surface_by_identity) != len(
            surfaces
        ):
            raise _InvalidPreparation("duplicate captured identity")

        logical_surface_keys: set[tuple[str, str, str, bytes]] = set()
        mutable_physical_keys: set[tuple[str, bytes]] = set()
        for surface in surfaces:
            assert isinstance(surface, Mapping)
            locator = surface.get("locator")
            if not isinstance(locator, Mapping):
                raise _InvalidPreparation("captured surface locator is invalid")
            logical_key = (
                str(surface.get("kind")),
                str(surface.get("route_id", "")),
                str(surface.get("equipment_identity", "")),
                _canonical_bytes(locator),
            )
            if logical_key in logical_surface_keys:
                raise _InvalidPreparation("duplicate captured logical surface")
            logical_surface_keys.add(logical_key)
            if surface.get("mutation_policy") != "forbidden":
                physical_key = (str(surface.get("kind")), _canonical_bytes(locator))
                if physical_key in mutable_physical_keys:
                    raise _InvalidPreparation("duplicate captured mutable surface")
                mutable_physical_keys.add(physical_key)

        reference_counts: dict[str, int] = {}
        for route in routes:
            assert isinstance(route, Mapping)
            route_id = route.get("route_id")
            planned_actions = route.get("planned_actions")
            if not isinstance(route_id, str) or not isinstance(planned_actions, list):
                raise _InvalidPreparation("captured route is invalid")
            if route.get("control_owner") == "reconciler_owned" and not planned_actions:
                raise _InvalidPreparation("reconciler-owned route has no action owner")
            for expected_kind, surface_id in _captured_references(route):
                surface = surface_by_identity.get(surface_id)
                if (
                    surface is None
                    or surface.get("kind") != expected_kind
                    or surface.get("route_id") != route_id
                    or reference_counts.get(surface_id, 0) != 0
                ):
                    raise _InvalidPreparation("captured route surface reference mismatch")
                reference_counts[surface_id] = 1

        for surface in surfaces:
            assert isinstance(surface, Mapping)
            if not _captured_surface_recovery_is_valid(surface):
                raise _InvalidPreparation("captured surface recovery is incoherent")
            surface_id = str(surface["surface_id"])
            route_id = surface.get("route_id")
            if route_id is None:
                continue
            route = route_by_identity.get(route_id)
            if route is None:
                raise _InvalidPreparation("captured surface route is unknown")
            equipment = surface.get("equipment_identity")
            route_equipment = set(route.get("equipment_identities", [])) | set(
                route.get("controlled_equipment_identities", [])
            )
            if equipment is not None and equipment not in route_equipment:
                raise _InvalidPreparation("captured surface equipment is foreign")
            if (
                surface.get("kind") != "canonical_skill_entry"
                and surface.get("mutation_policy") != route.get("control_owner")
            ):
                raise _InvalidPreparation("captured surface ownership mismatch")
            if (
                surface.get("mutation_policy") != "forbidden"
                and reference_counts.get(surface_id, 0) != 1
            ):
                raise _InvalidPreparation("mutable captured surface is orphaned")

        action_by_reference: dict[
            tuple[str, str], tuple[Mapping[str, object], Mapping[str, object]]
        ] = {}
        for evidence in actions:
            if not isinstance(evidence, Mapping) or not isinstance(
                evidence.get("action_payload"), Mapping
            ):
                raise _InvalidPreparation("invalid planned action evidence")
            action = evidence["action_payload"]
            assert isinstance(action, Mapping)
            reference_key = (
                str(action.get("action_identity")),
                str(evidence.get("action_digest")),
            )
            if reference_key in action_by_reference:
                raise _InvalidPreparation("duplicate planned action reference")
            action_by_reference[reference_key] = (evidence, action)

        reference_by_action: dict[str, Mapping[str, object]] = {}
        actions_by_route: dict[str, list[Mapping[str, object]]] = {}
        seen_action_references: set[tuple[str, str]] = set()
        for route in routes:
            assert isinstance(route, Mapping)
            planned_actions = route.get("planned_actions")
            assert isinstance(planned_actions, list)
            for reference in planned_actions:
                if not isinstance(reference, Mapping):
                    raise _InvalidPreparation("captured action reference is invalid")
                reference_key = (
                    str(reference.get("action_identity")),
                    str(reference.get("action_digest")),
                )
                resolved = action_by_reference.get(reference_key)
                if (
                    resolved is None
                    or reference_key in seen_action_references
                    or resolved[1].get("route_identity") != route.get("route_id")
                ):
                    raise _InvalidPreparation("captured action ownership is not exact")
                seen_action_references.add(reference_key)
                reference_by_action[reference_key[0]] = reference
                actions_by_route.setdefault(str(route.get("route_id")), []).append(
                    resolved[1]
                )
        if seen_action_references != set(action_by_reference):
            raise _InvalidPreparation("planned action capture coverage is incomplete")
        for route in routes:
            assert isinstance(route, Mapping)
            if not _native_route_capture_is_coherent(
                route,
                surface_by_identity,
                actions_by_route.get(str(route.get("route_id")), []),
            ):
                raise _InvalidPreparation("captured native route is incoherent")

        contexts: list[dict[str, object]] = []
        expected_ordinals = list(range(len(actions)))
        actual_ordinals: list[int] = []
        write_surface_counts: dict[str, int] = {}
        dependency_surface_counts: dict[str, int] = {}
        capture_bindings = capture.get("bindings")
        if not isinstance(capture_bindings, Mapping):
            raise _InvalidPreparation("captured bindings are missing")
        for evidence in actions:
            if not isinstance(evidence, Mapping) or not isinstance(
                evidence.get("action_payload"), Mapping
            ):
                raise _InvalidPreparation("invalid planned action evidence")
            action = evidence["action_payload"]
            assert isinstance(action, Mapping)
            ordinal = action.get("ordinal")
            if not isinstance(ordinal, int) or isinstance(ordinal, bool):
                raise _InvalidPreparation("invalid planned ordinal")
            actual_ordinals.append(ordinal)
            if (
                evidence.get("action_digest") != _digest(action)
                or action.get("action_identity") != _plan_action_identity(action)
                or action.get("desired_state_digest")
                != _digest(action.get("desired_state"))
                or action.get("candidate_identity") != trust.expected_candidate_identity
                or action.get("implementation_manifest_digest")
                != trust.expected_implementation_manifest_digest
                or action.get("plan_digest") != trust.expected_plan_digest
                or action.get("catalog_digest")
                != capture_bindings.get("catalog_digest")
                or action.get("lock_digest") != capture_bindings.get("lock_digest")
                or not _plan_action_graph_is_closed(action)
                or not _desired_state_matches_action(action)
                or not _secret_references_match(action)
            ):
                raise _InvalidPreparation("invalid planned action binding")
            expected_preconditions = {
                "catalog_digest": capture_bindings.get("catalog_digest"),
                "lock_digest": capture_bindings.get("lock_digest"),
                "plan_digest": trust.expected_plan_digest,
                "route_digest": action.get("route_digest"),
                "candidate_identity": trust.expected_candidate_identity,
                "implementation_manifest_digest": (
                    trust.expected_implementation_manifest_digest
                ),
                "capability_digest": action.get("capability_digest"),
                "manager_version_evidence_digest": action.get(
                    "manager_version_evidence_digest"
                ),
                "adapter_identity": action.get("adapter_identity"),
                "adapter_version": action.get("adapter_version"),
                "control_owner": "reconciler_owned",
                "activation_group": action.get("activation_group"),
                "surface_scope": action.get("surface_scope"),
                "prepared_checkpoint_required": True,
                "compare_before_mutate": True,
            }
            if action.get("preconditions") != expected_preconditions:
                raise _InvalidPreparation("planned action preconditions are not exact")
            capability_key = (
                str(action.get("adapter_identity")),
                str(action.get("adapter_version")),
                str(action.get("capability_identity")),
                str(action.get("capability_digest")),
                str(action.get("manager_version_evidence_digest")),
            )
            adapter_binding = self._adapters.get(capability_key)
            if adapter_binding is None:
                raise _InvalidPreparation("planned adapter is not manifest-bound")
            route = route_by_identity.get(action.get("route_identity"))
            if not isinstance(route, Mapping):
                raise _InvalidPreparation("planned route is not captured")
            if (
                route.get("route_digest") != action.get("route_digest")
                or route.get("capability_binding")
                != {
                    "capability_identity": action.get("capability_identity"),
                    "capability_digest": action.get("capability_digest"),
                    "manager_version_evidence_digest": action.get(
                        "manager_version_evidence_digest"
                    ),
                }
                or route.get("harness") != action.get("harness")
                or route.get("control_owner") != "reconciler_owned"
                or route.get("equipment_identities")
                != action.get("equipment_identities")
                or route.get("controlled_equipment_identities")
                != action.get("controlled_equipment_identities")
            ):
                raise _InvalidPreparation("captured route binding mismatch")
            reference = reference_by_action.get(str(action.get("action_identity")))
            if reference is None or reference.get("action_digest") != evidence.get(
                "action_digest"
            ):
                raise _InvalidPreparation("captured action reference mismatch")

            targets = action.get("write_targets")
            dependencies = action.get("verification_dependencies")
            write_bindings = reference.get("write_bindings")
            dependency_bindings = reference.get("verification_dependency_bindings")
            if (
                not isinstance(targets, list)
                or not isinstance(dependencies, list)
                or not isinstance(write_bindings, list)
                or not isinstance(dependency_bindings, list)
            ):
                raise _InvalidPreparation("captured projection binding missing")
            target_index = {
                str(target["target_identity"]): target
                for target in targets
                if isinstance(target, Mapping)
            }
            dependency_index = {
                str(dependency["dependency_identity"]): dependency
                for dependency in dependencies
                if isinstance(dependency, Mapping)
            }
            if len(write_bindings) != len(target_index) or len(
                dependency_bindings
            ) != len(dependency_index):
                raise _InvalidPreparation("captured projection coverage is incomplete")

            surface_ids: list[str] = []
            bound_targets: list[str] = []
            for binding in write_bindings:
                if not isinstance(binding, Mapping):
                    raise _InvalidPreparation("captured write binding is invalid")
                target_identity = binding.get("target_identity")
                surface_id = binding.get("surface_id")
                if not isinstance(target_identity, str) or not isinstance(
                    surface_id, str
                ):
                    raise _InvalidPreparation("captured write binding is invalid")
                target = target_index.get(target_identity)
                surface = surface_by_identity.get(surface_id)
                if (
                    target is None
                    or surface is None
                    or surface_id not in reference_counts
                    or surface.get("route_id") != action.get("route_identity")
                    or surface.get("kind") != target.get("surface_kind")
                    or surface.get("locator") != target.get("locator")
                    or surface.get("equipment_identity")
                    != target.get("equipment_identity")
                    or surface.get("mutation_policy") != "reconciler_owned"
                ):
                    raise _InvalidPreparation("captured write target mismatch")
                bound_targets.append(target_identity)
                surface_ids.append(surface_id)
                write_surface_counts[surface_id] = (
                    write_surface_counts.get(surface_id, 0) + 1
                )
            if bound_targets != sorted(set(bound_targets)) or set(
                bound_targets
            ) != set(target_index):
                raise _InvalidPreparation("captured write target coverage is not exact")

            bound_dependencies: list[str] = []
            for binding in dependency_bindings:
                if not isinstance(binding, Mapping):
                    raise _InvalidPreparation("captured dependency binding is invalid")
                dependency_identity = binding.get("dependency_identity")
                surface_id = binding.get("surface_id")
                if not isinstance(dependency_identity, str) or not isinstance(
                    surface_id, str
                ):
                    raise _InvalidPreparation("captured dependency binding is invalid")
                dependency = dependency_index.get(dependency_identity)
                surface = surface_by_identity.get(surface_id)
                if (
                    dependency is None
                    or surface is None
                    or surface_id not in reference_counts
                    or surface.get("route_id") != action.get("route_identity")
                    or surface.get("kind") != "canonical_skill_entry"
                    or surface.get("locator") != dependency.get("target_locator")
                    or surface.get("equipment_identity")
                    != dependency.get("equipment_identity")
                    or surface.get("mutation_policy") != "forbidden"
                ):
                    raise _InvalidPreparation("captured dependency mismatch")
                bound_dependencies.append(dependency_identity)
                surface_ids.append(surface_id)
                dependency_surface_counts[surface_id] = (
                    dependency_surface_counts.get(surface_id, 0) + 1
                )
            if bound_dependencies != sorted(set(bound_dependencies)) or set(
                bound_dependencies
            ) != set(dependency_index):
                raise _InvalidPreparation("captured dependency coverage is not exact")
            if len(surface_ids) != len(set(surface_ids)):
                raise _InvalidPreparation("captured projection surface is duplicated")

            projected_surfaces = []
            for surface_id in sorted(surface_ids):
                surface = surface_by_identity.get(surface_id)
                if surface is None or surface.get("route_id") != action.get(
                    "route_identity"
                ):
                    raise _InvalidPreparation("captured projection surface mismatch")
                projected_surfaces.append(copy.deepcopy(surface))
            manifest, adapter = adapter_binding
            contexts.append(
                {
                    "evidence": copy.deepcopy(evidence),
                    "action": copy.deepcopy(action),
                    "route": copy.deepcopy(route),
                    "reference": copy.deepcopy(reference),
                    "surfaces": projected_surfaces,
                    "adapter_manifest": copy.deepcopy(manifest),
                    "prepare_call": adapter,
                }
            )
        if actual_ordinals != expected_ordinals:
            raise _InvalidPreparation(
                "planned actions are not in canonical ordinal order"
            )
        for surface in surfaces:
            assert isinstance(surface, Mapping)
            surface_id = str(surface["surface_id"])
            write_count = write_surface_counts.get(surface_id, 0)
            if (
                surface.get("mutation_policy") == "reconciler_owned"
                and write_count != 1
            ):
                raise _InvalidPreparation("mutable surface action ownership is not exact")
            if (
                surface.get("mutation_policy") != "reconciler_owned"
                and write_count != 0
            ):
                raise _InvalidPreparation("non-reconciler surface is write-bound")
            dependency_count = dependency_surface_counts.get(surface_id, 0)
            route = route_by_identity.get(surface.get("route_id"))
            if dependency_count > 1:
                raise _InvalidPreparation("captured dependency is multiply bound")
            if (
                route is not None
                and route.get("control_owner") == "reconciler_owned"
                and surface.get("kind") == "canonical_skill_entry"
                and dependency_count != 1
            ):
                raise _InvalidPreparation(
                    "reconciler route dependency ownership is not exact"
                )
        return contexts

    def _facts_bindings(
        self,
        action: Mapping[str, object],
        action_digest: str,
        manifest: Mapping[str, object],
        captured_projection: Mapping[str, object],
        trust: PreparationTrust,
    ) -> dict[str, object]:
        return {
            "action_identity": action["action_identity"],
            "action_digest": action_digest,
            "ordinal": action["ordinal"],
            "candidate_identity": trust.expected_candidate_identity,
            "implementation_manifest_digest": trust.expected_implementation_manifest_digest,
            "plan_digest": trust.expected_plan_digest,
            "plan_action_set_digest": trust.expected_plan_action_set_digest,
            "capability_set_digest": trust.expected_capability_set_digest,
            "capability_identity": action["capability_identity"],
            "capability_digest": action["capability_digest"],
            "manager_version_evidence_digest": action[
                "manager_version_evidence_digest"
            ],
            "route_identity": action["route_identity"],
            "route_digest": action["route_digest"],
            "provider_digest": _digest(action["provider"]),
            "operation_digest": _digest(action["operation"]),
            "compensation_digest": _digest(action["compensation"]),
            "desired_state_digest": action["desired_state_digest"],
            "captured_projection_digest": _digest(captured_projection),
            "adapter_identity": action["adapter_identity"],
            "adapter_version": action["adapter_version"],
            "adapter_manifest_identity": manifest["adapter_manifest_identity"],
            "adapter_manifest_digest": manifest["adapter_manifest_digest"],
            "preparation_adapter_manifest_set_digest": self._adapter_manifest_set[
                "adapter_manifest_set_digest"
            ],
            "adapter_implementation_manifest_digest": manifest[
                "adapter_implementation_manifest_digest"
            ],
            "adapter_implementation_identity": manifest[
                "adapter_implementation_identity"
            ],
            "captured_state_identity": trust.expected_captured_state_identity,
            "captured_state_digest": trust.expected_captured_state_digest,
        }

    def _prepare_action(
        self,
        context: Mapping[str, object],
        trust: PreparationTrust,
        captured_state_bytes: bytes,
    ) -> dict[str, object]:
        action = context["action"]
        manifest = context["adapter_manifest"]
        assert isinstance(action, Mapping) and isinstance(manifest, Mapping)
        captured_projection = {
            "captured_state_bytes_base64": base64.b64encode(
                captured_state_bytes
            ).decode("ascii"),
            "captured_state_bytes_digest": _byte_digest(captured_state_bytes),
            "route_identity": action["route_identity"],
            "action_identity": action["action_identity"],
            "surface_ids": sorted(
                str(surface["surface_id"])
                for surface in context["surfaces"]
                if isinstance(surface, Mapping)
            ),
        }
        evidence = context["evidence"]
        assert isinstance(evidence, Mapping)
        echo_bindings = self._facts_bindings(
            action,
            str(evidence["action_digest"]),
            manifest,
            captured_projection,
            trust,
        )
        request: dict[str, object] = {
            "contract_version": "adapter-contract-v1",
            "request_identity": "prepare-request:sha256:" + "0" * 64,
            "echo_bindings": echo_bindings,
            "captured_projection": captured_projection,
            "operation": action["operation"],
            "desired_state": copy.deepcopy(action["desired_state"]),
            "desired_state_digest": action["desired_state_digest"],
            "compensation_operation": "restore_captured_pre_state",
            "request_digest": "sha256:" + "0" * 64,
        }
        _seal_record(
            request,
            identity_field="request_identity",
            identity_prefix="prepare-request:",
            digest_field="request_digest",
        )
        self._validate_definition(
            "adapter-contract-v1.schema.json",
            "prepareRequest",
            request,
        )
        request_bytes = _canonical_bytes(request)
        prepare_call = context["prepare_call"]
        if not callable(prepare_call):
            raise _InvalidPreparation("invalid bound adapter")
        response_bytes = prepare_call(request_bytes)
        facts = _parse_exact_object(
            response_bytes,
            maximum_bytes=_MAX_ADAPTER_RESPONSE_BYTES,
        )
        if _contains_literal_secret(facts):
            raise _InvalidPreparation(
                "prepared facts contain literal credential material"
            )
        allowed = frozenset(
            {
                "contract_version",
                "request_identity",
                "request_digest",
                "echo_bindings",
                "captured_pre_state",
                "captured_pre_state_digest",
                "expected_post_state",
                "expected_post_state_digest",
                "facts_digest",
            }
        )
        _require_closed(facts, allowed)
        self._validate_definition(
            "adapter-contract-v1.schema.json",
            "preparedStateFacts",
            facts,
        )
        if facts.get("contract_version") != "adapter-contract-v1":
            raise _InvalidPreparation("unsupported prepared facts version")
        if (
            facts.get("request_identity") != request["request_identity"]
            or facts.get("request_digest") != request["request_digest"]
        ):
            raise _InvalidPreparation("prepared facts request mismatch")
        if facts.get("echo_bindings") != echo_bindings:
            raise _InvalidPreparation("prepared facts binding mismatch")
        for state_field in ("captured_pre_state", "expected_post_state"):
            state = facts.get(state_field)
            if not isinstance(state, Mapping):
                raise _InvalidPreparation("prepared state is not a closed object")
            if facts.get(state_field + "_digest") != _digest(state):
                raise _InvalidPreparation("prepared state digest mismatch")
        controlled = action.get("controlled_equipment_identities")
        if not isinstance(controlled, list) or any(
            _normalized_component_identities(facts.get(state_field))
            != tuple(controlled)
            for state_field in ("captured_pre_state", "expected_post_state")
        ):
            raise _InvalidPreparation(
                "prepared component membership exceeds action authority"
            )
        facts_payload = copy.deepcopy(facts)
        facts_payload.pop("facts_digest", None)
        if facts.get("facts_digest") != _digest(facts_payload):
            raise _InvalidPreparation("prepared facts digest mismatch")
        if not self._normalized_state_includes_desired_fragment(
            action["desired_state"], facts["expected_post_state"]
        ):
            raise _InvalidPreparation(
                "expected post-state does not include desired state"
            )
        expected_post_digest = facts["expected_post_state_digest"]
        for surface in context["surfaces"]:
            if not isinstance(surface, Mapping):
                continue
            recovery = surface.get("recovery")
            if (
                isinstance(recovery, Mapping)
                and recovery.get("kind") == "native_inverse"
                and recovery.get("inverse_operation") == "remove"
                and recovery.get("expected_pre_state_digest") != expected_post_digest
            ):
                raise _InvalidPreparation(
                    "native remove guard is not the prepared post-state"
                )
        return facts

    @staticmethod
    def _normalized_state_includes_desired_fragment(
        desired: object,
        actual: object,
    ) -> bool:
        if not isinstance(desired, Mapping) or not isinstance(actual, Mapping):
            return False
        for field in (
            "route_presence",
            "enablement",
            "native_update_suppression_state",
        ):
            if field in desired and actual.get(field) != desired[field]:
                return False
        desired_configuration = desired.get("configuration")
        if isinstance(desired_configuration, Mapping):
            expected_configuration = dict(desired_configuration)
            if expected_configuration.get("status") == "desired":
                expected_configuration["status"] = "observed"
            if actual.get("configuration") != expected_configuration:
                return False
        desired_components = desired.get("component_states")
        if isinstance(desired_components, list):
            actual_components = actual.get("component_states")
            if not isinstance(actual_components, list):
                return False
            actual_index = {
                item.get("equipment_identity"): item.get("state")
                for item in actual_components
                if isinstance(item, Mapping)
            }
            if any(
                not isinstance(item, Mapping)
                or actual_index.get(item.get("equipment_identity"))
                != item.get("state")
                for item in desired_components
            ):
                return False
        return True

    def _capture_authority_set(
        self,
        plan: Mapping[str, object],
        capture: Mapping[str, object],
        facts: Sequence[Mapping[str, object]],
        trust: PreparationTrust,
    ) -> dict[str, object]:
        actions = plan["actions"]
        assert isinstance(actions, list)
        observations: list[dict[str, object]] = []
        for evidence, action_facts in zip(actions, facts, strict=True):
            action = evidence["action_payload"]
            observations.append(
                {
                    "action_identity": action["action_identity"],
                    "ordinal": action["ordinal"],
                    "captured_state_identity": trust.expected_captured_state_identity,
                    "captured_state_digest": trust.expected_captured_state_digest,
                    "surface": copy.deepcopy(action["surface_scope"]),
                    "controlled_equipment_identities": copy.deepcopy(
                        action["controlled_equipment_identities"]
                    ),
                    "normalized_pre_state": copy.deepcopy(
                        action_facts["captured_pre_state"]
                    ),
                    "normalized_pre_state_digest": action_facts[
                        "captured_pre_state_digest"
                    ],
                }
            )
        value: dict[str, object] = {
            "schema_version": "agent-equipment-capture-observation-authority-set/v1",
            "authority_set_identity": "capture-observation-authority-set:sha256:"
            + "0" * 64,
            "bindings": {
                "candidate_identity": trust.expected_candidate_identity,
                "implementation_manifest_digest": trust.expected_implementation_manifest_digest,
                "plan_digest": trust.expected_plan_digest,
                "plan_action_set_digest": trust.expected_plan_action_set_digest,
                "capability_set_digest": trust.expected_capability_set_digest,
                "preparation_adapter_manifest_set_digest": self._adapter_manifest_set[
                    "adapter_manifest_set_digest"
                ],
                "captured_state_identity": trust.expected_captured_state_identity,
                "captured_state_digest": trust.expected_captured_state_digest,
            },
            "observations": observations,
            "authority_set_digest": "sha256:" + "0" * 64,
        }
        _seal_record(
            value,
            identity_field="authority_set_identity",
            identity_prefix="capture-observation-authority-set:",
            digest_field="authority_set_digest",
        )
        self._validate_definition(
            "execution-authority-v1.schema.json",
            "captureObservationAuthoritySet",
            value,
        )
        return value

    def _prepared_authority_set(
        self,
        plan: Mapping[str, object],
        capture: Mapping[str, object],
        facts: Sequence[Mapping[str, object]],
        capture_set: Mapping[str, object],
        trust: PreparationTrust,
    ) -> dict[str, object]:
        actions = plan["actions"]
        assert isinstance(actions, list)
        authorities: list[dict[str, object]] = []
        contexts = self._action_contexts(plan, capture, trust)
        for evidence, action_facts in zip(actions, facts, strict=True):
            action = evidence["action_payload"]
            context = contexts[int(action["ordinal"])]
            facts_bindings = action_facts.get("echo_bindings")
            if not isinstance(facts_bindings, Mapping):
                raise _InvalidPreparation("prepared facts bindings are missing")
            route = context["route"]
            projected_surfaces = context["surfaces"]
            assert isinstance(route, Mapping) and isinstance(projected_surfaces, list)
            restore_evidence = route["restore_evidence"]
            surface_recovery = sorted(
                (
                    {
                        "surface_id": surface["surface_id"],
                        "recovery": copy.deepcopy(surface["recovery"]),
                    }
                    for surface in projected_surfaces
                    if isinstance(surface, Mapping)
                ),
                key=lambda item: str(item["surface_id"]),
            )
            recovery_material_digest = _digest(
                {
                    "restore_evidence": restore_evidence,
                    "surface_recovery": surface_recovery,
                }
            )
            native_update_control = (
                restore_evidence.get("native_update_control", "not_applicable")
                if isinstance(restore_evidence, Mapping)
                else "not_applicable"
            )
            authority: dict[str, object] = {
                "action_identity": action["action_identity"],
                "action_digest": evidence["action_digest"],
                "ordinal": action["ordinal"],
                "candidate_identity": action["candidate_identity"],
                "implementation_manifest_digest": action[
                    "implementation_manifest_digest"
                ],
                "catalog_digest": action["catalog_digest"],
                "lock_digest": action["lock_digest"],
                "plan_digest": action["plan_digest"],
                "plan_action_set_digest": trust.expected_plan_action_set_digest,
                "capability_set_digest": trust.expected_capability_set_digest,
                "route_capability_binding": {
                    "capability_identity": action["capability_identity"],
                    "capability_digest": action["capability_digest"],
                    "manager_version_evidence_digest": action[
                        "manager_version_evidence_digest"
                    ],
                },
                "adapter_binding": {
                    "adapter_identity": action["adapter_identity"],
                    "adapter_version": action["adapter_version"],
                    "adapter_manifest_identity": facts_bindings[
                        "adapter_manifest_identity"
                    ],
                    "adapter_manifest_digest": facts_bindings[
                        "adapter_manifest_digest"
                    ],
                    "adapter_implementation_identity": facts_bindings[
                        "adapter_implementation_identity"
                    ],
                    "adapter_implementation_manifest_digest": facts_bindings[
                        "adapter_implementation_manifest_digest"
                    ],
                },
                "capture_observation_authority_set_identity": capture_set[
                    "authority_set_identity"
                ],
                "capture_observation_authority_set_digest": capture_set[
                    "authority_set_digest"
                ],
                "route_capture_binding": {
                    "route_identity": action["route_identity"],
                    "route_digest": action["route_digest"],
                    "restore_evidence_digest": _digest(restore_evidence),
                    "recovery_material_digest": recovery_material_digest,
                    "native_update_control": native_update_control,
                },
                "route_digest": action["route_digest"],
                "provider": copy.deepcopy(action["provider"]),
                "provider_digest": _digest(action["provider"]),
                "operation": action["operation"],
                "operation_digest": _digest(action["operation"]),
                "compensation": copy.deepcopy(action["compensation"]),
                "compensation_digest": _digest(action["compensation"]),
                "compensation_operation": "restore_captured_pre_state",
                "desired_state": copy.deepcopy(action["desired_state"]),
                "desired_state_digest": action["desired_state_digest"],
                "surface": copy.deepcopy(action["surface_scope"]),
                "captured_state_identity": trust.expected_captured_state_identity,
                "captured_state_digest": trust.expected_captured_state_digest,
                "captured_pre_state": copy.deepcopy(action_facts["captured_pre_state"]),
                "captured_pre_state_digest": action_facts["captured_pre_state_digest"],
                "expected_post_state": copy.deepcopy(
                    action_facts["expected_post_state"]
                ),
                "expected_post_state_digest": action_facts[
                    "expected_post_state_digest"
                ],
                "authority_digest": "sha256:" + "0" * 64,
            }
            payload = copy.deepcopy(authority)
            payload.pop("authority_digest", None)
            authority["authority_digest"] = _digest(payload)
            authorities.append(authority)
        value: dict[str, object] = {
            "schema_version": "agent-equipment-prepared-action-authority-set/v1",
            "authority_set_identity": "prepared-action-authority-set:sha256:"
            + "0" * 64,
            "bindings": {
                "candidate_identity": trust.expected_candidate_identity,
                "implementation_manifest_digest": trust.expected_implementation_manifest_digest,
                "plan_digest": trust.expected_plan_digest,
                "plan_action_set_digest": trust.expected_plan_action_set_digest,
                "capability_set_digest": trust.expected_capability_set_digest,
                "preparation_adapter_manifest_set_digest": self._adapter_manifest_set[
                    "adapter_manifest_set_digest"
                ],
                "captured_state_identity": trust.expected_captured_state_identity,
                "captured_state_digest": trust.expected_captured_state_digest,
                "capture_observation_authority_set_identity": capture_set[
                    "authority_set_identity"
                ],
                "capture_observation_authority_set_digest": capture_set[
                    "authority_set_digest"
                ],
            },
            "authorities": authorities,
            "authority_set_digest": "sha256:" + "0" * 64,
        }
        _seal_record(
            value,
            identity_field="authority_set_identity",
            identity_prefix="prepared-action-authority-set:",
            digest_field="authority_set_digest",
        )
        self._validate_definition(
            "execution-authority-v1.schema.json",
            "preparedActionAuthoritySet",
            value,
        )
        return value

    @staticmethod
    def _artifact(raw: bytes) -> dict[str, object]:
        return {
            "bytes_base64": base64.b64encode(raw).decode("ascii"),
            "bytes_digest": _byte_digest(raw),
        }

    def _bundle_bytes(
        self,
        plan_bytes: bytes,
        capture_bytes: bytes,
        capture: Mapping[str, object],
        capture_set: Mapping[str, object],
        prepared_set: Mapping[str, object],
        trust: PreparationTrust,
    ) -> bytes:
        capability_binding_set = {
            "schema_version": "agent-equipment-capability-binding-set/v1",
            "capability_binding_set_identity": (
                "capability-binding-set:sha256:" + "0" * 64
            ),
            "bindings": copy.deepcopy(capture["bindings"]["capability_bindings"]),
            "capability_set_digest": trust.expected_capability_set_digest,
            "capability_binding_set_digest": "sha256:" + "0" * 64,
        }
        _seal_record(
            capability_binding_set,
            identity_field="capability_binding_set_identity",
            identity_prefix="capability-binding-set:",
            digest_field="capability_binding_set_digest",
        )
        self._validate_definition(
            "adapter-contract-v1.schema.json",
            "capabilityBindingSet",
            capability_binding_set,
        )
        artifacts = {
            "adapter_manifest_set": self._artifact(self._adapter_manifest_set_bytes),
            "capability_binding_set": self._artifact(
                _canonical_bytes(capability_binding_set)
            ),
            "capture_observation_authority_set": self._artifact(
                _canonical_bytes(capture_set)
            ),
            "captured_state": self._artifact(capture_bytes),
            "gate_manifest": self._artifact(self._gate_manifest_bytes),
            "plan_action_set": self._artifact(plan_bytes),
            "prepared_action_authority_set": self._artifact(
                _canonical_bytes(prepared_set)
            ),
        }
        capture_bindings = capture.get("bindings")
        if not isinstance(capture_bindings, Mapping):
            raise _InvalidPreparation("captured bindings are missing")
        value: dict[str, object] = {
            "schema_version": "agent-equipment-preparation-bundle/v1",
            "preparation_bundle_identity": "preparation-bundle:sha256:" + "0" * 64,
            "bindings": {
                "candidate_identity": trust.expected_candidate_identity,
                "implementation_manifest_digest": trust.expected_implementation_manifest_digest,
                "catalog_digest": _require_digest(
                    capture_bindings.get("catalog_digest")
                ),
                "lock_digest": _require_digest(capture_bindings.get("lock_digest")),
                "plan_digest": trust.expected_plan_digest,
                "plan_action_set_digest": trust.expected_plan_action_set_digest,
                "captured_state_identity": trust.expected_captured_state_identity,
                "captured_state_digest": trust.expected_captured_state_digest,
                "capability_set_digest": trust.expected_capability_set_digest,
                "preparation_adapter_manifest_set_digest": self._adapter_manifest_set[
                    "adapter_manifest_set_digest"
                ],
                "capture_observation_authority_set_identity": capture_set[
                    "authority_set_identity"
                ],
                "capture_observation_authority_set_digest": capture_set[
                    "authority_set_digest"
                ],
                "prepared_action_authority_set_identity": prepared_set[
                    "authority_set_identity"
                ],
                "prepared_action_authority_set_digest": prepared_set[
                    "authority_set_digest"
                ],
                "preparation_gate_identity": self._gate_manifest["gate_identity"],
                "preparation_gate_manifest_digest": self._gate_manifest[
                    "manifest_digest"
                ],
                "store_identity": self._store_identity,
                "store_generation": 1,
            },
            "artifacts": artifacts,
            "preparation_bundle_digest": "sha256:" + "0" * 64,
        }
        _seal_record(
            value,
            identity_field="preparation_bundle_identity",
            identity_prefix="preparation-bundle:",
            digest_field="preparation_bundle_digest",
        )
        self._validate_definition(
            "execution-authority-v1.schema.json",
            "preparationBundle",
            value,
        )
        return _canonical_bytes(value)

    def _validate_reused_bundle(
        self,
        bundle_bytes: bytes,
        plan_bytes: bytes,
        capture_bytes: bytes,
        trust: PreparationTrust,
    ) -> None:
        bundle = _parse_exact_object(bundle_bytes, maximum_bytes=_MAX_STORE_ENTRY_BYTES)
        _verify_sealed_record(
            bundle,
            identity_field="preparation_bundle_identity",
            identity_prefix="preparation-bundle:",
            digest_field="preparation_bundle_digest",
        )
        bindings = bundle.get("bindings")
        artifacts = bundle.get("artifacts")
        if not isinstance(bindings, Mapping) or not isinstance(artifacts, Mapping):
            raise _InvalidPreparation("invalid reused preparation bundle")
        capture_document = _parse_exact_object(
            capture_bytes,
            maximum_bytes=_MAX_INPUT_BYTES,
        )
        capture_bindings = capture_document.get("bindings")
        if not isinstance(capture_bindings, Mapping):
            raise _InvalidPreparation("reused captured bindings are missing")
        expected = {
            "candidate_identity": trust.expected_candidate_identity,
            "implementation_manifest_digest": trust.expected_implementation_manifest_digest,
            "catalog_digest": capture_bindings.get("catalog_digest"),
            "lock_digest": capture_bindings.get("lock_digest"),
            "plan_digest": trust.expected_plan_digest,
            "plan_action_set_digest": trust.expected_plan_action_set_digest,
            "captured_state_identity": trust.expected_captured_state_identity,
            "captured_state_digest": trust.expected_captured_state_digest,
            "capability_set_digest": trust.expected_capability_set_digest,
            "preparation_adapter_manifest_set_digest": self._adapter_manifest_set[
                "adapter_manifest_set_digest"
            ],
            "preparation_gate_identity": self._gate_manifest["gate_identity"],
            "preparation_gate_manifest_digest": self._gate_manifest["manifest_digest"],
            "store_identity": self._store_identity,
            "store_generation": 1,
        }
        if any(bindings.get(field) != value for field, value in expected.items()):
            raise _InvalidPreparation("reused preparation binding mismatch")
        exact_artifacts = {
            "plan_action_set": plan_bytes,
            "captured_state": capture_bytes,
            "adapter_manifest_set": self._adapter_manifest_set_bytes,
            "gate_manifest": self._gate_manifest_bytes,
        }
        for name, exact_bytes in exact_artifacts.items():
            artifact = artifacts.get(name)
            if not isinstance(artifact, Mapping):
                raise _InvalidPreparation("reused preparation artifact missing")
            decoded = base64.b64decode(str(artifact.get("bytes_base64")), validate=True)
            if decoded != exact_bytes or artifact.get("bytes_digest") != _byte_digest(
                decoded
            ):
                raise _InvalidPreparation("reused preparation artifact mismatch")
        for name, artifact in artifacts.items():
            if not isinstance(name, str) or not isinstance(artifact, Mapping):
                raise _InvalidPreparation("invalid reused preparation artifact")
            decoded = base64.b64decode(str(artifact.get("bytes_base64")), validate=True)
            if artifact.get("bytes_digest") != _byte_digest(decoded):
                raise _InvalidPreparation("reused preparation artifact digest mismatch")
