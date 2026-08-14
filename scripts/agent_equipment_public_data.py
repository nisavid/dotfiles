"""Secret-free public-data policy shared by equipment validators and scans."""

from __future__ import annotations

import ast
import json
import re
import textwrap
import warnings
from collections.abc import Container, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib

__all__ = (
    "contains_literal_credential",
    "serialized_syntax",
    "string_looks_like_credential",
    "string_looks_like_private_key",
)


_PROVIDER_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9_]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"(?:AKIA|ASIA)[0-9A-Z]{16}|"
    r"sk-[A-Za-z0-9_-]{20,}|"
    r"pst_[A-Za-z0-9_-]{12,}::[A-Za-z0-9_-]{8,})(?![A-Za-z0-9_])"
)
_CREDENTIAL_ROLE_COMPONENTS = (
    ("personal", "access", "token"),
    ("secret", "access", "key"),
    ("access", "key", "id"),
    ("proxy", "authorization"),
    ("service", "role", "key"),
    ("enterprise", "token"),
    ("session", "token"),
    ("access", "token"),
    ("client", "secret"),
    ("secret", "key"),
    ("auth", "token"),
    ("api", "token"),
    ("bot", "token"),
    ("oauth", "token"),
    ("x", "api", "key"),
    ("api", "key"),
    ("authorization",),
    ("password",),
    ("secret",),
    ("token",),
    ("pat",),
)
_CREDENTIAL_ROLES = frozenset("".join(parts) for parts in _CREDENTIAL_ROLE_COMPONENTS)
_GENERIC_PROVIDER_ROLE_COMPONENTS = frozenset(
    {
        ("personal", "access", "token"),
        ("secret", "access", "key"),
        ("access", "key", "id"),
        ("client", "secret"),
        ("api", "key"),
        ("pat",),
    }
)
_NONLIVE_PROVIDER_PREFIXES = frozenset({"canary", "fake", "fixture", "mock", "test"})
_PUBLIC_CONTROL_COMPONENTS = frozenset({"compare", "compat", "compatibility"})
_PROVIDER_FAMILY_ALIASES = {
    "aws": "aws",
    "cloudflare": "cloudflare",
    "cookie": "cookie",
    "context7": "context7",
    "db": "database",
    "docker": "docker",
    "firecrawl": "firecrawl",
    "gh": "github",
    "github": "github",
    "greptile": "greptile",
    "hf": "huggingface",
    "huggingface": "huggingface",
    "jwt": "jwt",
    "npm": "npm",
    "postgres": "postgres",
    "postgresql": "postgres",
    "redis": "redis",
    "sentry": "sentry",
    "slack": "slack",
    "stripe": "stripe",
    "supabase": "supabase",
    "vercel": "vercel",
    "webhook": "webhook",
}
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?ix)(?<![A-Za-z0-9_-])"
    r'(?:(?:"(?P<double_key>[A-Za-z][A-Za-z0-9_.-]*)")|'
    r"(?:'(?P<single_key>[A-Za-z][A-Za-z0-9_.-]*)')|"
    r"(?P<bare_key>[A-Za-z][A-Za-z0-9_.-]*))"
    r"[ \t]*[:=][ \t]*"
    r'(?:(?:"(?P<double_value>(?:\\.|[^"\\])*)")|'
    r"(?:'(?P<single_value>(?:\\.|[^'\\])*)')|"
    r"(?P<bare_value>[A-Za-z0-9][A-Za-z0-9._~+/@:=-]*+))"
    r"(?=[ \t]*(?:[,;)}\]\r\n#]|//|$))"
)
_REFERENCE_ASSIGNMENT = re.compile(
    r"(?ix)(?<![A-Za-z0-9_-])"
    r'(?:(?:"(?P<double_key>[A-Za-z][A-Za-z0-9_.-]*)")|'
    r"(?:'(?P<single_key>[A-Za-z][A-Za-z0-9_.-]*)')|"
    r"(?P<bare_key>[A-Za-z][A-Za-z0-9_.-]*))"
    r"[ \t]*[:=][ \t]*"
    r'(?:(?:"(?P<double_value>(?:\\.|[^"\\])*)")|'
    r"(?:'(?P<single_value>(?:\\.|[^'\\])*)')|"
    r"(?P<bare_value>[A-Za-z0-9$\\{][A-Za-z0-9._~+/@:=${}\\-]*+))"
    r"""(?=[ \t]*(?:[,;)}\]\r\n#]|//|$)|['"][ \t]*(?:[,;)}\]\r\n#]|//|$))"""
)
_CROSS_LINE_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?ix)(?<![A-Za-z0-9_-])(?:"
    r'"(?P<cross_json_key>[A-Za-z][A-Za-z0-9_.-]*)"'
    r"[ \t]*:[ \t]*\r?\n[ \t]+"
    r'"(?P<cross_json_value>(?:\\.|[^"\\])*)"'
    r"|"
    r"(?P<cross_yaml_key>[A-Za-z][A-Za-z0-9_.-]*)"
    r"[ \t]*:[ \t]*\r?\n[ \t]+(?:"
    r'"(?P<cross_yaml_double>(?:\\.|[^"\\])*)"|'
    r"'(?P<cross_yaml_single>(?:\\.|[^'\\])*)'|"
    r"(?P<cross_yaml_bare>[A-Za-z0-9$][A-Za-z0-9._~+/@:=${}-]*)"
    r"))(?=[ \t]*(?:[,;)}\]\r\n#]|//|$))"
)
_YAML_BLOCK_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?ix)(?<![A-Za-z0-9_-])"
    r"(?P<block_key>[A-Za-z][A-Za-z0-9_.-]*)[ \t]*:[ \t]*"
    r"(?:[>|][+-]?[1-9]?|&[A-Za-z0-9_.-]+|!!str)"
    r"(?:[ \t]+|[ \t]*\r?\n[ \t]+)"
    r"(?P<block_value>[A-Za-z0-9][^\r\n#]*)"
)
_TOML_MULTILINE_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?ix)(?<![A-Za-z0-9_-])"
    r"(?P<toml_key>[A-Za-z][A-Za-z0-9_.-]*)[ \t]*=[ \t]*"
    r"(?P<toml_quote>\"\"\"|'\'\')"
    r"(?P<toml_value>.*?)"
    r"(?P=toml_quote)",
    re.DOTALL | re.IGNORECASE | re.VERBOSE,
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
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._~+/-]+)")
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
_JS_BRACED_UNICODE_ESCAPE = re.compile(r"\\u\{([0-9a-fA-F]{1,6})\}")
_PRIVATE_KEY_MARKER = re.compile(
    r"-----BEGIN (?:(?:ENCRYPTED|RSA|EC|DSA|OPENSSH) )?PRIVATE KEY-----|"
    r"-----BEGIN " + r"PGP PRIVATE KEY BLOCK-----|"
    r"-----BEGIN " + r"SSH2 ENCRYPTED PRIVATE KEY-----|"
    r"---- BEGIN " + r"SSH2 ENCRYPTED PRIVATE KEY ----|"
    r"PuTTY-User-" + r"Key-File-[0-9]+[ 	]*:|"
    r"AGE-"
    r"SECRET-KEY-"
)
_OPAQUE_SECRET_REFERENCE = re.compile(
    r"(?i)(?:secret[_-]?(?:profile|reference)|reference):"
    r"[A-Za-z][A-Za-z0-9_.-]*\Z"
)
_SECRET_PROVIDER_REFERENCE = re.compile(
    r"(?:pass://[A-Za-z0-9_.+-]+/[A-Za-z0-9_.@+-]+/[A-Za-z0-9_.+-]+|"
    r"secret-service://)\Z"
)
_SYMBOLIC_REFERENCE = re.compile(r"__[A-Z][A-Z0-9_]*__\Z")
_TEMPLATE_SOURCE_MARKER = "__AGENT_EQUIPMENT_TEMPLATE_SOURCE__"
_TEMPLATE_CONTROL_MARKER = "__AGENT_EQUIPMENT_TEMPLATE_CONTROL__"
_TEMPLATE_LOCAL_OUTPUT_MARKER = "__AGENT_EQUIPMENT_TEMPLATE_LOCAL_OUTPUT__"
_TEMPLATE_UNCERTAIN_OUTPUT_MARKER = "__AGENT_EQUIPMENT_TEMPLATE_OUTPUT__"
_TEMPLATE_OPENER = re.compile(r"\{\{|\{%|\{#")
_JAVASCRIPT_SUFFIXES = frozenset(
    {".cjs", ".cts", ".js", ".json", ".mjs", ".mts", ".ts"}
)
_JAVASCRIPT_CONSERVATIVE_SUFFIXES = frozenset({".jsx", ".tsx"})
_YAML_SUFFIXES = frozenset({".yaml", ".yml"})
_ASSIGNMENT_SUFFIXES = frozenset({".conf", ".env", ".toml"})
_TEMPLATE_SUFFIXES = frozenset(
    {".gotmpl", ".j2", ".jinja", ".jinja2", ".template", ".tmpl", ".tpl"}
)
_CAMEL_ACRONYM_BOUNDARY = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_WORD_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")


def serialized_syntax(relative: str) -> str | None:
    """Return the underlying bounded syntax for plain or templated source."""

    suffixes = [suffix.casefold() for suffix in Path(relative).suffixes]
    templated = any(suffix in _TEMPLATE_SUFFIXES for suffix in suffixes)
    suffixes = [suffix for suffix in suffixes if suffix not in _TEMPLATE_SUFFIXES]
    suffix = suffixes[-1] if suffixes else ""
    if suffix in _JAVASCRIPT_CONSERVATIVE_SUFFIXES:
        return (
            "javascript-conservative-template"
            if templated
            else "javascript-conservative"
        )
    if suffix in _JAVASCRIPT_SUFFIXES:
        if templated:
            return "javascript-template"
        return "javascript" if suffix != ".json" else None
    if suffix in _YAML_SUFFIXES:
        return "yaml-template" if templated else "yaml"
    if suffix in _ASSIGNMENT_SUFFIXES:
        return "toml-template" if templated else None
    return "template" if templated else None


def string_looks_like_private_key(value: str) -> bool:
    """Return whether *value* contains a private-key serialization marker."""

    return _PRIVATE_KEY_MARKER.search(value) is not None


def _mapping_pair_looks_like_credential(key: object, value: object) -> bool:
    if not isinstance(key, str) or not isinstance(value, str):
        return False
    return _credential_field_value_is_literal(key, value)


def _normalized_field_name(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.casefold())


def _field_components(key: str) -> tuple[str, ...]:
    separated = _CAMEL_ACRONYM_BOUNDARY.sub(r"\1_\2", key)
    separated = _CAMEL_WORD_BOUNDARY.sub(r"\1_\2", separated)
    return tuple(
        component.casefold()
        for component in re.split(r"[^A-Za-z0-9]+", separated)
        if component
    )


def _credential_field_identity(key: str) -> tuple[str | None, str] | None:
    folded_key = key.casefold()
    if any(
        marker.casefold() in folded_key
        for marker in (
            _TEMPLATE_SOURCE_MARKER,
            _TEMPLATE_UNCERTAIN_OUTPUT_MARKER,
        )
    ):
        return None, "templatedcredential"
    normalized = _normalized_field_name(key)
    components = _field_components(key)
    if (
        "reference" in components
        or components[:2] == ("secret", "profile")
        or _PUBLIC_CONTROL_COMPONENTS.intersection(components)
        or components[-1:] == ("identity",)
    ):
        return None
    if normalized in _CREDENTIAL_ROLES:
        return None, normalized
    for role_components in _CREDENTIAL_ROLE_COMPONENTS:
        size = len(role_components)
        role = "".join(role_components)
        if (
            len(components) > size
            and components[-size:] == role_components
            and components[0] not in _NONLIVE_PROVIDER_PREFIXES
            and (
                role_components in _GENERIC_PROVIDER_ROLE_COMPONENTS
                or any(
                    component in _PROVIDER_FAMILY_ALIASES
                    for component in components[:-size]
                )
            )
        ):
            return "".join(components[:-size]), role
        if len(components) > size and components[:size] == role_components:
            provider = "".join(components[size:])
            if provider in _PROVIDER_FAMILY_ALIASES:
                return _PROVIDER_FAMILY_ALIASES[provider], role
    for alias, provider in _PROVIDER_FAMILY_ALIASES.items():
        if normalized.startswith(alias):
            role = normalized[len(alias) :]
            if role in _CREDENTIAL_ROLES:
                return provider, role
        if normalized.endswith(alias):
            role = normalized[: -len(alias)]
            if role in _CREDENTIAL_ROLES:
                return provider, role
    return None


def _field_is_uppercase_name(key: str) -> bool:
    return re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is not None


def _reference_value_is_safe(value: str) -> bool:
    candidate = value.strip()
    if (
        not candidate
        or _TEMPLATE_LOCAL_OUTPUT_MARKER in candidate
        or _TEMPLATE_UNCERTAIN_OUTPUT_MARKER in candidate
        or string_looks_like_private_key(candidate)
        or _PROVIDER_TOKEN.search(candidate) is not None
    ):
        return False
    if (
        _REFERENCE_PLACEHOLDER.fullmatch(candidate)
        or _OPAQUE_SECRET_REFERENCE.fullmatch(candidate)
        or _SECRET_PROVIDER_REFERENCE.fullmatch(candidate)
        or _SYMBOLIC_REFERENCE.fullmatch(candidate)
    ):
        return True
    remainder = _REFERENCE_PLACEHOLDER.sub("", candidate)
    return bool(remainder != candidate and re.fullmatch(r"""[ \t'\"]*""", remainder))


def _credential_field_value_is_literal(key: str, value: str) -> bool:
    field_identity = _credential_field_identity(key)
    if field_identity is None:
        return False
    _, role = field_identity
    candidate = value.strip()
    if any(
        marker in candidate
        for marker in (
            _TEMPLATE_LOCAL_OUTPUT_MARKER,
            _TEMPLATE_UNCERTAIN_OUTPUT_MARKER,
        )
    ):
        return True
    if not candidate or _reference_value_is_safe(candidate):
        return False
    if candidate.casefold() in {"false", "none", "null", "true", "~"}:
        return False
    if role not in {"authorization", "proxyauthorization"}:
        return True
    if re.fullmatch(
        r"(?i)(?:fixture/.*|sha256:[0-9a-f]{64}|validated_record)",
        candidate,
    ):
        return False
    scheme = re.fullmatch(r"(?is)(?:bearer|basic)\s+(.+)", candidate)
    return scheme is None or not _reference_value_is_safe(scheme.group(1))


def _reference_template_is_safe(value: str) -> bool:
    candidate = value.strip()
    if (
        not candidate
        or string_looks_like_private_key(candidate)
        or _PROVIDER_TOKEN.search(candidate) is not None
    ):
        return False
    matches = tuple(_REFERENCE_PLACEHOLDER.finditer(candidate))
    if len(matches) != 1:
        return False
    match = matches[0]
    prefix = candidate[: match.start()].strip().casefold()
    suffix = candidate[match.end() :].strip()
    return prefix in {
        "",
        "'",
        '"',
        "authorization:bearer",
        "authorization:basic",
        "proxy-authorization:bearer",
        "proxy-authorization:basic",
    } and suffix in {"", "'", '"'}


