"""Pure authored catalog-and-lock update proposals."""

from __future__ import annotations

import re

from .canonical import canonical_json_bytes, canonical_json_sha256
from .model import FrozenJsonObject, ValidatedCatalogLock, freeze_json, thaw_json
from .source_resolution import (
    SourceResolver,
    admit_source_resolution,
    build_source_resolution_request,
    materialize_source_manifest,
)
from .validator import validate_catalog_lock

MAX_UPDATE_DISTRIBUTIONS = 4096
MAX_UPDATE_EQUIPMENT_IDENTITIES = 65_536
MAX_UPDATE_COVERAGE_RECORDS = 196_608
MAX_UPDATE_CATALOG_BYTES = 4 * 1024 * 1024
MAX_UPDATE_LOCK_BYTES = 16 * 1024 * 1024
MAX_UPDATE_PROPOSAL_BYTES = 32 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


def _require_frozen_object(value: object, field: str) -> FrozenJsonObject:
    if not isinstance(value, FrozenJsonObject):
        raise TypeError(f"update {field} must be an object")
    return value


def _require_array(value: object, field: str) -> tuple[object, ...]:
    if type(value) is not tuple:
        raise ValueError(f"update {field} must be an array")
    return value


def _distribution_identity(
    distribution: FrozenJsonObject,
    *,
    manifest: bool,
) -> str:
    field = "distribution_identity" if manifest else "identity"
    identity = distribution.get(field)
    if type(identity) is not str or not identity.startswith("distribution:"):
        raise ValueError(f"update distribution {field} is invalid")
    return identity


def _index_distributions(
    value: object,
    *,
    field: str,
    manifest: bool,
) -> tuple[tuple[FrozenJsonObject, ...], dict[str, FrozenJsonObject]]:
    serialized = _require_array(value, field)
    if not serialized or len(serialized) > MAX_UPDATE_DISTRIBUTIONS:
        raise ValueError(f"update {field} must be bounded and nonempty")
    by_identity: dict[str, FrozenJsonObject] = {}
    for item in serialized:
        distribution = _require_frozen_object(item, f"{field} entry")
        identity = _distribution_identity(distribution, manifest=manifest)
        if identity in by_identity:
            raise ValueError(f"update {field} identities must be unique")
        by_identity[identity] = distribution
    identities = tuple(sorted(by_identity))
    return tuple(by_identity[identity] for identity in identities), by_identity


def _normalize_selection(
    selection: FrozenJsonObject,
    available_identities: tuple[str, ...],
) -> tuple[FrozenJsonObject, tuple[str, ...]]:
    if not isinstance(selection, FrozenJsonObject):
        raise TypeError("update selection must be frozen JSON")
    if set(selection) == {"all"} and selection.get("all") is True:
        return selection, available_identities
    if set(selection) != {"distribution"}:
        raise ValueError("update selection must be all or one exact distribution")
    identity = selection.get("distribution")
    if type(identity) is not str or not identity.startswith("distribution:"):
        raise ValueError("update distribution selector is invalid")
    if identity not in available_identities:
        raise ValueError("update distribution selector is not in the catalog")
    return selection, (identity,)


def _source_manifest_digest(manifest: FrozenJsonObject) -> str:
    value = manifest.get("source_manifest_digest")
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError("update source manifest digest is invalid")
    payload = thaw_json(manifest)
    if type(payload) is not dict:
        raise TypeError("update source manifest must be an object")
    payload.pop("source_manifest_digest")
    if value != canonical_json_sha256(payload):
        raise ValueError("update source manifest digest is not canonical")
    return value


def _retirement_distribution_identity(retirement: FrozenJsonObject) -> str:
    direct = retirement.get("distribution_identity")
    if type(direct) is str:
        return direct
    route = retirement.get("route")
    if isinstance(route, FrozenJsonObject):
        routed = route.get("distribution")
        if type(routed) is str:
            return routed
    raise ValueError("update retirement distribution binding is unavailable")


