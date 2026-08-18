"""Read-only authored proposals derived from factual equipment discovery."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol

from .canonical import canonical_json_bytes, canonical_json_sha256
from .discovery import (
    MAX_DISCOVERY_AGGREGATE_BYTES,
    MAX_DISCOVERY_RECORDS,
    DiscoveryError,
    EquipmentDiscoveryObservation,
    EquipmentDiscoveryReport,
    EquipmentDiscoveryRequest,
    admit_discovery_report,
)
from .model import FrozenJsonObject, ValidatedCatalogLock, freeze_json, thaw_json
from .secrets import contains_literal_credential
from .validator import validate_catalog_lock

_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_CANDIDATE_PATTERN = re.compile(r"candidate:[a-z0-9][a-z0-9:._/-]*")
_CAPABILITY_PATTERN = re.compile(r"capability:[a-z0-9][a-z0-9._/-]*")
_TARGET_PATTERN = re.compile(
    r"(?P<harness>claude|codex|cursor)/"
    r"(?P<equipment_identity>(?:skill|plugin|mcp|hook|other):"
    r"[a-z0-9][a-z0-9._/-]*)"
)
MAX_ADD_CATALOG_BYTES = 4 * 1024 * 1024
MAX_ADD_LOCK_BYTES = 16 * 1024 * 1024
MAX_ADD_PROPOSAL_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class AuthoringError:
    """One stable, redacted failure from an authored proposal command."""

    code: str
    message: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", self.code) is None:
            raise ValueError("authoring error codes must be stable identifiers")
        if type(self.message) is not str or not self.message:
            raise ValueError("authoring errors require a message")
        if contains_literal_credential({"message": self.message}):
            raise ValueError("authoring errors must not contain literal secrets")


class DiscoveryPort(Protocol):
    """The controller-facing port for one complete discovery pass."""

    def discover(
        self,
        request: EquipmentDiscoveryRequest,
    ) -> EquipmentDiscoveryReport | DiscoveryError:
        """Collect one fresh atomic report for the exact request."""

        ...


@dataclass(frozen=True, slots=True)
class DiscoveryHarnessBinding:
    """One harness's exact capability and manager-evidence binding."""

    capability_identity: str
    capability_digest: str
    manager_version_evidence_digest: str
    harness: str

    def __post_init__(self) -> None:
        _validate_harness_binding(
            self.capability_identity,
            self.capability_digest,
            self.manager_version_evidence_digest,
            self.harness,
        )


@dataclass(frozen=True, slots=True)
class DiscoverySelection:
    """Bindings for all or exact unmanaged targets across harnesses."""

    candidate_identity: str
    implementation_manifest_digest: str
    bindings: tuple[DiscoveryHarnessBinding, ...]
    targets: tuple[str, ...] | None

    def __post_init__(self) -> None:
        _validate_selection(
            self.candidate_identity,
            self.implementation_manifest_digest,
            self.bindings,
            self.targets,
            targets_required=False,
        )

    def requests(
        self,
        command: str,
        base: ValidatedCatalogLock,
    ) -> tuple[EquipmentDiscoveryRequest, ...]:
        """Bind each selected harness to one validated catalog and lock."""

        _require_base(base)
        return _requests(
            command,
            base,
            self.candidate_identity,
            self.implementation_manifest_digest,
            self.bindings,
            self.targets,
        )


@dataclass(frozen=True, slots=True)
class TargetSelection:
    """Bindings for one or more exact targets selected by the add command."""

    candidate_identity: str
    implementation_manifest_digest: str
    bindings: tuple[DiscoveryHarnessBinding, ...]
    targets: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_selection(
            self.candidate_identity,
            self.implementation_manifest_digest,
            self.bindings,
            self.targets,
            targets_required=True,
        )

    def requests(
        self,
        command: str,
        base: ValidatedCatalogLock,
    ) -> tuple[EquipmentDiscoveryRequest, ...]:
        """Bind every exact target to one validated catalog and lock."""

        _require_base(base)
        return _requests(
            command,
            base,
            self.candidate_identity,
            self.implementation_manifest_digest,
            self.bindings,
            self.targets,
        )


@dataclass(frozen=True, slots=True)
class UnmanagedObservationRecord:
    """One factual catalog-absent observation in canonical form."""

    document: FrozenJsonObject
    unmanaged_identity: str
    target: str
    state_digest: str


@dataclass(frozen=True, slots=True)
class UnmanagedReport:
    """The canonical, read-only unmanaged result for one discovery report."""

    document: FrozenJsonObject
    records: tuple[UnmanagedObservationRecord, ...]
    discovery_digest: str