def _structured_reference_is_safe(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    if set(value) == {"secret_profile_reference"}:
        profile = value.get("secret_profile_reference")
        return (
            isinstance(profile, str)
            and re.fullmatch(r"[a-z0-9][a-z0-9._-]*", profile) is not None
        )
    if set(value) != {"secret_reference", "template"}:
        return False
    reference = value.get("secret_reference")
    template = value.get("template")
    return (
        isinstance(reference, str)
        and re.fullmatch(r"[A-Z_][A-Z0-9_]*", reference) is not None
        and isinstance(template, str)
        and _reference_template_is_safe(template)
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
    return _normalized_field_name(folded) != _normalized_field_name(key)


def _assignment_match_has_safe_reference(match: re.Match[str]) -> bool:
    key = _first_matched_group(match, "double_key", "single_key", "bare_key")
    value = _first_matched_group(
        match,
        "double_value",
        "single_value",
        "bare_value",
    )
    return _credential_field_identity(key) is not None and _reference_value_is_safe(
        value
    )


def _without_safe_reference_assignments(value: str) -> str:
    spans = [
        match.span()
        for match in _REFERENCE_ASSIGNMENT.finditer(value)
        if _assignment_match_has_safe_reference(match)
    ]
    for start, end in reversed(spans):
        value = value[:start] + "{reference}" + value[end:]
    return value


def _reference_assignment_is_literal(match: re.Match[str]) -> bool:
    key = _first_matched_group(match, "double_key", "single_key", "bare_key")
    value = _first_matched_group(
        match,
        "double_value",
        "single_value",
        "bare_value",
    )
    field_identity = _credential_field_identity(key)
    if field_identity is None or not value.strip() or _reference_value_is_safe(value):
        return False
    _, role = field_identity
    if role in {"authorization", "proxyauthorization"} and re.fullmatch(
        r"(?i)(?:fixture/.*|sha256:[0-9a-f]{64}|validated_record)",
        value.strip(),
    ):
        return False
    return _normalized_field_name(value) != _normalized_field_name(key)


def _cross_line_assignment_is_literal(match: re.Match[str]) -> bool:
    key = _first_matched_group(match, "cross_json_key", "cross_yaml_key")
    value = _first_matched_group(
        match,
        "cross_json_value",
        "cross_yaml_double",
        "cross_yaml_single",
        "cross_yaml_bare",
    )
    if not _credential_field_value_is_literal(key, value):
        return False
    if value.casefold() in {"bearer", "basic"}:
        return False
    return _normalized_field_name(value) != _normalized_field_name(key)


def _structured_assignment_is_literal(key: str, value: str) -> bool:
    if not _credential_field_value_is_literal(key, value):
        return False
    return _normalized_field_name(value) != _normalized_field_name(key)


def _contains_credential_shaped_bearer_value(value: str) -> bool:
    for match in _BEARER_VALUE.finditer(value):
        token = match.group(1)
        if _PROVIDER_TOKEN.fullmatch(token) is not None:
            return True
        if re.fullmatch(
            r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
            token,
        ):
            return True
        if len(token) >= 20:
            return True
        if len(token) >= 16 and re.search(r"[0-9._~+/-]", token) is not None:
            return True
    return False


def _parsed_json_contains_literal_credential(value: str) -> bool:
    stripped = value.lstrip()
    if not stripped.startswith(("{", "[")):
        return False
    credential_occurrence = False

    def object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        nonlocal credential_occurrence
        credential_occurrence = credential_occurrence or any(
            contains_literal_credential({key: member}) for key, member in pairs
        )
        return dict(pairs)

    try:
        document, end = json.JSONDecoder(
            object_pairs_hook=object_from_pairs,
        ).raw_decode(stripped)
    except (TypeError, ValueError):
        return False
    if (
        not isinstance(document, (Mapping, list))
        or re.fullmatch(r"[\s,;)}\]]*", stripped[end:]) is None
    ):
        return False
    return credential_occurrence or contains_literal_credential(document)


def _parsed_toml_contains_literal_credential(value: str) -> bool:
    if "=" not in value:
        return False
    try:
        document = tomllib.loads(value)
    except tomllib.TOMLDecodeError:
        return False
    return contains_literal_credential(document)


def _parse_quoted_scalar(value: str) -> tuple[str, int] | None:
    if not value or value[0] not in {"'", '"'}:
        return None
    quote = value[0]
    decoded: list[str] = []
    index = 1
    while index < len(value):
        character = value[index]
        if quote == "'" and character == "'" and value[index : index + 2] == "''":
            decoded.append("'")
            index += 2
            continue
        if character == quote:
            raw = value[: index + 1]
            if quote == '"':
                try:
                    return str(json.loads(raw)), index + 1
                except (TypeError, ValueError):
                    return "".join(decoded), index + 1
            return "".join(decoded), index + 1
        if character == "\\" and index + 1 < len(value):
            marker = value[index + 1]
            if marker == "x" and re.fullmatch(
                r"[0-9a-fA-F]{2}", value[index + 2 : index + 4]
            ):
                decoded.append(chr(int(value[index + 2 : index + 4], 16)))
                index += 4
                continue
            if marker == "u" and value[index + 2 : index + 3] == "{":
                closing = value.find("}", index + 3)
                codepoint = value[index + 3 : closing] if closing >= 0 else ""
                if re.fullmatch(r"[0-9a-fA-F]{1,6}", codepoint):
                    ordinal = int(codepoint, 16)
                    if ordinal <= 0x10FFFF:
                        decoded.append(chr(ordinal))
                        index = closing + 1
                        continue
            if marker == "u" and re.fullmatch(
                r"[0-9a-fA-F]{4}", value[index + 2 : index + 6]
            ):
                decoded.append(chr(int(value[index + 2 : index + 6], 16)))
                index += 6
                continue
            if marker in "01234567":
                octal = re.match(r"[0-7]{1,3}", value[index + 1 : index + 4])
                assert octal is not None
                decoded.append(chr(int(octal.group(0), 8) & 0xFF))
                index += 1 + octal.end()
                continue
            escape_values = {
                "b": "\b",
                "f": "\f",
                "n": "\n",
                "r": "\r",
                "t": "\t",
                "v": "\v",
                "\\": "\\",
                '"': '"',
                "'": "'",
            }
            decoded.append(escape_values.get(marker, marker))
            index += 2
            continue
        decoded.append(character)
        index += 1
    return None


def _split_serialized_pair(
    value: str,
    *,
    separators: frozenset[str],
) -> tuple[str, str, str] | None:
    candidate = value.lstrip()
    if candidate.startswith("["):
        candidate = candidate[1:].lstrip()
    declaration = re.match(r"(?i)(?:export|const|let|var)[ \t]+", candidate)
    if declaration is not None:
        candidate = candidate[declaration.end() :]
    call = re.match(r"[A-Za-z_][A-Za-z0-9_.-]*[ \t]*\(", candidate)
    if call is not None:
        candidate = candidate[call.end() :].lstrip()

    if candidate.startswith(("'", '"')):
        parsed_key = _parse_quoted_scalar(candidate)
        if parsed_key is None:
            return None
        key, end = parsed_key
        remainder = candidate[end:].lstrip()
        if not remainder or remainder[0] not in separators:
            return None
        if remainder[1:].startswith(remainder[0]):
            return None
        return key, remainder[0], remainder[1:].lstrip()

    separator_indexes = tuple(
        index for index, character in enumerate(candidate) if character in separators
    )
    if not separator_indexes:
        return None
    separator_index = min(separator_indexes)
    key = candidate[:separator_index].strip()
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_. /-]*", key) is None:
        return None
    if candidate[separator_index + 1 :].startswith(candidate[separator_index]):
        return None
    return key, candidate[separator_index], candidate[separator_index + 1 :].lstrip()


def _strip_plain_scalar_tail(value: str) -> str:
    candidate = value.rstrip()
    next_mapping = re.search(r",[ \t]+[A-Za-z_][A-Za-z0-9_.-]*[ \t]*:", candidate)
    if next_mapping is not None:
        candidate = candidate[: next_mapping.start()].rstrip()
    comment = re.search(r"[ \t]+#", candidate)
    if comment is not None:
        candidate = candidate[: comment.start()].rstrip()
    candidate = re.sub(r"[ \t]+//.*\Z", "", candidate).rstrip()
    return re.sub(r"[;,]+\Z", "", candidate).rstrip()


def _serialized_scalar(value: str) -> tuple[str, bool] | None:
    if not value:
        return None
    if value.startswith(("'", '"')):
        parsed = _parse_quoted_scalar(value)
        if parsed is None:
            return None
        scalar, end = parsed
        tail = value[end:].strip()
        if tail and re.fullmatch(r"(?:[,;)}\]][ \t]*)*(?:(?:#|//).*)?", tail) is None:
            return None
        return scalar, True
    scalar = _strip_plain_scalar_tail(value)
    while scalar:
        unmatched_wrapper = next(
            (
                (opening, closing)
                for opening, closing in (("(", ")"), ("[", "]"), ("{", "}"))
                if scalar.endswith(closing)
                and scalar.count(opening) < scalar.count(closing)
            ),
            None,
        )
        if unmatched_wrapper is None:
            break
        scalar = scalar[:-1].rstrip()
    scalar = _strip_plain_scalar_tail(scalar)
    return (scalar, False) if scalar else None


def _serialized_scalar_is_source_expression(value: str, *, key: str) -> bool:
    candidate = value.strip()
    folded = candidate.casefold()
    if candidate.startswith(("$(", "`")):
        return True
    if folded in {
        "any",
        "basic",
        "bearer",
        "bool",
        "bytes",
        "dict",
        "float",
        "int",
        "list",
        "none",
        "object",
        "optional",
        "str",
        "string",
        "tuple",
    }:
        return True
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", candidate) and (
        "_" in candidate
        or candidate.casefold() in {"identity", "option", "shift", "value"}
    ):
        return True
    return not _field_is_uppercase_name(key) and bool(
        re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*\[[^\]]+\]", candidate)
        or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*\([^\r\n]*\)", candidate)
        or re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+",
            candidate,
        )
    )


def _inline_assignments_contain_literal_credential(value: str) -> bool:
    for line in value.splitlines() or [value]:
        pair = _split_serialized_pair(line, separators=frozenset({"="}))
        if pair is None:
            continue
        key, _, raw_value = pair
        scalar = _serialized_scalar(raw_value)
        if scalar is None:
            continue
        member, quoted = scalar
        if not quoted and _serialized_scalar_is_source_expression(member, key=key):
            continue
        if _structured_assignment_is_literal(key, member):
            return True
    return False


def _strip_yaml_node_properties(value: str) -> str:
    candidate = value.lstrip()
    while candidate.startswith(("&", "!")):
        if candidate.startswith("!<"):
            end = candidate.find(">")
            if end < 0:
                return candidate
            candidate = candidate[end + 1 :].lstrip()
            continue
        match = re.match(r"(?:&[A-Za-z0-9_.-]+|!!?[A-Za-z0-9_./:-]+)", candidate)
        if match is None:
            return candidate
        candidate = candidate[match.end() :].lstrip()
    return candidate


def _yaml_block_header(value: str) -> re.Match[str] | None:
    return re.fullmatch(
        r"(?P<style>[|>])(?:(?P<first>[1-9]|[+-])(?P<second>[1-9]|[+-])?)?"
        r"(?:[ \t]+#.*)?",
        value,
    )


def _yaml_indent(line: str) -> int | None:
    prefix = line[: len(line) - len(line.lstrip(" \t"))]
    return None if "\t" in prefix else len(prefix)


def _yaml_block_value(
    lines: list[str],
    start: int,
    parent_indent: int,
) -> tuple[str, int]:
    content: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index]
        indent = _yaml_indent(line)
        if line.strip() and (indent is None or indent <= parent_indent):
            break
        content.append(line)
        index += 1
    nonblank_indents = [
        indent
        for line in content
        if line.strip() and (indent := _yaml_indent(line)) is not None
    ]
    content_indent = min(nonblank_indents, default=parent_indent + 1)
    return (
        "\n".join(line[content_indent:] if line.strip() else "" for line in content),
        index,
    )


def _yaml_scalar(value: str) -> tuple[str, bool] | None:
    candidate = _strip_yaml_node_properties(value)
    if not candidate:
        return None
    return _serialized_scalar(candidate)


def _yaml_assignments_contain_literal_credential(value: str) -> bool:
    lines = value.splitlines()
    credential_contexts: list[tuple[int, str]] = []
    explicit_key: tuple[int, str] | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        indent = _yaml_indent(line)
        if indent is None:
            index += 1
            continue
        stripped = line[indent:]
        while credential_contexts and indent <= credential_contexts[-1][0]:
            credential_contexts.pop()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue

        if stripped.startswith("? "):
            parsed_key = _yaml_scalar(stripped[2:].strip())
            if parsed_key is not None:
                explicit_key = (indent, parsed_key[0])
            index += 1
            continue
        if stripped.startswith(":") and explicit_key == (
            indent,
            explicit_key[1] if explicit_key else "",
        ):
            key = explicit_key[1]
            raw_value = stripped[1:].lstrip()
            explicit_key = None
        else:
            mapping_source = stripped
            if mapping_source.startswith("- "):
                mapping_source = mapping_source[2:].lstrip()
            mapping_source = _strip_yaml_node_properties(mapping_source)
            pair = _split_serialized_pair(
                mapping_source,
                separators=frozenset({":"}),
            )
            if pair is None:
                if credential_contexts and _field_is_uppercase_name(
                    credential_contexts[-1][1]
                ):
                    scalar = _yaml_scalar(stripped)
                    if (
                        scalar is not None
                        and not _serialized_scalar_is_source_expression(
                            scalar[0], key=credential_contexts[-1][1]
                        )
                    ):
                        return True
                index += 1
                continue
            key, _, raw_value = pair

        candidate = _strip_yaml_node_properties(raw_value)
        header = _yaml_block_header(candidate)
        if header is not None:
            block_value, index = _yaml_block_value(lines, index + 1, indent)
            contextual_key = credential_contexts[-1][1] if credential_contexts else key
            if _structured_assignment_is_literal(contextual_key, block_value):
                return True
            continue

        scalar = _yaml_scalar(raw_value)
        contextual_key = credential_contexts[-1][1] if credential_contexts else key
        if scalar is not None:
            member, quoted = scalar
            if (
                quoted
                or not _serialized_scalar_is_source_expression(
                    member,
                    key=contextual_key,
                )
            ) and _structured_assignment_is_literal(contextual_key, member):
                return True
        elif _credential_field_identity(key) is not None:
            credential_contexts.append((indent, key))
        index += 1
    return False


_AUTHORIZATION_VALUE = re.compile(
    r"(?im)(?<![A-Za-z0-9_-])"
    r"(?P<key>authorization|proxy-authorization)[ \t]*[:=][ \t]*"
    r"(?P<value>[^\r\n]+)"
)
_QUERY_CREDENTIAL_VALUE = re.compile(
    r"(?i)[?&](?P<key>x-api-key|api[_-]?key|access[_-]?token|token|secret|"
    r"password|client[_-]?secret)=(?P<value>[^&#\s]*)"
)


def _direct_context_contains_literal_credential(value: str) -> bool:
    for match in _AUTHORIZATION_VALUE.finditer(value):
        raw_value = match.group("value").strip()
        scheme = re.match(r"(?i)(?:bearer|basic|digest)\s+", raw_value)
        if scheme is None and re.search(r"[ \t]", raw_value) is not None:
            continue
        if scheme is not None:
            payload = raw_value[scheme.end() :]
            reference = _REFERENCE_PLACEHOLDER.match(payload)
            if reference is not None:
                tail = payload[reference.end() :]
                if tail.startswith(("'", '"')) or re.fullmatch(
                    r"""[,;}\]]*(?:[ \t]+(?:and|or)\b.*)?""", tail
                ):
                    continue
        for _ in range(2):
            scalar = _serialized_scalar(raw_value)
            if scalar is not None:
                raw_value = scalar[0]
            raw_value = re.sub(r"""["'][ \t]*\Z""", "", raw_value)
        if _serialized_scalar_is_source_expression(raw_value, key=match.group("key")):
            continue
        if _credential_field_value_is_literal(match.group("key"), raw_value):
            return True
    for match in _QUERY_CREDENTIAL_VALUE.finditer(value):
        raw_value = re.sub(r"""["',;\]]*[ \t]*\Z""", "", match.group("value"))
        if _credential_field_value_is_literal(match.group("key"), raw_value):
            return True
    return False


def _python_assignment_key(target: ast.expr) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        prefix = _python_assignment_key(target.value)
        return f"{prefix}.{target.attr}" if prefix is not None else target.attr
    if isinstance(target, ast.Subscript):
        try:
            key = ast.literal_eval(target.slice)
        except (TypeError, ValueError):
            return None
        return key if isinstance(key, str) else None
    return None


