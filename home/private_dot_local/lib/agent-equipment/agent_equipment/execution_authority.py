"""Pre-claim admission for externally issued apply authority."""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, TypeAlias

from .canonical import (
    byte_sha256,
    canonical_json_bytes,
    canonical_json_sha256,
    strict_load_json_bytes,
)
from .model import Diagnostic, FrozenJsonObject, thaw_json
from .secrets import contains_literal_credential
from .validator import EXPECTED_SCHEMA_SHA256, validate_captured_schema_document

MAX_APPLY_AUTHORIZATION_BYTES = 256 * 1024
MAX_PREPARATION_RECEIPT_BYTES = 256 * 1024
MAX_PREPARATION_BUNDLE_BYTES = 128 * 1024 * 1024
MAX_PREPARATION_ARTIFACT_BYTES = 16 * 1024 * 1024

_SCHEMA_NAME = "execution-authority-v1.schema.json"
_ADAPTER_SCHEMA_NAME = "adapter-contract-v1.schema.json"
_CAPTURED_STATE_SCHEMA_NAME = "captured-state-v1.schema.json"
_PLAN_ACTION_SET_SCHEMA_NAME = "plan-action-set-v1.schema.json"
_PREPARATION_SCHEMA_NAMES = tuple(
    sorted(
        (
            _ADAPTER_SCHEMA_NAME,
            _CAPTURED_STATE_SCHEMA_NAME,
            _SCHEMA_NAME,
            _PLAN_ACTION_SET_SCHEMA_NAME,
        )
    )
)

_UTC_TIMESTAMP = re.compile(
    r"^(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})[Tt]"
    r"(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
    r"(?:[.,](?P<fraction>[0-9]{1,9}))?Z$"
)
_EXECUTION_NONCE = re.compile(r"execution-nonce:sha256:[0-9a-f]{64}")
_ARTIFACT_ROLES = (
    "plan_action_set",
    "captured_state",
    "capability_binding_set",
    "adapter_manifest_set",
    "gate_manifest",
    "capture_observation_authority_set",
    "prepared_action_authority_set",
)
_BUNDLE_BINDING_FIELDS = frozenset(
    {
        "candidate_identity",
        "implementation_manifest_digest",
        "catalog_digest",
        "lock_digest",
        "plan_digest",
        "plan_action_set_digest",
        "capability_set_digest",
        "preparation_adapter_manifest_set_digest",
        "captured_state_identity",
        "captured_state_digest",
        "capture_observation_authority_set_identity",
        "capture_observation_authority_set_digest",
        "prepared_action_authority_set_identity",
        "prepared_action_authority_set_digest",
        "preparation_gate_identity",
        "preparation_gate_manifest_digest",
        "store_identity",
        "store_generation",
    }
)
_APPLY_BINDING_FIELDS = frozenset(
    {
        "candidate_identity",
        "implementation_manifest_digest",
        "catalog_digest",
        "lock_digest",
        "plan_digest",
        "plan_action_set_digest",
        "prepared_action_authority_set_identity",
        "prepared_action_authority_set_digest",
        "capability_set_digest",
        "captured_state_identity",
        "captured_state_digest",
        "capture_observation_authority_set_identity",
        "capture_observation_authority_set_digest",
        "preparation_bundle_digest",
        "expected_case_manifest_digest",
        "operator_review_package_digest",
    }
)
_SHARED_BINDING_FIELDS = frozenset(
    {
        "candidate_identity",
        "implementation_manifest_digest",
        "catalog_digest",
        "lock_digest",
        "plan_digest",
        "plan_action_set_digest",
        "capability_set_digest",
        "captured_state_identity",
        "captured_state_digest",
        "capture_observation_authority_set_identity",
        "capture_observation_authority_set_digest",
        "prepared_action_authority_set_identity",
        "prepared_action_authority_set_digest",
    }
)


@dataclass(frozen=True, slots=True)
class ApplyAuthorizationTrust:
    """Independent values against which one apply authorization is admitted."""

    expected_candidate_identity: str
    expected_implementation_manifest_digest: str
    expected_authorization_identity: str
    expected_authorization_digest: str
    expected_execution_domain_identity: str
    expected_execution_nonce: str
    expected_run_identity: str
    expected_operator_review_package_digest: str
    expected_issuer_identity: str
    trusted_now: datetime


class PreparationBundleResolver(Protocol):
    """Producer-owned retrieval of one authenticated preparation bundle."""

    def resolve(self, preparation_bundle_digest: str) -> object:
        """Return exact receipt and bundle bytes from the producer-owned store."""

        ...


@dataclass(frozen=True, slots=True)
class ResolvedPreparationBundle:
    """Exact bytes authenticated by one prebound producer-owned resolver."""

    receipt_bytes: bytes
    bundle_bytes: bytes


@dataclass(frozen=True, slots=True)
class PreparationArtifactStreams:
    """The seven exact artifact byte streams admitted from one bundle."""

    plan_action_set: bytes
    captured_state: bytes
    capability_binding_set: bytes
    adapter_manifest_set: bytes
    gate_manifest: bytes
    capture_observation_authority_set: bytes
    prepared_action_authority_set: bytes

    def as_dict(self) -> dict[str, bytes]:
        """Return a detached role-to-bytes view for downstream validation."""

        return {role: getattr(self, role) for role in _ARTIFACT_ROLES}


@dataclass(frozen=True, slots=True)
class ApplyAdmissionRejection:
    """Secret-free diagnostics for one rejected pre-claim admission."""

    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class AdmittedApplyAuthorization:
    """Immutable authority and preparation evidence admitted before live checks."""

    authorization_record: FrozenJsonObject
    authorization_digest: str
    preparation_receipt_record: FrozenJsonObject
    preparation_bundle_record: FrozenJsonObject
    receipt_bytes: bytes
    bundle_bytes: bytes
    artifacts: PreparationArtifactStreams


ApplyPreclaimResult: TypeAlias = AdmittedApplyAuthorization | ApplyAdmissionRejection


class ApplyPreclaimGate:
    """Validate apply authority and preparation evidence without claiming a nonce."""

    def __init__(self, resolver: PreparationBundleResolver) -> None:
        resolve = getattr(resolver, "resolve", None)
        if not callable(resolve):
            raise TypeError("apply preclaim gate requires a preparation resolver")
        self._resolve = resolve

    def admit(
        self,
        raw_authorization: bytes,
        trust: ApplyAuthorizationTrust,
    ) -> ApplyPreclaimResult:
        """Admit immutable execution evidence before live comparison and CAS."""

        if type(trust) is not ApplyAuthorizationTrust:
            raise TypeError("apply preclaim admission requires typed trust")
        if (
            type(raw_authorization) is not bytes
            or len(raw_authorization) > MAX_APPLY_AUTHORIZATION_BYTES
        ):
            return _rejection(
                "EXECUTION_AUTHORITY_BYTES_INVALID",
                "The apply authorization is not one bounded raw byte stream.",
            )
        try:
            authorization = strict_load_json_bytes(raw_authorization)
            canonical_bytes = canonical_json_bytes(authorization)
        except (RecursionError, UnicodeError, ValueError, TypeError):
            return _rejection(
                "EXECUTION_AUTHORITY_JSON_INVALID",
                "The apply authorization is not unambiguous strict UTF-8 JSON.",
            )
        if (
            len(canonical_bytes) > MAX_APPLY_AUTHORIZATION_BYTES
            or canonical_bytes != raw_authorization
        ):
            return _rejection(
                "EXECUTION_AUTHORITY_JSON_INVALID",
                "The apply authorization is not one bounded canonical byte stream.",
            )
        if not isinstance(authorization, FrozenJsonObject):
            return _rejection(
                "APPLY_AUTHORIZATION_SCHEMA_INVALID",
                "The apply authorization does not satisfy the checked-in closed schema.",
            )
        mutable_authorization = thaw_json(authorization)
        if not _apply_authorization_has_closed_shape(
            mutable_authorization
        ) or not _validate_execution_authority_record(mutable_authorization):
            return _rejection(
                "APPLY_AUTHORIZATION_SCHEMA_INVALID",
                "The apply authorization does not satisfy the checked-in closed schema.",
            )
        assert isinstance(mutable_authorization, dict)
        if contains_literal_credential(mutable_authorization):
            return _rejection(
                "APPLY_AUTHORIZATION_LITERAL_SECRET",
                "The apply authorization contains credential-shaped literal material.",
            )
        diagnostics = _authorization_diagnostics(mutable_authorization, trust)
        if diagnostics:
            return ApplyAdmissionRejection(diagnostics)

        bindings = mutable_authorization["bindings"]
        assert isinstance(bindings, dict)
        preparation_bundle_digest = bindings["preparation_bundle_digest"]
        assert isinstance(preparation_bundle_digest, str)
        try:
            resolution = self._resolve(preparation_bundle_digest)
        except Exception:  # noqa: BLE001 - producer retrieval always fails closed.
            return _rejection(
                "PREPARATION_BUNDLE_RESOLUTION_FAILED",
                "The producer-owned preparation bundle could not be resolved.",
            )
        admitted = _admit_resolution(
            resolution,
            authorization_bindings=bindings,
        )
        if isinstance(admitted, ApplyAdmissionRejection):
            return admitted
        receipt, bundle, receipt_bytes, bundle_bytes, artifacts = admitted
        return AdmittedApplyAuthorization(
            authorization_record=authorization,
            authorization_digest=canonical_json_sha256(mutable_authorization),
            preparation_receipt_record=receipt,
            preparation_bundle_record=bundle,
            receipt_bytes=receipt_bytes,
            bundle_bytes=bundle_bytes,
            artifacts=artifacts,
        )


