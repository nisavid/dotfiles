"""Bounded, read-only discovery of agent equipment."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import urlsplit

from .canonical import canonical_json_bytes, canonical_json_sha256
from .model import FrozenJsonObject, freeze_json, thaw_json
from .secrets import contains_literal_credential

MAX_DISCOVERY_RESPONSE_BYTES = 1024 * 1024
MAX_DISCOVERY_RECORDS = 4096
MAX_DISCOVERY_AGGREGATE_BYTES = 8 * 1024 * 1024
MAX_DISCOVERY_DEPTH = 64
MAX_DISCOVERY_NODES = 100_000
MAX_DISCOVERY_ADAPTERS = 64
MAX_DISCOVERY_FIELD_CHARACTERS = 4096
MAX_DISCOVERY_REFERENCES = 64
MAX_DISCOVERY_PROVIDER_ARGUMENTS = 64

_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_CANDIDATE_PATTERN = re.compile(r"candidate:[a-z0-9][a-z0-9:._/-]*")
_CAPABILITY_PATTERN = re.compile(r"capability:[a-z0-9][a-z0-9._/-]*")
_TARGET_PATTERN = re.compile(
    r"(?P<harness>claude|codex|cursor)/"
    r"(?P<equipment_identity>(?:skill|plugin|mcp|hook|other):"
    r"[a-z0-9][a-z0-9._/-]*)"
)
_DISTRIBUTION_PATTERN = re.compile(r"distribution:[a-z0-9][a-z0-9._/-]*")
_GIT_REVISION_PATTERN = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_GIT_BRANCH_PATTERN = re.compile(
    r"(?!HEAD$)(?!-)(?!\.)(?!.*(?:/\.|//|\.\.|@\{|\\))"
    r"(?!.*\.lock(?:/|$))(?!.*[./]$)[A-Za-z0-9._/-]+"
)
_PLUGIN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@/-]*")
_PUBLIC_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_REGISTRY_QUALIFIED_NATIVE_PACKAGE_PATTERN = re.compile(
    r"(?:@[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._-]{0,127}|"
    r"[a-z0-9][a-z0-9._-]{0,127}(?:@[a-z0-9][a-z0-9._-]{0,127})?)"
)
_NPX_PACKAGE_PATTERN = re.compile(
    r"(?:@[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._-]{0,127}|"
    r"[a-z0-9][a-z0-9._-]{0,127})"
)
_NATIVE_CHANNEL_PATTERN = re.compile(r"[a-z0-9][a-z0-9._/-]{0,127}")
_SEMVER_IDENTIFIER = r"(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
_SEMANTIC_VERSION_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    rf"(?:-{_SEMVER_IDENTIFIER}(?:\.{_SEMVER_IDENTIFIER})*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
_CODEX_REVISION_PATTERN = re.compile(r"(?=[0-9a-f]{8}\Z)(?=.*[0-9])[0-9a-f]{8}")
_PROVIDER_LITERAL_PATTERN = re.compile(r"[-A-Za-z0-9._~:/@?&=+,#]+")
_SECRET_TEMPLATE_PATTERN = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9-]*:(?:Bearer )?)?\$\{\{reference\}\}"
)
_ENVIRONMENT_VARIABLE_PATTERN = re.compile(r"[A-Z_][A-Z0-9_]*")
_SECRET_PROFILE_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*")
_EVIDENCE_REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~:/@+-]*")
_OBSERVATION_SOURCE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,/_+-]{0,254}")
_SEMANTIC_VERSION_MANAGERS = frozenset({"claude", "cursor", "npx"})
_RAW_EVIDENCE_FIELDS = (
    "provider_evidence",
    "source_evidence",
    "restore_evidence",
    "secret_references",
    "evidence_references",
)
_COMMON_OBSERVATION_FIELDS = frozenset(
    {
        "target",
        "equipment_identity",
        "equipment_kind",
        "present",
        "normalized_state",
        "state_digest",
        "capability_identity",
        "capability_digest",
        "manager_version_evidence_digest",
    }
)
_RAW_SEMANTIC_OBSERVATION_FIELDS = _COMMON_OBSERVATION_FIELDS | frozenset(
    _RAW_EVIDENCE_FIELDS
)
_PROJECTED_SEMANTIC_OBSERVATION_FIELDS = _COMMON_OBSERVATION_FIELDS | {
    f"{field}_digest" for field in _RAW_EVIDENCE_FIELDS
}
_EPHEMERAL_FIELDS = frozenset({"request_id", "correlation_id", "observed_at"})
_REQUEST_FIELDS = frozenset(
    {
        "command",
        "candidate_identity",
        "implementation_manifest_digest",
        "catalog_digest",
        "lock_digest",
        "capability_identity",
        "capability_digest",
        "manager_version_evidence_digest",
        "harness",
        "target_scope",
        "request_digest",
    }
)
_REQUEST_STRING_FIELDS = (
    "command",
    "candidate_identity",
    "implementation_manifest_digest",
    "catalog_digest",
    "lock_digest",
    "capability_identity",
    "capability_digest",
    "manager_version_evidence_digest",
    "harness",
    "request_digest",
)


@dataclass(frozen=True, slots=True)
class DiscoveryError:
    """One stable, redacted discovery failure."""

    code: str
    message: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", self.code) is None:
            raise ValueError("discovery error codes must be stable identifiers")
        if type(self.message) is not str or not self.message:
            raise ValueError("discovery errors require a message")
        if contains_literal_credential({"message": self.message}):
            raise ValueError("discovery errors must not contain literal secrets")


@dataclass(frozen=True, slots=True)
class EquipmentDiscoveryObservation:
    """One canonical, secret-free factual equipment observation."""

    document: FrozenJsonObject
    observation_identity: str
    target: str
    equipment_identity: str
    equipment_kind: str
    present: bool
    state_digest: str
    capability_identity: str


@dataclass(frozen=True, slots=True)
class EquipmentDiscoveryReport:
    """One atomic canonical result from a complete discovery collection."""

    document: FrozenJsonObject
    request: EquipmentDiscoveryRequest
    observations: tuple[EquipmentDiscoveryObservation, ...]
    complete: bool
    discovery_digest: str


class EquipmentDiscoveryAdapter(Protocol):
    """The read-only boundary implemented by one harness discovery adapter."""

    def capabilities(self) -> object:
        """Return the adapter's current capability and manager bindings."""

        ...

    def discover(self, request: EquipmentDiscoveryRequest) -> object:
        """Return one bounded, factual response without mutating runtime state."""

        ...


