"""Secret-free public-data policy shared by equipment validators and scans."""

from __future__ import annotations

import ast
import json
import re
import textwrap
import warnings
from collections.abc import Mapping
from typing import Any

import tomllib

__all__ = (
    "contains_literal_credential",
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
_CAMEL_ACRONYM_BOUNDARY = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_WORD_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")


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
    if not candidate or _reference_value_is_safe(candidate):
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
    try:
        document, end = json.JSONDecoder().raw_decode(stripped)
    except (TypeError, ValueError):
        return False
    if (
        not isinstance(document, (Mapping, list))
        or re.fullmatch(r"[\s,;)}\]]*", stripped[end:]) is None
    ):
        return False
    return contains_literal_credential(document)


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
        if quote == '"' and character == "\\" and index + 1 < len(value):
            decoded.append(value[index : index + 2])
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
    while scalar.endswith(")") and scalar.count("(") < scalar.count(")"):
        scalar = scalar[:-1].rstrip()
    return (scalar, False) if scalar else None


def _serialized_scalar_is_source_expression(value: str, *, key: str) -> bool:
    candidate = value.strip()
    folded = candidate.casefold()
    field_identity = _credential_field_identity(key)
    if (
        field_identity is not None
        and field_identity[1] in {"authorization", "proxyauthorization"}
        and not _field_is_uppercase_name(key)
        and re.search(r"[ \t]", candidate) is not None
        and re.match(r"(?i)(?:bearer|basic|digest)\s+", candidate) is None
    ):
        return True
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
        "_" in candidate or candidate.casefold() in {"identity", "option", "shift"}
    ):
        return True
    return not _field_is_uppercase_name(key) and (
        re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*\[[^\]]+\]", candidate)
        or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*\([^\r\n]*\)", candidate)
        or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", candidate)
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
            pair = _split_serialized_pair(stripped, separators=frozenset({":"}))
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
        raw_value = re.sub(r"""["'][,;)}\]]*[ \t]*\Z""", "", raw_value)
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


def string_looks_like_credential(value: str) -> bool:
    """Return whether *value* contains literal credential material."""

    candidate = _JSON_UNICODE_ESCAPE.sub(
        lambda match: chr(int(match.group(1), 16)),
        value,
    )
    if (
        string_looks_like_private_key(candidate)
        or _PROVIDER_TOKEN.search(candidate) is not None
    ):
        return True
    if _parsed_json_contains_literal_credential(candidate):
        return True
    python_result = _parsed_python_credential_result(candidate)
    if python_result is not None:
        return python_result
    return (
        _parsed_toml_contains_literal_credential(candidate)
        or _direct_context_contains_literal_credential(candidate)
        or _contains_credential_shaped_bearer_value(candidate)
        or _inline_assignments_contain_literal_credential(candidate)
        or _yaml_assignments_contain_literal_credential(candidate)
    )


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
    return False
