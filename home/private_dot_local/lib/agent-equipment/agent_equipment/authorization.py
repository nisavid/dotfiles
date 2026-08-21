"""Strict apply authorization admission and one-time nonce claims."""

from __future__ import annotations

import errno
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import Lock
from types import TracebackType
from typing import Protocol, Self, TypeAlias

from ._json_schema import validate_document
from .canonical import (
    canonical_json_bytes,
    canonical_json_sha256,
    strict_load_json_bytes,
)
from .model import Diagnostic, FrozenJsonObject, freeze_json, thaw_json
from .secrets import contains_literal_credential

MAX_APPLY_AUTHORIZATION_BYTES = 256 * 1024
_SCHEMA_NAME = "execution-authority-v1.schema.json"
_SCHEMA_DIRECTORY = Path(__file__).resolve().parent.parent / "schemas"
_UTC_TIMESTAMP = re.compile(
    r"^(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})[Tt]"
    r"(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
    r"(?:[.,](?P<fraction>[0-9]{1,9}))?Z$"
)
_EXECUTION_DOMAIN_IDENTITY = re.compile(
    r"execution-domain:[A-Za-z0-9][A-Za-z0-9._/-]{0,254}"
)
_APPLY_AUTHORIZATION_IDENTITY = re.compile(r"apply-authorization:sha256:[0-9a-f]{64}")
_EXECUTION_NONCE = re.compile(r"execution-nonce:sha256:[0-9a-f]{64}")
_RUN_IDENTITY = re.compile(r"run:sha256:[0-9a-f]{64}")
_CLAIM_IDENTITY = re.compile(r"authorization-ledger-claim:sha256:([0-9a-f]{64})")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class ApplyAuthorizationTrust:
    """Independently trusted values against which one authority is admitted."""

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
    expected_bindings: FrozenJsonObject


class AuthorizationLedgerClaimStatus(Enum):
    """Closed outcome of one authorization-ledger compare-and-swap."""

    DURABLE = "durable"
    REPLAY = "replay"
    UNAVAILABLE = "unavailable"
    DURABILITY_UNCERTAIN = "durability_uncertain"


@dataclass(frozen=True, slots=True)
class AuthorizationLedgerClaim:
    """One closed authorization and run binding submitted to durable CAS."""

    apply_authorization_identity: str
    apply_authorization_digest: str
    execution_domain_identity: str
    execution_nonce: str
    run_identity: str

    def __post_init__(self) -> None:
        if not _valid_claim_bindings(self):
            raise ValueError("authorization ledger claim bindings are invalid")

    @property
    def claim_identity(self) -> str:
        return authorization_ledger_claim_identity(
            self.execution_domain_identity,
            self.execution_nonce,
        )

    def as_json(self) -> FrozenJsonObject:
        document = freeze_json(
            {
                "schema_version": ("agent-equipment-authorization-ledger-claim/v1"),
                "claim_identity": self.claim_identity,
                "apply_authorization_identity": (self.apply_authorization_identity),
                "apply_authorization_digest": self.apply_authorization_digest,
                "execution_domain_identity": self.execution_domain_identity,
                "execution_nonce": self.execution_nonce,
                "run_identity": self.run_identity,
            }
        )
        if not isinstance(document, FrozenJsonObject):
            raise TypeError("authorization ledger claim must be JSON")
        return document


class AuthorizationLedger(Protocol):
    """Domain-level port for one durable execution-nonce claim."""

    def claim(
        self,
        claim: AuthorizationLedgerClaim,
    ) -> AuthorizationLedgerClaimStatus: ...


@dataclass(frozen=True, slots=True)
class TrustedExecutionDomain:
    """Bind one deployment-owned domain identity to its sole CAS target."""

    identity: str
    authorization_ledger: AuthorizationLedger

    def __post_init__(self) -> None:
        if (
            type(self.identity) is not str
            or _EXECUTION_DOMAIN_IDENTITY.fullmatch(self.identity) is None
        ):
            raise ValueError("trusted execution domain identity is invalid")
        if not callable(getattr(self.authorization_ledger, "claim", None)):
            raise TypeError("trusted execution domain requires a claim ledger")


@dataclass(frozen=True, slots=True)
class ApplyAuthorizationGate:
    """A validation gate prebound to one authoritative execution domain."""

    _execution_domain: TrustedExecutionDomain

    def __init__(self, execution_domain: TrustedExecutionDomain) -> None:
        if type(execution_domain) is not TrustedExecutionDomain:
            raise TypeError("authorization gate requires a trusted execution domain")
        object.__setattr__(self, "_execution_domain", execution_domain)

    def authorize_apply_start(
        self,
        raw_authorization: bytes,
        trust: ApplyAuthorizationTrust,
    ) -> ApplyAuthorizationResult:
        """Validate one external authority, then claim its domain nonce."""

        return _authorize_apply_start(
            raw_authorization,
            trust,
            self._execution_domain,
        )


