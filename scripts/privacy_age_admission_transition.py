#!/usr/bin/env python3
"""Evaluate the frozen Git object fixtures for one admission transition."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any


TRANSITION_SCHEMA = "privacy-age-admission-transition/v1"
OBJECT_FIXTURE_SCHEMA = "privacy-age-admission-transition-object-fixture/v1"
PREDECESSOR_FIXTURE_SCHEMA = "privacy-age-integrity-predecessor-fixture/v1"

_OBJECT_ID = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ROLE_ORDER = {"pr_base": 0, "predecessor": 1, "target": 2}
_EXPECTED_REPOSITORY = "nisavid/dotfiles"
_EXPECTED_PULL_REQUEST = 172
_EXPECTED_MIGRATION = "one-time-transition-pr-172-v1"
_EXPECTED_SNAPSHOTS = {
    "pr_base": (
        "7fbe8e520cf85c16de4ba05b9b016b153340ed05",
        "40e4f9ff2373527400e2c7bbc2ffdf879cf5fa7b",
    ),
    "predecessor": (
        "0e981202824a76043083039a407dd165e243d544",
        "ac2898cd79618f85d527e62c83537555f360be83",
    ),
    "target": (
        "d2c15543baddd922b2ce1f087ea38ada29f323fd",
        "d902f2ae6c53e53ce0983a95415727f3a5b11e9b",
    ),
}
_EXPECTED_FIXTURE_ROLES = {
    "active-predecessor": ("predecessor",),
    "pr-base-and-target": ("pr_base", "target"),
}


class TransitionEvaluationError(RuntimeError):
    """The frozen transition input did not match its closed contract."""


@dataclass(frozen=True)
class EvaluatedSnapshot:
    role: str
    commit: str
    root_tree: str


@dataclass(frozen=True)
class EvaluatedFixture:
    name: str
    pack_sha256: str
    object_count: int
    snapshots: tuple[EvaluatedSnapshot, ...]


@dataclass(frozen=True)
class TransitionEvaluation:
    repository: str
    pull_request: int
    migration: str
    snapshots: tuple[EvaluatedSnapshot, ...]
    fixtures: tuple[EvaluatedFixture, ...]


def _closed_object(value: Any, keys: set[str], *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise TransitionEvaluationError(f"{label} does not match its closed schema")
    return value


def _closed_array(value: Any, *, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise TransitionEvaluationError(f"{label} must be an array")
    return value


def _string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TransitionEvaluationError(f"{label} must be a nonempty string")
    return value


def _positive_integer(value: Any, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise TransitionEvaluationError(f"{label} must be a positive integer")
    return value


def _object_id(value: Any, *, label: str) -> str:
    object_id = _string(value, label=label)
    if _OBJECT_ID.fullmatch(object_id) is None:
        raise TransitionEvaluationError(f"{label} must be a SHA-1 object ID")
    return object_id


def _digest(value: Any, *, label: str) -> str:
    digest = _string(value, label=label)
    if _DIGEST.fullmatch(digest) is None:
        raise TransitionEvaluationError(f"{label} must be a SHA-256 digest")
    return digest


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TransitionEvaluationError("JSON contains a duplicate key")
        result[key] = value
    return result


def _load_json_bytes(contents: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            contents.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        if isinstance(error, TransitionEvaluationError):
            raise
        raise TransitionEvaluationError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise TransitionEvaluationError(f"{label} must be a JSON object")
    return value


def _repository_path(repository_root: Path, raw: Any, *, label: str) -> Path:
    value = _string(raw, label=label)
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or relative.as_posix() != value
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise TransitionEvaluationError(f"{label} must be a canonical repository path")
    root = repository_root.resolve(strict=True)
    try:
        resolved = root.joinpath(*relative.parts).resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise TransitionEvaluationError(f"{label} is unavailable") from error
    if not resolved.is_file():
        raise TransitionEvaluationError(f"{label} must name a regular file")
    return resolved


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for variable in tuple(environment):
        if variable.startswith("GIT_"):
            environment.pop(variable, None)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    return environment


def _git(
    *arguments: str,
    cwd: Path,
    input_bytes: bytes | None = None,
) -> bytes:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=cwd,
            input=input_bytes,
            check=True,
            capture_output=True,
            env=_git_environment(),
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise TransitionEvaluationError("Git object fixture evaluation failed") from error
    return completed.stdout


def _parse_snapshot(value: Any, *, label: str) -> EvaluatedSnapshot:
    item = _closed_object(
        value,
        {"role", "commit", "root_tree"},
        label=label,
    )
    role = _string(item["role"], label=f"{label}.role")
    if role not in _ROLE_ORDER:
        raise TransitionEvaluationError(f"{label}.role is not recognized")
    return EvaluatedSnapshot(
        role=role,
        commit=_object_id(item["commit"], label=f"{label}.commit"),
        root_tree=_object_id(item["root_tree"], label=f"{label}.root_tree"),
    )


def _parse_pack(value: Any, *, label: str) -> dict[str, Any]:
    pack = _closed_object(
        value,
        {"path", "sha256", "size", "object_count"},
        label=label,
    )
    return {
        "path": _string(pack["path"], label=f"{label}.path"),
        "sha256": _digest(pack["sha256"], label=f"{label}.sha256"),
        "size": _positive_integer(pack["size"], label=f"{label}.size"),
        "object_count": _positive_integer(
            pack["object_count"],
            label=f"{label}.object_count",
        ),
    }


def _parse_fixture_manifest(
    contents: bytes,
    *,
    expected_snapshots: tuple[EvaluatedSnapshot, ...],
) -> tuple[dict[str, Any], tuple[EvaluatedSnapshot, ...]]:
    value = _load_json_bytes(contents, label="object fixture manifest")
    schema = value.get("schema")
    if schema == PREDECESSOR_FIXTURE_SCHEMA:
        item = _closed_object(value, {"schema", "pack", "snapshot"}, label="fixture")
        snapshot = _closed_object(
            item["snapshot"],
            {
                "commit",
                "shallow_boundary",
                "omitted_parent",
                "root_tree",
                "integrity_gate_blob",
            },
            label="fixture.snapshot",
        )
        commit = _object_id(snapshot["commit"], label="fixture.snapshot.commit")
        if _object_id(
            snapshot["shallow_boundary"],
            label="fixture.snapshot.shallow_boundary",
        ) != commit:
            raise TransitionEvaluationError("predecessor shallow boundary is not its commit")
        _object_id(snapshot["omitted_parent"], label="fixture.snapshot.omitted_parent")
        _object_id(
            snapshot["integrity_gate_blob"],
            label="fixture.snapshot.integrity_gate_blob",
        )
        snapshots = (
            EvaluatedSnapshot(
                role="predecessor",
                commit=commit,
                root_tree=_object_id(
                    snapshot["root_tree"],
                    label="fixture.snapshot.root_tree",
                ),
            ),
        )
    elif schema == OBJECT_FIXTURE_SCHEMA:
        item = _closed_object(value, {"schema", "pack", "snapshots"}, label="fixture")
        snapshots = tuple(
            _parse_snapshot(snapshot, label=f"fixture.snapshots[{index}]")
            for index, snapshot in enumerate(
                _closed_array(item["snapshots"], label="fixture.snapshots")
            )
        )
    else:
        raise TransitionEvaluationError("object fixture schema is not recognized")

    if snapshots != expected_snapshots:
        raise TransitionEvaluationError("object fixture snapshots do not match the transition")
    return _parse_pack(item["pack"], label="fixture.pack"), snapshots


def _indexed_objects(repository: Path) -> set[str]:
    git_dir = Path(
        _git("rev-parse", "--git-dir", cwd=repository).decode("ascii").strip()
    )
    if not git_dir.is_absolute():
        git_dir = repository / git_dir
    indexes = tuple((git_dir / "objects/pack").glob("*.idx"))
    if len(indexes) != 1:
        raise TransitionEvaluationError("object fixture did not produce one pack index")
    try:
        with indexes[0].open("rb") as index:
            completed = subprocess.run(
                ("git", "show-index"),
                cwd=repository,
                stdin=index,
                check=True,
                capture_output=True,
                env=_git_environment(),
                timeout=30,
            )
    except (OSError, subprocess.SubprocessError) as error:
        raise TransitionEvaluationError("Git object fixture evaluation failed") from error
    try:
        return {
            line.split(maxsplit=2)[1].decode("ascii")
            for line in completed.stdout.splitlines()
        }
    except (IndexError, UnicodeDecodeError) as error:
        raise TransitionEvaluationError("object fixture index is malformed") from error


def _evaluate_pack(
    *,
    fixture_manifest: Path,
    pack_spec: dict[str, Any],
    snapshots: tuple[EvaluatedSnapshot, ...],
) -> tuple[str, int]:
    pack_path = _repository_path(
        fixture_manifest.parent,
        pack_spec["path"],
        label="fixture.pack.path",
    )
    pack_bytes = pack_path.read_bytes()
    if len(pack_bytes) != pack_spec["size"]:
        raise TransitionEvaluationError("object fixture pack size does not match")
    pack_digest = hashlib.sha256(pack_bytes).hexdigest()
    if pack_digest != pack_spec["sha256"]:
        raise TransitionEvaluationError("object fixture pack digest does not match")

    with TemporaryDirectory(prefix="privacy-age-transition-") as temporary:
        repository = Path(temporary) / "objects"
        repository.mkdir()
        _git("init", "--quiet", "--object-format=sha1", cwd=repository)
        _git("index-pack", "--stdin", "--fix-thin", cwd=repository, input_bytes=pack_bytes)
        indexed = _indexed_objects(repository)
        if len(indexed) != pack_spec["object_count"]:
            raise TransitionEvaluationError("object fixture pack count does not match")

        expected_objects: set[str] = set()
        for snapshot in snapshots:
            if _git("cat-file", "-t", snapshot.commit, cwd=repository).strip() != b"commit":
                raise TransitionEvaluationError("snapshot commit object is unavailable")
            commit_lines = _git("cat-file", "-p", snapshot.commit, cwd=repository).splitlines()
            tree_lines = [line for line in commit_lines if line.startswith(b"tree ")]
            if len(tree_lines) != 1:
                raise TransitionEvaluationError("snapshot commit does not name one root tree")
            observed_tree = tree_lines[0].split(maxsplit=1)[1].decode("ascii")
            if observed_tree != snapshot.root_tree:
                raise TransitionEvaluationError("snapshot root tree does not match its commit")
            if _git("cat-file", "-t", snapshot.root_tree, cwd=repository).strip() != b"tree":
                raise TransitionEvaluationError("snapshot root tree object is unavailable")
            closure = _git(
                "rev-list",
                "--objects",
                "--no-object-names",
                snapshot.root_tree,
                cwd=repository,
            )
            try:
                expected_objects.update(
                    line.decode("ascii") for line in closure.splitlines() if line
                )
            except UnicodeDecodeError as error:
                raise TransitionEvaluationError("object fixture closure is malformed") from error
            expected_objects.add(snapshot.commit)

        if indexed != expected_objects:
            raise TransitionEvaluationError("object fixture pack is not the exact object closure")

    return pack_digest, len(indexed)


def evaluate_transition(
    manifest_path: Path,
    *,
    repository_root: Path,
) -> TransitionEvaluation:
    """Validate and evaluate the closed, network-free transition fixtures."""

    root = repository_root.resolve(strict=True)
    transition_path = manifest_path.resolve(strict=True)
    try:
        transition_path.relative_to(root)
    except ValueError as error:
        raise TransitionEvaluationError("transition manifest is outside the repository") from error

    transition = _closed_object(
        _load_json_bytes(transition_path.read_bytes(), label="transition manifest"),
        {"schema", "migration", "repository", "pull_request", "fixtures"},
        label="transition manifest",
    )
    if transition["schema"] != TRANSITION_SCHEMA:
        raise TransitionEvaluationError("transition manifest schema is not recognized")
    migration = _string(transition["migration"], label="transition.migration")
    repository = _string(transition["repository"], label="transition.repository")
    pull_request = _positive_integer(
        transition["pull_request"],
        label="transition.pull_request",
    )
    if (
        repository != _EXPECTED_REPOSITORY
        or pull_request != _EXPECTED_PULL_REQUEST
        or migration != _EXPECTED_MIGRATION
    ):
        raise TransitionEvaluationError("transition identity does not match the one-time migration")

    evaluated_fixtures: list[EvaluatedFixture] = []
    all_snapshots: list[EvaluatedSnapshot] = []
    fixture_names: set[str] = set()
    for index, raw_fixture in enumerate(
        _closed_array(transition["fixtures"], label="transition.fixtures")
    ):
        label = f"transition.fixtures[{index}]"
        fixture = _closed_object(
            raw_fixture,
            {
                "name",
                "manifest",
                "manifest_sha256",
                "manifest_size",
                "snapshots",
            },
            label=label,
        )
        name = _string(fixture["name"], label=f"{label}.name")
        if name in fixture_names:
            raise TransitionEvaluationError("transition fixture names must be unique")
        fixture_names.add(name)
        expected_snapshots = tuple(
            _parse_snapshot(snapshot, label=f"{label}.snapshots[{snapshot_index}]")
            for snapshot_index, snapshot in enumerate(
                _closed_array(fixture["snapshots"], label=f"{label}.snapshots")
            )
        )
        if tuple(snapshot.role for snapshot in expected_snapshots) != _EXPECTED_FIXTURE_ROLES.get(
            name
        ) or any(
            (snapshot.commit, snapshot.root_tree) != _EXPECTED_SNAPSHOTS[snapshot.role]
            for snapshot in expected_snapshots
        ):
            raise TransitionEvaluationError("snapshot identities do not match the one-time migration")
        fixture_manifest = _repository_path(
            root,
            fixture["manifest"],
            label=f"{label}.manifest",
        )
        fixture_bytes = fixture_manifest.read_bytes()
        if len(fixture_bytes) != _positive_integer(
            fixture["manifest_size"],
            label=f"{label}.manifest_size",
        ):
            raise TransitionEvaluationError("object fixture manifest size does not match")
        if hashlib.sha256(fixture_bytes).hexdigest() != _digest(
            fixture["manifest_sha256"],
            label=f"{label}.manifest_sha256",
        ):
            raise TransitionEvaluationError("object fixture manifest digest does not match")
        pack_spec, snapshots = _parse_fixture_manifest(
            fixture_bytes,
            expected_snapshots=expected_snapshots,
        )
        pack_digest, object_count = _evaluate_pack(
            fixture_manifest=fixture_manifest,
            pack_spec=pack_spec,
            snapshots=snapshots,
        )
        evaluated_fixtures.append(
            EvaluatedFixture(
                name=name,
                pack_sha256=pack_digest,
                object_count=object_count,
                snapshots=snapshots,
            )
        )
        all_snapshots.extend(snapshots)

    roles = [snapshot.role for snapshot in all_snapshots]
    if sorted(roles) != sorted(_ROLE_ORDER):
        raise TransitionEvaluationError("transition must contain exactly three snapshot roles")
    return TransitionEvaluation(
        repository=repository,
        pull_request=pull_request,
        migration=migration,
        snapshots=tuple(sorted(all_snapshots, key=lambda snapshot: _ROLE_ORDER[snapshot.role])),
        fixtures=tuple(evaluated_fixtures),
    )
