from __future__ import annotations

import json
import os
import runpy
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
PREPARER = SKILL_DIR / "scripts" / "prepare_behavior_evals.py"
REPO_ROOT = SKILL_DIR.parents[3]
EVALS_ROOT = REPO_ROOT / "home" / "dot_agents" / "skills"


def shipped_eval_paths() -> list[Path]:
    return sorted(EVALS_ROOT.glob("*/evals/evals.json"))


class PrepareBehaviorEvalsTests(unittest.TestCase):
    def test_reports_a_missing_skill_directory_as_a_cli_error(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            skill_dir = root / "missing-skill"
            workspace = root / "workspace"

            result = subprocess.run(
                [
                    sys.executable,
                    str(PREPARER),
                    "--skill-dir",
                    str(skill_dir),
                    "--workspace",
                    str(workspace),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout or result.stderr)
            self.assertIn("No such file or directory", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(workspace.exists())

    def test_rejects_a_fifo_fixture_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            skill_dir = root / "skill"
            fixtures_dir = skill_dir / "evals" / "fixtures"
            fixtures_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("candidate skill", encoding="utf-8")
            os.mkfifo(fixtures_dir / "blocked-input")
            (skill_dir / "evals" / "evals.json").write_text(
                json.dumps(
                    {
                        "skill_name": "fifo-fixture",
                        "evals": [
                            {
                                "id": 1,
                                "name": "reject fifo",
                                "prompt": "Run the isolated evaluation.",
                                "fixture_paths": ["evals/fixtures/blocked-input"],
                                "expected_output": "No prompt is generated.",
                                "expectations": [
                                    {
                                        "id": "regular-source",
                                        "text": "Rejects a nonregular prompt source.",
                                        "severity": "safety",
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            workspace = root / "workspace"

            result = subprocess.run(
                [
                    sys.executable,
                    str(PREPARER),
                    "--skill-dir",
                    str(skill_dir),
                    "--workspace",
                    str(workspace),
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout or result.stderr)
            self.assertIn("source path must be a regular file", result.stderr)
            self.assertFalse(workspace.exists())

    def test_rejects_a_dangling_workspace_symlink(self) -> None:
        skill_dir = shipped_eval_paths()[0].parents[1]

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            target = root / "outside-created"
            workspace = root / "workspace-link"
            workspace.symlink_to(target, target_is_directory=True)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PREPARER),
                    "--skill-dir",
                    str(skill_dir),
                    "--workspace",
                    str(workspace),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout or result.stderr)
            self.assertTrue(workspace.is_symlink())
            self.assertFalse(target.exists())

    def test_rejects_a_workspace_beneath_a_symlinked_parent(self) -> None:
        skill_dir = shipped_eval_paths()[0].parents[1]

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir).resolve()
            outside = root / "outside"
            outside.mkdir()
            workspace_parent = root / "workspace-parent"
            workspace_parent.symlink_to(outside, target_is_directory=True)
            workspace = workspace_parent / "workspace"

            result = subprocess.run(
                [
                    sys.executable,
                    str(PREPARER),
                    "--skill-dir",
                    str(skill_dir),
                    "--workspace",
                    str(workspace),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout or result.stderr)
            self.assertIn("workspace path must not contain symlinks", result.stderr)
            self.assertFalse((outside / "workspace").exists())

    def test_rejects_parent_traversal_in_the_workspace_path(self) -> None:
        skill_dir = shipped_eval_paths()[0].parents[1]

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir).resolve()
            (root / "requested").mkdir()
            workspace = root / "requested" / ".." / "outside" / "workspace"

            result = subprocess.run(
                [
                    sys.executable,
                    str(PREPARER),
                    "--skill-dir",
                    str(skill_dir),
                    "--workspace",
                    str(workspace),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout or result.stderr)
            self.assertIn("workspace path must not contain parent traversal", result.stderr)
            self.assertFalse((root / "outside" / "workspace").exists())

    def test_rejects_a_workspace_parent_writable_by_other_principals(self) -> None:
        skill_dir = shipped_eval_paths()[0].parents[1]

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir).resolve()
            shared_parent = root / "shared-parent"
            shared_parent.mkdir()
            shared_parent.chmod(0o777)
            workspace = shared_parent / "workspace"

            result = subprocess.run(
                [
                    sys.executable,
                    str(PREPARER),
                    "--skill-dir",
                    str(skill_dir),
                    "--workspace",
                    str(workspace),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout or result.stderr)
            self.assertIn("workspace parent must not be writable", result.stderr)
            self.assertFalse(workspace.exists())

    def test_rejects_a_sticky_parent_owned_by_an_untrusted_principal(self) -> None:
        preparer = runpy.run_path(str(PREPARER))
        preparer_globals = preparer["validate_parent_mutation_boundary"].__globals__
        untrusted_parent = mock.Mock(
            st_mode=stat.S_IFDIR | 0o1777,
            st_uid=os.geteuid() + 1,
        )

        with mock.patch.object(
            preparer_globals["os"],
            "fstat",
            return_value=untrusted_parent,
        ):
            with self.assertRaisesRegex(ValueError, "trusted principal"):
                preparer["validate_parent_mutation_boundary"](123)

    def test_workspace_population_keeps_descriptor_authority(self) -> None:
        preparer = runpy.run_path(str(PREPARER))
        eval_item = {
            "id": 1,
            "name": "stable workspace",
            "prompt": "Run the isolated evaluation.",
            "fixture_paths": [],
            "expected_output": "A safe result.",
            "expectations": [],
        }
        prompts = {"with_skill": "with skill", "without_skill": "without skill"}

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir).resolve()
            workspace_parent = root / "workspace-parent"
            workspace_parent.mkdir()
            workspace = workspace_parent / "workspace"
            created_workspace, workspace_fd = preparer["create_workspace"](workspace)

            moved_parent = root / "moved-parent"
            workspace_parent.rename(moved_parent)
            outside = root / "outside"
            outside.mkdir()
            workspace_parent.symlink_to(outside, target_is_directory=True)

            try:
                preparer["write_eval"](workspace_fd, eval_item, 1, prompts)
                with self.assertRaisesRegex(ValueError, "no longer identifies"):
                    preparer["write_run_instructions"](
                        workspace_fd,
                        created_workspace,
                        "stable-workspace",
                        1,
                    )
            finally:
                os.close(workspace_fd)

            self.assertFalse((outside / "workspace").exists())
            moved_workspace = moved_parent / "workspace"
            self.assertFalse((moved_workspace / "RUN_INSTRUCTIONS.md").exists())
            self.assertTrue(list(moved_workspace.glob("eval-*/eval_metadata.json")))

    def test_created_directory_descriptor_ignores_a_published_replacement(self) -> None:
        preparer = runpy.run_path(str(PREPARER))

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir).resolve()
            parent_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            preparer_globals = preparer["create_directory"].__globals__
            real_publish = preparer_globals["publish_directory"]
            real_mkdir = os.mkdir
            real_rename = os.rename

            def replace_after_publish(
                directory_fd: int,
                private_name: str,
                public_name: str,
            ) -> None:
                real_publish(directory_fd, private_name, public_name)
                real_rename(
                    public_name,
                    "created-workspace",
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
                real_mkdir(public_name, dir_fd=directory_fd)

            try:
                with mock.patch.dict(
                    preparer_globals,
                    {"publish_directory": replace_after_publish},
                ):
                    workspace_fd = preparer["create_directory"](parent_fd, "workspace")
                try:
                    preparer["write_text"](workspace_fd, "marker", "bound\n")
                finally:
                    os.close(workspace_fd)
            finally:
                os.close(parent_fd)

            self.assertTrue((root / "created-workspace" / "marker").is_file())
            self.assertFalse((root / "workspace" / "marker").exists())

    def test_directory_publication_does_not_replace_an_existing_entry(self) -> None:
        preparer = runpy.run_path(str(PREPARER))

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir).resolve()
            workspace = root / "workspace"
            workspace.mkdir()
            marker = workspace / "marker"
            marker.write_text("preserve\n", encoding="utf-8")
            parent_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with self.assertRaises(FileExistsError):
                    preparer["create_directory"](parent_fd, "workspace")
            finally:
                os.close(parent_fd)

            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve\n")
            self.assertFalse(list(root.glob(".prepare-behavior-evals-*")))

    def test_rejects_invalid_generated_names_before_creating_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            skill_dir = root / "skill"
            evals_dir = skill_dir / "evals"
            evals_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("candidate skill", encoding="utf-8")
            (evals_dir / "evals.json").write_text(
                json.dumps(
                    {
                        "skill_name": "invalid-name",
                        "evals": [
                            {
                                "id": "bad/../../escape",
                                "name": "invalid name",
                                "prompt": "Run the isolated evaluation.",
                                "fixture_paths": [],
                                "expectations": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            workspace = root / "workspace"

            result = subprocess.run(
                [
                    sys.executable,
                    str(PREPARER),
                    "--skill-dir",
                    str(skill_dir),
                    "--workspace",
                    str(workspace),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout or result.stderr)
            self.assertIn("generated workspace name", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(workspace.exists())

    def test_rejects_duplicate_generated_names_before_creating_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            skill_dir = root / "skill"
            evals_dir = skill_dir / "evals"
            evals_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("candidate skill", encoding="utf-8")
            duplicate_eval = {
                "id": 1,
                "name": "duplicate",
                "prompt": "Run the isolated evaluation.",
                "fixture_paths": [],
                "expectations": [],
            }
            (evals_dir / "evals.json").write_text(
                json.dumps(
                    {
                        "skill_name": "duplicate-name",
                        "evals": [duplicate_eval, duplicate_eval],
                    }
                ),
                encoding="utf-8",
            )
            workspace = root / "workspace"

            result = subprocess.run(
                [
                    sys.executable,
                    str(PREPARER),
                    "--skill-dir",
                    str(skill_dir),
                    "--workspace",
                    str(workspace),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout or result.stderr)
            self.assertIn("unique workspace directories", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(workspace.exists())

    def test_rejects_reusing_an_existing_workspace(self) -> None:
        skill_dir = shipped_eval_paths()[0].parents[1]

        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir) / "workspace"
            first = subprocess.run(
                [
                    sys.executable,
                    str(PREPARER),
                    "--skill-dir",
                    str(skill_dir),
                    "--workspace",
                    str(workspace),
                    "--runs",
                    "3",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(first.returncode, 0, first.stdout or first.stderr)
            original_instructions = (workspace / "RUN_INSTRUCTIONS.md").read_text(encoding="utf-8")

            second = subprocess.run(
                [
                    sys.executable,
                    str(PREPARER),
                    "--skill-dir",
                    str(skill_dir),
                    "--workspace",
                    str(workspace),
                    "--runs",
                    "1",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(second.returncode, 0, second.stdout or second.stderr)
            self.assertEqual(
                (workspace / "RUN_INSTRUCTIONS.md").read_text(encoding="utf-8"),
                original_instructions,
            )
            self.assertTrue(list(workspace.glob("eval-*/with_skill/run-3")))

    def test_rejects_nonpositive_run_counts_before_creating_workspace(self) -> None:
        skill_dir = shipped_eval_paths()[0].parents[1]

        with tempfile.TemporaryDirectory() as tempdir:
            for runs in (0, -1):
                with self.subTest(runs=runs):
                    workspace = Path(tempdir) / f"workspace-{runs}"
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(PREPARER),
                            "--skill-dir",
                            str(skill_dir),
                            "--workspace",
                            str(workspace),
                            "--runs",
                            str(runs),
                        ],
                        text=True,
                        capture_output=True,
                        check=False,
                    )

                    self.assertNotEqual(result.returncode, 0, result.stdout or result.stderr)
                    self.assertFalse(workspace.exists())

    def test_every_shipped_eval_file_scaffolds_isolated_execution_prompts(self) -> None:
        eval_paths = shipped_eval_paths()
        self.assertTrue(eval_paths, "repository must ship at least one behavior eval file")

        with tempfile.TemporaryDirectory() as tempdir:
            for eval_path in eval_paths:
                skill_dir = eval_path.parents[1]
                workspace = Path(tempdir) / skill_dir.name
                with self.subTest(eval_path=eval_path.relative_to(REPO_ROOT)):
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(PREPARER),
                            "--skill-dir",
                            str(skill_dir),
                            "--workspace",
                            str(workspace),
                            "--runs",
                            "3",
                        ],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout or result.stderr)
                    document = json.loads(eval_path.read_text(encoding="utf-8"))
                    for evaluation in document["evals"]:
                        eval_dirs = list(workspace.glob(f"eval-{evaluation['id']}-*"))
                        self.assertEqual(len(eval_dirs), 1, eval_dirs)
                        metadata = json.loads(
                            (eval_dirs[0] / "eval_metadata.json").read_text(encoding="utf-8")
                        )
                        execution_parts = [evaluation["prompt"]]
                        execution_parts.extend(
                            (skill_dir / fixture_path).read_text(encoding="utf-8")
                            for fixture_path in evaluation["fixture_paths"]
                        )
                        expected_without_skill = "\n\n".join(execution_parts)
                        execution_parts.append((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
                        expected_with_skill = "\n\n".join(execution_parts)
                        for run_number in range(1, 4):
                            with_skill_prompt = (
                                eval_dirs[0]
                                / "with_skill"
                                / f"run-{run_number}"
                                / "subagent_prompt.md"
                            ).read_text(encoding="utf-8")
                            without_skill_prompt = (
                                eval_dirs[0]
                                / "without_skill"
                                / f"run-{run_number}"
                                / "subagent_prompt.md"
                            ).read_text(encoding="utf-8")
                            self.assertEqual(without_skill_prompt, expected_without_skill)
                            self.assertEqual(with_skill_prompt, expected_with_skill)
                        self.assertEqual(metadata["assertions"], evaluation["expectations"])

                    instructions = (workspace / "RUN_INSTRUCTIONS.md").read_text(encoding="utf-8")
                    self.assertIn(
                        "Capture each subagent's final response and write it to that run's `outputs/response.md`.",
                        instructions,
                    )
                    self.assertIn("Allow no tool use for either subagent.", instructions)
                    self.assertIn("`run-1` through `run-3`", instructions)
                    self.assertNotIn("Ask each subagent to save", instructions)

    def test_rejects_fixture_paths_outside_the_skill_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            outside_file = root / "outside.txt"
            outside_file.write_text("outside-content-sentinel", encoding="utf-8")

            for label, fixture_path in {
                "absolute": str(outside_file),
                "traversal": "../outside.txt",
                "symlink": "evals/fixtures/leak.txt",
            }.items():
                with self.subTest(label=label):
                    skill_dir = root / f"skill-{label}"
                    fixtures_dir = skill_dir / "evals" / "fixtures"
                    fixtures_dir.mkdir(parents=True)
                    (skill_dir / "SKILL.md").write_text("candidate skill", encoding="utf-8")
                    if label == "symlink":
                        (fixtures_dir / "leak.txt").symlink_to(outside_file)
                    evals = {
                        "skill_name": f"skill-{label}",
                        "evals": [
                            {
                                "id": 1,
                                "name": "reject unsafe fixture",
                                "prompt": "Run the isolated evaluation.",
                                "fixture_paths": [fixture_path],
                                "expected_output": "A safe result.",
                                "expectations": [
                                    {
                                        "id": "safe",
                                        "text": "Does not expose secrets.",
                                        "severity": "safety",
                                    }
                                ],
                            }
                        ],
                    }
                    (skill_dir / "evals" / "evals.json").write_text(
                        json.dumps(evals), encoding="utf-8"
                    )
                    workspace = root / f"workspace-{label}"
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(PREPARER),
                            "--skill-dir",
                            str(skill_dir),
                            "--workspace",
                            str(workspace),
                        ],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0, result.stdout or result.stderr)
                    self.assertFalse(workspace.exists())
                    for candidate in root.rglob("*"):
                        if (
                            candidate == outside_file
                            or candidate.is_symlink()
                            or not candidate.is_file()
                        ):
                            continue
                        self.assertNotIn(
                            "outside-content-sentinel",
                            candidate.read_text(encoding="utf-8"),
                            candidate,
                        )

    def test_rejects_symlinked_eval_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            manifest = root / "outside-evals.json"
            manifest.write_text(
                json.dumps(
                    {
                        "skill_name": "outside-manifest",
                        "evals": [
                            {
                                "id": 1,
                                "name": "outside manifest",
                                "prompt": "outside-manifest-sentinel",
                                "fixture_paths": [],
                                "expected_output": "No prompt is generated.",
                                "expectations": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            skill_dir = root / "skill"
            (skill_dir / "evals").mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("candidate skill", encoding="utf-8")
            (skill_dir / "evals" / "evals.json").symlink_to(manifest)
            workspace = root / "workspace"

            result = subprocess.run(
                [
                    sys.executable,
                    str(PREPARER),
                    "--skill-dir",
                    str(skill_dir),
                    "--workspace",
                    str(workspace),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout or result.stderr)
            self.assertFalse(workspace.exists())
            excluded = {manifest, skill_dir / "evals" / "evals.json"}
            for candidate in root.rglob("*"):
                if (
                    candidate in excluded
                    or candidate.is_symlink()
                    or not candidate.is_file()
                ):
                    continue
                self.assertNotIn(
                    "outside-manifest-sentinel",
                    candidate.read_text(encoding="utf-8"),
                    candidate,
                )


if __name__ == "__main__":
    unittest.main()
