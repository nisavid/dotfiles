"""Immutable production data model for agent equipment."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias, override

JsonScalar: TypeAlias = None | bool | int | float | str
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_CATALOG_SCHEMA_VERSION = "catalog/v1"
_LOCK_SCHEMA_VERSION = "lock/v1"
_INSTALLED_IMPLEMENTATION_SCHEMA_VERSION = "agent-equipment-installed-implementation/v1"
_RUNTIME_IDENTITY_PATTERN = re.compile(
    r"cpython:(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
)
_INSTALLED_IMPLEMENTATION_PATHS = (
    "bin/agent-equipment",
    "lib/agent-equipment/agent_equipment/__init__.py",
    "lib/agent-equipment/agent_equipment/_json_schema.py",
    "lib/agent-equipment/agent_equipment/canonical.py",
    "lib/agent-equipment/agent_equipment/inventory.py",
    "lib/agent-equipment/agent_equipment/model.py",
    "lib/agent-equipment/agent_equipment/resolver.py",
    "lib/agent-equipment/agent_equipment/secrets.py",
    "lib/agent-equipment/agent_equipment/validator.py",
    "lib/agent-equipment/schemas/acceptance-evidence-v1.schema.json",
    "lib/agent-equipment/schemas/adapter-contract-v1.schema.json",
    "lib/agent-equipment/schemas/captured-state-v1.schema.json",
    "lib/agent-equipment/schemas/catalog-v1.schema.json",
    "lib/agent-equipment/schemas/execution-authority-v1.schema.json",
    "lib/agent-equipment/schemas/lock-v1.schema.json",
    "lib/agent-equipment/schemas/plan-action-set-v1.schema.json",
)


@dataclass(frozen=True, slots=True)
class FrozenJsonObject(Mapping[str, "FrozenJsonValue"]):
    """An immutable JSON object whose members have deterministic key order."""

    _items: tuple[tuple[str, FrozenJsonValue], ...]

    def __post_init__(self) -> None:
        if type(self._items) is not tuple:
            raise TypeError("frozen JSON object members must be an immutable tuple")
        previous_key: str | None = None
        for item in self._items:
            if type(item) is not tuple or len(item) != 2:
                raise TypeError("frozen JSON object members must be key/value pairs")
            key, value = item
            if type(key) is not str:
                raise TypeError("JSON object member names must be strings")
            _validate_string(key)
            if previous_key is not None and key <= previous_key:
                raise ValueError(
                    "frozen JSON object member names must be unique and sorted"
                )
            _validate_frozen_json(value)
            previous_key = key

    @override
    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._items)

    @override
    def __len__(self) -> int:
        return len(self._items)

    @override
    def __getitem__(self, key: str) -> FrozenJsonValue:
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)


FrozenJsonValue: TypeAlias = (
    JsonScalar | tuple["FrozenJsonValue", ...] | FrozenJsonObject
)


def _validate_frozen_json(value: object) -> None:
    if value is None or type(value) is bool or type(value) is int:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return
    if type(value) is str:
        _validate_string(value)
        return
    if isinstance(value, FrozenJsonObject):
        return
    if type(value) is tuple:
        for item in value:
            _validate_frozen_json(item)
        return
    raise TypeError("frozen JSON values must be recursively immutable")


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    equipment_identity: str | None = None
    harness: str | None = None
    route_identity: str | None = None
    evidence_source: str | None = None

    def __post_init__(self) -> None:
        _require_string(self.code)
        _require_string(self.message)
        for value in (
            self.equipment_identity,
            self.harness,
            self.route_identity,
            self.evidence_source,
        ):
            if value is not None:
                _require_string(value)


@dataclass(frozen=True, slots=True)
class AdapterError:
    """A closed, redacted adapter error returned instead of partial state."""

    code: str
    classification: str
    message: str
    retry: str
    mutation_state: str
    evidence_references: tuple[FrozenJsonObject, ...] = ()

    def __post_init__(self) -> None:
        _require_string(self.code)
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", self.code) is None:
            raise ValueError("adapter error codes must be stable uppercase identifiers")
        if self.classification not in {
            "invalid_request",
            "unsupported",
            "capability_changed",
            "concurrent_change",
            "secret_resolution_failed",
            "native_failure",
            "partial_change",
        }:
            raise ValueError("adapter error classification is unsupported")
        if not _require_string(self.message):
            raise ValueError("adapter error messages must be nonempty")
        if self.retry not in {"never", "after_audit"}:
            raise ValueError("adapter error retry disposition is unsupported")
        if self.mutation_state not in {
            "not_started",
            "possibly_changed",
            "unknown",
        }:
            raise ValueError("adapter error mutation state is unsupported")
        if type(self.evidence_references) is not tuple or any(
            type(item) is not FrozenJsonObject for item in self.evidence_references
        ):
            raise TypeError(
                "adapter error evidence references must be an immutable typed tuple"
            )

    def as_json(self) -> FrozenJsonObject:
        """Return the common error result as immutable JSON."""

        document = freeze_json(
            {
                "status": "error",
                "code": self.code,
                "classification": self.classification,
                "message": self.message,
                "retry": self.retry,
                "mutation_state": self.mutation_state,
                "evidence_references": list(self.evidence_references),
            }
        )
        if not isinstance(document, FrozenJsonObject):
            raise TypeError("adapter error payload must be a JSON object")
        return document


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    """One immutable, digest-bound adapter capability record."""

    document: FrozenJsonObject
    capability_identity: str
    adapter_identity: str
    adapter_version: str
    harness: str
    capability_digest: str
    manager_version_evidence_digest: str

    def __post_init__(self) -> None:
        if type(self.document) is not FrozenJsonObject:
            raise TypeError("capability document must be a frozen JSON object")
        for value in (
            self.capability_identity,
            self.adapter_identity,
            self.adapter_version,
            self.harness,
        ):
            if not _require_string(value):
                raise ValueError("capability identity fields must be nonempty")
        if self.harness not in {"claude", "codex", "cursor"}:
            raise ValueError("capability harness is unsupported")
        _require_sha256(self.capability_digest)
        _require_sha256(self.manager_version_evidence_digest)
        for field, value in (
            ("capability_identity", self.capability_identity),
            ("adapter_identity", self.adapter_identity),
            ("adapter_version", self.adapter_version),
            ("harness", self.harness),
            ("capability_digest", self.capability_digest),
        ):
            if self.document.get(field) != value:
                raise ValueError(f"capability {field} must agree with its document")
        manager_evidence = self.document.get("manager_version_evidence")
        if (
            not isinstance(manager_evidence, FrozenJsonObject)
            or manager_evidence.get("evidence_digest")
            != self.manager_version_evidence_digest
        ):
            raise ValueError(
                "manager version evidence digest must agree with its document"
            )
        manager_payload = thaw_json(manager_evidence)
        capability_payload = thaw_json(self.document)
        if type(manager_payload) is not dict or type(capability_payload) is not dict:
            raise TypeError("capability digest payloads must be JSON objects")
        manager_payload.pop("evidence_digest", None)
        capability_payload.pop("capability_digest", None)
        if self.manager_version_evidence_digest != _canonical_json_digest(
            manager_payload
        ):
            raise ValueError("manager version evidence digest must be canonical")
        if self.capability_digest != _canonical_json_digest(capability_payload):
            raise ValueError("capability digest must be canonical")


@dataclass(frozen=True, slots=True)
class CapabilityDiscovery:
    """One canonical nonempty capability set or one closed adapter error."""

    records: tuple[CapabilityRecord, ...]
    error: AdapterError | None = None

    def __post_init__(self) -> None:
        if type(self.records) is not tuple or any(
            type(item) is not CapabilityRecord for item in self.records
        ):
            raise TypeError("capability records must be an immutable typed tuple")
        successful = bool(self.records) and self.error is None
        failed = not self.records and type(self.error) is AdapterError
        if not (successful or failed):
            raise ValueError(
                "capability discovery must be nonempty success or one complete error"
            )
        identities = tuple(record.capability_identity for record in self.records)
        if len(identities) != len(set(identities)):
            raise ValueError("capability identities must be globally unique")
        if self.records != tuple(sorted(self.records, key=_capability_record_sort_key)):
            raise ValueError("capability records must use canonical order")

    def as_json(self) -> FrozenJsonObject:
        """Return the closed CapabilityDiscovery envelope."""

        result: object
        if self.error is not None:
            result = self.error.as_json()
        else:
            result = {
                "status": "ok",
                "records": [record.document for record in self.records],
            }
        document = freeze_json({"record_type": "CapabilityDiscovery", "result": result})
        if not isinstance(document, FrozenJsonObject):
            raise TypeError("capability discovery payload must be a JSON object")
        return document

    @property
    def digest(self) -> str:
        """Return the canonical digest of the complete discovery envelope."""

        return _canonical_json_digest(self.as_json())


CapabilitySet: TypeAlias = CapabilityDiscovery


@dataclass(frozen=True, slots=True)
class ObserveRequest:
    """One immutable read-only observation request."""

    document: FrozenJsonObject
    request_identity: str
    capability_identity: str

    def __post_init__(self) -> None:
        if type(self.document) is not FrozenJsonObject:
            raise TypeError("observe request document must be a frozen JSON object")
        for field, value in (
            ("request_identity", self.request_identity),
            ("capability_identity", self.capability_identity),
        ):
            if not _require_string(value):
                raise ValueError("observe request identity fields must be nonempty")
            if self.document.get(field) != value:
                raise ValueError(
                    f"observe request {field} must agree with its document"
                )

    @property
    def route_identity(self) -> str:
        """Return the selected route identity."""

        value = self.document.get("route_identity")
        if type(value) is not str:
            raise ValueError("observe request route identity is unavailable")
        return value

    @property
    def harness(self) -> str:
        """Return the selected harness."""

        value = self.document.get("harness")
        if type(value) is not str:
            raise ValueError("observe request harness is unavailable")
        return value


@dataclass(frozen=True, slots=True)
class RuntimeObservation:
    """One immutable successful or failed read-only runtime observation."""

    document: FrozenJsonObject
    request_identity: str
    capability_identity: str
    route_identity: str
    state_digest: str | None
    error: AdapterError | None = None

    def __post_init__(self) -> None:
        if type(self.document) is not FrozenJsonObject:
            raise TypeError("runtime observation document must be frozen JSON")
        for field, value in (
            ("request_identity", self.request_identity),
            ("capability_identity", self.capability_identity),
            ("route_identity", self.route_identity),
        ):
            if not _require_string(value):
                raise ValueError("runtime observation identities must be nonempty")
            if self.document.get(field) != value:
                raise ValueError(
                    f"runtime observation {field} must agree with its document"
                )
        result = self.document.get("result")
        if not isinstance(result, FrozenJsonObject):
            raise TypeError("runtime observation result must be frozen JSON")
        if result.get("status") == "ok":
            if self.error is not None:
                raise ValueError("successful observations cannot carry an error")
            _require_sha256(self.state_digest)
            if result.get("state_digest") != self.state_digest:
                raise ValueError(
                    "observation state digest must agree with its document"
                )
        elif result.get("status") == "error":
            if self.state_digest is not None or type(self.error) is not AdapterError:
                raise ValueError("failed observations must carry one typed error")
        else:
            raise ValueError("runtime observation result status is unsupported")

    @property
    def candidate_identity(self) -> str:
        """Return the immutable candidate binding."""

        return _required_document_string(self.document, "candidate_identity")

    @property
    def implementation_manifest_digest(self) -> str:
        """Return the installed implementation-manifest binding."""

        return _required_document_string(
            self.document,
            "implementation_manifest_digest",
        )

    @property
    def catalog_digest(self) -> str:
        """Return the authored-catalog binding."""

        return _required_document_string(self.document, "catalog_digest")

    @property
    def lock_digest(self) -> str:
        """Return the resolved-lock binding."""

        return _required_document_string(self.document, "lock_digest")

    @property
    def capability_digest(self) -> str:
        """Return the selected capability binding."""

        return _required_document_string(self.document, "capability_digest")

    @property
    def manager_version_evidence_digest(self) -> str:
        """Return the selected manager-evidence binding."""

        return _required_document_string(
            self.document,
            "manager_version_evidence_digest",
        )

    @property
    def harness(self) -> str:
        """Return the observed harness."""

        return _required_document_string(self.document, "harness")


@dataclass(frozen=True, slots=True)
class RuntimeInventory:
    """One complete immutable, timestamp-independent runtime inventory."""

    capabilities: CapabilityDiscovery
    observations: tuple[RuntimeObservation, ...]
    candidate_identity: str
    implementation_manifest_digest: str
    catalog_digest: str
    lock_digest: str
    digest: str

    def __post_init__(self) -> None:
        if (
            type(self.capabilities) is not CapabilityDiscovery
            or self.capabilities.error
        ):
            raise TypeError("runtime inventory requires one successful capability set")
        if (
            type(self.observations) is not tuple
            or not self.observations
            or any(type(item) is not RuntimeObservation for item in self.observations)
        ):
            raise TypeError(
                "runtime inventory observations must be one nonempty immutable tuple"
            )
        if any(item.error is not None for item in self.observations):
            raise ValueError(
                "runtime inventory cannot contain partial observation errors"
            )
        if self.observations != tuple(
            sorted(self.observations, key=_runtime_observation_sort_key)
        ):
            raise ValueError("runtime observations must use canonical order")
        request_identities = tuple(item.request_identity for item in self.observations)
        if len(request_identities) != len(set(request_identities)):
            raise ValueError("runtime observation request identities must be unique")
        if not _require_string(self.candidate_identity):
            raise ValueError("runtime inventory candidate identity must be nonempty")
        for digest in (
            self.implementation_manifest_digest,
            self.catalog_digest,
            self.lock_digest,
            self.digest,
        ):
            _require_sha256(digest)
        common_bindings = (
            self.candidate_identity,
            self.implementation_manifest_digest,
            self.catalog_digest,
            self.lock_digest,
        )
        capability_by_identity = {
            record.capability_identity: record for record in self.capabilities.records
        }
        for observation in self.observations:
            if (
                observation.candidate_identity,
                observation.implementation_manifest_digest,
                observation.catalog_digest,
                observation.lock_digest,
            ) != common_bindings:
                raise ValueError("runtime observations must share exact input bindings")
            capability = capability_by_identity.get(observation.capability_identity)
            if capability is None:
                raise ValueError("runtime observation capability is undiscovered")
            if (
                observation.capability_digest != capability.capability_digest
                or observation.manager_version_evidence_digest
                != capability.manager_version_evidence_digest
                or observation.harness != capability.harness
            ):
                raise ValueError(
                    "runtime observation capability binding is inconsistent"
                )
        if self.digest != _runtime_inventory_digest(
            self.capabilities,
            self.observations,
            self.candidate_identity,
            self.implementation_manifest_digest,
            self.catalog_digest,
            self.lock_digest,
        ):
            raise ValueError("runtime inventory digest is not canonical")


@dataclass(frozen=True, slots=True)
class PlanNode:
    """One immutable plan-bound mutation or verification node."""

    key: str
    kind: str
    ordinal: int
    identity: str
    dependencies: tuple[str, ...]
    definition: FrozenJsonObject

    def __post_init__(self) -> None:
        if not _require_string(self.key):
            raise ValueError("plan node keys must be nonempty")
        if self.kind not in {"mutation", "verification"}:
            raise ValueError("plan node kind must be mutation or verification")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise TypeError("plan node ordinal must be a nonnegative integer")
        if not _require_string(self.identity):
            raise ValueError("plan node identities must be nonempty")
        expected_prefix = (
            "action:sha256:" if self.kind == "mutation" else "verification:sha256:"
        )
        if not self.identity.startswith(expected_prefix):
            raise ValueError("plan node identity does not match its kind")
        if type(self.dependencies) is not tuple or any(
            type(identity) is not str for identity in self.dependencies
        ):
            raise TypeError("plan node dependencies must be an immutable string tuple")
        if len(self.dependencies) != len(set(self.dependencies)):
            raise ValueError("plan node dependencies must be unique")
        if type(self.definition) is not FrozenJsonObject:
            raise TypeError("plan node definition must be frozen JSON")


@dataclass(frozen=True, slots=True)
class ValidatedPlan:
    """One closed graph bound to a canonical semantic preimage."""

    nodes: tuple[PlanNode, ...]
    edges: tuple[tuple[str, str], ...]
    digest: str
    preimage: FrozenJsonObject

    def __post_init__(self) -> None:
        if (
            type(self.nodes) is not tuple
            or not self.nodes
            or any(type(node) is not PlanNode for node in self.nodes)
        ):
            raise TypeError("validated plan nodes must be one immutable typed tuple")
        if tuple(node.ordinal for node in self.nodes) != tuple(range(len(self.nodes))):
            raise ValueError("validated plan ordinals must be complete and sequential")
        identities = tuple(node.identity for node in self.nodes)
        if len(identities) != len(set(identities)):
            raise ValueError("validated plan node identities must be unique")
        if type(self.edges) is not tuple or any(
            type(edge) is not tuple
            or len(edge) != 2
            or any(type(identity) is not str for identity in edge)
            for edge in self.edges
        ):
            raise TypeError("validated plan edges must be immutable identity pairs")
        identity_set = set(identities)
        if any(
            predecessor not in identity_set or successor not in identity_set
            for predecessor, successor in self.edges
        ):
            raise ValueError("validated plan edges must reference closed plan nodes")
        if type(self.preimage) is not FrozenJsonObject:
            raise TypeError("validated plan preimage must be frozen JSON")
        _require_sha256(self.digest)
        if self.digest != _canonical_json_digest(self.preimage):
            raise ValueError("validated plan digest must bind its exact preimage")
        keys = tuple(node.key for node in self.nodes)
        if len(keys) != len(set(keys)):
            raise ValueError("validated plan node keys must be unique")
        ordinal_by_identity = {node.identity: node.ordinal for node in self.nodes}
        expected_edges: list[tuple[str, str]] = []
        for node in self.nodes:
            dependency_ordinals: list[int] = []
            for dependency in node.dependencies:
                dependency_ordinal = ordinal_by_identity.get(dependency)
                if dependency_ordinal is None or dependency_ordinal >= node.ordinal:
                    raise ValueError(
                        "validated plan dependencies must be earlier closed nodes"
                    )
                dependency_ordinals.append(dependency_ordinal)
                expected_edges.append((dependency, node.identity))
            if dependency_ordinals != sorted(dependency_ordinals):
                raise ValueError(
                    "validated plan dependencies must use predecessor order"
                )
            if node.kind == "mutation":
                route_identity = node.definition.get("route_identity")
                operation = node.definition.get("operation")
                desired_state_digest = node.definition.get("desired_state_digest")
                if not all(
                    type(value) is str
                    for value in (route_identity, operation, desired_state_digest)
                ):
                    raise ValueError("validated mutation definition is incomplete")
                expected_identity = "action:" + _canonical_json_digest(
                    {
                        "plan_digest": self.digest,
                        "ordinal": node.ordinal,
                        "route_id": route_identity,
                        "operation": operation,
                        "desired_state_digest": desired_state_digest,
                    }
                )
            else:
                expected_identity = "verification:" + _canonical_json_digest(
                    {
                        "plan_digest": self.digest,
                        "ordinal": node.ordinal,
                        "semantic_definition_digest": _canonical_json_digest(
                            node.definition
                        ),
                        "predecessor_identities": node.dependencies,
                    }
                )
            if node.identity != expected_identity:
                raise ValueError("validated plan node identity is not canonical")
        expected_edges.sort(
            key=lambda edge: (
                ordinal_by_identity[edge[0]],
                ordinal_by_identity[edge[1]],
            )
        )
        if self.edges != tuple(expected_edges):
            raise ValueError(
                "validated plan edges must equal every node dependency exactly"
            )

        preimage_nodes = self.preimage.get("nodes")
        preimage_edges = self.preimage.get("edges")
        if type(preimage_nodes) is not tuple or type(preimage_edges) is not tuple:
            raise ValueError("validated plan preimage graph is unavailable")
        expected_preimage_nodes = freeze_json(
            [
                {
                    "ordinal": node.ordinal,
                    "kind": node.kind,
                    "definition": node.definition,
                }
                for node in self.nodes
            ]
        )
        expected_preimage_edges = freeze_json(
            [
                [ordinal_by_identity[predecessor], ordinal_by_identity[successor]]
                for predecessor, successor in self.edges
            ]
        )
        if (
            preimage_nodes != expected_preimage_nodes
            or preimage_edges != expected_preimage_edges
        ):
            raise ValueError(
                "validated plan nodes and edges must equal the semantic preimage"
            )

        final_nodes = tuple(
            node
            for node in self.nodes
            if node.kind == "verification"
            and node.definition.get("purpose") == "final_coverage"
        )
        if len(final_nodes) != 1:
            raise ValueError("validated plan must have one final coverage node")
        final_identity = final_nodes[0].identity
        successors: dict[str, set[str]] = {identity: set() for identity in identities}
        predecessors: dict[str, set[str]] = {identity: set() for identity in identities}
        for predecessor, successor in self.edges:
            successors[predecessor].add(successor)
            predecessors[successor].add(predecessor)
        if successors[final_identity]:
            raise ValueError("final coverage must be the validated plan sink")
        reaches_final = {final_identity}
        pending = [final_identity]
        while pending:
            current = pending.pop()
            for predecessor in predecessors[current]:
                if predecessor not in reaches_final:
                    reaches_final.add(predecessor)
                    pending.append(predecessor)
        if reaches_final != set(identities):
            raise ValueError("every validated plan node must reach final coverage")

    def as_json(self) -> FrozenJsonObject:
        """Return the complete immutable plan projection."""

        document = freeze_json(
            {
                "digest": self.digest,
                "preimage": self.preimage,
                "nodes": [
                    {
                        "key": node.key,
                        "kind": node.kind,
                        "ordinal": node.ordinal,
                        "identity": node.identity,
                        "dependencies": list(node.dependencies),
                        "definition": node.definition,
                    }
                    for node in self.nodes
                ],
                "edges": [list(edge) for edge in self.edges],
            }
        )
        if not isinstance(document, FrozenJsonObject):
            raise TypeError("validated plan projection must be frozen JSON")
        return document


@dataclass(frozen=True, slots=True)
class Resolution:
    """One complete immutable result from the pure production resolver."""

    command: str
    diagnostics: tuple[Diagnostic, ...]
    coverage: tuple[CoverageRecord, ...]
    provider_selections: tuple[FrozenJsonObject, ...]
    operation_matrix: tuple[FrozenJsonObject, ...]
    overlays: tuple[FrozenJsonObject, ...]
    candidate_plan: ValidatedPlan | None
    mutation_plan: ValidatedPlan | None
    digest: str

    def __post_init__(self) -> None:
        if self.command not in {"audit", "apply"}:
            raise ValueError("resolution command must be audit or apply")
        if type(self.diagnostics) is not tuple or any(
            type(value) is not Diagnostic for value in self.diagnostics
        ):
            raise TypeError("resolution diagnostics must be an immutable typed tuple")
        if type(self.coverage) is not tuple or any(
            type(value) is not CoverageRecord for value in self.coverage
        ):
            raise TypeError("resolution coverage must be an immutable typed tuple")
        for values in (
            self.provider_selections,
            self.operation_matrix,
            self.overlays,
        ):
            if type(values) is not tuple or any(
                type(value) is not FrozenJsonObject for value in values
            ):
                raise TypeError(
                    "resolution JSON collections must be immutable typed tuples"
                )
        if (
            self.candidate_plan is not None
            and type(self.candidate_plan) is not ValidatedPlan
        ):
            raise TypeError("candidate plan must be one validated plan")
        if (
            self.mutation_plan is not None
            and type(self.mutation_plan) is not ValidatedPlan
        ):
            raise TypeError("mutation plan must be one validated plan")
        if self.diagnostics and (
            self.candidate_plan is not None or self.mutation_plan is not None
        ):
            raise ValueError("fatal diagnostics cannot return any plan")
        if self.mutation_plan is not None and (
            self.command != "apply" or self.mutation_plan is not self.candidate_plan
        ):
            raise ValueError("only apply may project its candidate as a mutation plan")
        _require_sha256(self.digest)
        if self.digest != _resolution_digest(
            self.command,
            self.diagnostics,
            self.coverage,
            self.provider_selections,
            self.operation_matrix,
            self.overlays,
            self.candidate_plan,
            self.mutation_plan,
        ):
            raise ValueError("resolution digest must bind the complete result")

    def as_json(self) -> FrozenJsonObject:
        """Return the complete immutable resolver projection."""

        document = freeze_json(
            _resolution_payload(
                self.command,
                self.diagnostics,
                self.coverage,
                self.provider_selections,
                self.operation_matrix,
                self.overlays,
                self.candidate_plan,
                self.mutation_plan,
            )
            | {"digest": self.digest}
        )
        if not isinstance(document, FrozenJsonObject):
            raise TypeError("resolution projection must be frozen JSON")
        return document


@dataclass(frozen=True, slots=True)
class Catalog:
    schema_version: str
    document: FrozenJsonObject
    digest: str

    def __post_init__(self) -> None:
        if self.schema_version != _CATALOG_SCHEMA_VERSION:
            raise ValueError("catalog schema version must be catalog/v1")
        if type(self.document) is not FrozenJsonObject:
            raise TypeError("catalog document must be a frozen JSON object")
        if self.document.get("schema_version") != self.schema_version:
            raise ValueError("catalog schema version must agree with its document")
        _require_sha256(self.digest)
        if self.digest != _canonical_json_digest(self.document):
            raise ValueError("catalog digest does not match its canonical document")


@dataclass(frozen=True, slots=True)
class ResolvedLock:
    schema_version: str
    document: FrozenJsonObject
    digest: str

    def __post_init__(self) -> None:
        if self.schema_version != _LOCK_SCHEMA_VERSION:
            raise ValueError("resolved lock schema version must be lock/v1")
        if type(self.document) is not FrozenJsonObject:
            raise TypeError("resolved lock document must be a frozen JSON object")
        if self.document.get("schema_version") != self.schema_version:
            raise ValueError(
                "resolved lock schema version must agree with its document"
            )
        _require_sha256(self.digest)
        if self.digest != _canonical_json_digest(self.document):
            raise ValueError(
                "resolved lock digest does not match its canonical document"
            )


@dataclass(frozen=True, slots=True)
class CoverageRecord:
    equipment_identity: str
    harness: str
    record: FrozenJsonObject

    def __post_init__(self) -> None:
        _require_string(self.equipment_identity)
        _require_string(self.harness)
        if type(self.record) is not FrozenJsonObject:
            raise TypeError("coverage record must be a frozen JSON object")


@dataclass(frozen=True, slots=True)
class ValidatedCatalogLock:
    catalog: Catalog
    lock: ResolvedLock
    coverage: tuple[CoverageRecord, ...]

    def __post_init__(self) -> None:
        if type(self.catalog) is not Catalog or type(self.lock) is not ResolvedLock:
            raise TypeError("validated pair must contain typed catalog and lock models")
        if type(self.coverage) is not tuple:
            raise TypeError("coverage must be an immutable tuple")
        if any(type(record) is not CoverageRecord for record in self.coverage):
            raise TypeError("coverage must contain only typed coverage records")
        if self.lock.document.get("catalog_digest") != self.catalog.digest:
            raise ValueError("resolved lock must bind the exact catalog digest")
        coverage_keys = tuple(
            (record.equipment_identity, record.harness) for record in self.coverage
        )
        if coverage_keys != tuple(sorted(coverage_keys)) or len(coverage_keys) != len(
            set(coverage_keys)
        ):
            raise ValueError("coverage records must have sorted unique identities")
        lock_coverage = _lock_coverage(self.lock.document)
        model_coverage = {
            (record.equipment_identity, record.harness): record.record
            for record in self.coverage
        }
        if lock_coverage != model_coverage:
            raise ValueError("coverage must equal all lock coverage records")


@dataclass(frozen=True, slots=True)
class CatalogLockValidation:
    model: ValidatedCatalogLock | None
    diagnostics: tuple[Diagnostic, ...]

    def __post_init__(self) -> None:
        if type(self.diagnostics) is not tuple:
            raise TypeError("diagnostics must be an immutable tuple")
        if any(type(item) is not Diagnostic for item in self.diagnostics):
            raise TypeError("diagnostics must contain only typed diagnostics")
        if self.model is not None and type(self.model) is not ValidatedCatalogLock:
            raise TypeError("validation model must be a validated catalog/lock pair")
        valid_state = self.model is not None and not self.diagnostics
        invalid_state = self.model is None and bool(self.diagnostics)
        if not (valid_state or invalid_state):
            raise ValueError(
                "validation must contain either a model or one or more diagnostics"
            )


@dataclass(frozen=True, slots=True, order=True)
class InstalledFile:
    path: str
    digest: str

    def __post_init__(self) -> None:
        _require_string(self.path)
        _require_sha256(self.digest)


@dataclass(frozen=True, slots=True)
class InstalledImplementationManifest:
    schema_version: str
    runtime_identity: str
    runtime_executable_digest: str
    files: tuple[InstalledFile, ...]
    digest: str

    def __post_init__(self) -> None:
        if self.schema_version != _INSTALLED_IMPLEMENTATION_SCHEMA_VERSION:
            raise ValueError("installed implementation schema version is unsupported")
        _require_cpython_runtime_identity(self.runtime_identity)
        _require_sha256(self.runtime_executable_digest)
        _require_sha256(self.digest)
        if type(self.files) is not tuple:
            raise TypeError("installed files must be an immutable tuple")
        if any(type(item) is not InstalledFile for item in self.files):
            raise TypeError("installed files must contain only typed file records")
        paths = tuple(item.path for item in self.files)
        if paths != _INSTALLED_IMPLEMENTATION_PATHS:
            raise ValueError("installed file records must equal the closed inventory")
        if self.digest != _installed_implementation_digest(
            self.schema_version,
            self.runtime_identity,
            self.runtime_executable_digest,
            self.files,
        ):
            raise ValueError(
                "installed implementation manifest digest is not canonical"
            )

    def as_json(self) -> FrozenJsonObject:
        """Return the closed canonical payload whose digest identifies this manifest."""

        document = freeze_json(
            _installed_implementation_payload(
                self.schema_version,
                self.runtime_identity,
                self.runtime_executable_digest,
                self.files,
            )
        )
        if not isinstance(document, FrozenJsonObject):
            raise TypeError("manifest payload must be a JSON object")
        return document


def _validate_string(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("JSON strings must be valid Unicode scalar values") from error
    return value


def _require_string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("typed model text fields must be strings")
    return _validate_string(value)


def _require_sha256(value: object) -> str:
    digest = _require_string(value)
    if _SHA256_PATTERN.fullmatch(digest) is None:
        raise ValueError("digests must use lowercase sha256 followed by 64 hex digits")
    return digest


def _required_document_string(document: FrozenJsonObject, field: str) -> str:
    value = document.get(field)
    if type(value) is not str:
        raise ValueError(f"typed document field {field} is unavailable")
    return value


def _require_cpython_runtime_identity(value: object) -> str:
    identity = _require_string(value)
    match = _RUNTIME_IDENTITY_PATTERN.fullmatch(identity)
    if match is None:
        raise ValueError("runtime identity must name an exact CPython version")
    version = tuple(int(component) for component in match.groups())
    if version < (3, 12, 0):
        raise ValueError("runtime identity must be CPython 3.12 or newer")
    return identity


def _capability_record_sort_key(record: CapabilityRecord) -> tuple[str, ...]:
    provider = record.document.get("provider_match")
    if not isinstance(provider, FrozenJsonObject):
        return (record.harness, "", "", "", record.capability_identity)
    kind = provider.get("kind")
    if type(kind) is not str:
        kind = ""
    selectors: tuple[object, object] = {
        "standalone_skill": (provider.get("canonical_root"), ""),
        "native_plugin": (provider.get("manager"), provider.get("scope")),
        "direct_mcp": (provider.get("transport"), provider.get("overlay_family")),
    }.get(kind, ("", ""))
    first, second = (value if type(value) is str else "" for value in selectors)
    return (
        record.harness,
        kind,
        first,
        second,
        record.capability_identity,
    )


def _runtime_observation_sort_key(
    observation: RuntimeObservation,
) -> tuple[str, str, str]:
    return (
        observation.harness,
        observation.route_identity,
        observation.request_identity,
    )


def _lock_coverage(
    document: FrozenJsonObject,
) -> dict[tuple[str, str], FrozenJsonObject]:
    serialized_coverage = document.get("coverage")
    if type(serialized_coverage) is not tuple:
        raise ValueError("resolved lock coverage must be an immutable JSON array")
    coverage: dict[tuple[str, str], FrozenJsonObject] = {}
    for entry in serialized_coverage:
        if not isinstance(entry, FrozenJsonObject):
            raise TypeError("resolved lock coverage entries must be JSON objects")
        equipment_identity = entry.get("equipment_identity")
        harness = entry.get("harness")
        record = entry.get("record")
        if (
            type(equipment_identity) is not str
            or type(harness) is not str
            or not isinstance(record, FrozenJsonObject)
        ):
            raise ValueError("resolved lock coverage entries are malformed")
        key = (equipment_identity, harness)
        if key in coverage:
            raise ValueError("resolved lock coverage identities must be unique")
        coverage[key] = record
    return coverage


def _installed_implementation_payload(
    schema_version: str,
    runtime_identity: str,
    runtime_executable_digest: str,
    files: tuple[InstalledFile, ...],
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "runtime_identity": runtime_identity,
        "runtime_executable_digest": runtime_executable_digest,
        "files": [
            {"path": installed.path, "digest": installed.digest} for installed in files
        ],
    }


def _installed_implementation_digest(
    schema_version: str,
    runtime_identity: str,
    runtime_executable_digest: str,
    files: tuple[InstalledFile, ...],
) -> str:
    return _canonical_json_digest(
        _installed_implementation_payload(
            schema_version,
            runtime_identity,
            runtime_executable_digest,
            files,
        )
    )


def _canonical_json_bytes(document: object) -> bytes:
    return json.dumps(
        thaw_json(freeze_json(document)),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _canonical_json_digest(document: object) -> str:
    payload = _canonical_json_bytes(document)
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _runtime_inventory_digest(
    capabilities: CapabilityDiscovery,
    observations: tuple[RuntimeObservation, ...],
    candidate_identity: str,
    implementation_manifest_digest: str,
    catalog_digest: str,
    lock_digest: str,
) -> str:
    observation_payloads: list[dict[str, object]] = []
    for observation in observations:
        payload = thaw_json(observation.document)
        if type(payload) is not dict:
            raise TypeError("runtime observation payload must be a JSON object")
        for runtime_only_field in (
            "request_identity",
            "correlation_identity",
            "observed_at",
        ):
            payload.pop(runtime_only_field, None)
        observation_payloads.append(payload)
    observation_payloads.sort(key=_canonical_json_bytes)
    return _canonical_json_digest(
        {
            "schema_version": "runtime-inventory/v1",
            "candidate_identity": candidate_identity,
            "implementation_manifest_digest": implementation_manifest_digest,
            "catalog_digest": catalog_digest,
            "lock_digest": lock_digest,
            "capability_discovery": capabilities.as_json(),
            "observations": observation_payloads,
        }
    )


def _resolution_payload(
    command: str,
    diagnostics: tuple[Diagnostic, ...],
    coverage: tuple[CoverageRecord, ...],
    provider_selections: tuple[FrozenJsonObject, ...],
    operation_matrix: tuple[FrozenJsonObject, ...],
    overlays: tuple[FrozenJsonObject, ...],
    candidate_plan: ValidatedPlan | None,
    mutation_plan: ValidatedPlan | None,
) -> dict[str, object]:
    return {
        "schema_version": "agent-equipment-resolution/v1",
        "command": command,
        "diagnostics": [
            {
                "code": diagnostic.code,
                "message": diagnostic.message,
                "equipment_identity": diagnostic.equipment_identity,
                "harness": diagnostic.harness,
                "route_identity": diagnostic.route_identity,
                "evidence_source": diagnostic.evidence_source,
            }
            for diagnostic in diagnostics
        ],
        "coverage": [
            {
                "equipment_identity": record.equipment_identity,
                "harness": record.harness,
                "record": record.record,
            }
            for record in coverage
        ],
        "provider_selections": list(provider_selections),
        "operation_matrix": list(operation_matrix),
        "overlays": list(overlays),
        "candidate_plan": (
            candidate_plan.as_json() if candidate_plan is not None else None
        ),
        "mutation_plan": (
            mutation_plan.as_json() if mutation_plan is not None else None
        ),
    }


def _resolution_digest(
    command: str,
    diagnostics: tuple[Diagnostic, ...],
    coverage: tuple[CoverageRecord, ...],
    provider_selections: tuple[FrozenJsonObject, ...],
    operation_matrix: tuple[FrozenJsonObject, ...],
    overlays: tuple[FrozenJsonObject, ...],
    candidate_plan: ValidatedPlan | None,
    mutation_plan: ValidatedPlan | None,
) -> str:
    return _canonical_json_digest(
        _resolution_payload(
            command,
            diagnostics,
            coverage,
            provider_selections,
            operation_matrix,
            overlays,
            candidate_plan,
            mutation_plan,
        )
    )


def freeze_json(value: object) -> FrozenJsonValue:
    """Validate a closed JSON value and return a recursively immutable copy."""

    if value is None or type(value) is bool or type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if type(value) is str:
        return _validate_string(value)
    if isinstance(value, Mapping):
        frozen_items: list[tuple[str, FrozenJsonValue]] = []
        for key in sorted(value):
            if type(key) is not str:
                raise TypeError("JSON object member names must be strings")
            frozen_items.append((_validate_string(key), freeze_json(value[key])))
        return FrozenJsonObject(tuple(frozen_items))
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        return tuple(freeze_json(item) for item in value)
    raise TypeError(f"unsupported JSON value type: {type(value).__name__}")


def thaw_json(value: FrozenJsonValue) -> JsonScalar | list[object] | dict[str, object]:
    """Return a detached mutable built-in representation of frozen JSON."""

    if isinstance(value, FrozenJsonObject):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value