def _apply_authorization_has_closed_shape(document: object) -> bool:
    if type(document) is not dict or set(document) != {
        "schema_version",
        "authorization_identity",
        "issuer_identity",
        "issued_at",
        "not_before",
        "expires_at",
        "execution_nonce",
        "run_identity",
        "execution_domain_identity",
        "command",
        "bindings",
    }:
        return False
    bindings = document.get("bindings")
    return (
        document.get("schema_version") == "agent-equipment-apply-authorization/v1"
        and document.get("command") == "apply"
        and type(document.get("execution_nonce")) is str
        and _EXECUTION_NONCE.fullmatch(document["execution_nonce"]) is not None
        and type(bindings) is dict
        and set(bindings) == _APPLY_BINDING_FIELDS
    )


def _authorization_diagnostics(
    authorization: dict[str, object],
    trust: ApplyAuthorizationTrust,
) -> tuple[Diagnostic, ...]:
    if not _valid_trusted_clock(trust.trusted_now):
        return (
            Diagnostic(
                code="TRUSTED_CLOCK_INVALID",
                message="The executor must supply a timezone-aware trusted clock.",
            ),
        )
    identity_payload = {
        key: value
        for key, value in authorization.items()
        if key != "authorization_identity"
    }
    bindings = authorization["bindings"]
    assert isinstance(bindings, dict)
    diagnostics: list[Diagnostic] = []
    if authorization["authorization_identity"] != (
        "apply-authorization:" + canonical_json_sha256(identity_payload)
    ):
        diagnostics.append(
            Diagnostic(
                code="APPLY_AUTHORIZATION_IDENTITY_INVALID",
                message="The apply authorization identity is not canonical.",
            )
        )
    for actual, expected, code in (
        (
            authorization["authorization_identity"],
            trust.expected_authorization_identity,
            "APPLY_AUTHORIZATION_TRUST_MISMATCH",
        ),
        (
            canonical_json_sha256(authorization),
            trust.expected_authorization_digest,
            "APPLY_AUTHORIZATION_DIGEST_MISMATCH",
        ),
        (
            authorization["issuer_identity"],
            trust.expected_issuer_identity,
            "APPLY_AUTHORIZATION_BINDING_MISMATCH",
        ),
        (
            authorization["execution_domain_identity"],
            trust.expected_execution_domain_identity,
            "EXECUTION_DOMAIN_MISMATCH",
        ),
        (
            authorization["execution_nonce"],
            trust.expected_execution_nonce,
            "EXECUTION_BINDING_MISMATCH",
        ),
        (
            authorization["run_identity"],
            trust.expected_run_identity,
            "EXECUTION_BINDING_MISMATCH",
        ),
        (
            bindings["candidate_identity"],
            trust.expected_candidate_identity,
            "APPLY_AUTHORIZATION_BINDING_MISMATCH",
        ),
        (
            bindings["implementation_manifest_digest"],
            trust.expected_implementation_manifest_digest,
            "APPLY_AUTHORIZATION_BINDING_MISMATCH",
        ),
        (
            bindings["operator_review_package_digest"],
            trust.expected_operator_review_package_digest,
            "OPERATOR_REVIEW_PACKAGE_BINDING_MISMATCH",
        ),
    ):
        if actual != expected:
            diagnostics.append(
                Diagnostic(
                    code=code,
                    message="The apply authorization does not match trusted input.",
                )
            )
    if not _time_window_is_valid(authorization, trust.trusted_now):
        diagnostics.append(
            Diagnostic(
                code="APPLY_AUTHORIZATION_TIME_INVALID",
                message="The trusted clock is outside the authorization window.",
            )
        )
    return tuple(sorted(set(diagnostics), key=lambda item: (item.code, item.message)))


def _admit_resolution(
    resolution: object,
    *,
    authorization_bindings: dict[str, object],
) -> (
    tuple[
        FrozenJsonObject,
        FrozenJsonObject,
        bytes,
        bytes,
        PreparationArtifactStreams,
    ]
    | ApplyAdmissionRejection
):
    if type(resolution) is not ResolvedPreparationBundle:
        return _rejection(
            "PREPARATION_BUNDLE_RESOLUTION_INVALID",
            "The producer-owned resolver returned an invalid result.",
        )
    receipt_bytes = resolution.receipt_bytes
    bundle_bytes = resolution.bundle_bytes
    if (
        type(receipt_bytes) is not bytes
        or len(receipt_bytes) > MAX_PREPARATION_RECEIPT_BYTES
    ):
        return _rejection(
            "PREPARATION_RECEIPT_BYTES_INVALID",
            "The preparation receipt is not one bounded exact byte stream.",
        )
    if (
        type(bundle_bytes) is not bytes
        or len(bundle_bytes) > MAX_PREPARATION_BUNDLE_BYTES
    ):
        return _rejection(
            "PREPARATION_BUNDLE_BYTES_INVALID",
            "The preparation bundle is not one bounded exact byte stream.",
        )
    try:
        receipt = strict_load_json_bytes(receipt_bytes)
        bundle = strict_load_json_bytes(bundle_bytes)
        canonical_receipt_bytes = canonical_json_bytes(receipt)
        canonical_bundle_bytes = canonical_json_bytes(bundle)
    except (RecursionError, UnicodeError, ValueError, TypeError):
        return _rejection(
            "PREPARATION_EVIDENCE_JSON_INVALID",
            "Preparation evidence is not unambiguous strict UTF-8 JSON.",
        )
    if (
        canonical_receipt_bytes != receipt_bytes
        or canonical_bundle_bytes != bundle_bytes
    ):
        return _rejection(
            "PREPARATION_EVIDENCE_JSON_INVALID",
            "Preparation evidence is not canonical JSON.",
        )
    if not isinstance(receipt, FrozenJsonObject) or not isinstance(
        bundle, FrozenJsonObject
    ):
        return _rejection(
            "PREPARATION_EVIDENCE_SCHEMA_INVALID",
            "Preparation evidence does not satisfy its closed record shape.",
        )
    mutable_receipt = thaw_json(receipt)
    mutable_bundle = thaw_json(bundle)
    if (
        not _preparation_evidence_has_closed_shape(mutable_receipt, mutable_bundle)
        or not _validate_execution_authority_record(mutable_receipt)
        or not _validate_execution_authority_record(mutable_bundle)
    ):
        return _rejection(
            "PREPARATION_EVIDENCE_SCHEMA_INVALID",
            "Preparation evidence does not satisfy its closed record shape.",
        )
    assert isinstance(mutable_receipt, dict)
    assert isinstance(mutable_bundle, dict)
    bundle_metadata = {
        key: value for key, value in mutable_bundle.items() if key != "artifacts"
    }
    if contains_literal_credential(mutable_receipt) or contains_literal_credential(
        bundle_metadata
    ):
        return _rejection(
            "PREPARATION_EVIDENCE_LITERAL_SECRET",
            "Preparation evidence contains credential-shaped literal material.",
        )

    evidence_diagnostic = _preparation_evidence_diagnostic(
        mutable_receipt,
        mutable_bundle,
        bundle_bytes=bundle_bytes,
        authorization_bindings=authorization_bindings,
    )
    if evidence_diagnostic is not None:
        return ApplyAdmissionRejection((evidence_diagnostic,))
    bundle_bindings = mutable_bundle["bindings"]
    assert isinstance(bundle_bindings, dict)
    artifact_result = _decode_artifacts(
        mutable_bundle["artifacts"],
        bundle_bindings=bundle_bindings,
    )
    if isinstance(artifact_result, ApplyAdmissionRejection):
        return artifact_result
    return receipt, bundle, receipt_bytes, bundle_bytes, artifact_result


def _preparation_evidence_has_closed_shape(
    receipt: object,
    bundle: object,
) -> bool:
    if type(bundle) is not dict or set(bundle) != {
        "schema_version",
        "preparation_bundle_identity",
        "bindings",
        "artifacts",
        "preparation_bundle_digest",
    }:
        return False
    if bundle.get("schema_version") != "agent-equipment-preparation-bundle/v1":
        return False
    bindings = bundle.get("bindings")
    artifacts = bundle.get("artifacts")
    if (
        type(bindings) is not dict
        or set(bindings) != _BUNDLE_BINDING_FIELDS
        or type(artifacts) is not dict
        or set(artifacts) != set(_ARTIFACT_ROLES)
        or any(
            type(value) is not dict or set(value) != {"bytes_base64", "bytes_digest"}
            for value in artifacts.values()
        )
    ):
        return False
    if type(receipt) is not dict or set(receipt) != {
        "schema_version",
        "receipt_identity",
        "payload",
    }:
        return False
    payload = receipt.get("payload")
    return (
        receipt.get("schema_version") == "agent-equipment-preparation-receipt/v1"
        and type(payload) is dict
        and set(payload)
        == {
            "outcome",
            "preparation_bundle_identity",
            "preparation_bundle_digest",
            "preparation_bundle_bytes_digest",
            "preparation_gate_identity",
            "preparation_gate_manifest_digest",
            "store_identity",
            "store_generation",
        }
        and payload.get("outcome") == "committed"
    )


def _validate_execution_authority_record(document: dict[str, object]) -> bool:
    return validate_captured_schema_document(
        document,
        root_schema_name=_SCHEMA_NAME,
    )


def _validate_adapter_contract_record(
    document: dict[str, object],
    *,
    record_type: str,
) -> bool:
    return validate_captured_schema_document(
        {"record_type": record_type, "record": document},
        root_schema_name=_ADAPTER_SCHEMA_NAME,
    )


def _validate_standalone_schema_record(
    document: dict[str, object],
    *,
    schema_name: str,
) -> bool:
    return validate_captured_schema_document(
        document,
        root_schema_name=schema_name,
    )