def _validate_retirement_bindings(
    retirements: tuple[object, ...],
    manifests: tuple[FrozenJsonObject, ...],
) -> None:
    available = {
        (
            _distribution_identity(manifest, manifest=True),
            _source_manifest_digest(manifest),
        )
        for manifest in manifests
    }
    for value in retirements:
        retirement = _require_frozen_object(value, "retirement")
        digest = retirement.get("source_manifest_digest")
        if (
            type(digest) is not str
            or (_retirement_distribution_identity(retirement), digest) not in available
        ):
            raise ValueError(
                "update retirement has no bound historical source manifest"
            )


def _require_retirements_for_membership_shrink(
    old_manifest: FrozenJsonObject,
    new_manifest: FrozenJsonObject,
    retirements: tuple[object, ...],
) -> None:
    old_equipment = _require_array(
        old_manifest.get("equipment"),
        "old source-manifest equipment",
    )
    new_available = _require_array(
        new_manifest.get("available_equipment"),
        "new available equipment",
    )
    if any(type(item) is not str for item in (*old_equipment, *new_available)):
        raise ValueError("update source-manifest equipment identities are invalid")
    disappeared = set(old_equipment) - set(new_available)
    if not disappeared:
        return
    distribution_identity = _distribution_identity(old_manifest, manifest=True)
    source_manifest_digest = _source_manifest_digest(old_manifest)
    retired_equipment: set[str] = set()
    for value in retirements:
        retirement = _require_frozen_object(value, "retirement")
        equipment_identity = retirement.get("equipment_identity")
        if (
            type(equipment_identity) is str
            and _retirement_distribution_identity(retirement) == distribution_identity
            and retirement.get("source_manifest_digest") == source_manifest_digest
            and retirement.get("desired_state") in {"absent", "disabled"}
        ):
            retired_equipment.add(equipment_identity)
    if not disappeared.issubset(retired_equipment):
        raise ValueError(
            "update disappearing active equipment requires exact retirements"
        )


def _freeze_object(document: object, field: str) -> FrozenJsonObject:
    frozen = freeze_json(document)
    if not isinstance(frozen, FrozenJsonObject):
        raise TypeError(f"update {field} must be an object")
    return frozen


def _mutable_object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"update {field} must be an object")
    return value


def _mutable_array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"update {field} must be an array")
    return value


def _identity_sort_key(value: object) -> str:
    if isinstance(value, dict) and isinstance(value.get("identity"), str):
        return value["identity"]
    return ""


def _normalize_catalog_order(catalog: dict[str, object]) -> None:
    """Sort identity-addressed registries without changing ordered fields."""

    for field in (
        "distributions",
        "coverage_templates",
        "equipment",
        "retirements",
    ):
        _mutable_array(catalog.get(field), f"catalog {field}").sort(
            key=_identity_sort_key
        )


def _catalog_coverage_records(
    catalog: dict[str, object],
) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    for value in _mutable_array(
        catalog.get("coverage_templates"),
        "catalog coverage templates",
    ):
        template = _mutable_object(value, "catalog coverage template")
        records.append(
            _mutable_object(
                template.get("record"),
                "catalog coverage-template record",
            )
        )
    for value in _mutable_array(catalog.get("equipment"), "catalog equipment"):
        equipment = _mutable_object(value, "catalog equipment entry")
        coverage = _mutable_object(
            equipment.get("coverage"),
            "catalog equipment coverage",
        )
        for entry_value in coverage.values():
            entry = _mutable_object(entry_value, "catalog equipment coverage entry")
            if set(entry) == {"record"}:
                records.append(
                    _mutable_object(
                        entry.get("record"),
                        "catalog exact coverage record",
                    )
                )
    return tuple(records)