@dataclass(frozen=True, slots=True)
class CatalogAdditionProposal:
    """One immutable full catalog-and-lock addition proposed for review."""

    document: FrozenJsonObject
    catalog: FrozenJsonObject
    lock: FrozenJsonObject
    proposal_identity: str


@dataclass(frozen=True, slots=True)
class _AggregatedDiscovery:
    observations: tuple[EquipmentDiscoveryObservation, ...]
    discovery_digest: str


@dataclass(frozen=True, slots=True)
class _TrustedDistributionBinding:
    identity: str
    catalog: dict[str, object]
    lock: dict[str, object]
    source_evidence_digest: str


def find_unmanaged(
    base: ValidatedCatalogLock,
    selection: DiscoverySelection,
    discovery: DiscoveryPort,
) -> UnmanagedReport | AuthoringError:
    """Return only positively observed targets absent from authored state."""

    if (
        type(base) is not ValidatedCatalogLock
        or type(selection) is not DiscoverySelection
    ):
        return _authoring_error(
            "UNMANAGED_REQUEST_INVALID", "Unmanaged discovery request is invalid."
        )
    try:
        requests = selection.requests("unmanaged", base)
    except (TypeError, ValueError):
        return _authoring_error(
            "UNMANAGED_REQUEST_INVALID", "Unmanaged discovery request is invalid."
        )
    admitted = _discover_pass(discovery, requests)
    if isinstance(admitted, AuthoringError):
        return admitted

    cataloged_identities, reserved_targets = _cataloged_equipment(base)
    records: list[UnmanagedObservationRecord] = []
    for observation in admitted.observations:
        if (
            not observation.present
            or observation.equipment_identity in cataloged_identities
            or observation.target in reserved_targets
        ):
            continue
        identity_payload = {
            "target": observation.target,
            "state_digest": observation.state_digest,
            "catalog_digest": base.catalog.digest,
            "discovery_digest": admitted.discovery_digest,
        }
        unmanaged_identity = canonical_json_sha256(identity_payload)
        document = freeze_json(
            identity_payload
            | {
                "unmanaged_identity": unmanaged_identity,
                "observation": thaw_json(observation.document),
            }
        )
        if not isinstance(document, FrozenJsonObject):
            return _authoring_error(
                "UNMANAGED_RESULT_INVALID", "Unmanaged result is invalid."
            )
        records.append(
            UnmanagedObservationRecord(
                document,
                unmanaged_identity,
                observation.target,
                observation.state_digest,
            )
        )
    ordered = tuple(sorted(records, key=_unmanaged_sort_key))
    report_document = freeze_json(
        {
            "command": "unmanaged",
            "catalog_digest": base.catalog.digest,
            "lock_digest": base.lock.digest,
            "discovery_digest": admitted.discovery_digest,
            "records": [thaw_json(item.document) for item in ordered],
        }
    )
    if not isinstance(report_document, FrozenJsonObject):
        return _authoring_error(
            "UNMANAGED_RESULT_INVALID", "Unmanaged result is invalid."
        )
    return UnmanagedReport(report_document, ordered, admitted.discovery_digest)