@dataclass(frozen=True, slots=True)
class EquipmentDiscoveryRequest:
    """One immutable request for all targets or exact equipment targets."""

    document: FrozenJsonObject
    command: str
    harness: str
    targets: tuple[str, ...] | None
    request_digest: str

    @classmethod
    def create(
        cls,
        *,
        command: str,
        candidate_identity: str,
        implementation_manifest_digest: str,
        catalog_digest: str,
        lock_digest: str,
        capability_identity: str,
        capability_digest: str,
        manager_version_evidence_digest: str,
        harness: str,
        targets: tuple[str, ...] | None,
    ) -> EquipmentDiscoveryRequest:
        """Validate bindings and create their canonical request."""

        if type(command) is not str or command not in {"unmanaged", "add"}:
            raise ValueError("discovery command must be unmanaged or add")
        if not _bounded_string_matches(candidate_identity, _CANDIDATE_PATTERN):
            raise ValueError("candidate identity is invalid")
        for value in (
            implementation_manifest_digest,
            catalog_digest,
            lock_digest,
            capability_digest,
            manager_version_evidence_digest,
        ):
            if not _bounded_string_matches(value, _DIGEST_PATTERN):
                raise ValueError("discovery digest binding is invalid")
        if not _bounded_string_matches(capability_identity, _CAPABILITY_PATTERN):
            raise ValueError("capability identity is invalid")
        if type(harness) is not str or harness not in {"claude", "codex", "cursor"}:
            raise ValueError("discovery harness is unsupported")
        normalized_targets = _normalized_targets(harness, targets)
        if command == "add" and normalized_targets is None:
            raise ValueError("add discovery requires one or more exact targets")
        target_scope: object
        if normalized_targets is None:
            target_scope = {"all": True}
        else:
            target_scope = {"targets": list(normalized_targets)}
        payload = {
            "command": command,
            "candidate_identity": candidate_identity,
            "implementation_manifest_digest": implementation_manifest_digest,
            "catalog_digest": catalog_digest,
            "lock_digest": lock_digest,
            "capability_identity": capability_identity,
            "capability_digest": capability_digest,
            "manager_version_evidence_digest": manager_version_evidence_digest,
            "harness": harness,
            "target_scope": target_scope,
        }
        request_digest = canonical_json_sha256(payload)
        document = freeze_json(payload | {"request_digest": request_digest})
        if not isinstance(document, FrozenJsonObject):
            raise TypeError("discovery request must be a JSON object")
        return cls(document, command, harness, normalized_targets, request_digest)


def _normalized_targets(
    harness: str,
    targets: tuple[str, ...] | None,
) -> tuple[str, ...] | None:
    if targets is None:
        return None
    if type(targets) is not tuple or not targets:
        raise ValueError("target selection must be a nonempty immutable tuple")
    if len(targets) > MAX_DISCOVERY_RECORDS:
        raise ValueError("target selection exceeds the discovery record limit")
    normalized: list[str] = []
    for target in targets:
        if type(target) is not str:
            raise TypeError("discovery targets must be strings")
        if len(target) > MAX_DISCOVERY_FIELD_CHARACTERS:
            raise ValueError("discovery target exceeds its field limit")
        match = _TARGET_PATTERN.fullmatch(target)
        if match is None or match.group("harness") != harness:
            raise ValueError("discovery target is not an exact target for the harness")
        normalized.append(target)
    result = tuple(sorted(normalized))
    if result != targets or len(result) != len(set(result)):
        raise ValueError("discovery targets must be sorted and unique")
    return result


