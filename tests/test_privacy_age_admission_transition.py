from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.privacy_age_admission_transition import (
    TransitionEvaluationError,
    evaluate_transition,
)


ROOT = Path(__file__).resolve().parents[1]
TRANSITION_MANIFEST = (
    ROOT / ".github/age-admission/one-time-transition-pr-172-v1.json"
)
PREDECESSOR_FIXTURE = (
    ROOT / "tests/fixtures/privacy-age-integrity/legacy-active-base-v1.json"
)
TARGET_FIXTURE = (
    ROOT
    / "tests/fixtures/privacy-age-admission-transition/pr-172-base-target-v1.json"
)


def load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"fixture is not an object: {path}")
    return value


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def copy_fixture_bundle(root: Path) -> Path:
    paths = (
        TRANSITION_MANIFEST.relative_to(ROOT),
        PREDECESSOR_FIXTURE.relative_to(ROOT),
        PREDECESSOR_FIXTURE.with_suffix(".pack").relative_to(ROOT),
        TARGET_FIXTURE.relative_to(ROOT),
        TARGET_FIXTURE.with_suffix(".pack").relative_to(ROOT),
    )
    for relative in paths:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    return root / TRANSITION_MANIFEST.relative_to(ROOT)


def refresh_fixture_manifest_pin(root: Path, fixture_manifest: Path) -> None:
    transition_path = root / TRANSITION_MANIFEST.relative_to(ROOT)
    transition = load_json(transition_path)
    fixtures = transition["fixtures"]
    if not isinstance(fixtures, list):
        raise AssertionError("transition fixtures are malformed")
    relative = fixture_manifest.relative_to(root).as_posix()
    contents = fixture_manifest.read_bytes()
    for fixture in fixtures:
        if isinstance(fixture, dict) and fixture.get("manifest") == relative:
            fixture["manifest_sha256"] = hashlib.sha256(contents).hexdigest()
            fixture["manifest_size"] = len(contents)
            write_json(transition_path, transition)
            return
    raise AssertionError(f"transition does not reference {relative}")


def fixture_git_environment() -> dict[str, str]:
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
            "LC_ALL": "C",
        }
    )
    return environment


def git(*arguments: str, cwd: Path, input_bytes: bytes | None = None) -> bytes:
    return subprocess.run(
        ("git", *arguments),
        cwd=cwd,
        input=input_bytes,
        check=True,
        capture_output=True,
        env=fixture_git_environment(),
        timeout=30,
    ).stdout


def replace_target_pack(
    root: Path,
    *,
    replace_missing_object: bool,
) -> None:
    fixture_path = root / TARGET_FIXTURE.relative_to(ROOT)
    fixture = load_json(fixture_path)
    pack_spec = fixture["pack"]
    snapshots = fixture["snapshots"]
    if not isinstance(pack_spec, dict) or not isinstance(snapshots, list):
        raise AssertionError("target fixture is malformed")
    pack_path = fixture_path.parent / str(pack_spec["path"])

    with TemporaryDirectory() as temporary:
        repository = Path(temporary) / "objects"
        repository.mkdir()
        git("init", "--quiet", "--object-format=sha1", cwd=repository)
        git("index-pack", "--stdin", "--fix-thin", cwd=repository, input_bytes=pack_path.read_bytes())
        git_dir = repository / git("rev-parse", "--git-dir", cwd=repository).decode().strip()
        index = next((git_dir / "objects/pack").glob("*.idx"))
        with index.open("rb") as stream:
            indexed = subprocess.run(
                ("git", "show-index"),
                cwd=repository,
                stdin=stream,
                check=True,
                capture_output=True,
                env=fixture_git_environment(),
                timeout=30,
            ).stdout
        object_ids = {
            line.split(maxsplit=2)[1].decode("ascii")
            for line in indexed.splitlines()
        }
        target = next(
            snapshot
            for snapshot in snapshots
            if isinstance(snapshot, dict) and snapshot.get("role") == "target"
        )
        leaves = git(
            "ls-tree",
            "-r",
            "--full-tree",
            str(target["root_tree"]),
            cwd=repository,
        ).splitlines()
        victim = next(
            line.split(maxsplit=3)[2].decode("ascii")
            for line in leaves
            if line.split(maxsplit=3)[1] == b"blob"
        )
        object_ids.remove(victim)
        if replace_missing_object:
            replacement = git(
                "hash-object",
                "-w",
                "--stdin",
                cwd=repository,
                input_bytes=b"unrelated replacement fixture\n",
            ).decode("ascii").strip()
            object_ids.add(replacement)
        new_pack = git(
            "pack-objects",
            "--stdout",
            "--window=0",
            cwd=repository,
            input_bytes=("\n".join(sorted(object_ids)) + "\n").encode("ascii"),
        )

    pack_path.write_bytes(new_pack)
    pack_spec["sha256"] = hashlib.sha256(new_pack).hexdigest()
    pack_spec["size"] = len(new_pack)
    pack_spec["object_count"] = len(object_ids)
    write_json(fixture_path, fixture)
    refresh_fixture_manifest_pin(root, fixture_path)


