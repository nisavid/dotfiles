"""Canonical JSON encoding shared by every digest-bearing artifact."""

import hashlib
import json
import re
from typing import Any


DIGEST = re.compile(r"[0-9a-f]{64}\Z")


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