def collect_discovery(
    adapters: Sequence[EquipmentDiscoveryAdapter],
    request: EquipmentDiscoveryRequest,
) -> EquipmentDiscoveryReport | DiscoveryError:
    """Collect every adapter response atomically and in deterministic order."""

    if (
        not _request_is_valid(request)
        or type(adapters) not in {list, tuple}
        or not adapters
        or len(adapters) > MAX_DISCOVERY_ADAPTERS
    ):
        return _error("DISCOVERY_REQUEST_INVALID", "Discovery request is invalid.")
    aggregate_bytes = 0
    observations: list[EquipmentDiscoveryObservation] = []
    all_complete = True
    for adapter in adapters:
        try:
            capability = adapter.capabilities()
        except (Exception, SystemExit):  # noqa: BLE001 - untrusted adapter boundary
            return _error("DISCOVERY_FAILED", "Equipment discovery failed.")
        capability_bytes = _bounded_json_bytes(capability, MAX_DISCOVERY_RESPONSE_BYTES)
        if capability_bytes is None:
            return _error(
                "DISCOVERY_CAPABILITY_INVALID",
                "Equipment discovery capability evidence is invalid.",
            )
        aggregate_bytes += len(capability_bytes)
        if aggregate_bytes > MAX_DISCOVERY_AGGREGATE_BYTES:
            return _aggregate_error()
        capability_error = _validate_capability(capability, request)
        if capability_error is not None:
            return capability_error
        try:
            response = adapter.discover(request)
        except (Exception, SystemExit):  # noqa: BLE001 - untrusted adapter boundary
            return _error("DISCOVERY_FAILED", "Equipment discovery failed.")
        response_bytes = _bounded_json_bytes(response, MAX_DISCOVERY_RESPONSE_BYTES)
        if response_bytes is None:
            return _error(
                "DISCOVERY_RESPONSE_INVALID",
                "Equipment discovery response is invalid.",
            )
        aggregate_bytes += len(response_bytes)
        if aggregate_bytes > MAX_DISCOVERY_AGGREGATE_BYTES:
            return _aggregate_error()
        admitted = _admit_response(response, request)
        if isinstance(admitted, DiscoveryError):
            return admitted
        response_observations, complete = admitted
        all_complete = all_complete and complete
        observations.extend(response_observations)
        if len(observations) > MAX_DISCOVERY_RECORDS:
            return _aggregate_error()

    deduplicated: dict[tuple[str, str, str], EquipmentDiscoveryObservation] = {}
    for observation in observations:
        key = (
            observation.target,
            observation.equipment_identity,
            observation.capability_identity,
        )
        previous = deduplicated.get(key)
        if previous is not None:
            if previous.document != observation.document:
                return _error(
                    "DISCOVERY_CONFLICT",
                    "Equipment discovery returned conflicting observations.",
                )
            continue
        deduplicated[key] = observation
    ordered = tuple(
        sorted(
            deduplicated.values(),
            key=_observation_sort_key,
        )
    )
    if request.targets is not None:
        observed_targets = {item.target for item in ordered}
        if any(target not in observed_targets for target in request.targets):
            return _error(
                "DISCOVERY_TARGET_MISSING",
                "Equipment discovery did not report every exact target.",
            )
    digest_payload = {
        "request_digest": request.request_digest,
        "complete": all_complete,
        "observation_identities": [item.observation_identity for item in ordered],
    }
    discovery_digest = canonical_json_sha256(digest_payload)
    report_document = freeze_json(
        {
            "record_type": "EquipmentDiscoveryReport",
            "request": thaw_json(request.document),
            "complete": all_complete,
            "observations": [thaw_json(item.document) for item in ordered],
            "discovery_digest": discovery_digest,
        }
    )
    if not isinstance(report_document, FrozenJsonObject):
        return _error(
            "DISCOVERY_RESPONSE_INVALID", "Equipment discovery response is invalid."
        )
    return EquipmentDiscoveryReport(
        report_document,
        request,
        ordered,
        all_complete,
        discovery_digest,
    )


def admit_discovery_report(
    value: object,
    request: EquipmentDiscoveryRequest,
) -> EquipmentDiscoveryReport | DiscoveryError:
    """Re-admit a report returned across the controller discovery port."""

    if not _request_is_valid(request):
        return _error("DISCOVERY_REQUEST_INVALID", "Discovery request is invalid.")
    if type(value) is not EquipmentDiscoveryReport:
        return _response_error()
    if (
        type(value.request) is not EquipmentDiscoveryRequest
        or not _request_is_valid(value.request)
        or value.request != request
        or type(value.observations) is not tuple
        or len(value.observations) > MAX_DISCOVERY_RECORDS
        or type(value.complete) is not bool
        or type(value.discovery_digest) is not str
    ):
        return _response_error()
    if not _json_within_complexity(
        value.document,
        MAX_DISCOVERY_AGGREGATE_BYTES,
        frozen=True,
    ):
        return _response_error()
    try:
        report_document = thaw_json(value.document)
    except (TypeError, ValueError, RecursionError):
        return _response_error()
    if _bounded_json_bytes(report_document, MAX_DISCOVERY_AGGREGATE_BYTES) is None:
        return _response_error()
    if contains_literal_credential(report_document):
        return _literal_secret_error()
    for observation in value.observations:
        if (
            type(observation) is not EquipmentDiscoveryObservation
            or type(observation.observation_identity) is not str
            or type(observation.target) is not str
            or type(observation.equipment_identity) is not str
            or type(observation.equipment_kind) is not str
            or type(observation.present) is not bool
            or type(observation.state_digest) is not str
            or type(observation.capability_identity) is not str
        ):
            return _response_error()
        if not _json_within_complexity(
            observation.document,
            MAX_DISCOVERY_RESPONSE_BYTES,
            frozen=True,
        ):
            return _response_error()
        try:
            observation_document = thaw_json(observation.document)
        except (TypeError, ValueError, RecursionError):
            return _response_error()
        if (
            _bounded_json_bytes(
                observation_document,
                MAX_DISCOVERY_RESPONSE_BYTES,
            )
            is None
        ):
            return _response_error()
        if contains_literal_credential(observation_document):
            return _literal_secret_error()
    if not isinstance(report_document, dict) or set(report_document) != {
        "record_type",
        "request",
        "complete",
        "observations",
        "discovery_digest",
    }:
        return _response_error()
    if (
        report_document.get("record_type") != "EquipmentDiscoveryReport"
        or report_document.get("request") != thaw_json(request.document)
        or report_document.get("complete") is not value.complete
        or report_document.get("discovery_digest") != value.discovery_digest
    ):
        return _response_error()
    raw_observations = report_document.get("observations")
    if not isinstance(raw_observations, list) or len(raw_observations) != len(
        value.observations
    ):
        return _response_error()
    admitted: list[EquipmentDiscoveryObservation] = []
    for raw in raw_observations:
        if not isinstance(raw, dict) or set(raw) != (
            _PROJECTED_SEMANTIC_OBSERVATION_FIELDS | {"observation_identity"}
        ):
            return _response_error()
        observation_identity = raw.get("observation_identity")
        semantic = {
            key: member for key, member in raw.items() if key != "observation_identity"
        }
        observation = _admit_projected_observation(semantic, request)
        if (
            isinstance(observation, DiscoveryError)
            or observation.observation_identity != observation_identity
        ):
            return _response_error()
        admitted.append(observation)
    admitted_tuple = tuple(admitted)
    if admitted_tuple != value.observations:
        return _response_error()
    admitted_keys = tuple(
        (
            item.target,
            item.equipment_identity,
            item.capability_identity,
        )
        for item in admitted_tuple
    )
    if admitted_tuple != tuple(
        sorted(admitted_tuple, key=_observation_sort_key)
    ) or len(admitted_keys) != len(set(admitted_keys)):
        return _response_error()
    if request.targets is None and not value.complete:
        return _error(
            "DISCOVERY_SCOPE_INCOMPLETE",
            "Equipment discovery did not complete its all-target scope.",
        )
    if request.targets is not None:
        observed_targets = {item.target for item in admitted_tuple}
        if any(target not in observed_targets for target in request.targets):
            return _error(
                "DISCOVERY_TARGET_MISSING",
                "Equipment discovery did not report every exact target.",
            )
    expected_digest = canonical_json_sha256(
        {
            "request_digest": request.request_digest,
            "complete": value.complete,
            "observation_identities": [
                item.observation_identity for item in admitted_tuple
            ],
        }
    )
    if value.discovery_digest != expected_digest:
        return _response_error()
    canonical_document = freeze_json(
        {
            "record_type": "EquipmentDiscoveryReport",
            "request": thaw_json(request.document),
            "complete": value.complete,
            "observations": [thaw_json(item.document) for item in admitted_tuple],
            "discovery_digest": expected_digest,
        }
    )
    if type(canonical_document) is not FrozenJsonObject:
        return _response_error()
    return EquipmentDiscoveryReport(
        canonical_document,
        request,
        admitted_tuple,
        value.complete,
        expected_digest,
    )


