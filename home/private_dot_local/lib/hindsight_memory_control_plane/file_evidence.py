"""Stable, bounded reads for local evidence files."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Iterator


class FileEvidenceError(ValueError):
    pass


DIGEST = re.compile(r"[0-9a-f]{64}\Z")
MAX_VERIFIED_SNAPSHOT_BYTES = 8 * 1024 * 1024 * 1024


def _unsafe_directory(metadata: os.stat_result) -> bool:
    mode = stat.S_IMODE(metadata.st_mode)
    return metadata.st_uid not in {0, os.geteuid()} or bool(
        mode & 0o022 and not mode & stat.S_ISVTX
    )


def validate_trusted_regular_file(metadata: os.stat_result, label: str) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise FileEvidenceError(f"{label} must be a regular file")
    if metadata.st_uid not in {0, os.geteuid()}:
        raise FileEvidenceError(f"{label} must be owned by the current user or root")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise FileEvidenceError(f"{label} must not be group or world writable")
    if metadata.st_nlink != 1:
        raise FileEvidenceError(f"{label} must not have hard links")


def file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


@contextmanager
def verified_file_snapshot(
    value: str | Path,
    label: str,
    expected_digest: str,
    *,
    max_bytes: int = MAX_VERIFIED_SNAPSHOT_BYTES,
) -> Iterator[str]:
    if not isinstance(expected_digest, str) or DIGEST.fullmatch(expected_digest) is None:
        raise FileEvidenceError(f"{label} digest is invalid")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise FileEvidenceError(f"{label} size limit is invalid")
    source = Path(value)
    if not source.is_absolute():
        raise FileEvidenceError(f"{label} path must be absolute")
    reject_symlink_components(source, label, allow_missing=False)
    try:
        validate_trusted_regular_file(source.lstat(), label)
    except OSError:
        raise FileEvidenceError(f"{label} is unavailable") from None
    source_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        source_descriptor = os.open(source, source_flags)
    except OSError:
        raise FileEvidenceError(f"{label} is unavailable") from None
    yield_started = False
    try:
        before = os.fstat(source_descriptor)
        validate_trusted_regular_file(before, label)
        if before.st_size > max_bytes:
            raise FileEvidenceError(f"{label} is too large")
        suffix = ".zip" if source.suffix == ".zip" else ".archive"
        with tempfile.TemporaryDirectory(
            prefix="hindsight-memory-verified-archive-"
        ) as temporary:
            snapshot_directory = Path(temporary)
            snapshot_directory.chmod(0o700)
            snapshot = snapshot_directory / f"archive{suffix}"
            snapshot_flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            snapshot_descriptor = os.open(snapshot, snapshot_flags, 0o400)
            artifact_hash = hashlib.sha256()
            size = 0
            try:
                while chunk := os.read(source_descriptor, 1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise FileEvidenceError(f"{label} is too large")
                    artifact_hash.update(chunk)
                    remaining = memoryview(chunk)
                    while remaining:
                        written = os.write(snapshot_descriptor, remaining)
                        if written <= 0:
                            raise OSError("snapshot write failed")
                        remaining = remaining[written:]
                os.fsync(snapshot_descriptor)
                os.fchmod(snapshot_descriptor, 0o400)
                snapshot_metadata = os.fstat(snapshot_descriptor)
            finally:
                os.close(snapshot_descriptor)
            after = os.fstat(source_descriptor)
            current = source.lstat()
            if file_identity(before) != file_identity(after) or (
                current.st_dev, current.st_ino
            ) != (after.st_dev, after.st_ino):
                raise FileEvidenceError(f"{label} changed while being snapshotted")
            if not hmac.compare_digest(artifact_hash.hexdigest(), expected_digest):
                raise FileEvidenceError(f"{label} digest does not match plan")
            validate_trusted_regular_file(snapshot_metadata, label)
            current_snapshot = snapshot.lstat()
            if file_identity(snapshot_metadata) != file_identity(current_snapshot):
                raise FileEvidenceError(f"{label} snapshot identity changed")
            yield_started = True
            yield str(snapshot)
    except FileEvidenceError:
        raise
    except OSError:
        if yield_started:
            raise
        raise FileEvidenceError(f"{label} is unavailable") from None
    finally:
        try:
            os.close(source_descriptor)
        except OSError:
            pass


def reject_symlink_components(path: Path, label: str, *, allow_missing: bool) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            if allow_missing:
                return
            raise FileEvidenceError(f"{label} is unavailable") from None
        except OSError:
            raise FileEvidenceError(f"{label} is unavailable") from None
        if stat.S_ISLNK(metadata.st_mode):
            if current.parent == Path("/") and metadata.st_uid == 0:
                try:
                    resolved_target = current.resolve(strict=True)
                except FileNotFoundError:
                    if allow_missing:
                        return
                    raise FileEvidenceError(f"{label} is unavailable") from None
                except RuntimeError:
                    raise FileEvidenceError(
                        f"{label} path must not contain a symlink cycle"
                    ) from None
                except OSError:
                    raise FileEvidenceError(f"{label} is unavailable") from None
                if resolved_target == current:
                    raise FileEvidenceError(
                        f"{label} path must not contain a symlink cycle"
                    )
                reject_symlink_components(
                    resolved_target, label, allow_missing=False,
                )
                try:
                    target_metadata = resolved_target.lstat()
                except OSError:
                    raise FileEvidenceError(f"{label} is unavailable") from None
                if (
                    stat.S_ISDIR(target_metadata.st_mode)
                    and _unsafe_directory(target_metadata)
                ):
                    raise FileEvidenceError(
                        f"{label} path must not contain an untrusted or writable ancestor"
                    )
                continue
            raise FileEvidenceError(f"{label} path must not contain symlinks")
        if current != path and stat.S_ISDIR(metadata.st_mode):
            if _unsafe_directory(metadata):
                raise FileEvidenceError(
                    f"{label} path must not contain an untrusted or writable ancestor"
                )


def read_file_evidence(
    value: str | Path,
    label: str,
    *,
    allow_missing: bool = False,
    max_bytes: int = 1024 * 1024,
) -> tuple[bytes, str] | None:
    if not isinstance(value, (str, Path)):
        raise FileEvidenceError(f"{label} path must be absolute")
    path = Path(value)
    if not path.is_absolute():
        raise FileEvidenceError(f"{label} path must be absolute")
    reject_symlink_components(path, label, allow_missing=allow_missing)
    try:
        validate_trusted_regular_file(path.lstat(), label)
    except FileNotFoundError:
        if allow_missing:
            return None
        raise FileEvidenceError(f"{label} is unavailable") from None
    except OSError:
        raise FileEvidenceError(f"{label} is unavailable") from None
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        if allow_missing:
            return None
        raise FileEvidenceError(f"{label} is unavailable") from None
    except OSError:
        raise FileEvidenceError(f"{label} is unavailable") from None
    try:
        before = os.fstat(descriptor)
        validate_trusted_regular_file(before, label)
        if before.st_size > max_bytes:
            raise FileEvidenceError(f"{label} is too large")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(65536, max_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > max_bytes:
                raise FileEvidenceError(f"{label} is too large")
        after = os.fstat(descriptor)
    except FileEvidenceError:
        raise
    except OSError:
        raise FileEvidenceError(f"{label} is unavailable") from None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    try:
        current = path.lstat()
    except OSError:
        raise FileEvidenceError(f"{label} changed while being read") from None
    if file_identity(before) != file_identity(after) or (
        current.st_dev, current.st_ino
    ) != (after.st_dev, after.st_ino):
        raise FileEvidenceError(f"{label} changed while being read")
    raw = b"".join(chunks)
    return raw, hashlib.sha256(raw).hexdigest()
