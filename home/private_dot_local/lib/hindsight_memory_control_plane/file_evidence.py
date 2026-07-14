"""Stable, bounded reads for local evidence files."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat


class FileEvidenceError(ValueError):
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
        if stat.S_ISLNK(metadata.st_mode) and not (
            current.parent == Path("/") and metadata.st_uid == 0
        ):
            raise FileEvidenceError(f"{label} path must not contain symlinks")


def read_file_evidence(
    value: str | Path,
    label: str,
    *,
    allow_missing: bool = False,
    max_bytes: int = 1024 * 1024,
) -> tuple[bytes, str] | None:
    if not isinstance(value, (str, Path)):
        raise FileEvidenceError(f"{label} path must be absolute")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise FileEvidenceError(f"{label} path must be absolute")
    reject_symlink_components(path, label, allow_missing=allow_missing)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
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
        if not stat.S_ISREG(before.st_mode):
            raise FileEvidenceError(f"{label} must be a regular file")
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
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
    if identity(before) != identity(after) or (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino):
        raise FileEvidenceError(f"{label} changed while being read")
    raw = b"".join(chunks)
    return raw, hashlib.sha256(raw).hexdigest()