def _request_is_valid(value: object) -> bool:
    if type(value) is not EquipmentDiscoveryRequest:
        return False
    if (
        type(value.command) is not str
        or type(value.harness) is not str
        or type(value.request_digest) is not str
        or value.targets is not None
        and (
            type(value.targets) is not tuple
            or any(type(target) is not str for target in value.targets)
        )
        or not _json_within_complexity(
            value.document,
            MAX_DISCOVERY_RESPONSE_BYTES,
            frozen=True,
        )
    ):
        return False
    try:
        document = thaw_json(value.document)
    except (TypeError, ValueError, RecursionError):
        return False
    if (
        _bounded_json_bytes(document, MAX_DISCOVERY_RESPONSE_BYTES) is None
        or not isinstance(document, dict)
        or set(document) != _REQUEST_FIELDS
    ):
        return False
    if any(type(document.get(field)) is not str for field in _REQUEST_STRING_FIELDS):
        return False
    target_scope = document.get("target_scope")
    targets: tuple[str, ...] | None
    if target_scope == {"all": True}:
        targets = None
    elif (
        isinstance(target_scope, dict)
        and set(target_scope) == {"targets"}
        and isinstance(target_scope.get("targets"), list)
    ):
        raw_targets = target_scope["targets"]
        if any(type(target) is not str for target in raw_targets):
            return False
        targets = tuple(raw_targets)
    else:
        return False
    try:
        expected = EquipmentDiscoveryRequest.create(
            command=cast(str, document["command"]),
            candidate_identity=cast(str, document["candidate_identity"]),
            implementation_manifest_digest=cast(
                str, document["implementation_manifest_digest"]
            ),
            catalog_digest=cast(str, document["catalog_digest"]),
            lock_digest=cast(str, document["lock_digest"]),
            capability_identity=cast(str, document["capability_identity"]),
            capability_digest=cast(str, document["capability_digest"]),
            manager_version_evidence_digest=cast(
                str, document["manager_version_evidence_digest"]
            ),
            harness=cast(str, document["harness"]),
            targets=targets,
        )
    except (TypeError, ValueError, RecursionError):
        return False
    return value == expected


def _bounded_json_bytes(value: object, maximum: int) -> bytes | None:
    if not _json_within_complexity(value, maximum, frozen=False):
        return None
    try:
        encoded = canonical_json_bytes(value)
    except (TypeError, UnicodeError, ValueError, RecursionError):
        return None
    if len(encoded) > maximum:
        return None
    return encoded


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


def _json_within_complexity(
    value: object,
    maximum: int,
    *,
    frozen: bool,
) -> bool:
    nodes = 0
    encoded_bytes = 0
    pending: list[tuple[object, int]] = [(value, 1)]
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > MAX_DISCOVERY_NODES or depth > MAX_DISCOVERY_DEPTH:
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
        elif not frozen and type(current) is dict:
            if nodes + len(pending) + len(current) > MAX_DISCOVERY_NODES:
                return False
            encoded_bytes += 2 + len(current) + max(0, len(current) - 1)
            if encoded_bytes > maximum:
                return False
            for key, member in current.items():
                if type(key) is not str:
                    return False
                key_bytes = _json_string_byte_length(
                    key,
                    maximum - encoded_bytes,
                )
                if key_bytes is None:
                    return False
                encoded_bytes += key_bytes
                pending.append((member, depth + 1))
        elif not frozen and type(current) is list:
            if nodes + len(pending) + len(current) > MAX_DISCOVERY_NODES:
                return False
            encoded_bytes += 2 + max(0, len(current) - 1)
            if encoded_bytes > maximum:
                return False
            pending.extend((member, depth + 1) for member in current)
        elif frozen and type(current) is FrozenJsonObject:
            items = object.__getattribute__(current, "_items")
            if type(items) is not tuple:
                return False
            if nodes + len(pending) + len(items) > MAX_DISCOVERY_NODES:
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
        elif frozen and type(current) is tuple:
            if nodes + len(pending) + len(current) > MAX_DISCOVERY_NODES:
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