class FileAuthorizationLedger:
    """One trusted execution-domain ledger backed by exclusive durable files."""

    def __init__(
        self,
        root: Path,
    ) -> None:
        if not isinstance(root, Path) or not root.is_absolute() or ".." in root.parts:
            raise ValueError("authorization ledger root must be one absolute path")
        self._descriptor_lock = Lock()
        self._directory_descriptor = self._open_directory(root)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Release this ledger's stable directory binding."""

        with self._descriptor_lock:
            descriptor = self._directory_descriptor
            self._directory_descriptor = None
        if descriptor is not None:
            os.close(descriptor)

    @staticmethod
    def _open_directory(root: Path) -> int | None:
        no_follow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        if no_follow is None or directory is None:
            return None
        try:
            return os.open(
                root,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | no_follow | directory,
            )
        except OSError:
            return None

    def _duplicate_directory(self) -> int | None:
        with self._descriptor_lock:
            if self._directory_descriptor is None:
                return None
            try:
                return os.dup(self._directory_descriptor)
            except OSError:
                return None

    def claim(
        self,
        claim: AuthorizationLedgerClaim,
    ) -> AuthorizationLedgerClaimStatus:
        """Exclusively persist one closed claim and its directory entry."""

        claim_name = self._claim_name(claim)
        if claim_name is None:
            return AuthorizationLedgerClaimStatus.UNAVAILABLE
        try:
            claim_bytes = canonical_json_bytes(claim.as_json())
        except (RecursionError, UnicodeError, TypeError, ValueError):
            return AuthorizationLedgerClaimStatus.UNAVAILABLE

        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:
            return AuthorizationLedgerClaimStatus.UNAVAILABLE
        directory_descriptor = self._duplicate_directory()
        if directory_descriptor is None:
            return AuthorizationLedgerClaimStatus.UNAVAILABLE
        claim_descriptor: int | None = None
        created = False
        status = AuthorizationLedgerClaimStatus.UNAVAILABLE
        try:
            try:
                claim_descriptor = os.open(
                    claim_name,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | no_follow,
                    0o600,
                    dir_fd=directory_descriptor,
                )
                created = True
            except FileExistsError:
                return AuthorizationLedgerClaimStatus.REPLAY

            os.fchmod(claim_descriptor, 0o600)
            _write_all(claim_descriptor, claim_bytes)
            os.fsync(claim_descriptor)
            descriptor_to_close = claim_descriptor
            claim_descriptor = None
            os.close(descriptor_to_close)
            os.fsync(directory_descriptor)
            status = AuthorizationLedgerClaimStatus.DURABLE
        except OSError:
            status = (
                AuthorizationLedgerClaimStatus.DURABILITY_UNCERTAIN
                if created
                else AuthorizationLedgerClaimStatus.UNAVAILABLE
            )
        finally:
            if claim_descriptor is not None:
                descriptor_to_close = claim_descriptor
                claim_descriptor = None
                try:
                    os.close(descriptor_to_close)
                except OSError:
                    if created:
                        status = AuthorizationLedgerClaimStatus.DURABILITY_UNCERTAIN
            if directory_descriptor is not None:
                descriptor_to_close = directory_descriptor
                directory_descriptor = None
                try:
                    os.close(descriptor_to_close)
                except OSError:
                    if created:
                        status = AuthorizationLedgerClaimStatus.DURABILITY_UNCERTAIN
        return status

    def _claim_name(self, claim: AuthorizationLedgerClaim) -> str | None:
        if type(claim) is not AuthorizationLedgerClaim or not _valid_claim_bindings(
            claim
        ):
            return None
        match = _CLAIM_IDENTITY.fullmatch(claim.claim_identity)
        if match is None:
            return None
        return f"{match.group(1)}.json"


@dataclass(frozen=True, slots=True)
class ClaimedApplyAuthorization:
    """One validated authorization whose nonce is durably consumed."""

    authorization_record: FrozenJsonObject
    ledger_claim: AuthorizationLedgerClaim

    @property
    def authorization_digest(self) -> str:
        return self.ledger_claim.apply_authorization_digest

    @property
    def claim_identity(self) -> str:
        return self.ledger_claim.claim_identity


@dataclass(frozen=True, slots=True)
class AuthorizationRejection:
    """A closed, secret-free refusal to begin an apply run."""

    diagnostics: tuple[Diagnostic, ...]

    def __post_init__(self) -> None:
        if not self.diagnostics or any(
            type(diagnostic) is not Diagnostic for diagnostic in self.diagnostics
        ):
            raise ValueError("authorization rejection requires typed diagnostics")


ApplyAuthorizationResult: TypeAlias = ClaimedApplyAuthorization | AuthorizationRejection


