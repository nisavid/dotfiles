"""Production catalog/lock validation with a compatibility-only design model."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, TypeGuard
from urllib.parse import urlsplit

from ._json_schema import (
    validate_document as _validate_schema,
)
from ._json_schema import (
    validate_schema_documents as _validate_schema_documents,
)
from .canonical import (
    canonical_json_bytes as _canonical_json_bytes,
)
from .canonical import (
    canonical_json_sha256 as _canonical_json_sha256,
)
from .canonical import (
    strict_load_json_bytes,
)
from .model import (
    Catalog,
    CatalogLockValidation,
    CoverageRecord,
    Diagnostic,
    FrozenJsonObject,
    ResolvedLock,
    ValidatedCatalogLock,
    freeze_json,
    thaw_json,
)
from .secrets import contains_literal_credential
from .source_resolution import MAX_AVAILABLE_EQUIPMENT, MAX_SOURCE_RESOLUTION_BYTES

__all__ = ("load_catalog_lock", "validate_catalog_lock")

JsonObject = Mapping[str, Any]
_GroupedOperation = tuple[
    tuple[str, ...],
    tuple[str, ...],
    str,
    str,
    str,
    str,
]
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
SCHEMA_DIRECTORY = Path(__file__).resolve().parent.parent / "schemas"
MAX_SCHEMA_BYTES = 1024 * 1024
MAX_CATALOG_BYTES = 4 * 1024 * 1024
MAX_LOCK_BYTES = 16 * 1024 * 1024
MAX_SOURCE_FIELD_CHARACTERS = 4096
MAX_SOURCE_PACKAGE_CHARACTERS = 255
_DOCUMENT_READ_CHUNK_BYTES = 1024 * 1024
_NATIVE_MANAGER_PACKAGE_PATTERN = re.compile(
    r"(?:@[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._-]{0,127}|"
    r"[a-z0-9][a-z0-9._-]{0,127}(?:@[a-z0-9][a-z0-9._-]{0,127})?)"
)
_NPX_PACKAGE_PATTERN = re.compile(
    r"(?:@[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._-]{0,127}|"
    r"[a-z0-9][a-z0-9._-]{0,127})"
)
_NATIVE_CHANNEL_PATTERN = re.compile(r"[a-z0-9][a-z0-9._/-]{0,127}")
_SEMANTIC_VERSION_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
_OBSERVATION_SOURCE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,/_+-]{0,254}")
EXPECTED_SCHEMA_SHA256 = MappingProxyType(
    {
        "acceptance-evidence-v1.schema.json": "5264aad08075c115cb3633f3d0f9a46b8a0a2027758b931c4334a2f234e660d5",
        "adapter-contract-v1.schema.json": "b7ea9ca7c9c2c9c114a1090c4df1f2b3241616e2ae915558d2ca286c945b68d5",
        "captured-state-v1.schema.json": "d0c30850f03366dd612208d12ee35b2462d84e5e6901e3ca7d0a6b0ed3bdf693",
        "catalog-v1.schema.json": "d0582e3343d9960ffcadbdf4afe694b9bdd6f37bdab5d381d77b91e29be8c3b6",
        "execution-authority-v1.schema.json": "30c61c9fdbbc52679bf1f18bf80cf99d7429d7efc07a8b6ccf80dde7ee4d5b48",
        "lock-v1.schema.json": "482b55f05c6d0622961f2526095975d946d651b9bf398c06e33fd04f8e5d4714",
        "plan-action-set-v1.schema.json": "2096ece6780cedd1df10dea43a279bbb360550927ad69d871c0ad75c1ffcf504",
    }
)
_captured_schema_bytes = globals().pop(
    "_AGENT_EQUIPMENT_CAPTURED_SCHEMA_BYTES",
    None,
)
if _captured_schema_bytes is None:
    _CAPTURED_SCHEMA_BYTES: Mapping[str, bytes] | None = None
elif isinstance(_captured_schema_bytes, Mapping) and all(
    type(name) is str and type(payload) is bytes
    for name, payload in _captured_schema_bytes.items()
):
    _CAPTURED_SCHEMA_BYTES = MappingProxyType(dict(_captured_schema_bytes))
else:
    _CAPTURED_SCHEMA_BYTES = MappingProxyType({})


@dataclass(frozen=True, order=True)
class _CoverageEntry:
    equipment_identity: str
    harness: str
    record: JsonObject


@dataclass(frozen=True, order=True)
class _PlannedOperation:
    equipment_identities: tuple[str, ...]
    controlled_equipment_identities: tuple[str, ...]
    harness: str
    route_identity: str
    activation_group: str
    operation: str


@dataclass(frozen=True)
class _DesignValidationResult:
    diagnostics: tuple[Diagnostic, ...]
    coverage: tuple[_CoverageEntry, ...]
    mutation_plan: tuple[_PlannedOperation, ...] | None


@dataclass(frozen=True, slots=True)
class _HeldPathEntry:
    parent_descriptor: int | None
    name: str
    descriptor: int
    identity: tuple[int, int, int]
    stable_metadata: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _HeldDocument:
    path_entries: tuple[_HeldPathEntry, ...]
    parent_descriptor: int
    leaf_name: str
    descriptor: int
    identity: tuple[int, int, int]
    stable_metadata: tuple[int, ...]


def _diagnostic_sort_key(item: Diagnostic) -> tuple[str, str, str, str, str]:
    return (
        item.equipment_identity or "",
        item.harness or "",
        item.route_identity or "",
        item.code,
        item.message,
    )


def _planned_operation_sort_key(
    item: _PlannedOperation,
) -> tuple[tuple[str, ...], tuple[str, ...], str, str, str, int]:
    return (
        item.equipment_identities,
        item.controlled_equipment_identities,
        item.harness,
        item.route_identity,
        item.activation_group,
        OPERATIONS.index(item.operation),
    )


def canonical_json_sha256(document: JsonObject) -> str:
    """Return the digest of UTF-8 RFC-style canonical JSON for *document*."""

    return _canonical_json_sha256(document)


def _source_string_is_bounded(value: Any) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= MAX_SOURCE_FIELD_CHARACTERS
    )


def _document_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
    )


def _stable_document_metadata(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _stable_directory_metadata(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
    )


def _hold_bounded_document(
    descriptors: ExitStack,
    path: Path,
    *,
    maximum_bytes: int,
) -> _HeldDocument:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    nonblocking = getattr(os, "O_NONBLOCK", None)
    if type(no_follow) is not int or type(nonblocking) is not int:
        raise OSError("safe nonblocking document reads are unavailable")
    path_entries, parent_descriptor = _hold_document_parent(
        descriptors,
        path,
        no_follow=no_follow,
    )
    leaf_name = path.name
    if not leaf_name:
        raise ValueError("document leaf name is unavailable")
    before = os.stat(
        leaf_name,
        dir_fd=parent_descriptor,
        follow_symlinks=False,
    )
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_size > maximum_bytes
    ):
        raise ValueError("document leaf is not an admissible regular file")
    flags = os.O_RDONLY | no_follow | nonblocking | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(leaf_name, flags, dir_fd=parent_descriptor)
    descriptors.callback(os.close, descriptor)
    os.set_inheritable(descriptor, False)
    opened = os.fstat(descriptor)
    if (
        _document_identity(before) != _document_identity(opened)
        or _stable_document_metadata(before) != _stable_document_metadata(opened)
        or not stat.S_ISREG(opened.st_mode)
        or opened.st_nlink != 1
        or opened.st_size > maximum_bytes
    ):
        raise ValueError("document leaf changed before capture")
    return _HeldDocument(
        path_entries=path_entries,
        parent_descriptor=parent_descriptor,
        leaf_name=leaf_name,
        descriptor=descriptor,
        identity=_document_identity(opened),
        stable_metadata=_stable_document_metadata(opened),
    )


def _hold_document_parent(
    descriptors: ExitStack,
    path: Path,
    *,
    no_follow: int,
) -> tuple[tuple[_HeldPathEntry, ...], int]:
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if type(directory_flag) is not int:
        raise OSError("safe directory descriptor reads are unavailable")
    flags = os.O_RDONLY | directory_flag | no_follow | getattr(os, "O_CLOEXEC", 0)
    if path.is_absolute():
        anchor = path.anchor
        parent_parts = path.parent.parts[1:]
    else:
        anchor = "."
        parent_parts = path.parent.parts

    entries: list[_HeldPathEntry] = []
    parent_descriptor: int | None = None
    for name in (anchor, *parent_parts):
        before = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if not stat.S_ISDIR(before.st_mode):
            raise ValueError("document path parent is not a directory")
        descriptor = os.open(
            name,
            flags,
            dir_fd=parent_descriptor,
        )
        descriptors.callback(os.close, descriptor)
        os.set_inheritable(descriptor, False)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or _document_identity(before) != _document_identity(opened)
            or _stable_directory_metadata(before) != _stable_directory_metadata(opened)
        ):
            raise ValueError("document path parent changed before capture")
        entries.append(
            _HeldPathEntry(
                parent_descriptor=parent_descriptor,
                name=name,
                descriptor=descriptor,
                identity=_document_identity(opened),
                stable_metadata=_stable_directory_metadata(opened),
            )
        )
        parent_descriptor = descriptor
    assert parent_descriptor is not None
    return tuple(entries), parent_descriptor


def _read_bounded_document_descriptor(
    descriptor: int,
    *,
    maximum_bytes: int,
) -> bytes:
    if maximum_bytes < 0:
        raise ValueError("document capture bound is invalid")
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_size > maximum_bytes
    ):
        raise ValueError("document leaf is not an admissible regular file")
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    captured_bytes = 0
    while True:
        block = os.read(
            descriptor,
            min(
                _DOCUMENT_READ_CHUNK_BYTES,
                maximum_bytes + 1 - captured_bytes,
            ),
        )
        if not block:
            break
        captured_bytes += len(block)
        if captured_bytes > maximum_bytes:
            raise ValueError("document exceeds its capture bound")
        chunks.append(block)
    if _stable_document_metadata(before) != _stable_document_metadata(
        os.fstat(descriptor)
    ):
        raise ValueError("document changed during capture")
    return b"".join(chunks)


def _revalidate_held_document(held: _HeldDocument) -> None:
    for entry in held.path_entries:
        descriptor_metadata = os.fstat(entry.descriptor)
        path_metadata = os.stat(
            entry.name,
            dir_fd=entry.parent_descriptor,
            follow_symlinks=False,
        )
        if (
            _document_identity(descriptor_metadata) != entry.identity
            or _document_identity(path_metadata) != entry.identity
            or _stable_directory_metadata(descriptor_metadata) != entry.stable_metadata
            or _stable_directory_metadata(path_metadata) != entry.stable_metadata
        ):
            raise ValueError("document parent path changed during validation")
    descriptor_metadata = os.fstat(held.descriptor)
    path_metadata = os.stat(
        held.leaf_name,
        dir_fd=held.parent_descriptor,
        follow_symlinks=False,
    )
    if (
        _document_identity(descriptor_metadata) != held.identity
        or _document_identity(path_metadata) != held.identity
        or _stable_document_metadata(descriptor_metadata) != held.stable_metadata
        or _stable_document_metadata(path_metadata) != held.stable_metadata
    ):
        raise ValueError("document path or bytes changed during validation")


def load_catalog_lock(
    catalog_path: Path,
    lock_path: Path,
) -> CatalogLockValidation:
    """Strictly load and validate one catalog/lock pair without planning."""

    return _load_catalog_lock_with_schemas(
        catalog_path,
        lock_path,
        schemas=_installed_schema_documents(),
    )


def _load_catalog_lock_for_tests(
    catalog_path: Path,
    lock_path: Path,
    *,
    schema_directory: Path,
) -> CatalogLockValidation:
    """Private fixture seam for exercising invalid installed Schema sets."""

    return _load_catalog_lock_with_schemas(
        catalog_path,
        lock_path,
        schemas=_trusted_schema_documents(schema_directory),
    )


def _load_catalog_lock_with_schemas(
    catalog_path: Path,
    lock_path: Path,
    *,
    schemas: dict[str, dict[str, Any]] | None,
) -> CatalogLockValidation:
    if schemas is None:
        return _schema_manifest_failure()
    try:
        with ExitStack() as descriptors:
            try:
                catalog_document = _hold_bounded_document(
                    descriptors,
                    Path(catalog_path),
                    maximum_bytes=MAX_CATALOG_BYTES,
                )
                lock_document = _hold_bounded_document(
                    descriptors,
                    Path(lock_path),
                    maximum_bytes=MAX_LOCK_BYTES,
                )
                if catalog_document.identity[:2] == lock_document.identity[:2]:
                    raise ValueError("catalog and lock must be distinct files")
                catalog_bytes = _read_bounded_document_descriptor(
                    catalog_document.descriptor,
                    maximum_bytes=MAX_CATALOG_BYTES,
                )
                lock_bytes = _read_bounded_document_descriptor(
                    lock_document.descriptor,
                    maximum_bytes=MAX_LOCK_BYTES,
                )
            except (OSError, TypeError, UnicodeError, ValueError):
                return _document_capture_failure()
            try:
                catalog = thaw_json(strict_load_json_bytes(catalog_bytes))
                lock = thaw_json(strict_load_json_bytes(lock_bytes))
                result = _validate_catalog_lock_with_schemas(catalog, lock, schemas)
            except (TypeError, UnicodeError, ValueError, RecursionError):
                return _document_parse_failure()
            try:
                _revalidate_held_document(catalog_document)
                _revalidate_held_document(lock_document)
            except (OSError, TypeError, UnicodeError, ValueError):
                return _document_capture_failure()
            return result
    except (OSError, TypeError, UnicodeError, ValueError):
        return _document_capture_failure()


def validate_catalog_lock(
    catalog: object,
    lock: object,
) -> CatalogLockValidation:
    """Validate detached in-memory documents and return only immutable state."""

    return _validate_catalog_lock_with_installed_schemas(
        catalog,
        lock,
        schemas=_installed_schema_documents(),
    )


def _validate_adapter_contract_document(
    document: object,
    *,
    record_type: str,
) -> bool:
    """Admit one adapter envelope through the installed digest-pinned Schemas."""

    if record_type not in {
        "CapabilityDiscovery",
        "ObserveRequest",
        "RuntimeObservation",
    }:
        return False
    if type(document) is not dict or document.get("record_type") != record_type:
        return False
    return validate_captured_schema_document(
        document,
        root_schema_name="adapter-contract-v1.schema.json",
    )


def validate_captured_schema_document(
    document: object,
    *,
    root_schema_name: str,
) -> bool:
    """Validate through the one import-time captured, digest-pinned Schema set."""

    allowed_by_root = {
        "adapter-contract-v1.schema.json": {
            "adapter-contract-v1.schema.json",
            "catalog-v1.schema.json",
        },
        "plan-action-set-v1.schema.json": {
            "plan-action-set-v1.schema.json",
        },
    }
    allowed = allowed_by_root.get(root_schema_name)
    schemas = _CAPTURED_SCHEMA_DOCUMENTS
    if allowed is None or schemas is None:
        return False
    return _validate_schema(
        document,
        schema_directory=SCHEMA_DIRECTORY,
        root_schema_name=root_schema_name,
        allowed_schema_names=allowed,
        schema_documents=schemas,
    )


def _validate_catalog_lock_for_tests(
    catalog: object,
    lock: object,
    *,
    schema_directory: Path,
) -> CatalogLockValidation:
    """Private fixture seam for exercising invalid installed Schema sets."""

    return _validate_catalog_lock_with_installed_schemas(
        catalog,
        lock,
        schemas=_trusted_schema_documents(schema_directory),
    )


def _validate_catalog_lock_with_installed_schemas(
    catalog: object,
    lock: object,
    *,
    schemas: dict[str, dict[str, Any]] | None,
) -> CatalogLockValidation:
    if schemas is None:
        return _schema_manifest_failure()
    try:
        detached_catalog = thaw_json(freeze_json(catalog))
        detached_lock = thaw_json(freeze_json(lock))
    except (TypeError, UnicodeError, ValueError, RecursionError):
        return _document_parse_failure()
    return _validate_catalog_lock_with_schemas(
        detached_catalog,
        detached_lock,
        schemas,
    )


def _validate_catalog_lock_with_schemas(
    catalog: object,
    lock: object,
    schemas: dict[str, dict[str, Any]],
) -> CatalogLockValidation:
    if not isinstance(catalog, Mapping) or not isinstance(lock, Mapping):
        return _document_parse_failure()
    result = _validate_design(
        catalog,
        lock,
        _schema_documents=schemas,
        _include_mutation_plan=False,
    )
    if result.diagnostics:
        return CatalogLockValidation(None, result.diagnostics)
    catalog_document = freeze_json(catalog)
    lock_document = freeze_json(lock)
    if not isinstance(catalog_document, Mapping) or not isinstance(
        lock_document, Mapping
    ):
        return _document_parse_failure()
    coverage_records: list[CoverageRecord] = []
    for entry in result.coverage:
        frozen_record = freeze_json(entry.record)
        if not isinstance(frozen_record, FrozenJsonObject):
            return _document_parse_failure()
        coverage_records.append(
            CoverageRecord(
                entry.equipment_identity,
                entry.harness,
                frozen_record,
            )
        )
    coverage = tuple(coverage_records)
    return CatalogLockValidation(
        ValidatedCatalogLock(
            Catalog(
                str(catalog["schema_version"]),
                catalog_document,
                _canonical_json_sha256(catalog),
            ),
            ResolvedLock(
                str(lock["schema_version"]),
                lock_document,
                _canonical_json_sha256(lock),
            ),
            coverage,
        ),
        (),
    )


def _trusted_schema_documents(
    schema_directory: Path,
) -> dict[str, dict[str, Any]] | None:
    try:
        directory = Path(schema_directory)
        schema_bytes: dict[str, bytes] = {}
        for name in EXPECTED_SCHEMA_SHA256:
            with (directory / name).open("rb") as schema_file:
                schema_bytes[name] = schema_file.read(MAX_SCHEMA_BYTES + 1)
    except OSError:
        return None
    return _trusted_schema_documents_from_bytes(schema_bytes)


def _trusted_schema_documents_from_bytes(
    schema_bytes: Mapping[str, bytes],
) -> dict[str, dict[str, Any]] | None:
    if set(schema_bytes) != set(EXPECTED_SCHEMA_SHA256):
        return None
    schemas: dict[str, dict[str, Any]] = {}
    try:
        for name in sorted(EXPECTED_SCHEMA_SHA256):
            payload = schema_bytes[name]
            if type(payload) is not bytes or len(payload) > MAX_SCHEMA_BYTES:
                return None
            if hashlib.sha256(payload).hexdigest() != EXPECTED_SCHEMA_SHA256[name]:
                return None
            parsed = thaw_json(strict_load_json_bytes(payload))
            if type(parsed) is not dict:
                return None
            schemas[name] = parsed
    except (KeyError, TypeError, UnicodeError, ValueError, RecursionError):
        return None
    if not _validate_schema_documents(
        schemas,
        allowed_schema_names=EXPECTED_SCHEMA_SHA256,
    ):
        return None
    return schemas


def _installed_schema_documents() -> dict[str, dict[str, Any]] | None:
    if _CAPTURED_SCHEMA_BYTES is not None:
        return _trusted_schema_documents_from_bytes(_CAPTURED_SCHEMA_BYTES)
    return _trusted_schema_documents(SCHEMA_DIRECTORY)


_CAPTURED_SCHEMA_DOCUMENTS = _installed_schema_documents()


def _schema_manifest_failure() -> CatalogLockValidation:
    return CatalogLockValidation(
        None,
        (
            Diagnostic(
                "SCHEMA_MANIFEST_INVALID",
                "The installed schema manifest is missing, changed, or invalid.",
            ),
        ),
    )


def _document_parse_failure() -> CatalogLockValidation:
    return CatalogLockValidation(
        None,
        (
            Diagnostic(
                "DOCUMENT_PARSE_INVALID",
                "Catalog and lock inputs must be strict finite UTF-8 JSON documents.",
            ),
        ),
    )


def _document_capture_failure() -> CatalogLockValidation:
    return CatalogLockValidation(
        None,
        (
            Diagnostic(
                "DOCUMENT_CAPTURE_INVALID",
                "Catalog and lock inputs must be stable, size-bounded, unique "
                "regular files reached without symbolic links.",
            ),
        ),
    )


def _load_and_validate(catalog_path: Path, lock_path: Path) -> _DesignValidationResult:
    """Load a catalog and lock as UTF-8 JSON, then validate them together."""

    try:
        catalog = _load_json_without_duplicate_members(Path(catalog_path))
        lock = _load_json_without_duplicate_members(Path(lock_path))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        return _DesignValidationResult(
            diagnostics=(
                Diagnostic(
                    "DOCUMENT_PARSE_INVALID",
                    "Catalog and lock inputs must be valid JSON with unique object member names.",
                ),
            ),
            coverage=(),
            mutation_plan=None,
        )
    return _validate_design(catalog, lock)


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


def _validate_design(
    catalog: JsonObject,
    lock: JsonObject,
    *,
    _schema_documents: Mapping[str, Any] | None = None,
    _include_mutation_plan: bool = True,
) -> _DesignValidationResult:
    """Validate and deterministically expand one catalog/lock design pair."""

    diagnostics = list(
        _document_schema_diagnostics(
            catalog,
            lock,
            schema_documents=_schema_documents,
        )
    )
    if diagnostics:
        return _DesignValidationResult(
            diagnostics=tuple(diagnostics),
            coverage=(),
            mutation_plan=None,
        )
    diagnostics.extend(_literal_secret_diagnostics(catalog, lock))
    if diagnostics:
        return _DesignValidationResult(
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
            for field in (
                "distributions",
                "coverage_templates",
                "equipment",
                "retirements",
            )
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
        identities: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            identity = item.get("identity")
            if isinstance(identity, str):
                identities.append(identity)
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
    coverage: list[_CoverageEntry] = []
    active_authored_record_ids: set[int] = set()
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
        if not isinstance(equipment, dict) or not isinstance(
            equipment.get("identity"), str
        ):
            diagnostics.append(
                Diagnostic(
                    "CATALOG_SHAPE_INVALID",
                    "Equipment entries must be objects with identities.",
                )
            )
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
    lock_distributions = lock.get("distributions") if isinstance(lock, dict) else None
    if isinstance(lock_distributions, list):
        for item in lock_distributions:
            if (
                isinstance(item, dict)
                and isinstance(item.get("distribution_identity"), str)
                and isinstance(item.get("equipment"), list)
                and all(isinstance(identity, str) for identity in item["equipment"])
            ):
                resolved_membership[item["distribution_identity"]] = tuple(
                    item["equipment"]
                )
    selected_identities = sorted(
        {
            identity
            for identities in resolved_membership.values()
            for identity in identities
        }
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
            if equipment_identity in identities
            and distribution_identity in distributions
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
                    template = (
                        templates.get(template_identity)
                        if isinstance(template_identity, str)
                        else None
                    )
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
            active_authored_record_ids.add(id(record))
            if not _coverage_record_is_structurally_valid(
                record,
                diagnostics,
                equipment_identity,
                harness,
            ):
                continue
            coverage.append(_CoverageEntry(equipment_identity, harness, record))

    for equipment_identity, harness, record in _authored_catalog_records(catalog):
        if id(record) in active_authored_record_ids or harness is None:
            continue
        _coverage_record_is_structurally_valid(
            record,
            diagnostics,
            equipment_identity,
            harness,
        )

    retirement_operations = _validate_retirements(
        catalog,
        lock,
        coverage,
        diagnostics,
    )
    _validate_lock(catalog, lock, coverage, diagnostics)
    grouped_operations: dict[tuple[str, str, str, str], set[str]] = {}
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
    for (
        retirement_equipment_identities,
        retirement_controlled_identities,
        retirement_harness,
        retirement_route_identity,
        retirement_activation_group,
        retirement_operation,
    ) in retirement_operations:
        activation_key = (
            retirement_harness,
            retirement_activation_group,
        )
        previous_group_route = activation_groups.get(activation_key)
        if (
            previous_group_route is not None
            and previous_group_route != retirement_route_identity
        ):
            diagnostics.append(
                Diagnostic(
                    "ACTIVATION_GROUP_CONFLICT",
                    "One activation group maps to exactly one route identity within a harness.",
                    equipment_identity=retirement_equipment_identities[0],
                    harness=retirement_harness,
                    route_identity=retirement_route_identity,
                )
            )
        else:
            activation_groups[activation_key] = retirement_route_identity
        key = (
            retirement_harness,
            retirement_route_identity,
            retirement_activation_group,
            retirement_operation,
        )
        grouped_operations.setdefault(key, set()).update(
            retirement_equipment_identities
        )
        grouped_controls.setdefault(key, set()).update(retirement_controlled_identities)

    ordered_diagnostics = tuple(
        sorted(
            diagnostics,
            key=_diagnostic_sort_key,
        )
    )
    return _DesignValidationResult(
        diagnostics=ordered_diagnostics,
        coverage=tuple(sorted(coverage)),
        mutation_plan=(
            _construct_mutation_plan(grouped_operations, grouped_controls)
            if _include_mutation_plan and not ordered_diagnostics
            else None
        ),
    )


def _construct_mutation_plan(
    grouped_operations: Mapping[tuple[str, str, str, str], set[str]],
    grouped_controls: Mapping[tuple[str, str, str, str], set[str]],
) -> tuple[_PlannedOperation, ...]:
    planned = (
        _PlannedOperation(
            equipment_identities=tuple(sorted(equipment_identities)),
            controlled_equipment_identities=tuple(
                sorted(
                    grouped_controls.get(
                        (harness, route_identity, activation_group, operation), ()
                    )
                )
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
    )
    return tuple(
        sorted(
            planned,
            key=_planned_operation_sort_key,
        )
    )


def _coverage_record_is_structurally_valid(
    record: Any,
    diagnostics: list[Diagnostic],
    equipment_identity: str | None,
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
    route_ids: list[str] = []
    for route in routes:
        if not isinstance(route, dict) or not isinstance(route.get("identity"), str):
            diagnostics.append(
                Diagnostic(
                    "COVERAGE_RECORD_INVALID",
                    "Every active route must be a complete object with an identity.",
                    equipment_identity=equipment_identity,
                    harness=harness,
                )
            )
            return False
        route_ids.append(route["identity"])
    duplicate_ids = {
        identity for identity in route_ids if route_ids.count(identity) > 1
    }
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
    if len(active_route_ids) != len(set(active_route_ids)) or set(
        active_route_ids
    ) != set(route_ids):
        diagnostics.append(
            Diagnostic(
                "COVERAGE_RECORD_INVALID",
                "Preferred and supplementary route identities name the complete active route set exactly once.",
                equipment_identity=equipment_identity,
                harness=harness,
            )
        )
        valid = False

    exceptions: list[Any] = selection["allow_overlap"]
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
    *,
    schema_documents: Mapping[str, Any] | None = None,
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
            schema_documents=schema_documents,
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
    equipment_identity: str | None,
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
                route_identity=(
                    route_identity if isinstance(route_identity, str) else None
                ),
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
    if not isinstance(secret_references, list) or any(
        not _secret_reference_is_valid(item) for item in secret_references
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
    declared_secret_references = (
        {
            (reference["kind"], reference["name"])
            for reference in secret_references
            if _secret_reference_is_valid(reference)
        }
        if isinstance(secret_references, list)
        else set()
    )
    if not _provider_is_valid(
        route.get("provider"), harness, declared_secret_references
    ):
        diagnostics.append(
            Diagnostic(
                "PROVIDER_CONFIGURATION_INVALID",
                "Provider configuration is typed, portable, harness-compatible, and references only declared secrets.",
                equipment_identity=equipment_identity,
                harness=harness,
                route_identity=(
                    route_identity if isinstance(route_identity, str) else None
                ),
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
        if (
            operation in MUTATING_OPERATIONS
            and operation_record["disposition"] == "automated"
        ):
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
            and _source_string_is_bounded(restore["artifact_ref"])
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
            _source_string_is_bounded(restore["channel"])
            and bool(restore["channel"].strip())
            and _source_string_is_bounded(restore["reviewed_baseline"])
            and bool(restore["reviewed_baseline"].strip())
            and isinstance(restore["observation_source"], str)
            and bool(
                _OBSERVATION_SOURCE_PATTERN.fullmatch(restore["observation_source"])
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
        if isinstance(distribution, str) and distribution.startswith("distribution:")
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
    if not _source_string_is_bounded(identity) or not re.fullmatch(
        r"distribution:[a-z0-9][a-z0-9._/-]*", identity
    ):
        return False
    source = distribution.get("source")
    source_valid = _catalog_source_is_valid(source)
    selection = distribution.get("selection")
    selection_valid = isinstance(selection, dict) and (
        (set(selection) == {"all"} and selection.get("all") is True)
        or (
            set(selection) == {"equipment"}
            and isinstance(selection.get("equipment"), list)
            and bool(selection["equipment"])
            and len(selection["equipment"]) == len(set(selection["equipment"]))
            and all(
                _source_string_is_bounded(item)
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


def _catalog_source_is_valid(source: Any) -> bool:
    if not isinstance(source, dict):
        return False
    if source.get("kind") == "git":
        if set(source) not in (
            {"kind", "repository"},
            {"branch", "kind", "repository"},
        ):
            return False
        repository = source.get("repository")
        return (
            _source_string_is_bounded(repository)
            and _public_git_repository_is_valid(repository)
            and (
                "branch" not in source
                or isinstance(source.get("branch"), str)
                and _git_branch_is_valid(source["branch"])
            )
        )
    if source.get("kind") != "native_manager" or set(source) not in (
        {"kind", "manager", "package"},
        {"channel", "kind", "manager", "package"},
    ):
        return False
    manager = source.get("manager")
    package = source.get("package")
    if manager == "http":
        return (
            set(source) == {"channel", "kind", "manager", "package"}
            and isinstance(package, str)
            and len(package) <= MAX_SOURCE_PACKAGE_CHARACTERS
            and _static_credential_free_https_url_is_valid(package)
            and source.get("channel") == "static"
        )
    if (
        manager not in {"claude", "codex", "cursor", "npx"}
        or not isinstance(package, str)
        or len(package) > MAX_SOURCE_PACKAGE_CHARACTERS
        or not (
            _NPX_PACKAGE_PATTERN.fullmatch(package)
            if manager == "npx"
            else _NATIVE_MANAGER_PACKAGE_PATTERN.fullmatch(package)
        )
    ):
        return False
    return "channel" not in source or (
        isinstance(source.get("channel"), str)
        and bool(_NATIVE_CHANNEL_PATTERN.fullmatch(source["channel"]))
        and source["channel"] != "latest"
    )


def _git_branch_is_valid(value: str) -> bool:
    return len(value) <= MAX_SOURCE_FIELD_CHARACTERS and bool(
        re.fullmatch(
            r"(?!HEAD$)(?!-)(?!\.)(?!.*(?:/\.|//|\.\.|@\{|\\))(?!.*\.lock(?:/|$))(?!.*[./]$)[A-Za-z0-9._/-]+",
            value,
        )
    )


def _public_git_repository_is_valid(value: str) -> bool:
    if len(value) > MAX_SOURCE_FIELD_CHARACTERS:
        return False
    if not _static_credential_free_https_url_is_valid(value):
        return False
    parsed = urlsplit(value)
    return parsed.path not in {"", "/"} and parsed.path.endswith(".git")


def _git_commit_oid_is_valid(value: str) -> bool:
    return bool(re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value))


def _resolved_source_matches_policy(source: Any, resolved: Any) -> bool:
    if not _catalog_source_is_valid(source) or not isinstance(resolved, dict):
        return False
    if source.get("kind") == "git":
        return (
            set(resolved) == {"kind", "revision"}
            and resolved.get("kind") == "git"
            and isinstance(resolved.get("revision"), str)
            and _git_commit_oid_is_valid(resolved["revision"])
        )
    return (
        set(resolved) == {"kind", "version"}
        and resolved.get("kind") == "native_manager"
        and _resolved_version_is_valid_for_manager(
            source.get("manager"), resolved.get("version")
        )
    )


def _resolved_version_is_valid_for_manager(manager: Any, version: Any) -> bool:
    if not isinstance(version, dict):
        return False
    if manager in {"claude", "cursor", "npx"}:
        value = version.get("value")
        return (
            set(version) == {"kind", "value"}
            and version.get("kind") == "semantic_version"
            and isinstance(value, str)
            and len(value) <= 255
            and bool(_SEMANTIC_VERSION_PATTERN.fullmatch(value))
        )
    if manager == "codex":
        value = version.get("value")
        return (
            set(version) == {"kind", "value"}
            and version.get("kind") == "revision"
            and isinstance(value, str)
            and bool(re.fullmatch(r"[0-9a-f]{8}", value))
            and any(character.isdigit() for character in value)
        )
    return manager == "http" and version == {"kind": "static_source"}


def _resolved_version_value(version: Any) -> str | None:
    if not isinstance(version, dict):
        return None
    value = version.get("value")
    return value if isinstance(value, str) else None


def _source_manifest_digest_is_valid(manifest: Any) -> bool:
    if not isinstance(manifest, dict):
        return False
    digest = manifest.get("source_manifest_digest")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        return False
    payload = dict(manifest)
    payload.pop("source_manifest_digest", None)
    return digest == canonical_json_sha256(payload)


def _source_manifest_is_valid(manifest: Any) -> bool:
    if not isinstance(manifest, dict):
        return False
    try:
        if len(_canonical_json_bytes(manifest)) > MAX_SOURCE_RESOLUTION_BYTES:
            return False
    except (TypeError, UnicodeError, ValueError, RecursionError):
        return False
    if set(manifest) != {
        "available_equipment",
        "distribution_identity",
        "equipment",
        "membership_evidence",
        "resolved_source",
        "restore",
        "schema_version",
        "source",
        "source_manifest_digest",
    }:
        return False
    identity = manifest.get("distribution_identity")
    if (
        manifest.get("schema_version") != "source-manifest/v1"
        or not _source_string_is_bounded(identity)
        or not re.fullmatch(r"distribution:[a-z0-9][a-z0-9._/-]*", identity)
        or not _resolved_source_matches_policy(
            manifest.get("source"), manifest.get("resolved_source")
        )
        or not _restore_is_valid(manifest.get("restore"))
        or not _resolved_source_matches_restore(
            manifest.get("source"),
            manifest.get("resolved_source"),
            manifest.get("restore"),
        )
        or not _source_manifest_digest_is_valid(manifest)
    ):
        return False
    available = manifest.get("available_equipment")
    selected = manifest.get("equipment")
    if (
        not isinstance(available, list)
        or not isinstance(selected, list)
        or not _source_manifest_equipment_is_valid(available)
        or not _source_manifest_equipment_is_valid(selected)
        or not set(selected).issubset(available)
    ):
        return False
    evidence = manifest.get("membership_evidence")
    return (
        isinstance(evidence, dict)
        and set(evidence) == {"evidence_digest", "kind"}
        and evidence.get("kind") == "authoritative_source_listing"
        and evidence.get("evidence_digest")
        == canonical_json_sha256({"available_equipment": available})
    )


def _source_manifest_equipment_is_valid(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and len(value) <= MAX_AVAILABLE_EQUIPMENT
        and value == sorted(set(value))
        and all(
            _source_string_is_bounded(identity)
            and bool(
                re.fullmatch(
                    r"(skill|plugin|mcp|hook|other):[a-z0-9][a-z0-9._/-]*",
                    identity,
                )
            )
            for identity in value
        )
    )


def _resolved_source_matches_restore(
    source: Any,
    resolved: Any,
    restore: Any,
) -> bool:
    if (
        not _catalog_source_is_valid(source)
        or not isinstance(resolved, dict)
        or not isinstance(restore, dict)
    ):
        return False
    if resolved.get("kind") == "git":
        if source.get("kind") != "git" or restore.get("class") != "immutable":
            return False
        repository = source.get("repository")
        revision = resolved.get("revision")
        expected = f"git+{repository}@{revision}"
        artifact_ref = restore.get("artifact_ref")
        return (
            restore.get("revision") == revision
            and isinstance(artifact_ref, str)
            and (artifact_ref == expected or artifact_ref.startswith(f"{expected}#"))
        )
    if (
        resolved.get("kind") != "native_manager"
        or restore.get("class") != "native_rolling"
    ):
        return False
    manager = source.get("manager")
    package = source.get("package")
    channel = source.get("channel", "latest")
    version = resolved.get("version")
    if not _resolved_version_is_valid_for_manager(manager, version):
        return False
    version_value = _resolved_version_value(version)
    if manager == "npx":
        return (
            version_value is not None
            and restore.get("channel") == f"npm:{version_value}"
            and restore.get("reviewed_baseline") == f"{package}@{version_value}"
        )
    if manager == "http":
        return (
            channel == "static"
            and restore.get("channel") == "static"
            and restore.get("reviewed_baseline") == package
        )
    return (
        version_value is not None
        and restore.get("channel") == channel
        and restore.get("reviewed_baseline") == version_value
    )


def _artifact_subpath_is_valid(value: str) -> bool:
    if not value or "%" in value or "\\" in value:
        return False
    return all(
        segment not in {"", ".", ".."}
        and bool(re.fullmatch(r"[A-Za-z0-9._~-]+", segment))
        for segment in value.split("/")
    )


def _immutable_artifact_ref_is_valid(value: str) -> bool:
    if len(value) > MAX_SOURCE_FIELD_CHARACTERS or not value.startswith("git+"):
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
            and set(provider) == {"kind", "manager", "plugin_id", "scope"}
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
            )
            in declared_secret_references
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
            )
            in declared_secret_references
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
            or (
                bool(consumed_secret_references)
                and consumed_secret_references[0][0] == "secret_profile"
            )
        )
    )


def _hostname_has_valid_dns_labels(value: str) -> bool:
    return len(value) <= 253 and all(
        bool(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label))
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
    coverage: list[_CoverageEntry],
    diagnostics: list[Diagnostic],
) -> list[_GroupedOperation]:
    retirements = catalog.get("retirements")
    if not isinstance(retirements, list):
        diagnostics.append(
            Diagnostic(
                "RETIREMENT_SHAPE_INVALID",
                "Catalog retirements are an explicit list of owned losing surfaces.",
            )
        )
        return []

    active_route_ids = {
        route.get("identity")
        for entry in coverage
        if isinstance(entry.record.get("provider_selection"), dict)
        for route in entry.record["provider_selection"].get("routes", [])
        if isinstance(route, dict)
    }
    seen_retirement_ids: set[str] = set()
    seen_surfaces: set[tuple[str, ...]] = set()
    grouped: list[_GroupedOperation] = []
    manifests_by_digest = {
        manifest.get("source_manifest_digest"): manifest
        for field in ("distributions", "source_manifest_history")
        for manifest in (
            lock.get(field, []) if isinstance(lock.get(field), list) else []
        )
        if isinstance(manifest, dict)
        and isinstance(manifest.get("source_manifest_digest"), str)
    }

    for retirement in retirements:
        if not isinstance(retirement, dict) or set(retirement) != {
            "identity",
            "equipment_identity",
            "harness",
            "route",
            "surface",
            "desired_state",
            "source_manifest_digest",
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
            or not re.fullmatch(
                r"retirement:[a-z0-9][a-z0-9._/-]*", retirement_identity
            )
            or retirement_identity in seen_retirement_ids
        ):
            diagnostics.append(
                Diagnostic(
                    "RETIREMENT_IDENTITY_INVALID",
                    "Retirement identities are unique, portable, and namespaced.",
                    equipment_identity=(
                        equipment_identity
                        if isinstance(equipment_identity, str)
                        else None
                    ),
                    harness=(harness if isinstance(harness, str) else None),
                    route_identity=(
                        route_identity if isinstance(route_identity, str) else None
                    ),
                )
            )
        elif isinstance(retirement_identity, str):
            seen_retirement_ids.add(retirement_identity)

        if (
            not isinstance(equipment_identity, str)
            or not re.fullmatch(
                r"(skill|plugin|mcp|hook|other):[a-z0-9][a-z0-9._/-]*",
                equipment_identity,
            )
            or harness not in {"claude", "codex", "cursor"}
            or not isinstance(route, dict)
        ):
            diagnostics.append(
                Diagnostic(
                    "RETIREMENT_REFERENCE_INVALID",
                    "A retirement names selected equipment, one active harness, and one complete losing route.",
                    equipment_identity=(
                        equipment_identity
                        if isinstance(equipment_identity, str)
                        else None
                    ),
                    harness=(harness if isinstance(harness, str) else None),
                    route_identity=(
                        route_identity if isinstance(route_identity, str) else None
                    ),
                )
            )
            continue

        route_valid = _route_is_valid(route, diagnostics, equipment_identity, harness)
        distribution_identity = route.get("distribution")
        source_manifest_digest = retirement.get("source_manifest_digest")
        source_manifest = (
            manifests_by_digest.get(source_manifest_digest)
            if isinstance(source_manifest_digest, str)
            else None
        )
        manifest_membership = (
            source_manifest.get("equipment")
            if isinstance(source_manifest, dict)
            else None
        )
        if (
            not isinstance(distribution_identity, str)
            or not isinstance(source_manifest, dict)
            or source_manifest.get("distribution_identity") != distribution_identity
            or not isinstance(manifest_membership, list)
            or equipment_identity not in manifest_membership
        ):
            diagnostics.append(
                Diagnostic(
                    "RETIREMENT_SOURCE_MANIFEST_INVALID",
                    "A retirement binds an exact current or historical Source Manifest that supplied its losing route and equipment.",
                    equipment_identity=equipment_identity,
                    harness=harness,
                    route_identity=route_identity,
                )
            )
            route_valid = False
        if not _source_manifest_matches_provider(
            source_manifest, route.get("provider")
        ):
            diagnostics.append(
                Diagnostic(
                    "RETIREMENT_DISTRIBUTION_SOURCE_PROVIDER_MISMATCH",
                    "The losing provider invokes the exact package, version, manager, or immutable source bound by its Source Manifest.",
                    equipment_identity=equipment_identity,
                    harness=harness,
                    route_identity=route_identity,
                )
            )
            route_valid = False
        if not isinstance(source_manifest, dict) or route.get(
            "restore"
        ) != source_manifest.get("restore"):
            diagnostics.append(
                Diagnostic(
                    "RETIREMENT_DISTRIBUTION_RESTORE_MISMATCH",
                    "The losing route restore evidence is the exact restore retained by its Source Manifest.",
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
            retirement.get("surface"),
            route.get("provider"),
            equipment_identity,
            harness,
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

        operation = (
            "remove" if retirement.get("desired_state") == "absent" else "disable"
        )
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
        activation_group = route.get("activation_group")
        if (
            route_valid
            and isinstance(route_identity, str)
            and isinstance(activation_group, str)
        ):
            grouped.append(
                (
                    (equipment_identity,),
                    (),
                    harness,
                    route_identity,
                    activation_group,
                    operation,
                )
            )
    return grouped


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
        return provider.get("kind") == "direct_mcp" and surface.get(
            "server_name"
        ) == provider.get("server_name")
    if kind == "plugin":
        return provider.get("kind") == "native_plugin" and surface.get(
            "plugin_id"
        ) == provider.get("plugin_id")
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
            and isinstance(component_identity, str)
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
    complete_route_set: set[str],
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
    coverage: list[_CoverageEntry],
    diagnostics: list[Diagnostic],
) -> None:
    if not isinstance(lock, dict) or set(lock) != {
        "schema_version",
        "catalog_digest",
        "distributions",
        "source_manifest_history",
        "coverage",
        "retirements",
    }:
        diagnostics.append(
            Diagnostic(
                "LOCK_SHAPE_INVALID", "The resolved lock has the exact lock/v1 shape."
            )
        )
        return
    if lock.get("schema_version") != "lock/v1":
        diagnostics.append(
            Diagnostic(
                "LOCK_SHAPE_INVALID", "The resolved lock schema version is lock/v1."
            )
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
            Diagnostic(
                "LOCK_SHAPE_INVALID", "Lock coverage is a list of expanded records."
            )
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
                Diagnostic(
                    "LOCK_SHAPE_INVALID",
                    "Every lock coverage entry has one exact shape.",
                )
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
    if not isinstance(lock_retirements, list) or not isinstance(
        catalog_retirements, list
    ):
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
    source_manifest_history = lock.get("source_manifest_history")
    if not isinstance(lock_distributions, list) or not isinstance(
        source_manifest_history, list
    ):
        diagnostics.append(
            Diagnostic(
                "LOCK_SHAPE_INVALID",
                "Lock current and historical source manifests are lists.",
            )
        )
        return
    current_by_identity: dict[str, JsonObject] = {}
    manifests_by_digest: dict[str, JsonObject] = {}
    current_digests: set[str] = set()
    history_digests: set[str] = set()
    for role, manifests in (
        ("current", lock_distributions),
        ("history", source_manifest_history),
    ):
        for item in manifests:
            if isinstance(item, dict) and not _resolved_source_matches_restore(
                item.get("source"),
                item.get("resolved_source"),
                item.get("restore"),
            ):
                diagnostics.append(
                    Diagnostic(
                        "DISTRIBUTION_SOURCE_RESTORE_MISMATCH",
                        "Source Manifest restore evidence is an exact consequence of its resolved source.",
                    )
                )
            if not _source_manifest_is_valid(item):
                diagnostics.append(
                    Diagnostic(
                        (
                            "LOCK_DISTRIBUTION_INVALID"
                            if role == "current"
                            else "SOURCE_MANIFEST_HISTORY_INVALID"
                        ),
                        (
                            "Each current lock distribution is one complete canonical Source Manifest."
                            if role == "current"
                            else "Each historical lock entry is one complete canonical Source Manifest."
                        ),
                    )
                )
                continue
            assert isinstance(item, dict)
            identity = item["distribution_identity"]
            digest = item["source_manifest_digest"]
            assert isinstance(identity, str)
            assert isinstance(digest, str)
            if digest in manifests_by_digest:
                diagnostics.append(
                    Diagnostic(
                        "SOURCE_MANIFEST_HISTORY_INVALID",
                        "Current and historical Source Manifest digests are globally unique.",
                    )
                )
                continue
            manifests_by_digest[digest] = item
            if role == "current":
                if identity in current_by_identity:
                    diagnostics.append(
                        Diagnostic(
                            "LOCK_DISTRIBUTION_INVALID",
                            "The lock resolves each current catalog distribution exactly once.",
                        )
                    )
                    continue
                current_by_identity[identity] = item
                current_digests.add(digest)
            else:
                history_digests.add(digest)

    catalog_distributions = {
        item.get("identity"): item
        for item in (
            catalog.get("distributions", [])
            if isinstance(catalog.get("distributions"), list)
            else []
        )
        if isinstance(item, dict) and isinstance(item.get("identity"), str)
    }
    if set(current_by_identity) != set(catalog_distributions):
        diagnostics.append(
            Diagnostic(
                "LOCK_DISTRIBUTION_INVALID",
                "The lock resolves every current catalog distribution exactly once.",
            )
        )
    for identity, distribution in catalog_distributions.items():
        manifest = current_by_identity.get(identity)
        if manifest is None:
            continue
        selection = distribution.get("selection")
        membership = manifest.get("equipment")
        available = manifest.get("available_equipment")
        if manifest.get("source") != distribution.get("source"):
            diagnostics.append(
                Diagnostic(
                    "LOCK_DISTRIBUTION_SOURCE_MISMATCH",
                    "The current Source Manifest binds the exact authored source tracking policy.",
                )
            )
        selection_valid = isinstance(selection, dict) and (
            (
                set(selection) == {"all"}
                and selection.get("all") is True
                and membership == available
            )
            or (
                set(selection) == {"equipment"}
                and isinstance(selection.get("equipment"), list)
                and selection["equipment"]
                and len(selection["equipment"]) == len(set(selection["equipment"]))
                and selection["equipment"] == membership
            )
        )
        if not selection_valid:
            diagnostics.append(
                Diagnostic(
                    "DISTRIBUTION_SELECTION_INVALID",
                    "Current Source Manifest membership exactly satisfies complete all-or-explicit catalog selection.",
                )
            )

    for equipment_identity, harness, record in _authored_catalog_records(catalog):
        selection = record.get("provider_selection")
        if not isinstance(selection, dict):
            continue
        for route in selection.get("routes", []):
            if not isinstance(route, dict):
                continue
            distribution_identity = route.get("distribution")
            manifest = (
                current_by_identity.get(distribution_identity)
                if isinstance(distribution_identity, str)
                else None
            )
            if not _source_manifest_matches_provider(manifest, route.get("provider")):
                diagnostics.append(
                    Diagnostic(
                        "DISTRIBUTION_SOURCE_PROVIDER_MISMATCH",
                        "Every authored provider invokes the exact package, version, manager, or immutable source bound by its current Source Manifest.",
                        equipment_identity=equipment_identity,
                        harness=harness,
                        route_identity=route.get("identity"),
                    )
                )
            if manifest is None or manifest.get("restore") != route.get("restore"):
                diagnostics.append(
                    Diagnostic(
                        "LOCK_DISTRIBUTION_INVALID",
                        "Every authored route restore record matches its current Source Manifest.",
                        equipment_identity=equipment_identity,
                        harness=harness,
                        route_identity=route.get("identity"),
                    )
                )

    retirement_digests = {
        item.get("source_manifest_digest")
        for item in (
            catalog.get("retirements", [])
            if isinstance(catalog.get("retirements"), list)
            else []
        )
        if isinstance(item, dict)
        and isinstance(item.get("source_manifest_digest"), str)
    }
    if (
        retirement_digests - set(manifests_by_digest)
        or history_digests != retirement_digests - current_digests
    ):
        diagnostics.append(
            Diagnostic(
                "SOURCE_MANIFEST_HISTORY_INVALID",
                "History contains exactly the non-current Source Manifests still referenced by retirements.",
            )
        )

    for entry in coverage:
        selection = entry.record.get("provider_selection")
        if not isinstance(selection, dict):
            continue
        for route in selection.get("routes", []):
            manifest = current_by_identity.get(route.get("distribution"))
            manifest_equipment = (
                manifest.get("equipment") if manifest is not None else None
            )
            route_membership = (
                manifest_equipment if isinstance(manifest_equipment, list) else ()
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


def _authored_catalog_records(
    catalog: JsonObject,
) -> tuple[tuple[str | None, str | None, JsonObject], ...]:
    records: list[tuple[str | None, str | None, JsonObject]] = []
    templates = catalog.get("coverage_templates")
    if isinstance(templates, list):
        for template in templates:
            if not isinstance(template, dict):
                continue
            record = template.get("record")
            harness = template.get("harness")
            if isinstance(record, dict):
                records.append(
                    (
                        None,
                        harness if isinstance(harness, str) else None,
                        record,
                    )
                )
    equipment_entries = catalog.get("equipment")
    if isinstance(equipment_entries, list):
        for equipment in equipment_entries:
            if not isinstance(equipment, dict):
                continue
            equipment_identity = equipment.get("identity")
            coverage = equipment.get("coverage")
            if not isinstance(coverage, dict):
                continue
            for harness, entry in coverage.items():
                if not isinstance(entry, dict) or set(entry) != {"record"}:
                    continue
                record = entry.get("record")
                if isinstance(record, dict):
                    records.append(
                        (
                            (
                                equipment_identity
                                if isinstance(equipment_identity, str)
                                else None
                            ),
                            harness,
                            record,
                        )
                    )
    return tuple(records)


def _source_manifest_matches_provider(manifest: Any, provider: Any) -> bool:
    if not isinstance(manifest, dict) or not isinstance(provider, dict):
        return False
    resolved = manifest.get("resolved_source")
    source = manifest.get("source")
    if not isinstance(resolved, dict) or not isinstance(source, dict):
        return False
    if resolved.get("kind") == "git":
        return provider.get("kind") == "standalone_skill"
    if resolved.get("kind") != "native_manager":
        return False
    manager = source.get("manager")
    package = source.get("package")
    channel = source.get("channel", "latest")
    version = resolved.get("version")
    if provider.get("kind") == "native_plugin":
        return (
            provider.get("manager") == manager and provider.get("plugin_id") == package
        )
    if provider.get("kind") != "direct_mcp" or manager != "npx":
        return (
            provider.get("kind") == "direct_mcp"
            and provider.get("transport") == "http"
            and manager == "http"
            and provider.get("url") == package
            and channel == "static"
        )
    if not _resolved_version_is_valid_for_manager(manager, version):
        return False
    version_value = _resolved_version_value(version)
    if version_value is None:
        return False
    expected_selector = f"{package}@{version_value}"
    arguments = provider.get("arguments")
    if not isinstance(arguments, list):
        return False
    command = provider.get("command")
    invocation_arguments = arguments
    if command == "secret-exec":
        wrapper_boundaries = [
            index
            for index in range(len(arguments) - 1)
            if arguments[index] == {"literal": "--"}
            and arguments[index + 1] == {"literal": "npx"}
        ]
        if len(wrapper_boundaries) != 1:
            return False
        wrapper_boundary = wrapper_boundaries[0]
        invocation_arguments = arguments[wrapper_boundary + 2 :]
    elif command != "npx":
        return False
    matches = sum(
        isinstance(argument, dict)
        and set(argument) == {"literal"}
        and argument.get("literal") == expected_selector
        for argument in invocation_arguments
    )
    return matches == 1