def repack_target_for_declared_snapshots(root: Path) -> None:
    fixture_path = root / TARGET_FIXTURE.relative_to(ROOT)
    fixture = load_json(fixture_path)
    pack_spec = fixture["pack"]
    snapshots = fixture["snapshots"]
    if not isinstance(pack_spec, dict) or not isinstance(snapshots, list):
        raise AssertionError("target fixture is malformed")
    pack_path = fixture_path.parent / str(pack_spec["path"])

    with TemporaryDirectory() as temporary:
        repository = Path(temporary) / "objects"
        repository.mkdir()
        git("init", "--quiet", "--object-format=sha1", cwd=repository)
        git("index-pack", "--stdin", "--fix-thin", cwd=repository, input_bytes=pack_path.read_bytes())
        object_ids: set[str] = set()
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                raise AssertionError("target snapshot is malformed")
            object_ids.add(str(snapshot["commit"]))
            object_ids.update(
                git(
                    "rev-list",
                    "--objects",
                    "--no-object-names",
                    str(snapshot["root_tree"]),
                    cwd=repository,
                )
                .decode("ascii")
                .splitlines()
            )
        new_pack = git(
            "pack-objects",
            "--stdout",
            "--window=0",
            cwd=repository,
            input_bytes=("\n".join(sorted(object_ids)) + "\n").encode("ascii"),
        )

    pack_path.write_bytes(new_pack)
    pack_spec["sha256"] = hashlib.sha256(new_pack).hexdigest()
    pack_spec["size"] = len(new_pack)
    pack_spec["object_count"] = len(object_ids)
    write_json(fixture_path, fixture)
    refresh_fixture_manifest_pin(root, fixture_path)


