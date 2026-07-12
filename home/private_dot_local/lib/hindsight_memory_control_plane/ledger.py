"""Content-free append-only controller decision ledger."""

import os
from pathlib import Path
from typing import Any, Mapping

from .canonical import canonical_bytes


LEDGER_KEYS = {
    "schema_version",
    "action_id",
    "correlation_id",
    "source_bank",
    "target_bank",
    "bank",
    "policy_digest",
    "artifact_digest",
    "decision",
    "reason_code",
    "timestamp",
    "reversible_record_id",
}
PAYLOAD_KEYS = {
    "body", "content", "document", "memory", "message", "output", "payload",
    "prompt", "request", "response", "text", "tool_output", "transcript",
}


class LedgerError(ValueError):
    pass


def _reject_payload(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in PAYLOAD_KEYS or normalized.endswith("_payload") or normalized.endswith("_content"):
                raise LedgerError(f"ledger record contains payload-like key: {key}")
            _reject_payload(item)
    elif isinstance(value, list):
        for item in value:
            _reject_payload(item)


def validate_record(record: Mapping[str, Any]) -> None:
    if not isinstance(record, dict):
        raise LedgerError("ledger record must be an object")
    unknown = set(record) - LEDGER_KEYS
    if unknown:
        raise LedgerError(f"ledger record has unknown keys: {sorted(unknown)}")
    required = {
        "schema_version", "action_id", "correlation_id", "policy_digest",
        "artifact_digest", "decision", "reason_code", "timestamp",
    }
    missing = required - set(record)
    if missing:
        raise LedgerError(f"ledger record is missing keys: {sorted(missing)}")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise LedgerError("ledger schema_version must be integer 1")
    _reject_payload(record)


def append_record(path: str | Path, record: Mapping[str, Any]) -> None:
    validate_record(record)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, canonical_bytes(record) + b"\n")
    finally:
        os.close(descriptor)