def _preparation_evidence_diagnostic(
    receipt: dict[str, object],
    bundle: dict[str, object],
    *,
    bundle_bytes: bytes,
    authorization_bindings: dict[str, object],
) -> Diagnostic | None:
    identity_payload = {
        key: value
        for key, value in bundle.items()
        if key not in {"preparation_bundle_identity", "preparation_bundle_digest"}
    }
    expected_identity = "preparation-bundle:" + canonical_json_sha256(identity_payload)
    digest_payload = {
        key: value
        for key, value in bundle.items()
        if key != "preparation_bundle_digest"
    }
    expected_digest = canonical_json_sha256(digest_payload)
    payload = receipt["payload"]
    bindings = bundle["bindings"]
    assert isinstance(payload, dict)
    assert isinstance(bindings, dict)
    expected_receipt_identity = "preparation-receipt:" + canonical_json_sha256(payload)
    if (
        bundle["preparation_bundle_identity"] != expected_identity
        or bundle["preparation_bundle_digest"] != expected_digest
        or receipt["receipt_identity"] != expected_receipt_identity
    ):
        return Diagnostic(
            code="PREPARATION_EVIDENCE_IDENTITY_INVALID",
            message="Preparation evidence has an invalid canonical identity or digest.",
        )
    if authorization_bindings["preparation_bundle_digest"] != expected_digest or any(
        authorization_bindings[field] != bindings[field]
        for field in _SHARED_BINDING_FIELDS
    ):
        return Diagnostic(
            code="PREPARATION_BUNDLE_AUTHORIZATION_MISMATCH",
            message="The preparation bundle does not match validated authorization bindings.",
        )
    if (
        payload["preparation_bundle_identity"] != expected_identity
        or payload["preparation_bundle_digest"] != expected_digest
        or payload["preparation_bundle_bytes_digest"] != byte_sha256(bundle_bytes)
        or payload["store_generation"] != 1
        or bindings["store_generation"] != 1
        or any(
            payload[field] != bindings[field]
            for field in (
                "preparation_gate_identity",
                "preparation_gate_manifest_digest",
                "store_identity",
                "store_generation",
            )
        )
    ):
        return Diagnostic(
            code="PREPARATION_RECEIPT_BUNDLE_MISMATCH",
            message="The authenticated receipt does not match the exact preparation bundle.",
        )
    return None