def propose_add(
    base: ValidatedCatalogLock,
    selection: TargetSelection,
    discovery: DiscoveryPort,
) -> CatalogAdditionProposal | AuthoringError:
    """Discover twice, revalidate exactly, and emit one authored proposal."""

    if type(base) is not ValidatedCatalogLock or type(selection) is not TargetSelection:
        return _authoring_error("ADD_REQUEST_INVALID", "Add request is invalid.")
    try:
        requests = selection.requests("add", base)
    except (TypeError, ValueError):
        return _authoring_error("ADD_REQUEST_INVALID", "Add request is invalid.")
    cataloged_identities, reserved_targets = _cataloged_equipment(base)
    for target in selection.targets:
        equipment_identity = target.split("/", 1)[1]
        if equipment_identity in cataloged_identities or target in reserved_targets:
            return _authoring_error(
                "ADD_TARGET_NOT_UNMANAGED",
                "A selected target is already represented in authored state.",
            )

    first = _discover_pass(discovery, requests)
    if isinstance(first, AuthoringError):
        return first
    first_observations = _positive_targets(first, selection.targets)
    if first_observations is None:
        return _authoring_error(
            "ADD_TARGET_NOT_UNMANAGED",
            "Every selected target must be positively observed as unmanaged.",
        )

    proposed_catalog = thaw_json(base.catalog.document)
    proposed_lock = thaw_json(base.lock.document)
    if not isinstance(proposed_catalog, dict) or not isinstance(proposed_lock, dict):
        return _authoring_error("ADD_PROPOSAL_INVALID", "Add proposal is invalid.")
    error = _add_to_documents(
        proposed_catalog,
        proposed_lock,
        first_observations,
    )
    if error is not None:
        return error
    catalog_document = freeze_json(proposed_catalog)
    lock_document = freeze_json(proposed_lock)
    if not isinstance(catalog_document, FrozenJsonObject) or not isinstance(
        lock_document, FrozenJsonObject
    ):
        return _authoring_error("ADD_PROPOSAL_INVALID", "Add proposal is invalid.")
    if (
        len(canonical_json_bytes(catalog_document)) > MAX_ADD_CATALOG_BYTES
        or len(canonical_json_bytes(lock_document)) > MAX_ADD_LOCK_BYTES
    ):
        return _authoring_error(
            "ADD_PROPOSAL_LIMIT_EXCEEDED",
            "Add proposal exceeds its byte limit.",
        )
    catalog_digest = canonical_json_sha256(catalog_document)
    lock_digest = canonical_json_sha256(lock_document)
    proposal_payload = {
        "command": "add",
        "base_catalog_digest": base.catalog.digest,
        "base_lock_digest": base.lock.digest,
        "targets": list(selection.targets),
        "observation_identities": [
            item.observation_identity for item in first_observations
        ],
        "catalog_digest": catalog_digest,
        "lock_digest": lock_digest,
        "catalog": catalog_document,
        "lock": lock_document,
    }
    proposal_identity = canonical_json_sha256(proposal_payload)
    document = freeze_json(proposal_payload | {"proposal_identity": proposal_identity})
    if not isinstance(document, FrozenJsonObject):
        return _authoring_error("ADD_PROPOSAL_INVALID", "Add proposal is invalid.")
    if len(canonical_json_bytes(document)) > MAX_ADD_PROPOSAL_BYTES:
        return _authoring_error(
            "ADD_PROPOSAL_LIMIT_EXCEEDED",
            "Add proposal exceeds its byte limit.",
        )
    second = _discover_pass(discovery, requests)
    if isinstance(second, AuthoringError):
        return second
    second_observations = _positive_targets(second, selection.targets)
    if second_observations is None:
        return _authoring_error(
            "ADD_TARGET_NOT_UNMANAGED",
            "Every selected target must be positively observed as unmanaged.",
        )
    if (
        tuple(item.document for item in first_observations)
        != tuple(item.document for item in second_observations)
        or first.discovery_digest != second.discovery_digest
    ):
        return _authoring_error(
            "ADD_OBSERVATION_CHANGED",
            "The selected target changed during add revalidation.",
        )
    return CatalogAdditionProposal(
        document,
        catalog_document,
        lock_document,
        proposal_identity,
    )


def _validate_harness_binding(
    capability_identity: str,
    capability_digest: str,
    manager_version_evidence_digest: str,
    harness: str,
) -> None:
    if _CAPABILITY_PATTERN.fullmatch(capability_identity) is None:
        raise ValueError("capability identity is invalid")
    for digest in (
        capability_digest,
        manager_version_evidence_digest,
    ):
        if _DIGEST_PATTERN.fullmatch(digest) is None:
            raise ValueError("selection digest binding is invalid")
    if harness not in {"claude", "codex", "cursor"}:
        raise ValueError("selection harness is unsupported")


def _validate_selection(
    candidate_identity: str,
    implementation_manifest_digest: str,
    bindings: tuple[DiscoveryHarnessBinding, ...],
    targets: tuple[str, ...] | None,
    *,
    targets_required: bool,
) -> None:
    if _CANDIDATE_PATTERN.fullmatch(candidate_identity) is None:
        raise ValueError("candidate identity is invalid")
    if _DIGEST_PATTERN.fullmatch(implementation_manifest_digest) is None:
        raise ValueError("installed-manifest digest is invalid")
    if (
        type(bindings) is not tuple
        or not bindings
        or any(type(item) is not DiscoveryHarnessBinding for item in bindings)
    ):
        raise TypeError("selection bindings must be a nonempty immutable tuple")
    keys = tuple((item.harness, item.capability_identity) for item in bindings)
    if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise ValueError("selection bindings must be sorted and unique")
    harnesses = tuple(item.harness for item in bindings)
    if len(harnesses) != len(set(harnesses)):
        raise ValueError("selection requires exactly one binding per harness")
    if targets is None:
        if targets_required:
            raise ValueError("target selection requires one or more exact targets")
        return
    if type(targets) is not tuple or not targets:
        raise TypeError("targets must be a nonempty immutable tuple")
    if len(targets) > MAX_DISCOVERY_RECORDS:
        raise ValueError("target selection exceeds the discovery record limit")
    if targets != tuple(sorted(targets)) or len(targets) != len(set(targets)):
        raise ValueError("targets must be sorted and unique")
    bound_harnesses = set(harnesses)
    for target in targets:
        if type(target) is not str:
            raise TypeError("targets must be strings")
        match = _TARGET_PATTERN.fullmatch(target)
        if match is None or match.group("harness") not in bound_harnesses:
            raise ValueError("every exact target requires one harness binding")


