#!/usr/bin/env python3
"""Executable validation model for the global agent-equipment design."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


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
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def load_and_validate(catalog_path: Path, lock_path: Path) -> DesignValidationResult:
    """Load a catalog and lock as UTF-8 JSON, then validate them together."""

    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    return validate_design(catalog, lock)


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
            resolved_membership,
            coverage,
            diagnostics,
        )
    )
    _validate_lock(catalog, lock, coverage, diagnostics)
    grouped_operations: dict[
        tuple[str, str, str, str], set[str]
    ] = {}
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
    planned = [
        PlannedOperation(
            equipment_identities=tuple(sorted(equipment_identities)),
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

    catalog_schema = json.loads(
        (SCHEMA_DIRECTORY / "catalog-v1.schema.json").read_text(encoding="utf-8")
    )
    lock_schema = json.loads(
        (SCHEMA_DIRECTORY / "lock-v1.schema.json").read_text(encoding="utf-8")
    )
    schemas = {
        "catalog-v1.schema.json": catalog_schema,
        "lock-v1.schema.json": lock_schema,
    }
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
        failures = _json_schema_failures(
            document,
            schemas[schema_name],
            schemas,
            schema_name,
            "$",
        )
        if failures:
            diagnostics.append(
                Diagnostic(
                    code,
                    f"The {label} violates {schema_name}: {failures[0]}",
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
        if any(
            _string_looks_like_secret_material(value)
            for value in _iter_string_leaves(document)
        ):
            diagnostics.append(
                Diagnostic(
                    "LITERAL_SECRET_MATERIAL",
                    f"The {label} contains literal secret material; use a structured secret reference.",
                )
            )
    return tuple(diagnostics)


def _iter_string_leaves(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _iter_string_leaves(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_string_leaves(item)


def _string_looks_like_secret_material(value: str) -> bool:
    candidate = value.replace("${{reference}}", "").replace("{reference}", "")
    patterns = (
        r"(?i)\bcanary\b",
        r"(?i)\b(?:authorization|proxy-authorization|x-api-key|api[_-]?key|access[_-]?token|password|client[_-]?secret)\s*[:=]\s*(?:bearer\s+\S+|(?!bearer(?:\s|$))\S+)",
        r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+",
        r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",
        r"\bAKIA[A-Z0-9]{16}\b",
        r"[?&](?:api[_-]?key|access[_-]?token|token|secret)=[^&#\s]+",
    )
    return any(re.search(pattern, candidate) is not None for pattern in patterns)


def _json_schema_failures(
    instance: Any,
    schema: JsonObject,
    schemas: Mapping[str, JsonObject],
    schema_name: str,
    path: str,
) -> list[str]:
    """Evaluate the JSON Schema keywords used by the v1 catalog and lock."""

    failures: list[str] = []
    reference = schema.get("$ref")
    if isinstance(reference, str):
        reference_file, separator, fragment = reference.partition("#")
        target_name = reference_file or schema_name
        target: Any = schemas.get(target_name)
        if target is None:
            return [f"{path} references unknown schema {target_name!r}"]
        if separator and fragment:
            for encoded_part in fragment.removeprefix("/").split("/"):
                part = encoded_part.replace("~1", "/").replace("~0", "~")
                if not isinstance(target, dict) or part not in target:
                    return [f"{path} references unknown fragment {reference!r}"]
                target = target[part]
        if not isinstance(target, dict):
            return [f"{path} references a non-schema value {reference!r}"]
        failures.extend(
            _json_schema_failures(
                instance,
                target,
                schemas,
                target_name,
                path,
            )
        )

    branches = schema.get("oneOf")
    if isinstance(branches, list):
        matches = sum(
            not _json_schema_failures(
                instance,
                branch,
                schemas,
                schema_name,
                path,
            )
            for branch in branches
            if isinstance(branch, dict)
        )
        if matches != 1:
            failures.append(f"{path} must match exactly one allowed shape")

    expected_type = schema.get("type")
    type_matches = {
        "object": isinstance(instance, dict),
        "array": isinstance(instance, list),
        "string": isinstance(instance, str),
        "boolean": isinstance(instance, bool),
        "integer": isinstance(instance, int) and not isinstance(instance, bool),
        "number": isinstance(instance, (int, float)) and not isinstance(instance, bool),
        "null": instance is None,
    }
    if isinstance(expected_type, str) and not type_matches.get(expected_type, False):
        failures.append(f"{path} must be of type {expected_type}")
        return failures

    if "const" in schema and instance != schema["const"]:
        failures.append(f"{path} must equal the required constant")
    if isinstance(schema.get("enum"), list) and instance not in schema["enum"]:
        failures.append(f"{path} must be one of the allowed values")

    if isinstance(instance, str):
        minimum_length = schema.get("minLength")
        if isinstance(minimum_length, int) and len(instance) < minimum_length:
            failures.append(f"{path} is shorter than {minimum_length} characters")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, instance) is None:
            failures.append(f"{path} does not match the required pattern")

    if isinstance(instance, list):
        minimum_items = schema.get("minItems")
        if isinstance(minimum_items, int) and len(instance) < minimum_items:
            failures.append(f"{path} has fewer than {minimum_items} items")
        if schema.get("uniqueItems") is True:
            serialized = [
                json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                for item in instance
            ]
            if len(serialized) != len(set(serialized)):
                failures.append(f"{path} items must be unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                failures.extend(
                    _json_schema_failures(
                        item,
                        item_schema,
                        schemas,
                        schema_name,
                        f"{path}[{index}]",
                    )
                )

    if isinstance(instance, dict):
        required = schema.get("required")
        if isinstance(required, list):
            for property_name in required:
                if property_name not in instance:
                    failures.append(f"{path}.{property_name} is required")
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for property_name, property_schema in properties.items():
                if property_name in instance and isinstance(property_schema, dict):
                    failures.extend(
                        _json_schema_failures(
                            instance[property_name],
                            property_schema,
                            schemas,
                            schema_name,
                            f"{path}.{property_name}",
                        )
                    )
            if schema.get("additionalProperties") is False:
                for property_name in instance.keys() - properties.keys():
                    failures.append(
                        f"{path}.{property_name} is not an allowed property"
                    )
    return failures


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
    declared_secret_names = {
        reference["name"]
        for reference in secret_references
        if _secret_reference_is_valid(reference)
    } if isinstance(secret_references, list) else set()
    if not _provider_is_valid(route.get("provider"), harness, declared_secret_names):
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
            all(
                isinstance(restore[field], str) and bool(restore[field].strip())
                for field in ("revision", "artifact_ref")
            )
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
            and all(
                isinstance(source.get(field), str) and bool(source[field].strip())
                for field in ("repository", "ref")
            )
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


def _provider_is_valid(
    provider: Any,
    harness: str,
    declared_secret_names: set[str],
) -> bool:
    if not isinstance(provider, dict):
        return False
    kind = provider.get("kind")
    if kind == "standalone_skill":
        return set(provider) == {"kind", "canonical_root"} and provider.get(
            "canonical_root"
        ) == "agents_skills"
    if kind == "native_plugin":
        plugin_id = provider.get("plugin_id")
        return (
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
            set(provider) == {"kind", "server_name", "transport", "url"}
            and isinstance(provider.get("url"), str)
            and provider["url"].startswith("https://")
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
    for argument in arguments:
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
            and argument.get("secret_reference") in declared_secret_names
            and isinstance(argument.get("template"), str)
            and argument["template"].count("{reference}") == 1
        ):
            secret_value_expected = False
            continue
        return False
    return not secret_value_expected


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
                    harness=harness,
                    route_identity=route_identity,
                    activation_group=route["activation_group"],
                    operation=operation,
                )
            )
    return planned


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
    distribution_memberships: dict[str, tuple[str, ...]] = {}
    for item in lock_distributions:
        if (
            not isinstance(item, dict)
            or set(item) != {"identity", "equipment", "restore"}
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
