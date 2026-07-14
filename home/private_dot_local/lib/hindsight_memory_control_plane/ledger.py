"""Closed-schema, content-free append-only controller decision ledger."""

import fcntl
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Any, Mapping

from .canonical import canonical_bytes


LEDGER_KEYS = {
    "schema_version", "action_id", "correlation_id", "source_bank",
    "target_bank", "policy_digest", "artifact_digest", "decision",
    "reason_code", "timestamp", "reversible_record_id",
}
BANK_KEYS = {"profile_id", "bank_id", "endpoint"}
ENDPOINT_KEYS = {"profile_id", "scheme", "host", "port", "tenant"}
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
REASON = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z\Z")
DECISIONS = {"allow", "apply", "deny", "fail", "rollback", "skip"}


class LedgerError(ValueError):
    pass


def _identifier(value: Any, label: str) -> None:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise LedgerError(f"{label} must be a bounded identifier")


def _endpoint(value: Any, profile_id: str) -> None:
    if not isinstance(value, dict) or set(value) != ENDPOINT_KEYS:
        actual = set(value) if isinstance(value, dict) else set()
        raise LedgerError(f"endpoint keys are closed (missing={sorted(ENDPOINT_KEYS - actual)}, unknown={sorted(actual - ENDPOINT_KEYS)})")
    if value["profile_id"] != profile_id:
        raise LedgerError("endpoint profile_id must match bank profile_id")
    _identifier(value["profile_id"], "endpoint profile_id")
    if value["scheme"] not in {"http", "https"}:
        raise LedgerError("endpoint scheme must be http or https")
    if not isinstance(value["host"], str) or not value["host"] or len(value["host"]) > 253:
        raise LedgerError("endpoint host must be a bounded non-empty string")
    if type(value["port"]) is not int or not 1 <= value["port"] <= 65535:
        raise LedgerError("endpoint port must be an integer from 1 to 65535")
    _identifier(value["tenant"], "endpoint tenant")


def _bank(value: Any, label: str) -> None:
    if not isinstance(value, dict) or set(value) != BANK_KEYS:
        actual = set(value) if isinstance(value, dict) else set()
        raise LedgerError(f"bank reference keys are closed (missing={sorted(BANK_KEYS - actual)}, unknown={sorted(actual - BANK_KEYS)})")
    _identifier(value["profile_id"], f"{label} profile_id")
    _identifier(value["bank_id"], f"{label} bank_id")
    _endpoint(value["endpoint"], value["profile_id"])


def validate_record(record: Mapping[str, Any]) -> None:
    if not isinstance(record, dict):
        raise LedgerError("ledger record must be an object")
    unknown = set(record) - LEDGER_KEYS
    missing = LEDGER_KEYS - set(record)
    if unknown:
        raise LedgerError(f"ledger record has unknown keys: {sorted(unknown)}")
    if missing:
        raise LedgerError(f"ledger record is missing keys: {sorted(missing)}")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise LedgerError("ledger schema_version must be integer 1")
    _identifier(record["action_id"], "action_id")
    _identifier(record["correlation_id"], "correlation_id")
    _bank(record["source_bank"], "source_bank")
    _bank(record["target_bank"], "target_bank")
    for key in ("policy_digest", "artifact_digest"):
        if not isinstance(record[key], str) or not DIGEST.fullmatch(record[key]):
            raise LedgerError(f"{key} must be a lowercase SHA-256 digest")
    if record["decision"] not in DECISIONS:
        raise LedgerError("decision is not a supported enum")
    if not isinstance(record["reason_code"], str) or not REASON.fullmatch(record["reason_code"]):
        raise LedgerError("reason_code must be an uppercase enum")
    if not isinstance(record["timestamp"], str) or not TIMESTAMP.fullmatch(record["timestamp"]):
        raise LedgerError("timestamp must be a UTC RFC 3339 timestamp")
    reversible = record["reversible_record_id"]
    if reversible is not None:
        _identifier(reversible, "reversible_record_id")


def _open_ledger_parent(path: Path) -> int:
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise OSError("symlink-safe directory access is unavailable")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    absolute = Path(os.path.abspath(path))
    if sys.platform == "darwin" and len(absolute.parts) > 1:
        aliases = {"var": ("private", "var"), "tmp": ("private", "tmp"), "etc": ("private", "etc")}
        replacement = aliases.get(absolute.parts[1])
        if replacement is not None:
            absolute = Path("/").joinpath(*replacement, *absolute.parts[2:])
    descriptor = os.open("/", flags)
    try:
        for component in absolute.parts[1:]:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                else:
                    os.fsync(descriptor)
                child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def append_record(path: str | Path, record: Mapping[str, Any]) -> None:
    validate_record(record)
    target = Path(path)
    if target.name in {"", ".", ".."}:
        raise OSError("ledger destination name is invalid")
    directory = _open_ledger_parent(target.parent)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW
    try:
        descriptor = os.open(target.name, flags, 0o600, dir_fd=directory)
    except Exception:
        os.close(directory)
        raise
    original_size: int | None = None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise OSError("ledger destination must be a regular file")
        os.fchmod(descriptor, 0o600)
        deadline = time.monotonic() + 2.0
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("ledger lock acquisition timed out")
                time.sleep(0.01)
        original_size = os.lseek(descriptor, 0, os.SEEK_END)
        body = canonical_bytes(record) + b"\n"
        offset = 0
        while offset < len(body):
            written = os.write(descriptor, body[offset:])
            if written <= 0 or written > len(body) - offset:
                raise OSError("short ledger write")
            offset += written
        os.fsync(descriptor)
        os.fsync(directory)
    except Exception as error:
        if original_size is not None:
            try:
                os.ftruncate(descriptor, original_size)
                os.fsync(descriptor)
            except OSError as rollback_error:
                raise OSError("ledger append rollback failed") from error
        raise
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(descriptor)
        os.close(directory)
