#!/usr/bin/env python3
"""Semantic validation for agent-equipment captured-state manifests."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import sys
from typing import Mapping, Sequence
from urllib.parse import urlsplit

try:
    from agent_equipment_json_schema import validate_document as _validate_schema
except ModuleNotFoundError:  # Loaded as a repo module rather than an executable.
    from scripts.agent_equipment_json_schema import (
        validate_document as _validate_schema,
    )
try:
    from agent_equipment_public_data import contains_literal_credential
except ModuleNotFoundError:  # Loaded as a repo module rather than an executable.
    from scripts.agent_equipment_public_data import contains_literal_credential


JsonObject = Mapping[str, object]
CAPABILITY_BINDING_KEYS = frozenset(
    {
        "capability_identity",
        "capability_digest",
        "manager_version_evidence_digest",
    }
)
PLANNED_ACTION_REFERENCE_KEYS = frozenset(
    {
        "action_identity",
        "action_digest",
        "write_bindings",
        "verification_dependency_bindings",
    }
)
PLAN_ACTION_PAYLOAD_KEYS = frozenset(
    {
        "action_identity",
        "ordinal",
        "candidate_identity",
        "implementation_manifest_digest",
        "catalog_digest",
        "lock_digest",
        "plan_digest",
        "capability_identity",
        "capability_digest",
        "manager_version_evidence_digest",
        "adapter_identity",
        "adapter_version",
        "harness",
        "route_identity",
        "route_digest",
        "provider",
        "equipment_identities",
        "controlled_equipment_identities",
        "activation_group",
        "surface_scope",
        "write_targets",
        "operation",
        "operation_disposition",
        "desired_state",
        "desired_state_digest",
        "expected_post_state_digest",
        "secret_references",
        "preconditions",
        "verification_dependencies",
        "compensation",
    }
)
PLAN_ACTION_EVIDENCE_KEYS = frozenset({"action_payload", "action_digest"})
PLAN_ACTION_SET_KEYS = frozenset(
    {
        "schema_version",
        "candidate_identity",
        "implementation_manifest_digest",
        "plan_digest",
        "actions",
        "action_set_digest",
    }
)
PLAN_ACTION_SET_SCHEMA_VERSION = "agent-equipment-plan-action-set/v1"
DESIRED_STATE_KEYS = frozenset(
    {
        "route_presence",
        "enablement",
        "configuration",
        "component_states",
        "native_update_suppression_state",
    }
)
AUTOMATED_OPERATIONS = frozenset(
    {
        "install",
        "configure",
        "enable",
        "disable",
        "remove",
        "restore",
        "suppress_native_update",
    }
)
PRECONDITION_KEYS = frozenset(
    {
        "catalog_digest",
        "lock_digest",
        "plan_digest",
        "candidate_identity",
        "implementation_manifest_digest",
        "route_digest",
        "capability_digest",
        "manager_version_evidence_digest",
        "adapter_identity",
        "adapter_version",
        "control_owner",
        "activation_group",
        "surface_scope",
        "prepared_checkpoint_required",
        "compare_before_mutate",
    }
)
COMPENSATION_KEYS = frozenset({"kind", "captured_state_version"})
VERIFICATION_DEPENDENCY_KEYS = frozenset(
    {
        "relationship",
        "dependency_identity",
        "write_surface_identity",
        "equipment_identity",
        "target_locator",
    }
)
WRITE_TARGET_REQUIRED_KEYS = frozenset(
    {
        "target_identity",
        "write_surface_identity",
        "surface_kind",
        "locator",
    }
)
SCHEMA_DIRECTORY = Path(__file__).resolve().parent.parent / "docs/agent-equipment"


@dataclass(frozen=True, order=True)
class Diagnostic:
    """A secret-free, deterministic captured-state validation failure."""

    path: str
    code: str
    message: str


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _binding_key(binding: JsonObject) -> tuple[str, str, str]:
    return (
        str(binding["capability_identity"]),
        str(binding["capability_digest"]),
        str(binding["manager_version_evidence_digest"]),
    )


def capability_set_digest(bindings: Sequence[JsonObject]) -> str:
    """Digest the capability bindings after canonical identity-first sorting."""

    if not all(_has_closed_binding_shape(binding) for binding in bindings):
        raise ValueError("capability bindings must use the closed v1 shape")
    payload = _canonical_bytes(sorted(bindings, key=_binding_key))
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def plan_action_digest(action_payload: JsonObject) -> str:
    """Digest one closed, secret-free canonical plan-action evidence payload."""

    if not _has_plan_action_payload_shape(action_payload):
        raise ValueError("plan action evidence must use the closed v1 payload shape")
    return f"sha256:{hashlib.sha256(_canonical_bytes(action_payload)).hexdigest()}"


def write_target_identity(write_target: JsonObject) -> str:
    """Derive one physical write-target identity from its closed descriptor."""

    identity_payload = {
        key: value
        for key, value in write_target.items()
        if key != "target_identity"
    }
    if not _has_write_target_shape(
        {"target_identity": "target:sha256:" + "0" * 64, **identity_payload}
    ):
        raise ValueError("write target must use the closed v1 descriptor shape")
    return (
        "target:sha256:"
        f"{hashlib.sha256(_canonical_bytes(identity_payload)).hexdigest()}"
    )


def plan_action_identity(action_payload: JsonObject) -> str:
    """Derive the v1 action identity from its plan and execution coordinates."""

    if not _has_plan_action_payload_shape(action_payload):
        raise ValueError("plan action evidence must use the closed v1 payload shape")
    identity_payload = {
        "plan_digest": action_payload["plan_digest"],
        "ordinal": action_payload["ordinal"],
        "route_id": action_payload["route_identity"],
        "operation": action_payload["operation"],
        "desired_state_digest": action_payload["desired_state_digest"],
    }
    return (
        "action:sha256:"
        f"{hashlib.sha256(_canonical_bytes(identity_payload)).hexdigest()}"
    )


def _plan_action_evidence_key(evidence: JsonObject) -> tuple[int, str]:
    payload = evidence["action_payload"]
    assert isinstance(payload, Mapping)
    return int(payload["ordinal"]), str(payload["action_identity"])


def plan_action_set_digest(
    candidate_identity: str,
    implementation_manifest_digest: str,
    plan_digest: str,
    actions: Sequence[JsonObject],
) -> str:
    """Digest a closed authoritative plan-action projection in canonical order."""

    if (
        not isinstance(candidate_identity, str)
        or not candidate_identity
        or not isinstance(implementation_manifest_digest, str)
        or not re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            implementation_manifest_digest,
        )
        or not isinstance(plan_digest, str)
        or not all(
            _has_plan_action_evidence_shape(action) for action in actions
        )
    ):
        raise ValueError("plan action set must use the closed v1 shape")
    payload = {
        "schema_version": PLAN_ACTION_SET_SCHEMA_VERSION,
        "candidate_identity": candidate_identity,
        "implementation_manifest_digest": implementation_manifest_digest,
        "plan_digest": plan_digest,
        "actions": sorted(actions, key=_plan_action_evidence_key),
    }
    return f"sha256:{hashlib.sha256(_canonical_bytes(payload)).hexdigest()}"


def _diagnostic(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(path=path, code=code, message=message)


def _strict_json_object(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, member in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = member
    return value


def _reject_non_json_constant(_: str) -> object:
    raise ValueError("non-JSON numeric constant")


_OVERSIZED_JSON_INTEGER = object()


def _strict_json_integer(value: str) -> object:
    digit_limit = sys.get_int_max_str_digits()
    if digit_limit and len(value.removeprefix("-")) > digit_limit:
        return _OVERSIZED_JSON_INTEGER
    return int(value)


def _strict_json_load(stream: object) -> object:
    return json.load(
        stream,
        object_pairs_hook=_strict_json_object,
        parse_constant=_reject_non_json_constant,
        parse_int=_strict_json_integer,
    )


def _schema_gate_diagnostic(
    document: object,
    *,
    schema_name: str,
    code: str,
    label: str,
    path: str,
) -> Diagnostic | None:
    if _validate_schema(
        document,
        schema_directory=SCHEMA_DIRECTORY,
        root_schema_name=schema_name,
        allowed_schema_names={schema_name},
    ):
        return None
    return _diagnostic(
        code,
        path,
        f"The {label} or its closed local schema set is invalid.",
    )


def _is_array(value: object) -> bool:
    return isinstance(value, list)


def _has_closed_binding_shape(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == CAPABILITY_BINDING_KEYS
        and all(isinstance(value[key], str) for key in CAPABILITY_BINDING_KEYS)
    )


def _has_planned_action_reference_shape(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == PLANNED_ACTION_REFERENCE_KEYS
        and isinstance(value.get("action_identity"), str)
        and isinstance(value.get("action_digest"), str)
        and _is_array(value.get("write_bindings"))
        and all(
            isinstance(binding, Mapping)
            for binding in value.get("write_bindings", [])
        )
        and _is_array(value.get("verification_dependency_bindings"))
        and all(
            isinstance(binding, Mapping)
            for binding in value.get("verification_dependency_bindings", [])
        )
    )


def _has_desired_state_shape(value: object) -> bool:
    if (
        not isinstance(value, Mapping)
        or not value
        or not set(value).issubset(DESIRED_STATE_KEYS)
        or (
            "route_presence" in value
            and value.get("route_presence") not in {"present", "absent"}
        )
    ):
        return False
    if "enablement" in value and value["enablement"] not in {
        "enabled",
        "disabled",
    }:
        return False
    if "configuration" in value:
        configuration = value["configuration"]
        if not isinstance(configuration, Mapping):
            return False
        if configuration.get("status") == "desired":
            if set(configuration) != {"status", "digest"} or not isinstance(
                configuration.get("digest"), str
            ):
                return False
        elif configuration != {"status": "not_applicable"}:
            return False
    if "component_states" in value:
        component_states = value["component_states"]
        if (
            not _is_array(component_states)
            or not component_states
            or not all(
                isinstance(component, Mapping)
                and set(component) == {"equipment_identity", "state"}
                and isinstance(component.get("equipment_identity"), str)
                and component.get("state") in {"enabled", "disabled"}
                for component in component_states
            )
            or len({_canonical_bytes(component) for component in component_states})
            != len(component_states)
        ):
            return False
    if (
        "native_update_suppression_state" in value
        and value["native_update_suppression_state"]
        not in {"enabled", "disabled", "not_applicable"}
    ):
        return False
    return True


def _has_plan_action_payload_shape(value: object) -> bool:
    if not isinstance(value, Mapping) or set(value) != PLAN_ACTION_PAYLOAD_KEYS:
        return False
    provider = value.get("provider")
    preconditions = value.get("preconditions")
    compensation = value.get("compensation")
    equipment_identities = value.get("equipment_identities")
    controlled_equipment_identities = value.get(
        "controlled_equipment_identities"
    )
    surface_scope = value.get("surface_scope")
    secret_references = value.get("secret_references")
    verification_dependencies = value.get("verification_dependencies")
    write_targets = value.get("write_targets")
    return (
        isinstance(value.get("action_identity"), str)
        and isinstance(value.get("ordinal"), int)
        and not isinstance(value.get("ordinal"), bool)
        and 0 <= value["ordinal"] <= 2_147_483_647
        and all(
            isinstance(value.get(field), str)
            for field in (
                "catalog_digest",
                "lock_digest",
                "plan_digest",
                "candidate_identity",
                "implementation_manifest_digest",
                "capability_identity",
                "capability_digest",
                "manager_version_evidence_digest",
                "adapter_identity",
                "adapter_version",
                "harness",
                "route_identity",
                "route_digest",
                "activation_group",
                "desired_state_digest",
                "expected_post_state_digest",
            )
        )
        and _has_provider_shape(provider)
        and _is_sorted_unique_nonempty_strings(equipment_identities)
        and _is_sorted_unique_strings(controlled_equipment_identities)
        and _is_sorted_unique_nonempty_strings(surface_scope)
        and _has_write_targets_shape(write_targets)
        and value.get("operation") in AUTOMATED_OPERATIONS
        and value.get("operation_disposition") == "automated"
        and _has_desired_state_shape(value.get("desired_state"))
        and _has_secret_references_shape(secret_references)
        and _has_preconditions_shape(preconditions)
        and _has_verification_dependencies_shape(verification_dependencies)
        and compensation
        == {
            "kind": "restore_captured_pre_state",
            "captured_state_version": "agent-equipment-captured-state/v1",
        }
    )


def _is_sorted_unique_nonempty_strings(value: object) -> bool:
    return (
        _is_array(value)
        and bool(value)
        and all(isinstance(item, str) and bool(item) for item in value)
        and list(value) == sorted(set(value))
    )


def _is_sorted_unique_strings(value: object) -> bool:
    return (
        _is_array(value)
        and all(isinstance(item, str) and bool(item) for item in value)
        and list(value) == sorted(set(value))
    )


def _has_provider_shape(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    kind = value.get("kind")
    if kind == "standalone_skill":
        return set(value) == {"kind", "canonical_root"} and value.get(
            "canonical_root"
        ) == "agents_skills"
    if kind == "native_plugin":
        return (
            set(value) == {"kind", "manager", "plugin_id", "scope"}
            and value.get("manager") in {"claude", "codex", "cursor"}
            and isinstance(value.get("plugin_id"), str)
            and bool(value.get("plugin_id"))
            and value.get("scope") == "user"
        )
    if kind != "direct_mcp":
        return False
    transport = value.get("transport")
    if transport == "stdio":
        return (
            set(value)
            == {"kind", "server_name", "transport", "command", "arguments"}
            and all(
                isinstance(value.get(field), str) and bool(value.get(field))
                for field in ("server_name", "command")
            )
            and _is_array(value.get("arguments"))
            and all(
                _has_provider_argument_shape(argument)
                for argument in value["arguments"]
            )
        )
    return (
        transport == "http"
        and set(value) == {"kind", "server_name", "transport", "url"}
        and isinstance(value.get("server_name"), str)
        and bool(value.get("server_name"))
        and isinstance(value.get("url"), str)
        and _credential_free_https_url_is_valid(str(value.get("url")))
    )


def _has_provider_argument_shape(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    if set(value) == {"literal"}:
        return isinstance(value.get("literal"), str)
    if set(value) == {"secret_reference", "template"}:
        return (
            isinstance(value.get("secret_reference"), str)
            and bool(value.get("secret_reference"))
            and isinstance(value.get("template"), str)
            and str(value.get("template")).count("{reference}") == 1
        )
    return (
        set(value) == {"secret_profile_reference"}
        and isinstance(value.get("secret_profile_reference"), str)
        and bool(value.get("secret_profile_reference"))
    )


def _credential_free_https_url_is_valid(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    path_segments = tuple(segment for segment in parsed.path.split("/") if segment)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and _static_https_hostname_is_valid(parsed.hostname or "")
        and parsed.username is None
        and parsed.password is None
        and parsed.query == ""
        and parsed.fragment == ""
        and (port is None or 1 <= port <= 65535)
        and "\\" not in value
        and "%" not in value
        and all(
            segment not in {".", ".."}
            and bool(re.fullmatch(r"[A-Za-z0-9._~-]+", segment))
            and not re.fullmatch(
                r"(?i)(?:bearer|api[-_]?key|access[-_]?token|token|secret|password|client[-_]?secret|credential)(?:[-_.=:].*)?",
                segment,
            )
            for segment in path_segments
        )
    )


def _static_https_hostname_is_valid(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        labels = value.split(".")
        return len(value) <= 253 and all(
            1 <= len(label) <= 63
            and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
            is not None
            for label in labels
        )
    return True


def _has_secret_references_shape(value: object) -> bool:
    if not _is_array(value):
        return False
    canonical: list[bytes] = []
    for reference in value:
        if not isinstance(reference, Mapping) or set(reference) != {"kind", "name"}:
            return False
        if reference.get("kind") not in {"environment_variable", "secret_profile"}:
            return False
        if not isinstance(reference.get("name"), str) or not reference.get("name"):
            return False
        canonical.append(_canonical_bytes(reference))
    return canonical == sorted(set(canonical))


def _provider_secret_reference_keys(provider: JsonObject) -> set[tuple[str, str]]:
    if provider.get("kind") != "direct_mcp" or provider.get("transport") != "stdio":
        return set()
    arguments = provider.get("arguments")
    if not isinstance(arguments, list):
        return set()
    references: set[tuple[str, str]] = set()
    for argument in arguments:
        if not isinstance(argument, Mapping):
            continue
        if isinstance(argument.get("secret_reference"), str):
            references.add(("environment_variable", argument["secret_reference"]))
        if isinstance(argument.get("secret_profile_reference"), str):
            references.add(("secret_profile", argument["secret_profile_reference"]))
    return references


def _has_preconditions_shape(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == PRECONDITION_KEYS
        and all(
            isinstance(value.get(field), str) and bool(value.get(field))
            for field in PRECONDITION_KEYS
            - {"surface_scope", "prepared_checkpoint_required", "compare_before_mutate"}
        )
        and value.get("control_owner") == "reconciler_owned"
        and _is_sorted_unique_nonempty_strings(value.get("surface_scope"))
        and value.get("prepared_checkpoint_required") is True
        and value.get("compare_before_mutate") is True
    )


def _has_verification_dependencies_shape(value: object) -> bool:
    if not _is_array(value):
        return False
    canonical: list[bytes] = []
    for dependency in value:
        if (
            not isinstance(dependency, Mapping)
            or set(dependency) != VERIFICATION_DEPENDENCY_KEYS
            or dependency.get("relationship") != "canonical_skill_projection"
            or not all(
                isinstance(dependency.get(field), str) and bool(dependency.get(field))
                for field in (
                    "dependency_identity",
                    "write_surface_identity",
                    "equipment_identity",
                )
            )
            or not isinstance(dependency.get("target_locator"), Mapping)
            or set(dependency["target_locator"]) != {"path"}
            or not _is_skill_path(
                dependency["target_locator"].get("path"),
                "~/.agents/skills/",
            )
        ):
            return False
        canonical.append(_canonical_bytes(dependency))
    return canonical == sorted(set(canonical))


def _has_write_target_shape(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    keys = set(value)
    if keys not in {
        WRITE_TARGET_REQUIRED_KEYS,
        WRITE_TARGET_REQUIRED_KEYS | {"equipment_identity"},
    }:
        return False
    if not all(
        isinstance(value.get(field), str) and bool(value.get(field))
        for field in (
            "target_identity",
            "write_surface_identity",
            "surface_kind",
        )
    ):
        return False
    if "equipment_identity" in value and (
        not isinstance(value.get("equipment_identity"), str)
        or not value.get("equipment_identity")
    ):
        return False
    locator = value.get("locator")
    if not isinstance(locator, Mapping):
        return False
    surface_kind = value.get("surface_kind")
    if surface_kind in {"plugin_installation", "plugin_enablement"}:
        return (
            "equipment_identity" not in value
            and set(locator) == {"manager", "native_identity", "scope"}
            and all(
                isinstance(locator.get(field), str) and bool(locator.get(field))
                for field in ("manager", "native_identity", "scope")
            )
        )
    if surface_kind == "claude_skill_entry":
        return (
            "equipment_identity" in value
            and set(locator) == {"path"}
            and _is_skill_path(locator.get("path"), "~/.claude/skills/")
        )
    if surface_kind in {
        "legacy_projector",
        "mcp_selection",
        "plugin_selection",
    }:
        return (
            (
                "equipment_identity" not in value
                if surface_kind == "legacy_projector"
                else "equipment_identity" in value
            )
            and set(locator) == {"owner", "source", "key_path"}
            and all(
                isinstance(locator.get(field), str) and bool(locator.get(field))
                for field in ("owner", "source")
            )
            and _is_array(locator.get("key_path"))
            and bool(locator.get("key_path"))
            and all(
                isinstance(part, str) and bool(part)
                for part in locator.get("key_path", [])
            )
        )
    return False


def _has_write_targets_shape(value: object) -> bool:
    return (
        _is_array(value)
        and bool(value)
        and all(_has_write_target_shape(target) for target in value)
        and [str(target["target_identity"]) for target in value]
        == sorted({str(target["target_identity"]) for target in value})
    )


def _has_plan_action_evidence_shape(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == PLAN_ACTION_EVIDENCE_KEYS
        and _has_plan_action_payload_shape(value.get("action_payload"))
        and isinstance(value.get("action_digest"), str)
    )


def _has_authoritative_plan_action_set_shape(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == PLAN_ACTION_SET_KEYS
        and value.get("schema_version") == PLAN_ACTION_SET_SCHEMA_VERSION
        and isinstance(value.get("candidate_identity"), str)
        and bool(value.get("candidate_identity"))
        and isinstance(value.get("implementation_manifest_digest"), str)
        and isinstance(value.get("plan_digest"), str)
        and _is_array(value.get("actions"))
        and all(
            _has_plan_action_evidence_shape(action)
            for action in value.get("actions", [])
        )
        and isinstance(value.get("action_set_digest"), str)
    )


def _has_semantic_structure(document: object) -> bool:
    if not isinstance(document, Mapping):
        return False

    required_top_level = {
        "schema_version",
        "migration_id",
        "captured_at",
        "bindings",
        "provider_routes",
        "surfaces",
    }
    if not required_top_level.issubset(document):
        return False

    bindings = document.get("bindings")
    routes = document.get("provider_routes")
    surfaces = document.get("surfaces")
    if (
        not isinstance(bindings, Mapping)
        or not _is_array(routes)
        or not _is_array(surfaces)
    ):
        return False

    capability_bindings = bindings.get("capability_bindings")
    if (
        not _is_array(capability_bindings)
        or not isinstance(bindings.get("candidate_identity"), str)
        or not isinstance(bindings.get("implementation_manifest_digest"), str)
        or not isinstance(bindings.get("plan_digest"), str)
        or not isinstance(bindings.get("plan_action_set_digest"), str)
        or not isinstance(bindings.get("capability_set_digest"), str)
        or not all(_has_closed_binding_shape(binding) for binding in capability_bindings)
    ):
        return False

    for route in routes:
        if not isinstance(route, Mapping):
            return False
        references = route.get("surface_references")
        if (
            not isinstance(route.get("route_id"), str)
            or not _is_array(route.get("equipment_identities"))
            or not _is_array(route.get("controlled_equipment_identities"))
            or not all(
                isinstance(identity, str)
                for identity in route.get("equipment_identities", [])
            )
            or not isinstance(route.get("control_owner"), str)
            or not _has_closed_binding_shape(route.get("capability_binding"))
            or not isinstance(route.get("restore_evidence"), Mapping)
            or not isinstance(references, Mapping)
        ):
            return False
        for singular in ("installation", "enablement", "projector"):
            if not isinstance(references.get(singular), Mapping):
                return False
        if not _is_array(route.get("planned_actions")) or not all(
            _has_planned_action_reference_shape(reference)
            for reference in route.get("planned_actions", [])
        ):
            return False
        for plural in (
            "mcp_selections",
            "plugin_selections",
            "skill_entries",
            "canonical_skill_dependencies",
        ):
            if not _is_array(references.get(plural)) or not all(
                isinstance(reference, Mapping) for reference in references.get(plural, [])
            ):
                return False

    for surface in surfaces:
        if (
            not isinstance(surface, Mapping)
            or not isinstance(surface.get("surface_id"), str)
            or not isinstance(surface.get("kind"), str)
            or not isinstance(surface.get("mutation_policy"), str)
            or not isinstance(surface.get("locator"), Mapping)
            or not isinstance(surface.get("observation"), Mapping)
            or not isinstance(surface.get("recovery"), Mapping)
        ):
            return False
        if "route_id" in surface and not isinstance(surface.get("route_id"), str):
            return False
        if "equipment_identity" in surface and not isinstance(
            surface.get("equipment_identity"), str
        ):
            return False

    return True


def _captured_references(route: JsonObject) -> list[tuple[str, str]]:
    references = route["surface_references"]
    assert isinstance(references, Mapping)
    candidates: list[tuple[str, object]] = [
        ("plugin_installation", references["installation"]),
        ("plugin_enablement", references["enablement"]),
        ("legacy_projector", references["projector"]),
    ]
    candidates.extend(
        ("mcp_selection", reference)
        for reference in references["mcp_selections"]  # type: ignore[union-attr]
    )
    candidates.extend(
        ("plugin_selection", reference)
        for reference in references["plugin_selections"]  # type: ignore[union-attr]
    )
    candidates.extend(
        ("claude_skill_entry", reference)
        for reference in references["skill_entries"]  # type: ignore[union-attr]
    )
    candidates.extend(
        ("canonical_skill_entry", reference)
        for reference in references["canonical_skill_dependencies"]  # type: ignore[union-attr]
    )

    captured: list[tuple[str, str]] = []
    for expected_kind, reference in candidates:
        assert isinstance(reference, Mapping)
        if reference.get("status") == "captured" and isinstance(
            reference.get("surface_id"), str
        ):
            captured.append((expected_kind, reference["surface_id"]))
    return captured


def _is_skill_path(path: object, root: str) -> bool:
    if not isinstance(path, str) or not path.startswith(root):
        return False
    basename = path[len(root) :]
    return (
        basename not in {"", ".", ".."}
        and not any(separator in basename for separator in ("/", "\\", "\0"))
    )


def _logical_surface_key(surface: JsonObject) -> tuple[str, str, str, bytes]:
    kind = str(surface["kind"])
    equipment_identity = str(surface.get("equipment_identity", ""))
    return (
        kind,
        str(surface.get("route_id", "")),
        equipment_identity,
        _canonical_bytes(surface["locator"]),
    )


def _is_native_remove_inverse(recovery: JsonObject) -> bool:
    return (
        recovery.get("kind") == "native_inverse"
        and recovery.get("inverse_operation") == "remove"
    )


def _mutable_surface_recovery_diagnostics(
    surface: JsonObject,
    index: int,
) -> list[Diagnostic]:
    if surface.get("mutation_policy") != "reconciler_owned":
        return []
    kind = surface["kind"]
    observation = surface["observation"]
    recovery = surface["recovery"]
    assert isinstance(kind, str)
    assert isinstance(observation, Mapping)
    assert isinstance(recovery, Mapping)
    path = f"$.surfaces[{index}].recovery"

    if kind == "claude_skill_entry":
        entry_type = observation.get("entry_type")
        if entry_type == "absent":
            valid = recovery == {"kind": "none", "reason": "absent_noop"}
        else:
            valid = recovery.get("kind") == "private_blob"
        return (
            []
            if valid
            else [
                _diagnostic(
                    "CLAUDE_SKILL_RECOVERY_MISMATCH",
                    path,
                    "An absent Claude skill uses absent-noop recovery; a present entry requires sealed private recovery material.",
                )
            ]
        )

    if kind in {"mcp_selection", "plugin_selection"}:
        present = observation.get("present")
        if present is False:
            valid = recovery == {"kind": "none", "reason": "absent_noop"}
        else:
            valid = recovery.get("kind") == "private_blob"
        return (
            []
            if valid
            else [
                _diagnostic(
                    "SELECTION_RECOVERY_MISMATCH",
                    path,
                    "An absent selection uses absent-noop recovery; present secret-redacted state requires sealed private recovery material.",
                )
            ]
        )

    if kind in {"plugin_enablement", "legacy_projector"}:
        valid = recovery.get("kind") in {"structured_snapshot", "private_blob"}
        if (
            kind == "plugin_enablement"
            and observation.get("applicable") is False
            and observation.get("reason") == "not_installed"
        ):
            valid = recovery == {"kind": "none", "reason": "absent_noop"}
        return (
            []
            if valid
            else [
                _diagnostic(
                    "STRUCTURED_SURFACE_RECOVERY_MISMATCH",
                    path,
                    "A present structured mutable surface requires a bound structured or private recovery snapshot.",
                )
            ]
        )
    return []


def _validate_plan_action_evidence(
    evidence_records: Sequence[JsonObject],
    candidate_identity: str,
    implementation_manifest_digest: str,
    plan_digest: str,
) -> tuple[
    list[Diagnostic],
    dict[str, tuple[JsonObject, JsonObject]],
    set[str],
]:
    diagnostics: list[Diagnostic] = []
    evidence_by_identity: dict[str, tuple[JsonObject, JsonObject]] = {}
    valid_identities: set[str] = set()
    seen_digests: set[str] = set()
    order: list[tuple[int, str]] = []

    for index, evidence in enumerate(evidence_records):
        payload = evidence["action_payload"]
        assert isinstance(payload, Mapping)
        action_identity = payload["action_identity"]
        ordinal = payload["ordinal"]
        action_digest = evidence["action_digest"]
        assert isinstance(action_identity, str)
        assert isinstance(ordinal, int)
        assert isinstance(action_digest, str)
        path = f"$.authoritative_plan_action_set.actions[{index}]"
        order.append((ordinal, action_identity))
        valid = True

        if action_identity in evidence_by_identity:
            diagnostics.append(
                _diagnostic(
                    "DUPLICATE_PLAN_ACTION_IDENTITY",
                    f"{path}.action_payload.action_identity",
                    "Authoritative plan-action identities must be unique.",
                )
            )
            valid = False
        else:
            evidence_by_identity[action_identity] = (evidence, payload)

        if action_digest in seen_digests:
            diagnostics.append(
                _diagnostic(
                    "DUPLICATE_PLAN_ACTION_DIGEST",
                    f"{path}.action_digest",
                    "Authoritative plan-action digests must be unique.",
                )
            )
            valid = False
        seen_digests.add(action_digest)

        desired_state = payload["desired_state"]
        desired_state_digest = payload["desired_state_digest"]
        assert isinstance(desired_state_digest, str)
        if desired_state_digest != (
            f"sha256:{hashlib.sha256(_canonical_bytes(desired_state)).hexdigest()}"
        ):
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_DESIRED_STATE_DIGEST_MISMATCH",
                    f"{path}.action_payload.desired_state_digest",
                    "The desired-state digest does not match the authoritative action payload.",
                )
            )
            valid = False

        write_targets = payload["write_targets"]
        assert isinstance(write_targets, list)
        for target_index, write_target in enumerate(write_targets):
            assert isinstance(write_target, Mapping)
            if write_target["target_identity"] != write_target_identity(
                write_target
            ):
                diagnostics.append(
                    _diagnostic(
                        "PLAN_ACTION_WRITE_TARGET_IDENTITY_MISMATCH",
                        f"{path}.action_payload.write_targets[{target_index}].target_identity",
                        "The physical write-target identity must match its closed canonical descriptor.",
                    )
                )
                valid = False

        provider = payload["provider"]
        secret_references = payload["secret_references"]
        assert isinstance(provider, Mapping)
        assert isinstance(secret_references, list)
        declared_secret_references = {
            (str(reference["kind"]), str(reference["name"]))
            for reference in secret_references
            if isinstance(reference, Mapping)
        }
        if _provider_secret_reference_keys(provider) != declared_secret_references:
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_SECRET_REFERENCE_BINDING_MISMATCH",
                    f"{path}.action_payload.secret_references",
                    "The action must declare exactly the secret-reference names consumed by its provider arguments.",
                )
            )
            valid = False

        if action_identity != plan_action_identity(payload):
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_IDENTITY_MISMATCH",
                    f"{path}.action_payload.action_identity",
                    "The action identity does not match its canonical plan coordinates.",
                )
            )
            valid = False

        if action_digest != plan_action_digest(payload):
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_DIGEST_MISMATCH",
                    f"{path}.action_digest",
                    "The action digest does not match the closed canonical action payload.",
                )
            )
            valid = False

        if payload["plan_digest"] != plan_digest:
            diagnostics.append(
                _diagnostic(
                    "FORWARD_ACTION_PLAN_DIGEST_MISMATCH",
                    f"{path}.action_payload.plan_digest",
                    "Authoritative action evidence must be bound to its plan digest.",
                )
            )
            valid = False

        if payload["candidate_identity"] != candidate_identity:
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_CANDIDATE_IDENTITY_MISMATCH",
                    f"{path}.action_payload.candidate_identity",
                    "Authoritative action evidence must name the action set's exact implementation candidate.",
                )
            )
            valid = False

        if (
            payload["implementation_manifest_digest"]
            != implementation_manifest_digest
        ):
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_IMPLEMENTATION_MANIFEST_DIGEST_MISMATCH",
                    f"{path}.action_payload.implementation_manifest_digest",
                    "Authoritative action evidence must bind the action set's exact installed implementation manifest.",
                )
            )
            valid = False

        if valid:
            valid_identities.add(action_identity)

    if order != sorted(order):
        diagnostics.append(
            _diagnostic(
                "PLAN_ACTION_EVIDENCE_NOT_SORTED",
                "$.authoritative_plan_action_set.actions",
                "Authoritative plan actions must be ordered by ordinal and identity.",
            )
        )

    return diagnostics, evidence_by_identity, valid_identities


def _resolve_plan_action(
    *,
    route: JsonObject,
    route_index: int,
    reference_index: int,
    reference: JsonObject,
    evidence_by_identity: Mapping[str, tuple[JsonObject, JsonObject]],
    valid_identities: set[str],
) -> tuple[JsonObject | None, list[Diagnostic]]:
    action_identity = reference["action_identity"]
    action_digest = reference["action_digest"]
    assert isinstance(action_identity, str)
    assert isinstance(action_digest, str)
    path = f"$.provider_routes[{route_index}].planned_actions[{reference_index}]"
    resolved = evidence_by_identity.get(action_identity)
    if resolved is None:
        return None, [
            _diagnostic(
                "FORWARD_ACTION_IDENTITY_UNKNOWN",
                f"{path}.action_identity",
                "The planned action identity is absent from the authoritative plan-action set.",
            )
        ]

    evidence, payload = resolved
    if evidence["action_digest"] != action_digest:
        return None, [
            _diagnostic(
                "FORWARD_ACTION_DIGEST_MISMATCH",
                f"{path}.action_digest",
                "The planned action digest does not match the authoritative plan-action set.",
            )
        ]

    diagnostics: list[Diagnostic] = []
    if action_identity not in valid_identities:
        diagnostics.append(
            _diagnostic(
                "FORWARD_ACTION_EVIDENCE_INVALID",
                path,
                "The referenced planned action failed canonical evidence validation.",
            )
        )
    if payload["route_identity"] != route["route_id"]:
        diagnostics.append(
            _diagnostic(
                "FORWARD_ACTION_ROUTE_MISMATCH",
                path,
                "The planned action is bound to a different provider route.",
            )
        )
    if payload["route_digest"] != route["route_digest"]:
        diagnostics.append(
            _diagnostic(
                "FORWARD_ACTION_ROUTE_DIGEST_MISMATCH",
                path,
                "The planned action route digest does not match the captured route.",
            )
        )
    if payload["harness"] != route["harness"]:
        diagnostics.append(
            _diagnostic(
                "PLAN_ACTION_HARNESS_MISMATCH",
                path,
                "The planned action harness does not match the captured route.",
            )
        )
    if (
        payload["equipment_identities"] != sorted(route["equipment_identities"])
        or payload["controlled_equipment_identities"]
        != sorted(route["controlled_equipment_identities"])
    ):
        diagnostics.append(
            _diagnostic(
                "PLAN_ACTION_EQUIPMENT_MISMATCH",
                path,
                    "The planned action active and controlled equipment sets do not match the captured route.",
            )
        )
    if route.get("control_owner") != "reconciler_owned":
        diagnostics.append(
            _diagnostic(
                "AUTOMATED_ACTION_ROUTE_OWNERSHIP_INVALID",
                path,
                "Only a reconciler-owned route may reference an automated action.",
            )
        )

    return (payload if not diagnostics else None), diagnostics


def _validate_native_installation_route(
    *,
    route: JsonObject,
    route_index: int,
    resolved_forward_action: JsonObject | None,
    resolved_forward_action_reference: JsonObject | None,
    has_forward_install_reference: bool,
    surface_by_id: Mapping[str, JsonObject],
    surface_index_by_id: Mapping[str, int],
    installation_surfaces_by_route: Mapping[str, Sequence[JsonObject]],
) -> list[Diagnostic]:
    restore_evidence = route["restore_evidence"]
    assert isinstance(restore_evidence, Mapping)
    diagnostics: list[Diagnostic] = []
    path = f"$.provider_routes[{route_index}]"
    forward_action_reference = has_forward_install_reference

    references = route["surface_references"]
    assert isinstance(references, Mapping)
    installation_reference = references["installation"]
    assert isinstance(installation_reference, Mapping)
    route_id = route["route_id"]
    assert isinstance(route_id, str)
    route_installations = installation_surfaces_by_route.get(route_id, ())
    requires_installation = (
        restore_evidence.get("restore_class") == "native_rolling"
        or forward_action_reference
        or bool(route_installations)
    )
    if installation_reference.get("status") != "captured" or not isinstance(
        installation_reference.get("surface_id"), str
    ):
        if requires_installation:
            diagnostics.append(
                _diagnostic(
                    "NATIVE_INSTALLATION_REFERENCE_REQUIRED",
                    f"{path}.surface_references.installation",
                    "A native route must reference its captured plugin installation surface.",
                )
            )
        for installation in route_installations:
            recovery = installation["recovery"]
            observation = installation["observation"]
            assert isinstance(recovery, Mapping)
            assert isinstance(observation, Mapping)
            if not _is_native_remove_inverse(recovery):
                continue
            surface_index = surface_index_by_id.get(
                str(installation["surface_id"]),
                0,
            )
            recovery_path = f"$.surfaces[{surface_index}].recovery"
            if resolved_forward_action is None:
                diagnostics.append(
                    _diagnostic(
                        "NATIVE_REMOVE_INVERSE_UNBOUND",
                        recovery_path,
                        "Remove compensation requires a referenced canonical forward install.",
                    )
                )
            if observation.get("installed") is not False:
                diagnostics.append(
                    _diagnostic(
                        "NATIVE_REMOVE_INVERSE_REQUIRES_ABSENCE",
                        recovery_path,
                        "Native remove compensation is valid only for captured absence.",
                    )
                )
            if restore_evidence.get("restore_class") != "native_rolling":
                diagnostics.append(
                    _diagnostic(
                        "NATIVE_REMOVE_INVERSE_RESTORE_CLASS_INVALID",
                        recovery_path,
                        "Native remove compensation requires native-rolling absence evidence.",
                    )
                )
        return diagnostics

    installation = surface_by_id.get(installation_reference["surface_id"])
    if (
        installation is None
        or installation.get("kind") != "plugin_installation"
        or installation.get("route_id") != route.get("route_id")
    ):
        return diagnostics

    installation_index = surface_index_by_id.get(
        str(installation_reference["surface_id"])
    )
    if installation_index is None:
        return diagnostics

    observation = installation["observation"]
    recovery = installation["recovery"]
    assert isinstance(observation, Mapping)
    assert isinstance(recovery, Mapping)
    remove_inverse = _is_native_remove_inverse(recovery)
    installation_path = f"$.surfaces[{installation_index}].observation"
    recovery_path = f"$.surfaces[{installation_index}].recovery"

    if resolved_forward_action is not None:
        provider = resolved_forward_action.get("provider")
        locator = installation.get("locator")
        if not (
            isinstance(provider, Mapping)
            and provider.get("kind") == "native_plugin"
            and isinstance(locator, Mapping)
            and locator
            == {
                "manager": provider.get("manager"),
                "native_identity": provider.get("plugin_id"),
                "scope": provider.get("scope"),
            }
        ):
            diagnostics.append(
                _diagnostic(
                    "FORWARD_ACTION_INSTALLATION_LOCATOR_MISMATCH",
                    f"$.surfaces[{installation_index}].locator",
                    "The captured native installation locator must exactly match the plan-authorized provider target.",
                )
            )
        action_owns_installation = False
        if isinstance(resolved_forward_action_reference, Mapping):
            targets = resolved_forward_action.get("write_targets")
            bindings = resolved_forward_action_reference.get("write_bindings")
            if isinstance(targets, list) and isinstance(bindings, list):
                target_by_identity = {
                    str(target["target_identity"]): target
                    for target in targets
                    if isinstance(target, Mapping)
                }
                action_owns_installation = any(
                    isinstance(binding, Mapping)
                    and binding.get("surface_id")
                    == installation_reference["surface_id"]
                    and isinstance(
                        target_by_identity.get(str(binding.get("target_identity"))),
                        Mapping,
                    )
                    and target_by_identity[str(binding.get("target_identity"))].get(
                        "surface_kind"
                    )
                    == "plugin_installation"
                    and target_by_identity[str(binding.get("target_identity"))].get(
                        "locator"
                    )
                    == installation.get("locator")
                    for binding in bindings
                )
        if remove_inverse and not action_owns_installation:
            diagnostics.append(
                _diagnostic(
                    "NATIVE_REMOVE_INVERSE_INSTALL_ACTION_OWNERSHIP_MISMATCH",
                    recovery_path,
                    "Native remove compensation requires the same install action to own this exact captured installation target.",
                )
            )

    if forward_action_reference and resolved_forward_action is None:
        if remove_inverse:
            diagnostics.append(
                _diagnostic(
                    "NATIVE_REMOVE_INVERSE_UNBOUND",
                    recovery_path,
                    "Remove compensation requires resolved canonical forward-install evidence.",
                )
            )
    if forward_action_reference and observation.get("installed") is not False:
        diagnostics.append(
            _diagnostic(
                "NATIVE_FORWARD_INSTALL_REQUIRES_ABSENCE",
                installation_path,
                "A forward install action requires a captured absent installation.",
            )
        )
    if remove_inverse and observation.get("installed") is not False:
        diagnostics.append(
            _diagnostic(
                "NATIVE_REMOVE_INVERSE_REQUIRES_ABSENCE",
                recovery_path,
                "Native remove compensation is valid only for captured absence.",
            )
        )
    if (
        remove_inverse
        and resolved_forward_action is not None
        and recovery.get("expected_pre_state_digest")
        != resolved_forward_action.get("expected_post_state_digest")
    ):
        diagnostics.append(
            _diagnostic(
                "NATIVE_REMOVE_INVERSE_GUARD_MISMATCH",
                f"{recovery_path}.expected_pre_state_digest",
                "The remove inverse guard must equal the resolved forward install's normalized full expected-post-state digest.",
            )
        )

    if restore_evidence.get("restore_class") != "native_rolling":
        if forward_action_reference:
            diagnostics.append(
                _diagnostic(
                    "NATIVE_FORWARD_INSTALL_RESTORE_CLASS_INVALID",
                    f"{path}.restore_evidence.restore_class",
                    "Forward native install evidence requires native-rolling absence evidence.",
                )
            )
        if remove_inverse:
            diagnostics.append(
                _diagnostic(
                    "NATIVE_REMOVE_INVERSE_RESTORE_CLASS_INVALID",
                    recovery_path,
                    "Native remove compensation requires native-rolling absence evidence.",
                )
            )
        return diagnostics

    observed_version = restore_evidence.get("observed_version")
    if not isinstance(observed_version, Mapping):
        return [
            *diagnostics,
            _diagnostic(
                "CAPTURED_STATE_STRUCTURE_INVALID",
                f"{path}.restore_evidence.observed_version",
                "Native restore evidence is incomplete for semantic validation.",
            ),
        ]
    version_status = observed_version.get("status")

    if version_status == "route_absent":
        if observation.get("installed") is not False:
            diagnostics.append(
                _diagnostic(
                    "NATIVE_INSTALLATION_PRESENCE_MISMATCH",
                    installation_path,
                    "Route-absent restore evidence requires an absent installation observation.",
                )
            )

        if not forward_action_reference:
            if remove_inverse:
                diagnostics.append(
                    _diagnostic(
                        "NATIVE_REMOVE_INVERSE_UNBOUND",
                        recovery_path,
                        "Remove compensation requires an exact plan-bound forward install action.",
                    )
                )
            elif recovery != {"kind": "none", "reason": "absent_noop"}:
                diagnostics.append(
                    _diagnostic(
                        "NATIVE_INSTALLATION_RECOVERY_MISMATCH",
                        recovery_path,
                        "An unchanged absent installation requires absent-noop recovery.",
                    )
                )
        elif resolved_forward_action is not None and not remove_inverse:
            diagnostics.append(
                _diagnostic(
                    "NATIVE_INSTALLATION_RECOVERY_MISMATCH",
                    recovery_path,
                    "A plan-bound forward install requires guarded native remove compensation.",
                )
            )
        return diagnostics

    if version_status != "observed":
        diagnostics.append(
            _diagnostic(
                "CAPTURED_STATE_STRUCTURE_INVALID",
                f"{path}.restore_evidence.observed_version.status",
                "Native restore evidence has an unsupported version status.",
            )
        )
        return diagnostics

    if observation.get("installed") is not True:
        diagnostics.append(
            _diagnostic(
                "NATIVE_INSTALLATION_PRESENCE_MISMATCH",
                installation_path,
                "Observed native version evidence requires a present installation observation.",
            )
        )
    else:
        comparisons = (
            (
                "observed_version",
                observed_version.get("value"),
                "NATIVE_INSTALLATION_VERSION_MISMATCH",
                "The installation version must match native restore evidence.",
            ),
            (
                "channel",
                restore_evidence.get("channel"),
                "NATIVE_INSTALLATION_CHANNEL_MISMATCH",
                "The installation channel must match native restore evidence.",
            ),
            (
                "observation_source",
                restore_evidence.get("observation_source"),
                "NATIVE_INSTALLATION_SOURCE_MISMATCH",
                "The installation source must match native restore evidence.",
            ),
        )
        for field, expected, code, message in comparisons:
            if observation.get(field) != expected:
                diagnostics.append(
                    _diagnostic(code, f"{installation_path}.{field}", message)
                )

    expected_recovery = {
        "kind": "none",
        "reason": (
            "operator_owned"
            if route.get("control_owner") == "operator_owned"
            else "already_desired"
        ),
    }
    if recovery != expected_recovery:
        diagnostics.append(
            _diagnostic(
                "NATIVE_INSTALLATION_RECOVERY_MISMATCH",
                recovery_path,
                "A pre-existing native installation requires non-mutating recovery evidence.",
            )
        )
    return diagnostics


def _validate_action_capture_binding(
    *,
    route: JsonObject,
    route_index: int,
    payload: JsonObject,
    action_reference: JsonObject,
    bindings: JsonObject,
    surface_by_id: Mapping[str, JsonObject],
    write_counts: dict[str, int],
    dependency_read_counts: dict[str, int],
    dependency_write_counts: dict[str, int],
) -> list[Diagnostic]:
    """Bind one complete automated action projection to its captured surfaces."""

    diagnostics: list[Diagnostic] = []
    path = f"$.provider_routes[{route_index}].planned_actions"
    route_binding = route["capability_binding"]
    assert isinstance(route_binding, Mapping)
    preconditions = payload["preconditions"]
    assert isinstance(preconditions, Mapping)

    expected_projection_values = {
        "catalog_digest": bindings["catalog_digest"],
        "lock_digest": bindings["lock_digest"],
        "plan_digest": bindings["plan_digest"],
        "route_digest": route["route_digest"],
        "capability_identity": route_binding["capability_identity"],
        "capability_digest": route_binding["capability_digest"],
        "manager_version_evidence_digest": route_binding[
            "manager_version_evidence_digest"
        ],
        "harness": route["harness"],
    }
    for field, expected in expected_projection_values.items():
        if payload.get(field) != expected:
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_AUTHORITY_BINDING_MISMATCH",
                    f"{path}.{field}",
                    "The automated action projection does not match captured route authority.",
                )
            )

    precondition_projection_fields = (
        "candidate_identity",
        "implementation_manifest_digest",
        "catalog_digest",
        "lock_digest",
        "plan_digest",
        "route_digest",
        "capability_digest",
        "manager_version_evidence_digest",
        "adapter_identity",
        "adapter_version",
        "activation_group",
        "surface_scope",
    )
    for field in precondition_projection_fields:
        if preconditions.get(field) != payload.get(field):
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_PRECONDITION_BINDING_MISMATCH",
                    f"{path}.preconditions.{field}",
                    "The action precondition must exactly repeat its projected authority field.",
                )
            )
    if preconditions.get("control_owner") != route.get("control_owner"):
        diagnostics.append(
            _diagnostic(
                "PLAN_ACTION_PRECONDITION_BINDING_MISMATCH",
                f"{path}.preconditions.control_owner",
                "The action precondition must match captured route ownership.",
            )
        )

    route_reference_ids = {
        surface_id for _, surface_id in _captured_references(route)
    }
    provider = payload["provider"]
    assert isinstance(provider, Mapping)
    if provider.get("kind") == "native_plugin":
        references = route["surface_references"]
        assert isinstance(references, Mapping)
        installation_reference = references["installation"]
        assert isinstance(installation_reference, Mapping)
        installation = surface_by_id.get(
            str(installation_reference.get("surface_id", ""))
        )
        expected_locator = {
            "manager": provider.get("manager"),
            "native_identity": provider.get("plugin_id"),
            "scope": provider.get("scope"),
        }
        if (
            installation_reference.get("status") != "captured"
            or installation is None
            or installation.get("kind") != "plugin_installation"
            or installation.get("locator") != expected_locator
        ):
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_NATIVE_TARGET_MISMATCH",
                    f"{path}.provider",
                    "A native action's provider target must exactly match its captured installation surface.",
                )
            )
        restore_evidence = route["restore_evidence"]
        assert isinstance(restore_evidence, Mapping)
        if (
            restore_evidence.get("restore_class") == "native_rolling"
            and payload.get("operation") == "remove"
        ):
            diagnostics.append(
                _diagnostic(
                    "NATIVE_ROLLING_REMOVE_AUTOMATION_INVALID",
                    f"{path}.operation",
                    "A native-rolling plugin route cannot automate general removal.",
                )
            )
    surface_scope = payload["surface_scope"]
    assert isinstance(surface_scope, list)
    write_targets = payload["write_targets"]
    assert isinstance(write_targets, list)
    target_by_identity = {
        str(target["target_identity"]): target
        for target in write_targets
        if isinstance(target, Mapping)
    }
    write_bindings = action_reference["write_bindings"]
    assert isinstance(write_bindings, list)
    write_surface_ids_by_identity: dict[str, list[str]] = {}
    bound_target_identities: set[str] = set()
    for binding_index, binding in enumerate(write_bindings):
        assert isinstance(binding, Mapping)
        target_identity = str(binding["target_identity"])
        surface_id = str(binding["surface_id"])
        target = target_by_identity.get(target_identity)
        if target_identity in bound_target_identities:
            diagnostics.append(
                _diagnostic(
                    "DUPLICATE_ACTION_WRITE_BINDING",
                    f"{path}.write_bindings[{binding_index}]",
                    "Each authoritative physical write target may have only one captured surface binding.",
                )
            )
        bound_target_identities.add(target_identity)
        if target is None:
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_WRITE_TARGET_UNKNOWN",
                    f"{path}.write_bindings[{binding_index}].target_identity",
                    "A captured write binding must resolve to an authoritative physical target.",
                )
            )
            continue
        write_surface_identity = str(target["write_surface_identity"])
        write_surface_ids_by_identity.setdefault(
            write_surface_identity,
            [],
        ).append(surface_id)
        write_counts[surface_id] = write_counts.get(surface_id, 0) + 1
        surface = surface_by_id.get(surface_id)
        if surface is None:
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_WRITE_SURFACE_DANGLING",
                    f"{path}.write_bindings[{binding_index}]",
                    "Every capture-bound write surface must resolve to captured state.",
                )
            )
            continue
        if surface_id not in route_reference_ids:
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_WRITE_SURFACE_UNREFERENCED",
                    f"{path}.write_bindings[{binding_index}]",
                    "Every capture-bound write surface must occupy its captured route slot.",
                )
            )
        if surface.get("route_id") != route.get("route_id"):
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_WRITE_SURFACE_ROUTE_MISMATCH",
                    f"{path}.write_bindings[{binding_index}]",
                    "A capture-bound write surface must belong to the action's route.",
                )
            )
        if surface.get("mutation_policy") != "reconciler_owned":
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_WRITE_SURFACE_OWNERSHIP_INVALID",
                    f"{path}.write_bindings[{binding_index}]",
                    "An automated action may write only reconciler-owned captured surfaces.",
                )
            )
        expected_equipment = target.get("equipment_identity")
        if not (
            surface.get("kind") == target.get("surface_kind")
            and surface.get("locator") == target.get("locator")
            and (
                expected_equipment is None
                or surface.get("equipment_identity") == expected_equipment
            )
        ):
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_WRITE_TARGET_MISMATCH",
                    f"{path}.write_bindings[{binding_index}]",
                    "The captured physical write surface must exactly match its authoritative kind, equipment, and locator target.",
                )
            )

    if bound_target_identities != set(target_by_identity):
        diagnostics.append(
            _diagnostic(
                "PLAN_ACTION_WRITE_TARGET_BINDING_SET_MISMATCH",
                f"{path}.write_bindings",
                "Captured write bindings must cover every authoritative physical target exactly once.",
            )
        )
    if sorted({str(target["write_surface_identity"]) for target in write_targets}) != surface_scope:
        diagnostics.append(
            _diagnostic(
                "PLAN_ACTION_WRITE_BINDING_SCOPE_MISMATCH",
                f"{path}.write_targets",
                "Authoritative physical targets must cover each logical action surface identity exactly.",
            )
        )

    dependencies = payload["verification_dependencies"]
    assert isinstance(dependencies, list)
    dependency_bindings = action_reference["verification_dependency_bindings"]
    assert isinstance(dependency_bindings, list)
    dependency_surface_by_identity: dict[str, str] = {}
    for binding_index, binding in enumerate(dependency_bindings):
        assert isinstance(binding, Mapping)
        dependency_identity = str(binding["dependency_identity"])
        if dependency_identity in dependency_surface_by_identity:
            diagnostics.append(
                _diagnostic(
                    "DUPLICATE_VERIFICATION_DEPENDENCY_BINDING",
                    f"{path}.verification_dependency_bindings[{binding_index}]",
                    "Each authoritative verification dependency may have only one captured read binding.",
                )
            )
        else:
            dependency_surface_by_identity[dependency_identity] = str(
                binding["surface_id"]
            )
    dependency_identities = [
        str(dependency["dependency_identity"])
        for dependency in dependencies
        if isinstance(dependency, Mapping)
    ]
    if sorted(dependency_surface_by_identity) != sorted(dependency_identities):
        diagnostics.append(
            _diagnostic(
                "VERIFICATION_DEPENDENCY_BINDING_SET_MISMATCH",
                f"{path}.verification_dependency_bindings",
                "Captured read bindings must cover every authoritative verification dependency exactly once.",
            )
        )
    for dependency in dependencies:
        assert isinstance(dependency, Mapping)
        dependency_identity = str(dependency["dependency_identity"])
        read_id = dependency_surface_by_identity.get(dependency_identity, "")
        logical_write_id = str(dependency["write_surface_identity"])
        logical_write_surface_ids = write_surface_ids_by_identity.get(
            logical_write_id,
            [],
        )
        dependency_read_counts[read_id] = dependency_read_counts.get(read_id, 0) + 1
        read_surface = surface_by_id.get(read_id)
        claude_write_surfaces = [
            surface_by_id[surface_id]
            for surface_id in logical_write_surface_ids
            if surface_id in surface_by_id
            and surface_by_id[surface_id].get("kind") == "claude_skill_entry"
        ]
        write_surface = (
            claude_write_surfaces[0]
            if len(claude_write_surfaces) == 1
            else None
        )
        write_id = (
            str(write_surface["surface_id"])
            if write_surface is not None
            else ""
        )
        if write_id:
            dependency_write_counts[write_id] = (
                dependency_write_counts.get(write_id, 0) + 1
            )
        if read_surface is None:
            diagnostics.append(
                _diagnostic(
                    "CANONICAL_DEPENDENCY_DANGLING",
                    f"{path}.verification_dependencies",
                    "The canonical verification dependency is absent from captured state.",
                )
            )
            continue
        if write_surface is None:
            diagnostics.append(
                _diagnostic(
                    "CANONICAL_DEPENDENCY_WRITE_DANGLING",
                    f"{path}.verification_dependencies",
                    "The canonical dependency's Claude projection is absent from captured state.",
                )
            )
            continue
        read_locator = read_surface.get("locator")
        write_locator = write_surface.get("locator")
        target_locator = dependency.get("target_locator")
        coherent = (
            read_surface.get("kind") == "canonical_skill_entry"
            and read_surface.get("mutation_policy") == "forbidden"
            and write_surface.get("kind") == "claude_skill_entry"
            and read_id in route_reference_ids
            and read_surface.get("route_id") == route.get("route_id")
            and write_surface.get("route_id") == route.get("route_id")
            and read_surface.get("equipment_identity")
            == dependency.get("equipment_identity")
            == write_surface.get("equipment_identity")
            and isinstance(read_locator, Mapping)
            and isinstance(write_locator, Mapping)
            and isinstance(target_locator, Mapping)
            and read_locator == target_locator
            and str(read_locator.get("path", "")).removeprefix(
                "~/.agents/skills/"
            )
            == str(write_locator.get("path", "")).removeprefix(
                "~/.claude/skills/"
            )
        )
        if not coherent:
            diagnostics.append(
                _diagnostic(
                    "CANONICAL_DEPENDENCY_MISMATCH",
                    f"{path}.verification_dependencies",
                    "A Claude skill write must bind the same route and equipment to its exact verification-only canonical target.",
                )
            )

    return diagnostics


def validate_captured_state(
    document: object,
    authoritative_plan_action_set: object,
    *,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
) -> tuple[Diagnostic, ...]:
    """Validate captured semantics against an independently validated action set."""

    if (
        not isinstance(expected_candidate_identity, str)
        or not expected_candidate_identity
    ):
        return (
            _diagnostic(
                "TRUSTED_CANDIDATE_BINDING_INVALID",
                "$.trusted_candidate.candidate_identity",
                "The executor must supply a nonempty trusted candidate identity.",
            ),
        )
    if (
        not isinstance(expected_implementation_manifest_digest, str)
        or not re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            expected_implementation_manifest_digest,
        )
    ):
        return (
            _diagnostic(
                "TRUSTED_CANDIDATE_BINDING_INVALID",
                "$.trusted_candidate.implementation_manifest_digest",
                "The executor must supply a canonical trusted implementation-manifest digest.",
            ),
        )

    captured_schema_diagnostic = _schema_gate_diagnostic(
        document,
        schema_name="captured-state-v1.schema.json",
        code="CAPTURED_STATE_SCHEMA_INVALID",
        label="captured-state manifest",
        path="$",
    )
    if captured_schema_diagnostic is not None:
        return (captured_schema_diagnostic,)

    plan_action_schema_diagnostic = _schema_gate_diagnostic(
        authoritative_plan_action_set,
        schema_name="plan-action-set-v1.schema.json",
        code="AUTHORITATIVE_PLAN_ACTION_SET_SCHEMA_INVALID",
        label="authoritative plan-action set",
        path="$.authoritative_plan_action_set",
    )
    if plan_action_schema_diagnostic is not None:
        return (plan_action_schema_diagnostic,)

    if contains_literal_credential(document):
        return (
            _diagnostic(
                "CAPTURED_STATE_LITERAL_SECRET",
                "$",
                "The captured-state manifest contains credential-shaped literal material.",
            ),
        )
    if contains_literal_credential(authoritative_plan_action_set):
        return (
            _diagnostic(
                "AUTHORITATIVE_PLAN_ACTION_SET_LITERAL_SECRET",
                "$.authoritative_plan_action_set",
                "The authoritative plan-action set contains credential-shaped literal material.",
            ),
        )

    if not _has_semantic_structure(document):
        return (
            _diagnostic(
                "CAPTURED_STATE_STRUCTURE_INVALID",
                "$",
                "Captured state does not have the structure required for semantic validation.",
            ),
        )

    if not _has_authoritative_plan_action_set_shape(
        authoritative_plan_action_set
    ):
        return (
            _diagnostic(
                "AUTHORITATIVE_PLAN_ACTION_SET_INVALID",
                "$.authoritative_plan_action_set",
                "The authoritative plan-action set does not have the closed v1 structure.",
            ),
        )

    assert isinstance(document, Mapping)
    assert isinstance(authoritative_plan_action_set, Mapping)
    bindings = document["bindings"]
    routes = document["provider_routes"]
    surfaces = document["surfaces"]
    authoritative_actions = authoritative_plan_action_set["actions"]
    assert isinstance(bindings, Mapping)
    assert isinstance(routes, list)
    assert isinstance(surfaces, list)
    assert isinstance(authoritative_actions, list)
    capability_bindings = bindings["capability_bindings"]
    assert isinstance(capability_bindings, list)

    diagnostics: list[Diagnostic] = []
    authoritative_candidate_identity = authoritative_plan_action_set[
        "candidate_identity"
    ]
    authoritative_implementation_manifest_digest = authoritative_plan_action_set[
        "implementation_manifest_digest"
    ]
    authoritative_plan_digest = authoritative_plan_action_set["plan_digest"]
    authoritative_action_set_digest = authoritative_plan_action_set[
        "action_set_digest"
    ]
    assert isinstance(authoritative_candidate_identity, str)
    assert isinstance(authoritative_implementation_manifest_digest, str)
    assert isinstance(authoritative_plan_digest, str)
    assert isinstance(authoritative_action_set_digest, str)
    computed_action_set_digest = plan_action_set_digest(
        authoritative_candidate_identity,
        authoritative_implementation_manifest_digest,
        authoritative_plan_digest,
        authoritative_actions,
    )
    action_set_digest_valid = (
        authoritative_action_set_digest == computed_action_set_digest
    )
    plan_binding_valid = authoritative_plan_digest == bindings["plan_digest"]
    candidate_binding_valid = (
        authoritative_candidate_identity == bindings["candidate_identity"]
    )
    implementation_manifest_binding_valid = (
        authoritative_implementation_manifest_digest
        == bindings["implementation_manifest_digest"]
    )
    trusted_candidate_binding_valid = (
        authoritative_candidate_identity == expected_candidate_identity
        and bindings["candidate_identity"] == expected_candidate_identity
    )
    trusted_implementation_manifest_binding_valid = (
        authoritative_implementation_manifest_digest
        == expected_implementation_manifest_digest
        and bindings["implementation_manifest_digest"]
        == expected_implementation_manifest_digest
    )
    action_set_binding_valid = (
        bindings["plan_action_set_digest"] == computed_action_set_digest
    )
    if not action_set_digest_valid:
        diagnostics.append(
            _diagnostic(
                "AUTHORITATIVE_PLAN_ACTION_SET_DIGEST_INVALID",
                "$.authoritative_plan_action_set.action_set_digest",
                "The authoritative plan-action-set digest does not match its closed canonical payload.",
            )
        )
    if not plan_binding_valid:
        diagnostics.append(
            _diagnostic(
                "AUTHORITATIVE_PLAN_DIGEST_MISMATCH",
                "$.authoritative_plan_action_set.plan_digest",
                "The authoritative action set and captured state name different plan digests.",
            )
        )
    if not candidate_binding_valid:
        diagnostics.append(
            _diagnostic(
                "CANDIDATE_IDENTITY_MISMATCH",
                "$.bindings.candidate_identity",
                "Captured state and the authoritative action set name different implementation candidates.",
            )
        )
    if not implementation_manifest_binding_valid:
        diagnostics.append(
            _diagnostic(
                "IMPLEMENTATION_MANIFEST_DIGEST_MISMATCH",
                "$.bindings.implementation_manifest_digest",
                "Captured state and the authoritative action set bind different installed implementation manifests.",
            )
        )
    if not trusted_candidate_binding_valid:
        diagnostics.append(
            _diagnostic(
                "TRUSTED_CANDIDATE_IDENTITY_MISMATCH",
                "$.trusted_candidate.candidate_identity",
                "The sealed artifacts do not match the executor-supplied implementation candidate.",
            )
        )
    if not trusted_implementation_manifest_binding_valid:
        diagnostics.append(
            _diagnostic(
                "TRUSTED_IMPLEMENTATION_MANIFEST_DIGEST_MISMATCH",
                "$.trusted_candidate.implementation_manifest_digest",
                "The sealed artifacts do not match the executor-supplied installed implementation manifest.",
            )
        )
    if not action_set_binding_valid:
        diagnostics.append(
            _diagnostic(
                "PLAN_ACTION_SET_DIGEST_MISMATCH",
                "$.bindings.plan_action_set_digest",
                "The captured binding does not match the authoritative plan-action set.",
            )
        )
    (
        action_diagnostics,
        evidence_by_identity,
        valid_action_identities,
    ) = _validate_plan_action_evidence(
        authoritative_actions,
        authoritative_candidate_identity,
        authoritative_implementation_manifest_digest,
        authoritative_plan_digest,
    )
    diagnostics.extend(action_diagnostics)
    if not (
        action_set_digest_valid
        and candidate_binding_valid
        and implementation_manifest_binding_valid
        and trusted_candidate_binding_valid
        and trusted_implementation_manifest_binding_valid
        and plan_binding_valid
        and action_set_binding_valid
    ):
        valid_action_identities.clear()
    binding_keys = [_binding_key(binding) for binding in capability_bindings]
    if binding_keys != sorted(binding_keys):
        diagnostics.append(
            _diagnostic(
                "CAPABILITY_BINDINGS_NOT_SORTED",
                "$.bindings.capability_bindings",
                "Capability bindings must be serialized in canonical identity-first order.",
            )
        )

    seen_identities: set[str] = set()
    seen_bindings: set[tuple[str, str, str]] = set()
    for index, key in enumerate(binding_keys):
        if key[0] in seen_identities:
            diagnostics.append(
                _diagnostic(
                    "DUPLICATE_CAPABILITY_IDENTITY",
                    f"$.bindings.capability_bindings[{index}]",
                    "A capability identity may have only one closed binding.",
                )
            )
        seen_identities.add(key[0])
        if key in seen_bindings:
            diagnostics.append(
                _diagnostic(
                    "DUPLICATE_CAPABILITY_BINDING",
                    f"$.bindings.capability_bindings[{index}]",
                    "The same closed capability binding appears more than once.",
                )
            )
        seen_bindings.add(key)

    if bindings["capability_set_digest"] != capability_set_digest(capability_bindings):
        diagnostics.append(
            _diagnostic(
                "CAPABILITY_SET_DIGEST_MISMATCH",
                "$.bindings.capability_set_digest",
                "The capability-set digest does not match the canonical closed bindings.",
            )
        )

    route_by_id: dict[str, JsonObject] = {}
    for index, route in enumerate(routes):
        assert isinstance(route, Mapping)
        route_id = route["route_id"]
        assert isinstance(route_id, str)
        if route_id in route_by_id:
            diagnostics.append(
                _diagnostic(
                    "DUPLICATE_ROUTE_ID",
                    f"$.provider_routes[{index}].route_id",
                    "Provider route identifiers must be unique.",
                )
            )
        else:
            route_by_id[route_id] = route

        route_binding = route["capability_binding"]
        assert isinstance(route_binding, Mapping)
        if _binding_key(route_binding) not in seen_bindings:
            diagnostics.append(
                _diagnostic(
                    "ROUTE_CAPABILITY_BINDING_UNKNOWN",
                    f"$.provider_routes[{index}].capability_binding",
                    "Provider route capability evidence must match a closed top-level binding.",
                )
            )

    surface_by_id: dict[str, JsonObject] = {}
    surface_index_by_id: dict[str, int] = {}
    logical_surface_by_key: dict[tuple[str, str, str, bytes], int] = {}
    mutable_physical_surface_by_key: dict[tuple[str, bytes], int] = {}
    installation_surfaces_by_route: dict[str, list[JsonObject]] = {}
    singleton_surfaces: dict[tuple[str, str], list[JsonObject]] = {}
    for index, surface in enumerate(surfaces):
        assert isinstance(surface, Mapping)
        surface_id = surface["surface_id"]
        assert isinstance(surface_id, str)
        if surface_id in surface_by_id:
            diagnostics.append(
                _diagnostic(
                    "DUPLICATE_SURFACE_ID",
                    f"$.surfaces[{index}].surface_id",
                    "Captured surface identifiers must be unique.",
                )
            )
        else:
            surface_by_id[surface_id] = surface
            surface_index_by_id[surface_id] = index
        logical_key = _logical_surface_key(surface)
        if logical_key in logical_surface_by_key:
            diagnostics.append(
                _diagnostic(
                    "DUPLICATE_LOGICAL_SURFACE",
                    f"$.surfaces[{index}]",
                    "Captured surfaces must have unique kind, route, locator, and applicable equipment identity.",
                )
            )
        else:
            logical_surface_by_key[logical_key] = index
        if surface.get("mutation_policy") != "forbidden":
            physical_key = (
                str(surface["kind"]),
                _canonical_bytes(surface["locator"]),
            )
            if physical_key in mutable_physical_surface_by_key:
                diagnostics.append(
                    _diagnostic(
                        "DUPLICATE_MUTABLE_PHYSICAL_SURFACE",
                        f"$.surfaces[{index}]",
                        "A mutable physical locator may have only one capture, mutation owner, and recovery record for each surface kind.",
                    )
                )
            else:
                mutable_physical_surface_by_key[physical_key] = index
        if (
            surface.get("kind") in {"plugin_installation", "plugin_enablement"}
            and isinstance(surface.get("route_id"), str)
        ):
            singleton_surfaces.setdefault(
                (str(surface["route_id"]), str(surface["kind"])),
                [],
            ).append(surface)
        if (
            surface.get("kind") == "plugin_installation"
            and isinstance(surface.get("route_id"), str)
        ):
            installation_surfaces_by_route.setdefault(
                surface["route_id"],
                [],
            ).append(surface)

    plan_action_references: set[tuple[str, str]] = set()
    resolved_action_owners: list[
        tuple[int, JsonObject, JsonObject, JsonObject]
    ] = []
    for route_index, route in enumerate(routes):
        assert isinstance(route, Mapping)
        planned_action_references = route["planned_actions"]
        assert isinstance(planned_action_references, list)
        resolved_route_actions: list[JsonObject] = []
        resolved_route_action_pairs: list[tuple[JsonObject, JsonObject]] = []
        install_reference_present = False
        for reference_index, action_reference in enumerate(
            planned_action_references
        ):
            assert isinstance(action_reference, Mapping)
            reference_pair = (
                str(action_reference["action_identity"]),
                str(action_reference["action_digest"]),
            )
            if reference_pair in plan_action_references:
                diagnostics.append(
                    _diagnostic(
                        "DUPLICATE_FORWARD_ACTION_REFERENCE",
                        f"$.provider_routes[{route_index}].planned_actions[{reference_index}]",
                        "An authoritative automated action may have only one captured route owner.",
                    )
                )
            plan_action_references.add(reference_pair)
            resolved_action, action_reference_diagnostics = _resolve_plan_action(
                route=route,
                route_index=route_index,
                reference_index=reference_index,
                reference=action_reference,
                evidence_by_identity=evidence_by_identity,
                valid_identities=valid_action_identities,
            )
            diagnostics.extend(action_reference_diagnostics)
            if resolved_action is not None:
                resolved_route_actions.append(resolved_action)
                resolved_route_action_pairs.append(
                    (resolved_action, action_reference)
                )
                resolved_action_owners.append(
                    (route_index, route, resolved_action, action_reference)
                )
                if resolved_action.get("operation") == "install":
                    install_reference_present = True
        install_actions = [
            (action, reference)
            for action, reference in resolved_route_action_pairs
            if action.get("operation") == "install"
        ]
        if len(install_actions) > 1:
            diagnostics.append(
                _diagnostic(
                    "DUPLICATE_ROUTE_INSTALL_ACTION",
                    f"$.provider_routes[{route_index}].planned_actions",
                    "A provider route may own at most one automated install action.",
                )
            )
        diagnostics.extend(
            _validate_native_installation_route(
                route=route,
                route_index=route_index,
                resolved_forward_action=(
                    install_actions[0][0] if len(install_actions) == 1 else None
                ),
                resolved_forward_action_reference=(
                    install_actions[0][1] if len(install_actions) == 1 else None
                ),
                has_forward_install_reference=install_reference_present,
                surface_by_id=surface_by_id,
                surface_index_by_id=surface_index_by_id,
                installation_surfaces_by_route=installation_surfaces_by_route,
            )
        )

    for action_index, evidence in enumerate(authoritative_actions):
        assert isinstance(evidence, Mapping)
        payload = evidence["action_payload"]
        assert isinstance(payload, Mapping)
        authoritative_reference = (
            str(payload["action_identity"]),
            str(evidence["action_digest"]),
        )
        if authoritative_reference not in plan_action_references:
            diagnostics.append(
                _diagnostic(
                    "AUTHORITATIVE_PLAN_ACTION_UNREFERENCED",
                    (
                        "$.authoritative_plan_action_set.actions"
                        f"[{action_index}]"
                    ),
                    "Every authoritative automated action must have exactly one captured provider-route owner.",
                )
            )

    action_write_counts: dict[str, int] = {}
    dependency_read_counts: dict[str, int] = {}
    dependency_write_counts: dict[str, int] = {}
    for route_index, route, payload, action_reference in resolved_action_owners:
        diagnostics.extend(
            _validate_action_capture_binding(
                route=route,
                route_index=route_index,
                payload=payload,
                action_reference=action_reference,
                bindings=bindings,
                surface_by_id=surface_by_id,
                write_counts=action_write_counts,
                dependency_read_counts=dependency_read_counts,
                dependency_write_counts=dependency_write_counts,
            )
        )

    for index, surface in enumerate(surfaces):
        assert isinstance(surface, Mapping)
        surface_id = str(surface["surface_id"])
        write_count = action_write_counts.get(surface_id, 0)
        if surface.get("mutation_policy") == "reconciler_owned" and write_count != 1:
            diagnostics.append(
                _diagnostic(
                    "MUTABLE_SURFACE_ACTION_OWNERSHIP_MISMATCH",
                    f"$.surfaces[{index}]",
                    "Every reconciler-owned surface must belong to exactly one authoritative automated action.",
                )
            )
        if surface.get("mutation_policy") != "reconciler_owned" and write_count:
            diagnostics.append(
                _diagnostic(
                    "NONRECONCILER_SURFACE_ACTION_OWNERSHIP_INVALID",
                    f"$.surfaces[{index}]",
                    "Forbidden and operator-owned surfaces cannot belong to an automated action's write scope.",
                )
            )
        if surface.get("kind") == "claude_skill_entry" and write_count == 1:
            dependency_count = dependency_write_counts.get(surface_id, 0)
            if dependency_count == 0:
                diagnostics.append(
                    _diagnostic(
                        "CANONICAL_DEPENDENCY_MISSING",
                        f"$.surfaces[{index}]",
                        "A reconciled Claude skill projection requires an action-bound canonical verification dependency.",
                    )
                )
            elif dependency_count != 1:
                diagnostics.append(
                    _diagnostic(
                        "DUPLICATE_CANONICAL_DEPENDENCY",
                        f"$.surfaces[{index}]",
                        "A Claude skill projection must have exactly one canonical dependency.",
                    )
                )
        if (
            surface.get("kind") == "canonical_skill_entry"
            and dependency_read_counts.get(surface_id, 0) > 1
        ):
            diagnostics.append(
                _diagnostic(
                    "DUPLICATE_CANONICAL_DEPENDENCY",
                    f"$.surfaces[{index}]",
                    "A canonical verification surface may be the counterpart of only one Claude projection action.",
                )
            )
        if (
            surface.get("mutation_policy") == "operator_owned"
            and _is_native_remove_inverse(surface["recovery"])
        ):
            diagnostics.append(
                _diagnostic(
                    "OPERATOR_OWNED_NATIVE_INVERSE_INVALID",
                    f"$.surfaces[{index}].recovery",
                    "Operator-owned surfaces cannot carry automated native inverse compensation.",
                )
            )
        diagnostics.extend(_mutable_surface_recovery_diagnostics(surface, index))

    referenced_surface_ids: set[str] = set()
    reference_counts: dict[str, int] = {}
    for route_index, route in enumerate(routes):
        assert isinstance(route, Mapping)
        route_id = route["route_id"]
        for reference_index, (expected_kind, surface_id) in enumerate(
            _captured_references(route)
        ):
            reference_path = (
                f"$.provider_routes[{route_index}].surface_references"
                f"[captured:{reference_index}]"
            )
            if surface_id in referenced_surface_ids:
                diagnostics.append(
                    _diagnostic(
                        "DUPLICATE_SURFACE_REFERENCE",
                        reference_path,
                        "A captured surface may be referenced only once.",
                    )
                )
            referenced_surface_ids.add(surface_id)
            reference_counts[surface_id] = reference_counts.get(surface_id, 0) + 1

            surface = surface_by_id.get(surface_id)
            if surface is None:
                diagnostics.append(
                    _diagnostic(
                        "DANGLING_SURFACE_REFERENCE",
                        reference_path,
                        "A captured reference must resolve to a captured surface.",
                    )
                )
                continue
            if surface.get("kind") != expected_kind:
                diagnostics.append(
                    _diagnostic(
                        "REFERENCE_KIND_MISMATCH",
                        reference_path,
                        "The referenced surface kind does not match its route slot.",
                    )
                )
            if surface.get("route_id") != route_id:
                diagnostics.append(
                    _diagnostic(
                        "SURFACE_ROUTE_MISMATCH",
                        reference_path,
                        "The referenced surface is owned by a different provider route.",
                    )
                )

    for route_index, route in enumerate(routes):
        assert isinstance(route, Mapping)
        references = route["surface_references"]
        assert isinstance(references, Mapping)
        canonical_counts: dict[str, int] = {}
        for reference in references["canonical_skill_dependencies"]:
            assert isinstance(reference, Mapping)
            if reference.get("status") != "captured":
                continue
            surface = surface_by_id.get(str(reference.get("surface_id", "")))
            if surface is None or surface.get("kind") != "canonical_skill_entry":
                continue
            equipment_identity = str(surface.get("equipment_identity", ""))
            canonical_counts[equipment_identity] = (
                canonical_counts.get(equipment_identity, 0) + 1
            )
        route_skill_identities = {
            str(identity)
            for identity in (
                list(route["equipment_identities"])
                + list(route["controlled_equipment_identities"])
            )
            if str(identity).startswith("skill:")
        }
        for equipment_identity in route_skill_identities:
            count = canonical_counts.get(equipment_identity, 0)
            if count == 0:
                diagnostics.append(
                    _diagnostic(
                        "CANONICAL_SKILL_DEPENDENCY_MISSING",
                        f"$.provider_routes[{route_index}].surface_references.canonical_skill_dependencies",
                        "Every routed standalone or projected skill requires one verification-only canonical counterpart.",
                    )
                )
            elif count != 1:
                diagnostics.append(
                    _diagnostic(
                        "DUPLICATE_CANONICAL_SKILL_DEPENDENCY",
                        f"$.provider_routes[{route_index}].surface_references.canonical_skill_dependencies",
                        "Each routed skill must have exactly one canonical counterpart.",
                    )
                )
        for equipment_identity in canonical_counts:
            if equipment_identity not in route_skill_identities:
                diagnostics.append(
                    _diagnostic(
                        "CANONICAL_SKILL_DEPENDENCY_EQUIPMENT_MISMATCH",
                        f"$.provider_routes[{route_index}].surface_references.canonical_skill_dependencies",
                        "A canonical counterpart must name a skill equipment identity controlled by its route.",
                    )
                )

    for route_index, route in enumerate(routes):
        assert isinstance(route, Mapping)
        route_id = str(route["route_id"])
        references = route["surface_references"]
        assert isinstance(references, Mapping)
        for kind, slot in (
            ("plugin_installation", "installation"),
            ("plugin_enablement", "enablement"),
        ):
            candidates = singleton_surfaces.get((route_id, kind), [])
            reference = references[slot]
            assert isinstance(reference, Mapping)
            referenced_id = (
                reference.get("surface_id")
                if reference.get("status") == "captured"
                else None
            )
            candidate_ids = {candidate["surface_id"] for candidate in candidates}
            if len(candidates) > 1 or (
                len(candidates) == 1 and referenced_id not in candidate_ids
            ) or (not candidates and referenced_id is not None):
                diagnostics.append(
                    _diagnostic(
                        "ROUTE_SINGLETON_SURFACE_MISMATCH",
                        f"$.provider_routes[{route_index}].surface_references.{slot}",
                        "Installation and enablement slots must reference their route's only captured surface of that kind.",
                    )
                )

    for index, surface in enumerate(surfaces):
        assert isinstance(surface, Mapping)
        kind = surface["kind"]
        locator = surface["locator"]
        mutation_policy = surface["mutation_policy"]
        assert isinstance(kind, str)
        assert isinstance(locator, Mapping)

        surface_id = str(surface["surface_id"])
        if (
            surface.get("route_id") is not None
            and mutation_policy != "forbidden"
            and reference_counts.get(surface_id, 0) == 0
        ):
            diagnostics.append(
                _diagnostic(
                    "ORPHAN_MUTABLE_SURFACE",
                    f"$.surfaces[{index}]",
                    "Every mutable routed surface must be referenced exactly once from its owning route's kind-specific slot.",
                )
            )

        if kind == "canonical_skill_entry":
            if mutation_policy != "forbidden":
                diagnostics.append(
                    _diagnostic(
                        "CANONICAL_SURFACE_POLICY_INVALID",
                        f"$.surfaces[{index}].mutation_policy",
                        "Canonical skill entries are verification-only and forbid mutation.",
                    )
                )
            if not _is_skill_path(locator.get("path"), "~/.agents/skills/"):
                diagnostics.append(
                    _diagnostic(
                        "CANONICAL_SURFACE_ROOT_INVALID",
                        f"$.surfaces[{index}].locator.path",
                        "Canonical skill entries must be direct children of the canonical skill root.",
                    )
                )
            if surface["recovery"] != {
                "kind": "none",
                "reason": "verification_only",
            }:
                diagnostics.append(
                    _diagnostic(
                        "CANONICAL_SURFACE_RECOVERY_INVALID",
                        f"$.surfaces[{index}].recovery",
                        "Verification-only canonical entries cannot carry mutation recovery material.",
                    )
                )
        elif kind == "claude_skill_entry":
            if mutation_policy not in {"reconciler_owned", "operator_owned"}:
                diagnostics.append(
                    _diagnostic(
                        "CLAUDE_SURFACE_POLICY_INVALID",
                        f"$.surfaces[{index}].mutation_policy",
                        "Claude skill entries require an explicit mutable control owner.",
                    )
                )
            if not _is_skill_path(locator.get("path"), "~/.claude/skills/"):
                diagnostics.append(
                    _diagnostic(
                        "CLAUDE_SURFACE_ROOT_INVALID",
                        f"$.surfaces[{index}].locator.path",
                        "Claude skill entries must be direct children of the Claude skill root.",
                    )
                )

        route_id = surface.get("route_id")
        if route_id is None:
            continue
        route = route_by_id.get(route_id)
        if route is None:
            diagnostics.append(
                _diagnostic(
                    "UNKNOWN_SURFACE_ROUTE",
                    f"$.surfaces[{index}].route_id",
                    "A routed surface must name a captured provider route.",
                )
            )
            continue

        equipment_identity = surface.get("equipment_identity")
        route_equipment_identities = set(route["equipment_identities"]) | set(
            route["controlled_equipment_identities"]
        )
        if (
            equipment_identity is not None
            and equipment_identity not in route_equipment_identities
        ):
            diagnostics.append(
                _diagnostic(
                    "SURFACE_EQUIPMENT_MISMATCH",
                    f"$.surfaces[{index}].equipment_identity",
                    "The surface equipment identity is not a member of its provider route.",
                )
            )

        if kind != "canonical_skill_entry" and mutation_policy != route["control_owner"]:
            diagnostics.append(
                _diagnostic(
                    "SURFACE_OWNERSHIP_MISMATCH",
                    f"$.surfaces[{index}].mutation_policy",
                    "A mutable routed surface must use its provider route control owner.",
                )
            )

    return tuple(sorted(diagnostics))


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate captured-state cross-record semantics after the checked-in "
            "JSON Schema gate has passed, using a separately validated plan-action set."
        )
    )
    parser.add_argument(
        "--authoritative-plan-actions",
        required=True,
        type=Path,
        help="closed plan-action set emitted by the independently validated plan",
    )
    parser.add_argument(
        "--expected-candidate-identity",
        required=True,
        help="executor-trusted immutable implementation candidate identity",
    )
    parser.add_argument(
        "--expected-implementation-manifest-digest",
        required=True,
        help="executor-trusted digest of the complete installed implementation manifest",
    )
    parser.add_argument("manifest", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        with args.manifest.open(encoding="utf-8") as stream:
            document = _strict_json_load(stream)
    except (OSError, UnicodeError, ValueError):
        print(
            "CAPTURED_STATE_READ_FAILED: captured state could not be read as UTF-8 JSON.",
            file=sys.stderr,
        )
        return 1

    try:
        with args.authoritative_plan_actions.open(encoding="utf-8") as stream:
            authoritative_plan_action_set = _strict_json_load(stream)
    except (OSError, UnicodeError, ValueError):
        print(
            "AUTHORITATIVE_PLAN_ACTION_SET_READ_FAILED: authoritative plan actions could not be read as UTF-8 JSON.",
            file=sys.stderr,
        )
        return 1

    diagnostics = validate_captured_state(
        document,
        authoritative_plan_action_set,
        expected_candidate_identity=args.expected_candidate_identity,
        expected_implementation_manifest_digest=(
            args.expected_implementation_manifest_digest
        ),
    )
    for diagnostic in diagnostics:
        print(
            f"{diagnostic.path}: {diagnostic.code}: {diagnostic.message}",
            file=sys.stderr,
        )
    return 1 if diagnostics else 0


if __name__ == "__main__":
    raise SystemExit(main())