class PrivacyAgeAdmissionTransitionTests(TestCase):
    def test_exact_three_snapshot_fixture_is_complete(self) -> None:
        evaluation = evaluate_transition(
            TRANSITION_MANIFEST,
            repository_root=ROOT,
        )

        self.assertEqual(evaluation.repository, "nisavid/dotfiles")
        self.assertEqual(evaluation.pull_request, 172)
        self.assertEqual(evaluation.migration, "one-time-transition-pr-172-v1")
        self.assertEqual(
            {
                snapshot.role: (snapshot.commit, snapshot.root_tree)
                for snapshot in evaluation.snapshots
            },
            {
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
            },
        )
        self.assertEqual(
            {fixture.name: fixture.object_count for fixture in evaluation.fixtures},
            {
                "active-predecessor": 655,
                "pr-base-and-target": 682,
            },
        )

    def test_transition_rejects_a_different_commit_even_with_its_matching_tree(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            transition_path = copy_fixture_bundle(root)
            fixture_path = root / TARGET_FIXTURE.relative_to(ROOT)
            fixture = load_json(fixture_path)
            fixture_snapshots = fixture["snapshots"]
            self.assertIsInstance(fixture_snapshots, list)
            target = next(
                snapshot
                for snapshot in fixture_snapshots
                if isinstance(snapshot, dict) and snapshot.get("role") == "target"
            )
            target["commit"] = "7fbe8e520cf85c16de4ba05b9b016b153340ed05"
            target["root_tree"] = "40e4f9ff2373527400e2c7bbc2ffdf879cf5fa7b"
            write_json(fixture_path, fixture)
            repack_target_for_declared_snapshots(root)

            transition = load_json(transition_path)
            fixtures = transition["fixtures"]
            self.assertIsInstance(fixtures, list)
            target_fixture = next(
                entry
                for entry in fixtures
                if isinstance(entry, dict) and entry.get("name") == "pr-base-and-target"
            )
            snapshots = target_fixture["snapshots"]
            self.assertIsInstance(snapshots, list)
            target_pin = next(
                snapshot
                for snapshot in snapshots
                if isinstance(snapshot, dict) and snapshot.get("role") == "target"
            )
            target_pin["commit"] = target["commit"]
            target_pin["root_tree"] = target["root_tree"]
            write_json(transition_path, transition)

            with self.assertRaisesRegex(
                TransitionEvaluationError,
                "snapshot identities do not match",
            ):
                evaluate_transition(transition_path, repository_root=root)

    def test_transition_rejects_a_wrong_root_tree(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            transition_path = copy_fixture_bundle(root)
            transition = load_json(transition_path)
            fixtures = transition["fixtures"]
            self.assertIsInstance(fixtures, list)
            target_fixture = next(
                entry
                for entry in fixtures
                if isinstance(entry, dict) and entry.get("name") == "pr-base-and-target"
            )
            snapshots = target_fixture["snapshots"]
            self.assertIsInstance(snapshots, list)
            target = next(
                snapshot
                for snapshot in snapshots
                if isinstance(snapshot, dict) and snapshot.get("role") == "target"
            )
            target["root_tree"] = "40e4f9ff2373527400e2c7bbc2ffdf879cf5fa7b"
            write_json(transition_path, transition)

            with self.assertRaisesRegex(
                TransitionEvaluationError,
                "snapshot identities do not match",
            ):
                evaluate_transition(transition_path, repository_root=root)

    def test_transition_rejects_a_wrong_pack_digest(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            transition_path = copy_fixture_bundle(root)
            fixture_path = root / TARGET_FIXTURE.relative_to(ROOT)
            fixture = load_json(fixture_path)
            pack_spec = fixture["pack"]
            self.assertIsInstance(pack_spec, dict)
            pack_spec["sha256"] = "0" * 64
            write_json(fixture_path, fixture)
            refresh_fixture_manifest_pin(root, fixture_path)

            with self.assertRaisesRegex(
                TransitionEvaluationError,
                "pack digest does not match",
            ):
                evaluate_transition(transition_path, repository_root=root)

    def test_transition_rejects_a_wrong_pack_object_count(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            transition_path = copy_fixture_bundle(root)
            fixture_path = root / TARGET_FIXTURE.relative_to(ROOT)
            fixture = load_json(fixture_path)
            pack_spec = fixture["pack"]
            self.assertIsInstance(pack_spec, dict)
            pack_spec["object_count"] = 681
            write_json(fixture_path, fixture)
            refresh_fixture_manifest_pin(root, fixture_path)

            with self.assertRaisesRegex(
                TransitionEvaluationError,
                "pack count does not match",
            ):
                evaluate_transition(transition_path, repository_root=root)

    def test_transition_rejects_a_pack_with_a_missing_tree_object(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            transition_path = copy_fixture_bundle(root)
            replace_target_pack(root, replace_missing_object=False)

            with patch.dict(
                os.environ,
                {
                    "GIT_ALTERNATE_OBJECT_DIRECTORIES": os.fspath(
                        ROOT / ".git/objects"
                    ),
                    "GIT_NO_LAZY_FETCH": "0",
                },
                clear=False,
            ):
                with self.assertRaisesRegex(
                    TransitionEvaluationError,
                    "Git object fixture evaluation failed",
                ):
                    evaluate_transition(transition_path, repository_root=root)

    def test_transition_rejects_a_pack_with_a_replacement_object(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            transition_path = copy_fixture_bundle(root)
            replace_target_pack(root, replace_missing_object=True)

            with self.assertRaisesRegex(
                TransitionEvaluationError,
                "Git object fixture evaluation failed|not the exact object closure",
            ):
                evaluate_transition(transition_path, repository_root=root)

    def test_transition_ignores_hostile_git_routing_variables(self) -> None:
        hostile = {
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": "/definitely/missing/alternates",
            "GIT_COMMON_DIR": "/definitely/missing/common",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "extensions.objectFormat",
            "GIT_CONFIG_VALUE_0": "sha256",
            "GIT_DEFAULT_HASH": "sha256",
            "GIT_DIR": "/definitely/missing/repository",
            "GIT_INDEX_FILE": "/definitely/missing/index",
            "GIT_OBJECT_DIRECTORY": "/definitely/missing/objects",
            "GIT_REPLACE_REF_BASE": "refs/hostile-replacements/",
            "GIT_WORK_TREE": "/definitely/missing/worktree",
        }
        with patch.dict(os.environ, hostile, clear=False):
            evaluation = evaluate_transition(
                TRANSITION_MANIFEST,
                repository_root=ROOT,
            )

        self.assertEqual(
            {snapshot.role for snapshot in evaluation.snapshots},
            {"pr_base", "predecessor", "target"},
        )