def _validate_capability(
    value: object,
    request: EquipmentDiscoveryRequest,
) -> DiscoveryError | None:
    if type(value) is not dict:
        return _capability_error()
    if contains_literal_credential(value):
        return _literal_secret_error()
    expected = {
        "supports_equipment_discovery": True,
        "harness": request.document["harness"],
        "capability_identity": request.document["capability_identity"],
        "capability_digest": request.document["capability_digest"],
        "manager_version_evidence_digest": request.document[
            "manager_version_evidence_digest"
        ],
    }
    if value != expected:
        return _capability_error()
    return None


def _admit_response(
    value: object,
    request: EquipmentDiscoveryRequest,
) -> tuple[tuple[EquipmentDiscoveryObservation, ...], bool] | DiscoveryError:
    if type(value) is not dict:
        return _response_error()
    if contains_literal_credential(value):
        return _literal_secret_error()
    if not set(value).issubset(
        {"request_digest", "complete", "observations"} | _EPHEMERAL_FIELDS
    ):
        return _response_error()
    if value.get("request_digest") != request.request_digest:
        return _response_error()
    complete = value.get("complete")
    if type(complete) is not bool:
        return _response_error()
    if request.targets is None and not complete:
        return _error(
            "DISCOVERY_SCOPE_INCOMPLETE",
            "Equipment discovery did not complete its all-target scope.",
        )
    raw_observations = value.get("observations")
    if (
        type(raw_observations) is not list
        or len(raw_observations) > MAX_DISCOVERY_RECORDS
    ):
        return _response_error()
    admitted: list[EquipmentDiscoveryObservation] = []
    for raw in raw_observations:
        observation = _admit_observation(raw, request)
        if isinstance(observation, DiscoveryError):
            return observation
        admitted.append(observation)
    return tuple(admitted), complete


def _bounded_string_matches(value: object, pattern: re.Pattern[str]) -> bool:
    return (
        type(value) is str
        and len(value) <= MAX_DISCOVERY_FIELD_CHARACTERS
        and pattern.fullmatch(value) is not None
    )


def _hostname_has_valid_dns_labels(value: str) -> bool:
    return len(value) <= 253 and all(
        re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?",
            label,
        )
        is not None
        for label in value.split(".")
    )


def _static_credential_free_https_url_is_valid(value: object) -> bool:
    if type(value) is not str or len(value) > MAX_DISCOVERY_FIELD_CHARACTERS:
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    path_segments = tuple(segment for segment in parsed.path.split("/") if segment)
    return (
        parsed.scheme == "https"
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
            and re.fullmatch(r"[A-Za-z0-9._~-]+", segment) is not None
            and re.fullmatch(
                r"(?i)(?:bearer|api[-_]?key|access[-_]?token|token|secret|"
                r"password|client[-_]?secret|credential)(?:[-_.=:].*)?",
                segment,
            )
            is None
            for segment in path_segments
        )
    )


def _public_git_repository_is_valid(value: object) -> bool:
    if type(value) is not str or not _static_credential_free_https_url_is_valid(value):
        return False
    parsed = urlsplit(value)
    return parsed.path not in {"", "/"} and parsed.path.endswith(".git")


def _artifact_subpath_is_valid(value: str) -> bool:
    if not value or len(value) > MAX_DISCOVERY_FIELD_CHARACTERS:
        return False
    return (
        "%" not in value
        and "\\" not in value
        and all(
            segment not in {"", ".", ".."}
            and re.fullmatch(r"[A-Za-z0-9._~-]+", segment) is not None
            for segment in value.split("/")
        )
    )


def _immutable_artifact_ref_is_valid(
    value: object,
    repository: object,
    revision: object,
) -> bool:
    if (
        type(value) is not str
        or len(value) > MAX_DISCOVERY_FIELD_CHARACTERS
        or type(repository) is not str
        or type(revision) is not str
    ):
        return False
    expected = f"git+{repository}@{revision}"
    if value == expected:
        return True
    prefix = f"{expected}#"
    if not value.startswith(prefix):
        return False
    subpaths = value[len(prefix) :].split(",")
    return bool(subpaths) and all(_artifact_subpath_is_valid(item) for item in subpaths)


def _secret_reference_identities(
    value: object,
) -> set[tuple[str, str]] | None:
    if type(value) is not list or len(value) > MAX_DISCOVERY_REFERENCES:
        return None
    identities: list[tuple[str, str]] = []
    for reference in value:
        if type(reference) is not dict or set(reference) != {"kind", "name"}:
            return None
        kind = reference.get("kind")
        name = reference.get("name")
        if kind == "environment_variable":
            if not _bounded_string_matches(name, _ENVIRONMENT_VARIABLE_PATTERN):
                return None
        elif kind == "secret_profile":
            if not _bounded_string_matches(name, _SECRET_PROFILE_PATTERN):
                return None
        else:
            return None
        assert type(kind) is str
        assert type(name) is str
        identities.append((kind, name))
    if len(identities) != len(set(identities)):
        return None
    return set(identities)


def _literal_expects_secret_argument(value: str) -> bool:
    return value.strip().lower().rstrip(":=") in {
        "--api-key",
        "--apikey",
        "--access-token",
        "--token",
        "--password",
        "--client-secret",
        "authorization",
        "proxy-authorization",
        "x-api-key",
    }


