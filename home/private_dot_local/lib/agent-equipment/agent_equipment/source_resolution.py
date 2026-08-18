"""Fact-only source resolution and controller-owned manifest materialization."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from .canonical import canonical_json_bytes, canonical_json_sha256
from .model import FrozenJsonObject, freeze_json, thaw_json
from .secrets import contains_literal_credential

SOURCE_RESOLUTION_REQUEST_SCHEMA_VERSION = "source-resolution-request/v1"
SOURCE_RESOLUTION_SCHEMA_VERSION = "source-resolution-facts/v1"
SOURCE_MANIFEST_SCHEMA_VERSION = "source-manifest/v1"
MAX_SOURCE_RESOLUTION_REQUEST_BYTES = 256 * 1024
MAX_SOURCE_RESOLUTION_BYTES = 4 * 1024 * 1024
MAX_SOURCE_RESOLUTION_DEPTH = 64
MAX_SOURCE_RESOLUTION_NODES = 100_000
MAX_SOURCE_FIELD_CHARACTERS = 4096
MAX_AVAILABLE_EQUIPMENT = 16_384
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_GIT_REVISION_PATTERN = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_GIT_BRANCH_PATTERN = re.compile(
    r"(?!HEAD$)(?!-)(?!\.)(?!.*(?:/\.|//|\.\.|@\{|\\))"
    r"(?!.*\.lock(?:/|$))(?!.*[./]$)[A-Za-z0-9._/-]+"
)
_DISTRIBUTION_IDENTITY_PATTERN = re.compile(r"distribution:[a-z0-9][a-z0-9._/-]*")
_EQUIPMENT_IDENTITY_PATTERN = re.compile(
    r"(?:skill|plugin|mcp|hook|other):[a-z0-9][a-z0-9._/-]*"
)
_ARTIFACT_SUBPATH_SEGMENT_PATTERN = re.compile(r"[A-Za-z0-9._~-]+")
_NATIVE_MANAGER_PATTERN = re.compile(r"[a-z0-9][a-z0-9._/-]{0,127}")
_NATIVE_PACKAGE_PATTERN = re.compile(r"[A-Za-z0-9@][A-Za-z0-9@._/+:-]{0,254}")
_NATIVE_CHANNEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}")
_CATALOG_NATIVE_MANAGER_PACKAGE_PATTERN = re.compile(
    r"(?:@[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._-]{0,127}|"
    r"[a-z0-9][a-z0-9._-]{0,127}(?:@[a-z0-9][a-z0-9._-]{0,127})?)"
)
_NPX_PACKAGE_PATTERN = re.compile(
    r"(?:@[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._-]{0,127}|"
    r"[a-z0-9][a-z0-9._-]{0,127})"
)
_CATALOG_NATIVE_CHANNEL_PATTERN = re.compile(r"[a-z0-9][a-z0-9._/-]{0,127}")
_OBSERVATION_SOURCE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,/_+-]{0,254}")
_SEMVER_IDENTIFIER = r"(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
_SEMVER_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    rf"(?:-{_SEMVER_IDENTIFIER}(?:\.{_SEMVER_IDENTIFIER})*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
_CODEX_REVISION_PATTERN = re.compile(r"(?=[0-9a-f]{8}\Z)(?=.*[0-9])[0-9a-f]{8}")
_SEMANTIC_VERSION_MANAGERS = frozenset({"npx", "claude", "cursor"})
_LITERAL_SECRET_ERROR = "source-resolution input contains literal secret material"


def _json_string_byte_length(value: str, maximum: int) -> int | None:
    total = 2
    if total > maximum:
        return None
    for character in value:
        codepoint = ord(character)
        if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
            total += 2
        elif codepoint < 0x20:
            total += 6
        else:
            try:
                total += len(character.encode("utf-8"))
            except UnicodeEncodeError:
                return None
        if total > maximum:
            return None
    return total


def _exact_frozen_json_is_bounded(value: object, maximum: int) -> bool:
    nodes = 0
    encoded_bytes = 0
    pending: list[tuple[object, int]] = [(value, 1)]
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > MAX_SOURCE_RESOLUTION_NODES or depth > MAX_SOURCE_RESOLUTION_DEPTH:
            return False
        if current is None:
            encoded_bytes += 4
        elif type(current) is bool:
            encoded_bytes += 4 if current else 5
        elif type(current) is int:
            digits = 1 if current == 0 else current.bit_length() * 30_103 // 100_000 + 1
            encoded_bytes += digits + (1 if current < 0 else 0)
        elif type(current) is float:
            if not math.isfinite(current):
                return False
            encoded_bytes += len(repr(current))
        elif type(current) is str:
            string_bytes = _json_string_byte_length(
                current,
                maximum - encoded_bytes,
            )
            if string_bytes is None:
                return False
            encoded_bytes += string_bytes
        elif type(current) is FrozenJsonObject:
            items = object.__getattribute__(current, "_items")
            if type(items) is not tuple:
                return False
            if nodes + len(pending) + len(items) > MAX_SOURCE_RESOLUTION_NODES:
                return False
            encoded_bytes += 2 + len(items) + max(0, len(items) - 1)
            if encoded_bytes > maximum:
                return False
            previous_key: str | None = None
            for item in items:
                if type(item) is not tuple or len(item) != 2:
                    return False
                key, member = item
                if type(key) is not str or (
                    previous_key is not None and key <= previous_key
                ):
                    return False
                key_bytes = _json_string_byte_length(
                    key,
                    maximum - encoded_bytes,
                )
                if key_bytes is None:
                    return False
                encoded_bytes += key_bytes
                previous_key = key
                pending.append((member, depth + 1))
        elif type(current) is tuple:
            if nodes + len(pending) + len(current) > MAX_SOURCE_RESOLUTION_NODES:
                return False
            encoded_bytes += 2 + max(0, len(current) - 1)
            if encoded_bytes > maximum:
                return False
            pending.extend((member, depth + 1) for member in current)
        else:
            return False
        if encoded_bytes > maximum:
            return False
    return True


class SourceResolver(Protocol):
    """Resolve one configured source without changing runtime state."""

    def resolve(self, request: SourceResolutionRequest) -> FrozenJsonObject:
        """Return one request-bound fact-only source-resolution envelope."""


@dataclass(frozen=True, slots=True)
class SourceResolutionRequest:
    """One admitted, closed, bounded source-resolution request."""

    document: FrozenJsonObject
    command: str
    base_catalog_digest: str
    base_lock_digest: str
    distribution_identity: str
    source: FrozenJsonObject
    base_source_manifest_digest: str
    selection: FrozenJsonObject
    request_digest: str


@dataclass(frozen=True, slots=True)
class SourceManifest:
    """One admitted complete, controller-authored source manifest."""

    document: FrozenJsonObject
    source_manifest_digest: str


@dataclass(frozen=True, slots=True)
class SourceResolution:
    """One admitted request-bound fact-only source-resolution response."""

    document: FrozenJsonObject
    request_digest: str
    facts: FrozenJsonObject
    resolution_digest: str


def _require_nonempty_bounded_string(value: object, field: str) -> str:
    if type(value) is not str or not value or len(value) > MAX_SOURCE_FIELD_CHARACTERS:
        raise ValueError(f"source-resolution {field} must be a bounded string")
    return value


def _require_sha256(value: object, field: str) -> str:
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"source-resolution {field} must be a SHA-256 digest")
    return value


def _require_public_scalar(
    value: object,
    field: str,
    pattern: re.Pattern[str],
) -> str:
    if (
        type(value) is not str
        or len(value) > MAX_SOURCE_FIELD_CHARACTERS
        or pattern.fullmatch(value) is None
    ):
        raise ValueError(f"source-resolution {field} is invalid")
    return value


def _reject_literal_secret(document: FrozenJsonObject) -> None:
    if contains_literal_credential(document):
        raise ValueError(_LITERAL_SECRET_ERROR)


def _require_git_branch(value: object, field: str) -> str:
    branch = _require_nonempty_bounded_string(value, field)
    if _GIT_BRANCH_PATTERN.fullmatch(branch) is None:
        raise ValueError(f"source-resolution {field} is invalid")
    return branch


def _hostname_has_valid_dns_labels(value: str) -> bool:
    return len(value) <= 253 and all(
        re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?",
            label,
        )
        is not None
        for label in value.split(".")
    )


def _public_git_repository_is_valid(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    path_segments = tuple(segment for segment in parsed.path.split("/") if segment)
    return (
        len(value) <= MAX_SOURCE_FIELD_CHARACTERS
        and parsed.scheme == "https"
        and bool(parsed.hostname)
        and _hostname_has_valid_dns_labels(parsed.hostname or "")
        and parsed.username is None
        and parsed.password is None
        and parsed.query == ""
        and parsed.fragment == ""
        and (port is None or 1 <= port <= 65535)
        and "\\" not in value
        and "%" not in value
        and parsed.path not in {"", "/"}
        and parsed.path.endswith(".git")
        and all(
            segment not in {".", ".."}
            and _ARTIFACT_SUBPATH_SEGMENT_PATTERN.fullmatch(segment) is not None
            for segment in path_segments
        )
    )


def _static_credential_free_https_url_is_valid(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    path_segments = tuple(segment for segment in parsed.path.split("/") if segment)
    return (
        len(value) <= MAX_SOURCE_FIELD_CHARACTERS
        and parsed.scheme == "https"
        and bool(parsed.hostname)
        and _hostname_has_valid_dns_labels(parsed.hostname or "")
        and parsed.username is None
        and parsed.password is None
        and parsed.query == ""
        and parsed.fragment == ""
        and (port is None or 1 <= port <= 65535)
        and "\\" not in value
        and "%" not in value
        and all(
            segment not in {".", ".."}
            and _ARTIFACT_SUBPATH_SEGMENT_PATTERN.fullmatch(segment) is not None
            and re.fullmatch(
                r"(?i)(?:bearer|api[-_]?key|access[-_]?token|token|secret|password|"
                r"client[-_]?secret|credential)(?:[-_.=:].*)?",
                segment,
            )
            is None
            for segment in path_segments
        )
    )


def _artifact_subpath_is_valid(value: str) -> bool:
    if not value or "%" in value or "\\" in value:
        return False
    return all(
        segment not in {"", ".", ".."}
        and _ARTIFACT_SUBPATH_SEGMENT_PATTERN.fullmatch(segment) is not None
        for segment in value.split("/")
    )


def _immutable_artifact_ref_matches(
    value: object,
    repository: object,
    revision: object,
) -> bool:
    if not all(isinstance(item, str) for item in (value, repository, revision)):
        return False
    assert isinstance(value, str)
    assert isinstance(repository, str)
    assert isinstance(revision, str)
    if len(value) > MAX_SOURCE_FIELD_CHARACTERS:
        return False
    expected = f"git+{repository}@{revision}"
    if value == expected:
        return True
    prefix = f"{expected}#"
    return value.startswith(prefix) and all(
        _artifact_subpath_is_valid(item) for item in value[len(prefix) :].split(",")
    )


def _require_equipment_identity(value: object, field: str) -> str:
    identity = _require_nonempty_bounded_string(value, field)
    if _EQUIPMENT_IDENTITY_PATTERN.fullmatch(identity) is None:
        raise ValueError(f"source-resolution {field} is invalid")
    return identity


def _digest_without(document: FrozenJsonObject, field: str) -> str:
    payload = thaw_json(document)
    if type(payload) is not dict:
        raise TypeError("digest-bound source-resolution document must be an object")
    payload.pop(field)
    return canonical_json_sha256(payload)


def _admit_source(
    source: object,
    *,
    require_catalog_policy: bool = False,
) -> FrozenJsonObject:
    if not isinstance(source, FrozenJsonObject):
        raise TypeError("source-resolution source must be an object")
    kind = source.get("kind")
    if kind == "git":
        if set(source) not in (
            {"kind", "repository"},
            {"branch", "kind", "repository"},
        ):
            raise ValueError("Git source tracking policy is not closed")
        repository = _require_nonempty_bounded_string(
            source.get("repository"),
            "repository",
        )
        if not _public_git_repository_is_valid(repository):
            raise ValueError("source-resolution Git repository is invalid")
        if "branch" in source:
            _require_git_branch(source.get("branch"), "branch")
        return source
    if kind == "native_manager":
        if set(source) not in (
            {"kind", "manager", "package"},
            {"channel", "kind", "manager", "package"},
        ):
            raise ValueError("native source tracking policy is not closed")
        manager = _require_public_scalar(
            source.get("manager"),
            "manager",
            _NATIVE_MANAGER_PATTERN,
        )
        _require_public_scalar(
            source.get("package"),
            "package",
            _NPX_PACKAGE_PATTERN if manager == "npx" else _NATIVE_PACKAGE_PATTERN,
        )
        if "channel" in source:
            channel = _require_public_scalar(
                source.get("channel"),
                "channel",
                _NATIVE_CHANNEL_PATTERN,
            )
            if channel == "latest":
                raise ValueError("latest is represented by an omitted native channel")
        if require_catalog_policy:
            manager = source.get("manager")
            package = source.get("package")
            configured_channel = source.get("channel")
            if manager == "http":
                if (
                    set(source) != {"channel", "kind", "manager", "package"}
                    or type(package) is not str
                    or not _static_credential_free_https_url_is_valid(package)
                    or source.get("channel") != "static"
                ):
                    raise ValueError("HTTP source tracking policy is invalid")
            elif manager == "npx":
                if (
                    type(package) is not str
                    or _NPX_PACKAGE_PATTERN.fullmatch(package) is None
                    or (
                        "channel" in source
                        and (
                            type(configured_channel) is not str
                            or _CATALOG_NATIVE_CHANNEL_PATTERN.fullmatch(
                                configured_channel
                            )
                            is None
                        )
                    )
                ):
                    raise ValueError("native source tracking policy is invalid")
            elif (
                manager not in {"claude", "codex", "cursor"}
                or type(package) is not str
                or _CATALOG_NATIVE_MANAGER_PACKAGE_PATTERN.fullmatch(package) is None
                or (
                    "channel" in source
                    and (
                        type(configured_channel) is not str
                        or _CATALOG_NATIVE_CHANNEL_PATTERN.fullmatch(configured_channel)
                        is None
                    )
                )
            ):
                raise ValueError("native source tracking policy is invalid")
        return source
    raise ValueError("source-resolution source kind is unsupported")


def _admit_selection(selection: object) -> FrozenJsonObject:
    if not isinstance(selection, FrozenJsonObject):
        raise TypeError("source-resolution selection must be an object")
    if set(selection) == {"all"} and selection.get("all") is True:
        return selection
    if set(selection) != {"equipment"}:
        raise ValueError("source-resolution selection is not closed")
    equipment = selection.get("equipment")
    if type(equipment) is not tuple or not equipment:
        raise ValueError("explicit source selection must be nonempty")
    admitted = tuple(
        _require_equipment_identity(item, "equipment identity") for item in equipment
    )
    if admitted != tuple(sorted(set(admitted))):
        raise ValueError("explicit source selection must be sorted and unique")
    return selection


def admit_source_resolution_request(
    document: FrozenJsonObject,
) -> SourceResolutionRequest:
    """Admit one closed, bounded, digest-bound resolver request."""

    if not isinstance(document, FrozenJsonObject):
        raise TypeError("source-resolution request must be frozen JSON")
    if len(canonical_json_bytes(document)) > MAX_SOURCE_RESOLUTION_REQUEST_BYTES:
        raise ValueError("source-resolution request exceeds its byte bound")
    _reject_literal_secret(document)
    if set(document) != {
        "base_catalog_digest",
        "base_lock_digest",
        "base_source_manifest_digest",
        "command",
        "distribution_identity",
        "request_digest",
        "schema_version",
        "selection",
        "source",
    }:
        raise ValueError("source-resolution request is not closed")
    if document.get("schema_version") != SOURCE_RESOLUTION_REQUEST_SCHEMA_VERSION:
        raise ValueError("source-resolution request schema version is unsupported")
    if document.get("command") != "update":
        raise ValueError("source-resolution request command must be update")
    distribution_identity = _require_nonempty_bounded_string(
        document.get("distribution_identity"),
        "distribution identity",
    )
    if _DISTRIBUTION_IDENTITY_PATTERN.fullmatch(distribution_identity) is None:
        raise ValueError("source-resolution distribution identity is invalid")
    request_digest = _require_sha256(document.get("request_digest"), "request digest")
    if request_digest != _digest_without(document, "request_digest"):
        raise ValueError("source-resolution request digest is not canonical")
    return SourceResolutionRequest(
        document=document,
        command="update",
        base_catalog_digest=_require_sha256(
            document.get("base_catalog_digest"),
            "base catalog digest",
        ),
        base_lock_digest=_require_sha256(
            document.get("base_lock_digest"),
            "base lock digest",
        ),
        distribution_identity=distribution_identity,
        source=_admit_source(document.get("source")),
        base_source_manifest_digest=_require_sha256(
            document.get("base_source_manifest_digest"),
            "base source-manifest digest",
        ),
        selection=_admit_selection(document.get("selection")),
        request_digest=request_digest,
    )


def build_source_resolution_request(
    *,
    base_catalog_digest: str,
    base_lock_digest: str,
    distribution_identity: str,
    source: FrozenJsonObject,
    base_source_manifest_digest: str,
    selection: FrozenJsonObject,
) -> SourceResolutionRequest:
    """Build and admit one canonical update resolution request."""

    payload = {
        "schema_version": SOURCE_RESOLUTION_REQUEST_SCHEMA_VERSION,
        "command": "update",
        "base_catalog_digest": base_catalog_digest,
        "base_lock_digest": base_lock_digest,
        "distribution_identity": distribution_identity,
        "source": source,
        "base_source_manifest_digest": base_source_manifest_digest,
        "selection": selection,
    }
    document = freeze_json(payload | {"request_digest": canonical_json_sha256(payload)})
    if not isinstance(document, FrozenJsonObject):
        raise TypeError("source-resolution request must be an object")
    return admit_source_resolution_request(document)


def _admit_equipment_list(value: object, field: str) -> tuple[str, ...]:
    if type(value) is not tuple or not value or len(value) > MAX_AVAILABLE_EQUIPMENT:
        raise ValueError(f"source manifest {field} must be a bounded nonempty list")
    admitted = tuple(
        _require_equipment_identity(item, f"{field} identity") for item in value
    )
    if admitted != tuple(sorted(set(admitted))):
        raise ValueError(f"source manifest {field} must be sorted and unique")
    return admitted


def _admit_native_version(
    manager: object,
    version: object,
) -> FrozenJsonObject:
    if not isinstance(version, FrozenJsonObject):
        raise TypeError("source-resolution native version must be an object")
    if manager in _SEMANTIC_VERSION_MANAGERS:
        if set(version) != {"kind", "value"}:
            if version.get("kind") != "semantic_version":
                raise ValueError(
                    "source-resolution manager and version combination is unsupported"
                )
            raise ValueError("source-resolution native version is not closed")
        if version.get("kind") != "semantic_version":
            raise ValueError(
                "source-resolution manager and version combination is unsupported"
            )
        value = version.get("value")
        if (
            type(value) is not str
            or len(value) > 255
            or _SEMVER_PATTERN.fullmatch(value) is None
        ):
            raise ValueError("source-resolution semantic version is invalid")
        return version
    if manager == "codex":
        if set(version) != {"kind", "value"}:
            if version.get("kind") != "revision":
                raise ValueError(
                    "source-resolution manager and version combination is unsupported"
                )
            raise ValueError("source-resolution native version is not closed")
        if version.get("kind") != "revision":
            raise ValueError(
                "source-resolution manager and version combination is unsupported"
            )
        value = version.get("value")
        if type(value) is not str or _CODEX_REVISION_PATTERN.fullmatch(value) is None:
            raise ValueError("source-resolution native revision is invalid")
        return version
    if manager == "http":
        if set(version) != {"kind"}:
            if version.get("kind") != "static_source":
                raise ValueError(
                    "source-resolution manager and version combination is unsupported"
                )
            raise ValueError("source-resolution native version is not closed")
        if version.get("kind") != "static_source":
            raise ValueError(
                "source-resolution manager and version combination is unsupported"
            )
        return version
    raise ValueError("source-resolution manager and version combination is unsupported")


def _admit_resolution_facts(
    source: FrozenJsonObject,
    facts: object,
) -> FrozenJsonObject:
    if not isinstance(facts, FrozenJsonObject):
        raise TypeError("source-resolution facts must be an object")
    if source.get("kind") == "git":
        if set(facts) != {
            "available_equipment",
            "content_digest",
            "kind",
            "revision",
        }:
            raise ValueError("source-resolution Git facts are not closed")
        if facts.get("kind") != "git":
            raise ValueError("source-resolution fact kind does not match its request")
        revision = facts.get("revision")
        if (
            type(revision) is not str
            or _GIT_REVISION_PATTERN.fullmatch(revision) is None
        ):
            raise ValueError(
                "source-resolution Git revision must be exact and lowercase"
            )
        _require_sha256(facts.get("content_digest"), "content digest")
        _admit_equipment_list(facts.get("available_equipment"), "available equipment")
        return facts
    if set(facts) != {"available_equipment", "kind", "version"}:
        raise ValueError("source-resolution native facts are not closed")
    if facts.get("kind") != "native_manager":
        raise ValueError("source-resolution fact kind does not match its request")
    _admit_native_version(source.get("manager"), facts.get("version"))
    _admit_equipment_list(facts.get("available_equipment"), "available equipment")
    return facts


def admit_source_resolution(
    request: SourceResolutionRequest,
    document: FrozenJsonObject,
) -> SourceResolution:
    """Admit one closed fact response bound to *request*."""

    if type(request) is not SourceResolutionRequest:
        raise TypeError("source resolution requires an admitted request")
    if admit_source_resolution_request(request.document) != request:
        raise ValueError("source resolution request is not an admitted exact record")
    if type(document) is not FrozenJsonObject:
        raise TypeError("source resolution must be frozen JSON")
    if not _exact_frozen_json_is_bounded(document, MAX_SOURCE_RESOLUTION_BYTES):
        raise ValueError("source resolution exceeds its complexity or byte bound")
    if len(canonical_json_bytes(document)) > MAX_SOURCE_RESOLUTION_BYTES:
        raise ValueError("source resolution exceeds its byte bound")
    _reject_literal_secret(document)
    if set(document) != {
        "facts",
        "request_digest",
        "resolution_digest",
        "schema_version",
    }:
        raise ValueError("source resolution is not closed")
    if document.get("schema_version") != SOURCE_RESOLUTION_SCHEMA_VERSION:
        raise ValueError("source resolution schema version is unsupported")
    if document.get("request_digest") != request.request_digest:
        raise ValueError("source resolution does not bind its request")
    facts = _admit_resolution_facts(request.source, document.get("facts"))
    resolution_digest = _require_sha256(
        document.get("resolution_digest"),
        "resolution digest",
    )
    if resolution_digest != _digest_without(document, "resolution_digest"):
        raise ValueError("source resolution digest is not canonical")
    return SourceResolution(
        document=document,
        request_digest=request.request_digest,
        facts=facts,
        resolution_digest=resolution_digest,
    )


def _admit_resolved_source(
    configured: FrozenJsonObject,
    resolved: object,
) -> FrozenJsonObject:
    if not isinstance(resolved, FrozenJsonObject):
        raise TypeError("resolved source must be an object")
    if configured.get("kind") == "git":
        if set(resolved) != {"kind", "revision"}:
            raise ValueError("resolved Git source is not closed")
        if resolved.get("kind") != "git":
            raise ValueError("resolved Git source does not match its policy")
        revision = resolved.get("revision")
        if (
            type(revision) is not str
            or _GIT_REVISION_PATTERN.fullmatch(revision) is None
        ):
            raise ValueError("resolved Git revision must be exact and lowercase")
        return resolved
    if set(resolved) != {"kind", "version"}:
        raise ValueError("resolved native source is not closed")
    if resolved.get("kind") != "native_manager":
        raise ValueError("resolved native source does not match its policy")
    _admit_native_version(configured.get("manager"), resolved.get("version"))
    return resolved


def _native_version_value(version: FrozenJsonObject) -> str | None:
    value = version.get("value")
    if value is None:
        return None
    if type(value) is not str:
        raise TypeError("admitted native version value is malformed")
    return value


def _native_restore_channel_and_baseline(
    configured: FrozenJsonObject,
    version: FrozenJsonObject,
) -> tuple[str, str]:
    manager = configured.get("manager")
    package = configured.get("package")
    if type(package) is not str:
        raise TypeError("admitted native source package is malformed")
    channel = configured.get("channel", "latest")
    if type(channel) is not str:
        raise TypeError("admitted native source channel is malformed")
    value = _native_version_value(version)
    if manager == "npx" and value is not None:
        return f"npm:{value}", f"{package}@{value}"
    if manager == "http" and value is None:
        return channel, package
    if value is None:
        raise TypeError("admitted native version is missing its value")
    return channel, value


def _admit_restore(
    configured: FrozenJsonObject,
    resolved_source: FrozenJsonObject,
    restore: object,
) -> FrozenJsonObject:
    if not isinstance(restore, FrozenJsonObject):
        raise TypeError("source manifest restore record must be an object")
    if resolved_source.get("kind") == "git":
        if set(restore) != {
            "artifact_ref",
            "class",
            "content_digest",
            "native_update_control",
            "revision",
        }:
            raise ValueError("immutable source manifest restore record is not closed")
        revision = resolved_source.get("revision")
        repository = configured.get("repository")
        artifact_ref = _require_nonempty_bounded_string(
            restore.get("artifact_ref"),
            "restore artifact ref",
        )
        if (
            restore.get("class") != "immutable"
            or restore.get("revision") != revision
            or restore.get("native_update_control") != "not_applicable"
            or not _immutable_artifact_ref_matches(
                artifact_ref,
                repository,
                revision,
            )
        ):
            raise ValueError(
                "source manifest restore must match the resolved Git revision"
            )
        _require_sha256(restore.get("content_digest"), "restore content digest")
        return restore
    if set(restore) != {
        "channel",
        "class",
        "native_update_control",
        "observation_source",
        "reviewed_baseline",
    }:
        raise ValueError("native source manifest restore record is not closed")
    version = resolved_source.get("version")
    if not isinstance(version, FrozenJsonObject):
        raise TypeError("admitted native resolved source is malformed")
    expected_channel, expected_baseline = _native_restore_channel_and_baseline(
        configured,
        version,
    )
    channel = _require_nonempty_bounded_string(
        restore.get("channel"),
        "restore channel",
    )
    reviewed_baseline = _require_nonempty_bounded_string(
        restore.get("reviewed_baseline"),
        "restore reviewed baseline",
    )
    if (
        restore.get("class") != "native_rolling"
        or channel != expected_channel
        or reviewed_baseline != expected_baseline
        or restore.get("native_update_control")
        not in {"unknown", "suppressible", "unsuppressible"}
    ):
        raise ValueError(
            "source manifest restore must match the resolved native source"
        )
    _require_public_scalar(
        restore.get("observation_source"),
        "restore observation source",
        _OBSERVATION_SOURCE_PATTERN,
    )
    return restore


def admit_source_manifest(document: FrozenJsonObject) -> SourceManifest:
    """Admit one controller-authored manifest using its adjacent source policy."""

    if not isinstance(document, FrozenJsonObject):
        raise TypeError("source manifest must be frozen JSON")
    if len(canonical_json_bytes(document)) > MAX_SOURCE_RESOLUTION_BYTES:
        raise ValueError("source manifest exceeds its byte bound")
    _reject_literal_secret(document)
    if set(document) != {
        "available_equipment",
        "distribution_identity",
        "equipment",
        "membership_evidence",
        "resolved_source",
        "restore",
        "schema_version",
        "source",
        "source_manifest_digest",
    }:
        raise ValueError("source manifest is not closed")
    if document.get("schema_version") != SOURCE_MANIFEST_SCHEMA_VERSION:
        raise ValueError("source manifest schema version is unsupported")
    distribution_identity = _require_nonempty_bounded_string(
        document.get("distribution_identity"),
        "distribution identity",
    )
    if _DISTRIBUTION_IDENTITY_PATTERN.fullmatch(distribution_identity) is None:
        raise ValueError("source manifest distribution identity is invalid")
    configured = _admit_source(
        document.get("source"),
        require_catalog_policy=True,
    )
    resolved_source = _admit_resolved_source(
        configured,
        document.get("resolved_source"),
    )
    available = _admit_equipment_list(
        document.get("available_equipment"),
        "available equipment",
    )
    selected = _admit_equipment_list(document.get("equipment"), "equipment")
    if not set(selected).issubset(available):
        raise ValueError("source manifest equipment is not in its available listing")
    membership_evidence = document.get("membership_evidence")
    if (
        not isinstance(membership_evidence, FrozenJsonObject)
        or set(membership_evidence) != {"evidence_digest", "kind"}
        or membership_evidence.get("kind") != "authoritative_source_listing"
    ):
        raise ValueError("source manifest membership evidence is not closed")
    membership_evidence_digest = _require_sha256(
        membership_evidence.get("evidence_digest"),
        "membership evidence digest",
    )
    if membership_evidence_digest != canonical_json_sha256(
        {"available_equipment": available}
    ):
        raise ValueError(
            "source manifest membership evidence digest does not bind its list"
        )
    _admit_restore(configured, resolved_source, document.get("restore"))
    source_manifest_digest = _require_sha256(
        document.get("source_manifest_digest"),
        "source-manifest digest",
    )
    if source_manifest_digest != _digest_without(document, "source_manifest_digest"):
        raise ValueError("source manifest digest is not canonical")
    return SourceManifest(document, source_manifest_digest)


def _git_artifact_suffix(
    configured: FrozenJsonObject,
    resolved_source: FrozenJsonObject,
    restore: FrozenJsonObject,
) -> str:
    repository = configured.get("repository")
    revision = resolved_source.get("revision")
    artifact_ref = restore.get("artifact_ref")
    if not all(isinstance(item, str) for item in (repository, revision, artifact_ref)):
        raise TypeError("admitted Git restore record is malformed")
    assert isinstance(repository, str)
    assert isinstance(revision, str)
    assert isinstance(artifact_ref, str)
    prefix = f"git+{repository}@{revision}"
    if not artifact_ref.startswith(prefix):
        raise ValueError("base Git artifact reference does not match its source")
    return artifact_ref[len(prefix) :]


def materialize_source_manifest(
    request: SourceResolutionRequest,
    resolution: SourceResolution,
    base_manifest_document: FrozenJsonObject,
) -> SourceManifest:
    """Construct and seal one Source Manifest from facts plus reviewed policy."""

    if type(request) is not SourceResolutionRequest:
        raise TypeError("manifest materialization requires an admitted request")
    if type(resolution) is not SourceResolution:
        raise TypeError("manifest materialization requires an admitted resolution")
    if (
        resolution.request_digest != request.request_digest
        or admit_source_resolution(request, resolution.document) != resolution
    ):
        raise ValueError("source resolution does not bind its request")
    base_manifest = admit_source_manifest(base_manifest_document)
    if base_manifest.source_manifest_digest != request.base_source_manifest_digest:
        raise ValueError("base source-manifest digest does not match its request")
    base_document = base_manifest.document
    if (
        base_document.get("distribution_identity") != request.distribution_identity
        or base_document.get("source") != request.source
    ):
        raise ValueError("base source manifest does not match its request")

    available = _admit_equipment_list(
        resolution.facts.get("available_equipment"),
        "available equipment",
    )
    requested_equipment = request.selection.get("equipment")
    if requested_equipment is None:
        selected = available
    elif type(requested_equipment) is tuple:
        selected = tuple(
            _require_equipment_identity(item, "selected equipment identity")
            for item in requested_equipment
        )
    else:
        raise TypeError("admitted source selection is malformed")
    if not set(selected).issubset(available):
        raise ValueError("source resolution does not satisfy its selection")

    kind = request.source.get("kind")
    if kind == "git":
        revision = resolution.facts.get("revision")
        content_digest = resolution.facts.get("content_digest")
        if type(revision) is not str or type(content_digest) is not str:
            raise TypeError("admitted Git resolution facts are malformed")
        base_resolved = base_document.get("resolved_source")
        base_restore = base_document.get("restore")
        if not isinstance(base_resolved, FrozenJsonObject) or not isinstance(
            base_restore, FrozenJsonObject
        ):
            raise TypeError("admitted base Git manifest is malformed")
        suffix = _git_artifact_suffix(request.source, base_resolved, base_restore)
        repository = request.source.get("repository")
        if type(repository) is not str:
            raise TypeError("admitted Git source repository is malformed")
        resolved_source: object = {"kind": "git", "revision": revision}
        restore: object = {
            "class": "immutable",
            "revision": revision,
            "artifact_ref": f"git+{repository}@{revision}{suffix}",
            "content_digest": content_digest,
            "native_update_control": "not_applicable",
        }
    else:
        version = resolution.facts.get("version")
        if not isinstance(version, FrozenJsonObject):
            raise TypeError("admitted native resolution facts are malformed")
        base_restore = base_document.get("restore")
        if not isinstance(base_restore, FrozenJsonObject):
            raise TypeError("admitted base native manifest is malformed")
        channel, baseline = _native_restore_channel_and_baseline(
            request.source,
            version,
        )
        resolved_source = {
            "kind": "native_manager",
            "version": version,
        }
        restore = {
            "class": "native_rolling",
            "channel": channel,
            "reviewed_baseline": baseline,
            "observation_source": base_restore.get("observation_source"),
            "native_update_control": base_restore.get("native_update_control"),
        }

    membership_evidence = {
        "kind": "authoritative_source_listing",
        "evidence_digest": canonical_json_sha256({"available_equipment": available}),
    }
    payload = {
        "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
        "distribution_identity": request.distribution_identity,
        "source": request.source,
        "resolved_source": resolved_source,
        "available_equipment": available,
        "membership_evidence": membership_evidence,
        "equipment": selected,
        "restore": restore,
    }
    document = freeze_json(
        payload | {"source_manifest_digest": canonical_json_sha256(payload)}
    )
    if not isinstance(document, FrozenJsonObject):
        raise TypeError("materialized source manifest must be an object")
    return admit_source_manifest(document)