def _replace_npx_selector(
    provider: dict[str, object],
    old_restore: dict[str, object],
    new_restore: dict[str, object],
) -> None:
    if provider.get("kind") != "direct_mcp":
        raise ValueError("update npx source route must use a direct MCP provider")
    arguments = _mutable_array(provider.get("arguments"), "npx arguments")
    command = provider.get("command")
    if command == "npx":
        invocation_start = 0
    elif command == "secret-exec":
        boundaries = [
            index
            for index in range(len(arguments) - 1)
            if arguments[index] == {"literal": "--"}
            and arguments[index + 1] == {"literal": "npx"}
        ]
        if len(boundaries) != 1:
            raise ValueError("update secret-wrapped npx route is ambiguous")
        invocation_start = boundaries[0] + 2
    else:
        raise ValueError("update npx source route has no exact npx invocation")
    old_selector = old_restore.get("reviewed_baseline")
    new_selector = new_restore.get("reviewed_baseline")
    if not isinstance(old_selector, str) or not isinstance(new_selector, str):
        raise TypeError("update npx source route baselines are invalid")
    matches = [
        index
        for index in range(invocation_start, len(arguments))
        if arguments[index] == {"literal": old_selector}
    ]
    if len(matches) != 1:
        raise ValueError("update npx source route selector is ambiguous")
    arguments[matches[0]] = {"literal": new_selector}


def _rewrite_catalog_route_evidence(
    catalog: dict[str, object],
    distribution_identity: str,
    old_manifest: FrozenJsonObject,
    new_manifest: FrozenJsonObject,
) -> None:
    old_restore = thaw_json(old_manifest.get("restore"))
    new_restore = thaw_json(new_manifest.get("restore"))
    source = thaw_json(new_manifest.get("source"))
    if (
        not isinstance(old_restore, dict)
        or not isinstance(new_restore, dict)
        or not isinstance(source, dict)
    ):
        raise TypeError("update source-manifest restore evidence must be objects")
    for record in _catalog_coverage_records(catalog):
        provider_selection = record.get("provider_selection")
        if not isinstance(provider_selection, dict):
            continue
        routes = _mutable_array(
            provider_selection.get("routes"),
            "catalog coverage routes",
        )
        for value in routes:
            route = _mutable_object(value, "catalog coverage route")
            if route.get("distribution") != distribution_identity:
                continue
            if route.get("restore") != old_restore:
                raise ValueError(
                    "update catalog route restore does not match its base manifest"
                )
            provider = _mutable_object(
                route.get("provider"),
                "catalog route provider",
            )
            if source.get("kind") == "git":
                if provider.get("kind") != "standalone_skill":
                    raise ValueError(
                        "update Git source route must use a standalone-skill provider"
                    )
            elif source.get("manager") == "npx":
                _replace_npx_selector(
                    provider,
                    old_restore,
                    new_restore,
                )
            route["restore"] = {key: value for key, value in new_restore.items()}


def _catalog_distributions_by_identity(
    catalog: dict[str, object],
) -> dict[str, dict[str, object]]:
    indexed: dict[str, dict[str, object]] = {}
    for value in _mutable_array(
        catalog.get("distributions"),
        "catalog distributions",
    ):
        distribution = _mutable_object(value, "catalog distribution")
        identity = distribution.get("identity")
        if not isinstance(identity, str) or identity in indexed:
            raise ValueError("update catalog distribution identities are invalid")
        indexed[identity] = distribution
    return indexed


def _catalog_templates_by_identity(
    catalog: dict[str, object],
) -> dict[str, dict[str, object]]:
    indexed: dict[str, dict[str, object]] = {}
    for value in _mutable_array(
        catalog.get("coverage_templates"),
        "catalog coverage templates",
    ):
        template = _mutable_object(value, "catalog coverage template")
        identity = template.get("identity")
        if not isinstance(identity, str) or identity in indexed:
            raise ValueError("update catalog template identities are invalid")
        indexed[identity] = template
    return indexed


