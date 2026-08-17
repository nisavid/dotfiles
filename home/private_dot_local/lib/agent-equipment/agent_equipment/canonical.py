"""Strict JSON parsing and canonical content digests."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from collections.abc import Iterable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .model import (
    _INSTALLED_IMPLEMENTATION_PATHS,
    _INSTALLED_IMPLEMENTATION_SCHEMA_VERSION,
    FrozenJsonValue,
    InstalledFile,
    InstalledImplementationManifest,
    _installed_implementation_digest,
    freeze_json,
    thaw_json,
)

INSTALLED_IMPLEMENTATION_SCHEMA_VERSION = _INSTALLED_IMPLEMENTATION_SCHEMA_VERSION
_PACKAGE_PREFIX = "lib/agent-equipment/agent_equipment/"
_SCHEMA_PREFIX = "lib/agent-equipment/schemas/"
_PACKAGE_NAMES = tuple(
    path.removeprefix(_PACKAGE_PREFIX)
    for path in _INSTALLED_IMPLEMENTATION_PATHS
    if path.startswith(_PACKAGE_PREFIX)
)
_SCHEMA_NAMES = tuple(
    path.removeprefix(_SCHEMA_PREFIX)
    for path in _INSTALLED_IMPLEMENTATION_PATHS
    if path.startswith(_SCHEMA_PREFIX)
)
_MAX_LAUNCHER_BYTES = 256 * 1024
_MAX_PACKAGE_SOURCE_BYTES = 1024 * 1024
_MAX_SCHEMA_BYTES = 512 * 1024
_MAX_CAPTURED_IMPLEMENTATION_BYTES = 8 * 1024 * 1024
_MAX_RUNTIME_EXECUTABLE_BYTES = 256 * 1024 * 1024


def _reject_duplicate_members(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("JSON object member names must be unique")
        document[key] = value
    return document


def _reject_nonfinite_number(token: str) -> object:
    raise ValueError(f"non-finite JSON number is not permitted: {token}")


def byte_sha256(payload: bytes) -> str:
    """Return a tagged SHA-256 digest of exact bytes."""

    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def canonical_json_bytes(document: object) -> bytes:
    """Serialize a closed JSON document as compact sorted-key UTF-8."""

    mutable_document = thaw_json(freeze_json(document))
    return json.dumps(
        mutable_document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_json_sha256(document: object) -> str:
    """Return the tagged SHA-256 digest of canonical JSON bytes."""

    return byte_sha256(canonical_json_bytes(document))


def strict_load_json_bytes(payload: bytes) -> FrozenJsonValue:
    """Parse exact UTF-8 JSON bytes with unique members and closed values."""

    text = payload.decode("utf-8", errors="strict")
    document = json.loads(
        text,
        object_pairs_hook=_reject_duplicate_members,
        parse_constant=_reject_nonfinite_number,
    )
    return freeze_json(document)


def strict_load_json_path(path: Path) -> FrozenJsonValue:
    """Read and strictly parse one JSON file."""

    return strict_load_json_bytes(path.read_bytes())


def _before_descriptor_hash(role: str, relative_path: str) -> None:
    """Test seam invoked after validation and before descriptor hashing."""


@dataclass(frozen=True, slots=True)
class _HeldEntry:
    parent_descriptor: int
    name: str
    descriptor: int
    identity: tuple[int, int, int]
    stable_metadata: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _HeldPath:
    path: Path
    descriptor: int
    stable_metadata: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _HeldInventory:
    descriptor: int
    expected_names: tuple[str, ...]


def _stable_file_metadata(metadata: os.stat_result) -> tuple[int, ...]:
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


def _entry_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
    )


def _hash_descriptor(
    file_descriptor: int,
    role: str,
    relative_path: str,
    *,
    max_bytes: int,
) -> tuple[str, int]:
    if max_bytes < 0:
        raise ValueError("manifest hash bound is exhausted")
    before = os.fstat(file_descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("manifest entries must be regular files")
    if before.st_size > max_bytes:
        raise ValueError("manifest entry exceeds its hash bound")
    _before_descriptor_hash(role, relative_path)
    os.lseek(file_descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    hashed_bytes = 0
    while block := os.read(
        file_descriptor,
        min(1024 * 1024, (max_bytes + 1) - hashed_bytes),
    ):
        hashed_bytes += len(block)
        if hashed_bytes > max_bytes:
            raise ValueError("manifest entry exceeds its hash bound")
        digest.update(block)
    after = os.fstat(file_descriptor)
    if _stable_file_metadata(before) != _stable_file_metadata(after):
        raise ValueError("manifest entry changed while it was being hashed")
    return f"sha256:{digest.hexdigest()}", hashed_bytes


def _installed_file_max_bytes(relative: PurePosixPath) -> int:
    relative_path = relative.as_posix()
    if relative_path == "bin/agent-equipment":
        return _MAX_LAUNCHER_BYTES
    if relative_path.startswith(_PACKAGE_PREFIX):
        return _MAX_PACKAGE_SOURCE_BYTES
    if relative_path.startswith(_SCHEMA_PREFIX):
        return _MAX_SCHEMA_BYTES
    raise ValueError("installed file path has no capture bound")


def _open_descriptor(
    path: str | Path,
    flags: int,
    *,
    directory_descriptor: int | None = None,
) -> int:
    try:
        return os.open(
            path,
            flags | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=directory_descriptor,
        )
    except OSError as error:
        raise ValueError("manifest path could not be opened safely") from error


def _stat_entry(directory_descriptor: int, name: str) -> os.stat_result:
    try:
        return os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
    except OSError as error:
        raise ValueError("manifest path changed during hashing") from error


def _require_same_entry(
    directory_descriptor: int,
    name: str,
    expected: tuple[int, int, int],
) -> None:
    if _entry_identity(_stat_entry(directory_descriptor, name)) != expected:
        raise ValueError("manifest path changed during hashing")


def _require_same_path(path: Path, file_descriptor: int) -> None:
    try:
        current = path.lstat()
    except OSError as error:
        raise ValueError("manifest path changed during hashing") from error
    if _entry_identity(current) != _entry_identity(os.fstat(file_descriptor)):
        raise ValueError("manifest path changed during hashing")


def _require_stable_descriptor(
    file_descriptor: int,
    expected: tuple[int, ...],
) -> None:
    if _stable_file_metadata(os.fstat(file_descriptor)) != expected:
        raise ValueError("manifest entry changed during whole-set hashing")


def _require_closed_directory(
    directory_descriptor: int,
    expected_names: tuple[str, ...],
) -> None:
    observed_names: set[str] = set()
    try:
        with os.scandir(directory_descriptor) as entries:
            for entry in entries:
                if len(observed_names) >= len(expected_names):
                    raise ValueError("installed directory inventory must be closed")
                observed_names.add(entry.name)
    except OSError as error:
        raise ValueError("installed directory inventory could not be read") from error
    if observed_names != set(expected_names):
        raise ValueError("installed directory inventory must be closed")


def _safe_relative_path(value: str) -> PurePosixPath:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        raise ValueError("installed file paths must be nonempty POSIX relative paths")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("installed file paths must contain valid Unicode") from error
    relative = PurePosixPath(value)
    if (
        value == "."
        or relative.is_absolute()
        or relative.as_posix() != value
        or any(part in (".", "..") for part in relative.parts)
    ):
        raise ValueError("installed file paths must be normalized and contained")
    return relative


def _hold_installed_file(
    descriptors: ExitStack,
    root_descriptor: int,
    relative: PurePosixPath,
    held_entries: list[_HeldEntry],
    remaining_bytes: int,
) -> tuple[InstalledFile, tuple[int, int], int]:
    parent_descriptor = root_descriptor
    for part in relative.parts[:-1]:
        child_descriptor = _open_descriptor(
            part,
            os.O_RDONLY | os.O_DIRECTORY,
            directory_descriptor=parent_descriptor,
        )
        descriptors.callback(os.close, child_descriptor)
        child_metadata = os.fstat(child_descriptor)
        if not stat.S_ISDIR(child_metadata.st_mode):
            raise ValueError("installed path parents must be directories")
        held_entries.append(
            _HeldEntry(
                parent_descriptor=parent_descriptor,
                name=part,
                descriptor=child_descriptor,
                identity=_entry_identity(child_metadata),
                stable_metadata=_stable_file_metadata(child_metadata),
            )
        )
        parent_descriptor = child_descriptor

    file_name = relative.parts[-1]
    file_descriptor = _open_descriptor(
        file_name,
        os.O_RDONLY,
        directory_descriptor=parent_descriptor,
    )
    descriptors.callback(os.close, file_descriptor)
    file_metadata = os.fstat(file_descriptor)
    if not stat.S_ISREG(file_metadata.st_mode):
        raise ValueError("manifest entries must be regular files")
    if file_metadata.st_nlink != 1:
        raise ValueError("installed files must have exactly one hard link")
    held_entries.append(
        _HeldEntry(
            parent_descriptor=parent_descriptor,
            name=file_name,
            descriptor=file_descriptor,
            identity=_entry_identity(file_metadata),
            stable_metadata=_stable_file_metadata(file_metadata),
        )
    )
    digest, hashed_bytes = _hash_descriptor(
        file_descriptor,
        "installed",
        relative.as_posix(),
        max_bytes=min(_installed_file_max_bytes(relative), remaining_bytes),
    )
    return (
        InstalledFile(relative.as_posix(), digest),
        (file_metadata.st_dev, file_metadata.st_ino),
        hashed_bytes,
    )


def _hold_directory_child(
    descriptors: ExitStack,
    parent_descriptor: int,
    name: str,
    held_entries: list[_HeldEntry],
) -> int:
    descriptor = _open_descriptor(
        name,
        os.O_RDONLY | os.O_DIRECTORY,
        directory_descriptor=parent_descriptor,
    )
    descriptors.callback(os.close, descriptor)
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("installed path parents must be directories")
    held_entries.append(
        _HeldEntry(
            parent_descriptor=parent_descriptor,
            name=name,
            descriptor=descriptor,
            identity=_entry_identity(metadata),
            stable_metadata=_stable_file_metadata(metadata),
        )
    )
    return descriptor


def _hold_owned_tree_inventories(
    descriptors: ExitStack,
    root_descriptor: int,
    held_entries: list[_HeldEntry],
) -> tuple[_HeldInventory, ...]:
    lib_descriptor = _hold_directory_child(
        descriptors,
        root_descriptor,
        "lib",
        held_entries,
    )
    owned_descriptor = _hold_directory_child(
        descriptors,
        lib_descriptor,
        "agent-equipment",
        held_entries,
    )
    package_descriptor = _hold_directory_child(
        descriptors,
        owned_descriptor,
        "agent_equipment",
        held_entries,
    )
    schema_descriptor = _hold_directory_child(
        descriptors,
        owned_descriptor,
        "schemas",
        held_entries,
    )
    inventories = (
        _HeldInventory(
            descriptor=owned_descriptor,
            expected_names=("agent_equipment", "schemas"),
        ),
        _HeldInventory(
            descriptor=package_descriptor,
            expected_names=_PACKAGE_NAMES,
        ),
        _HeldInventory(
            descriptor=schema_descriptor,
            expected_names=_SCHEMA_NAMES,
        ),
    )
    for inventory in inventories:
        _require_closed_directory(
            inventory.descriptor,
            inventory.expected_names,
        )
    return inventories


def _hold_runtime_executable(
    descriptors: ExitStack,
    runtime_executable: Path,
) -> tuple[str, _HeldPath, Path]:
    try:
        resolved_runtime = runtime_executable.resolve(strict=True)
        resolved_before = resolved_runtime.lstat()
    except OSError as error:
        raise ValueError("runtime executable could not be resolved") from error
    file_descriptor = _open_descriptor(resolved_runtime, os.O_RDONLY)
    descriptors.callback(os.close, file_descriptor)
    opened_metadata = os.fstat(file_descriptor)
    if _entry_identity(resolved_before) != _entry_identity(opened_metadata):
        raise ValueError("runtime executable changed before hashing")
    digest, _ = _hash_descriptor(
        file_descriptor,
        "runtime",
        resolved_runtime.as_posix(),
        max_bytes=_MAX_RUNTIME_EXECUTABLE_BYTES,
    )
    return (
        digest,
        _HeldPath(
            path=resolved_runtime,
            descriptor=file_descriptor,
            stable_metadata=_stable_file_metadata(opened_metadata),
        ),
        resolved_runtime,
    )


def _runtime_identity(
    implementation_name: str,
    version: tuple[int, int, int],
) -> str:
    if implementation_name != "cpython":
        raise ValueError("runtime implementation must be CPython")
    if (
        type(version) is not tuple
        or len(version) != 3
        or any(type(component) is not int or component < 0 for component in version)
        or version < (3, 12, 0)
    ):
        raise ValueError("runtime version must be CPython 3.12 or newer")
    return f"cpython:{version[0]}.{version[1]}.{version[2]}"


def _closed_relative_paths(relative_paths: Iterable[str]) -> tuple[PurePosixPath, ...]:
    if isinstance(relative_paths, (str, bytes)):
        raise TypeError("relative_paths must be an iterable of path strings")
    normalized = tuple(_safe_relative_path(value) for value in relative_paths)
    if tuple(path.as_posix() for path in normalized) != _INSTALLED_IMPLEMENTATION_PATHS:
        raise ValueError(
            "installed paths must equal the closed implementation inventory"
        )
    return normalized


def _revalidate_held_entries(
    root: _HeldPath,
    runtime: _HeldPath,
    runtime_executable: Path,
    resolved_runtime: Path,
    held_entries: Iterable[_HeldEntry],
    held_inventories: Iterable[_HeldInventory],
) -> None:
    _require_stable_descriptor(runtime.descriptor, runtime.stable_metadata)
    _require_same_path(runtime.path, runtime.descriptor)
    try:
        selected_after = runtime_executable.resolve(strict=True)
    except OSError as error:
        raise ValueError("runtime executable changed during hashing") from error
    if selected_after != resolved_runtime:
        raise ValueError("runtime executable changed during hashing")
    _require_stable_descriptor(root.descriptor, root.stable_metadata)
    _require_same_path(root.path, root.descriptor)
    for inventory in held_inventories:
        _require_closed_directory(
            inventory.descriptor,
            inventory.expected_names,
        )
    for held in reversed(tuple(held_entries)):
        _require_stable_descriptor(held.descriptor, held.stable_metadata)
        _require_same_entry(held.parent_descriptor, held.name, held.identity)


def _build_installed_implementation_manifest(
    *,
    implementation_name: str,
    version: tuple[int, int, int],
    runtime_executable: Path,
    installed_root: Path,
    relative_paths: Iterable[str],
) -> InstalledImplementationManifest:
    """Internal fixture seam for one closed in-memory implementation manifest."""

    runtime_identity = _runtime_identity(implementation_name, version)
    normalized = _closed_relative_paths(relative_paths)
    if not isinstance(runtime_executable, Path):
        raise TypeError("runtime executable must be a concrete path")
    if not isinstance(installed_root, Path):
        raise TypeError("installed root must be a concrete path")

    with ExitStack() as descriptors:
        (
            runtime_executable_digest,
            held_runtime,
            resolved_runtime,
        ) = _hold_runtime_executable(descriptors, runtime_executable)

        try:
            root_metadata = installed_root.lstat()
        except OSError as error:
            raise ValueError("installed root must exist") from error
        if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(
            root_metadata.st_mode
        ):
            raise ValueError("installed root must be a real directory")
        root_descriptor = _open_descriptor(
            installed_root,
            os.O_RDONLY | os.O_DIRECTORY,
        )
        descriptors.callback(os.close, root_descriptor)
        opened_root_metadata = os.fstat(root_descriptor)
        if _entry_identity(root_metadata) != _entry_identity(opened_root_metadata):
            raise ValueError("installed root changed before hashing")
        held_root = _HeldPath(
            path=installed_root,
            descriptor=root_descriptor,
            stable_metadata=_stable_file_metadata(opened_root_metadata),
        )

        held_entries: list[_HeldEntry] = []
        held_inventories = _hold_owned_tree_inventories(
            descriptors,
            root_descriptor,
            held_entries,
        )
        installed_files: list[InstalledFile] = []
        installed_inodes: set[tuple[int, int]] = set()
        captured_size = 0
        for relative in normalized:
            installed_file, inode, captured_bytes = _hold_installed_file(
                descriptors,
                root_descriptor,
                relative,
                held_entries,
                _MAX_CAPTURED_IMPLEMENTATION_BYTES - captured_size,
            )
            if inode in installed_inodes:
                raise ValueError("installed files must not share an inode")
            installed_inodes.add(inode)
            installed_files.append(installed_file)
            captured_size += captured_bytes

        _revalidate_held_entries(
            held_root,
            held_runtime,
            runtime_executable,
            resolved_runtime,
            held_entries,
            held_inventories,
        )

        files = tuple(installed_files)
        digest = _installed_implementation_digest(
            INSTALLED_IMPLEMENTATION_SCHEMA_VERSION,
            runtime_identity,
            runtime_executable_digest,
            files,
        )
        return InstalledImplementationManifest(
            schema_version=INSTALLED_IMPLEMENTATION_SCHEMA_VERSION,
            runtime_identity=runtime_identity,
            runtime_executable_digest=runtime_executable_digest,
            files=files,
            digest=digest,
        )


def build_installed_implementation_manifest() -> InstalledImplementationManifest:
    """Build the complete manifest for this process and installed package."""

    executable = sys.executable
    if type(executable) is not str or not executable:
        raise ValueError("selected runtime executable is unavailable")
    return _build_installed_implementation_manifest(
        implementation_name=sys.implementation.name,
        version=(
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        ),
        runtime_executable=Path(executable),
        installed_root=Path(__file__).resolve().parents[3],
        relative_paths=_INSTALLED_IMPLEMENTATION_PATHS,
    )