def _provider_evidence_is_valid(
    value: object,
    harness: str,
    declared_secret_references: set[tuple[str, str]],
) -> bool:
    if type(value) is not dict:
        return False
    kind = value.get("kind")
    if kind == "standalone_skill":
        return (
            not declared_secret_references
            and set(value) == {"kind", "canonical_root"}
            and value.get("canonical_root") == "agents_skills"
        )
    if kind == "native_plugin":
        return (
            not declared_secret_references
            and set(value) == {"kind", "manager", "plugin_id", "scope"}
            and value.get("manager") == harness
            and value.get("scope") == "user"
            and _bounded_string_matches(value.get("plugin_id"), _PLUGIN_ID_PATTERN)
        )
    if kind != "direct_mcp":
        return False
    if not _bounded_string_matches(value.get("server_name"), _PUBLIC_NAME_PATTERN):
        return False
    if value.get("transport") == "http":
        return (
            not declared_secret_references
            and set(value) == {"kind", "server_name", "transport", "url"}
            and _static_credential_free_https_url_is_valid(value.get("url"))
        )
    if value.get("transport") != "stdio" or set(value) != {
        "kind",
        "server_name",
        "transport",
        "command",
        "arguments",
    }:
        return False
    command = value.get("command")
    arguments = value.get("arguments")
    if (
        not _bounded_string_matches(command, _PUBLIC_NAME_PATTERN)
        or type(arguments) is not list
        or len(arguments) > MAX_DISCOVERY_PROVIDER_ARGUMENTS
    ):
        return False
    assert type(command) is str
    secret_value_expected = False
    consumed_secret_references: list[tuple[str, str]] = []
    for index, argument in enumerate(arguments):
        if type(argument) is not dict:
            return False
        if set(argument) == {"literal"}:
            literal = argument.get("literal")
            if secret_value_expected or not _bounded_string_matches(
                literal, _PROVIDER_LITERAL_PATTERN
            ):
                return False
            assert type(literal) is str
            secret_value_expected = _literal_expects_secret_argument(literal)
            continue
        if set(argument) == {"secret_reference", "template"}:
            reference = argument.get("secret_reference")
            template = argument.get("template")
            if type(reference) is not str or not _bounded_string_matches(
                template, _SECRET_TEMPLATE_PATTERN
            ):
                return False
            identity = ("environment_variable", reference)
            if identity not in declared_secret_references:
                return False
            consumed_secret_references.append(identity)
            secret_value_expected = False
            continue
        if set(argument) == {"secret_profile_reference"}:
            reference = argument.get("secret_profile_reference")
            if type(reference) is not str or command != "secret-exec" or index != 0:
                return False
            identity = ("secret_profile", reference)
            if identity not in declared_secret_references:
                return False
            consumed_secret_references.append(identity)
            secret_value_expected = False
            continue
        return False
    return (
        not secret_value_expected
        and len(consumed_secret_references) == len(set(consumed_secret_references))
        and set(consumed_secret_references) == declared_secret_references
        and (
            command != "secret-exec"
            or bool(consumed_secret_references)
            and consumed_secret_references[0][0] == "secret_profile"
        )
    )


def _configured_source_is_valid(value: object) -> bool:
    if type(value) is not dict:
        return False
    if value.get("kind") == "git":
        return (
            set(value)
            in (
                {"kind", "repository"},
                {"branch", "kind", "repository"},
            )
            and _public_git_repository_is_valid(value.get("repository"))
            and (
                "branch" not in value
                or _bounded_string_matches(value.get("branch"), _GIT_BRANCH_PATTERN)
            )
        )
    if value.get("kind") != "native_manager" or set(value) not in (
        {"kind", "manager", "package"},
        {"channel", "kind", "manager", "package"},
    ):
        return False
    manager = value.get("manager")
    package = value.get("package")
    if manager == "http":
        return (
            set(value) == {"channel", "kind", "manager", "package"}
            and _static_credential_free_https_url_is_valid(package)
            and value.get("channel") == "static"
        )
    return (
        manager in {*_SEMANTIC_VERSION_MANAGERS, "codex"}
        and _bounded_string_matches(
            package,
            (
                _NPX_PACKAGE_PATTERN
                if manager == "npx"
                else _REGISTRY_QUALIFIED_NATIVE_PACKAGE_PATTERN
            ),
        )
        and (
            "channel" not in value
            or value.get("channel") != "latest"
            and _bounded_string_matches(value.get("channel"), _NATIVE_CHANNEL_PATTERN)
        )
    )


def _resolved_version_is_valid(manager: object, value: object) -> bool:
    if type(value) is not dict:
        return False
    if manager in _SEMANTIC_VERSION_MANAGERS:
        return (
            set(value) == {"kind", "value"}
            and value.get("kind") == "semantic_version"
            and _bounded_string_matches(
                value.get("value"),
                _SEMANTIC_VERSION_PATTERN,
            )
        )
    if manager == "codex":
        return (
            set(value) == {"kind", "value"}
            and value.get("kind") == "revision"
            and _bounded_string_matches(value.get("value"), _CODEX_REVISION_PATTERN)
        )
    return manager == "http" and value == {"kind": "static_source"}


def _resolved_source_matches_policy(source: object, resolved: object) -> bool:
    if type(source) is not dict or type(resolved) is not dict:
        return False
    if source.get("kind") == "git":
        return (
            set(resolved) == {"kind", "revision"}
            and resolved.get("kind") == "git"
            and _bounded_string_matches(
                resolved.get("revision"),
                _GIT_REVISION_PATTERN,
            )
        )
    return (
        source.get("kind") == "native_manager"
        and set(resolved) == {"kind", "version"}
        and resolved.get("kind") == "native_manager"
        and _resolved_version_is_valid(
            source.get("manager"),
            resolved.get("version"),
        )
    )