def _requests(
    command: str,
    base: ValidatedCatalogLock,
    candidate_identity: str,
    implementation_manifest_digest: str,
    bindings: tuple[DiscoveryHarnessBinding, ...],
    targets: tuple[str, ...] | None,
) -> tuple[EquipmentDiscoveryRequest, ...]:
    requests: list[EquipmentDiscoveryRequest] = []
    for binding in bindings:
        harness_targets = (
            None
            if targets is None
            else tuple(
                target for target in targets if target.startswith(f"{binding.harness}/")
            )
        )
        if harness_targets == ():
            continue
        requests.append(
            EquipmentDiscoveryRequest.create(
                command=command,
                candidate_identity=candidate_identity,
                implementation_manifest_digest=implementation_manifest_digest,
                catalog_digest=base.catalog.digest,
                lock_digest=base.lock.digest,
                capability_identity=binding.capability_identity,
                capability_digest=binding.capability_digest,
                manager_version_evidence_digest=(
                    binding.manager_version_evidence_digest
                ),
                harness=binding.harness,
                targets=harness_targets,
            )
        )
    if not requests:
        raise ValueError("selection did not produce a discovery request")
    return tuple(requests)


def _require_base(base: ValidatedCatalogLock) -> None:
    if type(base) is not ValidatedCatalogLock:
        raise TypeError("authoring requires one validated catalog and lock")


def _admit_port_report(
    value: EquipmentDiscoveryReport | DiscoveryError,
    request: EquipmentDiscoveryRequest,
) -> EquipmentDiscoveryReport | AuthoringError:
    if isinstance(value, DiscoveryError):
        return _authoring_error("DISCOVERY_FAILED", "Equipment discovery failed.")
    admitted = admit_discovery_report(value, request)
    if isinstance(admitted, DiscoveryError):
        return _authoring_error(
            admitted.code,
            admitted.message,
        )
    return admitted


def _discover_pass(
    discovery: DiscoveryPort,
    requests: tuple[EquipmentDiscoveryRequest, ...],
) -> _AggregatedDiscovery | AuthoringError:
    reports: list[EquipmentDiscoveryReport] = []
    admitted_observations = 0
    admitted_bytes = 0
    for request in requests:
        try:
            report = discovery.discover(request)
            admitted = _admit_port_report(report, request)
        except (Exception, SystemExit):  # noqa: BLE001 - untrusted discovery port
            return _authoring_error("DISCOVERY_FAILED", "Equipment discovery failed.")
        if isinstance(admitted, AuthoringError):
            return admitted
        admitted_observations += len(admitted.observations)
        admitted_bytes += len(canonical_json_bytes(admitted.document))
        if (
            admitted_observations > MAX_DISCOVERY_RECORDS
            or admitted_bytes > MAX_DISCOVERY_AGGREGATE_BYTES
        ):
            return _authoring_error(
                "DISCOVERY_LIMIT_EXCEEDED",
                "Equipment discovery exceeds its collection limits.",
            )
        reports.append(admitted)
    observations: dict[tuple[str, str, str], EquipmentDiscoveryObservation] = {}
    for report in reports:
        for observation in report.observations:
            key = (
                observation.target,
                observation.equipment_identity,
                observation.capability_identity,
            )
            previous = observations.get(key)
            if previous is not None and previous.document != observation.document:
                return _authoring_error(
                    "DISCOVERY_CONFLICT",
                    "Equipment discovery returned conflicting observations.",
                )
            observations[key] = observation
    ordered = tuple(
        sorted(
            observations.values(),
            key=_discovery_observation_sort_key,
        )
    )
    discovery_digest = canonical_json_sha256(
        {
            "request_digests": [item.request.request_digest for item in reports],
            "discovery_digests": [item.discovery_digest for item in reports],
        }
    )
    return _AggregatedDiscovery(ordered, discovery_digest)


def _positive_targets(
    report: _AggregatedDiscovery,
    targets: tuple[str, ...],
) -> tuple[EquipmentDiscoveryObservation, ...] | None:
    selected: list[EquipmentDiscoveryObservation] = []
    for target in targets:
        matches = tuple(
            item
            for item in report.observations
            if item.target == target and item.present
        )
        if len(matches) != 1:
            return None
        selected.append(matches[0])
    return tuple(selected)


