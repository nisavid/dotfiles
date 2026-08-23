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

# Isolated Python omits the script directory from `sys.path`. Re-add only this
# canonical trusted directory before loading the sibling verifier modules; the
# workflow verifies this file's exact Git blob before execution.
_SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if _SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, _SCRIPT_DIRECTORY)

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
        b"scripts/privacy-scan",
        b"scripts/privacy_age_envelopes.py",
        b"scripts/privacy_age_integrity_gate.py",
    }
)
BOOTSTRAP_REQUIRED_ENTRIES = {
    b".github/age-admission/allowed_signers": (b"blob", b"100644"),
    b".github/workflows/privacy-age-integrity.yml": (b"blob", b"100644"),
    b"scripts/admit-age-envelopes": (b"blob", b"100755"),
    b"scripts/privacy-scan": (b"blob", b"100755"),
    b"scripts/create-age-admission-receipt": (b"blob", b"100755"),
    b"scripts/run-trusted-age-admission": (b"blob", b"100755"),
    b"scripts/privacy_age_admission.py": (b"blob", b"100644"),
    b"scripts/privacy_age_envelopes.py": (b"blob", b"100644"),
    b"scripts/privacy_age_integrity_gate.py": (b"blob", b"100755"),
    # The scanner's classifier is inherited unchanged during bootstrap; keep
    # its mode invariant here without making an unchanged base blob a stale
    # bootstrap replacement.
    b"scripts/agent_equipment_public_data.py": (b"blob", b"100644"),
}
# Once activated, every trusted verifier, scanner, parser, launcher, and the
# protected workflow remains a required regular entry. A signed receipt may
# authorize its content change, but it cannot silently remove a seam and leave
# the next run without the code that enforces the boundary.
ACTIVE_REQUIRED_PATHS = BOOTSTRAP_REQUIRED_PATHS | frozenset(
    {b"scripts/agent_equipment_public_data.py"}
)
# The first verifier key is an authority root, not merely bootstrap collateral.
# Pin its exact reviewed blob so the one-time owner exception cannot install a
# candidate-chosen key that would authorize later transitions indefinitely.
BOOTSTRAP_REVIEWED_SIGNER_ENTRY = (
    b"blob",
    b"100644",
    b"3455d1413afc070001e300e622bccd5427eda72c",
)
# Pin every bootstrap authority blob that is not self-referential. The
# remaining gate blob is covered by the independent owner-side tree digest in
# the bootstrap runbook because embedding its own object ID would be circular.
BOOTSTRAP_REVIEWED_AUTHORITY_ENTRIES = {
    b"scripts/admit-age-envelopes": (
        b"blob",
        b"100755",
        b"a16b9da9c51b87556df85a2d6a5165aef16ecfe3",
    ),
    b"scripts/privacy-scan": (
        b"blob",
        b"100755",
        b"612a2ae9acde883d3f2b5e92ce8cefc4fcf0d1bf",
    ),
    b"scripts/create-age-admission-receipt": (
        b"blob",
        b"100755",
        b"dc3335b5032e2ad809609783379bdf06b75dbf09",
    ),
    b"scripts/privacy_age_admission.py": (
        b"blob",
        b"100644",
        b"d92fd11bd6fddcd5a1847226f6bbd1b5676ae871",
    ),
    b"scripts/privacy_age_envelopes.py": (
        b"blob",
        b"100644",
        b"b052cbfcff312a37e4ecf38a88f6fac77025cc3e",
    ),
    b"scripts/run-trusted-age-admission": (
        b"blob",
        b"100755",
        b"55fabfffe72b2e0a099f0effaf673380219f4889",
    ),
}
# These support files are part of this reviewed bootstrap revision, but are not
# admission authority. Permit only their exact reviewed Git blobs; every other
# protected collateral change remains outside the one-time exception.
BOOTSTRAP_REVIEWED_SUPPORT_ENTRIES = {
    b".github/workflows/privacy-age-integrity.yml": (
        b"blob",
        b"100644",
        b"7881ce3c5cdb789fd861e48f46c3c82c313a21a4",
    ),
    b".github/workflows/platform-portability.yml": (
        b"blob",
        b"100644",
        b"fea93f6a2805d1899722f806ecd11d40c6c259c6",
    ),
    b"docs/ENCRYPTION.md": (
        b"blob",
        b"100644",
        b"64f297f1bd17670d21c8cef32e67f7f966ad86fe",
    ),
}
# This marker lives in the already protected workflow.  The legacy
# pre-bootstrap gate therefore prevents a pull request from activating the
# new boundary merely by pre-seeding the four new pathnames.  Keep the marker
# when making later workflow edits; it is a reservation, not a whole-file
# digest.
ADMISSION_ACTIVATION_PATH = b".github/workflows/privacy-age-integrity.yml"
ADMISSION_ACTIVATION_MARKER = (
    b"# Protected admission activation sentinel: owner-signed-age-v1\n"
)
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
    activation_present: bool


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
        if (
            len(object_id) != 40
            or COMMIT_ID.fullmatch(object_id.decode("ascii", "ignore")) is None
        ):
            raise IntegrityGateError("git tree object identity is malformed")
        if len(entries) >= MAX_GIT_TREE_ENTRIES:
            raise IntegrityGateError("git tree contains too many entries")
        entries[path] = TreeEntry(mode=mode, kind=kind, object_id=object_id)
    return entries