def _parsed_python_credential_result(value: str) -> bool | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(textwrap.dedent(value))
    except (IndentationError, SyntaxError, ValueError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            try:
                document = ast.literal_eval(node)
            except (TypeError, ValueError):
                pass
            else:
                if contains_literal_credential(document):
                    return True
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if (
                    keyword.arg is None
                    or _credential_field_identity(keyword.arg) is None
                ):
                    continue
                try:
                    member = ast.literal_eval(keyword.value)
                except (TypeError, ValueError):
                    continue
                if isinstance(member, str) and _credential_field_value_is_literal(
                    keyword.arg, member
                ):
                    return True
        if isinstance(node, ast.Assign):
            assignments = tuple((target, node.value) for target in node.targets)
        elif isinstance(node, ast.AnnAssign):
            key = _python_assignment_key(node.target)
            if key is not None and _credential_field_identity(key) is not None:
                if _field_is_uppercase_name(key):
                    return None
                if isinstance(
                    node.annotation, ast.Name
                ) and node.annotation.id.casefold() in {
                    "any",
                    "bool",
                    "bytes",
                    "dict",
                    "float",
                    "int",
                    "list",
                    "object",
                    "str",
                    "string",
                    "tuple",
                }:
                    return False
                if isinstance(node.annotation, (ast.Attribute, ast.Subscript)):
                    return False
                return None
            assignments = ((node.target, node.value),) if node.value is not None else ()
        else:
            continue
        for target, assigned in assignments:
            key = _python_assignment_key(target)
            if key is None or _credential_field_identity(key) is None:
                continue
            try:
                member = ast.literal_eval(assigned)
            except (TypeError, ValueError):
                if isinstance(assigned, ast.Name):
                    return _credential_field_value_is_literal(key, assigned.id)
                if isinstance(assigned, (ast.List, ast.Tuple)) and all(
                    isinstance(
                        member, (ast.Attribute, ast.Call, ast.Name, ast.Subscript)
                    )
                    for member in assigned.elts
                ):
                    continue
                if (
                    _field_is_uppercase_name(key)
                    and isinstance(assigned, ast.Call)
                    and isinstance(assigned.func, ast.Name)
                ):
                    return True
                if isinstance(assigned, (ast.Attribute, ast.Call, ast.Subscript)):
                    continue
                if isinstance(assigned, ast.BinOp) and any(
                    isinstance(member, ast.Constant) and isinstance(member.value, str)
                    for member in ast.walk(assigned)
                ):
                    continue
                return True
            if isinstance(member, str):
                if _credential_field_value_is_literal(key, member):
                    return True
            elif contains_literal_credential({key: member}):
                return True
    return False


def _parse_backtick_scalar(value: str) -> tuple[str, int] | None:
    if not value.startswith("`"):
        return None
    decoded: list[str] = []
    index = 1
    while index < len(value):
        character = value[index]
        if character == "`":
            return "".join(decoded), index + 1
        if character == "\\" and index + 1 < len(value):
            decoded.append(value[index + 1])
            index += 2
            continue
        decoded.append(character)
        index += 1
    return None


def _parse_serialized_string(value: str, start: int) -> tuple[str, int] | None:
    if value[start : start + 1] == "`":
        parsed = _parse_backtick_scalar(value[start:])
    else:
        parsed = _parse_quoted_scalar(value[start:])
    return (parsed[0], start + parsed[1]) if parsed is not None else None


def _balanced_serialized_segment(
    value: str,
    start: int,
) -> tuple[str, int] | None:
    opening = value[start : start + 1]
    pairs = {"(": ")", "[": "]", "{": "}"}
    if opening not in pairs:
        return None
    stack = [opening]
    index = start + 1
    while index < len(value):
        if value[index : index + 2] == "/*":
            closing = value.find("*/", index + 2)
            if closing < 0:
                return None
            index = closing + 2
            continue
        character = value[index]
        if character in {"'", '"', "`"}:
            parsed = _parse_serialized_string(value, index)
            if parsed is None:
                return None
            _, index = parsed
            continue
        if character in pairs:
            stack.append(character)
        elif character in pairs.values():
            if not stack or pairs[stack[-1]] != character:
                return None
            stack.pop()
            if not stack:
                return value[start : index + 1], index + 1
        index += 1
    return None


def _inline_reference_object(value: str) -> object | None:
    candidate = _without_serialized_comments(value).strip()
    if not candidate.startswith("{") or not candidate.endswith("}"):
        return None
    body = candidate[1:-1]
    segments: list[str] = []
    start = 0
    stack: list[str] = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    index = 0
    while index < len(body):
        if body[index : index + 2] == "/*":
            closing = body.find("*/", index + 2)
            if closing < 0:
                return None
            index = closing + 2
            continue
        if body[index] in {"'", '"', "`"}:
            parsed = _parse_serialized_string(body, index)
            if parsed is None:
                return None
            _, index = parsed
            continue
        if body[index] in pairs:
            stack.append(body[index])
        elif body[index] in pairs.values():
            if not stack or pairs[stack[-1]] != body[index]:
                return None
            stack.pop()
        elif body[index] == "," and not stack:
            segments.append(body[start:index])
            start = index + 1
        index += 1
    segments.append(body[start:])

    document: dict[str, str] = {}
    member_pattern = re.compile(
        r"(?s)\s*(?P<key>"
        r'"(?:\\.|[^"\\])*"|'
        r"'(?:''|[^'])*'|"
        r"[A-Za-z_$][A-Za-z0-9_$.-]*"
        r")"
        r"\s*:\s*(?P<value>.*?)\s*"
    )
    for segment in segments:
        match = member_pattern.fullmatch(segment)
        if match is None:
            return None
        raw_key = match.group("key")
        parsed_key = _parse_serialized_string(raw_key, 0)
        key = parsed_key[0] if parsed_key is not None else raw_key
        if (
            parsed_key is not None and parsed_key[1] != len(raw_key)
        ) or key in document:
            return None
        raw_value = match.group("value")
        parsed = _parse_serialized_string(raw_value, 0)
        if parsed is not None and parsed[1] == len(raw_value):
            member = parsed[0]
        elif re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_.$-]*", raw_value):
            member = raw_value
        else:
            return None
        document[key] = member
    return document


def _without_serialized_comments(value: str) -> str:
    rendered: list[str] = []
    index = 0
    while index < len(value):
        if value[index : index + 2] == "/*":
            closing = value.find("*/", index + 2)
            if closing < 0:
                return ""
            rendered.append(" ")
            index = closing + 2
            continue
        if value[index : index + 2] == "//" or value[index] == "#":
            newline = value.find("\n", index + 1)
            if newline < 0:
                break
            rendered.append("\n")
            index = newline + 1
            continue
        if value[index] in {"'", '"', "`"}:
            parsed = _parse_serialized_string(value, index)
            if parsed is None:
                return ""
            rendered.append(value[index : parsed[1]])
            _, index = parsed
            continue
        rendered.append(value[index])
        index += 1
    return "".join(rendered)


def _serialized_composite_is_safe_reference(value: str) -> bool:
    for loader in (json.loads, ast.literal_eval):
        try:
            document = loader(value)
        except (SyntaxError, TypeError, ValueError):
            continue
        return _structured_reference_is_safe(document)
    return _structured_reference_is_safe(_inline_reference_object(value))


def _expression_literals_and_skeleton(value: str) -> tuple[tuple[str, ...], str]:
    literals: list[str] = []
    skeleton: list[str] = []
    index = 0
    while index < len(value):
        if value[index : index + 2] == "/*":
            closing = value.find("*/", index + 2)
            if closing < 0:
                return tuple(literals), "".join(skeleton)
            skeleton.append(" ")
            index = closing + 2
            continue
        if value[index : index + 2] == "//" and (
            index == 0 or value[index - 1].isspace()
        ):
            break
        if value[index] in {"'", '"', "`"}:
            parsed = _parse_serialized_string(value, index)
            if parsed is None:
                return tuple(literals), "".join(skeleton)
            literal, index = parsed
            literals.append(literal)
            skeleton.append('""')
            continue
        skeleton.append(value[index])
        index += 1
    return tuple(literals), "".join(skeleton).strip()


def _javascript_known_source_expression_symbols(
    value: str,
    *,
    key: str,
    literals: tuple[str, ...],
) -> frozenset[str] | None:
    parts = re.split(r"\s*(?:\?\?|\|\||&&)\s*", value.strip())
    if not parts or any(
        re.fullmatch(
            r"(?:[A-Za-z_$][A-Za-z0-9_$]*|false|null|true|undefined|\"\"|'')",
            fallback,
        )
        is None
        for fallback in parts[1:]
    ):
        return None
    source = parts[0]
    member = re.fullmatch(
        r"(?P<root>process|Bun)(?:\.|\?\.)env"
        r"(?:(?:\.|\?\.)(?P<field>[A-Za-z_$][A-Za-z0-9_$]*)|"
        r"\[\s*\"\"\s*\])",
        source,
    )
    if member is not None:
        field = member.group("field")
        source_literal_count = 0 if field is not None else 1
        source_is_safe = (
            field is not None and _credential_field_identity(field) is not None
        ) or (
            field is None
            and bool(literals)
            and _credential_field_identity(literals[0]) is not None
        )
    else:
        getter = re.fullmatch(
            r"(?:(?P<root>Deno|os)(?:\.|\?\.)env(?:\.|\?\.)get|"
            r"(?P<function>getenv))\(\s*\"\"\s*\)",
            source,
        )
        if (
            getter is None
            or not literals
            or (
                _credential_field_identity(literals[0]) is None
                and not _field_is_uppercase_name(literals[0])
            )
        ):
            return None
        source_literal_count = 1
        binding = getter.group("root") or getter.group("function")
        source_is_safe = True
    if not source_is_safe or not all(
        not literal
        or _reference_value_is_safe(literal)
        or _normalized_field_name(literal) == _normalized_field_name(key)
        for literal in literals[source_literal_count:]
    ):
        return None
    source_symbol = member.group("root") if member is not None else binding
    symbols = {source_symbol}
    symbols.update(
        fallback
        for fallback in parts[1:]
        if fallback not in {"false", "null", "true", '""', "''"}
    )
    return frozenset(symbols)


def _javascript_known_source_expression_is_safe(
    value: str,
    *,
    key: str,
    literals: tuple[str, ...],
    local_bindings: Container[str],
) -> bool:
    symbols = _javascript_known_source_expression_symbols(
        value,
        key=key,
        literals=literals,
    )
    return symbols is not None and all(
        symbol not in local_bindings for symbol in symbols
    )


@dataclass(frozen=True)
class _JavaScriptToken:
    kind: str
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class _JavaScriptLexicalIndex:
    tokens: tuple[_JavaScriptToken, ...]
    delimiter_mates: tuple[int, ...]
    opaque_spans: tuple[tuple[int, int, str], ...]
    nonvalue_colons: frozenset[int]
    ignored_symbol_positions: frozenset[int]
    typed_assignment_members: tuple[tuple[str, int], ...]
    source_proofs_valid: bool
    analysis_exhausted: bool
    work_units: int

    def colon_is_definitely_nonvalue(self, position: int) -> bool:
        return position in self.nonvalue_colons


_JAVASCRIPT_PREFIX_KEYWORDS = frozenset(
    {
        "await",
        "case",
        "const",
        "delete",
        "do",
        "else",
        "export",
        "extends",
        "in",
        "import",
        "instanceof",
        "let",
        "new",
        "of",
        "return",
        "throw",
        "typeof",
        "var",
        "void",
        "yield",
    }
)
_JAVASCRIPT_MULTI_CHARACTER_TOKENS = (
    ">>>=",
    "===",
    "!==",
    "**=",
    "&&=",
    "||=",
    "??=",
    ">>>",
    "...",
    "=>",
    "==",
    "!=",
    "<=",
    ">=",
    "++",
    "--",
    "&&",
    "||",
    "??",
    "?.",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "**",
    "<<",
    ">>",
)
_JAVASCRIPT_ASSIGNMENT_TOKENS = frozenset(
    {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "&&=", "||=", "??=", "**="}
)


def _javascript_identifier_start(character: str) -> bool:
    return character == "_" or character == "$" or character.isalpha()


def _javascript_identifier_part(character: str) -> bool:
    return _javascript_identifier_start(character) or character.isdigit()


def _javascript_regex_literal_end(value: str, start: int) -> int | None:
    index = start + 1
    in_character_class = False
    while index < len(value) and value[index] not in "\r\n":
        if value[index] == "\\":
            index += 2
            continue
        if value[index] == "[":
            in_character_class = True
        elif value[index] == "]":
            in_character_class = False
        elif value[index] == "/" and not in_character_class:
            index += 1
            while index < len(value) and _javascript_identifier_part(value[index]):
                index += 1
            return index
        index += 1
    return None


def _javascript_token_can_end_expression(token: _JavaScriptToken) -> bool:
    if token.kind in {"number", "regex", "string"}:
        return True
    if token.kind == "identifier":
        return token.text not in _JAVASCRIPT_PREFIX_KEYWORDS
    return token.text in {")", "]", "}", "++", "--"}


def _lex_javascript(
    value: str,
) -> tuple[
    tuple[_JavaScriptToken, ...],
    tuple[tuple[int, int, str], ...],
    tuple[tuple[int, int], ...],
]:
    tokens: list[_JavaScriptToken] = []
    opaque_spans: list[tuple[int, int, str]] = []
    uncertain_spans: list[tuple[int, int]] = []
    frames: list[dict[str, int | str]] = [{"kind": "code", "depth": 0}]
    parenthesis_controls: list[bool] = []
    index = 0
    can_end_expression = False

    def add_token(kind: str, text: str, start: int, end: int) -> None:
        nonlocal can_end_expression
        token = _JavaScriptToken(kind, text, start, end)
        tokens.append(token)
        can_end_expression = _javascript_token_can_end_expression(token)

    while index < len(value):
        frame = frames[-1]
        if frame["kind"] == "template":
            quasi_start = int(frame["quasi_start"])
            if value[index] == "\\":
                index = min(len(value), index + 2)
                continue
            if value[index] == "`":
                opaque_spans.append((quasi_start, index + 1, "string"))
                frames.pop()
                add_token("string", "`", quasi_start, index + 1)
                index += 1
                continue
            if value[index : index + 2] == "${":
                opaque_spans.append((quasi_start, index + 1, "string"))
                add_token("punctuation", "{", index + 1, index + 2)
                frames.append({"kind": "code", "depth": 1})
                index += 2
                continue
            index += 1
            continue

        if value[index].isspace():
            index += 1
            continue
        if value[index : index + 2] == "/*":
            closing = value.find("*/", index + 2)
            end = len(value) if closing < 0 else closing + 2
            opaque_spans.append((index, end, "comment"))
            if closing < 0:
                uncertain_spans.append((index, end))
            index = end
            continue
        if value[index : index + 2] == "//":
            newline = value.find("\n", index + 2)
            end = len(value) if newline < 0 else newline + 1
            opaque_spans.append((index, end, "comment"))
            index = end
            continue
        character = value[index]
        if character == "\\":
            unicode_escape = re.match(
                r"\\u(?:\{[0-9a-fA-F]{1,6}\}|[0-9a-fA-F]{4})",
                value[index:],
            )
            if unicode_escape is not None:
                end = index + unicode_escape.end()
                uncertain_spans.append((0, len(value)))
                add_token("punctuation", value[index:end], index, end)
                index = end
                continue
        if character in {"'", '"'}:
            parsed = _parse_serialized_string(value, index)
            end = len(value) if parsed is None else parsed[1]
            opaque_spans.append((index, end, "string"))
            if parsed is None:
                uncertain_spans.append((index, end))
            add_token("string", character, index, end)
            index = end
            continue
        if character == "`":
            frames.append({"kind": "template", "quasi_start": index})
            index += 1
            continue
        if character == "/" and not can_end_expression:
            regex_end = _javascript_regex_literal_end(value, index)
            if regex_end is not None:
                opaque_spans.append((index, regex_end, "regex"))
                add_token("regex", "/", index, regex_end)
                index = regex_end
                continue
        if _javascript_identifier_start(character):
            end = index + 1
            while end < len(value) and _javascript_identifier_part(value[end]):
                end += 1
            add_token("identifier", value[index:end], index, end)
            index = end
            continue
        if character.isdigit():
            end = index + 1
            while end < len(value) and (
                _javascript_identifier_part(value[end]) or value[end] in {".", "_"}
            ):
                end += 1
            add_token("number", value[index:end], index, end)
            index = end
            continue
        token_text = next(
            (
                candidate
                for candidate in _JAVASCRIPT_MULTI_CHARACTER_TOKENS
                if value.startswith(candidate, index)
            ),
            character,
        )
        previous_token = tokens[-1] if tokens else None
        add_token("punctuation", token_text, index, index + len(token_text))
        if token_text == "(":
            is_control = previous_token is not None and previous_token.text in {
                "catch",
                "for",
                "if",
                "switch",
                "while",
                "with",
            }
            if (
                previous_token is not None
                and previous_token.text == "await"
                and len(tokens) >= 3
            ):
                is_control = tokens[-3].text == "for"
            parenthesis_controls.append(is_control)
        elif token_text == ")" and parenthesis_controls:
            if parenthesis_controls.pop():
                can_end_expression = False
        if frames[-1]["depth"]:
            if character == "{":
                frames[-1]["depth"] = int(frames[-1]["depth"]) + 1
            elif character == "}":
                frames[-1]["depth"] = int(frames[-1]["depth"]) - 1
                if not frames[-1]["depth"]:
                    frames.pop()
                    if frames and frames[-1]["kind"] == "template":
                        frames[-1]["quasi_start"] = index + 1
        index += len(token_text)

    for frame in frames[1:]:
        start = int(frame.get("quasi_start", 0))
        uncertain_spans.append((start, len(value)))
        if frame["kind"] == "template":
            opaque_spans.append((start, len(value), "string"))
    return (
        tuple(tokens),
        tuple(sorted(opaque_spans, key=lambda span: (span[0], span[1]))),
        tuple(uncertain_spans),
    )


