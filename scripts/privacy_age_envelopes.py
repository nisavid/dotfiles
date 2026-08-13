"""Closed inventory primitives for public age ciphertexts."""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

AGE_MANIFEST_NAME = ".privacy-age-envelopes.json"
AGE_MANIFEST_VERSION = "privacy-age-envelopes/v1"
AGE_VERSION = "v1.3.1"
MAX_AGE_ENVELOPE_BYTES = 4 * 1024 * 1024
MAX_AGE_ENVELOPES = 4096
MAX_AGE_MANIFEST_BYTES = 1024 * 1024
MAX_AGE_PATH_BYTES = 512
AGE_INSPECTION_MEMBERS = {
    "version",
    "postquantum",
    "armor",
    "stanza_types",
    "sizes",
}
AGE_INSPECTION_SIZE_MEMBERS = {
    "header",
    "armor",
    "overhead",
    "min_payload",
    "max_payload",
    "min_padding",
    "max_padding",
}

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PATH_SEGMENT = re.compile(r"[A-Za-z0-9._-]+\Z", re.ASCII)


class AgeEnvelopeError(ValueError):
    """An age-envelope inventory failed closed validation."""


def _reject_constant(_: str) -> None:
    raise AgeEnvelopeError("non-finite JSON number")


def _object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AgeEnvelopeError("duplicate JSON member")
        result[key] = value
    return result


def validate_age_path(relative: object) -> str:
    """Return one safe canonical repository-relative age path."""

    if not isinstance(relative, str) or not relative:
        raise AgeEnvelopeError("invalid envelope path")
    try:
        encoded = relative.encode("ascii")
    except UnicodeEncodeError as error:
        raise AgeEnvelopeError("non-ASCII envelope path") from error
    if len(encoded) > MAX_AGE_PATH_BYTES or not relative.endswith(".age"):
        raise AgeEnvelopeError("invalid envelope path")
    if relative.startswith("/") or "\\" in relative:
        raise AgeEnvelopeError("non-relative envelope path")
    segments = relative.split("/")
    if any(
        segment in {"", ".", ".."} or _PATH_SEGMENT.fullmatch(segment) is None
        for segment in segments
    ):
        raise AgeEnvelopeError("non-canonical envelope path")
    return relative


def canonical_manifest_bytes(entries: Mapping[str, str]) -> bytes:
    """Serialize a deterministic closed age-envelope inventory."""

    document = {
        "version": AGE_MANIFEST_VERSION,
        "envelopes": [
            {"path": path, "sha256": entries[path]} for path in sorted(entries)
        ],
    }
    data = (json.dumps(document, ensure_ascii=True, indent=2) + "\n").encode("ascii")
    if len(data) > MAX_AGE_MANIFEST_BYTES:
        raise AgeEnvelopeError("oversized envelope manifest")
    return data


