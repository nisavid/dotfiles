#!/usr/bin/env python3
"""Compare a PR head to its trusted base without executing candidate code."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from .privacy_age_admission import (
        ADMISSION_VERSION,
        MAX_ADMISSION_BODY_BYTES,
        AdmissionReceiptError,
        extract_receipt,
        validate_payload,
        verify_receipt_signature,
    )
    from .privacy_age_envelopes import AgeEnvelopeError, read_regular_file
except ImportError:  # pragma: no cover - direct script execution
    from privacy_age_admission import (
        ADMISSION_VERSION,
        MAX_ADMISSION_BODY_BYTES,
        AdmissionReceiptError,
        extract_receipt,
        validate_payload,
        verify_receipt_signature,
    )
    from privacy_age_envelopes import AgeEnvelopeError, read_regular_file

COMMIT_ID = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
MAX_GIT_TREE_BYTES = 8 * 1024 * 1024
MAX_GIT_TREE_ENTRIES = 10_000
MAX_GIT_OBJECT_BYTES = 16 * 1024 * 1024

# Changes to these paths require a signed owner admission after local
# identity-backed validation. The pull_request_target workflow executes this
# list from the trusted base commit, never from the candidate checkout.
PROTECTED_EXACT_PATHS = frozenset(
    {
        b".github/age-admission/allowed_signers",
        b".privacy-age-envelopes.json",
        b"docs/ENCRYPTION.md",
        b"home/.chezmoi.toml.tmpl",
        b"home/private_dot_local/lib/agent-equipment/agent_equipment/secrets.py",
        b"scripts/admit-age-envelopes",
        b"scripts/agent_equipment_public_data.py",
        b"scripts/create-age-admission-receipt",
        b"scripts/run-trusted-age-admission",
        b"scripts/privacy-scan",
        b"scripts/privacy_age_admission.py",
        b"scripts/privacy_age_envelopes.py",
        b"scripts/privacy_age_integrity_gate.py",
    }
)
ADMISSION_INFRASTRUCTURE_PATHS = frozenset(
    {
        b".github/age-admission/allowed_signers",
        b"scripts/create-age-admission-receipt",
        b"scripts/run-trusted-age-admission",
        b"scripts/privacy_age_admission.py",
    }
)
# A pre-bootstrap base already has the legacy gate, workflow, and envelope
# scanner. The break-glass merge is safe only when the head replaces all of
# those legacy seams and adds the signed-admission seams together.
BOOTSTRAP_REQUIRED_PATHS = ADMISSION_INFRASTRUCTURE_PATHS | frozenset(
    {
        b".github/workflows/privacy-age-integrity.yml",
        b"scripts/admit-age-envelopes",
        b"scripts/privacy_age_envelopes.py",
        b"scripts/privacy_age_integrity_gate.py",
    }
)
BOOTSTRAP_REQUIRED_ENTRIES = {
    b".github/age-admission/allowed_signers": (b"blob", b"100644"),
    b".github/workflows/privacy-age-integrity.yml": (b"blob", b"100644"),
    b"scripts/admit-age-envelopes": (b"blob", b"100755"),
    b"scripts/create-age-admission-receipt": (b"blob", b"100755"),
    b"scripts/run-trusted-age-admission": (b"blob", b"100755"),
    b"scripts/privacy_age_admission.py": (b"blob", b"100644"),
    b"scripts/privacy_age_envelopes.py": (b"blob", b"100644"),
    b"scripts/privacy_age_integrity_gate.py": (b"blob", b"100755"),
}
# These support files are part of this reviewed bootstrap revision, but are not
# admission authority. Permit only their exact reviewed Git blobs; every other
# protected collateral change remains outside the one-time exception.
BOOTSTRAP_REVIEWED_SUPPORT_ENTRIES = {
    b".github/workflows/platform-portability.yml": (
        b"blob",
        b"100644",
        b"fea93f6a2805d1899722f806ecd11d40c6c259c6",
    ),
    b"docs/ENCRYPTION.md": (
        b"blob",
        b"100644",
        b"50ea29d9d96c1d3c63866cea1cc39040bf83ea09",
    ),
}
PROTECTED_OPTIONAL_PATHS = frozenset({b".gitattributes", b".gitmodules"})
PROTECTED_PREFIXES = (b".github/actions/", b".github/workflows/")


class IntegrityGateError(RuntimeError):
    """The exact base/head comparison could not establish the boundary."""


@dataclass(frozen=True)
class TreeEntry:
    mode: bytes
    kind: bytes
    object_id: bytes


@dataclass(frozen=True)
class ProtectedTransition:
    """The exact protected tree transition shared by signing and verification."""

    base: Path
    base_commit: str
    head: Path
    head_commit: str
    base_tree: dict[bytes, TreeEntry]
    head_tree: dict[bytes, TreeEntry]
    changed: tuple[bytes, ...]
    infrastructure_present: frozenset[bytes]


def _git(
    repository: Path,
    *arguments: str,
    maximum_output_bytes: int | None = None,
) -> bytes:
    environment = os.environ.copy()
    for variable in (
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_LOCAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_WORK_TREE",
    ):
        environment.pop(variable, None)
    for variable in tuple(environment):
        if variable.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            environment.pop(variable, None)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
        }
    )
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                "core.fsmonitor=false",
                "-c",
                f"core.hooksPath={os.devnull}",
                "-C",
                os.fspath(repository),
                *arguments,
            ],
            check=False,
            capture_output=True,
            env=environment,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise IntegrityGateError("git object inspection failed") from error
    if result.returncode != 0:
        raise IntegrityGateError("git object inspection failed")
    if maximum_output_bytes is not None and len(result.stdout) > maximum_output_bytes:
        raise IntegrityGateError("git object inspection exceeded its size limit")
    return result.stdout


def _validated_checkout(repository: Path, expected_commit: str) -> Path:
    if COMMIT_ID.fullmatch(expected_commit) is None:
        raise IntegrityGateError("expected commit is not an exact object identity")
    try:
        canonical = repository.resolve(strict=True)
    except OSError as error:
        raise IntegrityGateError("checkout is unavailable") from error
    if not canonical.is_dir():
        raise IntegrityGateError("checkout is unavailable")
    actual = _git(canonical, "rev-parse", "--verify", "HEAD").decode("ascii").strip()
    if actual != expected_commit:
        raise IntegrityGateError("checkout does not match the expected commit")
    resolved = (
        _git(
            canonical,
            "rev-parse",
            "--verify",
            f"{expected_commit}^{{commit}}",
        )
        .decode("ascii")
        .strip()
    )
    if resolved != expected_commit:
        raise IntegrityGateError("expected commit is unavailable")
    return canonical


def _tree(repository: Path, commit: str) -> dict[bytes, TreeEntry]:
    raw = _git(
        repository,
        "ls-tree",
        "-r",
        "-t",
        "-z",
        "--full-tree",
        commit,
        maximum_output_bytes=MAX_GIT_TREE_BYTES,
    )
    entries: dict[bytes, TreeEntry] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, path = record.split(b"\t", 1)
            mode, kind, object_id = metadata.split(b" ", 2)
        except ValueError as error:
            raise IntegrityGateError("git tree record is malformed") from error
        if not path or path in entries:
            raise IntegrityGateError("git tree paths are not unique")
        if len(entries) >= MAX_GIT_TREE_ENTRIES:
            raise IntegrityGateError("git tree contains too many entries")
        entries[path] = TreeEntry(mode=mode, kind=kind, object_id=object_id)
    return entries


def _is_age_path(path: bytes) -> bool:
    return path.rsplit(b"/", 1)[-1].lower().endswith(b".age")


def _is_protected(path: bytes) -> bool:
    return (
        path in PROTECTED_EXACT_PATHS
        or path in PROTECTED_OPTIONAL_PATHS
        or any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES)
        or _is_age_path(path)
    )


def _tree_side(
    repository: Path,
    entry: TreeEntry | None,
) -> dict[str, str | None] | None:
    if entry is None:
        return None
    try:
        kind = entry.kind.decode("ascii")
        mode = entry.mode.decode("ascii")
    except UnicodeDecodeError as error:
        raise IntegrityGateError("protected tree metadata is not ASCII") from error
    data = _git(
        repository,
        "cat-file",
        kind,
        entry.object_id.decode("ascii"),
        maximum_output_bytes=MAX_GIT_OBJECT_BYTES,
    )
    # Keep the digest over the exact Git object bytes, independent of Git's
    # object hash algorithm. This also binds symlink and gitlink transitions.
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    return {"kind": kind, "mode": mode, "sha256": digest}


def _protected_transition(
    *,
    base_repository: Path,
    base_commit: str,
    head_repository: Path,
    head_commit: str,
) -> ProtectedTransition:
    """Inspect one exact base/head pair and derive its protected transition."""

    base = _validated_checkout(base_repository, base_commit)
    head = _validated_checkout(head_repository, head_commit)
    base_tree = _tree(base, base_commit)
    head_tree = _tree(head, head_commit)

    missing_base_paths = sorted(
        (PROTECTED_EXACT_PATHS - ADMISSION_INFRASTRUCTURE_PATHS) - base_tree.keys()
    )
    if missing_base_paths:
        raise IntegrityGateError("trusted base is missing a protected path")
    infrastructure_present = frozenset(
        ADMISSION_INFRASTRUCTURE_PATHS & base_tree.keys()
    )
    if infrastructure_present and infrastructure_present != ADMISSION_INFRASTRUCTURE_PATHS:
        raise IntegrityGateError("trusted base has an incomplete admission boundary")

    protected_paths = {
        path for path in base_tree.keys() | head_tree.keys() if _is_protected(path)
    }
    if not protected_paths:
        raise IntegrityGateError("trusted base has no protected boundary")
    changed = tuple(
        sorted(path for path in protected_paths if base_tree.get(path) != head_tree.get(path))
    )
    return ProtectedTransition(
        base=base,
        base_commit=base_commit,
        head=head,
        head_commit=head_commit,
        base_tree=base_tree,
        head_tree=head_tree,
        changed=changed,
        infrastructure_present=infrastructure_present,
    )


def _require_bootstrap_head_complete(transition: ProtectedTransition) -> None:
    unexpected = {
        path
        for path in set(transition.changed) - BOOTSTRAP_REQUIRED_PATHS
        if (
            path not in BOOTSTRAP_REVIEWED_SUPPORT_ENTRIES
            or transition.head_tree.get(path) is None
            or (
                transition.head_tree[path].kind,
                transition.head_tree[path].mode,
                transition.head_tree[path].object_id,
            )
            != BOOTSTRAP_REVIEWED_SUPPORT_ENTRIES[path]
        )
    }
    missing = BOOTSTRAP_REQUIRED_PATHS - transition.head_tree.keys()
    malformed = {
        path
        for path, expected in BOOTSTRAP_REQUIRED_ENTRIES.items()
        if path in transition.head_tree
        and (
            transition.head_tree[path].kind,
            transition.head_tree[path].mode,
        )
        != expected
    }
    stale = {
        path
        for path in BOOTSTRAP_REQUIRED_PATHS
        if path in transition.base_tree
        and transition.head_tree.get(path) is not None
        and (
            transition.head_tree[path].kind,
            transition.head_tree[path].object_id,
        )
        == (
            transition.base_tree[path].kind,
            transition.base_tree[path].object_id,
        )
    }
    if unexpected:
        raise IntegrityGateError(
            "bootstrap candidate is not limited to admission infrastructure"
        )
    if missing or malformed or stale:
        raise IntegrityGateError(
            "bootstrap candidate is missing complete admission infrastructure"
        )


def _admission_paths(
    transition: ProtectedTransition,
) -> list[dict[str, object]]:
    paths: list[dict[str, object]] = []
    for path in transition.changed:
        try:
            relative = path.decode("ascii")
        except UnicodeDecodeError as error:
            raise IntegrityGateError("protected path is not ASCII") from error
        paths.append(
            {
                "base": _tree_side(
                    transition.base,
                    transition.base_tree.get(path),
                ),
                "head": _tree_side(
                    transition.head,
                    transition.head_tree.get(path),
                ),
                "path": relative,
            }
        )
    return paths


def _verify_admission(
    transition: ProtectedTransition,
    *,
    admission_body: bytes | None,
    allowed_signers: Path | None,
    repository: str | None,
) -> None:
    if admission_body is None:
        raise IntegrityGateError(
            f"candidate changes {len(transition.changed)} protected path(s) without admission"
        )
    try:
        receipt = extract_receipt(admission_body)
    except AdmissionReceiptError as error:
        raise IntegrityGateError("admission receipt is invalid") from error
    if receipt is None or allowed_signers is None or repository is None:
        raise IntegrityGateError("protected transition lacks trusted admission inputs")
    payload, payload_bytes, signature = receipt
    try:
        validated = validate_payload(
            payload,
            expected_repository=repository,
            expected_base_commit=transition.base_commit,
            expected_head_commit=transition.head_commit,
        )
        expected_paths = _admission_paths(transition)
        if validated["paths"] != expected_paths:
            raise AdmissionReceiptError("admission paths do not match transition")
        canonical_allowed_signers = allowed_signers.resolve(strict=True)
        try:
            canonical_allowed_signers.relative_to(transition.base)
        except ValueError as error:
            raise AdmissionReceiptError(
                "admission signer configuration is not trusted"
            ) from error
        verify_receipt_signature(
            payload_bytes,
            signature,
            allowed_signers=canonical_allowed_signers,
        )
    except (AdmissionReceiptError, OSError) as error:
        raise IntegrityGateError("admission receipt is not authorized") from error


def verify_integrity_boundary(
    *,
    base_repository: Path,
    base_commit: str,
    head_repository: Path,
    head_commit: str,
    admission_body: bytes | None = None,
    allowed_signers: Path | None = None,
    repository: str | None = None,
) -> None:
    """Reject every unadmitted protected transition between exact checkouts."""

    transition = _protected_transition(
        base_repository=base_repository,
        base_commit=base_commit,
        head_repository=head_repository,
        head_commit=head_commit,
    )
    if transition.changed:
        if transition.infrastructure_present != ADMISSION_INFRASTRUCTURE_PATHS:
            _require_bootstrap_head_complete(transition)
            raise IntegrityGateError(
                "trusted base predates signed admission; bootstrap owner exception required"
            )
        _verify_admission(
            transition,
            admission_body=admission_body,
            allowed_signers=allowed_signers,
            repository=repository,
        )


def build_admission_payload(
    *,
    base_repository: Path,
    base_commit: str,
    head_repository: Path,
    head_commit: str,
    repository: str,
    issued_at: str,
    expires_at: str,
    nonce: str,
) -> dict[str, object]:
    """Build the signed payload for the exact protected transition."""

    transition = _protected_transition(
        base_repository=base_repository,
        base_commit=base_commit,
        head_repository=head_repository,
        head_commit=head_commit,
    )
    if transition.infrastructure_present != ADMISSION_INFRASTRUCTURE_PATHS:
        _require_bootstrap_head_complete(transition)
        raise IntegrityGateError(
            "trusted base predates signed admission; bootstrap owner exception required"
        )
    if not transition.changed:
        raise IntegrityGateError("candidate has no protected transition to admit")
    payload: dict[str, object] = {
        "base_commit": base_commit,
        "expires_at": expires_at,
        "head_commit": head_commit,
        "issued_at": issued_at,
        "nonce": nonce,
        "paths": _admission_paths(transition),
        "repository": repository,
        "version": ADMISSION_VERSION,
    }
    return validate_payload(
        payload,
        expected_repository=repository,
        expected_base_commit=base_commit,
        expected_head_commit=head_commit,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-repository", type=Path, required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--head-repository", type=Path, required=True)
    parser.add_argument("--head-commit", required=True)
    parser.add_argument("--admission-body", type=Path)
    parser.add_argument("--allowed-signers", type=Path)
    parser.add_argument("--repository")
    arguments = parser.parse_args()
    try:
        try:
            admission_body = (
                read_regular_file(
                    arguments.admission_body,
                    maximum=MAX_ADMISSION_BODY_BYTES,
                )
                if arguments.admission_body is not None
                else None
            )
        except (AgeEnvelopeError, OSError) as error:
            raise IntegrityGateError("admission body is unavailable") from error
        verify_integrity_boundary(
            base_repository=arguments.base_repository,
            base_commit=arguments.base_commit,
            head_repository=arguments.head_repository,
            head_commit=arguments.head_commit,
            admission_body=admission_body,
            allowed_signers=arguments.allowed_signers,
            repository=arguments.repository,
        )
    except IntegrityGateError as error:
        print(f"privacy age integrity gate failed: {error}", file=sys.stderr)
        return 1
    print("privacy age integrity boundary verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
