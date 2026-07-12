"""Closed-schema, content-free append-only controller decision ledger."""

import os
from pathlib import Path
import re
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