def _javascript_delimiter_mates(
    tokens: tuple[_JavaScriptToken, ...],
) -> tuple[tuple[int, ...], tuple[tuple[int, int], ...]]:
    mates = [-1] * len(tokens)
    uncertain: list[tuple[int, int]] = []
    stack: list[int] = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    openings = frozenset(pairs)
    closings = frozenset(pairs.values())
    for token_index, token in enumerate(tokens):
        if token.text in openings:
            stack.append(token_index)
        elif token.text in closings:
            if not stack or pairs[tokens[stack[-1]].text] != token.text:
                uncertain.append((0, tokens[-1].end if tokens else token.end))
                continue
            opening = stack.pop()
            mates[opening] = token_index
            mates[token_index] = opening
    uncertain.extend((tokens[index].start, tokens[-1].end) for index in stack)
    return tuple(mates), tuple(uncertain)


def _javascript_statement_can_end(token: _JavaScriptToken) -> bool:
    if token.kind in {"identifier", "number", "regex", "string"}:
        return token.text not in {
            "await",
            "case",
            "const",
            "delete",
            "export",
            "extends",
            "import",
            "in",
            "instanceof",
            "let",
            "new",
            "of",
            "return",
            "throw",
            "type",
            "typeof",
            "var",
            "void",
            "yield",
        }
    return token.text in {")", "]", "}", "++", "--"}


def _javascript_statement_can_start(token: _JavaScriptToken) -> bool:
    if token.text in {
        ".",
        "?.",
        ",",
        ":",
        ";",
        "?",
        ")",
        "]",
        "}",
        "&&",
        "||",
        "??",
        "else",
        "catch",
        "finally",
        "from",
        "as",
        "satisfies",
    }:
        return False
    return token.text not in _JAVASCRIPT_ASSIGNMENT_TOKENS and token.text not in {
        "+",
        "-",
        "*",
        "/",
        "%",
        "&",
        "|",
        "^",
        "<",
        ">",
        "<=",
        ">=",
        "==",
        "===",
        "!=",
        "!==",
    }


