"""Immutable production data model for agent equipment."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias, override

JsonScalar: TypeAlias = None | bool | int | float | str
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_CATALOG_SCHEMA_VERSION = "catalog/v1"
_LOCK_SCHEMA_VERSION = "lock/v1"
_INSTALLED_IMPLEMENTATION_SCHEMA_VERSION = "agent-equipment-installed-implementation/v1"
_RUNTIME_IDENTITY_PATTERN = re.compile(
    r"cpython:(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
)
_INSTALLED_IMPLEMENTATION_PATHS = (
    "bin/agent-equipment",
    "lib/agent-equipment/agent_equipment/__init__.py",
    "lib/agent-equipment/agent_equipment/_json_schema.py",
    "lib/agent-equipment/agent_equipment/canonical.py",
    "lib/agent-equipment/agent_equipment/model.py",
    "lib/agent-equipment/agent_equipment/secrets.py",
    "lib/agent-equipment/agent_equipment/validator.py",
    "lib/agent-equipment/schemas/acceptance-evidence-v1.schema.json",
    "lib/agent-equipment/schemas/adapter-contract-v1.schema.json",
    "lib/agent-equipment/schemas/captured-state-v1.schema.json",
    "lib/agent-equipment/schemas/catalog-v1.schema.json",
    "lib/agent-equipment/schemas/execution-authority-v1.schema.json",
    "lib/agent-equipment/schemas/lock-v1.schema.json",
    "lib/agent-equipment/schemas/plan-action-set-v1.schema.json",
)


@dataclass(frozen=True, slots=True)
class FrozenJsonObject(Mapping[str, "FrozenJsonValue"]):
    """An immutable JSON object whose members have deterministic key order."""

    _items: tuple[tuple[str, FrozenJsonValue], ...]

    def __post_init__(self) -> None:
        if type(self._items) is not tuple:
            raise TypeError("frozen JSON object members must be an immutable tuple")
        previous_key: str | None = None
        for item in self._items:
            if type(item) is not tuple or len(item) != 2:
                raise TypeError("frozen JSON object members must be key/value pairs")
            key, value = item
            if type(key) is not str:
                raise TypeError("JSON object member names must be strings")
            _validate_string(key)
            if previous_key is not None and key <= previous_key:
                raise ValueError(
                    "frozen JSON object member names must be unique and sorted"
                )
            _validate_frozen_json(value)
            previous_key = key

    @override
    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._items)

    @override
    def __len__(self) -> int:
        return len(self._items)

    @override
    def __getitem__(self, key: str) -> FrozenJsonValue:
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)


FrozenJsonValue: TypeAlias = (
    JsonScalar | tuple["FrozenJsonValue", ...] | FrozenJsonObject
)


def _validate_frozen_json(value: object) -> None:
    if value is None or type(value) is bool or type(value) is int:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return
    if type(value) is str:
        _validate_string(value)
        return
    if isinstance(value, FrozenJsonObject):
        return
    if type(value) is tuple:
        for item in value:
            _validate_frozen_json(item)
        return
    raise TypeError("frozen JSON values must be recursively immutable")


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    equipment_identity: str | None = None
    harness: str | None = None
    route_identity: str | None = None

    def __post_init__(self) -> None:
        _require_string(self.code)
        _require_string(self.message)
        for value in (
            self.equipment_identity,
            self.harness,
            self.route_identity,
        ):
            if value is not None:
                _require_string(value)


@dataclass(frozen=True, slots=True)
class Catalog:
    schema_version: str
    document: FrozenJsonObject
    digest: str

    def __post_init__(self) -> None:
        if self.schema_version != _CATALOG_SCHEMA_VERSION:
            raise ValueError("catalog schema version must be catalog/v1")
        if type(self.document) is not FrozenJsonObject:
            raise TypeError("catalog document must be a frozen JSON object")
        if self.document.get("schema_version") != self.schema_version:
            raise ValueError("catalog schema version must agree with its document")
        _require_sha256(self.digest)
        if self.digest != _canonical_json_digest(self.document):
            raise ValueError("catalog digest does not match its canonical document")


@dataclass(frozen=True, slots=True)
class ResolvedLock:
    schema_version: str
    document: FrozenJsonObject
    digest: str

    def __post_init__(self) -> None:
        if self.schema_version != _LOCK_SCHEMA_VERSION:
            raise ValueError("resolved lock schema version must be lock/v1")
        if type(self.document) is not FrozenJsonObject:
            raise TypeError("resolved lock document must be a frozen JSON object")
        if self.document.get("schema_version") != self.schema_version:
            raise ValueError(
                "resolved lock schema version must agree with its document"
            )
        _require_sha256(self.digest)
        if self.digest != _canonical_json_digest(self.document):
            raise ValueError(
                "resolved lock digest does not match its canonical document"
            )


@dataclass(frozen=True, slots=True)
class CoverageRecord:
    equipment_identity: str
    harness: str
    record: FrozenJsonObject

    def __post_init__(self) -> None:
        _require_string(self.equipment_identity)
        _require_string(self.harness)
        if type(self.record) is not FrozenJsonObject:
            raise TypeError("coverage record must be a frozen JSON object")


@dataclass(frozen=True, slots=True)
class ValidatedCatalogLock:
    catalog: Catalog
    lock: ResolvedLock
    coverage: tuple[CoverageRecord, ...]

    def __post_init__(self) -> None:
        if type(self.catalog) is not Catalog or type(self.lock) is not ResolvedLock:
            raise TypeError("validated pair must contain typed catalog and lock models")
        if type(self.coverage) is not tuple:
            raise TypeError("coverage must be an immutable tuple")
        if any(type(record) is not CoverageRecord for record in self.coverage):
            raise TypeError("coverage must contain only typed coverage records")
        if self.lock.document.get("catalog_digest") != self.catalog.digest:
            raise ValueError("resolved lock must bind the exact catalog digest")
        coverage_keys = tuple(
            (record.equipment_identity, record.harness) for record in self.coverage
        )
        if coverage_keys != tuple(sorted(coverage_keys)) or len(coverage_keys) != len(
            set(coverage_keys)
        ):
            raise ValueError("coverage records must have sorted unique identities")
        lock_coverage = _lock_coverage(self.lock.document)
        model_coverage = {
            (record.equipment_identity, record.harness): record.record
            for record in self.coverage
        }
        if lock_coverage != model_coverage:
            raise ValueError("coverage must equal all lock coverage records")


@dataclass(frozen=True, slots=True)
class CatalogLockValidation:
    model: ValidatedCatalogLock | None
    diagnostics: tuple[Diagnostic, ...]

    def __post_init__(self) -> None:
        if type(self.diagnostics) is not tuple:
            raise TypeError("diagnostics must be an immutable tuple")
        if any(type(item) is not Diagnostic for item in self.diagnostics):
            raise TypeError("diagnostics must contain only typed diagnostics")
        if self.model is not None and type(self.model) is not ValidatedCatalogLock:
            raise TypeError("validation model must be a validated catalog/lock pair")
        valid_state = self.model is not None and not self.diagnostics
        invalid_state = self.model is None and bool(self.diagnostics)
        if not (valid_state or invalid_state):
            raise ValueError(
                "validation must contain either a model or one or more diagnostics"
            )


@dataclass(frozen=True, slots=True, order=True)
class InstalledFile:
    path: str
    digest: str

    def __post_init__(self) -> None:
        _require_string(self.path)
        _require_sha256(self.digest)


@dataclass(frozen=True, slots=True)
class InstalledImplementationManifest:
    schema_version: str
    runtime_identity: str
    runtime_executable_digest: str
    files: tuple[InstalledFile, ...]
    digest: str

    def __post_init__(self) -> None:
        if self.schema_version != _INSTALLED_IMPLEMENTATION_SCHEMA_VERSION:
            raise ValueError("installed implementation schema version is unsupported")
        _require_cpython_runtime_identity(self.runtime_identity)
        _require_sha256(self.runtime_executable_digest)
        _require_sha256(self.digest)
        if type(self.files) is not tuple:
            raise TypeError("installed files must be an immutable tuple")
        if any(type(item) is not InstalledFile for item in self.files):
            raise TypeError("installed files must contain only typed file records")
        paths = tuple(item.path for item in self.files)
        if paths != _INSTALLED_IMPLEMENTATION_PATHS:
            raise ValueError("installed file records must equal the closed inventory")
        if self.digest != _installed_implementation_digest(
            self.schema_version,
            self.runtime_identity,
            self.runtime_executable_digest,
            self.files,
        ):
            raise ValueError(
                "installed implementation manifest digest is not canonical"
            )

    def as_json(self) -> FrozenJsonObject:
        """Return the closed canonical payload whose digest identifies this manifest."""

        document = freeze_json(
            _installed_implementation_payload(
                self.schema_version,
                self.runtime_identity,
                self.runtime_executable_digest,
                self.files,
            )
        )
        if not isinstance(document, FrozenJsonObject):
            raise TypeError("manifest payload must be a JSON object")
        return document


def _validate_string(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("JSON strings must be valid Unicode scalar values") from error
    return value


def _require_string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("typed model text fields must be strings")
    return _validate_string(value)


def _require_sha256(value: object) -> str:
    digest = _require_string(value)
    if _SHA256_PATTERN.fullmatch(digest) is None:
        raise ValueError("digests must use lowercase sha256 followed by 64 hex digits")
    return digest


def _require_cpython_runtime_identity(value: object) -> str:
    identity = _require_string(value)
    match = _RUNTIME_IDENTITY_PATTERN.fullmatch(identity)
    if match is None:
        raise ValueError("runtime identity must name an exact CPython version")
    version = tuple(int(component) for component in match.groups())
    if version < (3, 12, 0):
        raise ValueError("runtime identity must be CPython 3.12 or newer")
    return identity


def _lock_coverage(
    document: FrozenJsonObject,
) -> dict[tuple[str, str], FrozenJsonObject]:
    serialized_coverage = document.get("coverage")
    if type(serialized_coverage) is not tuple:
        raise ValueError("resolved lock coverage must be an immutable JSON array")
    coverage: dict[tuple[str, str], FrozenJsonObject] = {}
    for entry in serialized_coverage:
        if not isinstance(entry, FrozenJsonObject):
            raise TypeError("resolved lock coverage entries must be JSON objects")
        equipment_identity = entry.get("equipment_identity")
        harness = entry.get("harness")
        record = entry.get("record")
        if (
            type(equipment_identity) is not str
            or type(harness) is not str
            or not isinstance(record, FrozenJsonObject)
        ):
            raise ValueError("resolved lock coverage entries are malformed")
        key = (equipment_identity, harness)
        if key in coverage:
            raise ValueError("resolved lock coverage identities must be unique")
        coverage[key] = record
    return coverage


def _installed_implementation_payload(
    schema_version: str,
    runtime_identity: str,
    runtime_executable_digest: str,
    files: tuple[InstalledFile, ...],
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "runtime_identity": runtime_identity,
        "runtime_executable_digest": runtime_executable_digest,
        "files": [
            {"path": installed.path, "digest": installed.digest} for installed in files
        ],
    }


def _installed_implementation_digest(
    schema_version: str,
    runtime_identity: str,
    runtime_executable_digest: str,
    files: tuple[InstalledFile, ...],
) -> str:
    return _canonical_json_digest(
        _installed_implementation_payload(
            schema_version,
            runtime_identity,
            runtime_executable_digest,
            files,
        )
    )


def _canonical_json_digest(document: object) -> str:
    payload = json.dumps(
        thaw_json(freeze_json(document)),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def freeze_json(value: object) -> FrozenJsonValue:
    """Validate a closed JSON value and return a recursively immutable copy."""

    if value is None or type(value) is bool or type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if type(value) is str:
        return _validate_string(value)
    if isinstance(value, Mapping):
        frozen_items: list[tuple[str, FrozenJsonValue]] = []
        for key in sorted(value):
            if type(key) is not str:
                raise TypeError("JSON object member names must be strings")
            frozen_items.append((_validate_string(key), freeze_json(value[key])))
        return FrozenJsonObject(tuple(frozen_items))
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        return tuple(freeze_json(item) for item in value)
    raise TypeError(f"unsupported JSON value type: {type(value).__name__}")


def thaw_json(value: FrozenJsonValue) -> JsonScalar | list[object] | dict[str, object]:
    """Return a detached mutable built-in representation of frozen JSON."""

    if isinstance(value, FrozenJsonObject):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value