def _cataloged_equipment(
    base: ValidatedCatalogLock,
) -> tuple[set[str], set[str]]:
    catalog = thaw_json(base.catalog.document)
    lock = thaw_json(base.lock.document)
    if not isinstance(catalog, dict) or not isinstance(lock, dict):
        raise TypeError("validated authored state must contain JSON objects")
    cataloged: set[str] = set()
    equipment = catalog.get("equipment")
    if isinstance(equipment, list):
        for item in equipment:
            if isinstance(item, dict) and isinstance(item.get("identity"), str):
                cataloged.add(item["identity"])
    reserved: set[str] = set()
    coverage = lock.get("coverage")
    if isinstance(coverage, list):
        for item in coverage:
            target = _target_from_record(item)
            if target is not None:
                reserved.add(target)
                if isinstance(item, dict) and isinstance(
                    item.get("equipment_identity"), str
                ):
                    cataloged.add(item["equipment_identity"])
    retirements = lock.get("retirements")
    if isinstance(retirements, list):
        for item in retirements:
            target = _target_from_record(item)
            if target is not None:
                reserved.add(target)
                if isinstance(item, dict) and isinstance(
                    item.get("equipment_identity"), str
                ):
                    cataloged.add(item["equipment_identity"])
    return cataloged, reserved


