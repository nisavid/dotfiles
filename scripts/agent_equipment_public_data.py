"""Secret-free public-data policy shared by equipment validators and scans."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

__all__ = ("contains_literal_credential", "string_looks_like_credential")


_PROVIDER_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9_]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"sk-[A-Za-z0-9_-]{20,}|"
    r"pst_[A-Za-z0-9_-]{12,}::[A-Za-z0-9_-]{8,})(?![A-Za-z0-9_])"
)
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])(?:x-api-key|api[_-]?key|access[_-]?token|"
    r"password|client[_-]?secret)\s*[:=]\s*([A-Za-z0-9][^\s,\]\}\"']*)"
)
_AUTHORIZATION_SCHEME = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])(?:authorization|proxy-authorization)\s*[:=]\s*"
    r"(?:bearer|basic|digest)\s+[A-Za-z0-9][^\s,\]\}\"']*"
    r"(?![A-Za-z0-9._~+/@:()\[\]-])"
)
_OPAQUE_AUTHORIZATION_HEADER = re.compile(
    r"(?<![A-Za-z0-9_-])(?:Authorization|Proxy-Authorization)\s*[:=]\s*"
    r"(?!fixture/|sha256:)[A-Za-z0-9][A-Za-z0-9._~+/@:-]{7,}"
    r"(?![A-Za-z0-9._~+/@:()\[\]-])"
)
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+")
_CREDENTIAL_QUERY = re.compile(
    r"(?i)[?&](?:x-api-key|api[_-]?key|access[_-]?token|token|secret|"
    r"password|client[_-]?secret)=[A-Za-z0-9][^&#\s,\]\}\"']*"
)
_REFERENCE_PLACEHOLDER = re.compile(
    r"\$\{\{[^{}\r\n]+\}\}|\{reference\}|\\?\$\{[A-Za-z_][A-Za-z0-9_]*\}|"
    r"\\?\$[A-Za-z_][A-Za-z0-9_]*|\\?\$[0-9@#?*!-]"
)


def string_looks_like_credential(value: str) -> bool:
    """Return whether *value* contains literal credential material."""

    candidate = _REFERENCE_PLACEHOLDER.sub("", value)
    if (
        _PROVIDER_TOKEN.search(candidate) is not None
        or _AUTHORIZATION_SCHEME.search(candidate) is not None
        or _OPAQUE_AUTHORIZATION_HEADER.search(candidate) is not None
        or _BEARER_VALUE.search(candidate) is not None
        or _CREDENTIAL_QUERY.search(candidate) is not None
    ):
        return True
    return any(
        match.group(1).casefold() not in {"bearer", "basic"}
        for match in _CREDENTIAL_ASSIGNMENT.finditer(candidate)
    )


def contains_literal_credential(document: object) -> bool:
    """Return whether a recursive public document contains a literal credential."""

    pending: list[Any] = [document]
    seen: set[int] = set()
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            if string_looks_like_credential(value):
                return True
            continue
        if isinstance(value, Mapping):
            identity = id(value)
            if identity in seen:
                continue
            seen.add(identity)
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            identity = id(value)
            if identity in seen:
                continue
            seen.add(identity)
            pending.extend(value)
    return False
