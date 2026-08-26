from __future__ import annotations

import builtins
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from scripts import privacy_age_admission_transition as transition_module
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
TARGET_COMMIT = "d2c15543baddd922b2ce1f087ea38ada29f323fd"
REVIEW_RECORD_PATH = (
    ".github/age-admission/privacy-scan-reviewed-findings-v1.json"
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


def frozen_target_bytes(path: str) -> bytes:
    return git("show", f"{TARGET_COMMIT}:{path}", cwd=ROOT)


def compact_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def replace_target_files(
    root: Path,
    replacements: dict[str, tuple[str, bytes] | None],
) -> None:
    fixture_path = root / TARGET_FIXTURE.relative_to(ROOT)
    fixture = load_json(fixture_path)
    pack_spec = fixture["pack"]
    snapshots = fixture["snapshots"]
    if not isinstance(pack_spec, dict) or not isinstance(snapshots, list):
        raise AssertionError("target fixture is malformed")
    pack_path = fixture_path.parent / str(pack_spec["path"])

    observed_entries: dict[str, tuple[str, str, str] | None] = {}
    with TemporaryDirectory() as temporary:
        repository = Path(temporary) / "objects"
        repository.mkdir()
        git("init", "--quiet", "--object-format=sha1", cwd=repository)
        git(
            "index-pack",
            "--stdin",
            "--fix-thin",
            cwd=repository,
            input_bytes=pack_path.read_bytes(),
        )
        target = next(
            snapshot
            for snapshot in snapshots
            if isinstance(snapshot, dict) and snapshot.get("role") == "target"
        )
        git("read-tree", str(target["root_tree"]), cwd=repository)
        for path, replacement in replacements.items():
            git("update-index", "--force-remove", "--", path, cwd=repository)
            if replacement is None:
                observed_entries[path] = None
                continue
            mode, contents = replacement
            object_id = git(
                "hash-object",
                "-w",
                "--stdin",
                cwd=repository,
                input_bytes=contents,
            ).decode("ascii").strip()
            git(
                "update-index",
                "--add",
                "--cacheinfo",
                f"{mode},{object_id},{path}",
                cwd=repository,
            )
            observed_entries[path] = (mode, "blob", object_id)

        target_tree = git("write-tree", cwd=repository).decode("ascii").strip()
        target_commit = git(
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit-tree",
            target_tree,
            cwd=repository,
            input_bytes=b"finding mutation\n",
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
    structure = transition["structure"]
    if not isinstance(fixtures, list) or not isinstance(structure, dict):
        raise AssertionError("transition is malformed")
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

    entries = structure["entries"]
    if not isinstance(entries, dict) or not isinstance(entries.get("target"), list):
        raise AssertionError("target structure entries are malformed")
    target_entries = entries["target"]
    for path, observed in observed_entries.items():
        for entry in target_entries:
            if isinstance(entry, list) and entry and entry[0] == path:
                if observed is None:
                    break
                mode, kind, object_id = observed
                entry[:] = [path, kind, mode, object_id]
                break
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

    def assert_finding_mutation_rejected(
        self,
        replacements: dict[str, tuple[str, bytes] | None],
        *,
        pattern: str = "review record|reviewed finding|finding validation",
    ) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            transition_path = copy_fixture_bundle(root)
            replace_target_files(root, replacements)
            receipt_adapter = Mock(
                side_effect=AssertionError("later adapter ran before findings passed")
            )

            with self.assertRaisesRegex(TransitionEvaluationError, pattern):
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

    def test_exact_five_reviewed_findings_are_bound_to_target_bytes(self) -> None:
        evaluation = evaluate_transition(
            TRANSITION_MANIFEST,
            repository_root=ROOT,
        )

        self.assertEqual(
            [
                (
                    finding.path,
                    finding.line,
                    finding.rule,
                    finding.category,
                    finding.content_sha256,
                    finding.mode,
                    finding.object_id,
                    finding.file_size,
                    finding.file_sha256,
                )
                for finding in evaluation.findings
            ],
            [
                (
                    ".github/workflows/privacy-age-integrity.yml",
                    0,
                    "provider-token",
                    "runtime_action_output_reference",
                    "sha256:fc988d046c322bc5974da1d2025db0cba6e2a6d64466d2b1f705fb355e0a7c41",
                    "100644",
                    "ac6d1610d245bac428b56504d7872b3424e4523f",
                    28_304,
                    "fc988d046c322bc5974da1d2025db0cba6e2a6d64466d2b1f705fb355e0a7c41",
                ),
                (
                    "scripts/privacy_age_admission_publisher.py",
                    163,
                    "provider-token",
                    "runtime_checks_bearer_header",
                    "sha256:8c4caac7ac5e8cd87623b6b53dba33f2c07f06a20d2539abc36009e5be8d7eeb",
                    "100644",
                    "42fc7887c8cb59625db8e103131eb089611fa90f",
                    23_420,
                    "8c4caac7ac5e8cd87623b6b53dba33f2c07f06a20d2539abc36009e5be8d7eeb",
                ),
                (
                    "scripts/privacy_age_pr_snapshot.py",
                    83,
                    "provider-token",
                    "runtime_pr_read_bearer_header",
                    "sha256:f2c9a7cfd2ff2be9d99085d46f0b274d7b913a9fcd8b01729e7823294f119d49",
                    "100644",
                    "06ff19944db5ff83ca32044fb7f0c52d10626682",
                    11_309,
                    "f2c9a7cfd2ff2be9d99085d46f0b274d7b913a9fcd8b01729e7823294f119d49",
                ),
                (
                    "tests/test_privacy_age_admission_app.py",
                    444,
                    "provider-token",
                    "mocked_test_canary",
                    "sha256:603e0ba78e3055609b7f3469c769f88d8eba3fbe837f956d52ef3b19e3bd7e7d",
                    "100644",
                    "690b3534e3322919d65c67a8b035fa84841aaf79",
                    18_479,
                    "603e0ba78e3055609b7f3469c769f88d8eba3fbe837f956d52ef3b19e3bd7e7d",
                ),
                (
                    "tests/test_privacy_age_admission_app.py",
                    479,
                    "provider-token",
                    "mocked_test_canary",
                    "sha256:603e0ba78e3055609b7f3469c769f88d8eba3fbe837f956d52ef3b19e3bd7e7d",
                    "100644",
                    "690b3534e3322919d65c67a8b035fa84841aaf79",
                    18_479,
                    "603e0ba78e3055609b7f3469c769f88d8eba3fbe837f956d52ef3b19e3bd7e7d",
                ),
            ],
        )
        self.assertEqual(
            [
                (
                    policy.path,
                    policy.content_sha256,
                    policy.mode,
                    policy.object_id,
                    policy.file_size,
                    policy.file_sha256,
                )
                for policy in evaluation.review_policy
            ],
            [
                (
                    "home/private_dot_local/lib/agent-equipment/agent_equipment/secrets.py",
                    "sha256:d0f16da2ee64172cc277d1156e2ec19028c828c8f3bcd9a0c240c8ea8dcdf358",
                    "100644",
                    "05d838b88cf32f56feda5b803a97c5a8b68516d0",
                    155_106,
                    "d0f16da2ee64172cc277d1156e2ec19028c828c8f3bcd9a0c240c8ea8dcdf358",
                ),
                (
                    "scripts/agent_equipment_public_data.py",
                    "sha256:8b896e011ebf82a61ed457a07a3a13bd6b4b80d98537de99ed13f4363591ce4d",
                    "100644",
                    "840b7aa365be48307699a273250eeb044e3ade63",
                    648,
                    "8b896e011ebf82a61ed457a07a3a13bd6b4b80d98537de99ed13f4363591ce4d",
                ),
                (
                    "scripts/privacy-scan",
                    "sha256:a6c4ff4e7bb41c1a1aef5fadd92ba39a5733d4ec62f2025f591ae3cf25365b91",
                    "100755",
                    "685da1a66cc6b427af4a4d99bb97ac02d02d4e6b",
                    29_799,
                    "a6c4ff4e7bb41c1a1aef5fadd92ba39a5733d4ec62f2025f591ae3cf25365b91",
                ),
                (
                    "scripts/privacy_scan_review.py",
                    "sha256:7a04892d1f01dc51d71a616864fa198e421588f14b1f19e120ba3685cc5aa9e5",
                    "100644",
                    "c60312be9feeecaf8698b09f93481fb2ba8919b4",
                    16_983,
                    "7a04892d1f01dc51d71a616864fa198e421588f14b1f19e120ba3685cc5aa9e5",
                ),
            ],
        )

    def test_finding_validation_rejects_missing_and_additional_findings(self) -> None:
        original = json.loads(frozen_target_bytes(REVIEW_RECORD_PATH))
        self.assertIsInstance(original, dict)
        entries = original["entries"]
        self.assertIsInstance(entries, list)
        cases: list[tuple[str, dict[str, object]]] = []

        one_removed = json.loads(json.dumps(original))
        one_removed["entries"] = one_removed["entries"][1:]
        cases.append(("one-removed", one_removed))

        all_removed = json.loads(json.dumps(original))
        all_removed["entries"] = []
        cases.append(("all-removed", all_removed))

        sixth = json.loads(json.dumps(original))
        additional = json.loads(json.dumps(entries[0]))
        additional["line"] = 1
        sixth["entries"].append(additional)
        cases.append(("sixth", sixth))

        duplicate = json.loads(json.dumps(original))
        duplicate["entries"].append(json.loads(json.dumps(entries[0])))
        cases.append(("duplicate", duplicate))

        for name, record in cases:
            with self.subTest(name=name):
                self.assert_finding_mutation_rejected(
                    {REVIEW_RECORD_PATH: ("100644", compact_json(record))}
                )

    def test_finding_validation_rejects_changed_or_malformed_records(self) -> None:
        original_bytes = frozen_target_bytes(REVIEW_RECORD_PATH)
        original = json.loads(original_bytes)
        self.assertIsInstance(original, dict)

        changed = json.loads(json.dumps(original))
        changed["entries"][0]["rule"] = "changed-rule"

        malformed_entry = json.loads(json.dumps(original))
        del malformed_entry["entries"][0]["category"]

        duplicate_policy_key = original_bytes.replace(
            b'"version":',
            b'"version":"duplicate","version":',
            1,
        )
        duplicate_record_key = original_bytes.replace(
            b'{"entries":',
            b'{"entries":[],"entries":',
            1,
        )
        duplicate_entry_key = original_bytes.replace(
            b'{"category":',
            b'{"category":"duplicate","category":',
            1,
        )
        deeply_nested = (
            b'{"entries":'
            + (b"[" * 200_000)
            + b"0"
            + (b"]" * 200_000)
            + b"}"
        )
        self.assertLess(len(deeply_nested), 512 * 1024)
        with self.assertRaises(RecursionError):
            json.loads(deeply_nested)

        cases = (
            ("changed", compact_json(changed)),
            ("malformed-entry", compact_json(malformed_entry)),
            ("malformed-json", b"{"),
            ("duplicate-policy-key", duplicate_policy_key),
            ("duplicate-record-key", duplicate_record_key),
            ("duplicate-entry-key", duplicate_entry_key),
            ("deeply-nested", deeply_nested),
        )
        for name, contents in cases:
            with self.subTest(name=name):
                self.assert_finding_mutation_rejected(
                    {REVIEW_RECORD_PATH: ("100644", contents)}
                )

    def test_finding_validation_rejects_referenced_file_identity_mismatches(self) -> None:
        test_path = "tests/test_privacy_age_admission_app.py"
        test_contents = frozen_target_bytes(test_path)
        original = json.loads(frozen_target_bytes(REVIEW_RECORD_PATH))
        self.assertIsInstance(original, dict)

        wrong_blob = json.loads(json.dumps(original))
        wrong_blob["entries"][3]["git_blob_sha1"] = "0" * 40
        wrong_mode = json.loads(json.dumps(original))
        wrong_mode["entries"][3]["mode"] = "100755"
        wrong_content = json.loads(json.dumps(original))
        wrong_content["entries"][3]["content_sha256"] = "sha256:" + "0" * 64

        cases = (
            ("file-missing", {test_path: None}),
            ("file-bytes", {test_path: ("100644", b"altered finding input\n")}),
            ("file-mode", {test_path: ("100755", test_contents)}),
            (
                "record-blob",
                {REVIEW_RECORD_PATH: ("100644", compact_json(wrong_blob))},
            ),
            (
                "record-mode",
                {REVIEW_RECORD_PATH: ("100644", compact_json(wrong_mode))},
            ),
            (
                "record-content",
                {REVIEW_RECORD_PATH: ("100644", compact_json(wrong_content))},
            ),
        )
        for name, replacements in cases:
            with self.subTest(name=name):
                self.assert_finding_mutation_rejected(replacements)

    def test_finding_validation_binds_every_review_policy_file(self) -> None:
        policy_path = "scripts/privacy_scan_review.py"
        policy_contents = frozen_target_bytes(policy_path)
        record = json.loads(frozen_target_bytes(REVIEW_RECORD_PATH))
        self.assertIsInstance(record, dict)
        changed_record = json.loads(json.dumps(record))
        changed_record["policy"]["files"][policy_path] = "sha256:" + ("0" * 64)

        cases = (
            ("policy-missing", {policy_path: None}),
            ("policy-bytes", {policy_path: ("100644", b"changed policy\n")}),
            ("policy-mode", {policy_path: ("100755", policy_contents)}),
            (
                "record-policy-digest",
                {REVIEW_RECORD_PATH: ("100644", compact_json(changed_record))},
            ),
        )
        for name, replacements in cases:
            with self.subTest(name=name):
                self.assert_finding_mutation_rejected(
                    replacements,
                    pattern=(
                        "structural Git entry|protected Git delta|"
                        "protected transition entry|"
                        "review record|review policy|finding validation"
                    ),
                )

    def test_finding_validation_treats_candidate_code_only_as_frozen_data(self) -> None:
        real_import = builtins.__import__
        real_run = subprocess.run
        observed_commands: list[tuple[str, ...]] = []

        def guarded_import(
            name: str,
            globals: object = None,
            locals: object = None,
            fromlist: object = (),
            level: int = 0,
        ) -> object:
            if "privacy_scan_review" in name or "privacy-scan" in name:
                raise AssertionError("candidate review code was imported")
            return real_import(name, globals, locals, fromlist, level)

        def guarded_run(command: tuple[str, ...], *args: object, **kwargs: object):
            observed_commands.append(tuple(command))
            self.assertEqual(command[0], "git")
            return real_run(command, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=guarded_import):
            with patch.object(
                transition_module.subprocess,
                "run",
                side_effect=guarded_run,
            ):
                evaluation = evaluate_transition(
                    TRANSITION_MANIFEST,
                    repository_root=ROOT,
                )

        self.assertEqual(len(evaluation.findings), 5)
        self.assertTrue(observed_commands)

    def test_finding_validation_accepts_inclusive_record_and_input_size_bounds(self) -> None:
        record_bytes = frozen_target_bytes(REVIEW_RECORD_PATH)
        exact_record = record_bytes + (b" " * ((512 * 1024) - len(record_bytes)))
        self.assertEqual(len(exact_record), 512 * 1024)
        cases = (
            (
                "record",
                {REVIEW_RECORD_PATH: ("100644", exact_record)},
                "review record bytes",
            ),
            (
                "finding",
                {
                    "tests/test_privacy_age_admission_app.py": (
                        "100644",
                        b"x" * (4 * 1024 * 1024),
                    )
                },
                "reviewed finding file",
            ),
            (
                "policy",
                {
                    "scripts/privacy_scan_review.py": (
                        "100644",
                        b"x" * (4 * 1024 * 1024),
                    )
                },
                "review policy file",
            ),
        )
        for name, replacements, expected_error in cases:
            with self.subTest(name=name):
                self.assert_finding_mutation_rejected(
                    replacements,
                    pattern=expected_error,
                )

    def test_finding_validation_rejects_oversized_record_and_inputs(self) -> None:
        cases = (
            (
                "record",
                {
                    REVIEW_RECORD_PATH: (
                        "100644",
                        b" " * ((512 * 1024) + 1),
                    )
                },
            ),
            (
                "input",
                {
                    "tests/test_privacy_age_admission_app.py": (
                        "100644",
                        b"x" * ((4 * 1024 * 1024) + 1),
                    )
                },
            ),
            (
                "policy",
                {
                    "scripts/privacy_scan_review.py": (
                        "100644",
                        b"x" * ((4 * 1024 * 1024) + 1),
                    )
                },
            ),
        )
        for name, replacements in cases:
            with self.subTest(name=name):
                self.assert_finding_mutation_rejected(
                    replacements,
                    pattern="finding validation resource limit exceeded",
                )

    def test_finding_validation_timeout_fails_before_later_adapter(self) -> None:
        receipt_adapter = Mock(
            side_effect=AssertionError("later adapter ran before findings passed")
        )
        clock = Mock(side_effect=([0.0] * 8) + [31.0])

        with self.assertRaisesRegex(
            TransitionEvaluationError,
            "finding validation timed out",
        ):
            evaluate_transition(
                TRANSITION_MANIFEST,
                repository_root=ROOT,
                after_structure=receipt_adapter,
                finding_clock=clock,
            )
        receipt_adapter.assert_not_called()
        self.assertGreater(clock.call_count, 3)

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