def _decode_artifacts(
    artifacts: object,
    *,
    bundle_bindings: dict[str, object],
) -> PreparationArtifactStreams | ApplyAdmissionRejection:
    assert isinstance(artifacts, dict)
    decoded: dict[str, bytes] = {}
    documents: dict[str, dict[str, object]] = {}
    for role in _ARTIFACT_ROLES:
        member = artifacts[role]
        assert isinstance(member, dict)
        encoded = member["bytes_base64"]
        expected_digest = member["bytes_digest"]
        if (
            type(encoded) is not str
            or type(expected_digest) is not str
            or len(encoded) > ((MAX_PREPARATION_ARTIFACT_BYTES + 2) // 3) * 4
        ):
            return _rejection(
                "PREPARATION_ARTIFACT_BYTES_INVALID",
                "A preparation artifact is not one bounded exact byte stream.",
            )
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return _rejection(
                "PREPARATION_ARTIFACT_BYTES_INVALID",
                "A preparation artifact is not valid canonical base64.",
            )
        if (
            len(payload) > MAX_PREPARATION_ARTIFACT_BYTES
            or base64.b64encode(payload).decode("ascii") != encoded
            or byte_sha256(payload) != expected_digest
        ):
            return _rejection(
                "PREPARATION_ARTIFACT_DIGEST_MISMATCH",
                "A preparation artifact does not match its exact byte digest.",
            )
        try:
            document = strict_load_json_bytes(payload)
            canonical_payload = canonical_json_bytes(document)
        except (RecursionError, UnicodeError, ValueError, TypeError):
            return _rejection(
                "PREPARATION_ARTIFACT_JSON_INVALID",
                "A preparation artifact is not unambiguous strict UTF-8 JSON.",
            )
        if canonical_payload != payload:
            return _rejection(
                "PREPARATION_ARTIFACT_JSON_INVALID",
                "A preparation artifact is not canonical JSON.",
            )
        mutable_document = thaw_json(document)
        if type(mutable_document) is not dict:
            return _rejection(
                "PREPARATION_ARTIFACT_JSON_INVALID",
                "A preparation artifact must be one closed JSON object.",
            )
        if contains_literal_credential(mutable_document):
            return _rejection(
                "PREPARATION_ARTIFACT_LITERAL_SECRET",
                "A preparation artifact contains credential-shaped literal material.",
            )
        decoded[role] = payload
        documents[role] = mutable_document
    if not _artifact_schemas_are_valid(documents):
        return _rejection(
            "PREPARATION_ARTIFACT_SCHEMA_INVALID",
            "A preparation artifact does not satisfy its checked-in closed schema.",
        )
    if not _artifact_bindings_are_valid(documents, bundle_bindings):
        return _rejection(
            "PREPARATION_ARTIFACT_BINDING_INVALID",
            "A preparation artifact does not match its self-digest or bundle binding.",
        )
    return PreparationArtifactStreams(**decoded)


def _artifact_schemas_are_valid(
    documents: dict[str, dict[str, object]],
) -> bool:
    return (
        _validate_standalone_schema_record(
            documents["plan_action_set"],
            schema_name=_PLAN_ACTION_SET_SCHEMA_NAME,
        )
        and _validate_standalone_schema_record(
            documents["captured_state"],
            schema_name=_CAPTURED_STATE_SCHEMA_NAME,
        )
        and _validate_adapter_contract_record(
            documents["capability_binding_set"],
            record_type="CapabilityBindingSet",
        )
        and _validate_adapter_contract_record(
            documents["adapter_manifest_set"],
            record_type="AdapterManifestSet",
        )
        and _validate_adapter_contract_record(
            documents["gate_manifest"],
            record_type="GateManifest",
        )
        and _validate_execution_authority_record(
            documents["capture_observation_authority_set"]
        )
        and _validate_execution_authority_record(
            documents["prepared_action_authority_set"]
        )
    )


def _artifact_bindings_are_valid(
    documents: dict[str, dict[str, object]],
    bundle_bindings: dict[str, object],
) -> bool:
    plan = documents["plan_action_set"]
    plan_index = _plan_action_index(plan, bundle_bindings)
    if plan_index is None:
        return False

    captured = documents["captured_state"]
    capability_set = documents["capability_binding_set"]
    capability_bindings = capability_set.get("bindings")
    if type(
        capability_bindings
    ) is not list or not _capability_bindings_are_closed_and_sorted(
        capability_bindings
    ):
        return False
    capability_identity_payload = {
        key: value
        for key, value in capability_set.items()
        if key
        not in {
            "capability_binding_set_identity",
            "capability_binding_set_digest",
        }
    }
    capability_record_payload = {
        key: value
        for key, value in capability_set.items()
        if key != "capability_binding_set_digest"
    }
    if (
        capability_set.get("capability_set_digest")
        != canonical_json_sha256(capability_bindings)
        or capability_set.get("capability_set_digest")
        != bundle_bindings["capability_set_digest"]
        or capability_set.get("capability_binding_set_identity")
        != "capability-binding-set:"
        + canonical_json_sha256(capability_identity_payload)
        or capability_set.get("capability_binding_set_digest")
        != canonical_json_sha256(capability_record_payload)
    ):
        return False
    captured_bindings = captured.get("bindings")
    if (
        type(captured_bindings) is not dict
        or captured_bindings
        != {
            "candidate_identity": bundle_bindings["candidate_identity"],
            "implementation_manifest_digest": bundle_bindings[
                "implementation_manifest_digest"
            ],
            "catalog_digest": bundle_bindings["catalog_digest"],
            "lock_digest": bundle_bindings["lock_digest"],
            "plan_digest": bundle_bindings["plan_digest"],
            "plan_action_set_digest": bundle_bindings["plan_action_set_digest"],
            "capability_bindings": capability_bindings,
            "capability_set_digest": bundle_bindings["capability_set_digest"],
        }
        or canonical_json_sha256(captured) != bundle_bindings["captured_state_digest"]
    ):
        return False
    captured_contexts = _captured_action_contexts(
        captured,
        plan_index=plan_index,
    )
    if captured_contexts is None:
        return False

    adapter_set = documents["adapter_manifest_set"]
    manifests = adapter_set.get("manifests")
    if type(manifests) is not list or not _adapter_manifests_are_valid(
        manifests,
        capability_bindings=capability_bindings,
    ):
        return False
    adapter_identity_payload = {
        key: value
        for key, value in adapter_set.items()
        if key not in {"adapter_manifest_set_identity", "adapter_manifest_set_digest"}
    }
    adapter_record_payload = {
        key: value
        for key, value in adapter_set.items()
        if key != "adapter_manifest_set_digest"
    }
    if (
        adapter_set.get("adapter_manifest_set_identity")
        != "preparation-adapter-manifest-set:"
        + canonical_json_sha256(adapter_identity_payload)
        or adapter_set.get("adapter_manifest_set_digest")
        != canonical_json_sha256(adapter_record_payload)
        or adapter_set.get("adapter_manifest_set_digest")
        != bundle_bindings["preparation_adapter_manifest_set_digest"]
    ):
        return False
    adapter_index = _adapter_manifest_index(manifests)
    expected_adapter_keys = {
        _action_adapter_key(action) for action in plan_index.values()
    }
    if adapter_index is None or set(adapter_index) != expected_adapter_keys:
        return False

    gate_manifest = documents["gate_manifest"]
    gate_payload = {
        key: value for key, value in gate_manifest.items() if key != "manifest_digest"
    }
    if (
        gate_manifest.get("schema_version")
        != "agent-equipment-preparation-gate-manifest/v1"
        or gate_manifest.get("gate_identity")
        != bundle_bindings["preparation_gate_identity"]
        or gate_manifest.get("manifest_digest") != canonical_json_sha256(gate_payload)
        or gate_manifest.get("manifest_digest")
        != bundle_bindings["preparation_gate_manifest_digest"]
        or not _gate_schema_bindings_are_current(gate_manifest)
    ):
        return False

    capture_set = documents["capture_observation_authority_set"]
    capture_index = _capture_observation_index(
        capture_set,
        plan_index=plan_index,
        bundle_bindings=bundle_bindings,
    )
    if capture_index is None:
        return False
    prepared_set = documents["prepared_action_authority_set"]
    return _prepared_authorities_are_valid(
        prepared_set,
        plan_index=plan_index,
        captured_contexts=captured_contexts,
        capture_index=capture_index,
        adapter_index=adapter_index,
        bundle_bindings=bundle_bindings,
    )


def _plan_action_index(
    plan: dict[str, object],
    bundle_bindings: dict[str, object],
) -> dict[tuple[str, int], dict[str, object]] | None:
    actions = plan.get("actions")
    plan_without_digest = {
        key: value for key, value in plan.items() if key != "action_set_digest"
    }
    if (
        type(actions) is not list
        or not actions
        or plan.get("action_set_digest") != canonical_json_sha256(plan_without_digest)
        or plan.get("action_set_digest") != bundle_bindings["plan_action_set_digest"]
        or plan.get("candidate_identity") != bundle_bindings["candidate_identity"]
        or plan.get("implementation_manifest_digest")
        != bundle_bindings["implementation_manifest_digest"]
        or plan.get("plan_digest") != bundle_bindings["plan_digest"]
    ):
        return None
    result: dict[tuple[str, int], dict[str, object]] = {}
    ordered: list[tuple[int, str]] = []
    for evidence in actions:
        if type(evidence) is not dict:
            return None
        action = evidence.get("action_payload")
        if type(action) is not dict:
            return None
        identity = action.get("action_identity")
        ordinal = action.get("ordinal")
        desired_state = action.get("desired_state")
        preconditions = action.get("preconditions")
        if type(identity) is not str or type(ordinal) is not int:
            return None
        expected_identity_payload = {
            "plan_digest": action.get("plan_digest"),
            "ordinal": ordinal,
            "route_id": action.get("route_identity"),
            "operation": action.get("operation"),
            "desired_state_digest": action.get("desired_state_digest"),
        }
        expected_preconditions = {
            "catalog_digest": bundle_bindings["catalog_digest"],
            "lock_digest": bundle_bindings["lock_digest"],
            "plan_digest": bundle_bindings["plan_digest"],
            "route_digest": action.get("route_digest"),
            "candidate_identity": bundle_bindings["candidate_identity"],
            "implementation_manifest_digest": bundle_bindings[
                "implementation_manifest_digest"
            ],
            "capability_digest": action.get("capability_digest"),
            "manager_version_evidence_digest": action.get(
                "manager_version_evidence_digest"
            ),
            "adapter_identity": action.get("adapter_identity"),
            "adapter_version": action.get("adapter_version"),
            "control_owner": "reconciler_owned",
            "activation_group": action.get("activation_group"),
            "surface_scope": action.get("surface_scope"),
            "prepared_checkpoint_required": True,
            "compare_before_mutate": True,
        }
        if (
            evidence.get("action_digest") != canonical_json_sha256(action)
            or identity != "action:" + canonical_json_sha256(expected_identity_payload)
            or action.get("candidate_identity") != bundle_bindings["candidate_identity"]
            or action.get("implementation_manifest_digest")
            != bundle_bindings["implementation_manifest_digest"]
            or action.get("catalog_digest") != bundle_bindings["catalog_digest"]
            or action.get("lock_digest") != bundle_bindings["lock_digest"]
            or action.get("plan_digest") != bundle_bindings["plan_digest"]
            or type(desired_state) is not dict
            or action.get("desired_state_digest")
            != canonical_json_sha256(desired_state)
            or preconditions != expected_preconditions
            or _surface_rule_for_action(action) is None
            or not _write_target_identities_are_valid(
                action.get("write_targets"),
                action=action,
                surface_scope=action.get("surface_scope"),
            )
            or not _verification_dependencies_are_valid(action)
            or not _desired_state_matches_action(action)
            or not _secret_references_match(action)
        ):
            return None
        key = (identity, ordinal)
        if key in result:
            return None
        result[key] = action
        ordered.append((ordinal, identity))
    if ordered != sorted(ordered) or [ordinal for ordinal, _ in ordered] != list(
        range(len(actions))
    ):
        return None
    return result


def _desired_state_matches_action(action: dict[str, object]) -> bool:
    operation = action.get("operation")
    desired = action.get("desired_state")
    if type(desired) is not dict:
        return False
    operation_states: dict[str, dict[str, object]] = {
        "install": {"route_presence": "present"},
        "enable": {"enablement": "enabled"},
        "disable": {"enablement": "disabled"},
        "remove": {"route_presence": "absent"},
        "restore": {"route_presence": "present"},
    }
    if operation in operation_states:
        return desired == operation_states[str(operation)]
    if operation != "configure":
        return False
    provider = action.get("provider")
    controlled = action.get("controlled_equipment_identities")
    components = desired.get("component_states", [])
    if (
        type(provider) is not dict
        or type(controlled) is not list
        or type(components) is not list
        or any(
            type(component) is not dict
            or set(component) != {"equipment_identity", "state"}
            or component.get("state") not in {"enabled", "disabled"}
            for component in components
        )
    ):
        return False
    identities = [str(component["equipment_identity"]) for component in components]
    if identities != sorted(set(identities)) or identities != controlled:
        return False
    expected: dict[str, object] = {
        "configuration": {
            "status": "desired",
            "digest": canonical_json_sha256(
                {
                    "provider": provider,
                    "component_controls": components,
                }
            ),
        }
    }
    if components:
        expected["component_states"] = components
    return desired == expected


def _secret_references_match(action: dict[str, object]) -> bool:
    provider = action.get("provider")
    declared = action.get("secret_references")
    if type(provider) is not dict or type(declared) is not list:
        return False
    consumed: set[tuple[str, str]] = set()
    arguments = provider.get("arguments")
    if type(arguments) is list:
        for argument in arguments:
            if type(argument) is not dict:
                return False
            environment = argument.get("secret_reference")
            profile = argument.get("secret_profile_reference")
            if type(environment) is str:
                consumed.add(("environment_variable", environment))
            if type(profile) is str:
                consumed.add(("secret_profile", profile))
    declared_set = {
        (str(reference.get("kind")), str(reference.get("name")))
        for reference in declared
        if type(reference) is dict
    }
    declared_order = [
        canonical_json_bytes(reference)
        for reference in declared
        if type(reference) is dict
    ]
    return (
        len(declared_order) == len(declared)
        and consumed == declared_set
        and len(declared_set) == len(declared)
        and declared_order == sorted(set(declared_order))
    )


def _write_target_identities_are_valid(
    targets: object,
    *,
    action: dict[str, object],
    surface_scope: object,
) -> bool:
    if type(targets) is not list or type(surface_scope) is not list:
        return False
    identities: list[str] = []
    surfaces: list[str] = []
    surface_rules: list[str] = []
    for target in targets:
        if type(target) is not dict:
            return False
        identity_payload = {
            "surface_kind": target.get("surface_kind"),
            "locator": target.get("locator"),
        }
        if "equipment_identity" in target:
            identity_payload["equipment_identity"] = target["equipment_identity"]
        if target.get("target_identity") != (
            "target:" + canonical_json_sha256(identity_payload)
        ) or not _write_target_matches_action_authority(target, action):
            return False
        identity = target.get("target_identity")
        surface = target.get("write_surface_identity")
        if type(identity) is not str or type(surface) is not str:
            return False
        identities.append(identity)
        surfaces.append(surface)
        surface_rule = _logical_surface_rule_for_target(action, target)
        if surface_rule is None:
            return False
        surface_rules.append(surface_rule)
    expected_surface_rule = _surface_rule_for_action(action)
    return (
        identities == sorted(set(identities))
        and sorted(surfaces) == surface_scope
        and surface_rules
        and set(surface_rules) == {expected_surface_rule}
    )


def _surface_rule_for_action(action: dict[str, object]) -> str | None:
    route_identity = action.get("route_identity")
    active = action.get("equipment_identities")
    controlled = action.get("controlled_equipment_identities")
    surface_scope = action.get("surface_scope")
    if (
        type(route_identity) is not str
        or type(active) is not list
        or type(controlled) is not list
        or type(surface_scope) is not list
        or any(type(identity) is not str for identity in [*active, *controlled])
        or active != sorted(set(active))
        or controlled != sorted(set(controlled))
    ):
        return None
    identities = sorted(set(active) | set(controlled))
    if not identities:
        return None
    expected_scopes = {
        "route_identity": [f"surface:{route_identity}"],
        "shared_equipment_identity": [
            f"surface:shared/{identity}" for identity in identities
        ],
        "route_and_equipment_identity": [
            f"surface:{route_identity}/{identity}" for identity in identities
        ],
    }
    for rule, expected_scope in expected_scopes.items():
        if surface_scope == expected_scope:
            return rule
    return None


def _write_target_matches_action_authority(
    target: dict[str, object],
    action: dict[str, object],
) -> bool:
    provider = action.get("provider")
    locator = target.get("locator")
    surface_scope = action.get("surface_scope")
    active = action.get("equipment_identities")
    controlled = action.get("controlled_equipment_identities")
    if (
        type(provider) is not dict
        or type(locator) is not dict
        or type(surface_scope) is not list
        or type(active) is not list
        or type(controlled) is not list
        or target.get("write_surface_identity") not in surface_scope
    ):
        return False
    equipment = target.get("equipment_identity")
    authoritative_equipment = set(active) | set(controlled)
    if type(equipment) is str and equipment not in authoritative_equipment:
        return False
    kind = target.get("surface_kind")
    harness = action.get("harness")
    operation = action.get("operation")
    provider_kind = provider.get("kind")
    if kind in {"plugin_installation", "plugin_enablement"}:
        manager = provider.get("manager")
        expected_kind = {
            "claude": {
                "install": "plugin_installation",
                "enable": "plugin_enablement",
                "disable": "plugin_enablement",
            },
            "codex": {
                "install": "plugin_installation",
                "enable": "plugin_enablement",
                "disable": "plugin_enablement",
            },
            "cursor": {},
        }.get(str(manager), {}).get(str(operation))
        plugin_equipment = {
            identity
            for identity in authoritative_equipment
            if type(identity) is str and identity.startswith("plugin:")
        }
        return (
            provider_kind == "native_plugin"
            and kind == expected_kind
            and equipment is None
            and harness == manager
            and locator
            == {
                "manager": manager,
                "native_identity": provider.get("plugin_id"),
                "scope": provider.get("scope"),
            }
            and len(plugin_equipment) == 1
            and _logical_surface_rule(
                target.get("write_surface_identity"),
                route_identity=action.get("route_identity"),
                equipment_identity=next(iter(plugin_equipment), None),
            )
            is not None
        )
    if kind == "claude_skill_entry":
        path = locator.get("path")
        allowed_operations = {
            "native_plugin": {"install"},
            "standalone_skill": {"install", "remove", "restore"},
        }
        return (
            provider_kind in allowed_operations
            and operation in allowed_operations[str(provider_kind)]
            and harness == "claude"
            and type(equipment) is str
            and equipment.startswith("skill:")
            and type(path) is str
            and path.removeprefix("~/.claude/skills/")
            == equipment.rsplit("/", 1)[-1]
            and _logical_surface_rule(
                target.get("write_surface_identity"),
                route_identity=action.get("route_identity"),
                equipment_identity=equipment,
            )
            is not None
        )
    if kind == "mcp_selection":
        server_name = provider.get("server_name")
        coordinates = {
            "claude": ("settings", "mcpServers"),
            "codex": ("config", "mcp_servers"),
            "cursor": ("config", "mcpServers"),
        }.get(str(harness))
        return (
            provider_kind == "direct_mcp"
            and operation in {"configure", "enable", "disable", "remove", "restore"}
            and type(equipment) is str
            and equipment.startswith("mcp:")
            and type(server_name) is str
            and coordinates is not None
            and locator
            == {
                "owner": harness,
                "source": coordinates[0],
                "key_path": [coordinates[1], server_name],
            }
            and _logical_surface_rule(
                target.get("write_surface_identity"),
                route_identity=action.get("route_identity"),
                equipment_identity=equipment,
            )
            is not None
        )
    if kind == "plugin_selection":
        plugin_id = provider.get("plugin_id")
        return (
            provider_kind == "native_plugin"
            and operation == "configure"
            and harness == "codex"
            and type(equipment) is str
            and equipment.startswith("plugin:")
            and type(plugin_id) is str
            and locator
            == {
                "owner": "codex",
                "source": "config",
                "key_path": ["plugins", plugin_id],
            }
            and _logical_surface_rule(
                target.get("write_surface_identity"),
                route_identity=action.get("route_identity"),
                equipment_identity=equipment,
            )
            is not None
        )
    return False


def _logical_surface_rule_for_target(
    action: dict[str, object],
    target: dict[str, object],
) -> str | None:
    equipment = target.get("equipment_identity")
    if equipment is None:
        active = action.get("equipment_identities")
        controlled = action.get("controlled_equipment_identities")
        if type(active) is not list or type(controlled) is not list:
            return None
        plugin_equipment = {
            identity
            for identity in [*active, *controlled]
            if type(identity) is str and identity.startswith("plugin:")
        }
        if len(plugin_equipment) != 1:
            return None
        equipment = next(iter(plugin_equipment))
    return _logical_surface_rule(
        target.get("write_surface_identity"),
        route_identity=action.get("route_identity"),
        equipment_identity=equipment,
    )


def _logical_surface_rule(
    surface: object,
    *,
    route_identity: object,
    equipment_identity: object,
) -> str | None:
    if (
        type(surface) is not str
        or type(route_identity) is not str
        or type(equipment_identity) is not str
    ):
        return None
    expected = {
        "route_identity": f"surface:{route_identity}",
        "shared_equipment_identity": f"surface:shared/{equipment_identity}",
        "route_and_equipment_identity": f"surface:{route_identity}/{equipment_identity}",
    }
    for rule, expected_surface in expected.items():
        if surface == expected_surface:
            return rule
    return None


def _verification_dependencies_are_valid(action: dict[str, object]) -> bool:
    targets = action.get("write_targets")
    dependencies = action.get("verification_dependencies")
    if type(targets) is not list or type(dependencies) is not list:
        return False
    target_by_surface: dict[str, dict[str, object]] = {}
    claude_target_surfaces: set[str] = set()
    for target in targets:
        if type(target) is not dict:
            return False
        surface = target.get("write_surface_identity")
        if type(surface) is not str or surface in target_by_surface:
            return False
        target_by_surface[surface] = target
        if target.get("surface_kind") == "claude_skill_entry":
            claude_target_surfaces.add(surface)
    claimed_surfaces: set[str] = set()
    claimed_identities: set[str] = set()
    canonical_dependencies: list[bytes] = []
    for dependency in dependencies:
        if type(dependency) is not dict:
            return False
        surface = dependency.get("write_surface_identity")
        identity = dependency.get("dependency_identity")
        if (
            type(surface) is not str
            or surface in claimed_surfaces
            or type(identity) is not str
            or identity in claimed_identities
        ):
            return False
        claimed_surfaces.add(surface)
        claimed_identities.add(identity)
        canonical_dependencies.append(canonical_json_bytes(dependency))
        target = target_by_surface.get(surface)
        target_locator = target.get("locator") if type(target) is dict else None
        dependency_locator = dependency.get("target_locator")
        if (
            type(target) is not dict
            or target.get("surface_kind") != "claude_skill_entry"
            or target.get("equipment_identity")
            != dependency.get("equipment_identity")
            or type(target_locator) is not dict
            or type(dependency_locator) is not dict
        ):
            return False
        expected_identity = "dependency:" + canonical_json_sha256(
            {
                "relationship": dependency.get("relationship"),
                "write_surface_identity": surface,
                "equipment_identity": dependency.get("equipment_identity"),
                "target_locator": dependency_locator,
            }
        )
        write_path = target_locator.get("path")
        dependency_path = dependency_locator.get("path")
        if (
            dependency.get("relationship") != "canonical_skill_projection"
            or identity != expected_identity
            or type(write_path) is not str
            or type(dependency_path) is not str
            or write_path.removeprefix("~/.claude/skills/")
            != dependency_path.removeprefix("~/.agents/skills/")
        ):
            return False
    return (
        claimed_surfaces == claude_target_surfaces
        and canonical_dependencies == sorted(set(canonical_dependencies))
    )


def _captured_surface_references(
    route: dict[str, object],
) -> list[tuple[str, str]] | None:
    references = route.get("surface_references")
    if type(references) is not dict:
        return None
    candidates: list[tuple[str, object]] = [
        ("plugin_installation", references.get("installation")),
        ("plugin_enablement", references.get("enablement")),
        ("legacy_projector", references.get("projector")),
    ]
    for expected_kind, slot in (
        ("mcp_selection", "mcp_selections"),
        ("plugin_selection", "plugin_selections"),
        ("claude_skill_entry", "skill_entries"),
        ("canonical_skill_entry", "canonical_skill_dependencies"),
    ):
        members = references.get(slot)
        if type(members) is not list:
            return None
        candidates.extend((expected_kind, member) for member in members)
    captured: list[tuple[str, str]] = []
    for expected_kind, reference in candidates:
        if type(reference) is not dict:
            return None
        if reference.get("status") == "captured":
            surface_id = reference.get("surface_id")
            if type(surface_id) is not str:
                return None
            captured.append((expected_kind, surface_id))
    return captured


def _captured_surface_recovery_is_valid(surface: dict[str, object]) -> bool:
    kind = surface.get("kind")
    observation = surface.get("observation")
    recovery = surface.get("recovery")
    if type(observation) is not dict or type(recovery) is not dict:
        return False
    if kind == "canonical_skill_entry":
        return recovery == {"kind": "none", "reason": "verification_only"}
    if kind == "claude_skill_entry":
        if observation.get("entry_type") == "absent":
            return recovery == {"kind": "none", "reason": "absent_noop"}
        return recovery.get("kind") == "private_blob"
    if kind in {"mcp_selection", "plugin_selection"}:
        if observation.get("present") is False:
            return recovery == {"kind": "none", "reason": "absent_noop"}
        return recovery.get("kind") == "private_blob"
    if kind in {"plugin_enablement", "legacy_projector"}:
        if (
            kind == "plugin_enablement"
            and observation.get("applicable") is False
            and observation.get("reason") == "not_installed"
        ):
            return recovery == {"kind": "none", "reason": "absent_noop"}
        return recovery.get("kind") in {"structured_snapshot", "private_blob"}
    return kind == "plugin_installation"


def _native_route_capture_is_coherent(
    route: dict[str, object],
    surface_index: dict[str, dict[str, object]],
    actions: list[dict[str, object]],
) -> bool:
    references = route.get("surface_references")
    restore = route.get("restore_evidence")
    if type(references) is not dict or type(restore) is not dict:
        return False
    installation_reference = references.get("installation")
    if type(installation_reference) is not dict:
        return False
    install_actions = [action for action in actions if action.get("operation") == "install"]
    native_actions = [
        action
        for action in actions
        if type(action.get("provider")) is dict
        and action["provider"].get("kind") == "native_plugin"
    ]
    requires_installation = restore.get("restore_class") == "native_rolling" or bool(
        native_actions
    )
    if not requires_installation:
        return installation_reference.get("status") == "not_applicable"
    surface_id = installation_reference.get("surface_id")
    installation = (
        surface_index.get(str(surface_id))
        if installation_reference.get("status") == "captured"
        else None
    )
    if (
        type(installation) is not dict
        or installation.get("kind") != "plugin_installation"
        or installation.get("route_id") != route.get("route_id")
        or restore.get("restore_class") != "native_rolling"
    ):
        return False
    observation = installation.get("observation")
    recovery = installation.get("recovery")
    observed_version = restore.get("observed_version")
    if (
        type(observation) is not dict
        or type(recovery) is not dict
        or type(observed_version) is not dict
    ):
        return False
    if observed_version.get("status") == "route_absent":
        if observation.get("installed") is not False:
            return False
    elif observed_version.get("status") == "observed":
        if (
            observation.get("installed") is not True
            or observation.get("observed_version") != observed_version.get("value")
            or observation.get("channel") != restore.get("channel")
            or observation.get("observation_source")
            != restore.get("observation_source")
        ):
            return False
    else:
        return False
    if len(install_actions) > 1:
        return False
    if install_actions:
        return (
            observation.get("installed") is False
            and recovery.get("kind") == "native_inverse"
            and recovery.get("inverse_operation") == "remove"
        )
    if observation.get("installed") is False:
        return recovery == {"kind": "none", "reason": "absent_noop"}
    return recovery == {
        "kind": "none",
        "reason": (
            "operator_owned"
            if route.get("control_owner") == "operator_owned"
            else "already_desired"
        ),
    }


def _captured_action_contexts(
    captured: dict[str, object],
    *,
    plan_index: dict[tuple[str, int], dict[str, object]],
) -> dict[tuple[str, int], tuple[dict[str, object], list[dict[str, object]]]] | None:
    routes = captured.get("provider_routes")
    surfaces = captured.get("surfaces")
    if type(routes) is not list or type(surfaces) is not list:
        return None
    route_index: dict[str, dict[str, object]] = {}
    for route in routes:
        if type(route) is not dict or type(route.get("route_id")) is not str:
            return None
        route_id = route["route_id"]
        if route_id in route_index:
            return None
        route_index[route_id] = route
    surface_index: dict[str, dict[str, object]] = {}
    logical_surface_keys: set[tuple[str, str, str, bytes]] = set()
    mutable_physical_keys: set[tuple[str, bytes]] = set()
    for surface in surfaces:
        if type(surface) is not dict or type(surface.get("surface_id")) is not str:
            return None
        if not _captured_surface_recovery_is_valid(surface):
            return None
        surface_id = surface["surface_id"]
        if surface_id in surface_index:
            return None
        surface_index[surface_id] = surface
        locator = surface.get("locator")
        if type(locator) is not dict:
            return None
        logical_key = (
            str(surface.get("kind")),
            str(surface.get("route_id", "")),
            str(surface.get("equipment_identity", "")),
            canonical_json_bytes(locator),
        )
        if logical_key in logical_surface_keys:
            return None
        logical_surface_keys.add(logical_key)
        if surface.get("mutation_policy") != "forbidden":
            physical_key = (str(surface.get("kind")), canonical_json_bytes(locator))
            if physical_key in mutable_physical_keys:
                return None
            mutable_physical_keys.add(physical_key)

    reference_counts: dict[str, int] = {}
    for route in routes:
        assert type(route) is dict
        planned_actions = route.get("planned_actions")
        if type(planned_actions) is not list:
            return None
        if route.get("control_owner") == "reconciler_owned" and not planned_actions:
            return None
        references = _captured_surface_references(route)
        if references is None:
            return None
        for expected_kind, surface_id in references:
            surface = surface_index.get(surface_id)
            if (
                surface is None
                or surface.get("kind") != expected_kind
                or surface.get("route_id") != route.get("route_id")
                or reference_counts.get(surface_id, 0) != 0
            ):
                return None
            reference_counts[surface_id] = 1

    for surface in surfaces:
        assert type(surface) is dict
        route_id = surface.get("route_id")
        if route_id is None:
            continue
        route = route_index.get(str(route_id))
        if route is None:
            return None
        equipment = surface.get("equipment_identity")
        route_equipment = set(route.get("equipment_identities", [])) | set(
            route.get("controlled_equipment_identities", [])
        )
        if equipment is not None and equipment not in route_equipment:
            return None
        if (
            surface.get("kind") != "canonical_skill_entry"
            and surface.get("mutation_policy") != route.get("control_owner")
        ):
            return None
        if (
            surface.get("mutation_policy") != "forbidden"
            and reference_counts.get(str(surface["surface_id"]), 0) != 1
        ):
            return None

    expected_action_references = {
        (
            str(action.get("action_identity")),
            canonical_json_sha256(action),
        ): action
        for action in plan_index.values()
    }
    if len(expected_action_references) != len(plan_index):
        return None
    seen_action_references: set[tuple[str, str]] = set()
    reference_by_action_identity: dict[str, dict[str, object]] = {}
    actions_by_route: dict[str, list[dict[str, object]]] = {}
    for route in routes:
        assert type(route) is dict
        references = route.get("planned_actions")
        assert type(references) is list
        for reference in references:
            if type(reference) is not dict:
                return None
            reference_key = (
                str(reference.get("action_identity")),
                str(reference.get("action_digest")),
            )
            action = expected_action_references.get(reference_key)
            if (
                action is None
                or reference_key in seen_action_references
                or action.get("route_identity") != route.get("route_id")
            ):
                return None
            seen_action_references.add(reference_key)
            reference_by_action_identity[reference_key[0]] = reference
            actions_by_route.setdefault(str(route.get("route_id")), []).append(action)
    if seen_action_references != set(expected_action_references):
        return None
    for route in routes:
        assert type(route) is dict
        if not _native_route_capture_is_coherent(
            route,
            surface_index,
            actions_by_route.get(str(route.get("route_id")), []),
        ):
            return None

    result = {}
    write_surface_counts: dict[str, int] = {}
    dependency_surface_counts: dict[str, int] = {}
    for key, action in plan_index.items():
        route = route_index.get(str(action.get("route_identity")))
        capability_binding = {
            "capability_identity": action.get("capability_identity"),
            "capability_digest": action.get("capability_digest"),
            "manager_version_evidence_digest": action.get(
                "manager_version_evidence_digest"
            ),
        }
        if (
            route is None
            or route.get("route_digest") != action.get("route_digest")
            or route.get("capability_binding") != capability_binding
            or route.get("harness") != action.get("harness")
            or route.get("control_owner") != "reconciler_owned"
            or route.get("equipment_identities") != action.get("equipment_identities")
            or route.get("controlled_equipment_identities")
            != action.get("controlled_equipment_identities")
        ):
            return None
        reference = reference_by_action_identity.get(
            str(action.get("action_identity"))
        )
        if reference is None or reference.get("action_digest") != (
            canonical_json_sha256(action)
        ):
            return None
        write_bindings = reference.get("write_bindings")
        dependency_bindings = reference.get("verification_dependency_bindings")
        if type(write_bindings) is not list or type(dependency_bindings) is not list:
            return None
        targets = action["write_targets"]
        dependencies = action["verification_dependencies"]
        assert isinstance(targets, list)
        assert isinstance(dependencies, list)
        target_index = {
            target["target_identity"]: target
            for target in targets
            if type(target) is dict
        }
        dependency_index = {
            dependency["dependency_identity"]: dependency
            for dependency in dependencies
            if type(dependency) is dict
        }
        if len(write_bindings) != len(target_index) or len(
            dependency_bindings
        ) != len(dependency_index):
            return None
        bound_target_identities: list[object] = []
        for binding in write_bindings:
            if type(binding) is not dict:
                return None
            target = target_index.get(binding.get("target_identity"))
            surface = surface_index.get(str(binding.get("surface_id")))
            if (
                target is None
                or surface is None
                or reference_counts.get(str(binding.get("surface_id")), 0) != 1
                or surface.get("route_id") != route["route_id"]
                or surface.get("kind") != target.get("surface_kind")
                or surface.get("locator") != target.get("locator")
                or surface.get("equipment_identity")
                != target.get("equipment_identity")
                or surface.get("mutation_policy") != "reconciler_owned"
            ):
                return None
            surface_id = str(binding["surface_id"])
            write_surface_counts[surface_id] = (
                write_surface_counts.get(surface_id, 0) + 1
            )
            bound_target_identities.append(binding.get("target_identity"))
        if (
            len(set(bound_target_identities)) != len(bound_target_identities)
            or set(bound_target_identities) != set(target_index)
        ):
            return None
        bound_dependency_identities: list[object] = []
        for binding in dependency_bindings:
            if type(binding) is not dict:
                return None
            dependency = dependency_index.get(binding.get("dependency_identity"))
            surface = surface_index.get(str(binding.get("surface_id")))
            if (
                dependency is None
                or surface is None
                or reference_counts.get(str(binding.get("surface_id")), 0) != 1
                or surface.get("route_id") != route["route_id"]
                or surface.get("kind") != "canonical_skill_entry"
                or surface.get("locator") != dependency.get("target_locator")
                or surface.get("equipment_identity")
                != dependency.get("equipment_identity")
                or surface.get("mutation_policy") != "forbidden"
            ):
                return None
            surface_id = str(binding["surface_id"])
            dependency_surface_counts[surface_id] = (
                dependency_surface_counts.get(surface_id, 0) + 1
            )
            bound_dependency_identities.append(binding.get("dependency_identity"))
        if (
            len(set(bound_dependency_identities))
            != len(bound_dependency_identities)
            or set(bound_dependency_identities) != set(dependency_index)
        ):
            return None
        surface_ids = [
            binding.get("surface_id") for binding in [*write_bindings, *dependency_bindings]
        ]
        if any(type(surface_id) is not str for surface_id in surface_ids) or len(
            surface_ids
        ) != len(set(surface_ids)):
            return None
        projected = []
        for surface_id in sorted(surface_ids):
            surface = surface_index.get(surface_id)
            if surface is None or surface.get("route_id") != route["route_id"]:
                return None
            projected.append(surface)
        result[key] = (route, projected)
    for surface in surfaces:
        assert type(surface) is dict
        surface_id = str(surface["surface_id"])
        write_count = write_surface_counts.get(surface_id, 0)
        if (
            surface.get("mutation_policy") == "reconciler_owned"
            and write_count != 1
        ):
            return None
        if (
            surface.get("mutation_policy") != "reconciler_owned"
            and write_count != 0
        ):
            return None
        dependency_count = dependency_surface_counts.get(surface_id, 0)
        if dependency_count > 1:
            return None
        route = route_index.get(str(surface.get("route_id")))
        if (
            route is not None
            and route.get("control_owner") == "reconciler_owned"
            and surface.get("kind") == "canonical_skill_entry"
            and dependency_count != 1
        ):
            return None
    return result


def _adapter_manifest_index(
    manifests: list[object],
) -> dict[tuple[object, ...], dict[str, object]] | None:
    result: dict[tuple[object, ...], dict[str, object]] = {}
    for manifest in manifests:
        assert isinstance(manifest, dict)
        capability = manifest["capability_binding"]
        assert isinstance(capability, dict)
        key = (
            manifest["adapter_identity"],
            manifest["adapter_version"],
            capability["capability_identity"],
            capability["capability_digest"],
            capability["manager_version_evidence_digest"],
        )
        if key in result:
            return None
        result[key] = manifest
    return result


def _action_adapter_key(action: dict[str, object]) -> tuple[object, ...]:
    return (
        action.get("adapter_identity"),
        action.get("adapter_version"),
        action.get("capability_identity"),
        action.get("capability_digest"),
        action.get("manager_version_evidence_digest"),
    )


def _gate_schema_bindings_are_current(gate_manifest: dict[str, object]) -> bool:
    files = gate_manifest.get("files")
    if type(files) is not list:
        return False
    file_paths: list[str] = []
    for record in files:
        if (
            type(record) is not dict
            or set(record) != {"path", "digest"}
            or type(record.get("path")) is not str
            or type(record.get("digest")) is not str
        ):
            return False
        file_paths.append(record["path"])
    if file_paths != sorted(set(file_paths)):
        return False
    records = gate_manifest.get("schema_digests")
    expected_records = [
        {"name": name, "digest": "sha256:" + EXPECTED_SCHEMA_SHA256[name]}
        for name in _PREPARATION_SCHEMA_NAMES
    ]
    return records == expected_records


def _authority_set_seal_is_valid(
    authority_set: dict[str, object],
    *,
    identity_prefix: str,
    expected_identity: object,
    expected_digest: object,
) -> bool:
    identity_payload = {
        key: value
        for key, value in authority_set.items()
        if key not in {"authority_set_identity", "authority_set_digest"}
    }
    digest_payload = {
        key: value
        for key, value in authority_set.items()
        if key != "authority_set_digest"
    }
    return (
        authority_set.get("authority_set_identity")
        == identity_prefix + canonical_json_sha256(identity_payload)
        == expected_identity
        and authority_set.get("authority_set_digest")
        == canonical_json_sha256(digest_payload)
        == expected_digest
    )


def _capture_observation_index(
    capture_set: dict[str, object],
    *,
    plan_index: dict[tuple[str, int], dict[str, object]],
    bundle_bindings: dict[str, object],
) -> dict[tuple[str, int], dict[str, object]] | None:
    if not _authority_set_seal_is_valid(
        capture_set,
        identity_prefix="capture-observation-authority-set:",
        expected_identity=bundle_bindings["capture_observation_authority_set_identity"],
        expected_digest=bundle_bindings["capture_observation_authority_set_digest"],
    ):
        return None
    expected_bindings = {
        "candidate_identity": bundle_bindings["candidate_identity"],
        "implementation_manifest_digest": bundle_bindings[
            "implementation_manifest_digest"
        ],
        "plan_digest": bundle_bindings["plan_digest"],
        "plan_action_set_digest": bundle_bindings["plan_action_set_digest"],
        "capability_set_digest": bundle_bindings["capability_set_digest"],
        "preparation_adapter_manifest_set_digest": bundle_bindings[
            "preparation_adapter_manifest_set_digest"
        ],
        "captured_state_identity": bundle_bindings["captured_state_identity"],
        "captured_state_digest": bundle_bindings["captured_state_digest"],
    }
    observations = capture_set.get("observations")
    if (
        capture_set.get("bindings") != expected_bindings
        or type(observations) is not list
    ):
        return None
    result: dict[tuple[str, int], dict[str, object]] = {}
    ordered: list[tuple[int, str]] = []
    for observation in observations:
        if type(observation) is not dict:
            return None
        identity = observation.get("action_identity")
        ordinal = observation.get("ordinal")
        if type(identity) is not str or type(ordinal) is not int:
            return None
        key = (identity, ordinal)
        action = plan_index.get(key)
        pre_state = observation.get("normalized_pre_state")
        controlled = action.get("controlled_equipment_identities") if action else None
        if (
            action is None
            or key in result
            or observation.get("captured_state_identity")
            != bundle_bindings["captured_state_identity"]
            or observation.get("captured_state_digest")
            != bundle_bindings["captured_state_digest"]
            or observation.get("surface") != action.get("surface_scope")
            or observation.get("controlled_equipment_identities") != controlled
            or observation.get("normalized_pre_state_digest")
            != canonical_json_sha256(pre_state)
            or _normalized_component_identities(pre_state) != tuple(controlled)
        ):
            return None
        result[key] = observation
        ordered.append((ordinal, identity))
    if (
        set(result) != set(plan_index)
        or ordered != sorted(ordered)
        or [ordinal for ordinal, _ in ordered] != list(range(len(observations)))
    ):
        return None
    return result


def _prepared_authorities_are_valid(
    prepared_set: dict[str, object],
    *,
    plan_index: dict[tuple[str, int], dict[str, object]],
    captured_contexts: dict[
        tuple[str, int], tuple[dict[str, object], list[dict[str, object]]]
    ],
    capture_index: dict[tuple[str, int], dict[str, object]],
    adapter_index: dict[tuple[object, ...], dict[str, object]],
    bundle_bindings: dict[str, object],
) -> bool:
    if not _authority_set_seal_is_valid(
        prepared_set,
        identity_prefix="prepared-action-authority-set:",
        expected_identity=bundle_bindings["prepared_action_authority_set_identity"],
        expected_digest=bundle_bindings["prepared_action_authority_set_digest"],
    ):
        return False
    expected_bindings = {
        "candidate_identity": bundle_bindings["candidate_identity"],
        "implementation_manifest_digest": bundle_bindings[
            "implementation_manifest_digest"
        ],
        "plan_digest": bundle_bindings["plan_digest"],
        "plan_action_set_digest": bundle_bindings["plan_action_set_digest"],
        "capability_set_digest": bundle_bindings["capability_set_digest"],
        "preparation_adapter_manifest_set_digest": bundle_bindings[
            "preparation_adapter_manifest_set_digest"
        ],
        "captured_state_identity": bundle_bindings["captured_state_identity"],
        "captured_state_digest": bundle_bindings["captured_state_digest"],
        "capture_observation_authority_set_identity": bundle_bindings[
            "capture_observation_authority_set_identity"
        ],
        "capture_observation_authority_set_digest": bundle_bindings[
            "capture_observation_authority_set_digest"
        ],
    }
    authorities = prepared_set.get("authorities")
    if (
        prepared_set.get("bindings") != expected_bindings
        or type(authorities) is not list
    ):
        return False
    ordered: list[tuple[int, str]] = []
    seen: set[tuple[str, int]] = set()
    for authority in authorities:
        if type(authority) is not dict:
            return False
        identity = authority.get("action_identity")
        ordinal = authority.get("ordinal")
        if type(identity) is not str or type(ordinal) is not int:
            return False
        key = (identity, ordinal)
        action = plan_index.get(key)
        observation = capture_index.get(key)
        context = captured_contexts.get(key)
        if action is None or observation is None or context is None or key in seen:
            return False
        manifest = adapter_index.get(_action_adapter_key(action))
        if manifest is None or not _prepared_authority_matches(
            authority,
            action=action,
            observation=observation,
            route=context[0],
            projected_surfaces=context[1],
            manifest=manifest,
            bundle_bindings=bundle_bindings,
        ):
            return False
        seen.add(key)
        ordered.append((ordinal, identity))
    return (
        seen == set(plan_index)
        and ordered == sorted(ordered)
        and [ordinal for ordinal, _ in ordered] == list(range(len(authorities)))
    )


def _prepared_authority_matches(
    authority: dict[str, object],
    *,
    action: dict[str, object],
    observation: dict[str, object],
    route: dict[str, object],
    projected_surfaces: list[dict[str, object]],
    manifest: dict[str, object],
    bundle_bindings: dict[str, object],
) -> bool:
    restore_evidence = route.get("restore_evidence")
    if type(restore_evidence) is not dict:
        return False
    recovery_material = {
        "restore_evidence": restore_evidence,
        "surface_recovery": sorted(
            (
                {
                    "surface_id": surface["surface_id"],
                    "recovery": surface["recovery"],
                }
                for surface in projected_surfaces
            ),
            key=lambda item: str(item["surface_id"]),
        ),
    }
    expected_adapter_binding = {
        key: manifest[key]
        for key in (
            "adapter_identity",
            "adapter_version",
            "adapter_manifest_identity",
            "adapter_manifest_digest",
            "adapter_implementation_identity",
            "adapter_implementation_manifest_digest",
        )
    }
    expected = {
        "action_identity": action["action_identity"],
        "action_digest": canonical_json_sha256(action),
        "ordinal": action["ordinal"],
        "candidate_identity": bundle_bindings["candidate_identity"],
        "implementation_manifest_digest": bundle_bindings[
            "implementation_manifest_digest"
        ],
        "catalog_digest": bundle_bindings["catalog_digest"],
        "lock_digest": bundle_bindings["lock_digest"],
        "plan_digest": bundle_bindings["plan_digest"],
        "plan_action_set_digest": bundle_bindings["plan_action_set_digest"],
        "capability_set_digest": bundle_bindings["capability_set_digest"],
        "route_capability_binding": {
            "capability_identity": action["capability_identity"],
            "capability_digest": action["capability_digest"],
            "manager_version_evidence_digest": action[
                "manager_version_evidence_digest"
            ],
        },
        "adapter_binding": expected_adapter_binding,
        "capture_observation_authority_set_identity": bundle_bindings[
            "capture_observation_authority_set_identity"
        ],
        "capture_observation_authority_set_digest": bundle_bindings[
            "capture_observation_authority_set_digest"
        ],
        "route_capture_binding": {
            "route_identity": action["route_identity"],
            "route_digest": action["route_digest"],
            "restore_evidence_digest": canonical_json_sha256(restore_evidence),
            "recovery_material_digest": canonical_json_sha256(recovery_material),
            "native_update_control": restore_evidence.get(
                "native_update_control", "not_applicable"
            ),
        },
        "route_digest": action["route_digest"],
        "provider": action["provider"],
        "provider_digest": canonical_json_sha256(action["provider"]),
        "operation": action["operation"],
        "operation_digest": canonical_json_sha256(action["operation"]),
        "compensation": action["compensation"],
        "compensation_digest": canonical_json_sha256(action["compensation"]),
        "compensation_operation": "restore_captured_pre_state",
        "desired_state": action["desired_state"],
        "desired_state_digest": action["desired_state_digest"],
        "surface": action["surface_scope"],
        "captured_state_identity": bundle_bindings["captured_state_identity"],
        "captured_state_digest": bundle_bindings["captured_state_digest"],
        "captured_pre_state": observation["normalized_pre_state"],
        "captured_pre_state_digest": observation["normalized_pre_state_digest"],
    }
    expected_post_state = authority.get("expected_post_state")
    controlled = action.get("controlled_equipment_identities")
    authority_payload = {
        key: value for key, value in authority.items() if key != "authority_digest"
    }
    if (
        any(authority.get(field) != value for field, value in expected.items())
        or authority.get("expected_post_state_digest")
        != canonical_json_sha256(expected_post_state)
        or authority.get("authority_digest") != canonical_json_sha256(authority_payload)
        or _normalized_component_identities(authority.get("captured_pre_state"))
        != tuple(controlled)
        or _normalized_component_identities(expected_post_state) != tuple(controlled)
        or not _normalized_state_includes_desired_fragment(
            expected_post_state,
            action.get("desired_state"),
        )
    ):
        return False
    return all(
        not (
            type(surface.get("recovery")) is dict
            and surface["recovery"].get("kind") == "native_inverse"
            and surface["recovery"].get("inverse_operation") == "remove"
        )
        or surface["recovery"].get("expected_pre_state_digest")
        == authority.get("expected_post_state_digest")
        for surface in projected_surfaces
    )


def _normalized_component_identities(state: object) -> tuple[str, ...] | None:
    if type(state) is not dict or type(state.get("component_states")) is not list:
        return None
    components = state["component_states"]
    identities = [
        component.get("equipment_identity")
        for component in components
        if type(component) is dict
    ]
    if (
        len(identities) != len(components)
        or any(type(identity) is not str for identity in identities)
        or identities != sorted(set(identities))
    ):
        return None
    return tuple(identities)


def _normalized_state_includes_desired_fragment(
    state: object,
    desired: object,
) -> bool:
    if type(state) is not dict or type(desired) is not dict:
        return False
    for field in (
        "route_presence",
        "enablement",
        "native_update_suppression_state",
    ):
        if field in desired and state.get(field) != desired[field]:
            return False
    desired_configuration = desired.get("configuration")
    if type(desired_configuration) is dict:
        expected_configuration = dict(desired_configuration)
        if expected_configuration.get("status") == "desired":
            expected_configuration["status"] = "observed"
        if state.get("configuration") != expected_configuration:
            return False
    desired_components = desired.get("component_states")
    if type(desired_components) is list:
        state_components = state.get("component_states")
        if type(state_components) is not list:
            return False
        state_index = {
            item.get("equipment_identity"): item.get("state")
            for item in state_components
            if type(item) is dict
        }
        if any(
            type(item) is not dict
            or state_index.get(item.get("equipment_identity")) != item.get("state")
            for item in desired_components
        ):
            return False
    return True


def _capability_bindings_are_closed_and_sorted(bindings: list[object]) -> bool:
    if not bindings:
        return False
    if any(
        type(binding) is not dict
        or set(binding)
        != {
            "capability_identity",
            "capability_digest",
            "manager_version_evidence_digest",
        }
        for binding in bindings
    ):
        return False
    try:
        canonical_order = sorted(
            bindings,
            key=lambda binding: (
                binding["capability_identity"],
                binding["capability_digest"],
                binding["manager_version_evidence_digest"],
            ),
        )
    except (KeyError, TypeError):
        return False
    identities = [binding["capability_identity"] for binding in bindings]
    return bindings == canonical_order and len(set(identities)) == len(identities)


def _adapter_manifests_are_valid(
    manifests: object,
    *,
    capability_bindings: list[object],
) -> bool:
    if type(manifests) is not list or not manifests:
        return False
    identities: list[object] = []
    for manifest in manifests:
        if type(manifest) is not dict or set(manifest) != {
            "adapter_manifest_identity",
            "adapter_identity",
            "adapter_version",
            "adapter_implementation_identity",
            "adapter_implementation_manifest_digest",
            "capability_binding",
            "prepare_seam",
            "adapter_manifest_digest",
        }:
            return False
        identity_payload = {
            key: value
            for key, value in manifest.items()
            if key not in {"adapter_manifest_identity", "adapter_manifest_digest"}
        }
        digest_payload = {
            key: value
            for key, value in manifest.items()
            if key != "adapter_manifest_digest"
        }
        if (
            manifest.get("adapter_manifest_identity")
            != "preparation-adapter-manifest:" + canonical_json_sha256(identity_payload)
            or manifest.get("adapter_manifest_digest")
            != canonical_json_sha256(digest_payload)
            or manifest.get("capability_binding") not in capability_bindings
            or manifest.get("prepare_seam")
            != {
                "entrypoint": "prepare",
                "effect": "read_only",
                "request_record": "PrepareRequest",
                "response_record": "PreparedStateFacts",
            }
        ):
            return False
        identities.append(manifest["adapter_manifest_identity"])
    return identities == sorted(identities) and len(set(identities)) == len(identities)


def _valid_trusted_clock(value: object) -> bool:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return False
    try:
        return value.utcoffset() is not None
    except Exception:  # noqa: BLE001 - hostile datetime subclasses fail closed.
        return False


def _time_window_is_valid(
    authorization: dict[str, object],
    trusted_now: datetime,
) -> bool:
    try:
        issued_at = _utc_timestamp_tuple(authorization["issued_at"])
        not_before = _utc_timestamp_tuple(authorization["not_before"])
        expires_at = _utc_timestamp_tuple(authorization["expires_at"])
        now = trusted_now.astimezone(timezone.utc)
    except (AttributeError, OverflowError, TypeError, ValueError):
        return False
    if issued_at is None or not_before is None or expires_at is None:
        return False
    now_tuple = (
        now.year,
        now.month,
        now.day,
        now.hour,
        now.minute,
        now.second,
        now.microsecond * 1000,
    )
    return issued_at <= not_before <= now_tuple < expires_at


def _utc_timestamp_tuple(value: object) -> tuple[int, ...] | None:
    if type(value) is not str or (match := _UTC_TIMESTAMP.fullmatch(value)) is None:
        return None
    fraction = (match.group("fraction") or "").ljust(9, "0")
    return (
        int(match.group("year")),
        int(match.group("month")),
        int(match.group("day")),
        int(match.group("hour")),
        int(match.group("minute")),
        int(match.group("second")),
        int(fraction or "0"),
    )


def _rejection(code: str, message: str) -> ApplyAdmissionRejection:
    return ApplyAdmissionRejection((Diagnostic(code=code, message=message),))


__all__ = (
    "MAX_APPLY_AUTHORIZATION_BYTES",
    "MAX_PREPARATION_ARTIFACT_BYTES",
    "MAX_PREPARATION_BUNDLE_BYTES",
    "MAX_PREPARATION_RECEIPT_BYTES",
    "AdmittedApplyAuthorization",
    "ApplyAdmissionRejection",
    "ApplyAuthorizationTrust",
    "ApplyPreclaimGate",
    "ApplyPreclaimResult",
    "PreparationArtifactStreams",
    "PreparationBundleResolver",
    "ResolvedPreparationBundle",
)