def _authorize_apply_start(
    raw_authorization: bytes,
    trust: ApplyAuthorizationTrust,
    execution_domain: TrustedExecutionDomain,
) -> ApplyAuthorizationResult:
    """Validate one external apply authority, then durably claim its nonce."""

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
    if len(canonical_bytes) > MAX_APPLY_AUTHORIZATION_BYTES:
        return _rejection(
            "EXECUTION_AUTHORITY_JSON_INVALID",
            "The apply authorization exceeds its canonical byte bound.",
        )
    if not isinstance(authorization, FrozenJsonObject):
        return _rejection(
            "APPLY_AUTHORIZATION_SCHEMA_INVALID",
            "The apply authorization does not satisfy the checked-in closed schema.",
        )
    mutable_authorization = thaw_json(authorization)
    if type(mutable_authorization) is not dict or not validate_document(
        mutable_authorization,
        schema_directory=_SCHEMA_DIRECTORY,
        root_schema_name=_SCHEMA_NAME,
        allowed_schema_names=(_SCHEMA_NAME,),
    ):
        return _rejection(
            "APPLY_AUTHORIZATION_SCHEMA_INVALID",
            "The apply authorization does not satisfy the checked-in closed schema.",
        )
    if mutable_authorization.get("schema_version") != (
        "agent-equipment-apply-authorization/v1"
    ):
        return _rejection(
            "APPLY_AUTHORIZATION_SCHEMA_INVALID",
            "The apply authorization does not satisfy the checked-in closed schema.",
        )
    if contains_literal_credential(mutable_authorization):
        return _rejection(
            "APPLY_AUTHORIZATION_LITERAL_SECRET",
            "The apply authorization contains credential-shaped literal material.",
        )

    diagnostics = _semantic_diagnostics(mutable_authorization, trust)
    if diagnostics:
        return AuthorizationRejection(diagnostics)
    if execution_domain.identity != trust.expected_execution_domain_identity:
        return _rejection(
            "EXECUTION_DOMAIN_MISMATCH",
            "The authorization gate does not match the trusted execution domain.",
        )

    authorization_digest = canonical_json_sha256(mutable_authorization)
    claim = AuthorizationLedgerClaim(
        apply_authorization_identity=str(
            mutable_authorization["authorization_identity"]
        ),
        apply_authorization_digest=authorization_digest,
        execution_domain_identity=execution_domain.identity,
        execution_nonce=trust.expected_execution_nonce,
        run_identity=trust.expected_run_identity,
    )
    try:
        claim_status = execution_domain.authorization_ledger.claim(claim)
    except Exception:  # noqa: BLE001 - every ledger fault fails closed.
        claim_status = AuthorizationLedgerClaimStatus.DURABILITY_UNCERTAIN
    if claim_status is AuthorizationLedgerClaimStatus.DURABLE:
        return ClaimedApplyAuthorization(
            authorization_record=authorization,
            ledger_claim=claim,
        )
    return _ledger_rejection(claim_status)


def authorization_ledger_claim_identity(
    execution_domain_identity: str,
    execution_nonce: str,
) -> str:
    """Return the sole claim identity for a nonce in one execution domain."""

    return "authorization-ledger-claim:" + canonical_json_sha256(
        {
            "execution_domain_identity": execution_domain_identity,
            "execution_nonce": execution_nonce,
        }
    )


def _valid_claim_bindings(claim: AuthorizationLedgerClaim) -> bool:
    patterns = (
        (
            claim.apply_authorization_identity,
            _APPLY_AUTHORIZATION_IDENTITY,
        ),
        (claim.apply_authorization_digest, _DIGEST),
        (claim.execution_domain_identity, _EXECUTION_DOMAIN_IDENTITY),
        (claim.execution_nonce, _EXECUTION_NONCE),
        (claim.run_identity, _RUN_IDENTITY),
    )
    return all(
        type(value) is str and pattern.fullmatch(value) is not None
        for value, pattern in patterns
    )


