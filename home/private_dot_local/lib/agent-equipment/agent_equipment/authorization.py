"""Durable one-time authorization-ledger claims."""

from __future__ import annotations

import errno
import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import Lock
from types import TracebackType
from typing import Self

from .canonical import canonical_json_bytes, canonical_json_sha256
from .model import FrozenJsonObject, freeze_json

_EXECUTION_DOMAIN_IDENTITY = re.compile(
    r"execution-domain:[A-Za-z0-9][A-Za-z0-9._/-]{0,254}"
)
_APPLY_AUTHORIZATION_IDENTITY = re.compile(r"apply-authorization:sha256:[0-9a-f]{64}")
_EXECUTION_NONCE = re.compile(r"execution-nonce:sha256:[0-9a-f]{64}")
_RUN_IDENTITY = re.compile(r"run:sha256:[0-9a-f]{64}")
_CLAIM_IDENTITY = re.compile(r"authorization-ledger-claim:sha256:([0-9a-f]{64})")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


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


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0 or written > len(payload) - offset:
            raise OSError(errno.EIO, "authorization ledger write made no progress")
        offset += written