def _javascript_statement_bounds(
    value: str,
    tokens: tuple[_JavaScriptToken, ...],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    starts = list(range(len(tokens)))
    ends = [index + 1 for index in range(len(tokens))]
    frames: list[dict[str, object]] = [{"indices": [], "group_depth": 0}]

    def finish(frame: dict[str, object], end: int) -> None:
        indices = frame["indices"]
        assert isinstance(indices, list)
        if not indices:
            return
        start = indices[0]
        for token_index in indices:
            starts[token_index] = start
            ends[token_index] = end
        indices.clear()

    previous_end = 0
    for token_index, token in enumerate(tokens):
        if token.text == "}":
            if len(frames) > 1:
                finish(frames[-1], token_index)
                frames.pop()
            frame = frames[-1]
            indices = frame["indices"]
            assert isinstance(indices, list)
            indices.append(token_index)
            previous_end = token.end
            continue

        frame = frames[-1]
        indices = frame["indices"]
        group_depth = frame["group_depth"]
        assert isinstance(indices, list)
        assert isinstance(group_depth, int)
        if (
            indices
            and group_depth == 0
            and "\n" in value[previous_end : token.start]
            and _javascript_statement_can_end(tokens[indices[-1]])
            and _javascript_statement_can_start(token)
        ):
            finish(frame, token_index)
        indices.append(token_index)
        if token.text in {"(", "["}:
            frame["group_depth"] = group_depth + 1
        elif token.text in {")", "]"} and group_depth:
            frame["group_depth"] = group_depth - 1
        elif token.text == ";" and group_depth == 0:
            finish(frame, token_index + 1)
        if token.text == "{":
            frames.append({"indices": [], "group_depth": 0})
        previous_end = token.end

    for frame in reversed(frames):
        finish(frame, len(tokens))
    return tuple(starts), tuple(ends)


def _javascript_top_level_segments(
    tokens: tuple[_JavaScriptToken, ...],
    mates: tuple[int, ...],
    start: int,
    end: int,
) -> tuple[tuple[int, int], ...]:
    segments: list[tuple[int, int]] = []
    segment_start = start
    index = start
    while index < end:
        if tokens[index].text in {"(", "[", "{"} and 0 <= mates[index] < end:
            index = mates[index] + 1
            continue
        if tokens[index].text == ",":
            segments.append((segment_start, index))
            segment_start = index + 1
        index += 1
    segments.append((segment_start, end))
    return tuple(segments)


def _javascript_top_level_token(
    tokens: tuple[_JavaScriptToken, ...],
    mates: tuple[int, ...],
    start: int,
    end: int,
    values: frozenset[str],
) -> int | None:
    index = start
    while index < end:
        if tokens[index].text in {"(", "[", "{"} and 0 <= mates[index] < end:
            index = mates[index] + 1
            continue
        if tokens[index].text in values:
            return index
        index += 1
    return None


def _javascript_binding_pattern_names(
    tokens: tuple[_JavaScriptToken, ...],
    mates: tuple[int, ...],
    start: int,
) -> tuple[frozenset[str], int]:
    if start >= len(tokens):
        return frozenset(), start
    while start < len(tokens) and tokens[start].text == "...":
        start += 1
    if start >= len(tokens):
        return frozenset(), start
    outer = tokens[start]
    outer_end = (
        mates[start] + 1
        if outer.text in {"{", "["} and mates[start] >= 0
        else start + 1
    )
    pending = [start]
    names: set[str] = set()
    while pending:
        pattern_start = pending.pop()
        if pattern_start >= len(tokens):
            continue
        token = tokens[pattern_start]
        if token.kind == "identifier":
            names.add(token.text)
            continue
        if token.text not in {"{", "["} or mates[pattern_start] < 0:
            continue
        close = mates[pattern_start]
        for segment_start, segment_end in _javascript_top_level_segments(
            tokens,
            mates,
            pattern_start + 1,
            close,
        ):
            while segment_start < segment_end and tokens[segment_start].text == "...":
                segment_start += 1
            if segment_start >= segment_end:
                continue
            default = _javascript_top_level_token(
                tokens,
                mates,
                segment_start,
                segment_end,
                frozenset({"="}),
            )
            pattern_end = default if default is not None else segment_end
            if token.text == "{":
                separator = _javascript_top_level_token(
                    tokens,
                    mates,
                    segment_start,
                    pattern_end,
                    frozenset({":"}),
                )
                if separator is not None:
                    pending.append(separator + 1)
                elif tokens[segment_start].kind == "identifier":
                    names.add(tokens[segment_start].text)
            else:
                pending.append(segment_start)
    return frozenset(names), outer_end


def _javascript_binding_pattern_colons(
    tokens: tuple[_JavaScriptToken, ...],
    mates: tuple[int, ...],
    start: int,
) -> frozenset[int]:
    while start < len(tokens) and tokens[start].text == "...":
        start += 1
    pending = [start]
    colons: set[int] = set()
    while pending:
        pattern_start = pending.pop()
        if pattern_start >= len(tokens):
            continue
        token = tokens[pattern_start]
        if token.text not in {"{", "["} or mates[pattern_start] < 0:
            continue
        close = mates[pattern_start]
        for segment_start, segment_end in _javascript_top_level_segments(
            tokens,
            mates,
            pattern_start + 1,
            close,
        ):
            while segment_start < segment_end and tokens[segment_start].text == "...":
                segment_start += 1
            if segment_start >= segment_end:
                continue
            default = _javascript_top_level_token(
                tokens,
                mates,
                segment_start,
                segment_end,
                frozenset({"="}),
            )
            pattern_end = default if default is not None else segment_end
            if token.text == "{":
                separator = _javascript_top_level_token(
                    tokens,
                    mates,
                    segment_start,
                    pattern_end,
                    frozenset({":"}),
                )
                if separator is not None:
                    colons.add(tokens[separator].start)
                    pending.append(separator + 1)
            else:
                pending.append(segment_start)
    return frozenset(colons)


def _javascript_binding_pattern_static_keys(
    tokens: tuple[_JavaScriptToken, ...],
    mates: tuple[int, ...],
    start: int,
) -> frozenset[int]:
    while start < len(tokens) and tokens[start].text == "...":
        start += 1
    pending = [start]
    positions: set[int] = set()
    while pending:
        pattern_start = pending.pop()
        if pattern_start >= len(tokens):
            continue
        token = tokens[pattern_start]
        if token.text not in {"{", "["} or mates[pattern_start] < 0:
            continue
        close = mates[pattern_start]
        for segment_start, segment_end in _javascript_top_level_segments(
            tokens,
            mates,
            pattern_start + 1,
            close,
        ):
            while segment_start < segment_end and tokens[segment_start].text == "...":
                segment_start += 1
            if segment_start >= segment_end:
                continue
            default = _javascript_top_level_token(
                tokens,
                mates,
                segment_start,
                segment_end,
                frozenset({"="}),
            )
            pattern_end = default if default is not None else segment_end
            if token.text == "{":
                separator = _javascript_top_level_token(
                    tokens,
                    mates,
                    segment_start,
                    pattern_end,
                    frozenset({":"}),
                )
                if separator is not None:
                    if tokens[segment_start].kind == "identifier":
                        positions.add(tokens[segment_start].start)
                    pending.append(separator + 1)
            else:
                pending.append(segment_start)
    return frozenset(positions)


def _javascript_mark_type_range(
    tokens: tuple[_JavaScriptToken, ...],
    start: int,
    end: int,
    *,
    nonvalue_colons: set[int],
    ignored_symbol_positions: set[int],
) -> None:
    for token in tokens[start:end]:
        if token.text == ":":
            nonvalue_colons.add(token.start)
        elif token.kind == "identifier":
            ignored_symbol_positions.add(token.start)


def _javascript_callable_body(
    tokens: tuple[_JavaScriptToken, ...],
    mates: tuple[int, ...],
    parameters_end: int,
    statement_end: int,
    *,
    scan_limit: int,
) -> tuple[int | None, int, bool]:
    cursor = parameters_end + 1
    consumed = 0
    if cursor >= statement_end:
        return None, consumed, False
    if tokens[cursor].text == "{":
        return (cursor if mates[cursor] >= 0 else None), 1, False
    if tokens[cursor].text != ":":
        return None, 1, False
    cursor += 1
    type_start = cursor
    angle_depth = 0
    while cursor < statement_end:
        consumed += 1
        if consumed > scan_limit:
            return None, consumed, True
        token = tokens[cursor]
        if token.text == "<":
            angle_depth += 1
        elif token.text in {">", ">>"} and angle_depth:
            angle_depth = max(0, angle_depth - len(token.text))
        elif token.text in {"(", "["} and mates[cursor] >= 0:
            cursor = mates[cursor]
        elif token.text == "{" and mates[cursor] >= 0:
            previous = tokens[cursor - 1].text if cursor > type_start else ""
            if (
                cursor == type_start
                or angle_depth
                or previous
                in {
                    "&",
                    "(",
                    ",",
                    ":",
                    "=>",
                    "|",
                }
            ):
                cursor = mates[cursor]
            else:
                return cursor, consumed, False
        elif token.text == ";":
            return None, consumed, False
        cursor += 1
    return None, consumed, False


def _javascript_lexical_index(
    value: str,
    *,
    work_budget: int | None = None,
) -> _JavaScriptLexicalIndex:
    tokens, opaque_spans, lexer_uncertain = _lex_javascript(value)
    mates, delimiter_uncertain = _javascript_delimiter_mates(tokens)
    statement_starts, statement_ends = _javascript_statement_bounds(value, tokens)
    nonvalue_colons: set[int] = set()
    ignored_symbol_positions: set[int] = set()
    typed_assignment_members: list[tuple[str, int]] = []
    parameter_lists: set[tuple[int, int]] = set()
    class_bodies: set[int] = set()
    processed_declaration_starts: set[int] = set()
    processed_function_starts: set[int] = set()
    processed_class_starts: set[int] = set()
    processed_interface_starts: set[int] = set()
    processed_import_starts: set[int] = set()
    processed_alias_declaration_starts: set[int] = set()
    processed_type_statement_starts: set[int] = set()
    type_syntax_uncertain = False
    work_units = len(tokens) + len(opaque_spans)
    work_limit = len(tokens) * 8 + 4096 if work_budget is None else max(0, work_budget)

    def exhausted_result() -> _JavaScriptLexicalIndex:
        return _JavaScriptLexicalIndex(
            tokens=tokens,
            delimiter_mates=mates,
            opaque_spans=opaque_spans,
            nonvalue_colons=frozenset(nonvalue_colons),
            ignored_symbol_positions=frozenset(ignored_symbol_positions),
            typed_assignment_members=tuple(typed_assignment_members),
            source_proofs_valid=False,
            analysis_exhausted=True,
            work_units=work_units,
        )

    if work_units > work_limit:
        return exhausted_result()

    def bounded_statement_end(token_index: int) -> int:
        end = statement_ends[token_index]
        while end > token_index and tokens[end - 1].text == ";":
            end -= 1
        return end

    def declaration_end(token_index: int) -> int:
        end = bounded_statement_end(token_index)
        cursor = token_index + 1
        while cursor < end:
            if tokens[cursor].text in {"(", "[", "{"} and mates[cursor] >= 0:
                cursor = mates[cursor] + 1
                continue
            if tokens[cursor].text in {";", "of", "in", ")"}:
                return cursor
            cursor += 1
        return end

    def mark_pattern_and_annotation(start: int, end: int) -> None:
        if start >= end:
            return
        nonvalue_colons.update(_javascript_binding_pattern_colons(tokens, mates, start))
        ignored_symbol_positions.update(
            _javascript_binding_pattern_static_keys(tokens, mates, start)
        )
        _, pattern_end = _javascript_binding_pattern_names(tokens, mates, start)
        annotation = pattern_end
        if annotation < end and tokens[annotation].text in {"!", "?"}:
            annotation += 1
        if annotation >= end or tokens[annotation].text != ":":
            return
        default = _javascript_top_level_token(
            tokens,
            mates,
            annotation + 1,
            end,
            frozenset({"="}),
        )
        _javascript_mark_type_range(
            tokens,
            annotation,
            default if default is not None else end,
            nonvalue_colons=nonvalue_colons,
            ignored_symbol_positions=ignored_symbol_positions,
        )

    for token_index, token in enumerate(tokens):
        work_units += 1
        if work_units > work_limit:
            return exhausted_result()
        previous = tokens[token_index - 1].text if token_index else ""
        if token.text in {"const", "let", "var"} and previous not in {".", "?."}:
            statement_start = statement_starts[token_index]
            if statement_start in processed_declaration_starts:
                continue
            processed_declaration_starts.add(statement_start)
            end = declaration_end(token_index)
            work_units += max(0, end - token_index)
            if work_units > work_limit:
                return exhausted_result()
            for start, segment_end in _javascript_top_level_segments(
                tokens,
                mates,
                token_index + 1,
                end,
            ):
                mark_pattern_and_annotation(start, segment_end)
        elif token.text == "function":
            statement_start = statement_starts[token_index]
            if statement_start in processed_function_starts:
                continue
            processed_function_starts.add(statement_start)
            cursor = token_index + 1
            if cursor < len(tokens) and tokens[cursor].text == "*":
                cursor += 1
            if cursor < len(tokens) and tokens[cursor].kind == "identifier":
                cursor += 1
            end = bounded_statement_end(token_index)
            scan_start = cursor
            while cursor < end and tokens[cursor].text not in {"(", "{", ";"}:
                cursor += 1
            work_units += cursor - scan_start
            if work_units > work_limit:
                return exhausted_result()
            if cursor < end and tokens[cursor].text == "(" and mates[cursor] >= 0:
                parameter_lists.add((cursor, mates[cursor]))
        elif token.text == "catch" and token_index + 1 < len(tokens):
            opening = token_index + 1
            if tokens[opening].text == "(" and mates[opening] >= 0:
                parameter_lists.add((opening, mates[opening]))
        elif token.text == "=>" and token_index:
            closing = token_index - 1
            if tokens[closing].text == ")" and mates[closing] >= 0:
                parameter_lists.add((mates[closing], closing))
        elif token.text == "class":
            statement_start = statement_starts[token_index]
            if statement_start in processed_class_starts:
                continue
            processed_class_starts.add(statement_start)
            cursor = token_index + 1
            end = bounded_statement_end(token_index)
            scan_start = cursor
            while cursor < end and tokens[cursor].text not in {"{", ";"}:
                cursor += 1
            work_units += cursor - scan_start
            if work_units > work_limit:
                return exhausted_result()
            if cursor < end and tokens[cursor].text == "{" and mates[cursor] >= 0:
                class_bodies.add(cursor)

    controls = frozenset({"catch", "for", "if", "switch", "while", "with"})
    for opening, token in enumerate(tokens):
        if token.text != "(" or mates[opening] < 0:
            continue
        closing = mates[opening]
        previous = tokens[opening - 1] if opening else None
        if previous is None or previous.text in controls:
            continue
        after = closing + 1
        if after < len(tokens) and tokens[after].text == "=>":
            parameter_lists.add((opening, closing))
            continue
        body, consumed, exhausted = _javascript_callable_body(
            tokens,
            mates,
            closing,
            statement_ends[opening],
            scan_limit=max(0, work_limit - work_units),
        )
        work_units += consumed
        if exhausted:
            return exhausted_result()
        previous_is_function_name = (
            opening >= 2 and tokens[opening - 2].text == "function"
        ) or (
            opening >= 3
            and tokens[opening - 2].text == "*"
            and tokens[opening - 3].text == "function"
        )
        if (
            body is not None
            and previous.kind == "identifier"
            and previous.text != "function"
        ):
            parameter_lists.add((opening, closing))
            if not previous_is_function_name:
                ignored_symbol_positions.add(previous.start)

    for opening, closing in parameter_lists:
        for start, end in _javascript_top_level_segments(
            tokens,
            mates,
            opening + 1,
            closing,
        ):
            mark_pattern_and_annotation(start, end)
        annotation = closing + 1
        if annotation < len(tokens) and tokens[annotation].text == ":":
            end = statement_ends[opening]
            body, consumed, exhausted = _javascript_callable_body(
                tokens,
                mates,
                closing,
                end,
                scan_limit=max(0, work_limit - work_units),
            )
            work_units += consumed
            if exhausted:
                return exhausted_result()
            arrow = _javascript_top_level_token(
                tokens,
                mates,
                annotation + 1,
                end,
                frozenset({"=>"}),
            )
            annotation_end = body if body is not None else arrow
            if annotation_end is not None:
                _javascript_mark_type_range(
                    tokens,
                    annotation,
                    annotation_end,
                    nonvalue_colons=nonvalue_colons,
                    ignored_symbol_positions=ignored_symbol_positions,
                )

    for token_index, token in enumerate(tokens):
        if token.text == "type" and token_index + 2 < len(tokens):
            statement_start = statement_starts[token_index]
            if statement_start in processed_type_statement_starts:
                continue
            declaration_prefix = tokens[statement_start:token_index]
            if any(
                member.text not in {"declare", "default", "export"}
                for member in declaration_prefix
            ):
                continue
            processed_type_statement_starts.add(statement_start)
            end = bounded_statement_end(token_index)
            raw_end = statement_ends[token_index]
            boundary_is_proven = (
                end >= len(tokens)
                or (raw_end > end and tokens[raw_end - 1].text == ";")
                or (end < len(tokens) and tokens[end].text == "}")
                or (
                    end > token_index
                    and end < len(tokens)
                    and "\n" in value[tokens[end - 1].end : tokens[end].start]
                )
            )
            if not boundary_is_proven:
                type_syntax_uncertain = True
                continue
            assignment = _javascript_top_level_token(
                tokens,
                mates,
                token_index + 2,
                end,
                frozenset({"="}),
            )
            if tokens[token_index + 1].kind == "identifier" and assignment is not None:
                statement_keywords = frozenset(
                    {
                        "class",
                        "const",
                        "export",
                        "for",
                        "function",
                        "if",
                        "import",
                        "interface",
                        "let",
                        "return",
                        "switch",
                        "throw",
                        "try",
                        "type",
                        "var",
                        "while",
                        "with",
                    }
                )
                invalid_statement = None
                cursor = assignment + 1
                while cursor < end:
                    runtime_declaration_start = cursor - 2
                    if (
                        tokens[cursor].text == "="
                        and runtime_declaration_start > assignment + 1
                        and tokens[cursor - 1].kind == "identifier"
                        and tokens[runtime_declaration_start].kind == "identifier"
                    ):
                        invalid_statement = runtime_declaration_start
                        break
                    if (
                        tokens[cursor].text == "{"
                        and mates[cursor] >= 0
                        and cursor > assignment + 1
                        and tokens[cursor - 1].text
                        not in {"&", "(", ",", ":", "=>", "=", "?", "[", "|"}
                    ):
                        invalid_statement = (
                            runtime_declaration_start
                            if runtime_declaration_start > assignment + 1
                            and tokens[cursor - 1].kind == "identifier"
                            and tokens[runtime_declaration_start].kind == "identifier"
                            else cursor
                        )
                        break
                    if (
                        tokens[cursor].text in {"(", "[", "{"}
                        and 0 <= mates[cursor] < end
                    ):
                        cursor = mates[cursor] + 1
                        continue
                    previous = tokens[cursor - 1].text if cursor else ""
                    is_import_type = (
                        tokens[cursor].text == "import"
                        and cursor + 1 < end
                        and tokens[cursor + 1].text == "("
                    )
                    if (
                        tokens[cursor].text in statement_keywords
                        and previous not in {".", "?."}
                        and not is_import_type
                    ):
                        invalid_statement = cursor
                        break
                    cursor += 1
                type_end = invalid_statement if invalid_statement is not None else end
                if invalid_statement is not None:
                    type_syntax_uncertain = True
                work_units += max(0, type_end - token_index)
                if work_units > work_limit:
                    return exhausted_result()
                _javascript_mark_type_range(
                    tokens,
                    assignment + 1,
                    type_end,
                    nonvalue_colons=nonvalue_colons,
                    ignored_symbol_positions=ignored_symbol_positions,
                )
        elif token.text == "interface" and token_index + 1 < len(tokens):
            statement_start = statement_starts[token_index]
            if statement_start in processed_interface_starts:
                continue
            processed_interface_starts.add(statement_start)
            end = bounded_statement_end(token_index)
            body = token_index + 2
            scan_start = body
            while body < end and tokens[body].text != "{":
                body += 1
            work_units += body - scan_start
            if work_units > work_limit:
                return exhausted_result()
            if body < end and mates[body] >= 0:
                _javascript_mark_type_range(
                    tokens,
                    body + 1,
                    mates[body],
                    nonvalue_colons=nonvalue_colons,
                    ignored_symbol_positions=ignored_symbol_positions,
                )

    for body_open in class_bodies:
        body_close = mates[body_open]
        cursor = body_open + 1
        member_has_assignment = False
        while cursor < body_close:
            work_units += 1
            if work_units > work_limit:
                return exhausted_result()
            token = tokens[cursor]
            if token.text == ";":
                member_has_assignment = False
                cursor += 1
                continue
            if token.text == "=":
                key_index = cursor - 1
                while key_index > body_open and tokens[key_index].text in {"!", "?"}:
                    key_index -= 1
                if tokens[key_index].kind in {"identifier", "string"}:
                    ignored_symbol_positions.add(tokens[key_index].start)
                member_has_assignment = True
                cursor += 1
                continue
            if token.text in {"(", "[", "{"} and mates[cursor] >= 0:
                cursor = mates[cursor] + 1
                continue
            previous = tokens[cursor - 1].text if cursor else ""
            if (
                token.text == ":"
                and not member_has_assignment
                and (
                    tokens[cursor - 1].kind == "identifier"
                    or previous in {"]", "!", "?"}
                )
            ):
                key_index = cursor - 1
                while key_index > body_open and tokens[key_index].text in {"!", "?"}:
                    key_index -= 1
                if tokens[key_index].kind in {"identifier", "string"}:
                    ignored_symbol_positions.add(tokens[key_index].start)
                annotation_end = cursor + 1
                annotation_start = annotation_end
                angle_depth = 0
                while annotation_end < body_close:
                    member = tokens[annotation_end]
                    previous_member = tokens[annotation_end - 1]
                    if member.text == "<":
                        angle_depth += 1
                    elif member.text in {">", ">>"} and angle_depth:
                        angle_depth = max(0, angle_depth - len(member.text))
                    if (
                        not angle_depth
                        and annotation_end > annotation_start
                        and "\n" in value[previous_member.end : member.start]
                        and member.text not in {"&", ",", ".", "?.", ">", ">>", "|"}
                    ):
                        break
                    if (
                        not angle_depth
                        and annotation_end > annotation_start
                        and member.kind == "identifier"
                        and annotation_end + 1 < body_close
                        and tokens[annotation_end + 1].text == "("
                    ):
                        if "\n" not in value[previous_member.end : member.start]:
                            type_syntax_uncertain = True
                        break
                    if not angle_depth and annotation_end > annotation_start:
                        computed_member = (
                            annotation_end
                            if member.text == "["
                            else annotation_end + 1
                            if member.kind == "identifier"
                            and annotation_end + 1 < body_close
                            and tokens[annotation_end + 1].text == "["
                            else None
                        )
                        if computed_member is not None:
                            computed_close = mates[computed_member]
                            if (
                                computed_close >= 0
                                and computed_close + 1 < body_close
                                and tokens[computed_close + 1].text == "("
                            ):
                                type_syntax_uncertain = True
                                break
                        if (
                            member.kind == "identifier"
                            and annotation_end + 1 < body_close
                            and tokens[annotation_end + 1].text == "{"
                        ):
                            type_syntax_uncertain = True
                            break
                    if member.text in {"(", "[", "{"} and mates[annotation_end] >= 0:
                        annotation_end = mates[annotation_end] + 1
                        continue
                    if member.text in {"=", ";"}:
                        break
                    annotation_end += 1
                work_units += max(0, annotation_end - cursor)
                _javascript_mark_type_range(
                    tokens,
                    cursor,
                    annotation_end,
                    nonvalue_colons=nonvalue_colons,
                    ignored_symbol_positions=ignored_symbol_positions,
                )
                cursor = annotation_end
                continue
            cursor += 1

    delimiter_stack: list[int] = []
    nearest_brace_stack: list[int | None] = []
    object_like_braces: set[int] = set()
    object_member_has_value_colon: dict[int, bool] = {}
    ternaries: list[tuple[int, int, bool]] = []
    syntax_uncertain = type_syntax_uncertain
    for token_index, token in enumerate(tokens):
        if token.text in {"(", "[", "{"}:
            delimiter_stack.append(token_index)
            nearest_brace = (
                token_index
                if token.text == "{"
                else nearest_brace_stack[-1]
                if nearest_brace_stack
                else None
            )
            nearest_brace_stack.append(nearest_brace)
            if token.text == "{":
                previous = tokens[token_index - 1].text if token_index else ""
                if previous in {
                    "(",
                    "[",
                    ",",
                    ":",
                    "=",
                    "?",
                    "??",
                    "&&",
                    "||",
                    "!",
                    "!=",
                    "!==",
                    "%",
                    "&",
                    "*",
                    "+",
                    "-",
                    "/",
                    "<",
                    "<=",
                    "==",
                    "===",
                    ">",
                    ">=",
                    "^",
                    "|",
                    "~",
                    "await",
                    "case",
                    "default",
                    "delete",
                    "in",
                    "instanceof",
                    "new",
                    "of",
                    "return",
                    "throw",
                    "typeof",
                    "void",
                    "yield",
                }:
                    object_like_braces.add(token_index)
                    object_member_has_value_colon[token_index] = False
        elif token.text in {")", "]", "}"}:
            if any(depth >= len(delimiter_stack) for depth, _, _ in ternaries):
                syntax_uncertain = True
            if delimiter_stack:
                opening = delimiter_stack.pop()
                nearest_brace_stack.pop()
                object_member_has_value_colon.pop(opening, None)
                object_like_braces.discard(opening)
            while ternaries and ternaries[-1][0] > len(delimiter_stack):
                ternaries.pop()
        elif token.text == "?":
            nearest_brace = nearest_brace_stack[-1] if nearest_brace_stack else None
            ambiguous_mapping_colon = (
                nearest_brace is not None
                and nearest_brace in object_like_braces
                and not object_member_has_value_colon.get(nearest_brace, False)
            )
            ternaries.append(
                (len(delimiter_stack), token_index, ambiguous_mapping_colon)
            )
        elif token.text == ":":
            matched_ternary = False
            for ternary_index in range(len(ternaries) - 1, -1, -1):
                if ternaries[ternary_index][0] == len(delimiter_stack):
                    matched_ternary = True
                    if ternaries[ternary_index][2]:
                        syntax_uncertain = True
                    else:
                        nonvalue_colons.add(token.start)
                    del ternaries[ternary_index]
                    break
            if not matched_ternary and delimiter_stack:
                opening = delimiter_stack[-1]
                if opening in object_like_braces:
                    object_member_has_value_colon[opening] = True
        elif token.text in {",", ";", "=>"} and any(
            depth == len(delimiter_stack) for depth, _, _ in ternaries
        ):
            syntax_uncertain = True
            ternaries = [
                ternary for ternary in ternaries if ternary[0] != len(delimiter_stack)
            ]
        if token.text == "," and delimiter_stack:
            opening = delimiter_stack[-1]
            if opening in object_like_braces:
                object_member_has_value_colon[opening] = False
        if token.text in {";", "=>"}:
            ternaries.clear()
    if ternaries:
        syntax_uncertain = True

    for token_index, token in enumerate(tokens):
        if token.kind != "identifier":
            continue
        previous = tokens[token_index - 1].text if token_index else ""
        following = (
            tokens[token_index + 1].text if token_index + 1 < len(tokens) else ""
        )
        if previous in {".", "?."}:
            ignored_symbol_positions.add(token.start)
        if following == ":" and tokens[token_index + 1].start not in nonvalue_colons:
            ignored_symbol_positions.add(token.start)

    for token_index, token in enumerate(tokens):
        if token.text != "import":
            continue
        statement_start = statement_starts[token_index]
        if statement_start in processed_import_starts:
            continue
        processed_import_starts.add(statement_start)
        end = bounded_statement_end(token_index)
        cursor = token_index + 1
        if cursor < end and tokens[cursor].text == "type":
            ignored_symbol_positions.update(
                member.start
                for member in tokens[cursor:end]
                if member.kind == "identifier"
            )
            continue
        while cursor < end:
            work_units += 1
            if work_units > work_limit:
                return exhausted_result()
            if tokens[cursor].kind == "string":
                break
            if tokens[cursor].text == "{" and mates[cursor] >= 0:
                for start, member_end in _javascript_top_level_segments(
                    tokens,
                    mates,
                    cursor + 1,
                    mates[cursor],
                ):
                    if start >= member_end:
                        continue
                    if tokens[start].text == "type":
                        ignored_symbol_positions.update(
                            member.start
                            for member in tokens[start:member_end]
                            if member.kind == "identifier"
                        )
                        continue
                    alias = _javascript_top_level_token(
                        tokens,
                        mates,
                        start,
                        member_end,
                        frozenset({"as"}),
                    )
                    if alias is not None and tokens[start].kind == "identifier":
                        ignored_symbol_positions.add(tokens[start].start)
                cursor = mates[cursor] + 1
                continue
            cursor += 1

    for token_index, token in enumerate(tokens):
        if token.kind not in {"identifier", "string"}:
            continue
        annotation = token_index + 1
        if annotation < len(tokens) and tokens[annotation].text in {"!", "?"}:
            annotation += 1
        if (
            annotation >= len(tokens)
            or tokens[annotation].text != ":"
            or tokens[annotation].start not in nonvalue_colons
        ):
            continue
        end = statement_ends[token_index]
        assignment = annotation + 1
        angle_depth = 0
        while assignment < end:
            member = tokens[assignment]
            if member.text == "<":
                angle_depth += 1
            elif member.text in {">", ">>"} and angle_depth:
                angle_depth = max(0, angle_depth - len(member.text))
            elif member.text in {"(", "[", "{"} and mates[assignment] >= 0:
                assignment = mates[assignment] + 1
                continue
            elif member.text == "=" and not angle_depth:
                break
            elif member.text in {",", ";", ")"} and not angle_depth:
                assignment = end
                break
            assignment += 1
        if assignment >= end or tokens[assignment].text != "=":
            continue
        key = (
            _mapping_key_text(value[token.start : token.end])
            if token.kind == "string"
            else token.text
        )
        if key is not None and _credential_field_identity(key) is not None:
            typed_assignment_members.append((key, tokens[assignment].end))

    total_work_units = work_units + len(nonvalue_colons) + len(ignored_symbol_positions)
    analysis_exhausted = total_work_units > work_limit
    source_proofs_valid = not (
        lexer_uncertain or delimiter_uncertain or syntax_uncertain or analysis_exhausted
    )
    global_aliases = {
        "Reflect",
        "frames",
        "global",
        "globalThis",
        "parent",
        "self",
        "this",
        "top",
        "window",
    }

    def static_member(cursor: int) -> tuple[str, int] | None:
        if cursor >= len(tokens):
            return None
        if tokens[cursor].text in {".", "?."}:
            cursor += 1
            if cursor >= len(tokens):
                return None
            if tokens[cursor].kind == "identifier":
                return tokens[cursor].text, cursor + 1
        if tokens[cursor].text != "[" or mates[cursor] < 0:
            return None
        closing = mates[cursor]
        member = _static_javascript_string_expression(
            value[tokens[cursor].end : tokens[closing].start]
        )
        return (member, closing + 1) if member is not None else None

    delimiter_parents: tuple[int, ...] = ()
    invocation_budget_exhausted = False

    def charge_invocation_work(amount: int = 1) -> bool:
        nonlocal invocation_budget_exhausted, work_units
        work_units += amount
        if work_units > work_limit:
            invocation_budget_exhausted = True
            return False
        return True

    def grouped_expression_tail(
        expression_start: int,
        cursor: int,
    ) -> tuple[int, int]:
        while cursor < len(tokens) and tokens[cursor].text == ")":
            opening = mates[cursor]
            if opening < 0 or opening > expression_start:
                break
            previous = tokens[opening - 1] if opening else None
            if previous is not None and (
                _javascript_token_can_end_expression(previous)
                or previous.text in controls | {".", "?."}
            ):
                break
            if not charge_invocation_work():
                break
            expression_start = opening
            cursor += 1
        return expression_start, cursor

    def static_container_index(opening: int) -> int | None:
        def array_index(value: str) -> int | None:
            if len(value) > 10 or re.fullmatch(r"(?:0|[1-9][0-9]*)", value) is None:
                return None
            index = int(value)
            return index if index < 2**32 - 1 else None

        closing = mates[opening]
        start = opening + 1
        end = closing
        while start < end and tokens[start].text == "(" and mates[start] == end - 1:
            if not charge_invocation_work(2):
                return None
            start += 1
            end -= 1
        if end - start != 1:
            return None
        token = tokens[start]
        if token.kind == "number":
            return array_index(token.text)
        if token.kind != "string":
            return None
        index = _mapping_key_text(value[token.start : token.end])
        return array_index(index) if index is not None else None

    def reference_invocation(
        reference_start: int,
        reference_end: int,
    ) -> tuple[str, int] | None:
        expression_start, cursor = grouped_expression_tail(
            reference_start,
            reference_end,
        )
        while delimiter_parents and not invocation_budget_exhausted:
            container = delimiter_parents[expression_start]
            while container >= 0 and tokens[container].text != "[":
                if not charge_invocation_work():
                    return None
                container = delimiter_parents[container]
            if container < 0:
                break
            previous = tokens[container - 1] if container else None
            if previous is not None and (
                _javascript_token_can_end_expression(previous)
                or previous.text in {".", "?."}
            ):
                break

            closing = mates[container]
            if not charge_invocation_work(closing - container):
                return None
            segments = _javascript_top_level_segments(
                tokens,
                mates,
                container + 1,
                closing,
            )
            selected_segment = next(
                (
                    segment_index
                    for segment_index, (start, end) in enumerate(segments)
                    if start <= expression_start < end and cursor == end
                ),
                None,
            )
            if selected_segment is None:
                break

            container_start, selector = grouped_expression_tail(
                container,
                closing + 1,
            )
            if (
                selector + 1 < len(tokens)
                and tokens[selector].text == "?."
                and tokens[selector + 1].text == "["
            ):
                selector += 1
            if (
                selector >= len(tokens)
                or tokens[selector].text != "["
                or mates[selector] < 0
            ):
                break
            selected_index = static_container_index(selector)
            if selected_index != selected_segment:
                return None

            expression_start, cursor = grouped_expression_tail(
                container_start,
                mates[selector] + 1,
            )

        if (
            cursor + 1 < len(tokens)
            and tokens[cursor].text == "?."
            and tokens[cursor + 1].text == "("
        ):
            cursor += 1
        if cursor < len(tokens) and tokens[cursor].text == "(":
            return "direct", cursor

        invocation_member = static_member(cursor)
        if invocation_member is None:
            return None
        member_name, cursor = invocation_member
        if member_name not in {"apply", "bind", "call"}:
            return None
        if cursor < len(tokens) and tokens[cursor].text == "?.":
            cursor += 1
        if cursor < len(tokens) and tokens[cursor].text == "(":
            return member_name, cursor
        return None

    def timer_argument_is_string_code(opening: int) -> bool:
        call_end = mates[opening]
        if call_end < 0:
            return False

        position = _javascript_trivia_end(value, tokens[opening].end)
        while position < len(value) and value[position] == "(":
            position = _javascript_trivia_end(value, position + 1)
        if position < len(value) and value[position] in {"'", '"', "`"}:
            return True

        argument = opening + 1
        while (
            argument < call_end
            and tokens[argument].text == "("
            and 0 <= mates[argument] < call_end
        ):
            argument += 1
        if argument >= call_end:
            return False
        if tokens[argument].kind == "string":
            return True

        tagged_template_end = None
        tagged_template_cursor = None
        if (
            tokens[argument].text == "String"
            and argument + 2 < call_end
            and tokens[argument + 1].text in {".", "?."}
            and tokens[argument + 2].text == "raw"
        ):
            tagged_template_end = tokens[argument + 2].end
            tagged_template_cursor = argument + 3
        elif (
            tokens[argument].text == "String"
            and argument + 3 < call_end
            and tokens[argument + 1].text == "["
            and mates[argument + 1] == argument + 3
            and tokens[argument + 2].kind == "string"
            and _mapping_key_text(
                value[tokens[argument + 2].start : tokens[argument + 2].end]
            )
            == "raw"
        ):
            tagged_template_end = tokens[argument + 3].end
            tagged_template_cursor = argument + 4
        if tagged_template_end is None:
            return False
        assert tagged_template_cursor is not None
        while (
            tagged_template_cursor < call_end
            and tokens[tagged_template_cursor].text == ")"
            and 0 <= mates[tagged_template_cursor] < argument
        ):
            tagged_template_end = tokens[tagged_template_cursor].end
            tagged_template_cursor += 1
        template_start = _javascript_trivia_end(value, tagged_template_end)
        return template_start < len(value) and value[template_start] == "`"

    callable_references: list[tuple[str, int, int]] = []
    for token_index, token in enumerate(tokens):
        if token.kind != "identifier":
            continue
        previous = tokens[token_index - 1].text if token_index else ""
        if token.text in {"setInterval", "setTimeout"} and previous not in {".", "?."}:
            callable_references.append(("timer", token_index, token_index + 1))
        if token.text == "constructor" and previous in {".", "?."}:
            callable_references.append(("constructor", token_index, token_index + 1))

    for token_index, token in enumerate(tokens):
        if token.text != "[" or mates[token_index] < 0:
            continue
        closing = mates[token_index]
        if token_index + 1 >= closing or (
            tokens[token_index + 1].kind != "string"
            and tokens[token_index + 1].text not in {"(", "String"}
        ):
            continue
        work_units += closing - token_index
        if work_units > work_limit:
            return exhausted_result()
        member_name = _static_javascript_string_expression(
            value[token.end : tokens[closing].start]
        )
        if member_name == "constructor":
            callable_references.append(("constructor", token_index, closing + 1))

    if callable_references:
        work_units += len(tokens)
        if work_units > work_limit:
            return exhausted_result()
        parents = [-1] * len(tokens)
        stack: list[int] = []
        for token_index, token in enumerate(tokens):
            while stack and mates[stack[-1]] < token_index:
                stack.pop()
            parents[token_index] = stack[-1] if stack else -1
            if token.text in {"(", "[", "{"} and mates[token_index] > token_index:
                stack.append(token_index)
        delimiter_parents = tuple(parents)

    reference_budget_exhausted = False

    def reference_kind_at_expression_tail(start: int, end: int) -> str | None:
        nonlocal reference_budget_exhausted, work_units
        for kind, reference_start, reference_end in callable_references:
            work_units += 1
            if work_units > work_limit:
                reference_budget_exhausted = True
                return None
            if reference_start < start or reference_end > end:
                continue
            cursor = reference_end
            while cursor < end and tokens[cursor].text == ")":
                opening = mates[cursor]
                if opening < start or opening > reference_start:
                    break
                cursor += 1
            if cursor == end:
                return kind
        return None

    callable_aliases: dict[str, str] = {}
    for token_index, token in enumerate(tokens):
        if token.text not in {"const", "let", "var"}:
            continue
        statement_start = statement_starts[token_index]
        if statement_start in processed_alias_declaration_starts:
            continue
        processed_alias_declaration_starts.add(statement_start)
        end = declaration_end(token_index)
        for start, segment_end in _javascript_top_level_segments(
            tokens,
            mates,
            token_index + 1,
            end,
        ):
            assignment = _javascript_top_level_token(
                tokens,
                mates,
                start,
                segment_end,
                frozenset({"="}),
            )
            if assignment is None:
                continue
            if tokens[start].kind == "identifier":
                kind = reference_kind_at_expression_tail(
                    assignment + 1,
                    segment_end,
                )
                if reference_budget_exhausted:
                    return exhausted_result()
                if kind is not None:
                    callable_aliases[tokens[start].text] = kind
                continue
            if tokens[start].text != "{" or mates[start] < 0:
                continue
            for member_start, member_end in _javascript_top_level_segments(
                tokens,
                mates,
                start + 1,
                mates[start],
            ):
                separator = _javascript_top_level_token(
                    tokens,
                    mates,
                    member_start,
                    member_end,
                    frozenset({":"}),
                )
                key_token = tokens[member_start]
                if key_token.kind == "identifier":
                    key = key_token.text
                elif key_token.kind == "string":
                    key = _mapping_key_text(value[key_token.start : key_token.end])
                elif key_token.text == "[" and 0 <= mates[member_start] < member_end:
                    closing = mates[member_start]
                    work_units += closing - member_start
                    if work_units > work_limit:
                        return exhausted_result()
                    key = _static_javascript_string_expression(
                        value[key_token.end : tokens[closing].start]
                    )
                else:
                    key = None
                alias_index = member_start if separator is None else separator + 1
                if (
                    key == "constructor"
                    and alias_index < member_end
                    and tokens[alias_index].kind == "identifier"
                ):
                    callable_aliases[tokens[alias_index].text] = "constructor"

    for kind, reference_start, reference_end in callable_references:
        invocation = reference_invocation(reference_start, reference_end)
        if invocation_budget_exhausted:
            return exhausted_result()
        if invocation is None:
            continue
        invocation_kind, opening = invocation
        if (
            kind == "constructor"
            or invocation_kind != "direct"
            or (kind == "timer" and timer_argument_is_string_code(opening))
        ):
            source_proofs_valid = False

    for token_index, token in enumerate(tokens):
        previous = tokens[token_index - 1].text if token_index else ""
        alias_kind = callable_aliases.get(token.text)
        invocation = (
            reference_invocation(token_index, token_index + 1)
            if alias_kind is not None and previous not in {".", "?."}
            else None
        )
        if invocation_budget_exhausted:
            return exhausted_result()
        if invocation is not None:
            invocation_kind, opening = invocation
            if (
                alias_kind == "constructor"
                or invocation_kind != "direct"
                or (alias_kind == "timer" and timer_argument_is_string_code(opening))
            ):
                source_proofs_valid = False
        if (
            token.text in global_aliases
            or token.text == "with"
            or (token.text in {"eval", "Function"} and previous not in {".", "?."})
        ):
            source_proofs_valid = False

    total_work_units = work_units + len(nonvalue_colons) + len(ignored_symbol_positions)
    analysis_exhausted = total_work_units > work_limit
    source_proofs_valid = source_proofs_valid and not analysis_exhausted

    return _JavaScriptLexicalIndex(
        tokens=tokens,
        delimiter_mates=mates,
        opaque_spans=opaque_spans,
        nonvalue_colons=frozenset(nonvalue_colons),
        ignored_symbol_positions=frozenset(ignored_symbol_positions),
        typed_assignment_members=tuple(typed_assignment_members),
        source_proofs_valid=source_proofs_valid,
        analysis_exhausted=analysis_exhausted,
        work_units=total_work_units,
    )


_JAVASCRIPT_DIRECT_MEMBER = re.compile(
    r"(?sx)"
    r"(?P<key>"
    r'"(?:\\.|[^"\\])*"|'
    r"'(?:\\.|[^'\\])*'|"
    r"`(?:\\.|[^`\\])*`|"
    r"[A-Za-z_$][A-Za-z0-9_.$-]*"
    r")"
    r"(?:\s|/\*.*?\*/|//[^\r\n]*(?:\r?\n|$))*:(?!=|:)"
)
_SERIALIZED_ASSIGNMENT_MEMBER = re.compile(
    r"(?sx)"
    r"(?P<key>"
    r'"(?:\\.|[^"\\])*"|'
    r"'(?:\\.|[^'\\])*'|"
    r"[A-Za-z_$][A-Za-z0-9_.$ /-]*?"
    r")"
    r"(?:\s|/\*.*?\*/|//[^\r\n]*(?:\r?\n|$))*=(?!=|>)"
)
_YAML_FLOW_MEMBER = re.compile(
    r"(?msx)"
    r"(?:(?P<flow>[\{\[,]) | (?P<sequence>^[ \t]*-[ \t]+))"
    r"[ \t]*(?:\?[ \t]+)?"
    r"(?:(?:&[A-Za-z0-9_.-]+|!!?[A-Za-z0-9_./:-]+|!<[^>]+>)[ \t]+)*"
    r"(?P<key>"
    r'"(?:\\.|[^"\\])*"|'
    r"'(?:''|[^'])*'|"
    r"[A-Za-z_$][A-Za-z0-9_.$ /-]*?"
    r")"
    r"[ \t]*:"
)


def _mapping_key_text(raw_key: str) -> str | None:
    candidate = raw_key.strip()
    if candidate[:1] in {"'", '"', "`"}:
        parsed = _parse_serialized_string(candidate, 0)
        return parsed[0] if parsed is not None and parsed[1] == len(candidate) else None
    return candidate


def _javascript_direct_members(
    value: str,
    spans: tuple[tuple[int, int, str], ...],
) -> tuple[tuple[str, int, int], ...]:
    span_index = 0
    members: list[tuple[str, int, int]] = []
    for match in _JAVASCRIPT_DIRECT_MEMBER.finditer(value):
        while span_index < len(spans) and spans[span_index][1] <= match.start():
            span_index += 1
        containing = (
            spans[span_index]
            if span_index < len(spans)
            and spans[span_index][0] <= match.start() < spans[span_index][1]
            else None
        )
        if containing is not None:
            span_start, _, kind = containing
            if kind == "regex":
                continue
            if kind == "string" and match.start() != span_start:
                prefix = value[span_start + 1 : match.start()].rstrip()
                if not prefix or prefix[-1] not in "{[,":
                    continue
        key = _mapping_key_text(match.group("key"))
        if key is not None:
            members.append((key, match.start(), match.end()))
    return tuple(members)


def _bounded_mapping_expression(
    value: str,
    start: int,
    *,
    newline_terminates: bool,
) -> tuple[str | None, int]:
    index = start
    while (
        index < len(value)
        and value[index].isspace()
        and (not newline_terminates or value[index] not in "\r\n")
    ):
        index += 1
    expression_start = index
    stack: list[str] = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    while index < len(value):
        if value[index : index + 2] == "/*":
            closing = value.find("*/", index + 2)
            if closing < 0:
                return None, len(value) - expression_start
            index = closing + 2
            continue
        if value[index : index + 2] == "//":
            if value[expression_start : index + 2] in {
                "pass://",
                "secret-service://",
            }:
                index += 2
                continue
            newline = value.find("\n", index + 2)
            if newline < 0:
                index = len(value)
                break
            index = newline + 1
            if newline_terminates and not stack:
                break
            continue
        character = value[index]
        if character in {"'", '"', "`"}:
            parsed = _parse_serialized_string(value, index)
            if parsed is None:
                return None, len(value) - expression_start
            _, index = parsed
            continue
        if character in pairs:
            stack.append(character)
        elif character in pairs.values():
            if not stack:
                break
            if pairs[stack[-1]] != character:
                return None, index - expression_start
            stack.pop()
        elif not stack and (
            character in ",;" or (newline_terminates and character in "\r\n#")
        ):
            break
        index += 1
    expression = value[expression_start:index].strip()
    return (expression or None), max(1, index - expression_start)


def _javascript_bounded_mapping_expression(
    value: str,
    start: int,
    lexical_index: _JavaScriptLexicalIndex,
) -> tuple[str | None, int]:
    """Return one JavaScript expression without interpreting regex delimiters."""

    expression_start = _javascript_trivia_end(value, start)
    if value.startswith(("pass://", "secret-service://"), expression_start):
        return _bounded_mapping_expression(
            value,
            start,
            newline_terminates=False,
        )

    spans = lexical_index.opaque_spans
    low = 0
    high = len(spans)
    while low < high:
        middle = (low + high) // 2
        if spans[middle][0] <= expression_start:
            low = middle + 1
        else:
            high = middle
    if (
        low
        and spans[low - 1][0] <= expression_start < spans[low - 1][1]
        and spans[low - 1][2] == "string"
    ):
        return _bounded_mapping_expression(
            value,
            start,
            newline_terminates=False,
        )

    tokens = lexical_index.tokens
    low = 0
    high = len(tokens)
    while low < high:
        middle = (low + high) // 2
        if tokens[middle].start < expression_start:
            low = middle + 1
        else:
            high = middle
    token_index = low
    if token_index >= len(tokens) or tokens[token_index].start != expression_start:
        return None, max(1, len(value) - expression_start)

    index = token_index
    expression_end = len(value)
    while index < len(tokens):
        token = tokens[index]
        if token.text in {"(", "[", "{"}:
            mate = lexical_index.delimiter_mates[index]
            if mate < index:
                return None, max(1, token.end - expression_start)
            index = mate + 1
            continue
        if token.text in {")", "]", "}", ",", ";"}:
            expression_end = token.start
            break
        index += 1

    expression = value[expression_start:expression_end].strip()
    return (
        expression or None,
        max(1, expression_end - expression_start),
    )


def _javascript_template_is_source_only(
    value: str,
    *,
    key: str,
    local_bindings: Container[str],
) -> bool:
    candidate = value.strip()
    index = 0
    found = False
    while index < len(candidate):
        if candidate[index : index + 2] != "${":
            return False
        expression_start = index + 2
        depth = 1
        index = expression_start
        while index < len(candidate) and depth:
            if candidate[index] in {"'", '"', "`"}:
                parsed = _parse_serialized_string(candidate, index)
                if parsed is None:
                    return False
                _, index = parsed
                continue
            if candidate[index] == "{":
                depth += 1
            elif candidate[index] == "}":
                depth -= 1
                if not depth:
                    break
            index += 1
        if depth or not _javascript_expression_is_source_only(
            key,
            candidate[expression_start:index],
            allow_templates=False,
            local_bindings=local_bindings,
        ):
            return False
        found = True
        index += 1
    return found


def _javascript_literal_is_source_reference(
    literal: str,
    *,
    key: str,
    allow_templates: bool = True,
    local_bindings: Container[str] = frozenset(),
) -> bool:
    candidate = literal.strip()
    return (
        not candidate
        or _reference_value_is_safe(candidate)
        or (
            allow_templates
            and _javascript_template_is_source_only(
                candidate,
                key=key,
                local_bindings=local_bindings,
            )
        )
        or _normalized_field_name(candidate) == _normalized_field_name(key)
    )


def _javascript_expression_is_source_only(
    key: str,
    expression: str,
    *,
    allow_templates: bool = True,
    local_bindings: Container[str] = frozenset(),
) -> bool:
    literals, skeleton = _expression_literals_and_skeleton(expression)
    if _javascript_known_source_expression_is_safe(
        skeleton,
        key=key,
        literals=literals,
        local_bindings=local_bindings,
    ):
        return True
    if any(
        not _javascript_literal_is_source_reference(
            literal,
            key=key,
            allow_templates=allow_templates,
            local_bindings=local_bindings,
        )
        for literal in literals
    ):
        return False
    without_property_indexes = re.sub(
        r"\[\s*(?:[0-9]+|\"[A-Za-z_$][A-Za-z0-9_$]*\"|'[A-Za-z_$][A-Za-z0-9_$]*')\s*\]",
        "",
        skeleton,
    )
    if re.search(
        r"(?<![A-Za-z0-9_$])[0-9][0-9_]*(?![A-Za-z0-9_$])",
        without_property_indexes,
    ):
        return False
    return _javascript_source_expression_is_safe(
        skeleton,
        key=key,
        literals=literals,
        local_bindings=local_bindings,
    )


def _javascript_mapping_value_contains_literal_credential(
    key: str,
    expression: str,
    *,
    local_bindings: Container[str] = frozenset(),
) -> bool:
    parsed_string = _parse_serialized_string(expression, 0)
    if parsed_string is not None and parsed_string[1] == len(expression):
        return not _javascript_literal_is_source_reference(
            parsed_string[0],
            key=key,
            local_bindings=local_bindings,
        )
    balanced = _balanced_serialized_segment(expression, 0)
    if (
        balanced is not None
        and balanced[1] == len(expression)
        and expression.startswith("{")
    ):
        return not _serialized_composite_is_safe_reference(expression)
    if (
        balanced is not None
        and balanced[1] == len(expression)
        and expression.startswith("[")
    ):
        return True
    return not _javascript_expression_is_source_only(
        key,
        expression,
        local_bindings=local_bindings,
    )


def _javascript_source_expression_is_safe(
    value: str,
    *,
    key: str,
    literals: tuple[str, ...],
    local_bindings: Container[str],
) -> bool:
    candidate = _strip_outer_parentheses(value)
    if _reference_value_is_safe(candidate):
        return True
    if candidate.casefold() in {
        "any",
        "bool",
        "bytes",
        "false",
        "float",
        "int",
        "list",
        "never",
        "null",
        "object",
        "str",
        "string",
        "true",
        "tuple",
        "undefined",
        "unknown",
    }:
        return True
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", candidate):
        return candidate not in local_bindings
    field_identity = _credential_field_identity(key)
    if (
        field_identity is not None
        and field_identity[1] in {"authorization", "proxyauthorization"}
        and (
            member := re.fullmatch(
                r"(?P<root>[A-Za-z_$][A-Za-z0-9_$]*)"
                r"(?:\??\.[A-Za-z_$][A-Za-z0-9_$]*)+",
                candidate,
            )
        )
        and _credential_field_identity(candidate.rsplit(".", 1)[-1]) == field_identity
    ):
        return member.group("root") not in local_bindings
    return _javascript_known_source_expression_is_safe(
        candidate,
        key=key,
        literals=literals,
        local_bindings=local_bindings,
    )


def _strip_outer_parentheses(value: str) -> str:
    candidate = value.strip()
    left = 0
    left_layers = 0
    while left < len(candidate):
        while left < len(candidate) and candidate[left].isspace():
            left += 1
        if candidate[left : left + 1] != "(":
            break
        left_layers += 1
        left += 1
    right = len(candidate)
    right_layers = 0
    while right > left:
        while right > left and candidate[right - 1].isspace():
            right -= 1
        if candidate[right - 1 : right] != ")":
            break
        right_layers += 1
        right -= 1
    layers = min(left_layers, right_layers)
    if layers == 0:
        return candidate
    left = 0
    for _ in range(layers):
        while candidate[left].isspace():
            left += 1
        left += 1
    right = len(candidate)
    for _ in range(layers):
        while candidate[right - 1].isspace():
            right -= 1
        right -= 1
    return candidate[left:right].strip()


def _javascript_template_source_symbols(
    value: str,
    *,
    key: str,
) -> frozenset[str] | None:
    symbols: set[str] = set()
    index = 0
    found = False
    while index < len(value):
        if value[index : index + 2] != "${":
            return None
        expression_start = index + 2
        depth = 1
        index = expression_start
        while index < len(value) and depth:
            if value[index] in {"'", '"', "`"}:
                parsed = _parse_serialized_string(value, index)
                if parsed is None:
                    return None
                _, index = parsed
                continue
            if value[index] == "{":
                depth += 1
            elif value[index] == "}":
                depth -= 1
                if not depth:
                    break
            index += 1
        if depth:
            return None
        expression_symbols = _javascript_expression_source_symbols(
            key,
            value[expression_start:index],
        )
        if expression_symbols is None:
            return None
        symbols.update(expression_symbols)
        found = True
        index += 1
    return frozenset(symbols) if found else None


def _javascript_expression_source_symbols(
    key: str,
    expression: str,
) -> frozenset[str] | None:
    literals, skeleton = _expression_literals_and_skeleton(expression)
    candidate = _strip_outer_parentheses(skeleton)
    if any(
        marker in candidate
        for marker in (
            _TEMPLATE_LOCAL_OUTPUT_MARKER,
            _TEMPLATE_UNCERTAIN_OUTPUT_MARKER,
        )
    ):
        return None
    known = _javascript_known_source_expression_symbols(
        candidate,
        key=key,
        literals=literals,
    )
    if known is not None:
        return known
    if any(
        literal
        and not _reference_value_is_safe(literal)
        and _normalized_field_name(literal) != _normalized_field_name(key)
        for literal in literals
    ):
        return None
    without_property_indexes = re.sub(
        r"\[\s*(?:[0-9]+|\"[A-Za-z_$][A-Za-z0-9_$]*\"|'[A-Za-z_$][A-Za-z0-9_$]*')\s*\]",
        "",
        candidate,
    )
    if re.search(
        r"(?<![A-Za-z0-9_$])[0-9][0-9_]*(?![A-Za-z0-9_$])",
        without_property_indexes,
    ):
        return None
    if candidate in {
        _TEMPLATE_SOURCE_MARKER,
        "false",
        "null",
        "true",
    }:
        return frozenset()
    bindable_source_names = {
        "any",
        "bool",
        "bytes",
        "false",
        "float",
        "int",
        "list",
        "never",
        "null",
        "object",
        "str",
        "string",
        "true",
        "tuple",
        "undefined",
        "unknown",
    }
    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", candidate) and (
        _reference_value_is_safe(candidate)
        or candidate.casefold() in bindable_source_names
        or re.fullmatch(r"[A-Z][A-Z0-9_]*", candidate)
    ):
        return frozenset({candidate})
    if _reference_value_is_safe(candidate):
        return frozenset()
    field_identity = _credential_field_identity(key)
    member = re.fullmatch(
        r"(?P<root>[A-Za-z_$][A-Za-z0-9_$]*)"
        r"(?:\??\.[A-Za-z_$][A-Za-z0-9_$]*)+",
        candidate,
    )
    if (
        field_identity is not None
        and field_identity[1] in {"authorization", "proxyauthorization"}
        and member is not None
        and _credential_field_identity(candidate.rsplit(".", 1)[-1]) == field_identity
    ):
        return frozenset({member.group("root")})
    return None