def _target_from_record(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    harness = value.get("harness")
    equipment_identity = value.get("equipment_identity")
    if not isinstance(harness, str) or not isinstance(equipment_identity, str):
        return None
    return f"{harness}/{equipment_identity}"


def _add_to_documents(
    catalog: dict[str, object],
    lock: dict[str, object],
    observations: tuple[EquipmentDiscoveryObservation, ...],
) -> AuthoringError | None:
    if not observations:
        return _policy_error()
    distributions = catalog.get("distributions")
    locked_distributions = lock.get("distributions")
    equipment = catalog.get("equipment")
    lock_coverage = lock.get("coverage")
    active_harnesses = catalog.get("active_harnesses")
    retirements = lock.get("retirements")
    history = lock.get("source_manifest_history")
    coverage_templates = catalog.get("coverage_templates")
    catalog_retirements = catalog.get("retirements")
    if (
        not isinstance(distributions, list)
        or not isinstance(locked_distributions, list)
        or not isinstance(equipment, list)
        or not isinstance(lock_coverage, list)
        or not isinstance(active_harnesses, list)
        or not isinstance(retirements, list)
        or not isinstance(history, list)
        or not isinstance(coverage_templates, list)
        or not isinstance(catalog_retirements, list)
    ):
        return _policy_error()
    active = tuple(active_harnesses)
    if not active or any(not isinstance(item, str) for item in active):
        return _policy_error()

    trusted_bindings = _trusted_distribution_bindings(
        distributions,
        locked_distributions,
    )
    if trusted_bindings is None:
        return _policy_error()
    by_distribution: dict[str, list[EquipmentDiscoveryObservation]] = {}
    for observation in observations:
        source_evidence_digest = observation.document.get("source_evidence_digest")
        if (
            not isinstance(source_evidence_digest, str)
            or _DIGEST_PATTERN.fullmatch(source_evidence_digest) is None
        ):
            return _policy_error()
        trusted_binding = trusted_bindings.get(source_evidence_digest)
        if trusted_binding is None:
            return _policy_error()
        by_distribution.setdefault(trusted_binding.identity, []).append(observation)

    distribution_plans: dict[
        str,
        tuple[list[object], list[object], dict[str, object], str, set[str]],
    ] = {}
    equipment_plans: dict[str, tuple[str, dict[str, object]]] = {}
    for distribution_identity in sorted(by_distribution):
        distribution_observations = by_distribution[distribution_identity]
        first_observation = distribution_observations[0]
        source_evidence_digest = first_observation.document.get(
            "source_evidence_digest"
        )
        restore_evidence_digest = first_observation.document.get(
            "restore_evidence_digest"
        )
        if (
            not isinstance(source_evidence_digest, str)
            or _DIGEST_PATTERN.fullmatch(source_evidence_digest) is None
            or not isinstance(restore_evidence_digest, str)
            or _DIGEST_PATTERN.fullmatch(restore_evidence_digest) is None
        ):
            return _policy_error()
        trusted_binding = trusted_bindings.get(source_evidence_digest)
        if trusted_binding is None or trusted_binding.identity != distribution_identity:
            return _policy_error()
        distribution = trusted_binding.catalog
        locked_distribution = trusted_binding.lock
        source_manifest_digest = locked_distribution.get("source_manifest_digest")
        trusted_restore = locked_distribution.get("restore")
        if (
            not isinstance(source_manifest_digest, str)
            or _DIGEST_PATTERN.fullmatch(source_manifest_digest) is None
            or not isinstance(trusted_restore, dict)
            or canonical_json_sha256(trusted_restore) != restore_evidence_digest
        ):
            return _policy_error()
        selection = distribution.get("selection")
        locked_equipment = locked_distribution.get("equipment")
        available_equipment = locked_distribution.get("available_equipment")
        if (
            not isinstance(selection, dict)
            or set(selection) != {"equipment"}
            or not isinstance(locked_equipment, list)
            or not isinstance(available_equipment, list)
        ):
            return _policy_error()
        selected_equipment = selection.get("equipment")
        if (
            not isinstance(selected_equipment, list)
            or selected_equipment != locked_equipment
            or any(
                not isinstance(item, str)
                for item in (
                    *selected_equipment,
                    *locked_equipment,
                    *available_equipment,
                )
            )
        ):
            return _policy_error()
        planned_equipment: set[str] = set()
        for factual_observation in distribution_observations:
            if (
                factual_observation.document.get("source_evidence_digest")
                != trusted_binding.source_evidence_digest
                or factual_observation.document.get("restore_evidence_digest")
                != restore_evidence_digest
            ):
                return _policy_error()
            equipment_identity = factual_observation.equipment_identity
            equipment_kind = factual_observation.equipment_kind
            if equipment_identity not in available_equipment:
                return _policy_error()
            if equipment_identity in selected_equipment:
                return _authoring_error(
                    "ADD_TARGET_NOT_UNMANAGED",
                    "A selected target is already represented in authored state.",
                )
            coverage = _complete_peer_coverage(
                catalog,
                equipment_kind,
                selected_equipment,
            )
            if isinstance(coverage, AuthoringError):
                return coverage
            previous_plan = equipment_plans.get(equipment_identity)
            if previous_plan is not None and previous_plan != (
                equipment_kind,
                coverage,
            ):
                return _policy_error()
            equipment_plans[equipment_identity] = (equipment_kind, coverage)
            provider_evidence_digest = factual_observation.document.get(
                "provider_evidence_digest"
            )
            secret_references_digest = factual_observation.document.get(
                "secret_references_digest"
            )
            target_harness = factual_observation.target.split("/", 1)[0]
            route = _single_template_route(
                catalog,
                coverage,
                target_harness,
                distribution_identity,
            )
            if route is None:
                return _policy_error()
            trusted_provider = route.get("provider")
            trusted_secret_references = route.get("secret_references")
            if (
                not isinstance(provider_evidence_digest, str)
                or _DIGEST_PATTERN.fullmatch(provider_evidence_digest) is None
                or not isinstance(secret_references_digest, str)
                or _DIGEST_PATTERN.fullmatch(secret_references_digest) is None
                or not isinstance(trusted_provider, dict)
                or not isinstance(trusted_secret_references, list)
                or canonical_json_sha256(trusted_provider) != provider_evidence_digest
                or route.get("restore") != trusted_restore
                or canonical_json_sha256(trusted_secret_references)
                != secret_references_digest
            ):
                return _policy_error()
            planned_equipment.add(equipment_identity)
        distribution_plans[distribution_identity] = (
            selected_equipment,
            locked_equipment,
            locked_distribution,
            source_manifest_digest,
            planned_equipment,
        )

    for equipment_identity, (_, coverage) in equipment_plans.items():
        for harness in active:
            assert isinstance(harness, str)
            record = _template_record(catalog, coverage, harness)
            if record is None:
                return _policy_error()
            if record.get("outcome") in {"intentional_omission", "unsupported"}:
                continue
            route = _single_provider_route(catalog, coverage, harness)
            if route is None:
                return _policy_error()
            route_distribution = route.get("distribution")
            if not isinstance(route_distribution, str):
                return _policy_error()
            matching_distributions = [
                item
                for item in distributions
                if isinstance(item, dict) and item.get("identity") == route_distribution
            ]
            if len(matching_distributions) != 1:
                return _policy_error()
            selection = matching_distributions[0].get("selection")
            if not isinstance(selection, dict):
                return _policy_error()
            selected_equipment = selection.get("equipment")
            if not isinstance(selected_equipment, list):
                return _policy_error()
            distribution_plan = distribution_plans.get(route_distribution)
            planned_equipment = (
                distribution_plan[4] if distribution_plan is not None else set()
            )
            if (
                equipment_identity not in selected_equipment
                and equipment_identity not in planned_equipment
            ):
                return _policy_error()

    for distribution_identity in sorted(distribution_plans):
        (
            selected_equipment,
            locked_equipment,
            locked_distribution,
            source_manifest_digest,
            planned_equipment,
        ) = distribution_plans[distribution_identity]
        old_manifest = deepcopy(locked_distribution)
        old_manifest_is_retained = any(
            isinstance(item, dict)
            and item.get("source_manifest_digest") == source_manifest_digest
            for item in retirements
        )
        if old_manifest_is_retained:
            historical_matches = [
                item
                for item in history
                if isinstance(item, dict)
                and item.get("distribution_identity") == distribution_identity
                and item.get("source_manifest_digest") == source_manifest_digest
            ]
            if historical_matches and any(
                item != old_manifest for item in historical_matches
            ):
                return _policy_error()
            if not historical_matches:
                history.append(old_manifest)
        selected_equipment.extend(sorted(planned_equipment))
        locked_equipment.extend(sorted(planned_equipment))
        selected_equipment.sort(key=_string_sort_key)
        locked_equipment.sort(key=_string_sort_key)
        manifest_payload = {
            key: value
            for key, value in locked_distribution.items()
            if key != "source_manifest_digest"
        }
        locked_distribution["source_manifest_digest"] = canonical_json_sha256(
            manifest_payload
        )

    for equipment_identity in sorted(equipment_plans):
        equipment_kind, coverage = equipment_plans[equipment_identity]
        equipment.append(
            {
                "identity": equipment_identity,
                "kind": equipment_kind,
                "coverage": coverage,
            }
        )
        for harness in active:
            assert isinstance(harness, str)
            template_record = _template_record(catalog, coverage, harness)
            if template_record is None:
                return _policy_error()
            lock_coverage.append(
                {
                    "equipment_identity": equipment_identity,
                    "harness": harness,
                    "record": template_record,
                }
            )
    for identity_records in (
        distributions,
        coverage_templates,
        equipment,
        catalog_retirements,
    ):
        identity_records.sort(key=_identity_sort_key)
    locked_distributions.sort(key=_source_manifest_sort_key)
    retirements.sort(key=_identity_sort_key)
    history.sort(key=_source_manifest_sort_key)
    lock_coverage.sort(key=_lock_coverage_sort_key)
    if len(canonical_json_bytes(catalog)) > MAX_ADD_CATALOG_BYTES:
        return _authoring_error(
            "ADD_PROPOSAL_LIMIT_EXCEEDED",
            "Add proposal exceeds its byte limit.",
        )
    catalog_digest = canonical_json_sha256(catalog)
    lock["catalog_digest"] = catalog_digest
    if len(canonical_json_bytes(lock)) > MAX_ADD_LOCK_BYTES:
        return _authoring_error(
            "ADD_PROPOSAL_LIMIT_EXCEEDED",
            "Add proposal exceeds its byte limit.",
        )
    if contains_literal_credential(catalog) or contains_literal_credential(lock):
        return _authoring_error(
            "ADD_LITERAL_SECRET", "Add proposal contains literal secret material."
        )
    validation = validate_catalog_lock(catalog, lock)
    if validation.model is None:
        return _authoring_error("ADD_PROPOSAL_INVALID", "Add proposal is invalid.")
    return None


def _matching_peer_coverage(
    catalog: dict[str, object],
    equipment_kind: str,
    selected_equipment: list[object],
) -> dict[str, object] | None:
    equipment = catalog.get("equipment")
    if not isinstance(equipment, list):
        return None
    selected = {item for item in selected_equipment if isinstance(item, str)}
    candidates = [
        item["coverage"]
        for item in equipment
        if isinstance(item, dict)
        and item.get("identity") in selected
        and item.get("kind") == equipment_kind
        and isinstance(item.get("coverage"), dict)
    ]
    if not candidates or any(candidate != candidates[0] for candidate in candidates):
        return None
    coverage = candidates[0]
    assert isinstance(coverage, dict)
    return {key: value for key, value in coverage.items()}


def _complete_peer_coverage(
    catalog: dict[str, object],
    equipment_kind: str,
    selected_equipment: list[object],
) -> dict[str, object] | AuthoringError:
    active_harnesses = catalog.get("active_harnesses")
    if not isinstance(active_harnesses, list):
        return _policy_error()
    active = tuple(active_harnesses)
    if not active or any(not isinstance(item, str) for item in active):
        return _policy_error()
    coverage = _matching_peer_coverage(
        catalog,
        equipment_kind,
        selected_equipment,
    )
    if coverage is None:
        return _policy_error()
    if set(coverage) != set(active):
        return _policy_error()
    provider_count = 0
    for harness in active:
        assert isinstance(harness, str)
        record = _template_record(catalog, coverage, harness)
        if record is None:
            return _policy_error()
        if record.get("outcome") in {"intentional_omission", "unsupported"}:
            if record.get("provider_selection") != "no_provider":
                return _policy_error()
            continue
        if _single_provider_route(catalog, coverage, harness) is None:
            return _policy_error()
        provider_count += 1
    if provider_count == 0:
        return _policy_error()
    return {key: value for key, value in coverage.items()}


def _single_provider_route(
    catalog: dict[str, object],
    coverage: dict[str, object],
    harness: str,
) -> dict[str, object] | None:
    record = _template_record(catalog, coverage, harness)
    if record is None or record.get("outcome") not in {
        "managed_provider",
        "manually_managed_provider",
    }:
        return None
    provider_selection = record.get("provider_selection")
    if not isinstance(provider_selection, dict):
        return None
    routes = provider_selection.get("routes")
    if not isinstance(routes, list) or len(routes) != 1:
        return None
    route = routes[0]
    return route if isinstance(route, dict) else None


def _single_template_route(
    catalog: dict[str, object],
    coverage: dict[str, object],
    harness: str,
    distribution_identity: str,
) -> dict[str, object] | None:
    route = _single_provider_route(catalog, coverage, harness)
    if route is None or route.get("distribution") != distribution_identity:
        return None
    return route


def _template_record(
    catalog: dict[str, object],
    coverage: dict[str, object],
    harness: str,
) -> dict[str, object] | None:
    reference = coverage.get(harness)
    if not isinstance(reference, dict) or set(reference) != {"template"}:
        return None
    template_identity = reference.get("template")
    if not isinstance(template_identity, str):
        return None
    templates = catalog.get("coverage_templates")
    if not isinstance(templates, list):
        return None
    matches = [
        item
        for item in templates
        if isinstance(item, dict)
        and item.get("identity") == template_identity
        and item.get("harness") == harness
        and isinstance(item.get("record"), dict)
    ]
    if len(matches) != 1:
        return None
    record = matches[0]["record"]
    assert isinstance(record, dict)
    return {key: value for key, value in record.items()}


def _identity_sort_key(value: object) -> str:
    if isinstance(value, dict) and isinstance(value.get("identity"), str):
        return value["identity"]
    return ""


def _string_sort_key(value: object) -> str:
    return value if isinstance(value, str) else ""


def _trusted_distribution_bindings(
    distributions: list[object],
    locked_distributions: list[object],
) -> dict[str, _TrustedDistributionBinding] | None:
    bindings: dict[str, _TrustedDistributionBinding] = {}
    matched_locked_identities: set[str] = set()
    for distribution in distributions:
        if not isinstance(distribution, dict):
            return None
        distribution_identity = distribution.get("identity")
        source = distribution.get("source")
        if not isinstance(distribution_identity, str) or not isinstance(source, dict):
            return None
        matching_locked = [
            item
            for item in locked_distributions
            if isinstance(item, dict)
            and item.get("distribution_identity") == distribution_identity
        ]
        if len(matching_locked) != 1:
            return None
        locked_distribution = matching_locked[0]
        locked_source = locked_distribution.get("source")
        resolved_source = locked_distribution.get("resolved_source")
        source_manifest_digest = locked_distribution.get("source_manifest_digest")
        if (
            locked_source != source
            or not isinstance(resolved_source, dict)
            or not isinstance(source_manifest_digest, str)
            or _DIGEST_PATTERN.fullmatch(source_manifest_digest) is None
        ):
            return None
        source_evidence_digest = canonical_json_sha256(
            {
                "distribution_identity": distribution_identity,
                "source": source,
                "resolved_source": resolved_source,
                "source_manifest_digest": source_manifest_digest,
            }
        )
        if source_evidence_digest in bindings:
            return None
        bindings[source_evidence_digest] = _TrustedDistributionBinding(
            distribution_identity,
            distribution,
            locked_distribution,
            source_evidence_digest,
        )
        matched_locked_identities.add(distribution_identity)
    if len(matched_locked_identities) != len(locked_distributions):
        return None
    return bindings


def _unmanaged_sort_key(record: UnmanagedObservationRecord) -> str:
    return record.target


def _discovery_observation_sort_key(
    observation: EquipmentDiscoveryObservation,
) -> tuple[str, str, str]:
    return (
        observation.target,
        observation.equipment_identity,
        observation.capability_identity,
    )


def _lock_coverage_sort_key(value: object) -> tuple[str, str]:
    if not isinstance(value, dict):
        return ("", "")
    equipment_identity = value.get("equipment_identity")
    harness = value.get("harness")
    return (
        equipment_identity if isinstance(equipment_identity, str) else "",
        harness if isinstance(harness, str) else "",
    )


def _source_manifest_sort_key(value: object) -> tuple[str, str]:
    if not isinstance(value, dict):
        return ("", "")
    distribution_identity = value.get("distribution_identity")
    source_manifest_digest = value.get("source_manifest_digest")
    return (
        distribution_identity if isinstance(distribution_identity, str) else "",
        source_manifest_digest if isinstance(source_manifest_digest, str) else "",
    )


def _policy_error() -> AuthoringError:
    return _authoring_error(
        "ADD_AUTHORING_POLICY_REQUIRED",
        "The selected target requires an explicit authoring policy.",
    )


def _authoring_error(code: str, message: str) -> AuthoringError:
    return AuthoringError(code, message)
