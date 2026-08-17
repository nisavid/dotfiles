"""Public production API for global agent equipment desired state."""

from __future__ import annotations

import sys
from pathlib import Path

from .canonical import (
    build_installed_implementation_manifest,
    byte_sha256,
    canonical_json_bytes,
    canonical_json_sha256,
    strict_load_json_bytes,
    strict_load_json_path,
)
from .inventory import (
    ReadOnlyAdapter,
    admit_observe_request,
    collect_runtime_inventory,
)
from .model import (
    AdapterError,
    CapabilityDiscovery,
    Catalog,
    CatalogLockValidation,
    CoverageRecord,
    Diagnostic,
    FrozenJsonObject,
    InstalledFile,
    InstalledImplementationManifest,
    ObserveRequest,
    Resolution,
    ResolvedLock,
    RuntimeInventory,
    ValidatedCatalogLock,
    ValidatedPlan,
    freeze_json,
    thaw_json,
)
from .resolver import resolve
from .secrets import contains_literal_credential
from .validator import load_catalog_lock, validate_catalog_lock

_STATUS_CONFIG_DIRECTORY = "agent-equipment"
_STATUS_CATALOG_NAME = "catalog-v1.json"
_STATUS_LOCK_NAME = "lock-v1.json"

__all__ = (
    "CapabilityDiscovery",
    "Catalog",
    "CatalogLockValidation",
    "CoverageRecord",
    "Diagnostic",
    "FrozenJsonObject",
    "InstalledFile",
    "InstalledImplementationManifest",
    "Resolution",
    "ResolvedLock",
    "RuntimeInventory",
    "ValidatedCatalogLock",
    "ValidatedPlan",
    "build_installed_implementation_manifest",
    "byte_sha256",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "freeze_json",
    "load_catalog_lock",
    "main",
    "resolve",
    "strict_load_json_bytes",
    "strict_load_json_path",
    "thaw_json",
    "validate_catalog_lock",
)


def _status_runtime_inputs(
    validated: ValidatedCatalogLock,
    installed_implementation_manifest: InstalledImplementationManifest,
) -> tuple[tuple[ReadOnlyAdapter, ...], tuple[ObserveRequest, ...]]:
    """Return the closed private read-only adapter registry and requests.

    The installed registry is empty, so status fails closed. Adapter modules
    populate this private boundary without widening the exact public command or
    giving status mutation authority.
    """

    if type(validated) is not ValidatedCatalogLock:
        raise TypeError("status inputs require one validated catalog and lock")
    if type(installed_implementation_manifest) is not InstalledImplementationManifest:
        raise TypeError("status inputs require one installed implementation manifest")
    return (), ()


def _installed_status_paths() -> tuple[Path, Path]:
    status_root = Path.home() / ".config" / _STATUS_CONFIG_DIRECTORY
    return status_root / _STATUS_CATALOG_NAME, status_root / _STATUS_LOCK_NAME


def _status_requests_are_authorized(
    requests: object,
    validated: ValidatedCatalogLock,
    installed_implementation_manifest: InstalledImplementationManifest,
) -> bool:
    if (
        type(requests) is not tuple
        or not requests
        or any(type(request) is not ObserveRequest for request in requests)
    ):
        return False
    candidate_identities: set[str] = set()
    correlation_identities: set[str] = set()
    request_identities: set[str] = set()
    for request in requests:
        admitted = admit_observe_request(
            {
                "record_type": "ObserveRequest",
                "record": thaw_json(request.document),
            }
        )
        if isinstance(admitted, AdapterError) or admitted != request:
            return False
        document = request.document
        candidate_identity = document.get("candidate_identity")
        correlation_identity = document.get("correlation_identity")
        if (
            document.get("command") != "status"
            or document.get("purpose") != "inventory"
            or document.get("plan_digest") is not None
            or document.get("implementation_manifest_digest")
            != installed_implementation_manifest.digest
            or document.get("catalog_digest") != validated.catalog.digest
            or document.get("lock_digest") != validated.lock.digest
            or type(candidate_identity) is not str
            or not candidate_identity
            or type(correlation_identity) is not str
            or not correlation_identity
            or request.request_identity in request_identities
        ):
            return False
        candidate_identities.add(candidate_identity)
        correlation_identities.add(correlation_identity)
        request_identities.add(request.request_identity)
    return len(candidate_identities) == 1 and len(correlation_identities) == 1


