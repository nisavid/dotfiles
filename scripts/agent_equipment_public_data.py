"""Secret-free public-data policy shared by equipment validators and scans."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

__all__ = (
    "contains_literal_credential",
    "string_looks_like_credential",
    "string_looks_like_private_key",
)


_PROVIDER_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9_]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"sk-[A-Za-z0-9_-]{20,}|"
    r"pst_[A-Za-z0-9_-]{12,}::[A-Za-z0-9_-]{8,})(?![A-Za-z0-9_])"
)
_CREDENTIAL_FIELD_NAMES = frozenset(
    {
        "apikey",
        "accesstoken",
        "authorization",
        "clientsecret",
        "password",
        "proxyauthorization",
        "secret",
        "token",
        "xapikey",
    }
)
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?ix)(?<![A-Za-z0-9_-])"
    r'(?:"(?P<double_key>[A-Za-z][A-Za-z0-9_-]*)"|'
    r"'(?P<single_key>[A-Za-z][A-Za-z0-9_-]*)'|"
    r"(?P<bare_key>[A-Za-z][A-Za-z0-9_-]*))"
    r"\s*[:=]\s*"
    r'(?:"(?P<double_value>(?:\\.|[^"\\])*)"|'
    r"'(?P<single_value>(?:\\.|[^'\\])*)'|"
    r"(?P<bare_value>[A-Za-z0-9][A-Za-z0-9._~+/@:-]*))"
    r"(?=\s*(?:[,}\]\r\n#]|$))"
)
_AUTHORIZATION_SCHEME = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])(?:authorization|proxy-authorization)\s*[:=]\s*"
    r"(?:bearer|basic|digest)\s+[A-Za-z0-9][^\s,\]\}\"']*"
    r"(?![A-Za-z0-9._~+/@:()\[\]-])"
)
_OPAQUE_AUTHORIZATION_HEADER = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])(?:authorization|proxy-authorization)\s*[:=]\s*"
    r"(?!fixture/|sha256:|validated_record\b)"
    r"[A-Za-z0-9][A-Za-z0-9._~+/@:-]{7,}"
    r"(?![A-Za-z0-9._~+/@:()\[\]-])"
)
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+")
_CREDENTIAL_QUERY = re.compile(
    r"(?i)[?&](?:x-api-key|api[_-]?key|access[_-]?token|token|secret|"
    r"password|client[_-]?secret)=[A-Za-z0-9][^&#\s,\]\}\"']*"
)
_REFERENCE_PLACEHOLDER = re.compile(
    r"\$\{\{\s*[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\s*\}\}|"
    r"\{reference\}|\\?\$\{[A-Za-z_][A-Za-z0-9_]*\}|"
    r"\\?\$[A-Za-z_][A-Za-z0-9_]*|\\?\$[0-9@#?*!-]"
)
_JSON_UNICODE_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")
_PRIVATE_KEY_MARKER = re.compile(
    r"-----BEGIN (?:(?:ENCRYPTED|RSA|EC|DSA|OPENSSH) )?PRIVATE KEY-----|"
    r"AGE-"
    r"SECRET-KEY-"
)
_OPAQUE_SECRET_REFERENCE = re.compile(
    r"(?i)(?:secret[_-]?(?:profile|reference)|reference):[A-Za-z0-9][A-Za-z0-9._/-]*"
)


def string_looks_like_private_key(value: str) -> bool:
    """Return whether *value* contains a private-key serialization marker."""

    return _PRIVATE_KEY_MARKER.search(value) is not None


def _mapping_pair_looks_like_credential(key: object, value: object) -> bool:
    if not isinstance(key, str) or not isinstance(value, str):
        return False
    return _credential_field_value_is_literal(key, value)


def _credential_field_value_is_literal(key: str, value: str) -> bool:
    normalized_key = re.sub(r"[-_]", "", key.casefold())
    if normalized_key not in _CREDENTIAL_FIELD_NAMES:
        return False
    candidate = _REFERENCE_PLACEHOLDER.sub("", value).strip()
    if not candidate or _OPAQUE_SECRET_REFERENCE.fullmatch(candidate):
        return False
    return not (
        normalized_key in {"authorization", "proxyauthorization"}
        and re.fullmatch(
            r"(?i)(?:fixture/.*|sha256:[0-9a-f]{64}|validated_record)",
            candidate,
        )
    )


def _first_matched_group(match: re.Match[str], *names: str) -> str:
    return next(value for name in names if (value := match.group(name)) is not None)


def _assignment_match_is_literal(match: re.Match[str]) -> bool:
    key = _first_matched_group(match, "double_key", "single_key", "bare_key")
    value = _first_matched_group(
        match,
        "double_value",
        "single_value",
        "bare_value",
    )
    if not _credential_field_value_is_literal(key, value):
        return False
    folded = value.casefold()
    if folded in {"bearer", "basic"}:
        return False
    if (
        match.group("bare_key") is None
        and match.group("bare_value") is not None
        and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value)
    ):
        return False
    return re.sub(r"[-_]", "", folded) != re.sub(r"[-_]", "", key.casefold())


def string_looks_like_credential(value: str) -> bool:
    """Return whether *value* contains literal credential material."""

    candidate = _JSON_UNICODE_ESCAPE.sub(
        lambda match: chr(int(match.group(1), 16)),
        value,
    )
    candidate = _REFERENCE_PLACEHOLDER.sub("", candidate)
    if (
        string_looks_like_private_key(candidate)
        or _PROVIDER_TOKEN.search(candidate) is not None
        or _AUTHORIZATION_SCHEME.search(candidate) is not None
        or _OPAQUE_AUTHORIZATION_HEADER.search(candidate) is not None
        or _BEARER_VALUE.search(candidate) is not None
        or _CREDENTIAL_QUERY.search(candidate) is not None
    ):
        return True
    return any(
        _assignment_match_is_literal(match)
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
            if any(
                _mapping_pair_looks_like_credential(key, member)
                for key, member in value.items()
            ):
                return True
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            identity = id(value)
            if identity in seen:
                continue
            seen.add(identity)
            pending.extend(value)
    return False
