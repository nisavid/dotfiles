#!/usr/bin/env python3
"""Compare a PR head to its trusted base without executing candidate code."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

COMMIT_ID = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)

# Changes to these paths require an owner-controlled ruleset disposition after
# local identity-backed admission. The pull_request_target workflow executes
# this list from the trusted base commit, never from the candidate checkout.
PROTECTED_EXACT_PATHS = frozenset(
    {
        b".privacy-age-envelopes.json",
        b"docs/ENCRYPTION.md",
        b"home/.chezmoi.toml.tmpl",
        b"scripts/admit-age-envelopes",
        b"scripts/agent_equipment_public_data.py",
        b"scripts/privacy-scan",
        b"scripts/privacy_age_envelopes.py",
        b"scripts/privacy_age_integrity_gate.py",
    }
)
PROTECTED_OPTIONAL_PATHS = frozenset({b".gitattributes", b".gitmodules"})
PROTECTED_PREFIXES = (b".github/workflows/",)


class IntegrityGateError(RuntimeError):
    """The exact base/head comparison could not establish the boundary."""


@dataclass(frozen=True)
class TreeEntry:
    mode: bytes
    kind: bytes
    object_id: bytes


def _git(repository: Path, *arguments: str) -> bytes:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
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


def verify_integrity_boundary(
    *,
    base_repository: Path,
    base_commit: str,
    head_repository: Path,
    head_commit: str,
) -> None:
    """Reject every protected path transition between exact checkouts."""

    base = _validated_checkout(base_repository, base_commit)
    head = _validated_checkout(head_repository, head_commit)
    base_tree = _tree(base, base_commit)
    head_tree = _tree(head, head_commit)

    missing_base_paths = sorted(PROTECTED_EXACT_PATHS - base_tree.keys())
    if missing_base_paths:
        raise IntegrityGateError("trusted base is missing a protected path")

    protected_paths = {
        path for path in base_tree.keys() | head_tree.keys() if _is_protected(path)
    }
    if not protected_paths:
        raise IntegrityGateError("trusted base has no protected boundary")
    changed = sorted(
        path for path in protected_paths if base_tree.get(path) != head_tree.get(path)
    )
    if changed:
        raise IntegrityGateError(f"candidate changes {len(changed)} protected path(s)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-repository", type=Path, required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--head-repository", type=Path, required=True)
    parser.add_argument("--head-commit", required=True)
    arguments = parser.parse_args()
    try:
        verify_integrity_boundary(
            base_repository=arguments.base_repository,
            base_commit=arguments.base_commit,
            head_repository=arguments.head_repository,
            head_commit=arguments.head_commit,
        )
    except IntegrityGateError as error:
        print(f"privacy age integrity gate failed: {error}", file=sys.stderr)
        return 1
    print("privacy age integrity boundary verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