def _has_activation_sentinel(
    repository: Path,
    tree: dict[bytes, TreeEntry],
) -> bool:
    """Recognize the boundary only after the legacy-protected marker landed."""

    entry = tree.get(ADMISSION_ACTIVATION_PATH)
    if entry is None or entry.kind != b"blob" or entry.mode != b"100644":
        return False
    data = _git(
        repository,
        "cat-file",
        "blob",
        entry.object_id.decode("ascii"),
        maximum_output_bytes=MAX_GIT_OBJECT_BYTES,
    )
    marker = ADMISSION_ACTIVATION_MARKER.rstrip(b"\r\n")
    return marker in data.splitlines()


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
    activation_present = (
        infrastructure_present == ADMISSION_INFRASTRUCTURE_PATHS
        and _has_activation_sentinel(base, base_tree)
    )

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
        activation_present=activation_present,
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
    malformed.update(
        path
        for path, expected in BOOTSTRAP_REVIEWED_SUPPORT_ENTRIES.items()
        if path in transition.head_tree
        and (
            transition.head_tree[path].kind,
            transition.head_tree[path].mode,
            transition.head_tree[path].object_id,
        )
        != expected
    )
    malformed.update(
        path
        for path, expected in BOOTSTRAP_REVIEWED_AUTHORITY_ENTRIES.items()
        if path in transition.head_tree
        and (
            transition.head_tree[path].kind,
            transition.head_tree[path].mode,
            transition.head_tree[path].object_id,
        )
        != expected
    )
    signer = transition.head_tree.get(b".github/age-admission/allowed_signers")
    if (
        signer is None
        or (signer.kind, signer.mode, signer.object_id)
        != BOOTSTRAP_REVIEWED_SIGNER_ENTRY
    ):
        malformed.add(b".github/age-admission/allowed_signers")
    if not _has_activation_sentinel(transition.head, transition.head_tree):
        malformed.add(ADMISSION_ACTIVATION_PATH)
    if unexpected:
        raise IntegrityGateError(
            "bootstrap candidate is not limited to admission infrastructure"
        )
    if missing or malformed or stale:
        raise IntegrityGateError(
            "bootstrap candidate is missing complete admission infrastructure"
        )


def _require_active_head_complete(transition: ProtectedTransition) -> None:
    """Never admit a transition that removes or disables the active boundary."""

    missing = ACTIVE_REQUIRED_PATHS - transition.head_tree.keys()
    malformed = {
        path
        for path, expected in BOOTSTRAP_REQUIRED_ENTRIES.items()
        if path in ACTIVE_REQUIRED_PATHS
        and (
            path not in transition.head_tree
            or (
                transition.head_tree[path].kind,
                transition.head_tree[path].mode,
            )
            != expected
        )
    }
    if missing or malformed:
        raise IntegrityGateError(
            "active admission infrastructure must remain complete"
        )
    if not _has_activation_sentinel(transition.head, transition.head_tree):
        raise IntegrityGateError("admission activation sentinel must remain present")


def _require_admission_boundary_ready(
    transition: ProtectedTransition,
    *,
    require_bootstrap: bool,
) -> None:
    """Share active-boundary and one-time bootstrap ordering across callers."""

    if transition.activation_present:
        _require_active_head_complete(transition)
    if require_bootstrap and (
        transition.infrastructure_present != ADMISSION_INFRASTRUCTURE_PATHS
        or not transition.activation_present
    ):
        _require_bootstrap_head_complete(transition)
        raise IntegrityGateError(
            "trusted base predates signed admission; bootstrap owner exception required"
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
        signer_path = b".github/age-admission/allowed_signers"
        signer_entry = transition.base_tree.get(signer_path)
        canonical_allowed_signers = allowed_signers.resolve(strict=True)
        expected_signers_path = (transition.base / os.fsdecode(signer_path)).resolve(
            strict=True
        )
        if (
            canonical_allowed_signers != expected_signers_path
            or signer_entry is None
            or signer_entry.kind != b"blob"
            or signer_entry.mode != b"100644"
        ):
            raise AdmissionReceiptError(
                "admission signer configuration is not trusted"
            )
        signer_bytes = read_regular_file(
            canonical_allowed_signers,
            maximum=MAX_GIT_OBJECT_BYTES,
        )
        expected_signer_bytes = _git(
            transition.base,
            "cat-file",
            "blob",
            signer_entry.object_id.decode("ascii"),
            maximum_output_bytes=MAX_GIT_OBJECT_BYTES,
        )
        if signer_bytes != expected_signer_bytes:
            raise AdmissionReceiptError(
                "admission signer configuration does not match the trusted tree"
            )
        verify_receipt_signature(
            payload_bytes,
            signature,
            allowed_signers=canonical_allowed_signers,
        )
    except (AdmissionReceiptError, AgeEnvelopeError, OSError) as error:
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
    _require_admission_boundary_ready(
        transition,
        require_bootstrap=bool(transition.changed),
    )
    if transition.changed:
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
    _require_admission_boundary_ready(transition, require_bootstrap=True)
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