def _javascript_mapping_source_symbols(
    key: str,
    expression: str,
) -> frozenset[str] | None:
    parsed_string = _parse_serialized_string(expression, 0)
    if parsed_string is not None and parsed_string[1] == len(expression):
        literal = parsed_string[0]
        if expression.startswith("`") and "${" in literal:
            return _javascript_template_source_symbols(literal, key=key)
        if (
            not literal
            or _reference_value_is_safe(literal)
            or _normalized_field_name(literal) == _normalized_field_name(key)
        ):
            return frozenset()
        if expression.startswith("`"):
            return _javascript_template_source_symbols(literal, key=key)
        return None
    balanced = _balanced_serialized_segment(expression, 0)
    if (
        balanced is not None
        and balanced[1] == len(expression)
        and expression.startswith("{")
    ):
        return (
            frozenset() if _serialized_composite_is_safe_reference(expression) else None
        )
    if (
        balanced is not None
        and balanced[1] == len(expression)
        and expression.startswith("[")
    ):
        return None
    return _javascript_expression_source_symbols(key, expression)


def _javascript_uncertified_source_symbols(
    lexical_index: _JavaScriptLexicalIndex,
    allowed_ranges_by_name: Mapping[str, list[tuple[int, int]]],
) -> frozenset[str]:
    required = frozenset(allowed_ranges_by_name)
    if not lexical_index.source_proofs_valid:
        return required
    sorted_ranges = {
        name: tuple(sorted(ranges)) for name, ranges in allowed_ranges_by_name.items()
    }
    cursors = dict.fromkeys(required, 0)
    uncertified: set[str] = set()
    for token in lexical_index.tokens:
        name = token.text
        if token.kind != "identifier" or name not in required:
            continue
        if token.start in lexical_index.ignored_symbol_positions:
            continue
        ranges = sorted_ranges[name]
        cursor = cursors[name]
        while cursor < len(ranges) and ranges[cursor][1] <= token.start:
            cursor += 1
        cursors[name] = cursor
        if (
            cursor < len(ranges)
            and ranges[cursor][0] <= token.start < ranges[cursor][1]
        ):
            continue
        uncertified.add(name)
    return frozenset(uncertified)