def _semantic_diagnostics(
    authorization: dict[str, object],
    trust: ApplyAuthorizationTrust,
) -> tuple[Diagnostic, ...]:
    if not _valid_trusted_clock(trust.trusted_now):
        return (
            Diagnostic(
                code="TRUSTED_CLOCK_INVALID",
                message=("The executor must supply a timezone-aware trusted clock."),
            ),
        )
    if type(trust.expected_bindings) is not FrozenJsonObject:
        return (
            Diagnostic(
                code="APPLY_AUTHORIZATION_TRUST_INVALID",
                message=(
                    "The executor must supply one immutable trusted binding tuple."
                ),
            ),
        )

    diagnostics: list[Diagnostic] = []
    identity_payload = {
        key: value
        for key, value in authorization.items()
        if key != "authorization_identity"
    }
    derived_identity = "apply-authorization:" + canonical_json_sha256(identity_payload)
    if authorization["authorization_identity"] != derived_identity:
        diagnostics.append(
            Diagnostic(
                code="APPLY_AUTHORIZATION_IDENTITY_INVALID",
                message=(
                    "The apply-authorization identity does not match its "
                    "canonical payload."
                ),
            )
        )
    if authorization["authorization_identity"] != trust.expected_authorization_identity:
        diagnostics.append(
            Diagnostic(
                code="APPLY_AUTHORIZATION_TRUST_MISMATCH",
                message=(
                    "The apply authorization does not match the independently "
                    "trusted identity."
                ),
            )
        )
    if canonical_json_sha256(authorization) != trust.expected_authorization_digest:
        diagnostics.append(
            Diagnostic(
                code="APPLY_AUTHORIZATION_DIGEST_MISMATCH",
                message=(
                    "The apply authorization does not match the independently "
                    "trusted digest."
                ),
            )
        )
    if authorization["issuer_identity"] != trust.expected_issuer_identity:
        diagnostics.append(
            Diagnostic(
                code="APPLY_AUTHORIZATION_BINDING_MISMATCH",
                message=("The apply authorization does not match the trusted issuer."),
            )
        )
    if (
        authorization["execution_domain_identity"]
        != trust.expected_execution_domain_identity
    ):
        diagnostics.append(
            Diagnostic(
                code="EXECUTION_DOMAIN_MISMATCH",
                message=(
                    "The apply authorization does not match the independently "
                    "trusted ledger domain."
                ),
            )
        )

    bindings = authorization["bindings"]
    assert type(bindings) is dict
    if freeze_json(bindings) != trust.expected_bindings:
        diagnostics.append(
            Diagnostic(
                code="APPLY_AUTHORIZATION_BINDING_MISMATCH",
                message=(
                    "The apply authorization does not match the complete "
                    "independently trusted binding tuple."
                ),
            )
        )
    for field, expected in (
        ("candidate_identity", trust.expected_candidate_identity),
        (
            "implementation_manifest_digest",
            trust.expected_implementation_manifest_digest,
        ),
        (
            "operator_review_package_digest",
            trust.expected_operator_review_package_digest,
        ),
    ):
        if bindings[field] != expected:
            diagnostics.append(
                Diagnostic(
                    code=(
                        "OPERATOR_REVIEW_PACKAGE_BINDING_MISMATCH"
                        if field == "operator_review_package_digest"
                        else "APPLY_AUTHORIZATION_BINDING_MISMATCH"
                    ),
                    message=(
                        "The apply authorization does not match independently "
                        "trusted execution material."
                    ),
                )
            )
    if (
        authorization["execution_nonce"] != trust.expected_execution_nonce
        or authorization["run_identity"] != trust.expected_run_identity
    ):
        diagnostics.append(
            Diagnostic(
                code="EXECUTION_BINDING_MISMATCH",
                message=(
                    "The apply authorization does not match the trusted nonce and run."
                ),
            )
        )
    if not _time_window_is_valid(authorization, trust.trusted_now):
        diagnostics.append(
            Diagnostic(
                code="APPLY_AUTHORIZATION_TIME_INVALID",
                message=(
                    "The trusted clock is outside the authorization's ordered "
                    "validity window."
                ),
            )
        )
    return tuple(
        sorted(
            diagnostics,
            key=_diagnostic_sort_key,
        )
    )


def _diagnostic_sort_key(diagnostic: Diagnostic) -> tuple[str, str]:
    return diagnostic.code, diagnostic.message


def _valid_trusted_clock(value: object) -> bool:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return False
    try:
        return value.utcoffset() is not None
    except Exception:  # noqa: BLE001 - hostile datetime subclasses fail closed.
        return False


def _time_window_is_valid(
    authorization: dict[str, object], trusted_now: datetime
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


def _rejection(code: str, message: str) -> AuthorizationRejection:
    return AuthorizationRejection((Diagnostic(code=code, message=message),))


def _ledger_rejection(
    status: object,
) -> AuthorizationRejection:
    if status is AuthorizationLedgerClaimStatus.REPLAY:
        return _rejection(
            "APPLY_AUTHORIZATION_REPLAYED",
            "The execution nonce is already consumed in this authorization ledger.",
        )
    if status is AuthorizationLedgerClaimStatus.UNAVAILABLE:
        return _rejection(
            "AUTHORIZATION_LEDGER_UNAVAILABLE",
            "The authorization ledger could not durably claim the execution nonce.",
        )
    return _rejection(
        "AUTHORIZATION_LEDGER_DURABILITY_UNCERTAIN",
        "Authorization-ledger durability is uncertain; the nonce remains consumed.",
    )


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0 or written > len(payload) - offset:
            raise OSError(errno.EIO, "authorization ledger write made no progress")
        offset += written
