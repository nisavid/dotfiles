"""Signed, exact-transition admission receipts for protected age changes."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from .privacy_age_envelopes import (
        AgeEnvelopeError,
        open_regular_file_descriptor,
        read_regular_file,
    )
except ImportError:  # pragma: no cover - direct module loading
    from privacy_age_envelopes import (
        AgeEnvelopeError,
        open_regular_file_descriptor,
        read_regular_file,
    )

ADMISSION_VERSION = "privacy-age-admission/v1"
ADMISSION_NAMESPACE = "nisavid/dotfiles/age-admission/v1"
ADMISSION_PRINCIPAL = "repository-owner"
ADMISSION_MARKER_PREFIX = b"<!-- privacy-age-admission/v1 "
ADMISSION_MARKER_SUFFIX = b" -->"
MAX_ADMISSION_BODY_BYTES = 256 * 1024
MAX_ADMISSION_RECEIPT_BYTES = 64 * 1024
# The marker and body limits are intentionally tighter than the structural
# path-count ceiling; bounded pull-request text remains the authoritative cap.
MAX_ADMISSION_PAYLOAD_BYTES = 32 * 1024
MAX_ADMISSION_SIGNATURE_BYTES = 8 * 1024
MAX_ADMISSION_PATHS = 4096
ADMISSION_MAX_LIFETIME = timedelta(hours=24)
ADMISSION_CLOCK_SKEW = timedelta(minutes=5)

_COMMIT_ID = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)
_NONCE = re.compile(r"[0-9a-f]{32,128}\Z", re.ASCII)
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
# Git permits printable ASCII punctuation in path components.  Validate the
# path structurally below rather than narrowing it to an incidental filename
# subset; controls, traversal components, leading roots, and backslashes stay
# forbidden.
_PATH_SEGMENT = re.compile(r"[ -~]+\Z", re.ASCII)
_MARKER = re.compile(
    re.escape(ADMISSION_MARKER_PREFIX)
    + rb"([A-Za-z0-9_-]{1,65536})"
    + re.escape(ADMISSION_MARKER_SUFFIX),
)


class AdmissionReceiptError(ValueError):
    """An admission receipt failed closed validation."""


def _validate_executable_path_authority(raw: str) -> Path:
    """Resolve one executable only through root/current-owned, non-writable parents."""

    lexical = Path(os.path.abspath(raw))
    try:
        canonical = lexical.resolve(strict=True)
        owner = os.getuid()
    except (AttributeError, OSError) as error:
        raise AdmissionReceiptError("admission signature tooling is unavailable") from error
    current = lexical.parent
    visited: set[Path] = set()
    while True:
        if current in visited:
            raise AdmissionReceiptError("admission signature tooling is unavailable")
        visited.add(current)
        try:
            info = current.lstat()
        except OSError as error:
            raise AdmissionReceiptError("admission signature tooling is unavailable") from error
        if stat.S_ISLNK(info.st_mode):
            if info.st_uid != 0:
                raise AdmissionReceiptError("admission signature tooling is unavailable")
            try:
                current = current.resolve(strict=True)
            except OSError as error:
                raise AdmissionReceiptError(
                    "admission signature tooling is unavailable"
                ) from error
            if not current.is_dir():
                raise AdmissionReceiptError("admission signature tooling is unavailable")
            continue
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022 or info.st_uid not in {0, owner}:
            raise AdmissionReceiptError("admission signature tooling is unavailable")
        parent = current.parent
        if parent == current:
            break
        current = parent
    try:
        descriptor, info = open_regular_file_descriptor(lexical)
    except (AgeEnvelopeError, OSError) as error:
        raise AdmissionReceiptError("admission signature tooling is unavailable") from error
    try:
        try:
            canonical_info = canonical.stat(follow_symlinks=False)
        except OSError as error:
            raise AdmissionReceiptError(
                "admission signature tooling is unavailable"
            ) from error
        if (
            not stat.S_ISREG(canonical_info.st_mode)
            or (info.st_dev, info.st_ino) != (canonical_info.st_dev, canonical_info.st_ino)
            or info.st_mode & 0o111 == 0
            or info.st_mode & 0o022
            or info.st_uid not in {0, owner}
            or canonical_info.st_uid not in {0, owner}
        ):
            raise AdmissionReceiptError("admission signature tooling is unavailable")
    finally:
        os.close(descriptor)
    return canonical


def _reject_constant(_: str) -> None:
    raise AdmissionReceiptError("non-finite admission JSON number")


def _object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AdmissionReceiptError("duplicate admission JSON member")
        result[key] = value
    return result


def _canonical_json(
    document: Mapping[str, Any],
    *,
    maximum: int = MAX_ADMISSION_PAYLOAD_BYTES,
) -> bytes:
    try:
        data = json.dumps(
            document,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, UnicodeError, ValueError, OverflowError, RecursionError) as error:
        raise AdmissionReceiptError("admission JSON is not canonicalizable") from error
    if len(data) > maximum:
        raise AdmissionReceiptError("admission payload is oversized")
    return data


def _parse_canonical_json(data: bytes, *, maximum: int) -> dict[str, Any]:
    if len(data) > maximum:
        raise AdmissionReceiptError("admission receipt is oversized")
    try:
        source = data.decode("ascii")
        document = json.loads(
            source,
            object_pairs_hook=_object_from_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        raise AdmissionReceiptError("admission receipt JSON is invalid") from error
    if not isinstance(document, dict):
        raise AdmissionReceiptError("admission receipt JSON is not an object")
    if _canonical_json(document, maximum=maximum) != data:
        raise AdmissionReceiptError("admission receipt JSON is not canonical")
    return document


def _encode_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _decode_b64(value: object, *, maximum: int) -> bytes:
    if not isinstance(value, str) or not value or len(value) > maximum * 2:
        raise AdmissionReceiptError("admission receipt encoding is invalid")
    if re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise AdmissionReceiptError("admission receipt encoding is invalid")
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.b64decode(
            (value + padding).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError) as error:
        raise AdmissionReceiptError("admission receipt encoding is invalid") from error
    if len(decoded) > maximum:
        raise AdmissionReceiptError("admission receipt encoding is oversized")
    return decoded


def _validated_timestamp(value: object, *, name: str) -> datetime:
    if not isinstance(value, str) or _TIMESTAMP.fullmatch(value) is None:
        raise AdmissionReceiptError(f"admission {name} is invalid")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as error:
        raise AdmissionReceiptError(f"admission {name} is invalid") from error
    return parsed


def _validated_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise AdmissionReceiptError("admission path is invalid")
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as error:
        raise AdmissionReceiptError("admission path is not ASCII") from error
    if len(encoded) > 512 or value.startswith("/") or "\\" in value:
        raise AdmissionReceiptError("admission path is invalid")
    segments = value.split("/")
    if any(
        segment in {"", ".", ".."}
        or _PATH_SEGMENT.fullmatch(segment) is None
        for segment in segments
    ):
        raise AdmissionReceiptError("admission path is not canonical")
    return value


def _validated_digest(value: object, *, allow_null: bool = True) -> str | None:
    if value is None and allow_null:
        return None
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise AdmissionReceiptError("admission digest is invalid")
    return value


def _validated_tree_side(value: object) -> dict[str, str | None] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"kind", "mode", "sha256"}:
        raise AdmissionReceiptError("admission tree entry is invalid")
    kind = value["kind"]
    mode = value["mode"]
    if (
        not isinstance(kind, str)
        or not kind
        or not isinstance(mode, str)
        or not mode
        or re.fullmatch(r"[0-9]{6}", mode) is None
    ):
        raise AdmissionReceiptError("admission tree entry is invalid")
    return {
        "kind": kind,
        "mode": mode,
        "sha256": _validated_digest(value["sha256"]),
    }


def validate_payload(
    payload: Mapping[str, Any],
    *,
    expected_repository: str | None = None,
    expected_base_commit: str | None = None,
    expected_head_commit: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate and return one exact admission payload."""

    if set(payload) != {
        "base_commit",
        "expires_at",
        "head_commit",
        "issued_at",
        "nonce",
        "paths",
        "repository",
        "version",
    }:
        raise AdmissionReceiptError("admission payload shape is invalid")
    if payload["version"] != ADMISSION_VERSION:
        raise AdmissionReceiptError("unsupported admission payload version")
    repository = payload["repository"]
    if not isinstance(repository, str) or not repository:
        raise AdmissionReceiptError("admission repository is invalid")
    try:
        if len(repository.encode("ascii")) > 256:
            raise AdmissionReceiptError("admission repository is invalid")
    except UnicodeEncodeError as error:
        raise AdmissionReceiptError("admission repository is not ASCII") from error
    for name in ("base_commit", "head_commit"):
        commit = payload[name]
        if not isinstance(commit, str) or _COMMIT_ID.fullmatch(commit) is None:
            raise AdmissionReceiptError("admission commit is invalid")
    if expected_repository is not None and repository != expected_repository:
        raise AdmissionReceiptError("admission repository does not match event")
    if expected_base_commit is not None and payload["base_commit"] != expected_base_commit:
        raise AdmissionReceiptError("admission base does not match event")
    if expected_head_commit is not None and payload["head_commit"] != expected_head_commit:
        raise AdmissionReceiptError("admission head does not match event")

    issued_at = _validated_timestamp(payload["issued_at"], name="issue time")
    expires_at = _validated_timestamp(payload["expires_at"], name="expiry")
    if expires_at <= issued_at or expires_at - issued_at > ADMISSION_MAX_LIFETIME:
        raise AdmissionReceiptError("admission lifetime is invalid")
    effective_now = now or datetime.now(timezone.utc)
    if effective_now < issued_at - ADMISSION_CLOCK_SKEW:
        raise AdmissionReceiptError("admission receipt is from the future")
    if effective_now > expires_at + ADMISSION_CLOCK_SKEW:
        raise AdmissionReceiptError("admission receipt is expired")

    nonce = payload["nonce"]
    if not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None:
        raise AdmissionReceiptError("admission nonce is invalid")

    raw_paths = payload["paths"]
    if not isinstance(raw_paths, list) or len(raw_paths) > MAX_ADMISSION_PATHS:
        raise AdmissionReceiptError("admission paths are invalid")
    previous_path: str | None = None
    paths: list[dict[str, Any]] = []
    for raw_path in raw_paths:
        if (
            not isinstance(raw_path, dict)
            or set(raw_path) != {"base", "head", "path"}
        ):
            raise AdmissionReceiptError("admission path entry is invalid")
        path = _validated_path(raw_path["path"])
        if previous_path is not None and path <= previous_path:
            raise AdmissionReceiptError("admission paths are not sorted")
        previous_path = path
        paths.append(
            {
                "base": _validated_tree_side(raw_path["base"]),
                "head": _validated_tree_side(raw_path["head"]),
                "path": path,
            }
        )

    return {
        "base_commit": payload["base_commit"],
        "expires_at": payload["expires_at"],
        "head_commit": payload["head_commit"],
        "issued_at": payload["issued_at"],
        "nonce": nonce,
        "paths": paths,
        "repository": repository,
        "version": ADMISSION_VERSION,
    }