def _source_evidence_is_valid(value: object) -> bool:
    if type(value) is not dict or set(value) != {
        "distribution_identity",
        "source",
        "resolved_source",
        "source_manifest_digest",
    }:
        return False
    source = value.get("source")
    resolved = value.get("resolved_source")
    return (
        _bounded_string_matches(
            value.get("distribution_identity"),
            _DISTRIBUTION_PATTERN,
        )
        and _configured_source_is_valid(source)
        and _resolved_source_matches_policy(source, resolved)
        and _bounded_string_matches(
            value.get("source_manifest_digest"), _DIGEST_PATTERN
        )
    )


def _restore_evidence_is_valid(value: object, source_evidence: object) -> bool:
    if type(value) is not dict or type(source_evidence) is not dict:
        return False
    resolved = source_evidence.get("resolved_source")
    source = source_evidence.get("source")
    if type(resolved) is not dict or type(source) is not dict:
        return False
    if resolved.get("kind") == "git":
        revision = resolved.get("revision")
        repository = source.get("repository")
        return (
            set(value)
            == {
                "class",
                "revision",
                "artifact_ref",
                "content_digest",
                "native_update_control",
            }
            and value.get("class") == "immutable"
            and value.get("revision") == revision
            and _immutable_artifact_ref_is_valid(
                value.get("artifact_ref"),
                repository,
                revision,
            )
            and _bounded_string_matches(value.get("content_digest"), _DIGEST_PATTERN)
            and value.get("native_update_control") == "not_applicable"
        )
    if resolved.get("kind") != "native_manager":
        return False
    manager = source.get("manager")
    package = source.get("package")
    channel = source.get("channel", "latest")
    version = resolved.get("version")
    if type(version) is not dict:
        return False
    version_value = version.get("value")
    if manager == "npx" and type(version_value) is str:
        expected_channel = f"npm:{version_value}"
        expected_baseline = f"{package}@{version_value}"
    elif manager == "http" and version == {"kind": "static_source"}:
        expected_channel = channel
        expected_baseline = package
    elif type(version_value) is str:
        expected_channel = channel
        expected_baseline = version_value
    else:
        return False
    return (
        set(value)
        == {
            "class",
            "channel",
            "reviewed_baseline",
            "observation_source",
            "native_update_control",
        }
        and value.get("class") == "native_rolling"
        and value.get("channel") == expected_channel
        and value.get("reviewed_baseline") == expected_baseline
        and _bounded_string_matches(value.get("channel"), _PROVIDER_LITERAL_PATTERN)
        and _bounded_string_matches(
            value.get("reviewed_baseline"),
            _PROVIDER_LITERAL_PATTERN,
        )
        and _bounded_string_matches(
            value.get("observation_source"),
            _OBSERVATION_SOURCE_PATTERN,
        )
        and value.get("native_update_control")
        in {"unknown", "suppressible", "unsuppressible"}
    )


def _normalized_state_is_valid(value: object, present: bool) -> bool:
    if (
        type(value) is not dict
        or not value
        or not set(value).issubset(
            {
                "present",
                "enabled",
                "configuration_digest",
                "native_update_control",
                "native_update_suppression_state",
            }
        )
    ):
        return False
    if "present" in value and value.get("present") is not present:
        return False
    if "enabled" in value and type(value.get("enabled")) is not bool:
        return False
    if "configuration_digest" in value and not _bounded_string_matches(
        value.get("configuration_digest"),
        _DIGEST_PATTERN,
    ):
        return False
    native_control = value.get("native_update_control")
    suppression_state = value.get("native_update_suppression_state")
    if "native_update_control" in value and native_control not in {
        "unknown",
        "suppressible",
        "unsuppressible",
        "not_applicable",
    }:
        return False
    if "native_update_suppression_state" in value and suppression_state not in {
        "enabled",
        "disabled",
        "unavailable",
        "unknown",
        "not_applicable",
    }:
        return False
    return ("native_update_control" in value) is (
        "native_update_suppression_state" in value
    )


def _evidence_references_are_valid(value: object) -> bool:
    if type(value) is not list or len(value) > MAX_DISCOVERY_REFERENCES:
        return False
    identities: list[tuple[str, str]] = []
    for reference in value:
        if type(reference) is not dict or set(reference) != {"kind", "reference"}:
            return False
        kind = reference.get("kind")
        identity = reference.get("reference")
        if kind not in {"filesystem", "manager"} or not _bounded_string_matches(
            identity,
            _EVIDENCE_REFERENCE_PATTERN,
        ):
            return False
        assert type(kind) is str
        assert type(identity) is str
        identities.append((kind, identity))
    return len(identities) == len(set(identities))


def _observation_evidence_is_valid(
    semantic: dict[str, object],
    request: EquipmentDiscoveryRequest,
) -> bool:
    secret_references = _secret_reference_identities(semantic.get("secret_references"))
    if secret_references is None:
        return False
    present = semantic.get("present")
    assert type(present) is bool
    source_evidence = semantic.get("source_evidence")
    return (
        _provider_evidence_is_valid(
            semantic.get("provider_evidence"),
            request.harness,
            secret_references,
        )
        and _source_evidence_is_valid(source_evidence)
        and _restore_evidence_is_valid(
            semantic.get("restore_evidence"),
            source_evidence,
        )
        and _normalized_state_is_valid(semantic.get("normalized_state"), present)
        and _evidence_references_are_valid(semantic.get("evidence_references"))
    )


def _projected_observation_evidence_is_valid(
    semantic: dict[str, object],
) -> bool:
    present = semantic.get("present")
    assert type(present) is bool
    return all(
        _bounded_string_matches(
            semantic.get(f"{field}_digest"),
            _DIGEST_PATTERN,
        )
        for field in _RAW_EVIDENCE_FIELDS
    ) and _normalized_state_is_valid(semantic.get("normalized_state"), present)


