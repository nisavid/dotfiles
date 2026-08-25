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
from enum import Enum
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
        MAX_ADMISSION_PATHS,
        AdmissionReceiptError,
        extract_receipt,
        validate_payload,
        verify_receipt_signature,
    )
    from .privacy_age_admission_result import (
        AdmissionResultError,
        body_digest,
        canonical_json_bytes,
        make_result,
        make_state,
        parse_canonical_json,
        validate_snapshot,
        validate_state,
    )
    from .privacy_age_envelopes import AgeEnvelopeError, read_regular_file
except ImportError:  # pragma: no cover - direct script execution
    from privacy_age_admission import (
        ADMISSION_VERSION,
        MAX_ADMISSION_BODY_BYTES,
        MAX_ADMISSION_PATHS,
        AdmissionReceiptError,
        extract_receipt,
        validate_payload,
        verify_receipt_signature,
    )
    from privacy_age_admission_result import (
        AdmissionResultError,
        body_digest,
        canonical_json_bytes,
        make_result,
        make_state,
        parse_canonical_json,
        validate_snapshot,
        validate_state,
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
        b".github/age-admission/privacy-scan-reviewed-findings-v1.json",
        b".privacy-age-envelopes.json",
        b"docs/ENCRYPTION.md",
        b"home/.chezmoi.toml.tmpl",
        b"home/private_dot_local/lib/agent-equipment/agent_equipment/secrets.py",
        b"scripts/admit-age-envelopes",
        b"scripts/agent_equipment_public_data.py",
        b"scripts/create-age-admission-receipt",
        b"scripts/run-trusted-age-admission",
        b"scripts/privacy-scan",
        b"scripts/privacy_scan_review.py",
        b"scripts/privacy_age_admission.py",
        b"scripts/privacy_age_envelopes.py",
        b"scripts/privacy_age_integrity_gate.py",
        b"scripts/privacy_age_admission_result.py",
        b"scripts/privacy_age_pr_snapshot.py",
        b"scripts/privacy_age_admission_publisher.py",
    }
)
LEGACY_ACTIVE_BASE_COMMIT = "0e981202824a76043083039a407dd165e243d544"
LEGACY_ADMISSION_INFRASTRUCTURE_PATHS = frozenset(
    {
        b".github/age-admission/allowed_signers",
        b"scripts/create-age-admission-receipt",
        b"scripts/run-trusted-age-admission",
        b"scripts/privacy_age_admission.py",
        b"scripts/privacy_age_admission_result.py",
        b"scripts/privacy_age_pr_snapshot.py",
        b"scripts/privacy_age_admission_publisher.py",
    }
)
ADMISSION_INFRASTRUCTURE_PATHS = LEGACY_ADMISSION_INFRASTRUCTURE_PATHS | frozenset(
    {
        b"scripts/privacy_scan_review.py",
        b".github/age-admission/privacy-scan-reviewed-findings-v1.json",
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
    b"scripts/privacy_age_admission_result.py": (b"blob", b"100644"),
    b"scripts/privacy_age_pr_snapshot.py": (b"blob", b"100644"),
    b"scripts/privacy_age_admission_publisher.py": (b"blob", b"100644"),
    b"scripts/privacy_scan_review.py": (b"blob", b"100644"),
    b".github/age-admission/privacy-scan-reviewed-findings-v1.json": (
        b"blob",
        b"100644",
    ),
    # The scanner's classifier is inherited unchanged during bootstrap; keep
    # its mode invariant here without making an unchanged base blob a stale
    # bootstrap replacement.
    b"scripts/agent_equipment_public_data.py": (b"blob", b"100644"),
}
LEGACY_ADMISSION_INFRASTRUCTURE_ENTRIES = {
    path: BOOTSTRAP_REQUIRED_ENTRIES[path]
    for path in LEGACY_ADMISSION_INFRASTRUCTURE_PATHS
}
ADMISSION_INFRASTRUCTURE_ENTRIES = {
    path: BOOTSTRAP_REQUIRED_ENTRIES[path] for path in ADMISSION_INFRASTRUCTURE_PATHS
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
        b"e924bb92aae4c97626aa47ef385627bc4f7c8637",
    ),
    b"scripts/create-age-admission-receipt": (
        b"blob",
        b"100755",
        b"ee1eccff9d1747a207c3349ec4306847e3537fa1",
    ),
    b"scripts/privacy_age_admission.py": (
        b"blob",
        b"100644",
        b"28c87a5c184ab323e813148c168a0022d0642675",
    ),
    b"scripts/privacy_age_envelopes.py": (
        b"blob",
        b"100644",
        b"b052cbfcff312a37e4ecf38a88f6fac77025cc3e",
    ),
    b"scripts/run-trusted-age-admission": (
        b"blob",
        b"100755",
        b"fef9847973839e4dded51275761099a9cf2be728",
    ),
    # These result/snapshot/publication modules are trusted-base authority;
    # their reviewed blobs must be replaced together during bootstrap.
    b"scripts/privacy_age_admission_result.py": (
        b"blob",
        b"100644",
        b"24c9fb25e1891340ee451a291dda93a20389701f",
    ),
    b"scripts/privacy_age_pr_snapshot.py": (
        b"blob",
        b"100644",
        b"06ff19944db5ff83ca32044fb7f0c52d10626682",
    ),
    b"scripts/privacy_age_admission_publisher.py": (
        b"blob",
        b"100644",
        b"42fc7887c8cb59625db8e103131eb089611fa90f",
    ),
    b"scripts/privacy_scan_review.py": (
        b"blob",
        b"100644",
        b"554ebdbc5269b74122ba29730215d621e31f404d",
    ),
    b".github/age-admission/privacy-scan-reviewed-findings-v1.json": (
        b"blob",
        b"100644",
        b"9e92be25c33b2451e7f4de71c1ef890c200c130b",
    ),
}
# These support files are part of this reviewed bootstrap revision, but are not
# admission authority. Permit only their exact reviewed Git blobs; every other
# protected collateral change remains outside the one-time exception.
BOOTSTRAP_REVIEWED_SUPPORT_ENTRIES = {
    b".github/workflows/privacy-age-integrity.yml": (
        b"blob",
        b"100644",
        b"ac6d1610d245bac428b56504d7872b3424e4523f",
    ),
    b".github/workflows/platform-portability.yml": (
        b"blob",
        b"100644",
        b"fea93f6a2805d1899722f806ecd11d40c6c259c6",
    ),
    b"docs/ENCRYPTION.md": (
        b"blob",
        b"100644",
        b"fbb9361b2bd7e2eb7c1c9a04428ad3478ee8a125",
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


class AdmissionBoundaryState(str, Enum):
    """Closed trusted-base generations understood by this verifier revision."""

    PRE_BOOTSTRAP = "pre_bootstrap"
    ACTIVE_PREVIOUS = "active_previous"
    ACTIVE_CURRENT = "active_current"


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
    boundary_state: AdmissionBoundaryState


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
    if kind == "commit":
        # A gitlink records a commit identity, but the submodule object is not
        # guaranteed to exist in either checkout. Bind the recorded identity
        # directly instead of asking Git to load an unavailable submodule.
        digest = "sha256:" + hashlib.sha256(entry.object_id).hexdigest()
    else:
        data = _git(
            repository,
            "cat-file",
            kind,
            entry.object_id.decode("ascii"),
            maximum_output_bytes=MAX_GIT_OBJECT_BYTES,
        )
        # Keep the digest over exact Git object bytes, independent of Git's
        # object hash algorithm, for blobs, trees, and symlink targets.
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
    return {"kind": kind, "mode": mode, "sha256": digest}


def _boundary_entries_match(
    tree: dict[bytes, TreeEntry],
    expected: dict[bytes, tuple[bytes, bytes]],
) -> bool:
    return all(
        path in tree and (tree[path].kind, tree[path].mode) == identity
        for path, identity in expected.items()
    )


def _classify_admission_boundary(
    *,
    base: Path,
    base_commit: str,
    base_tree: dict[bytes, TreeEntry],
) -> AdmissionBoundaryState:
    """Recognize only the pre-bootstrap, pinned predecessor, or current boundary."""

    infrastructure_present = frozenset(
        ADMISSION_INFRASTRUCTURE_PATHS & base_tree.keys()
    )
    marker_present = _has_activation_sentinel(base, base_tree)
    if not infrastructure_present:
        if marker_present:
            raise IntegrityGateError("trusted base has an invalid admission boundary")
        return AdmissionBoundaryState.PRE_BOOTSTRAP
    if infrastructure_present == LEGACY_ADMISSION_INFRASTRUCTURE_PATHS:
        if (
            base_commit != LEGACY_ACTIVE_BASE_COMMIT
            or not marker_present
            or not _boundary_entries_match(
                base_tree,
                LEGACY_ADMISSION_INFRASTRUCTURE_ENTRIES,
            )
        ):
            raise IntegrityGateError("trusted base has an invalid admission boundary")
        return AdmissionBoundaryState.ACTIVE_PREVIOUS
    if infrastructure_present == ADMISSION_INFRASTRUCTURE_PATHS:
        if not marker_present or not _boundary_entries_match(
            base_tree,
            ADMISSION_INFRASTRUCTURE_ENTRIES,
        ):
            raise IntegrityGateError("trusted base has an invalid admission boundary")
        return AdmissionBoundaryState.ACTIVE_CURRENT
    raise IntegrityGateError("trusted base has an invalid admission boundary")


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
    boundary_state = _classify_admission_boundary(
        base=base,
        base_commit=base_commit,
        base_tree=base_tree,
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
        boundary_state=boundary_state,
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
        if path in transition.changed
        and (
            path not in transition.head_tree
            or (
                transition.head_tree[path].kind,
                transition.head_tree[path].mode,
                transition.head_tree[path].object_id,
            )
            != expected
        )
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

    if transition.boundary_state in {
        AdmissionBoundaryState.ACTIVE_PREVIOUS,
        AdmissionBoundaryState.ACTIVE_CURRENT,
    }:
        _require_active_head_complete(transition)
    if (
        require_bootstrap
        and transition.boundary_state is AdmissionBoundaryState.PRE_BOOTSTRAP
    ):
        _require_bootstrap_head_complete(transition)
        raise IntegrityGateError(
            "trusted base predates signed admission; bootstrap owner exception required"
        )


def _admission_paths(
    transition: ProtectedTransition,
) -> list[dict[str, object]]:
    if len(transition.changed) > MAX_ADMISSION_PATHS:
        raise IntegrityGateError("protected transition changes too many paths")
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

    if repository is None:
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
        return
    evaluate_integrity_boundary(
        base_repository=base_repository,
        base_commit=base_commit,
        head_repository=head_repository,
        head_commit=head_commit,
        admission_body=admission_body,
        allowed_signers=allowed_signers,
        repository=repository,
    )


def evaluate_integrity_boundary(
    *,
    base_repository: Path,
    base_commit: str,
    head_repository: Path,
    head_commit: str,
    admission_body: bytes | None = None,
    allowed_signers: Path | None = None,
    repository: str | None = None,
) -> dict[str, object]:
    """Return the closed App result after enforcing the exact boundary.

    The transition is classified before admission-body parsing. Consequently,
    an empty protected set produces terminal success without calling the
    receipt parser; all uncertainty remains a blocking exception.
    """

    if repository is None:
        raise IntegrityGateError("repository identity is required for a result")
    transition = _protected_transition(
        base_repository=base_repository,
        base_commit=base_commit,
        head_repository=head_repository,
        head_commit=head_commit,
    )
    return _evaluate_transition(
        transition,
        base_commit=base_commit,
        head_commit=head_commit,
        admission_body=admission_body,
        allowed_signers=allowed_signers,
        repository=repository,
    )


def _evaluate_transition(
    transition: ProtectedTransition,
    *,
    base_commit: str,
    head_commit: str,
    admission_body: bytes | None,
    allowed_signers: Path | None,
    repository: str,
) -> dict[str, object]:
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
    try:
        paths = [path.decode("ascii") for path in transition.changed]
        return make_result(
            repository=repository,
            base_commit=base_commit,
            head_commit=head_commit,
            protected_paths=paths,
        )
    except (UnicodeDecodeError, AdmissionResultError) as error:
        raise IntegrityGateError("admission result could not be formed") from error


def _write_result_file(path: Path, document: dict[str, object]) -> None:
    data = canonical_json_bytes(document) + b"\n"
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    if not no_follow:
        raise IntegrityGateError("safe result output is unavailable")
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow,
            0o600,
        )
    except OSError as error:
        raise IntegrityGateError("result output is unavailable") from error
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_snapshot_state(path: Path) -> dict[str, object]:
    try:
        document = parse_canonical_json(
            read_regular_file(path, maximum=MAX_ADMISSION_BODY_BYTES)
        )
    except (AgeEnvelopeError, OSError, UnicodeError, ValueError, RecursionError) as error:
        raise IntegrityGateError("live snapshot state is unavailable") from error
    if not isinstance(document, dict):
        raise IntegrityGateError("live snapshot state is invalid")
    if document.get("state") == "failed":
        try:
            return validate_state(document)
        except AdmissionResultError as error:
            raise IntegrityGateError("live snapshot state is invalid") from error
    try:
        validate_snapshot(document)
    except AdmissionResultError as error:
        raise IntegrityGateError("live snapshot state is invalid") from error
    return validate_snapshot(document).as_dict()


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
    parser.add_argument("--result-file", type=Path)
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--snapshot-file", type=Path)
    arguments = parser.parse_args()
    snapshot_document: dict[str, object] | None = None
    try:
        result_mode = any(
            value is not None
            for value in (
                arguments.result_file,
                arguments.state_file,
                arguments.snapshot_file,
            )
        )
        if not result_mode:
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
            print("privacy age integrity boundary verified")
            return 0
        if arguments.repository is None:
            raise IntegrityGateError("repository identity is required")
        if arguments.snapshot_file is not None:
            snapshot_state = _read_snapshot_state(arguments.snapshot_file)
            if snapshot_state.get("state") == "failed":
                if arguments.state_file is not None:
                    _write_result_file(arguments.state_file, snapshot_state)
                return 1
            snapshot_document = snapshot_state
            snapshot = validate_snapshot(snapshot_state)
            if (
                snapshot.repository != arguments.repository
                or snapshot.base_ref != "main"
                or snapshot.base_commit != arguments.base_commit
                or snapshot.head_commit != arguments.head_commit
                or snapshot.state != "open"
            ):
                raise IntegrityGateError("live snapshot does not match verifier inputs")

        # Inspect the transition before opening the pull-request body. The
        # empty outcome must not depend on receipt bytes or invoke its parser.
        transition = _protected_transition(
            base_repository=arguments.base_repository,
            base_commit=arguments.base_commit,
            head_repository=arguments.head_repository,
            head_commit=arguments.head_commit,
        )
        admission_body = None
        if transition.changed and arguments.admission_body is not None:
            try:
                admission_body = read_regular_file(
                    arguments.admission_body,
                    maximum=MAX_ADMISSION_BODY_BYTES,
                )
            except (AgeEnvelopeError, OSError) as error:
                raise IntegrityGateError("admission body is unavailable") from error
            if snapshot_document is not None:
                snapshot = validate_snapshot(snapshot_document)
                if body_digest(admission_body) != snapshot.body_sha256:
                    raise IntegrityGateError(
                        "admission body changed after the live snapshot"
                    )
        result = _evaluate_transition(
            transition,
            base_commit=arguments.base_commit,
            head_commit=arguments.head_commit,
            admission_body=admission_body,
            allowed_signers=arguments.allowed_signers,
            repository=arguments.repository,
        )
        if arguments.result_file is not None:
            _write_result_file(arguments.result_file, result)
        if arguments.state_file is not None:
            if snapshot_document is None:
                raise IntegrityGateError("result state lacks a live snapshot")
            _write_result_file(
                arguments.state_file,
                make_state(snapshot=snapshot_document, result=result),
            )
    except (IntegrityGateError, AdmissionResultError) as error:
        if arguments.state_file is not None:
            try:
                _write_result_file(
                    arguments.state_file,
                    make_state(
                        snapshot=snapshot_document,
                        error_code="verifier_failed",
                    ),
                )
            except (IntegrityGateError, AdmissionResultError):
                pass
        print(f"privacy age integrity gate failed: {error}", file=sys.stderr)
        return 1
    print("privacy age integrity boundary verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