def parse_manifest_bytes(data: bytes) -> dict[str, str]:
    """Parse and validate the exact canonical v1 manifest representation."""

    if len(data) > MAX_AGE_MANIFEST_BYTES:
        raise AgeEnvelopeError("oversized envelope manifest")
    try:
        source = data.decode("utf-8")
        document = json.loads(
            source,
            object_pairs_hook=_object_from_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AgeEnvelopeError("invalid envelope manifest JSON") from error
    if not isinstance(document, dict) or set(document) != {"version", "envelopes"}:
        raise AgeEnvelopeError("invalid envelope manifest shape")
    if document["version"] != AGE_MANIFEST_VERSION:
        raise AgeEnvelopeError("unsupported envelope manifest version")
    raw_entries = document["envelopes"]
    if not isinstance(raw_entries, list) or len(raw_entries) > MAX_AGE_ENVELOPES:
        raise AgeEnvelopeError("invalid envelope manifest entries")

    entries: dict[str, str] = {}
    folded_paths: set[str] = set()
    for entry in raw_entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise AgeEnvelopeError("invalid envelope manifest entry")
        relative = validate_age_path(entry["path"])
        digest = entry["sha256"]
        if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
            raise AgeEnvelopeError("invalid envelope digest")
        folded = relative.casefold()
        if relative in entries or folded in folded_paths:
            raise AgeEnvelopeError("duplicate envelope path")
        entries[relative] = digest
        folded_paths.add(folded)

    if data != canonical_manifest_bytes(entries):
        raise AgeEnvelopeError("non-canonical envelope manifest")
    return entries


def age_inspection_has_exact_postquantum_stanzas(
    document: object,
    *,
    stanza_count: int,
) -> bool:
    """Return whether age-inspect metadata proves the exact PQ stanza policy."""

    if not isinstance(document, dict) or set(document) != AGE_INSPECTION_MEMBERS:
        return False
    stanza_types = document["stanza_types"]
    sizes = document["sizes"]
    return (
        stanza_count > 0
        and document["version"] == "age-encryption.org/v1"
        and document["postquantum"] == "yes"
        and type(document["armor"]) is bool
        and isinstance(stanza_types, list)
        and len(stanza_types) == stanza_count
        and all(
            isinstance(stanza_type, str) and stanza_type == "mlkem768x25519"
            for stanza_type in stanza_types
        )
        and isinstance(sizes, dict)
        and set(sizes) == AGE_INSPECTION_SIZE_MEMBERS
        and all(type(size) is int and size >= 0 for size in sizes.values())
    )


def open_regular_file_descriptor(path: Path) -> tuple[int, os.stat_result]:
    """Open one regular file without following or blocking on its final path."""

    no_follow = getattr(os, "O_NOFOLLOW", None)
    nonblocking = getattr(os, "O_NONBLOCK", None)
    if no_follow is None or nonblocking is None:
        raise AgeEnvelopeError("safe regular-file opens are unavailable")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | no_follow | nonblocking
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise AgeEnvelopeError("file is unreadable or not regular") from error
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise AgeEnvelopeError("file is not regular")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor, info


def read_regular_file(path: Path, *, maximum: int) -> bytes:
    """Read one bounded regular file through a stable descriptor."""

    descriptor, _ = open_regular_file_descriptor(path)
    try:
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(data) > maximum:
        raise AgeEnvelopeError("file exceeds size limit")
    return data


def load_manifest(root: Path) -> dict[str, str]:
    """Load the root manifest through the bounded regular-file boundary."""

    data = read_regular_file(root / AGE_MANIFEST_NAME, maximum=MAX_AGE_MANIFEST_BYTES)
    return parse_manifest_bytes(data)


def discover_age_files(
    root: Path,
    *,
    skipped_directories: Iterable[str] = (),
) -> dict[str, Path]:
    """Return all and only regular, case-sensitive ``*.age`` paths."""

    skipped = set(skipped_directories)
    discovered: dict[str, Path] = {}
    folded_paths: set[str] = set()
    try:

        def walk_error(error: OSError) -> None:
            raise AgeEnvelopeError("envelope inventory is unreadable") from error

        walker = os.walk(
            root,
            topdown=True,
            onerror=walk_error,
            followlinks=False,
        )
        for current, directory_names, file_names in walker:
            directory_names[:] = [
                name for name in directory_names if name not in skipped
            ]
            candidates = list(file_names)
            candidates.extend(
                name for name in directory_names if name.casefold().endswith(".age")
            )
            for name in candidates:
                if not name.casefold().endswith(".age"):
                    continue
                if not name.endswith(".age"):
                    raise AgeEnvelopeError("case-confusable age envelope suffix")
                path = Path(current, name)
                relative = validate_age_path(path.relative_to(root).as_posix())
                try:
                    info = path.lstat()
                except OSError as error:
                    raise AgeEnvelopeError(
                        "envelope inventory is unreadable"
                    ) from error
                if not stat.S_ISREG(info.st_mode):
                    raise AgeEnvelopeError(
                        "envelope inventory contains a non-regular path"
                    )
                folded = relative.casefold()
                if relative in discovered or folded in folded_paths:
                    raise AgeEnvelopeError(
                        "envelope inventory contains duplicate paths"
                    )
                discovered[relative] = path
                folded_paths.add(folded)
    except OSError as error:
        raise AgeEnvelopeError("envelope inventory is unreadable") from error
    if len(discovered) > MAX_AGE_ENVELOPES:
        raise AgeEnvelopeError("too many age envelopes")
    return discovered
