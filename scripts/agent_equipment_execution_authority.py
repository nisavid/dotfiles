"""Pure validation for agent-equipment execution and release authority records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    from agent_equipment_json_schema import validate_document as _validate_schema
except ModuleNotFoundError:  # Loaded as a repo module rather than an executable.
    from scripts.agent_equipment_json_schema import (
        validate_document as _validate_schema,
    )
try:
    from agent_equipment_public_data import contains_literal_credential
except ModuleNotFoundError:  # Loaded as a repo module rather than an executable.
    from scripts.agent_equipment_public_data import contains_literal_credential


SCHEMA_DIRECTORY = Path(__file__).resolve().parent.parent / "docs/agent-equipment"
SCHEMA_NAME = "execution-authority-v1.schema.json"


@dataclass(frozen=True, order=True)
class Diagnostic:
    """One deterministic, secret-free authority validation failure."""

    path: str
    code: str
    message: str


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_digest(value: object) -> str:
    """Return the canonical SHA-256 digest used by v1 authority records."""

    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _diagnostic(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(path=path, code=code, message=message)


def _schema_valid(document: object) -> bool:
    return _validate_schema(
        document,
        schema_directory=SCHEMA_DIRECTORY,
        root_schema_name=SCHEMA_NAME,
        allowed_schema_names=frozenset({SCHEMA_NAME}),
    )


def _authorization_identity(document: Mapping[str, object]) -> str:
    payload = {
        key: value for key, value in document.items() if key != "authorization_identity"
    }
    return "apply-authorization:" + canonical_digest(payload)


def _archive_identity(payload: object) -> str:
    return "release-archive:" + canonical_digest(payload)


def _artifact_digest(document: Mapping[str, object], digest_member: str) -> str:
    return canonical_digest(
        {key: value for key, value in document.items() if key != digest_member}
    )


def validate_apply_authorization(
    document: object,
    *,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_apply_authorization_identity: str,
    expected_apply_authorization_digest: str,
    expected_execution_nonce: str,
    expected_run_identity: str,
    expected_operator_review_package_digest: str,
    expected_issuer_identity: str,
    trusted_now: datetime,
    expected_bindings: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    """Validate one externally issued apply authorization against trusted inputs."""

    if (
        not isinstance(document, Mapping)
        or document.get("schema_version") != "agent-equipment-apply-authorization/v1"
        or not _schema_valid(document)
    ):
        return (
            _diagnostic(
                "APPLY_AUTHORIZATION_SCHEMA_INVALID",
                "$",
                "The apply authorization does not satisfy the checked-in closed schema.",
            ),
        )
    if contains_literal_credential(document):
        return (
            _diagnostic(
                "APPLY_AUTHORIZATION_LITERAL_SECRET",
                "$",
                "The apply authorization contains credential-shaped literal material.",
            ),
        )
    if (
        not isinstance(trusted_now, datetime)
        or trusted_now.tzinfo is None
        or trusted_now.utcoffset() is None
    ):
        return (
            _diagnostic(
                "TRUSTED_CLOCK_INVALID",
                "$.trusted_clock",
                "The executor must supply a timezone-aware trusted clock.",
            ),
        )

    diagnostics: list[Diagnostic] = []
    bindings = document["bindings"]
    assert isinstance(bindings, Mapping)
    if document["authorization_identity"] != _authorization_identity(document):
        diagnostics.append(
            _diagnostic(
                "APPLY_AUTHORIZATION_IDENTITY_INVALID",
                "$.authorization_identity",
                "The apply-authorization identity does not match its canonical payload.",
            )
        )
    if document["authorization_identity"] != expected_apply_authorization_identity:
        diagnostics.append(
            _diagnostic(
                "APPLY_AUTHORIZATION_TRUST_MISMATCH",
                "$.authorization_identity",
                "The apply authorization does not match the independently trusted identity.",
            )
        )
    if canonical_digest(document) != expected_apply_authorization_digest:
        diagnostics.append(
            _diagnostic(
                "APPLY_AUTHORIZATION_DIGEST_MISMATCH",
                "$",
                "The apply authorization does not match the independently trusted digest.",
            )
        )
    if document["issuer_identity"] != expected_issuer_identity:
        diagnostics.append(
            _diagnostic(
                "APPLY_AUTHORIZATION_BINDING_MISMATCH",
                "$.issuer_identity",
                "The apply authorization does not match the trusted issuer.",
            )
        )
    if bindings != expected_bindings:
        diagnostics.append(
            _diagnostic(
                "APPLY_AUTHORIZATION_BINDING_MISMATCH",
                "$.bindings",
                "The apply authorization does not match the complete independently trusted binding tuple.",
            )
        )
    expected_fields = {
        "candidate_identity": expected_candidate_identity,
        "implementation_manifest_digest": expected_implementation_manifest_digest,
        "operator_review_package_digest": expected_operator_review_package_digest,
    }
    for field, expected in expected_fields.items():
        if bindings[field] != expected:
            diagnostics.append(
                _diagnostic(
                    (
                        "OPERATOR_REVIEW_PACKAGE_BINDING_MISMATCH"
                        if field == "operator_review_package_digest"
                        else "APPLY_AUTHORIZATION_BINDING_MISMATCH"
                    ),
                    f"$.bindings.{field}",
                    "The apply authorization does not match the independently trusted execution material.",
                )
            )
    if (
        document["execution_nonce"] != expected_execution_nonce
        or document["run_identity"] != expected_run_identity
    ):
        diagnostics.append(
            _diagnostic(
                "EXECUTION_BINDING_MISMATCH",
                "$",
                "The apply authorization does not match the trusted nonce and run.",
            )
        )
    try:
        issued_at = datetime.fromisoformat(
            str(document["issued_at"]).replace("Z", "+00:00")
        )
        not_before = datetime.fromisoformat(
            str(document["not_before"]).replace("Z", "+00:00")
        )
        expires_at = datetime.fromisoformat(
            str(document["expires_at"]).replace("Z", "+00:00")
        )
    except ValueError:
        issued_at = not_before = expires_at = trusted_now
        diagnostics.append(
            _diagnostic(
                "APPLY_AUTHORIZATION_TIME_INVALID",
                "$",
                "The apply authorization time window is invalid.",
            )
        )
    if not (issued_at <= not_before <= trusted_now < expires_at):
        diagnostics.append(
            _diagnostic(
                "APPLY_AUTHORIZATION_TIME_INVALID",
                "$",
                "The trusted clock is outside the authorization's ordered validity window.",
            )
        )
    return tuple(sorted(diagnostics))


def validate_release_archive_manifest(
    document: object,
    *,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_execution_binding: Mapping[str, object],
    expected_launcher_identity: str,
    expected_launcher_manifest_digest: str,
    expected_store_identity: str,
    expected_store_key: str,
    expected_archived_document_byte_digests: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    """Validate one closed archive manifest without touching the archive store."""

    if (
        not isinstance(document, Mapping)
        or document.get("schema_version")
        != "agent-equipment-release-archive-manifest/v1"
        or not _schema_valid(document)
    ):
        return (
            _diagnostic(
                "RELEASE_ARCHIVE_SCHEMA_INVALID",
                "$",
                "The release archive manifest does not satisfy the checked-in closed schema.",
            ),
        )
    if contains_literal_credential(document):
        return (
            _diagnostic(
                "RELEASE_ARCHIVE_LITERAL_SECRET",
                "$",
                "The release archive manifest contains credential-shaped literal material.",
            ),
        )

    diagnostics: list[Diagnostic] = []
    payload = document["payload"]
    assert isinstance(payload, Mapping)
    destination = payload["archive_destination"]
    assert isinstance(destination, Mapping)
    if document["archive_identity"] != _archive_identity(payload):
        diagnostics.append(
            _diagnostic(
                "RELEASE_ARCHIVE_IDENTITY_INVALID",
                "$.archive_identity",
                "The archive identity does not match its canonical payload.",
            )
        )
    if document["archive_manifest_digest"] != _artifact_digest(
        document, "archive_manifest_digest"
    ):
        diagnostics.append(
            _diagnostic(
                "RELEASE_ARCHIVE_DIGEST_INVALID",
                "$.archive_manifest_digest",
                "The archive manifest digest does not match the complete manifest.",
            )
        )
    expected_fields = {
        "candidate_identity": expected_candidate_identity,
        "implementation_manifest_digest": expected_implementation_manifest_digest,
        "launcher_identity": expected_launcher_identity,
        "launcher_manifest_digest": expected_launcher_manifest_digest,
    }
    if any(payload[field] != expected for field, expected in expected_fields.items()):
        diagnostics.append(
            _diagnostic(
                "RELEASE_ARCHIVE_AUTHORITY_MISMATCH",
                "$.payload",
                "The archive manifest does not match the trusted candidate and launcher authority.",
            )
        )
    if payload["execution_binding"] != expected_execution_binding:
        diagnostics.append(
            _diagnostic(
                "EXECUTION_BINDING_MISMATCH",
                "$.payload.execution_binding",
                "The archive manifest does not bind the exact trusted execution tuple.",
            )
        )
    if (
        destination["store_identity"] != expected_store_identity
        or destination["store_key"] != expected_store_key
    ):
        diagnostics.append(
            _diagnostic(
                "RELEASE_ARCHIVE_DESTINATION_MISMATCH",
                "$.payload.archive_destination",
                "The archive manifest does not name the trusted store and key.",
            )
        )
    archived_digests = payload["archived_document_byte_digests"]
    assert isinstance(archived_digests, Mapping)
    if archived_digests != expected_archived_document_byte_digests:
        diagnostics.append(
            _diagnostic(
                "ARCHIVED_DOCUMENT_BYTES_MISMATCH",
                "$.payload.archived_document_byte_digests",
                "The archive manifest does not bind the exact independently supplied document bytes.",
            )
        )
    return tuple(sorted(diagnostics))


def validate_release_receipt(
    document: object,
    *,
    expected_candidate_identity: str,
    expected_implementation_manifest_digest: str,
    expected_execution_binding: Mapping[str, object],
    expected_launcher_identity: str,
    expected_launcher_manifest_digest: str,
    expected_archive_identity: str,
    expected_archive_manifest_digest: str,
    expected_store_identity: str,
    expected_store_key: str,
) -> tuple[Diagnostic, ...]:
    """Validate a terminal receipt against one already committed archive manifest."""

    if (
        not isinstance(document, Mapping)
        or document.get("schema_version") != "agent-equipment-release-receipt/v1"
        or not _schema_valid(document)
    ):
        return (
            _diagnostic(
                "RELEASE_RECEIPT_SCHEMA_INVALID",
                "$",
                "The release receipt does not satisfy the checked-in closed schema.",
            ),
        )
    if contains_literal_credential(document):
        return (
            _diagnostic(
                "RELEASE_RECEIPT_LITERAL_SECRET",
                "$",
                "The release receipt contains credential-shaped literal material.",
            ),
        )

    diagnostics: list[Diagnostic] = []
    payload = document["payload"]
    assert isinstance(payload, Mapping)
    destination = payload["archive_destination"]
    assert isinstance(destination, Mapping)
    if document["receipt_identity"] != "release-receipt:" + canonical_digest(payload):
        diagnostics.append(
            _diagnostic(
                "RELEASE_RECEIPT_IDENTITY_INVALID",
                "$.receipt_identity",
                "The release receipt identity does not match its canonical payload.",
            )
        )
    expected_fields = {
        "candidate_identity": expected_candidate_identity,
        "implementation_manifest_digest": expected_implementation_manifest_digest,
        "launcher_identity": expected_launcher_identity,
        "launcher_manifest_digest": expected_launcher_manifest_digest,
        "archive_identity": expected_archive_identity,
        "archive_manifest_digest": expected_archive_manifest_digest,
    }
    if any(payload[field] != expected for field, expected in expected_fields.items()):
        diagnostics.append(
            _diagnostic(
                "RELEASE_RECEIPT_AUTHORITY_MISMATCH",
                "$.payload",
                "The release receipt does not match the trusted candidate, launcher, and archive.",
            )
        )
    if payload["execution_binding"] != expected_execution_binding:
        diagnostics.append(
            _diagnostic(
                "EXECUTION_BINDING_MISMATCH",
                "$.payload.execution_binding",
                "The release receipt does not bind the exact trusted execution tuple.",
            )
        )
    if (
        destination["store_identity"] != expected_store_identity
        or destination["store_key"] != expected_store_key
    ):
        diagnostics.append(
            _diagnostic(
                "RELEASE_RECEIPT_DESTINATION_MISMATCH",
                "$.payload.archive_destination",
                "The release receipt does not name the trusted archive store and key.",
            )
        )
    return tuple(sorted(diagnostics))


__all__ = (
    "Diagnostic",
    "canonical_digest",
    "validate_apply_authorization",
    "validate_release_archive_manifest",
    "validate_release_receipt",
)