def _static_javascript_template_key(value: str) -> str | None:
    rendered: list[str] = []
    index = 0
    while index < len(value):
        if value[index : index + 2] != "${":
            rendered.append(value[index])
            index += 1
            continue
        closing = value.find("}", index + 2)
        if closing < 0:
            return None
        expression = _strip_outer_parentheses(value[index + 2 : closing])
        parsed = _parse_serialized_string(expression, 0)
        if parsed is None or parsed[1] != len(expression):
            return None
        rendered.append(parsed[0])
        index = closing + 1
    return "".join(rendered)


def _static_javascript_string_expression(value: str) -> str | None:
    candidate = _without_serialized_comments(value).strip()
    literals: list[str] = []
    skeleton: list[str] = []
    index = 0
    while index < len(candidate):
        if candidate[index] in {"'", '"', "`"}:
            parsed = _parse_serialized_string(candidate, index)
            if parsed is None:
                return None
            literal = parsed[0]
            if candidate[index] == "`":
                literal = _static_javascript_template_key(literal)
                if literal is None:
                    return None
            literals.append(literal)
            skeleton.append("S")
            _, index = parsed
            continue
        skeleton.append(candidate[index])
        index += 1
    shape = re.sub(r"\s+", "", "".join(skeleton))
    plus_shape = re.sub(r"[()]", "", shape)
    if (
        re.fullmatch(r"S(?:\+S)*", plus_shape) is not None
        or re.fullmatch(r"S\.concat\(S(?:,S)*\)", shape) is not None
    ):
        return "".join(literals)
    if shape == "String.rawS" and len(literals) == 1:
        return literals[0]
    return None


def _computed_javascript_key(value: str) -> str | None:
    key = _static_javascript_string_expression(value)
    if key is None:
        candidate = _without_serialized_comments(value).strip()
        index = 0
        while index < len(candidate):
            if candidate[index] not in {"'", '"', "`"}:
                index += 1
                continue
            parsed = _parse_serialized_string(candidate, index)
            if parsed is None:
                return None
            literal, index = parsed
            if _credential_field_identity(literal) is not None:
                key = literal
                break
    return (
        key if key is not None and _credential_field_identity(key) is not None else None
    )


