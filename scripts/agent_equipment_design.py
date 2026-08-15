#!/usr/bin/env python3
"""Executable validation model for the global agent-equipment design."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any
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


JsonObject = Mapping[str, Any]
OPERATIONS = (
    "inspect",
    "install",
    "configure",
    "enable",
    "disable",
    "remove",
    "restore",
    "suppress_native_update",
)
MUTATING_OPERATIONS = frozenset(OPERATIONS) - {"inspect"}
SCHEMA_DIRECTORY = Path(__file__).resolve().parent.parent / "docs/agent-equipment"


@dataclass(frozen=True, order=True)
class CoverageEntry:
    equipment_identity: str
    harness: str
    record: JsonObject


@dataclass(frozen=True, order=True)
class PlannedOperation:
    equipment_identities: tuple[str, ...]
    controlled_equipment_identities: tuple[str, ...]
    harness: str
    route_identity: str
    activation_group: str
    operation: str


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    equipment_identity: str | None = None
    harness: str | None = None
    route_identity: str | None = None


@dataclass(frozen=True)
class DesignValidationResult:
    diagnostics: tuple[Diagnostic, ...]
    coverage: tuple[CoverageEntry, ...]
    mutation_plan: tuple[PlannedOperation, ...] | None


def canonical_json_sha256(document: JsonObject) -> str:
    """Return the digest of UTF-8 RFC-style canonical JSON for *document*."""

    payload = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def load_and_validate(catalog_path: Path, lock_path: Path) -> DesignValidationResult:
    """Load a catalog and lock as UTF-8 JSON, then validate them together."""

    try:
        catalog = _load_json_without_duplicate_members(Path(catalog_path))
        lock = _load_json_without_duplicate_members(Path(lock_path))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        return DesignValidationResult(
            diagnostics=(
                Diagnostic(
                    "DOCUMENT_PARSE_INVALID",
                    "Catalog and lock inputs must be valid JSON with unique object member names.",
                ),
            ),
            coverage=(),
            mutation_plan=None,
        )
    return validate_design(catalog, lock)


def _load_json_without_duplicate_members(path: Path) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object member")
            result[key] = value
        return result

    def reject_nonfinite_number(token: str) -> None:
        raise ValueError(f"non-finite JSON number: {token}")

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_nonfinite_number,
    )


def validate_design(catalog: JsonObject, lock: JsonObject) -> DesignValidationResult:
    """Validate and deterministically expand one catalog/lock design pair."""

    diagnostics = list(_document_schema_diagnostics(catalog, lock))
    if diagnostics:
        return DesignValidationResult(
            diagnostics=tuple(diagnostics),
            coverage=(),
            mutation_plan=None,
        )
    diagnostics.extend(_literal_secret_diagnostics(catalog, lock))
    if diagnostics:
        return DesignValidationResult(
            diagnostics=tuple(diagnostics),
            coverage=(),
            mutation_plan=None,
        )
    if (
        set(catalog)
        != {
            "schema_version",
            "active_harnesses",
            "distributions",
            "coverage_templates",
            "equipment",
            "retirements",
        }
        or catalog.get("schema_version") != "catalog/v1"
        or catalog.get("active_harnesses") != ["claude", "codex", "cursor"]
        or any(
            not isinstance(catalog.get(field), list)
            for field in ("distributions", "coverage_templates", "equipment", "retirements")
        )
    ):
        diagnostics.append(
            Diagnostic(
                "CATALOG_SHAPE_INVALID",
                "The authored catalog has the exact catalog/v1 top-level shape and active harness list.",
            )
        )
    templates = {
        item["identity"]: item
        for item in (
            catalog.get("coverage_templates", [])
            if isinstance(catalog.get("coverage_templates"), list)
            else []
        )
        if isinstance(item, dict) and isinstance(item.get("identity"), str)
    }
    distributions = {
        item["identity"]: item
        for item in (
            catalog.get("distributions", [])
            if isinstance(catalog.get("distributions"), list)
            else []
        )
        if isinstance(item, dict) and isinstance(item.get("identity"), str)
    }
    for distribution in (
        catalog.get("distributions", [])
        if isinstance(catalog.get("distributions"), list)
        else []
    ):
        if not _catalog_distribution_is_valid(distribution):
            diagnostics.append(
                Diagnostic(
                    "CATALOG_DISTRIBUTION_INVALID",
                    "Catalog distributions have namespaced identities, exact source selectors, one selection, and harness template references.",
                )
            )
    for field in ("distributions", "coverage_templates", "equipment"):
        items = catalog.get(field, []) if isinstance(catalog.get(field), list) else []
        identities = [
            item.get("identity")
            for item in items
            if isinstance(item, dict) and isinstance(item.get("identity"), str)
        ]
        for identity in sorted(
            {identity for identity in identities if identities.count(identity) > 1}
        ):
            diagnostics.append(
                Diagnostic(
                    "DUPLICATE_CATALOG_IDENTITY",
                    f"Catalog {field} identities are unique.",
                    equipment_identity=(identity if field == "equipment" else None),
                )
            )
    coverage: list[CoverageEntry] = []
    equipment_items = (
        catalog.get("equipment", [])
        if isinstance(catalog.get("equipment"), list)
        else []
    )
    harnesses = (
        catalog.get("active_harnesses", [])
        if isinstance(catalog.get("active_harnesses"), list)
        else []
    )
    equipment_overrides: dict[str, JsonObject] = {}
    for equipment in equipment_items:
        if not isinstance(equipment, dict) or not isinstance(equipment.get("identity"), str):
            diagnostics.append(Diagnostic("CATALOG_SHAPE_INVALID", "Equipment entries must be objects with identities."))
            continue
        if (
            not re.fullmatch(
                r"(skill|plugin|mcp|hook|other):[a-z0-9][a-z0-9._/-]*",
                equipment["identity"],
            )
            or set(equipment) != {"identity", "kind", "coverage"}
            or equipment.get("kind") not in {"skill", "plugin", "mcp", "hook", "other"}
            or not equipment["identity"].startswith(f"{equipment.get('kind')}:")
            or not isinstance(equipment.get("coverage"), dict)
            or not set(equipment["coverage"]).issubset({"claude", "codex", "cursor"})
        ):
            diagnostics.append(
                Diagnostic(
                    "EQUIPMENT_IDENTITY_INVALID",
                    "Equipment entries have a namespaced identity matching their kind and only harness coverage overrides.",
                    equipment_identity=equipment["identity"],
                )
            )
        equipment_overrides[equipment["identity"]] = equipment

    resolved_membership: dict[str, tuple[str, ...]] = {}
    lock_distributions = lock.get("distributions", []) if isinstance(lock, dict) else []
    if isinstance(lock_distributions, list):
        for item in lock_distributions:
            if (
                isinstance(item, dict)
                and isinstance(item.get("identity"), str)
                and isinstance(item.get("equipment"), list)
                and all(isinstance(identity, str) for identity in item["equipment"])
            ):
                resolved_membership[item["identity"]] = tuple(item["equipment"])
    selected_identities = sorted(
        {identity for identities in resolved_membership.values() for identity in identities}
    )
    for equipment_identity in selected_identities:
        if not re.fullmatch(
            r"(skill|plugin|mcp|hook|other):[a-z0-9][a-z0-9._/-]*",
            equipment_identity,
        ):
            diagnostics.append(
                Diagnostic(
                    "EQUIPMENT_IDENTITY_INVALID",
                    "Resolved equipment identities are typed and namespaced.",
                    equipment_identity=equipment_identity,
                )
            )
    for equipment_identity in equipment_overrides:
        if equipment_identity not in selected_identities:
            diagnostics.append(
                Diagnostic(
                    "EQUIPMENT_SELECTION_INVALID",
                    "Authored equipment coverage overrides must name an identity selected in the resolved lock.",
                    equipment_identity=equipment_identity,
                )
            )

    for equipment_identity in selected_identities:
        exact = equipment_overrides.get(equipment_identity, {}).get("coverage", {})
        selected_distributions = [
            distributions[distribution_identity]
            for distribution_identity, identities in resolved_membership.items()
            if equipment_identity in identities and distribution_identity in distributions
        ]
        for harness in harnesses:
            entry = exact.get(harness) if isinstance(exact, dict) else None
            record: Any = None
            if entry is not None:
                if isinstance(entry, dict) and set(entry) == {"record"}:
                    record = entry["record"]
                elif isinstance(entry, dict) and set(entry) == {"template"}:
                    template = templates.get(entry["template"])
                    if template is not None and template.get("harness") == harness:
                        record = template.get("record")
                    elif template is not None:
                        diagnostics.append(
                            Diagnostic(
                                "TEMPLATE_HARNESS_MISMATCH",
                                "Coverage template harness must match the target harness.",
                                equipment_identity=equipment_identity,
                                harness=harness,
                            )
                        )
                else:
                    diagnostics.append(
                        Diagnostic(
                            "COVERAGE_RECORD_INVALID",
                            "Coverage entries contain exactly one whole record or template reference.",
                            equipment_identity=equipment_identity,
                            harness=harness,
                        )
                    )
            else:
                fallback_records = []
                for distribution in selected_distributions:
                    distribution_templates = distribution.get("coverage_templates", {})
                    template_identity = (
                        distribution_templates.get(harness)
                        if isinstance(distribution_templates, dict)
                        else None
                    )
                    template = templates.get(template_identity)
                    if template is not None and template.get("harness") == harness:
                        fallback_records.append(template.get("record"))
                    elif template is not None:
                        diagnostics.append(
                            Diagnostic(
                                "TEMPLATE_HARNESS_MISMATCH",
                                "Coverage template harness must match the target harness.",
                                equipment_identity=equipment_identity,
                                harness=harness,
                            )
                        )
                if len(fallback_records) == 1:
                    record = fallback_records[0]
                elif len(fallback_records) > 1:
                    diagnostics.append(
                        Diagnostic(
                            "AMBIGUOUS_COVERAGE_TEMPLATE",
                            "Multiple selected distributions require an exact equipment-and-harness coverage record.",
                            equipment_identity=equipment_identity,
                            harness=harness,
                        )
                    )
            if record is None:
                diagnostics.append(
                    Diagnostic(
                        "MISSING_HARNESS_COVERAGE",
                        "No complete coverage record resolves for this equipment and harness.",
                        equipment_identity=equipment_identity,
                        harness=harness,
                    )
                )
                continue
            if not _coverage_record_is_structurally_valid(
                record,
                diagnostics,
                equipment_identity,
                harness,
            ):
                continue
            coverage.append(
                CoverageEntry(equipment_identity, harness, record)
            )

    retirement_operations = (
        _validate_retirements(
            catalog,
            lock,
            resolved_membership,
            coverage,
            diagnostics,
        )
    )
    _validate_lock(catalog, lock, coverage, diagnostics)
    grouped_operations: dict[
        tuple[str, str, str, str], set[str]
    ] = {}
    grouped_controls: dict[tuple[str, str, str, str], set[str]] = {}
    active_routes: dict[tuple[str, str], JsonObject] = {}
    activation_groups: dict[tuple[str, str], str] = {}
    for entry in coverage:
        selection = entry.record["provider_selection"]
        if selection == "no_provider":
            continue
        for route in selection["routes"]:
            route_key = (entry.harness, route["identity"])
            activation_key = (entry.harness, route["activation_group"])
            previous_group_route = activation_groups.get(activation_key)
            if (
                previous_group_route is not None
                and previous_group_route != route["identity"]
            ):
                diagnostics.append(
                    Diagnostic(
                        "ACTIVATION_GROUP_CONFLICT",
                        "One activation group maps to exactly one route identity within a harness.",
                        equipment_identity=entry.equipment_identity,
                        harness=entry.harness,
                        route_identity=route["identity"],
                    )
                )
            else:
                activation_groups[activation_key] = route["identity"]
            previous_route = active_routes.get(route_key)
            if previous_route is not None and previous_route != route:
                diagnostics.append(
                    Diagnostic(
                        "ROUTE_IDENTITY_CONFLICT",
                        "One route identity has one complete record within a harness.",
                        equipment_identity=entry.equipment_identity,
                        harness=entry.harness,
                        route_identity=route["identity"],
                    )
                )
            else:
                active_routes[route_key] = route
            if route["control_owner"] != "reconciler_owned":
                continue
            for operation, disposition in route["operations"].items():
                if operation != "inspect" and disposition["disposition"] == "automated":
                    key = (
                        entry.harness,
                        route["identity"],
                        route["activation_group"],
                        operation,
                    )
                    grouped_operations.setdefault(key, set()).add(
                        entry.equipment_identity
                    )
                    grouped_controls.setdefault(key, set()).update(
                        control["equipment_identity"]
                        for control in route["component_controls"]
                    )
    for retirement_operation in retirement_operations:
        activation_key = (
            retirement_operation.harness,
            retirement_operation.activation_group,
        )
        previous_group_route = activation_groups.get(activation_key)
        if (
            previous_group_route is not None
            and previous_group_route != retirement_operation.route_identity
        ):
            diagnostics.append(
                Diagnostic(
                    "ACTIVATION_GROUP_CONFLICT",
                    "One activation group maps to exactly one route identity within a harness.",
                    equipment_identity=retirement_operation.equipment_identities[0],
                    harness=retirement_operation.harness,
                    route_identity=retirement_operation.route_identity,
                )
            )
        else:
            activation_groups[activation_key] = retirement_operation.route_identity
        key = (
            retirement_operation.harness,
            retirement_operation.route_identity,
            retirement_operation.activation_group,
            retirement_operation.operation,
        )
        grouped_operations.setdefault(key, set()).update(
            retirement_operation.equipment_identities
        )
        grouped_controls.setdefault(key, set()).update(
            retirement_operation.controlled_equipment_identities
        )
    planned = [
        PlannedOperation(
            equipment_identities=tuple(sorted(equipment_identities)),
            controlled_equipment_identities=tuple(
                sorted(grouped_controls.get((harness, route_identity, activation_group, operation), ()))
            ),
            harness=harness,
            route_identity=route_identity,
            activation_group=activation_group,
            operation=operation,
        )
        for (
            harness,
            route_identity,
            activation_group,
            operation,
        ), equipment_identities in grouped_operations.items()
    ]

    ordered_diagnostics = tuple(
        sorted(
            diagnostics,
            key=lambda item: (
                item.equipment_identity or "",
                item.harness or "",
                item.route_identity or "",
                item.code,
                item.message,
            ),
        )
    )
    return DesignValidationResult(
        diagnostics=ordered_diagnostics,
        coverage=tuple(sorted(coverage)),
        mutation_plan=(
            None
            if ordered_diagnostics
            else tuple(
                sorted(
                    planned,
                    key=lambda item: (
                        item.equipment_identities,
                        item.controlled_equipment_identities,
                        item.harness,
                        item.route_identity,
                        item.activation_group,
                        OPERATIONS.index(item.operation),
                    ),
                )
            )
        ),
    )


def _coverage_record_is_structurally_valid(
    record: Any,
    diagnostics: list[Diagnostic],
    equipment_identity: str,
    harness: str,
) -> bool:
    if not isinstance(record, dict) or set(record) != {"outcome", "provider_selection"}:
        diagnostics.append(
            Diagnostic(
                "COVERAGE_RECORD_INVALID",
                "Coverage records contain exactly one outcome and provider selection.",
                equipment_identity=equipment_identity,
                harness=harness,
            )
        )
        return False
    outcome = record.get("outcome")
    selection = record.get("provider_selection")
    if outcome in {"intentional_omission", "unsupported"}:
        if selection != "no_provider":
            diagnostics.append(
                Diagnostic(
                    "COVERAGE_RECORD_INVALID",
                    "Omission and unsupported outcomes require exact no_provider.",
                    equipment_identity=equipment_identity,
                    harness=harness,
                )
            )
            return False
        return True
    if outcome not in {"managed_provider", "manually_managed_provider"}:
        diagnostics.append(
            Diagnostic(
                "COVERAGE_RECORD_INVALID",
                "Coverage outcome is not recognized.",
                equipment_identity=equipment_identity,
                harness=harness,
            )
        )
        return False
    expected_selection_keys = {
        "preferred_route",
        "supplementary_routes",
        "routes",
        "allow_overlap",
    }
    if not isinstance(selection, dict) or set(selection) != expected_selection_keys:
        diagnostics.append(
            Diagnostic(
                "COVERAGE_RECORD_INVALID",
                "Provider outcomes require one complete provider selection object.",
                equipment_identity=equipment_identity,
                harness=harness,
            )
        )
        return False
    routes = selection["routes"]
    if not isinstance(routes, list):
        diagnostics.append(
            Diagnostic(
                "COVERAGE_RECORD_INVALID",
                "Provider routes must be a list.",
                equipment_identity=equipment_identity,
                harness=harness,
            )
        )
        return False
    route_ids = [route.get("identity") for route in routes if isinstance(route, dict)]
    if len(route_ids) != len(routes):
        diagnostics.append(
            Diagnostic(
                "COVERAGE_RECORD_INVALID",
                "Every active route must be a complete object with an identity.",
                equipment_identity=equipment_identity,
                harness=harness,
            )
        )
        return False
    duplicate_ids = {identity for identity in route_ids if route_ids.count(identity) > 1}
    for route_identity in sorted(duplicate_ids):
        diagnostics.append(
            Diagnostic(
                "DUPLICATE_ROUTE_IDENTITY",
                "Active route identities are unique within a coverage record.",
                equipment_identity=equipment_identity,
                harness=harness,
                route_identity=route_identity,
            )
        )
    valid = not duplicate_ids
    preferred_route = selection["preferred_route"]
    supplementary_routes = selection["supplementary_routes"]
    if (
        not isinstance(preferred_route, str)
        or not isinstance(supplementary_routes, list)
        or not all(isinstance(item, str) for item in supplementary_routes)
    ):
        diagnostics.append(
            Diagnostic(
                "COVERAGE_RECORD_INVALID",
                "Preferred and supplementary route identities name the complete active route set exactly once.",
                equipment_identity=equipment_identity,
                harness=harness,
            )
        )
        return False
    active_route_ids = [preferred_route, *supplementary_routes]
    if (
        len(active_route_ids) != len(set(active_route_ids))
        or set(active_route_ids) != set(route_ids)
    ):
        diagnostics.append(
            Diagnostic(
                "COVERAGE_RECORD_INVALID",
                "Preferred and supplementary route identities name the complete active route set exactly once.",
                equipment_identity=equipment_identity,
                harness=harness,
            )
        )
        valid = False

    exceptions = selection["allow_overlap"]
    complete_route_set = set(route_ids)
    if not isinstance(exceptions, list):
        exceptions = []
        valid = False
    for supplementary_route in supplementary_routes:
        matches = [
            item
            for item in exceptions
            if _overlap_matches(item, supplementary_route, complete_route_set)
        ]
        if len(matches) != 1:
            diagnostics.append(
                Diagnostic(
                    "OVERLAP_INVALID",
                    "Every supplementary route requires one exact allow_overlap exception for the complete active route set.",
                    equipment_identity=equipment_identity,
                    harness=harness,
                    route_identity=supplementary_route,
                )
            )
            valid = False
    if len(exceptions) != len(supplementary_routes):
        diagnostics.append(
            Diagnostic(
                "OVERLAP_INVALID",
                "Allow-overlap exceptions correspond one-for-one with supplementary routes.",
                equipment_identity=equipment_identity,
                harness=harness,
            )
        )
        valid = False

    owners: list[str] = []
    for route in routes:
        route_identity = route.get("identity")
        route_valid = _route_is_valid(
            route,
            diagnostics,
            equipment_identity,
            harness,
        )
        valid = route_valid and valid
        owner = route.get("control_owner")
        if isinstance(owner, str):
            owners.append(owner)
    if outcome == "managed_provider" and any(
        owner != "reconciler_owned" for owner in owners
    ):
        diagnostics.append(
            Diagnostic(
                "COVERAGE_OWNER_MISMATCH",
                "Managed-provider coverage requires every active route to be reconciler-owned.",
                equipment_identity=equipment_identity,
                harness=harness,
            )
        )
        valid = False
    if outcome == "manually_managed_provider" and "operator_owned" not in owners:
        diagnostics.append(
            Diagnostic(
                "COVERAGE_OWNER_MISMATCH",
                "Manually-managed-provider coverage requires at least one operator-owned active route.",
                equipment_identity=equipment_identity,
                harness=harness,
            )
        )
        valid = False
    return valid


def _document_schema_diagnostics(
    catalog: Any,
    lock: Any,
) -> tuple[Diagnostic, ...]:
    """Validate both public documents against their checked-in JSON Schemas."""

    diagnostics: list[Diagnostic] = []
    for code, label, document, schema_name in (
        (
            "CATALOG_SCHEMA_INVALID",
            "authored catalog",
            catalog,
            "catalog-v1.schema.json",
        ),
        (
            "LOCK_SCHEMA_INVALID",
            "resolved lock",
            lock,
            "lock-v1.schema.json",
        ),
    ):
        if not _validate_schema(
            document,
            schema_directory=SCHEMA_DIRECTORY,
            root_schema_name=schema_name,
            allowed_schema_names=(
                {"catalog-v1.schema.json"}
                if schema_name == "catalog-v1.schema.json"
                else {"catalog-v1.schema.json", "lock-v1.schema.json"}
            ),
        ):
            diagnostics.append(
                Diagnostic(
                    code,
                    f"The {label} or its closed local schema set is invalid.",
                )
            )
    return tuple(diagnostics)


def _literal_secret_diagnostics(
    catalog: JsonObject,
    lock: JsonObject,
) -> tuple[Diagnostic, ...]:
    """Reject public documents containing seeded or obvious literal credentials."""

    diagnostics: list[Diagnostic] = []
    for label, document in (("catalog", catalog), ("lock", lock)):
        if contains_literal_credential(document):
            diagnostics.append(
                Diagnostic(
                    "LITERAL_SECRET_MATERIAL",
                    f"The {label} contains literal secret material; use a structured secret reference.",
                )
            )
    return tuple(diagnostics)


def _route_is_valid(
    route: JsonObject,
    diagnostics: list[Diagnostic],
    equipment_identity: str,
    harness: str,
) -> bool:
    route_identity = route.get("identity")
    expected_keys = {
        "identity",
        "distribution",
        "provider",
        "activation_group",
        "control_owner",
        "provenance",
        "restore",
        "secret_references",
        "component_controls",
        "operations",
    }
    valid = True
    if set(route) != expected_keys:
        diagnostics.append(
            Diagnostic(
                "ROUTE_RECORD_INVALID",
                "Active route records have one exact, complete shape.",
                equipment_identity=equipment_identity,
                harness=harness,
                route_identity=route_identity,
            )
        )
        valid = False
    if (
        not isinstance(route_identity, str)
        or not re.fullmatch(r"route:[a-z0-9][a-z0-9._/-]*", route_identity)
        or not isinstance(route.get("distribution"), str)
        or not re.fullmatch(
            r"distribution:[a-z0-9][a-z0-9._/-]*", route["distribution"]
        )
        or not isinstance(route.get("activation_group"), str)
        or not re.fullmatch(
            r"activation:[a-z0-9][a-z0-9._/-]*", route["activation_group"]
        )
    ):
        diagnostics.append(
            Diagnostic(
                "ROUTE_RECORD_INVALID",
                "Route, distribution, and activation-group identities are portable and namespaced.",
                equipment_identity=equipment_identity,
                harness=harness,
                route_identity=(route_identity if isinstance(route_identity, str) else None),
            )
        )
        valid = False
    if route.get("control_owner") not in {"reconciler_owned", "operator_owned"}:
        diagnostics.append(
            Diagnostic(
                "ROUTE_OWNER_INVALID",
                "Route control owner must be reconciler_owned or operator_owned.",
                equipment_identity=equipment_identity,
                harness=harness,
                route_identity=route_identity,
            )
        )
        valid = False
    provenance = route.get("provenance")
    if (
        not isinstance(provenance, dict)
        or set(provenance) != {"owner"}
        or not isinstance(provenance.get("owner"), str)
        or not provenance["owner"].strip()
    ):
        diagnostics.append(
            Diagnostic(
                "PROVENANCE_OWNER_INVALID",
                "Every active route has exactly one non-empty provenance owner.",
                equipment_identity=equipment_identity,
                harness=harness,
                route_identity=route_identity,
            )
        )
        valid = False
    elif not _provenance_matches_provider(
        provenance["owner"],
        route.get("provider"),
        harness,
        route.get("distribution"),
    ):
        diagnostics.append(
            Diagnostic(
                "PROVENANCE_OWNER_INVALID",
                "The provenance owner must name the selected distribution source, exact native plugin, or matching harness overlay.",
                equipment_identity=equipment_identity,
                harness=harness,
                route_identity=route_identity,
            )
        )
        valid = False
    restore = route.get("restore")
    if not _restore_is_valid(restore):
        restore_class = restore.get("class") if isinstance(restore, dict) else None
        diagnostics.append(
            Diagnostic(
                (
                    "NATIVE_ROLLING_RESTORE_INVALID"
                    if restore_class == "native_rolling"
                    else "IMMUTABLE_RESTORE_INVALID"
                ),
                "The route restore record is incomplete or malformed for its restore class.",
                equipment_identity=equipment_identity,
                harness=harness,
                route_identity=route_identity,
            )
        )
        valid = False
    secret_references = route.get("secret_references")
    if (
        not isinstance(secret_references, list)
        or any(not _secret_reference_is_valid(item) for item in secret_references)
    ):
        diagnostics.append(
            Diagnostic(
                "SECRET_REFERENCE_INVALID",
                "Routes store approved environment-variable references and never secret values.",
                equipment_identity=equipment_identity,
                harness=harness,
                route_identity=route_identity,
            )
        )
        valid = False
    declared_secret_references = {
        (reference["kind"], reference["name"])
        for reference in secret_references
        if _secret_reference_is_valid(reference)
    } if isinstance(secret_references, list) else set()
    if not _provider_is_valid(
        route.get("provider"), harness, declared_secret_references
    ):
        diagnostics.append(
            Diagnostic(
                "PROVIDER_CONFIGURATION_INVALID",
                "Provider configuration is typed, portable, harness-compatible, and references only declared secrets.",
                equipment_identity=equipment_identity,
                harness=harness,
                route_identity=(route_identity if isinstance(route_identity, str) else None),
            )
        )
        valid = False
    component_controls = route.get("component_controls")
    if not _component_controls_are_valid(
        component_controls,
        active_equipment_identity=equipment_identity,
    ):
        diagnostics.append(
            Diagnostic(
                "COMPONENT_CONTROL_INVALID",
                "Component controls are exact, non-conflicting equipment state declarations.",
                equipment_identity=equipment_identity,
                harness=harness,
                route_identity=route_identity,
            )
        )
        valid = False
    operations = route.get("operations")
    if not isinstance(operations, dict) or set(operations) != set(OPERATIONS):
        diagnostics.append(
            Diagnostic(
                "OPERATION_MATRIX_INVALID",
                "Every active route declares exactly the required operation set.",
                equipment_identity=equipment_identity,
                harness=harness,
                route_identity=route_identity,
            )
        )
        return False
    native_update_control = (
        restore.get("native_update_control") if isinstance(restore, dict) else None
    )
    suppression_disposition = (
        operations["suppress_native_update"].get("disposition")
        if isinstance(operations["suppress_native_update"], dict)
        else None
    )
    native_update_operation_valid = (
        (
            native_update_control in {"not_applicable", "unsuppressible"}
            and suppression_disposition == "unavailable"
        )
        or (
            native_update_control == "unknown"
            and suppression_disposition in {"operator_action", "unavailable"}
        )
        or (
            native_update_control == "suppressible"
            and suppression_disposition
            in {"automated", "operator_action", "unavailable"}
        )
    )
    if not native_update_operation_valid:
        diagnostics.append(
            Diagnostic(
                "NATIVE_UPDATE_OPERATION_INVALID",
                "Native-update classification and suppression disposition form one coherent capability claim.",
                equipment_identity=equipment_identity,
                harness=harness,
                route_identity=route_identity,
            )
        )
        valid = False
    for operation in OPERATIONS:
        operation_record = operations[operation]
        if (
            not isinstance(operation_record, dict)
            or operation_record.get("disposition")
            not in {"automated", "operator_action", "unavailable"}
            or not set(operation_record).issubset({"disposition", "compensation"})
        ):
            diagnostics.append(
                Diagnostic(
                    "OPERATION_MATRIX_INVALID",
                    "Every operation has exactly one recognized disposition.",
                    equipment_identity=equipment_identity,
                    harness=harness,
                    route_identity=route_identity,
                )
            )
            valid = False
            continue
        if operation in MUTATING_OPERATIONS and operation_record["disposition"] == "automated":
            if operation_record.get("compensation") != "restore_captured_pre_state":
                diagnostics.append(
                    Diagnostic(
                        "AUTOMATED_COMPENSATION_MISSING",
                        "Automated mutating operations restore their captured pre-state.",
                        equipment_identity=equipment_identity,
                        harness=harness,
                        route_identity=route_identity,
                    )
                )
                valid = False
            if (
                operation == "remove"
                and route.get("provider", {}).get("kind") == "native_plugin"
                and isinstance(restore, dict)
                and restore.get("class") == "native_rolling"
            ):
                diagnostics.append(
                    Diagnostic(
                        "NATIVE_ROLLING_PLUGIN_REMOVAL_INVALID",
                        "A native-rolling plugin cannot be removed automatically when its exact captured artifact cannot be restored.",
                        equipment_identity=equipment_identity,
                        harness=harness,
                        route_identity=route_identity,
                    )
                )
                valid = False
            if route.get("control_owner") == "operator_owned":
                diagnostics.append(
                    Diagnostic(
                        "OPERATOR_AUTOMATION_INVALID",
                        "Operator-owned routes cannot expose automated mutating operations.",
                        equipment_identity=equipment_identity,
                        harness=harness,
                        route_identity=route_identity,
                    )
                )
                valid = False
        elif "compensation" in operation_record:
            diagnostics.append(
                Diagnostic(
                    "OPERATION_MATRIX_INVALID",
                    "Only automated mutating operations declare compensation.",
                    equipment_identity=equipment_identity,
                    harness=harness,
                    route_identity=route_identity,
                )
            )
            valid = False
    return valid


def _restore_is_valid(restore: Any) -> bool:
    if not isinstance(restore, dict):
        return False
    restore_class = restore.get("class")
    if restore_class == "immutable":
        if set(restore) != {
            "class",
            "revision",
            "artifact_ref",
            "content_digest",
            "native_update_control",
        }:
            return False
        return (
            isinstance(restore["revision"], str)
            and _git_commit_oid_is_valid(restore["revision"])
            and isinstance(restore["artifact_ref"], str)
            and _immutable_artifact_ref_is_valid(restore["artifact_ref"])
            and _immutable_artifact_ref_revision(restore["artifact_ref"])
            == restore["revision"]
            and isinstance(restore["content_digest"], str)
            and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", restore["content_digest"]))
            and restore["native_update_control"] == "not_applicable"
        )
    if restore_class == "native_rolling":
        if set(restore) != {
            "class",
            "channel",
            "reviewed_baseline",
            "observation_source",
            "native_update_control",
        }:
            return False
        return (
            all(
                isinstance(restore[field], str) and bool(restore[field].strip())
                for field in ("channel", "reviewed_baseline", "observation_source")
            )
            and restore["native_update_control"]
            in {"unknown", "suppressible", "unsuppressible"}
        )
    return False


def _provenance_matches_provider(
    owner: str,
    provider: Any,
    harness: str,
    distribution: Any,
) -> bool:
    if not isinstance(provider, dict):
        return False
    kind = provider.get("kind")
    if kind == "direct_mcp":
        return owner == f"overlay:{harness}/mcp"
    if kind == "native_plugin":
        plugin_id = provider.get("plugin_id")
        return (
            isinstance(plugin_id, str)
            and owner == f"manager:{harness}-plugins/{plugin_id}"
        )
    if kind != "standalone_skill":
        return False
    source_owner = (
        f"source:{distribution.removeprefix('distribution:')}"
        if isinstance(distribution, str)
        and distribution.startswith("distribution:")
        else None
    )
    return owner == source_owner or (
        harness == "claude" and owner == "projection:claude/standalone-skill"
    )


def _catalog_distribution_is_valid(distribution: Any) -> bool:
    if not isinstance(distribution, dict) or set(distribution) != {
        "identity",
        "source",
        "selection",
        "coverage_templates",
    }:
        return False
    identity = distribution.get("identity")
    if not isinstance(identity, str) or not re.fullmatch(
        r"distribution:[a-z0-9][a-z0-9._/-]*", identity
    ):
        return False
    source = distribution.get("source")
    if not isinstance(source, dict):
        return False
    if source.get("kind") == "git":
        source_valid = (
            set(source) == {"kind", "repository", "ref"}
            and isinstance(source.get("repository"), str)
            and _public_git_repository_is_valid(source["repository"])
            and isinstance(source.get("ref"), str)
            and _git_commit_oid_is_valid(source["ref"])
        )
    elif source.get("kind") == "native_manager":
        source_valid = (
            set(source) == {"kind", "manager", "package", "channel"}
            and all(
                isinstance(source.get(field), str) and bool(source[field].strip())
                for field in ("manager", "package", "channel")
            )
        )
    else:
        source_valid = False
    selection = distribution.get("selection")
    selection_valid = isinstance(selection, dict) and (
        (set(selection) == {"all"} and selection.get("all") is True)
        or (
            set(selection) == {"equipment"}
            and isinstance(selection.get("equipment"), list)
            and bool(selection["equipment"])
            and len(selection["equipment"]) == len(set(selection["equipment"]))
            and all(
                isinstance(item, str)
                and bool(
                    re.fullmatch(
                        r"(skill|plugin|mcp|hook|other):[a-z0-9][a-z0-9._/-]*",
                        item,
                    )
                )
                for item in selection["equipment"]
            )
        )
    )
    template_refs = distribution.get("coverage_templates")
    templates_valid = (
        isinstance(template_refs, dict)
        and set(template_refs).issubset({"claude", "codex", "cursor"})
        and all(
            isinstance(value, str)
            and bool(re.fullmatch(r"template:[a-z0-9][a-z0-9._/-]*", value))
            for value in template_refs.values()
        )
    )
    return source_valid and selection_valid and templates_valid


def _public_git_repository_is_valid(value: str) -> bool:
    if not _static_credential_free_https_url_is_valid(value):
        return False
    parsed = urlsplit(value)
    return parsed.path not in {"", "/"} and parsed.path.endswith(".git")


def _git_commit_oid_is_valid(value: str) -> bool:
    return bool(re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value))


def _artifact_subpath_is_valid(value: str) -> bool:
    if not value or "%" in value or "\\" in value:
        return False
    return all(
        segment not in {"", ".", ".."}
        and bool(re.fullmatch(r"[A-Za-z0-9._~-]+", segment))
        for segment in value.split("/")
    )


def _immutable_artifact_ref_is_valid(value: str) -> bool:
    if not value.startswith("git+"):
        return False
    repository_and_selector = value[4:]
    if "@" not in repository_and_selector:
        return False
    repository, selector = repository_and_selector.rsplit("@", 1)
    if not _public_git_repository_is_valid(repository):
        return False
    revision, separator, subpaths = selector.partition("#")
    if not _git_commit_oid_is_valid(revision):
        return False
    if not separator:
        return True
    return all(_artifact_subpath_is_valid(subpath) for subpath in subpaths.split(","))


def _immutable_artifact_ref_revision(value: str) -> str | None:
    if not _immutable_artifact_ref_is_valid(value):
        return None
    return value.rsplit("@", 1)[1].partition("#")[0]


def _provider_is_valid(
    provider: Any,
    harness: str,
    declared_secret_references: set[tuple[str, str]],
) -> bool:
    if not isinstance(provider, dict):
        return False
    kind = provider.get("kind")
    if kind == "standalone_skill":
        return (
            not declared_secret_references
            and set(provider) == {"kind", "canonical_root"}
            and provider.get("canonical_root") == "agents_skills"
        )
    if kind == "native_plugin":
        plugin_id = provider.get("plugin_id")
        return (
            not declared_secret_references
            and
            set(provider) == {"kind", "manager", "plugin_id", "scope"}
            and provider.get("manager") == harness
            and provider.get("scope") == "user"
            and isinstance(plugin_id, str)
            and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@/-]*", plugin_id))
        )
    if kind != "direct_mcp":
        return False
    server_name = provider.get("server_name")
    if not isinstance(server_name, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]*", server_name
    ):
        return False
    if provider.get("transport") == "http":
        return (
            not declared_secret_references
            and set(provider) == {"kind", "server_name", "transport", "url"}
            and isinstance(provider.get("url"), str)
            and _static_credential_free_https_url_is_valid(provider["url"])
        )
    if provider.get("transport") != "stdio" or set(provider) != {
        "kind",
        "server_name",
        "transport",
        "command",
        "arguments",
    }:
        return False
    command = provider.get("command")
    arguments = provider.get("arguments")
    if (
        not isinstance(command, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", command)
        or not isinstance(arguments, list)
    ):
        return False
    secret_value_expected = False
    consumed_secret_references: list[tuple[str, str]] = []
    for index, argument in enumerate(arguments):
        if not isinstance(argument, dict):
            return False
        if set(argument) == {"literal"} and isinstance(argument.get("literal"), str):
            if secret_value_expected:
                return False
            secret_value_expected = _literal_expects_secret_argument(
                argument["literal"]
            )
            continue
        if (
            set(argument) == {"secret_reference", "template"}
            and (
                "environment_variable",
                argument.get("secret_reference"),
            ) in declared_secret_references
            and isinstance(argument.get("template"), str)
            and argument["template"].count("{reference}") == 1
        ):
            consumed_secret_references.append(
                ("environment_variable", argument["secret_reference"])
            )
            secret_value_expected = False
            continue
        if (
            set(argument) == {"secret_profile_reference"}
            and isinstance(argument.get("secret_profile_reference"), str)
            and (
                "secret_profile",
                argument["secret_profile_reference"],
            ) in declared_secret_references
            and command == "secret-exec"
            and index == 0
        ):
            consumed_secret_references.append(
                ("secret_profile", argument["secret_profile_reference"])
            )
            secret_value_expected = False
            continue
        return False
    return (
        not secret_value_expected
        and len(consumed_secret_references) == len(set(consumed_secret_references))
        and set(consumed_secret_references) == declared_secret_references
        and (
            command != "secret-exec"
            or bool(consumed_secret_references)
            and consumed_secret_references[0][0] == "secret_profile"
        )
    )


def _hostname_has_valid_dns_labels(value: str) -> bool:
    return len(value) <= 253 and all(
        bool(
            re.fullmatch(
                r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label
            )
        )
        for label in value.split(".")
    )


def _static_credential_free_https_url_is_valid(value: str) -> bool:
    """Return whether *value* is a static credential-free HTTPS endpoint URL."""

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    path_segments = tuple(segment for segment in parsed.path.split("/") if segment)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and _hostname_has_valid_dns_labels(parsed.hostname or "")
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


def _literal_expects_secret_argument(value: str) -> bool:
    normalized = value.strip().lower().rstrip(":=")
    return normalized in {
        "--api-key",
        "--apikey",
        "--access-token",
        "--token",
        "--password",
        "--client-secret",
        "authorization",
        "proxy-authorization",
        "x-api-key",
    }


def _secret_reference_is_valid(reference: Any) -> bool:
    if not isinstance(reference, dict) or set(reference) != {"kind", "name"}:
        return False
    name = reference.get("name")
    if not isinstance(name, str):
        return False
    if reference.get("kind") == "environment_variable":
        return bool(re.fullmatch(r"[A-Z_][A-Z0-9_]*", name))
    if reference.get("kind") == "secret_profile":
        return bool(re.fullmatch(r"[a-z0-9][a-z0-9._-]*", name))
    return False


def _validate_retirements(
    catalog: JsonObject,
    lock: JsonObject,
    resolved_membership: Mapping[str, tuple[str, ...]],
    coverage: list[CoverageEntry],
    diagnostics: list[Diagnostic],
) -> list[PlannedOperation]:
    retirements = catalog.get("retirements")
    if not isinstance(retirements, list):
        diagnostics.append(
            Diagnostic(
                "RETIREMENT_SHAPE_INVALID",
                "Catalog retirements are an explicit list of owned losing surfaces.",
            )
        )
        return []

    selected_identities = {
        identity for identities in resolved_membership.values() for identity in identities
    }
    active_route_ids = {
        route.get("identity")
        for entry in coverage
        if isinstance(entry.record.get("provider_selection"), dict)
        for route in entry.record["provider_selection"].get("routes", [])
        if isinstance(route, dict)
    }
    seen_retirement_ids: set[str] = set()
    seen_surfaces: set[tuple[str, ...]] = set()
    planned: list[PlannedOperation] = []
    distribution_sources = {
        distribution.get("identity"): distribution.get("source")
        for distribution in catalog.get("distributions", [])
        if isinstance(distribution, dict)
        and isinstance(distribution.get("identity"), str)
    }
    distribution_restores = {
        distribution.get("identity"): distribution.get("restore")
        for distribution in lock.get("distributions", [])
        if isinstance(distribution, dict)
        and isinstance(distribution.get("identity"), str)
    }

    for retirement in retirements:
        if not isinstance(retirement, dict) or set(retirement) != {
            "identity",
            "equipment_identity",
            "harness",
            "route",
            "surface",
            "desired_state",
        }:
            diagnostics.append(
                Diagnostic(
                    "RETIREMENT_SHAPE_INVALID",
                    "Each retirement has one exact owned-surface shape.",
                )
            )
            continue
        retirement_identity = retirement.get("identity")
        equipment_identity = retirement.get("equipment_identity")
        harness = retirement.get("harness")
        route = retirement.get("route")
        route_identity = route.get("identity") if isinstance(route, dict) else None

        if (
            not isinstance(retirement_identity, str)
            or not re.fullmatch(r"retirement:[a-z0-9][a-z0-9._/-]*", retirement_identity)
            or retirement_identity in seen_retirement_ids
        ):
            diagnostics.append(
                Diagnostic(
                    "RETIREMENT_IDENTITY_INVALID",
                    "Retirement identities are unique, portable, and namespaced.",
                    equipment_identity=(equipment_identity if isinstance(equipment_identity, str) else None),
                    harness=(harness if isinstance(harness, str) else None),
                    route_identity=(route_identity if isinstance(route_identity, str) else None),
                )
            )
        elif isinstance(retirement_identity, str):
            seen_retirement_ids.add(retirement_identity)

        if (
            not isinstance(equipment_identity, str)
            or equipment_identity not in selected_identities
            or harness not in {"claude", "codex", "cursor"}
            or not isinstance(route, dict)
        ):
            diagnostics.append(
                Diagnostic(
                    "RETIREMENT_REFERENCE_INVALID",
                    "A retirement names selected equipment, one active harness, and one complete losing route.",
                    equipment_identity=(equipment_identity if isinstance(equipment_identity, str) else None),
                    harness=(harness if isinstance(harness, str) else None),
                    route_identity=(route_identity if isinstance(route_identity, str) else None),
                )
            )
            continue

        route_valid = _route_is_valid(route, diagnostics, equipment_identity, harness)
        distribution_identity = route.get("distribution")
        if (
            distribution_identity not in resolved_membership
            or equipment_identity not in resolved_membership.get(distribution_identity, ())
        ):
            diagnostics.append(
                Diagnostic(
                    "RETIREMENT_REFERENCE_INVALID",
                    "The losing route distribution supplies the retired equipment identity in the resolved lock.",
                    equipment_identity=equipment_identity,
                    harness=harness,
                    route_identity=route_identity,
                )
            )
            route_valid = False
        if not _distribution_source_matches_provider(
            distribution_sources.get(distribution_identity), route.get("provider")
        ):
            diagnostics.append(
                Diagnostic(
                    "RETIREMENT_DISTRIBUTION_SOURCE_PROVIDER_MISMATCH",
                    "The losing provider invokes the exact package, channel, manager, or immutable source bound by its distribution.",
                    equipment_identity=equipment_identity,
                    harness=harness,
                    route_identity=route_identity,
                )
            )
            route_valid = False
        if route.get("restore") != distribution_restores.get(distribution_identity):
            diagnostics.append(
                Diagnostic(
                    "RETIREMENT_DISTRIBUTION_RESTORE_MISMATCH",
                    "The losing route restore evidence is the exact restore resolved for its distribution.",
                    equipment_identity=equipment_identity,
                    harness=harness,
                    route_identity=route_identity,
                )
            )
            route_valid = False
        if route_identity in active_route_ids:
            diagnostics.append(
                Diagnostic(
                    "RETIREMENT_ROUTE_ACTIVE",
                    "A retirement route cannot also be preferred or supplementary.",
                    equipment_identity=equipment_identity,
                    harness=harness,
                    route_identity=route_identity,
                )
            )
            route_valid = False
        if route.get("control_owner") != "reconciler_owned":
            diagnostics.append(
                Diagnostic(
                    "RETIREMENT_OWNER_INVALID",
                    "Only an explicitly reconciler-owned losing route may authorize retirement.",
                    equipment_identity=equipment_identity,
                    harness=harness,
                    route_identity=route_identity,
                )
            )
            route_valid = False

        surface_key = _retirement_surface_key(
            retirement.get("surface"),
            retirement.get("desired_state"),
            equipment_identity,
            harness,
        )
        if surface_key is None:
            diagnostics.append(
                Diagnostic(
                    "RETIREMENT_SURFACE_INVALID",
                    "A retirement uses a portable narrow selector and compatible absent or disabled state.",
                    equipment_identity=equipment_identity,
                    harness=harness,
                    route_identity=route_identity,
                )
            )
            route_valid = False
        elif not _retirement_surface_matches_provider(
            retirement.get("surface"), route.get("provider"), equipment_identity, harness
        ):
            diagnostics.append(
                Diagnostic(
                    "RETIREMENT_SURFACE_PROVIDER_MISMATCH",
                    "The losing surface locator is the canonical physical surface selected by its route provider and equipment identity.",
                    equipment_identity=equipment_identity,
                    harness=harness,
                    route_identity=route_identity,
                )
            )
            route_valid = False
        elif surface_key in seen_surfaces:
            diagnostics.append(
                Diagnostic(
                    "DUPLICATE_RETIREMENT_SURFACE",
                    "Each owned losing runtime surface has exactly one retirement.",
                    equipment_identity=equipment_identity,
                    harness=harness,
                    route_identity=route_identity,
                )
            )
            route_valid = False
        else:
            seen_surfaces.add(surface_key)

        operation = "remove" if retirement.get("desired_state") == "absent" else "disable"
        operation_record = route.get("operations", {}).get(operation)
        if (
            not isinstance(operation_record, dict)
            or operation_record.get("disposition") != "automated"
            or operation_record.get("compensation") != "restore_captured_pre_state"
        ):
            diagnostics.append(
                Diagnostic(
                    "RETIREMENT_OPERATION_INVALID",
                    "The relevant retirement operation is automated and restores captured pre-state.",
                    equipment_identity=equipment_identity,
                    harness=harness,
                    route_identity=route_identity,
                )
            )
            route_valid = False
        if route_valid and isinstance(route_identity, str):
            planned.append(
                PlannedOperation(
                    equipment_identities=(equipment_identity,),
                    controlled_equipment_identities=(),
                    harness=harness,
                    route_identity=route_identity,
                    activation_group=route["activation_group"],
                    operation=operation,
                )
            )
    return planned


def _retirement_surface_matches_provider(
    surface: Any,
    provider: Any,
    equipment_identity: str,
    harness: str,
) -> bool:
    if not isinstance(surface, dict) or not isinstance(provider, dict):
        return False
    kind = surface.get("kind")
    if kind == "claude_skill_projection":
        expected_name = equipment_identity.split(":", 1)[-1].rsplit("/", 1)[-1]
        return (
            harness == "claude"
            and provider.get("kind") == "standalone_skill"
            and surface.get("skill_name") == expected_name
        )
    if kind == "direct_mcp":
        return (
            provider.get("kind") == "direct_mcp"
            and surface.get("server_name") == provider.get("server_name")
        )
    if kind == "plugin":
        return (
            provider.get("kind") == "native_plugin"
            and surface.get("plugin_id") == provider.get("plugin_id")
        )
    if kind == "plugin_component":
        return (
            provider.get("kind") == "native_plugin"
            and surface.get("plugin_id") == provider.get("plugin_id")
            and surface.get("component_identity") == equipment_identity
        )
    return False


def _retirement_surface_key(
    surface: Any,
    desired_state: Any,
    equipment_identity: str,
    harness: str,
) -> tuple[str, ...] | None:
    if not isinstance(surface, dict):
        return None
    kind = surface.get("kind")
    if kind == "claude_skill_projection":
        name = surface.get("skill_name")
        if (
            set(surface) == {"kind", "skill_name"}
            and harness == "claude"
            and equipment_identity.startswith("skill:")
            and desired_state == "absent"
            and isinstance(name, str)
            and re.fullmatch(r"[a-z0-9][a-z0-9._-]*", name)
        ):
            return (harness, kind, name)
        return None
    if kind == "direct_mcp":
        name = surface.get("server_name")
        if (
            set(surface) == {"kind", "server_name"}
            and equipment_identity.startswith("mcp:")
            and desired_state == "absent"
            and isinstance(name, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name)
        ):
            return (harness, kind, name)
        return None
    if kind == "plugin":
        plugin_id = surface.get("plugin_id")
        if (
            set(surface) == {"kind", "plugin_id"}
            and equipment_identity.startswith("plugin:")
            and desired_state in {"absent", "disabled"}
            and isinstance(plugin_id, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@/-]*", plugin_id)
        ):
            return (harness, kind, plugin_id)
        return None
    if kind == "plugin_component":
        plugin_id = surface.get("plugin_id")
        component_identity = surface.get("component_identity")
        if (
            set(surface) == {"kind", "plugin_id", "component_identity"}
            and component_identity == equipment_identity
            and desired_state == "disabled"
            and isinstance(plugin_id, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@/-]*", plugin_id)
        ):
            return (harness, kind, plugin_id, component_identity)
    return None


def _overlap_matches(
    exception: Any,
    supplementary_route: str,
    complete_route_set: set[str | None],
) -> bool:
    if not isinstance(exception, dict) or set(exception) != {
        "kind",
        "supplementary_route",
        "routes",
        "rationale",
    }:
        return False
    routes = exception.get("routes")
    return (
        exception.get("kind") == "allow_overlap"
        and exception.get("supplementary_route") == supplementary_route
        and isinstance(routes, list)
        and all(isinstance(route, str) for route in routes)
        and len(routes) == len(set(routes))
        and set(routes) == complete_route_set
        and isinstance(exception.get("rationale"), str)
        and bool(exception["rationale"].strip())
    )


def _component_controls_are_valid(
    controls: Any,
    *,
    active_equipment_identity: str | None = None,
) -> bool:
    if not isinstance(controls, list):
        return False
    identities: list[str] = []
    for control in controls:
        if (
            not isinstance(control, dict)
            or set(control) != {"equipment_identity", "state"}
            or not isinstance(control.get("equipment_identity"), str)
            or not re.fullmatch(
                r"(skill|plugin|mcp|hook|other):[a-z0-9][a-z0-9._/-]*",
                control["equipment_identity"],
            )
            or control.get("state") not in {"enabled", "disabled"}
        ):
            return False
        if (
            control["equipment_identity"] == active_equipment_identity
            and control["state"] == "disabled"
        ):
            return False
        identities.append(control["equipment_identity"])
    return len(identities) == len(set(identities))


def _validate_lock(
    catalog: JsonObject,
    lock: JsonObject,
    coverage: list[CoverageEntry],
    diagnostics: list[Diagnostic],
) -> None:
    if not isinstance(lock, dict) or set(lock) != {
        "schema_version",
        "catalog_digest",
        "distributions",
        "coverage",
        "retirements",
    }:
        diagnostics.append(
            Diagnostic("LOCK_SHAPE_INVALID", "The resolved lock has the exact lock/v1 shape.")
        )
        return
    if lock.get("schema_version") != "lock/v1":
        diagnostics.append(
            Diagnostic("LOCK_SHAPE_INVALID", "The resolved lock schema version is lock/v1.")
        )
    if lock.get("catalog_digest") != canonical_json_sha256(catalog):
        diagnostics.append(
            Diagnostic(
                "LOCK_CATALOG_DIGEST_STALE",
                "The resolved lock is not bound to the canonical authored catalog.",
            )
        )

    lock_coverage = lock.get("coverage")
    if not isinstance(lock_coverage, list):
        diagnostics.append(
            Diagnostic("LOCK_SHAPE_INVALID", "Lock coverage is a list of expanded records.")
        )
        return
    seen_keys: set[tuple[str, str]] = set()
    lock_records: dict[tuple[str, str], Any] = {}
    for item in lock_coverage:
        if not isinstance(item, dict) or set(item) != {
            "equipment_identity",
            "harness",
            "record",
        }:
            diagnostics.append(
                Diagnostic("LOCK_SHAPE_INVALID", "Every lock coverage entry has one exact shape.")
            )
            continue
        key = (item["equipment_identity"], item["harness"])
        if key in seen_keys:
            diagnostics.append(
                Diagnostic(
                    "DUPLICATE_LOCK_COVERAGE",
                    "The resolved lock contains one record per equipment identity and harness.",
                    equipment_identity=key[0],
                    harness=key[1],
                )
            )
        seen_keys.add(key)
        lock_records[key] = item["record"]
    expected_records = {
        (entry.equipment_identity, entry.harness): entry.record for entry in coverage
    }
    if lock_records != expected_records or len(lock_coverage) != len(expected_records):
        diagnostics.append(
            Diagnostic(
                "LOCK_COVERAGE_MISMATCH",
                "Lock coverage must equal the complete expanded catalog coverage matrix.",
            )
        )

    active_route_membership: dict[tuple[str, str], set[str]] = {}
    for entry in coverage:
        selection = entry.record.get("provider_selection")
        if not isinstance(selection, dict):
            continue
        for route in selection.get("routes", []):
            if isinstance(route, dict) and isinstance(route.get("identity"), str):
                active_route_membership.setdefault(
                    (entry.harness, route["identity"]), set()
                ).add(entry.equipment_identity)

    lock_retirements = lock.get("retirements")
    catalog_retirements = catalog.get("retirements")
    if not isinstance(lock_retirements, list) or not isinstance(catalog_retirements, list):
        diagnostics.append(
            Diagnostic(
                "LOCK_RETIREMENT_MISMATCH",
                "Lock retirements are the exact expanded catalog-owned losing surfaces.",
            )
        )
    else:
        lock_by_identity = {
            item.get("identity"): item
            for item in lock_retirements
            if isinstance(item, dict) and isinstance(item.get("identity"), str)
        }
        catalog_by_identity = {
            item.get("identity"): item
            for item in catalog_retirements
            if isinstance(item, dict) and isinstance(item.get("identity"), str)
        }
        if (
            len(lock_by_identity) != len(lock_retirements)
            or len(catalog_by_identity) != len(catalog_retirements)
            or lock_by_identity != catalog_by_identity
        ):
            diagnostics.append(
                Diagnostic(
                    "LOCK_RETIREMENT_MISMATCH",
                    "Lock retirements are the exact expanded catalog-owned losing surfaces.",
                )
            )

    lock_distributions = lock.get("distributions")
    if not isinstance(lock_distributions, list):
        diagnostics.append(
            Diagnostic("LOCK_SHAPE_INVALID", "Lock distributions are a list of restore records.")
        )
        return
    distribution_records: dict[str, JsonObject] = {}
    distribution_sources: dict[str, JsonObject] = {}
    distribution_memberships: dict[str, tuple[str, ...]] = {}
    for item in lock_distributions:
        if (
            not isinstance(item, dict)
            or set(item) != {"identity", "source", "equipment", "restore"}
            or not isinstance(item.get("identity"), str)
            or not isinstance(item.get("equipment"), list)
            or not item.get("equipment")
            or not all(isinstance(identity, str) for identity in item["equipment"])
            or len(item["equipment"]) != len(set(item["equipment"]))
            or not _restore_is_valid(item.get("restore"))
            or item["identity"] in distribution_records
        ):
            diagnostics.append(
                Diagnostic(
                    "LOCK_DISTRIBUTION_INVALID",
                    "Each selected distribution has one complete immutable or native-rolling restore record.",
                )
            )
            continue
        distribution_records[item["identity"]] = item["restore"]
        distribution_sources[item["identity"]] = item["source"]
        distribution_memberships[item["identity"]] = tuple(item["equipment"])
    catalog_distribution_ids = {
        item.get("identity")
        for item in (
            catalog.get("distributions", [])
            if isinstance(catalog.get("distributions"), list)
            else []
        )
        if isinstance(item, dict)
    }
    if set(distribution_records) != catalog_distribution_ids:
        diagnostics.append(
            Diagnostic(
                "LOCK_DISTRIBUTION_INVALID",
                "The lock resolves every selected catalog distribution exactly once.",
            )
        )
    for distribution in (
        catalog.get("distributions", [])
        if isinstance(catalog.get("distributions"), list)
        else []
    ):
        if not isinstance(distribution, dict) or not isinstance(distribution.get("identity"), str):
            continue
        selection = distribution.get("selection")
        membership = distribution_memberships.get(distribution["identity"], ())
        if distribution_sources.get(distribution["identity"]) != distribution.get(
            "source"
        ):
            diagnostics.append(
                Diagnostic(
                    "LOCK_DISTRIBUTION_SOURCE_MISMATCH",
                    "The lock binds every distribution to the exact authored source selector.",
                )
            )
        source = distribution.get("source")
        restore = distribution_records.get(distribution["identity"])
        if not _distribution_source_matches_restore(source, restore):
            diagnostics.append(
                Diagnostic(
                    "DISTRIBUTION_SOURCE_RESTORE_MISMATCH",
                    "The resolved restore channel and artifact are exact consequences of the bound distribution source.",
                )
            )
        selection_valid = (
            isinstance(selection, dict)
            and (
                (set(selection) == {"all"} and selection.get("all") is True)
                or (
                    set(selection) == {"equipment"}
                    and isinstance(selection.get("equipment"), list)
                    and selection["equipment"]
                    and len(selection["equipment"]) == len(set(selection["equipment"]))
                    and set(selection["equipment"]) == set(membership)
                )
            )
        )
        if not selection_valid:
            diagnostics.append(
                Diagnostic(
                    "DISTRIBUTION_SELECTION_INVALID",
                    "Resolved distribution membership must satisfy exact all-or-explicit catalog selection.",
                )
            )
    for entry in coverage:
        selection = entry.record.get("provider_selection")
        if not isinstance(selection, dict):
            continue
        for route in selection.get("routes", []):
            route_membership = distribution_memberships.get(
                route.get("distribution"), ()
            )
            route_source = distribution_sources.get(route.get("distribution"))
            if not _distribution_source_matches_provider(
                route_source, route.get("provider")
            ):
                diagnostics.append(
                    Diagnostic(
                        "DISTRIBUTION_SOURCE_PROVIDER_MISMATCH",
                        "The selected provider invokes the exact package, channel, manager, or immutable source bound by its distribution.",
                        equipment_identity=entry.equipment_identity,
                        harness=entry.harness,
                        route_identity=route.get("identity"),
                    )
                )
            if entry.equipment_identity not in route_membership:
                diagnostics.append(
                    Diagnostic(
                        "ROUTE_DISTRIBUTION_MEMBERSHIP_INVALID",
                        "An active route distribution must include the current equipment identity in resolved membership.",
                        equipment_identity=entry.equipment_identity,
                        harness=entry.harness,
                        route_identity=route.get("identity"),
                    )
                )
            component_controls = route.get("component_controls")
            if isinstance(component_controls, list):
                for control in component_controls:
                    if (
                        isinstance(control, dict)
                        and isinstance(control.get("equipment_identity"), str)
                        and control["equipment_identity"] not in route_membership
                    ):
                        diagnostics.append(
                            Diagnostic(
                                "COMPONENT_CONTROL_DISTRIBUTION_INVALID",
                                "Every component control names equipment supplied by the selected route distribution.",
                                equipment_identity=entry.equipment_identity,
                                harness=entry.harness,
                                route_identity=route.get("identity"),
                            )
                        )
                    if (
                        isinstance(control, dict)
                        and control.get("state") == "enabled"
                        and isinstance(control.get("equipment_identity"), str)
                        and control["equipment_identity"]
                        not in active_route_membership.get(
                            (entry.harness, route.get("identity")), set()
                        )
                    ):
                        diagnostics.append(
                            Diagnostic(
                                "ENABLED_COMPONENT_CONTROL_COVERAGE_INVALID",
                                "An enabled component control must have active coverage on the same route and harness; disabled no-provider duplicates remain controlled but inactive.",
                                equipment_identity=entry.equipment_identity,
                                harness=entry.harness,
                                route_identity=route.get("identity"),
                            )
                        )
            if distribution_records.get(route.get("distribution")) != route.get("restore"):
                diagnostics.append(
                    Diagnostic(
                        "LOCK_DISTRIBUTION_INVALID",
                        "Active route restore evidence matches its resolved distribution.",
                        equipment_identity=entry.equipment_identity,
                        harness=entry.harness,
                        route_identity=route.get("identity"),
                    )
                )


def _distribution_source_matches_restore(source: Any, restore: Any) -> bool:
    if not isinstance(source, dict) or not isinstance(restore, dict):
        return False
    if source.get("kind") == "git":
        if restore.get("class") != "immutable":
            return False
        expected = f"git+{source.get('repository')}@{source.get('ref')}"
        artifact_ref = restore.get("artifact_ref")
        return (
            restore.get("revision") == source.get("ref")
            and isinstance(artifact_ref, str)
            and (artifact_ref == expected or artifact_ref.startswith(f"{expected}#"))
        )
    if source.get("kind") != "native_manager" or restore.get("class") != "native_rolling":
        return False
    manager = source.get("manager")
    package = source.get("package")
    channel = source.get("channel")
    if manager == "npx":
        return (
            restore.get("channel") == f"npm:{channel}"
            and restore.get("reviewed_baseline") == f"{package}@{channel}"
        )
    return restore.get("channel") == channel


def _distribution_source_matches_provider(source: Any, provider: Any) -> bool:
    if not isinstance(source, dict) or not isinstance(provider, dict):
        return False
    if source.get("kind") == "git":
        return provider.get("kind") == "standalone_skill"
    if source.get("kind") != "native_manager":
        return False
    manager = source.get("manager")
    package = source.get("package")
    channel = source.get("channel")
    if provider.get("kind") == "native_plugin":
        return (
            provider.get("manager") == manager
            and provider.get("plugin_id") == package
        )
    if provider.get("kind") != "direct_mcp" or manager != "npx":
        return (
            provider.get("kind") == "direct_mcp"
            and provider.get("transport") == "http"
            and manager == "http"
            and provider.get("url") == package
            and channel == "static"
        )
    expected_selector = f"{package}@{channel}"
    arguments = provider.get("arguments")
    if not isinstance(arguments, list):
        return False
    command = provider.get("command")
    invocation_arguments = arguments
    if command == "secret-exec":
        wrapper_boundary = next(
            (
                index
                for index in range(len(arguments) - 1)
                if arguments[index] == {"literal": "--"}
                and arguments[index + 1] == {"literal": "npx"}
            ),
            None,
        )
        if wrapper_boundary is None:
            return False
        invocation_arguments = arguments[wrapper_boundary + 2 :]
    elif command != "npx":
        return False
    return any(
        isinstance(argument, dict)
        and set(argument) == {"literal"}
        and argument.get("literal") == expected_selector
        for argument in invocation_arguments
    )