def _catalog_equipment_coverage_by_identity(
    catalog: dict[str, object],
) -> dict[str, dict[str, object]]:
    indexed: dict[str, dict[str, object]] = {}
    for value in _mutable_array(catalog.get("equipment"), "catalog equipment"):
        equipment = _mutable_object(value, "catalog equipment entry")
        identity = equipment.get("identity")
        coverage = equipment.get("coverage")
        if (
            not isinstance(identity, str)
            or identity in indexed
            or not isinstance(coverage, dict)
        ):
            raise ValueError("update catalog equipment entries are invalid")
        indexed[identity] = coverage
    return indexed


def _template_record(
    templates: dict[str, dict[str, object]],
    reference: object,
    harness: str,
) -> dict[str, object]:
    if not isinstance(reference, str):
        raise TypeError("update coverage template reference must be a string")
    template = templates.get(reference)
    if template is None or template.get("harness") != harness:
        raise ValueError("update coverage template reference is unresolved")
    return _mutable_object(template.get("record"), "coverage template record")


def _expanded_coverage(
    catalog: dict[str, object],
    manifests: tuple[FrozenJsonObject, ...],
) -> list[dict[str, object]]:
    distributions = _catalog_distributions_by_identity(catalog)
    templates = _catalog_templates_by_identity(catalog)
    equipment_coverage = _catalog_equipment_coverage_by_identity(catalog)
    harness_values = _mutable_array(
        catalog.get("active_harnesses"),
        "active harnesses",
    )
    if not harness_values or any(not isinstance(item, str) for item in harness_values):
        raise ValueError("update active harnesses are invalid")
    harnesses = tuple(item for item in harness_values if isinstance(item, str))
    membership: dict[str, tuple[str, ...]] = {}
    selected_identities: set[str] = set()
    for manifest in manifests:
        distribution_identity = _distribution_identity(manifest, manifest=True)
        equipment = _require_array(
            manifest.get("equipment"),
            "source-manifest equipment",
        )
        if any(not isinstance(item, str) for item in equipment):
            raise ValueError("update source-manifest equipment is invalid")
        typed_equipment = tuple(item for item in equipment if isinstance(item, str))
        membership[distribution_identity] = typed_equipment
        selected_identities.update(typed_equipment)
    if len(selected_identities) > MAX_UPDATE_EQUIPMENT_IDENTITIES:
        raise ValueError("update expanded equipment exceeds its count bound")

    coverage: list[dict[str, object]] = []
    for equipment_identity in sorted(selected_identities):
        exact = equipment_coverage.get(equipment_identity, {})
        selected_distributions = tuple(
            identity
            for identity in sorted(membership)
            if equipment_identity in membership[identity]
        )
        for harness in harnesses:
            record: dict[str, object] | None = None
            exact_entry = exact.get(harness)
            if exact_entry is not None:
                entry = _mutable_object(exact_entry, "exact coverage entry")
                if set(entry) == {"record"}:
                    record = _mutable_object(
                        entry.get("record"),
                        "exact coverage record",
                    )
                elif set(entry) == {"template"}:
                    record = _template_record(
                        templates,
                        entry.get("template"),
                        harness,
                    )
                else:
                    raise ValueError("update exact coverage entry is not closed")
            else:
                fallback_records: list[dict[str, object]] = []
                for distribution_identity in selected_distributions:
                    distribution = distributions.get(distribution_identity)
                    if distribution is None:
                        raise ValueError(
                            "update source-manifest distribution is absent from catalog"
                        )
                    references = _mutable_object(
                        distribution.get("coverage_templates"),
                        "distribution coverage templates",
                    )
                    reference = references.get(harness)
                    if reference is not None:
                        fallback_records.append(
                            _template_record(templates, reference, harness)
                        )
                if len(fallback_records) != 1:
                    raise ValueError(
                        "update cannot resolve one complete coverage record"
                    )
                record = fallback_records[0]
            coverage.append(
                {
                    "equipment_identity": equipment_identity,
                    "harness": harness,
                    "record": record,
                }
            )
            if len(coverage) > MAX_UPDATE_COVERAGE_RECORDS:
                raise ValueError("update expanded coverage exceeds its count bound")
    return coverage