def _observation_identity_bindings_are_valid(
    semantic: dict[str, object],
    request: EquipmentDiscoveryRequest,
) -> bool:
    target = semantic.get("target")
    equipment_identity = semantic.get("equipment_identity")
    equipment_kind = semantic.get("equipment_kind")
    if not _bounded_string_matches(target, _TARGET_PATTERN):
        return False
    assert type(target) is str
    match = _TARGET_PATTERN.fullmatch(target)
    assert match is not None
    if (
        match.group("harness") != request.harness
        or match.group("equipment_identity") != equipment_identity
        or request.targets is not None
        and target not in request.targets
    ):
        return False
    if (
        type(equipment_identity) is not str
        or len(equipment_identity) > MAX_DISCOVERY_FIELD_CHARACTERS
        or type(equipment_kind) is not str
        or equipment_kind not in {"skill", "plugin", "mcp", "hook", "other"}
        or equipment_kind != equipment_identity.split(":", 1)[0]
    ):
        return False
    if type(semantic.get("present")) is not bool:
        return False
    if (
        not _bounded_string_matches(
            semantic.get("capability_identity"),
            _CAPABILITY_PATTERN,
        )
        or semantic.get("capability_identity")
        != request.document["capability_identity"]
        or not _bounded_string_matches(semantic.get("state_digest"), _DIGEST_PATTERN)
    ):
        return False
    return all(
        semantic.get(field) == request.document[field]
        for field in (
            "capability_digest",
            "manager_version_evidence_digest",
        )
    )


def _build_observation(
    semantic: dict[str, object],
) -> EquipmentDiscoveryObservation | DiscoveryError:
    target = semantic["target"]
    equipment_identity = semantic["equipment_identity"]
    equipment_kind = semantic["equipment_kind"]
    present = semantic["present"]
    state_digest = semantic["state_digest"]
    capability_identity = semantic["capability_identity"]
    try:
        observation_identity = canonical_json_sha256(semantic)
        document = freeze_json(
            semantic | {"observation_identity": observation_identity}
        )
    except (TypeError, UnicodeError, ValueError, RecursionError):
        return _response_error()
    if not isinstance(document, FrozenJsonObject):
        return _response_error()
    assert type(target) is str
    assert type(equipment_identity) is str
    assert type(equipment_kind) is str
    assert type(present) is bool
    assert type(state_digest) is str
    assert type(capability_identity) is str
    return EquipmentDiscoveryObservation(
        document,
        observation_identity,
        target,
        equipment_identity,
        equipment_kind,
        present,
        state_digest,
        capability_identity,
    )


def _admit_observation(
    value: object,
    request: EquipmentDiscoveryRequest,
) -> EquipmentDiscoveryObservation | DiscoveryError:
    if type(value) is not dict:
        return _response_error()
    if contains_literal_credential(value):
        return _literal_secret_error()
    keys = set(value)
    if not _RAW_SEMANTIC_OBSERVATION_FIELDS.issubset(keys) or not keys.issubset(
        _RAW_SEMANTIC_OBSERVATION_FIELDS | _EPHEMERAL_FIELDS
    ):
        return _response_error()
    semantic = {key: value[key] for key in _RAW_SEMANTIC_OBSERVATION_FIELDS}
    if not _observation_identity_bindings_are_valid(semantic, request):
        return _response_error()
    if not _observation_evidence_is_valid(semantic, request):
        return _response_error()
    if semantic["state_digest"] != canonical_json_sha256(semantic["normalized_state"]):
        return _response_error()
    projected = {key: semantic[key] for key in _COMMON_OBSERVATION_FIELDS} | {
        f"{field}_digest": canonical_json_sha256(semantic[field])
        for field in _RAW_EVIDENCE_FIELDS
    }
    return _build_observation(projected)


def _admit_projected_observation(
    value: object,
    request: EquipmentDiscoveryRequest,
) -> EquipmentDiscoveryObservation | DiscoveryError:
    if (
        type(value) is not dict
        or set(value) != _PROJECTED_SEMANTIC_OBSERVATION_FIELDS
        or contains_literal_credential(value)
    ):
        return _response_error()
    semantic = {key: value[key] for key in _PROJECTED_SEMANTIC_OBSERVATION_FIELDS}
    if (
        not _observation_identity_bindings_are_valid(semantic, request)
        or not _projected_observation_evidence_is_valid(semantic)
        or semantic["state_digest"]
        != canonical_json_sha256(semantic["normalized_state"])
    ):
        return _response_error()
    return _build_observation(semantic)


def _error(code: str, message: str) -> DiscoveryError:
    return DiscoveryError(code, message)


def _literal_secret_error() -> DiscoveryError:
    return _error(
        "DISCOVERY_LITERAL_SECRET",
        "Equipment discovery contains literal secret material.",
    )


def _capability_error() -> DiscoveryError:
    return _error(
        "DISCOVERY_CAPABILITY_INVALID",
        "Equipment discovery capability evidence is invalid.",
    )


def _response_error() -> DiscoveryError:
    return _error(
        "DISCOVERY_RESPONSE_INVALID",
        "Equipment discovery response is invalid.",
    )


def _aggregate_error() -> DiscoveryError:
    return _error(
        "DISCOVERY_LIMIT_EXCEEDED",
        "Equipment discovery exceeds its collection limits.",
    )


def _observation_sort_key(
    observation: EquipmentDiscoveryObservation,
) -> tuple[str, str, str]:
    return (
        observation.target,
        observation.equipment_identity,
        observation.capability_identity,
    )
