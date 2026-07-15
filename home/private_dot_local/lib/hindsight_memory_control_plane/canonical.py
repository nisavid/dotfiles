"""Canonical JSON encoding shared by every digest-bearing artifact."""

import hashlib
import json
import math
import re
from typing import Any


DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class StrictJsonError(ValueError):
    """A JSON value is ambiguous or not interoperable."""


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise StrictJsonError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def _reject_non_finite_constant(value: str) -> None:
    raise StrictJsonError(f"non-finite JSON constant: {value}")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise StrictJsonError(f"non-finite JSON number: {value}")
    return parsed


def strict_json_loads(value: str | bytes | bytearray) -> Any:
    """Parse interoperable JSON without ambiguous object keys or numbers."""
    return json.loads(
        value,
        object_pairs_hook=_reject_duplicate_object_keys,
        parse_constant=_reject_non_finite_constant,
        parse_float=_parse_finite_float,
    )


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
