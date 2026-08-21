from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
PREPARER = SKILL_DIR / "scripts" / "prepare_behavior_evals.py"
REPO_ROOT = SKILL_DIR.parents[3]
EVALS_ROOT = REPO_ROOT / "home" / "dot_agents" / "skills"


def shipped_eval_paths() -> list[Path]:
    return sorted(EVALS_ROOT.glob("*/evals/evals.json"))


class PrepareBehaviorEvalsTests(unittest.TestCase):
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
                        with_skill_prompt = (
                            eval_dirs[0] / "with_skill" / "run-1" / "subagent_prompt.md"
                        ).read_text(encoding="utf-8")
                        without_skill_prompt = (
                            eval_dirs[0] / "without_skill" / "run-1" / "subagent_prompt.md"
                        ).read_text(encoding="utf-8")
                        metadata = json.loads(
                            (eval_dirs[0] / "eval_metadata.json").read_text(encoding="utf-8")
                        )
                        execution_parts = [evaluation["prompt"]]
                        execution_parts.extend(
                            (skill_dir / fixture_path).read_text(encoding="utf-8")
                            for fixture_path in evaluation["fixture_paths"]
                        )
                        self.assertEqual(without_skill_prompt, "\n\n".join(execution_parts))
                        execution_parts.append((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
                        self.assertEqual(with_skill_prompt, "\n\n".join(execution_parts))
                        self.assertEqual(metadata["assertions"], evaluation["expectations"])

                    instructions = (workspace / "RUN_INSTRUCTIONS.md").read_text(encoding="utf-8")
                    self.assertIn(
                        "Capture each subagent's final response and write it to that run's `outputs/response.md`.",
                        instructions,
                    )
                    self.assertIn("Allow no tool use for either subagent.", instructions)
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
                    for prompt_path in workspace.glob("eval-*/**/subagent_prompt.md"):
                        self.assertNotIn(
                            "outside-content-sentinel", prompt_path.read_text(encoding="utf-8")
                        )


if __name__ == "__main__":
    unittest.main()