def _javascript_regex_end(value: str, start: int) -> int | None:
    previous = start - 1
    while previous >= 0 and value[previous].isspace():
        previous -= 1
    if (
        previous > 0
        and value[previous] in "+-"
        and value[previous - 1] == value[previous]
    ):
        return None
    if previous >= 0 and value[previous] not in "=([{,:;!&|?+-*%^~<>":
        word = re.search(r"[A-Za-z_$][A-Za-z0-9_$]*\s*$", value[:start])
        if word is None or word.group(0).strip() not in {
            "case",
            "return",
            "throw",
            "yield",
        }:
            return None
    index = start + 1
    in_character_class = False
    while index < len(value) and value[index] not in "\r\n":
        if value[index] == "\\":
            index += 2
            continue
        if value[index] == "[":
            in_character_class = True
        elif value[index] == "]":
            in_character_class = False
        elif value[index] == "/" and not in_character_class:
            index += 1
            while index < len(value) and value[index].isalpha():
                index += 1
            return index
        index += 1
    return None


def _javascript_trivia_end(value: str, start: int) -> int:
    index = start
    while index < len(value):
        if value[index].isspace():
            index += 1
            continue
        if value[index : index + 2] == "/*":
            closing = value.find("*/", index + 2)
            if closing < 0:
                return len(value)
            index = closing + 2
            continue
        if value[index : index + 2] == "//":
            newline = value.find("\n", index + 2)
            if newline < 0:
                return len(value)
            index = newline + 1
            continue
        break
    return index


def _javascript_computed_members(
    value: str,
    lexical_index: _JavaScriptLexicalIndex,
) -> tuple[tuple[str | None, int, int], ...]:
    members: list[tuple[str | None, int, int]] = []
    tokens = lexical_index.tokens
    for token_index, token in enumerate(tokens):
        if token.text != "[" or lexical_index.delimiter_mates[token_index] < 0:
            continue
        closing_index = lexical_index.delimiter_mates[token_index]
        separator_index = closing_index + 1
        if separator_index >= len(tokens) or tokens[separator_index].text != ":":
            continue
        closing = tokens[closing_index]
        separator = tokens[separator_index]
        expression = value[token.end : closing.start]
        key = _computed_javascript_key(expression)
        if key is not None:
            members.append((key, separator.end, separator.start))
        elif _static_javascript_string_expression(expression) is None:
            members.append((None, separator.end, separator.start))
    return tuple(members)


def _javascript_direct_assignment_contains_credential_worthy_literal(
    value: str,
    lexical_index: _JavaScriptLexicalIndex,
) -> bool:
    tokens = lexical_index.tokens
    budget = len(value) * 4 + 4096
    type_parameter_ranges: list[tuple[int, int]] = []
    declaration_keywords = frozenset({"class", "function", "interface", "type"})

    for opening, token in enumerate(tokens):
        budget -= 1
        if budget < 0:
            return True
        if token.text != "<" or opening == 0:
            continue
        previous = tokens[opening - 1]
        header = previous.text == "function" or (
            previous.kind == "identifier"
            and opening >= 2
            and tokens[opening - 2].text in declaration_keywords
        )
        if not header:
            continue
        depth = 1
        closing = opening + 1
        while closing < len(tokens) and depth:
            budget -= 1
            if budget < 0:
                return True
            if tokens[closing].text == "<":
                depth += 1
            elif tokens[closing].text in {">", ">>"}:
                depth -= len(tokens[closing].text)
            closing += 1
        if depth <= 0:
            type_parameter_ranges.append((opening, closing))

    range_index = 0
    for token_index, token in enumerate(tokens):
        budget -= 1
        if budget < 0:
            return True
        while (
            range_index < len(type_parameter_ranges)
            and type_parameter_ranges[range_index][1] <= token_index
        ):
            range_index += 1
        if (
            range_index < len(type_parameter_ranges)
            and type_parameter_ranges[range_index][0]
            < token_index
            < type_parameter_ranges[range_index][1]
        ):
            continue
        if token.kind not in {"identifier", "string"}:
            continue
        key = (
            _mapping_key_text(value[token.start : token.end])
            if token.kind == "string"
            else token.text
        )
        if key is None or _credential_field_identity(key) is None:
            continue
        assignment = token_index + 1
        if assignment < len(tokens) and tokens[assignment].text in {"!", "?"}:
            assignment += 1
        if assignment >= len(tokens) or tokens[assignment].text != "=":
            continue
        expression, consumed = _javascript_bounded_mapping_expression(
            value,
            tokens[assignment].end,
            lexical_index,
        )
        budget -= consumed
        if budget < 0 or expression is None:
            return True
        literals, _ = _expression_literals_and_skeleton(expression)
        static_literal = _static_javascript_string_expression(expression)
        if static_literal is not None:
            literals += (static_literal,)
        for literal in literals:
            candidate = literal.strip()
            if (
                not candidate
                or _reference_value_is_safe(candidate)
                or _normalized_field_name(candidate) == _normalized_field_name(key)
            ):
                continue
            if len(candidate) >= 20 or (
                len(candidate) >= 16
                and re.search(r"[0-9._~+/-]", candidate) is not None
            ):
                return True
    return False


def _javascript_member_is_nonvalue(
    lexical_index: _JavaScriptLexicalIndex,
    colon: int,
) -> bool:
    return lexical_index.colon_is_definitely_nonvalue(colon)


def _javascript_unresolved_computed_member_requires_review(expression: str) -> bool:
    parsed = _parse_serialized_string(expression, 0)
    if parsed is None or parsed[1] != len(expression):
        return False
    literal = parsed[0].strip()
    if not literal or _reference_value_is_safe(literal):
        return False
    return len(literal) >= 20 or (
        len(literal) >= 16 and re.search(r"[0-9._~+/-]", literal) is not None
    )


def _javascript_mappings_contain_literal_credential(
    value: str,
    *,
    work_budget: int | None = None,
) -> bool:
    candidates: list[tuple[str | None, int]] = []
    lexical_index = _javascript_lexical_index(value, work_budget=work_budget)
    if lexical_index.analysis_exhausted:
        return True
    if _javascript_direct_assignment_contains_credential_worthy_literal(
        value,
        lexical_index,
    ):
        return True
    for key, match_start, match_end in _javascript_direct_members(
        value,
        lexical_index.opaque_spans,
    ):
        if _credential_field_identity(
            key
        ) is not None and not _javascript_member_is_nonvalue(
            lexical_index, match_end - 1
        ):
            candidates.append((key, match_end))
    for key, start, colon in _javascript_computed_members(value, lexical_index):
        if not _javascript_member_is_nonvalue(lexical_index, colon):
            candidates.append((key, start))
    candidates.extend(lexical_index.typed_assignment_members)
    budget = len(value) * 4 + 4096
    allowed_ranges_by_name: dict[str, list[tuple[int, int]]] = {}
    for key, start in candidates:
        expression, consumed = _javascript_bounded_mapping_expression(
            value,
            start,
            lexical_index,
        )
        budget -= consumed
        if budget < 0:
            return True
        if expression is None:
            return True
        if key is None:
            if _javascript_unresolved_computed_member_requires_review(expression):
                return True
            continue
        symbols = _javascript_mapping_source_symbols(key, expression)
        if symbols is None:
            return True
        expression_start = _javascript_trivia_end(value, start)
        if not value.startswith(expression, expression_start):
            return True
        expression_end = expression_start + len(expression)
        for symbol in symbols:
            allowed_ranges_by_name.setdefault(symbol, []).append(
                (expression_start, expression_end)
            )
    return bool(
        _javascript_uncertified_source_symbols(
            lexical_index,
            allowed_ranges_by_name,
        )
    )


def _javascript_conservative_mappings_contain_literal_credential(
    value: str,
) -> bool:
    """Scan JSX-family sources without trying to parse JSX grammar."""

    if _javascript_mappings_contain_literal_credential(value):
        return True
    lexical_index = _javascript_lexical_index(value)
    lexed_members = {
        (start, end)
        for _, start, end in _javascript_direct_members(
            value,
            lexical_index.opaque_spans,
        )
    }
    for match in _JAVASCRIPT_DIRECT_MEMBER.finditer(value):
        key = _mapping_key_text(match.group("key"))
        if (
            key is not None
            and _credential_field_identity(key) is not None
            and (match.start(), match.end()) not in lexed_members
        ):
            return True
    return False


def _template_projection(value: str) -> str | None:
    projected: list[str] = []
    local_bindings: set[str] = set()
    index = 0
    controls = {
        "block",
        "define",
        "else",
        "end",
        "if",
        "range",
        "with",
    }
    closings = {"{{": "}}", "{%": "%}", "{#": "#}"}
    while index < len(value):
        opener_match = _TEMPLATE_OPENER.search(value, index)
        if opener_match is None:
            projected.append(value[index:])
            break
        start = opener_match.start()
        projected.append(value[index:start])
        opener = value[start : start + 2]
        closing = closings[opener]
        end = value.find(closing, start + 2)
        if end < 0:
            return None
        body = value[start + 2 : end].strip()
        if body.startswith("-"):
            body = body[1:].lstrip()
        if body.endswith("-"):
            body = body[:-1].rstrip()
        local_assignment = False
        if opener == "{%":
            jinja_binding = re.match(
                r"set\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
                body,
            )
            if jinja_binding is not None:
                local_bindings.add(jinja_binding.group(1))
                local_assignment = True
        else:
            go_bindings = re.search(
                r"(?P<names>\$[A-Za-z_][A-Za-z0-9_]*"
                r"(?:\s*,\s*\$[A-Za-z_][A-Za-z0-9_]*)*)"
                r"\s*(?::=|=(?!=))",
                body,
            )
            if go_bindings is not None:
                local_bindings.update(
                    re.findall(
                        r"\$[A-Za-z_][A-Za-z0-9_]*",
                        go_bindings.group("names"),
                    )
                )
                local_assignment = True
        if opener == "{#" or (body.startswith("/*") and body.endswith("*/")):
            pass
        elif local_assignment:
            projected.append(_TEMPLATE_CONTROL_MARKER)
        elif opener == "{%":
            projected.append(_TEMPLATE_UNCERTAIN_OUTPUT_MARKER)
        elif not body:
            return None
        elif body.split(None, 1)[0] in controls:
            projected.append(_TEMPLATE_UNCERTAIN_OUTPUT_MARKER)
        else:
            parsed = (
                _parse_backtick_scalar(body)
                if body.startswith("`")
                else _parse_quoted_scalar(body)
            )
            if parsed is not None and not body[parsed[1] :].strip():
                projected.append(parsed[0])
            elif re.fullmatch(
                r"(?:[.$][A-Za-z_][A-Za-z0-9_]*|"
                r"[A-Za-z_][A-Za-z0-9_]*)(?:\.[A-Za-z_][A-Za-z0-9_]*)*",
                body,
            ):
                binding = re.match(
                    r"(?:\$[A-Za-z_][A-Za-z0-9_]*|"
                    r"[A-Za-z_][A-Za-z0-9_]*)",
                    body,
                )
                if binding is not None and binding.group(0) in local_bindings:
                    projected.append(_TEMPLATE_LOCAL_OUTPUT_MARKER)
                else:
                    projected.append(_TEMPLATE_SOURCE_MARKER)
            else:
                projected.append(_TEMPLATE_UNCERTAIN_OUTPUT_MARKER)
        index = end + len(closing)
    candidate = "".join(projected)
    marker = re.escape(_TEMPLATE_CONTROL_MARKER)
    alternatives = re.compile(
        rf"(?:{marker}\s*)*([:=])(?:\s*{marker}\s*\1)+(?:\s*{marker})*"
    )
    candidate = alternatives.sub(r"\1", candidate)
    return candidate.replace(_TEMPLATE_CONTROL_MARKER, "")


def _serialized_assignments_contain_literal_credential(value: str) -> bool:
    budget = len(value) * 4 + 4096
    for match in _SERIALIZED_ASSIGNMENT_MEMBER.finditer(value):
        key = _mapping_key_text(match.group("key"))
        if key is None or _credential_field_identity(key) is None:
            continue
        expression, consumed = _bounded_mapping_expression(
            value,
            match.end(),
            newline_terminates=True,
        )
        budget -= consumed
        if budget < 0:
            return True
        if (
            expression is not None
            and _javascript_mapping_value_contains_literal_credential(
                key,
                expression,
            )
        ):
            return True
    return False


def _yaml_flow_mappings_contain_literal_credential(value: str) -> bool:
    budget = len(value) * 4 + 4096
    for match in _YAML_FLOW_MEMBER.finditer(value):
        key = _mapping_key_text(match.group("key"))
        if key is None or _credential_field_identity(key) is None:
            continue
        expression, consumed = _bounded_mapping_expression(
            value,
            match.end(),
            newline_terminates=match.group("sequence") is not None,
        )
        budget -= consumed
        if budget < 0:
            return True
        if expression is None:
            continue
        parsed_string = _parse_serialized_string(expression, 0)
        if parsed_string is not None and parsed_string[1] == len(expression):
            if _structured_assignment_is_literal(key, parsed_string[0]):
                return True
            continue
        balanced = _balanced_serialized_segment(expression, 0)
        if balanced is not None and balanced[1] == len(expression):
            if not _serialized_composite_is_safe_reference(expression):
                return True
            continue
        if expression.casefold() in {"false", "none", "null", "true", "~"}:
            continue
        if _reference_value_is_safe(expression):
            continue
        if _structured_assignment_is_literal(key, expression):
            return True
    return False


def string_looks_like_credential(
    value: str,
    *,
    syntax: str | None = None,
) -> bool:
    """Return whether *value* contains literal credential material."""

    templated = syntax == "template" or bool(syntax and syntax.endswith("-template"))
    if templated:
        projection = _template_projection(value)
        if projection is None:
            return True
        value = projection
        if syntax != "template":
            syntax = syntax.removesuffix("-template")

    candidate = _JSON_UNICODE_ESCAPE.sub(
        lambda match: chr(int(match.group(1), 16)),
        value,
    )
    candidate = _JS_BRACED_UNICODE_ESCAPE.sub(
        lambda match: (
            chr(codepoint)
            if (codepoint := int(match.group(1), 16)) <= 0x10FFFF
            else match.group(0)
        ),
        candidate,
    )
    if (
        string_looks_like_private_key(candidate)
        or _PROVIDER_TOKEN.search(candidate) is not None
    ):
        return True
    if syntax == "line-invariants":
        return _direct_context_contains_literal_credential(
            candidate
        ) or _contains_credential_shaped_bearer_value(candidate)

    javascript_syntaxes = {"javascript", "javascript-conservative"}
    analyzers = (
        lambda: _parsed_json_contains_literal_credential(candidate),
        lambda: bool(_parsed_python_credential_result(candidate)),
        lambda: _parsed_toml_contains_literal_credential(candidate),
        lambda: _direct_context_contains_literal_credential(candidate),
        lambda: _contains_credential_shaped_bearer_value(candidate),
        lambda: _inline_assignments_contain_literal_credential(candidate),
        lambda: (
            syntax not in javascript_syntaxes
            and _yaml_assignments_contain_literal_credential(candidate)
        ),
        lambda: (
            syntax in {"javascript", "template"}
            and _javascript_mappings_contain_literal_credential(candidate)
        ),
        lambda: (
            syntax == "javascript-conservative"
            and _javascript_conservative_mappings_contain_literal_credential(candidate)
        ),
        lambda: (
            syntax in {"template", "yaml"}
            and _yaml_flow_mappings_contain_literal_credential(candidate)
        ),
        lambda: (
            syntax in {"template", "toml"}
            and _serialized_assignments_contain_literal_credential(candidate)
        ),
    )
    return any(analyzer() for analyzer in analyzers)


def contains_literal_credential(document: object) -> bool:
    """Return whether a recursive public document contains a literal credential."""

    pending: list[tuple[Any, bool]] = [(document, False)]
    seen: set[tuple[int, bool]] = set()
    while pending:
        value, credential_context = pending.pop()
        if isinstance(value, str):
            if credential_context and bool(value.strip()):
                return True
            if string_looks_like_credential(value):
                return True
            continue
        if isinstance(value, Mapping):
            identity = (id(value), credential_context)
            if identity in seen:
                continue
            seen.add(identity)
            for key, member in value.items():
                pending.append((key, False))
                if credential_context:
                    pending.append((member, True))
                    continue
                if isinstance(key, str) and _credential_field_identity(key) is not None:
                    if isinstance(member, str):
                        if _credential_field_value_is_literal(key, member):
                            return True
                    elif not _structured_reference_is_safe(member):
                        pending.append((member, True))
                    continue
                pending.append((member, False))
        elif isinstance(value, (list, tuple)):
            identity = (id(value), credential_context)
            if identity in seen:
                continue
            seen.add(identity)
            pending.extend((member, credential_context) for member in value)
        elif credential_context and value is not None and type(value) is not bool:
            return True
    return False
