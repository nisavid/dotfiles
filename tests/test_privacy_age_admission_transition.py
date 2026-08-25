from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

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


def mutate_target_structure(
    root: Path,
    mutations: tuple[tuple[str, str], ...],
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
        target = next(
            snapshot
            for snapshot in snapshots
            if isinstance(snapshot, dict) and snapshot.get("role") == "target"
        )
        git("read-tree", str(target["root_tree"]), cwd=repository)

        for path, mutation in mutations:
            original = git(
                "ls-tree",
                str(target["root_tree"]),
                "--",
                path,
                cwd=repository,
            ).decode("utf-8").strip()
            if not original:
                raise AssertionError(f"target fixture path is unavailable: {path}")
            mode, _, original_object_id = original.split("\t", 1)[0].split()
            git("update-index", "--force-remove", "--", path, cwd=repository)
            if mutation == "delete":
                continue
            if mutation == "alter":
                object_id = git(
                    "hash-object",
                    "-w",
                    "--stdin",
                    cwd=repository,
                    input_bytes=b"altered structural fixture\n",
                ).decode("ascii").strip()
                replacement_mode = mode
                replacement_path = path
            elif mutation == "symlink":
                object_id = git(
                    "hash-object",
                    "-w",
                    "--stdin",
                    cwd=repository,
                    input_bytes=b"outside-target\n",
                ).decode("ascii").strip()
                replacement_mode = "120000"
                replacement_path = path
            elif mutation == "directory":
                object_id = git(
                    "hash-object",
                    "-w",
                    "--stdin",
                    cwd=repository,
                    input_bytes=b"nested structural fixture\n",
                ).decode("ascii").strip()
                replacement_mode = "100644"
                replacement_path = f"{path}/nested"
            elif mutation == "gitlink":
                object_id = "7fbe8e520cf85c16de4ba05b9b016b153340ed05"
                replacement_mode = "160000"
                replacement_path = path
            elif mutation == "wrong_mode":
                object_id = original_object_id
                replacement_mode = "100755" if mode == "100644" else "100644"
                replacement_path = path
            else:
                raise AssertionError(f"unknown structural mutation: {mutation}")
            git(
                "update-index",
                "--add",
                "--cacheinfo",
                f"{replacement_mode},{object_id},{replacement_path}",
                cwd=repository,
            )

        target_tree = git("write-tree", cwd=repository).decode("ascii").strip()
        target_commit = git(
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit-tree",
            target_tree,
            cwd=repository,
            input_bytes=b"structural mutation\n",
        ).decode("ascii").strip()
        target["commit"] = target_commit
        target["root_tree"] = target_tree

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

    transition_path = root / TRANSITION_MANIFEST.relative_to(ROOT)
    transition = load_json(transition_path)
    fixtures = transition["fixtures"]
    if not isinstance(fixtures, list):
        raise AssertionError("transition fixtures are malformed")
    target_fixture = next(
        item
        for item in fixtures
        if isinstance(item, dict) and item.get("name") == "pr-base-and-target"
    )
    declared_snapshots = target_fixture["snapshots"]
    if not isinstance(declared_snapshots, list):
        raise AssertionError("target snapshots are malformed")
    declared_target = next(
        snapshot
        for snapshot in declared_snapshots
        if isinstance(snapshot, dict) and snapshot.get("role") == "target"
    )
    declared_target["commit"] = target_commit
    declared_target["root_tree"] = target_tree
    write_json(transition_path, transition)


class PrivacyAgeAdmissionTransitionTests(TestCase):
    def assert_structure_mutation_rejected(
        self,
        mutations: tuple[tuple[str, str], ...],
    ) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            transition_path = copy_fixture_bundle(root)
            mutate_target_structure(root, mutations)
            receipt_adapter = Mock(
                side_effect=AssertionError("receipt adapter ran before structure passed")
            )

            with self.assertRaisesRegex(
                TransitionEvaluationError,
                "structural Git entry|protected Git delta|protected transition entry",
            ):
                evaluate_transition(
                    transition_path,
                    repository_root=root,
                    after_structure=receipt_adapter,
                )
            receipt_adapter.assert_not_called()

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

    def test_exact_transition_structure_is_verified_from_git_objects(self) -> None:
        evaluation = evaluate_transition(
            TRANSITION_MANIFEST,
            repository_root=ROOT,
        )

        self.assertEqual(
            {entry.path for entry in evaluation.active_authority},
            {
                ".github/age-admission/allowed_signers",
                ".github/age-admission/privacy-scan-reviewed-findings-v1.json",
                "scripts/create-age-admission-receipt",
                "scripts/privacy_age_admission.py",
                "scripts/privacy_age_admission_publisher.py",
                "scripts/privacy_age_admission_result.py",
                "scripts/privacy_age_pr_snapshot.py",
                "scripts/privacy_scan_review.py",
                "scripts/run-trusted-age-admission",
            },
        )
        transitions = {
            transition.name: transition for transition in evaluation.transitions
        }
        self.assertEqual(
            {entry.path for entry in transitions["owner_receipt"].entries},
            {
                ".github/age-admission/privacy-scan-reviewed-findings-v1.json",
                ".github/workflows/platform-portability.yml",
                "docs/ENCRYPTION.md",
                "scripts/privacy-scan",
                "scripts/privacy_age_integrity_gate.py",
                "scripts/privacy_scan_review.py",
            },
        )
        self.assertEqual(
            {entry.path for entry in transitions["app_result"].entries},
            {
                ".github/age-admission/privacy-scan-reviewed-findings-v1.json",
                ".github/workflows/platform-portability.yml",
                ".github/workflows/privacy-age-integrity.yml",
                "docs/ENCRYPTION.md",
                "scripts/privacy-scan",
                "scripts/privacy_age_admission_publisher.py",
                "scripts/privacy_age_admission_result.py",
                "scripts/privacy_age_integrity_gate.py",
                "scripts/privacy_age_pr_snapshot.py",
                "scripts/privacy_scan_review.py",
            },
        )
        self.assertTrue(
            all(
                entry.kind == "blob"
                and entry.mode in {"100644", "100755"}
                and len(entry.object_id) == 40
                and entry.size is not None
                and entry.sha256 is not None
                for entry in evaluation.active_authority
            )
        )
        self.assertTrue(
            all(
                side.kind == "blob"
                and side.size is not None
                and side.sha256 is not None
                for transition in evaluation.transitions
                for entry in transition.entries
                for side in (entry.base, entry.head)
                if side is not None
            )
        )

    def test_structural_validation_rejects_a_deleted_transition_path(self) -> None:
        self.assert_structure_mutation_rejected(
            (("docs/ENCRYPTION.md", "delete"),)
        )

    def test_structural_validation_rejects_altered_transition_bytes(self) -> None:
        self.assert_structure_mutation_rejected(
            ((".github/workflows/platform-portability.yml", "alter"),)
        )

    def test_structural_validation_rejects_wrong_kinds_and_modes(self) -> None:
        cases = (
            ("symlink", "scripts/privacy_scan_review.py", "symlink"),
            ("directory", "scripts/privacy_age_admission_publisher.py", "directory"),
            ("gitlink", "scripts/privacy_age_admission_result.py", "gitlink"),
            ("wrong-mode", "scripts/create-age-admission-receipt", "wrong_mode"),
        )
        for name, path, mutation in cases:
            with self.subTest(name=name):
                self.assert_structure_mutation_rejected(((path, mutation),))

    def test_structural_validation_requires_each_new_authority_path(self) -> None:
        review_record = (
            ".github/age-admission/privacy-scan-reviewed-findings-v1.json"
        )
        reviewer = "scripts/privacy_scan_review.py"
        cases = (
            ("review-record", ((review_record, "delete"),)),
            ("reviewer", ((reviewer, "delete"),)),
            (
                "both",
                (
                    (review_record, "delete"),
                    (reviewer, "delete"),
                ),
            ),
        )
        for name, mutations in cases:
            with self.subTest(name=name):
                self.assert_structure_mutation_rejected(mutations)

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

            with self.assertRaises(TransitionEvaluationError):
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

            with self.assertRaises(TransitionEvaluationError):
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