def _manifest_sort_key(manifest: FrozenJsonObject) -> tuple[str, str]:
    return (
        _distribution_identity(manifest, manifest=True),
        _source_manifest_digest(manifest),
    )


def _exact_history(
    retirements: tuple[object, ...],
    current_manifests: tuple[FrozenJsonObject, ...],
    candidates: tuple[FrozenJsonObject, ...],
) -> tuple[FrozenJsonObject, ...]:
    by_digest: dict[str, FrozenJsonObject] = {}
    for manifest in candidates:
        digest = _source_manifest_digest(manifest)
        existing = by_digest.get(digest)
        if existing is not None and existing != manifest:
            raise ValueError("update source-manifest digest is ambiguous")
        by_digest[digest] = manifest
    current_digests = {
        _source_manifest_digest(manifest) for manifest in current_manifests
    }
    retirement_digests: set[str] = set()
    for value in retirements:
        retirement = _require_frozen_object(value, "retirement")
        digest = retirement.get("source_manifest_digest")
        if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
            raise ValueError("update retirement source-manifest digest is invalid")
        retirement_digests.add(digest)
    required_history_digests = retirement_digests - current_digests
    if any(digest not in by_digest for digest in required_history_digests):
        raise ValueError("update retirement has no historical source manifest")
    history = tuple(
        sorted(
            (by_digest[digest] for digest in required_history_digests),
            key=_manifest_sort_key,
        )
    )
    _validate_retirement_bindings(retirements, (*current_manifests, *history))
    return history


def _validated_proposed_pair(
    catalog_document: FrozenJsonObject,
    lock_document: FrozenJsonObject,
) -> ValidatedCatalogLock:
    validation = validate_catalog_lock(
        thaw_json(catalog_document),
        thaw_json(lock_document),
    )
    if validation.model is None:
        codes = ", ".join(sorted({item.code for item in validation.diagnostics}))
        raise ValueError(f"update proposed catalog-and-lock pair is invalid: {codes}")
    return validation.model