def canonical_payload_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return canonical bytes suitable for signing and verification."""

    validated = validate_payload(payload)
    return _canonical_json(validated)


def encode_receipt(payload: Mapping[str, Any], signature: bytes) -> bytes:
    """Encode one signed payload as a PR-body marker."""

    payload_bytes = canonical_payload_bytes(payload)
    if not signature or len(signature) > MAX_ADMISSION_SIGNATURE_BYTES:
        raise AdmissionReceiptError("admission signature is invalid")
    envelope = {
        "payload": _encode_b64(payload_bytes),
        "signature": _encode_b64(signature),
        "version": ADMISSION_VERSION,
    }
    encoded = _encode_b64(
        _canonical_json(envelope, maximum=MAX_ADMISSION_RECEIPT_BYTES)
    )
    receipt = ADMISSION_MARKER_PREFIX + encoded.encode("ascii") + ADMISSION_MARKER_SUFFIX
    if len(receipt) > MAX_ADMISSION_RECEIPT_BYTES:
        raise AdmissionReceiptError("admission receipt is oversized")
    return receipt


def _decode_receipt_marker(encoded: bytes) -> tuple[dict[str, Any], bytes, bytes]:
    envelope_bytes = _decode_b64(encoded.decode("ascii"), maximum=MAX_ADMISSION_RECEIPT_BYTES)
    envelope = _parse_canonical_json(envelope_bytes, maximum=MAX_ADMISSION_RECEIPT_BYTES)
    if set(envelope) != {"payload", "signature", "version"}:
        raise AdmissionReceiptError("admission receipt shape is invalid")
    if envelope["version"] != ADMISSION_VERSION:
        raise AdmissionReceiptError("unsupported admission receipt version")
    payload_bytes = _decode_b64(envelope["payload"], maximum=MAX_ADMISSION_PAYLOAD_BYTES)
    signature = _decode_b64(
        envelope["signature"],
        maximum=MAX_ADMISSION_SIGNATURE_BYTES,
    )
    payload = _parse_canonical_json(payload_bytes, maximum=MAX_ADMISSION_PAYLOAD_BYTES)
    validate_payload(payload)
    return payload, payload_bytes, signature


def extract_receipt(body: bytes) -> tuple[dict[str, Any], bytes, bytes] | None:
    """Extract exactly one signed receipt marker from a bounded PR body."""

    if len(body) > MAX_ADMISSION_BODY_BYTES:
        raise AdmissionReceiptError("pull request body is oversized")
    matches = list(_MARKER.finditer(body))
    if not matches:
        return None
    if len(matches) != 1:
        raise AdmissionReceiptError("admission receipt is ambiguous")
    return _decode_receipt_marker(matches[0].group(1))


def verify_receipt_signature(
    message: bytes,
    signature: bytes,
    *,
    allowed_signers: Path,
) -> None:
    """Verify an SSH signature using only the trusted allowed-signers file."""

    if not signature or len(signature) > MAX_ADMISSION_SIGNATURE_BYTES:
        raise AdmissionReceiptError("admission signature is invalid")
    try:
        canonical_allowed_signers = allowed_signers.resolve(strict=True)
        info = canonical_allowed_signers.stat()
    except OSError as error:
        raise AdmissionReceiptError("admission signer configuration is unavailable") from error
    if not stat.S_ISREG(info.st_mode) or info.st_size > 32 * 1024:
        raise AdmissionReceiptError("admission signer configuration is unavailable")
    raw_ssh_keygen = shutil.which("ssh-keygen")
    if raw_ssh_keygen is None:
        raise AdmissionReceiptError("admission signature tooling is unavailable")
    ssh_keygen = _validate_executable_path_authority(raw_ssh_keygen)

    try:
        with tempfile.TemporaryDirectory(prefix="age-admission-verify.") as temporary:
            root = Path(temporary)
            signer_copy = root / "allowed-signers"
            signature_file = root / "receipt.sig"
            try:
                signer_data = read_regular_file(
                    canonical_allowed_signers,
                    maximum=32 * 1024,
                    expected=info,
                )
            except (AgeEnvelopeError, OSError) as error:
                raise AdmissionReceiptError(
                    "admission signer configuration is unavailable"
                ) from error
            signer_copy.write_bytes(signer_data)
            signature_file.write_bytes(signature)
            os.chmod(signer_copy, 0o600)
            os.chmod(signature_file, 0o600)
            result = subprocess.run(
                [
                    ssh_keygen,
                    "-Y",
                    "verify",
                    "-f",
                    os.fspath(signer_copy),
                    "-I",
                    ADMISSION_PRINCIPAL,
                    "-n",
                    ADMISSION_NAMESPACE,
                    "-s",
                    os.fspath(signature_file),
                ],
                input=message,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AdmissionReceiptError("admission signature verification failed") from error
    if result.returncode != 0:
        raise AdmissionReceiptError("admission signature verification failed")