def _status_report(
    installed_implementation_manifest: InstalledImplementationManifest,
    *,
    resolution: FrozenJsonObject | None = None,
) -> tuple[int, FrozenJsonObject]:
    """Build one immutable status report without acquiring runtime authority."""

    if type(installed_implementation_manifest) is not InstalledImplementationManifest:
        raise TypeError(
            "installed_implementation_manifest must be an "
            "InstalledImplementationManifest"
        )
    if resolution is not None and type(resolution) is not FrozenJsonObject:
        raise TypeError("resolution must be an immutable typed resolution")

    status: int
    document: dict[str, object]
    if resolution is None:
        status = 69
        document = {
            "command": "status",
            "diagnostics": [
                {
                    "code": "STATUS_RUNTIME_UNAVAILABLE",
                    "message": "Read-only status inputs are unavailable.",
                }
            ],
            "implementation_manifest_digest": installed_implementation_manifest.digest,
            "status": "error",
        }
    elif contains_literal_credential(resolution):
        status = 65
        document = {
            "command": "status",
            "diagnostics": [
                {
                    "code": "STATUS_SECRET_MATERIAL",
                    "message": "Status resolution contains literal secret material.",
                }
            ],
            "implementation_manifest_digest": installed_implementation_manifest.digest,
            "status": "error",
        }
    else:
        has_fatal_diagnostics = bool(resolution.get("diagnostics"))
        status = 65 if has_fatal_diagnostics else 0
        document = {
            "command": "status",
            "implementation_manifest_digest": installed_implementation_manifest.digest,
            "resolution": resolution,
            "status": "error" if has_fatal_diagnostics else "ok",
        }
    report = freeze_json(document)
    if type(report) is not FrozenJsonObject:
        raise TypeError("status report must be an immutable JSON object")
    return status, report


def _run_status(
    installed_implementation_manifest: InstalledImplementationManifest,
) -> tuple[int, FrozenJsonObject]:
    """Load reviewed inputs and run the closed read-only status pipeline."""

    try:
        catalog_path, lock_path = _installed_status_paths()
        validation = load_catalog_lock(catalog_path, lock_path)
        validated = validation.model
        if validated is None:
            return _status_report(installed_implementation_manifest)
        adapters, requests = _status_runtime_inputs(
            validated,
            installed_implementation_manifest,
        )
        if (
            type(adapters) is not tuple
            or not adapters
            or not _status_requests_are_authorized(
                requests,
                validated,
                installed_implementation_manifest,
            )
        ):
            return _status_report(installed_implementation_manifest)
        inventory = collect_runtime_inventory(
            adapters,
            requests,
            validated_catalog_lock=validated,
        )
        if isinstance(inventory, AdapterError):
            return _status_report(installed_implementation_manifest)
        if (
            inventory.implementation_manifest_digest
            != installed_implementation_manifest.digest
            or inventory.catalog_digest != validated.catalog.digest
            or inventory.lock_digest != validated.lock.digest
        ):
            return _status_report(installed_implementation_manifest)
        resolution = resolve(
            "status",
            validated.catalog,
            validated.lock,
            inventory,
            inventory.capabilities,
        )
        if resolution.mutation_plan is not None:
            return _status_report(installed_implementation_manifest)
        return _status_report(
            installed_implementation_manifest,
            resolution=resolution.as_json(),
        )
    except (Exception, SystemExit):  # noqa: BLE001 - untrusted read boundaries
        return _status_report(installed_implementation_manifest)


def main(
    installed_implementation_manifest: InstalledImplementationManifest,
) -> int:
    """Run the closed production command boundary."""

    if type(installed_implementation_manifest) is not InstalledImplementationManifest:
        raise TypeError(
            "installed_implementation_manifest must be an "
            "InstalledImplementationManifest"
        )
    if sys.argv[1:] == ["status"]:
        status, report = _run_status(installed_implementation_manifest)
        print(canonical_json_bytes(report).decode("utf-8"))
        return status
    print(
        "agent-equipment: only the read-only status command is available",
        file=sys.stderr,
    )
    return 64