def propose_update(
    base: ValidatedCatalogLock,
    selection: FrozenJsonObject,
    source_resolver: SourceResolver,
) -> FrozenJsonObject:
    """Return one atomic full catalog-and-lock update proposal."""

    if type(base) is not ValidatedCatalogLock:
        raise TypeError("update requires one validated catalog-and-lock pair")
    catalog_distributions, catalog_by_identity = _index_distributions(
        base.catalog.document.get("distributions"),
        field="catalog distributions",
        manifest=False,
    )
    lock_distributions, lock_by_identity = _index_distributions(
        base.lock.document.get("distributions"),
        field="lock distributions",
        manifest=True,
    )
    catalog_identities = tuple(
        _distribution_identity(item, manifest=False) for item in catalog_distributions
    )
    if set(catalog_identities) != set(lock_by_identity):
        raise ValueError("update catalog and lock distribution identities differ")
    normalized_selection, selected_identities = _normalize_selection(
        selection,
        catalog_identities,
    )

    catalog_payload = thaw_json(base.catalog.document)
    if not isinstance(catalog_payload, dict):
        raise TypeError("update catalog payload must be an object")

    history_values = _require_array(
        base.lock.document.get("source_manifest_history"),
        "source-manifest history",
    )
    history: list[FrozenJsonObject] = [
        _require_frozen_object(item, "source-manifest history entry")
        for item in history_values
    ]
    retirements = _require_array(base.lock.document.get("retirements"), "retirements")
    _validate_retirement_bindings(
        retirements,
        (*lock_distributions, *history),
    )

    proposed_by_identity = dict(lock_by_identity)
    manifest_candidates = [*lock_distributions, *history]
    current_manifest_bytes = sum(
        len(canonical_json_bytes(manifest)) for manifest in lock_distributions
    )
    for identity in selected_identities:
        catalog_distribution = catalog_by_identity[identity]
        old_manifest = lock_by_identity[identity]
        source = _require_frozen_object(
            catalog_distribution.get("source"),
            "catalog distribution source",
        )
        distribution_selection = _require_frozen_object(
            catalog_distribution.get("selection"),
            "catalog distribution selection",
        )
        request = build_source_resolution_request(
            base_catalog_digest=base.catalog.digest,
            base_lock_digest=base.lock.digest,
            distribution_identity=identity,
            source=source,
            base_source_manifest_digest=_source_manifest_digest(old_manifest),
            selection=distribution_selection,
        )
        try:
            resolution_document = source_resolver.resolve(request)
            resolution = admit_source_resolution(request, resolution_document)
            new_manifest = materialize_source_manifest(
                request,
                resolution,
                old_manifest,
            ).document
        except (Exception, SystemExit):  # noqa: BLE001 - untrusted resolver boundary
            raise ValueError("update source resolution failed") from None
        _require_retirements_for_membership_shrink(
            old_manifest,
            new_manifest,
            retirements,
        )
        current_manifest_bytes -= len(canonical_json_bytes(old_manifest))
        current_manifest_bytes += len(canonical_json_bytes(new_manifest))
        if current_manifest_bytes > MAX_UPDATE_LOCK_BYTES:
            raise ValueError("update current source manifests exceed their byte bound")
        _rewrite_catalog_route_evidence(
            catalog_payload,
            identity,
            old_manifest,
            new_manifest,
        )
        proposed_by_identity[identity] = new_manifest
        manifest_candidates.append(new_manifest)

    _normalize_catalog_order(catalog_payload)
    proposed_distributions = tuple(
        proposed_by_identity[identity] for identity in sorted(proposed_by_identity)
    )
    proposed_history = _exact_history(
        retirements,
        proposed_distributions,
        tuple(manifest_candidates),
    )

    catalog_document = _freeze_object(catalog_payload, "proposed catalog")
    if len(canonical_json_bytes(catalog_document)) > MAX_UPDATE_CATALOG_BYTES:
        raise ValueError("update proposed catalog exceeds its byte bound")
    catalog_digest = canonical_json_sha256(catalog_document)
    lock_payload = thaw_json(base.lock.document)
    if type(lock_payload) is not dict:
        raise TypeError("update lock payload must be an object")
    lock_payload["catalog_digest"] = catalog_digest
    lock_payload["distributions"] = [thaw_json(item) for item in proposed_distributions]
    lock_payload["source_manifest_history"] = [
        thaw_json(item) for item in proposed_history
    ]
    lock_payload["coverage"] = _expanded_coverage(
        catalog_payload,
        proposed_distributions,
    )
    _mutable_array(lock_payload.get("retirements"), "lock retirements").sort(
        key=_identity_sort_key
    )
    lock_document = _freeze_object(lock_payload, "proposed lock")
    if len(canonical_json_bytes(lock_document)) > MAX_UPDATE_LOCK_BYTES:
        raise ValueError("update proposed lock exceeds its byte bound")
    validated = _validated_proposed_pair(catalog_document, lock_document)
    catalog_document = validated.catalog.document
    lock_document = validated.lock.document
    catalog_digest = validated.catalog.digest
    lock_digest = validated.lock.digest

    proposal_payload = {
        "schema_version": "update-proposal/v1",
        "command": "update",
        "base_catalog_digest": base.catalog.digest,
        "base_lock_digest": base.lock.digest,
        "selection": normalized_selection,
        "resolved_distribution_identities": selected_identities,
        "catalog": catalog_document,
        "catalog_digest": catalog_digest,
        "lock": lock_document,
        "lock_digest": lock_digest,
    }
    proposal_document = proposal_payload | {
        "proposal_digest": canonical_json_sha256(proposal_payload)
    }
    if len(canonical_json_bytes(proposal_document)) > MAX_UPDATE_PROPOSAL_BYTES:
        raise ValueError("update proposal exceeds its byte bound")
    return _freeze_object(
        proposal_document,
        "proposal",
    )
