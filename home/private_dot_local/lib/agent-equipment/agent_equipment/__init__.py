"""Public production API for global agent equipment desired state."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .authoring import (
    AuthoringError,
    CatalogAdditionProposal,
    DiscoveryHarnessBinding,
    DiscoveryPort,
    DiscoverySelection,
    TargetSelection,
    UnmanagedReport,
    find_unmanaged,
    propose_add,
)
from .canonical import (
    build_installed_implementation_manifest,
    byte_sha256,
    canonical_json_bytes,
    canonical_json_sha256,
    strict_load_json_bytes,
    strict_load_json_path,
)
from .discovery import MAX_DISCOVERY_FIELD_CHARACTERS, MAX_DISCOVERY_RECORDS
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
from .source_resolution import (
    SourceManifest,
    SourceResolution,
    SourceResolutionRequest,
    SourceResolver,
)
from .updater import propose_update
from .validator import load_catalog_lock, validate_catalog_lock

_CONFIG_DIRECTORY = "agent-equipment"
_CATALOG_NAME = "catalog-v1.json"
_LOCK_NAME = "lock-v1.json"
_TARGET_PATTERN = re.compile(
    r"(?:claude|codex|cursor)/"
    r"(?:skill|plugin|mcp|hook|other):"
    r"[a-z0-9][a-z0-9._/-]*"
)
_DISTRIBUTION_PATTERN = re.compile(r"distribution:[a-z0-9][a-z0-9._/-]*")

__all__ = (
    "CapabilityDiscovery",
    "Catalog",
    "CatalogAdditionProposal",
    "CatalogLockValidation",
    "CoverageRecord",
    "Diagnostic",
    "DiscoveryHarnessBinding",
    "DiscoverySelection",
    "FrozenJsonObject",
    "InstalledFile",
    "InstalledImplementationManifest",
    "Resolution",
    "ResolvedLock",
    "RuntimeInventory",
    "SourceManifest",
    "SourceResolution",
    "SourceResolutionRequest",
    "TargetSelection",
    "UnmanagedReport",
    "ValidatedCatalogLock",
    "ValidatedPlan",
    "build_installed_implementation_manifest",
    "byte_sha256",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "find_unmanaged",
    "freeze_json",
    "load_catalog_lock",
    "main",
    "propose_add",
    "propose_update",
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


def _installed_authored_paths() -> tuple[Path, Path]:
    authored_root = Path.home() / ".config" / _CONFIG_DIRECTORY
    return authored_root / _CATALOG_NAME, authored_root / _LOCK_NAME


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
        catalog_path, lock_path = _installed_authored_paths()
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


def _authoring_runtime_inputs(
    command: str,
    validated: ValidatedCatalogLock,
    installed_implementation_manifest: InstalledImplementationManifest,
    targets: tuple[str, ...] | None,
) -> tuple[DiscoverySelection | TargetSelection, DiscoveryPort]:
    """Return the closed private discovery registry for authored commands."""

    if command not in {"unmanaged", "add"}:
        raise ValueError("authored discovery command is unsupported")
    if type(validated) is not ValidatedCatalogLock:
        raise TypeError("authored discovery requires a validated catalog and lock")
    if type(installed_implementation_manifest) is not InstalledImplementationManifest:
        raise TypeError("authored discovery requires an installed manifest")
    if targets is not None and type(targets) is not tuple:
        raise TypeError("authored discovery targets must be immutable")
    raise RuntimeError("authored discovery adapters are unavailable")


def _source_resolution_runtime_input(
    validated: ValidatedCatalogLock,
    installed_implementation_manifest: InstalledImplementationManifest,
) -> SourceResolver:
    """Return the closed private source resolver for update."""

    if type(validated) is not ValidatedCatalogLock:
        raise TypeError("update requires a validated catalog and lock")
    if type(installed_implementation_manifest) is not InstalledImplementationManifest:
        raise TypeError("update requires an installed manifest")
    raise RuntimeError("source resolution is unavailable")


def _command_error_report(
    command: str,
    installed_implementation_manifest: InstalledImplementationManifest,
    *,
    code: str,
    message: str,
) -> FrozenJsonObject:
    document = freeze_json(
        {
            "command": command,
            "diagnostics": [{"code": code, "message": message}],
            "implementation_manifest_digest": installed_implementation_manifest.digest,
            "status": "error",
        }
    )
    if not isinstance(document, FrozenJsonObject):
        raise TypeError("command error report must be an immutable object")
    return document


def _runtime_unavailable_report(
    command: str,
    installed_implementation_manifest: InstalledImplementationManifest,
) -> tuple[int, FrozenJsonObject]:
    return 69, _command_error_report(
        command,
        installed_implementation_manifest,
        code=f"{command.upper()}_RUNTIME_UNAVAILABLE",
        message=f"{command.capitalize()} runtime inputs are unavailable.",
    )


def _authored_result(
    command: str,
    installed_implementation_manifest: InstalledImplementationManifest,
    result: UnmanagedReport
    | CatalogAdditionProposal
    | AuthoringError
    | FrozenJsonObject,
) -> tuple[int, FrozenJsonObject]:
    if isinstance(result, AuthoringError):
        return 65, _command_error_report(
            command,
            installed_implementation_manifest,
            code=result.code,
            message="The authored-state command failed.",
        )
    document = (
        result.document
        if isinstance(
            result,
            (UnmanagedReport, CatalogAdditionProposal),
        )
        else result
    )
    if not isinstance(document, FrozenJsonObject):
        return _runtime_unavailable_report(
            command,
            installed_implementation_manifest,
        )
    if contains_literal_credential(document):
        return 65, _command_error_report(
            command,
            installed_implementation_manifest,
            code="AUTHORED_RESULT_SECRET_MATERIAL",
            message="Authored command output contains literal secret material.",
        )
    return 0, document


def _run_authored_discovery_command(
    command: str,
    targets: tuple[str, ...] | None,
    installed_implementation_manifest: InstalledImplementationManifest,
) -> tuple[int, FrozenJsonObject]:
    try:
        catalog_path, lock_path = _installed_authored_paths()
        validation = load_catalog_lock(catalog_path, lock_path)
        base = validation.model
        if base is None:
            return _runtime_unavailable_report(
                command,
                installed_implementation_manifest,
            )
        selection, discovery = _authoring_runtime_inputs(
            command,
            base,
            installed_implementation_manifest,
            targets,
        )
        if command == "unmanaged":
            if type(selection) is not DiscoverySelection:
                return _runtime_unavailable_report(
                    command,
                    installed_implementation_manifest,
                )
            result = find_unmanaged(base, selection, discovery)
        else:
            if type(selection) is not TargetSelection:
                return _runtime_unavailable_report(
                    command,
                    installed_implementation_manifest,
                )
            result = propose_add(base, selection, discovery)
        return _authored_result(command, installed_implementation_manifest, result)
    except (Exception, SystemExit):  # noqa: BLE001 - untrusted read boundaries
        return _runtime_unavailable_report(
            command,
            installed_implementation_manifest,
        )


def _run_update(
    selection: FrozenJsonObject,
    installed_implementation_manifest: InstalledImplementationManifest,
) -> tuple[int, FrozenJsonObject]:
    try:
        catalog_path, lock_path = _installed_authored_paths()
        validation = load_catalog_lock(catalog_path, lock_path)
        base = validation.model
        if base is None:
            return _runtime_unavailable_report(
                "update",
                installed_implementation_manifest,
            )
        source_resolver = _source_resolution_runtime_input(
            base,
            installed_implementation_manifest,
        )
        proposal = propose_update(base, selection, source_resolver)
        return _authored_result(
            "update",
            installed_implementation_manifest,
            proposal,
        )
    except (Exception, SystemExit):  # noqa: BLE001 - untrusted source boundary
        return _runtime_unavailable_report(
            "update",
            installed_implementation_manifest,
        )


def _normalize_cli_targets(arguments: list[str]) -> tuple[str, ...]:
    if len(arguments) > MAX_DISCOVERY_RECORDS:
        raise ValueError("too many equipment targets")
    if any(len(argument) > MAX_DISCOVERY_FIELD_CHARACTERS for argument in arguments):
        raise ValueError("equipment target exceeds its field limit")
    if any(_TARGET_PATTERN.fullmatch(argument) is None for argument in arguments):
        raise ValueError("invalid equipment target")
    targets = tuple(sorted(arguments))
    if len(targets) != len(set(targets)):
        raise ValueError("equipment targets must be unique")
    return targets


def main(
    installed_implementation_manifest: InstalledImplementationManifest,
) -> int:
    """Run the closed production command boundary."""

    if type(installed_implementation_manifest) is not InstalledImplementationManifest:
        raise TypeError(
            "installed_implementation_manifest must be an "
            "InstalledImplementationManifest"
        )
    arguments = sys.argv[1:]
    if arguments == ["status"]:
        status, report = _run_status(installed_implementation_manifest)
        print(canonical_json_bytes(report).decode("utf-8"))
        return status
    try:
        if arguments and arguments[0] == "unmanaged":
            targets = _normalize_cli_targets(arguments[1:])
            status, report = _run_authored_discovery_command(
                "unmanaged",
                targets or None,
                installed_implementation_manifest,
            )
        elif arguments and arguments[0] == "add" and len(arguments) > 1:
            targets = _normalize_cli_targets(arguments[1:])
            status, report = _run_authored_discovery_command(
                "add",
                targets,
                installed_implementation_manifest,
            )
        elif arguments == ["update"]:
            selection = freeze_json({"all": True})
            if not isinstance(selection, FrozenJsonObject):
                raise TypeError("update selection must be an object")
            status, report = _run_update(
                selection,
                installed_implementation_manifest,
            )
        elif (
            len(arguments) == 2
            and arguments[0] == "update"
            and _DISTRIBUTION_PATTERN.fullmatch(arguments[1]) is not None
        ):
            selection = freeze_json({"distribution": arguments[1]})
            if not isinstance(selection, FrozenJsonObject):
                raise TypeError("update selection must be an object")
            status, report = _run_update(
                selection,
                installed_implementation_manifest,
            )
        elif arguments == ["apply"]:
            status, report = _runtime_unavailable_report(
                "apply",
                installed_implementation_manifest,
            )
        else:
            raise ValueError("invalid command or arguments")
    except (TypeError, ValueError):
        print("agent-equipment: invalid command or arguments", file=sys.stderr)
        return 64
    print(canonical_json_bytes(report).decode("utf-8"))
    return status
