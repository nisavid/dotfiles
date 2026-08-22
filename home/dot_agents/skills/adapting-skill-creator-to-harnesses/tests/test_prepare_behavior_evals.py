from __future__ import annotations

import hashlib
import importlib.util
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_behavior_evals.py"
SPEC = importlib.util.spec_from_file_location("prepare_behavior_evals", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
PREPARER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREPARER
SPEC.loader.exec_module(PREPARER)


class PrepareBehaviorEvalsTest(unittest.TestCase):
    def test_execution_prompts_contain_inputs_without_grading_data_or_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = root / "candidate-skill"
            fixture_dir = skill_dir / "evals" / "fixtures"
            workspace = root / "workspace"
            fixture_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("candidate skill body\n")
            (fixture_dir / "case.md").write_text("fixture body\n")
            eval_item = {
                "id": 1,
                "name": "isolated-prompt",
                "prompt": "raw task prompt",
                "files": ["evals/fixtures/case.md"],
                "expected_output": "expected-output sentinel",
                "expectations": [
                    {
                        "id": "private-grader-rule",
                        "text": "grader-expectation sentinel",
                        "severity": "safety",
                    }
                ],
            }
            data = {"skill_name": "candidate-skill", "evals": [eval_item]}

            PREPARER.prepare_execution_workspace(workspace, skill_dir, data, runs=1)

            with_skill = workspace / "eval-1-isolated-prompt" / "with_skill" / "run-1"
            without_skill = workspace / "eval-1-isolated-prompt" / "without_skill" / "run-1"
            with_prompt = (with_skill / "subagent_prompt.md").read_text()
            without_prompt = (without_skill / "subagent_prompt.md").read_text()

            for prompt in (with_prompt, without_prompt):
                self.assertIn("raw task prompt", prompt)
                self.assertIn("fixture body", prompt)
                self.assertNotIn("expected-output sentinel", prompt)
                self.assertNotIn("grader-expectation sentinel", prompt)
                self.assertNotIn(str(skill_dir), prompt)
                self.assertNotIn(str(workspace), prompt)
                self.assertNotIn("case.md", prompt)
            self.assertIn("candidate skill body", with_prompt)
            self.assertNotIn("candidate skill body", without_prompt)
            self.assertEqual(list(workspace.rglob("eval_metadata.json")), [])
            plan_text = (workspace / PREPARER.EXECUTION_PLAN_NAME).read_text()
            self.assertNotIn("expected-output sentinel", plan_text)
            self.assertNotIn("grader-expectation sentinel", plan_text)

            (with_skill / "outputs" / "response.md").write_text("with-skill response\n")
            (without_skill / "outputs" / "response.md").write_text("baseline response\n")
            PREPARER.stage_grader_metadata(workspace, skill_dir, data, runs=1)
            metadata = json.loads((with_skill / "eval_metadata.json").read_text())
            self.assertEqual(metadata["expected_output"], "expected-output sentinel")
            self.assertEqual(metadata["assertions"], eval_item["expectations"])

    def test_legacy_fixture_paths_are_embedded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            skill_dir = Path(temporary_directory) / "candidate-skill"
            fixture_dir = skill_dir / "evals" / "fixtures"
            fixture_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("candidate skill body\n")
            (fixture_dir / "legacy.md").write_text("legacy fixture body\n")

            prompt = PREPARER.prompt_text(
                skill_dir=skill_dir,
                eval_item={
                    "prompt": "legacy task",
                    "fixture_paths": ["evals/fixtures/legacy.md"],
                },
                run_kind="without_skill",
            )

            self.assertIn("legacy fixture body", prompt)
            self.assertNotIn("legacy.md", prompt)

    def test_disagreeing_input_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            skill_dir = Path(temporary_directory) / "candidate-skill"
            skill_dir.mkdir()

            with self.assertRaisesRegex(ValueError, "files and fixture_paths disagree"):
                PREPARER.fixture_text(
                    skill_dir=skill_dir,
                    eval_item={
                        "files": ["evals/fixtures/canonical.md"],
                        "fixture_paths": ["evals/fixtures/legacy.md"],
                    },
                )

    def test_prompt_only_eval_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            skill_dir = Path(temporary_directory) / "candidate-skill"
            skill_dir.mkdir()

            prompt = PREPARER.prompt_text(
                skill_dir=skill_dir,
                eval_item={"prompt": "prompt-only task"},
                run_kind="without_skill",
            )

            self.assertIn("prompt-only task", prompt)
            self.assertNotIn("Fixture:", prompt)

    def test_tool_policy_comes_only_from_the_eval_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            skill_dir = Path(temporary_directory) / "candidate-skill"
            skill_dir.mkdir()

            prompt = PREPARER.prompt_text(
                skill_dir=skill_dir,
                eval_item={"prompt": "Use the authorized local inspection tool."},
                run_kind="without_skill",
            )

            self.assertIn("Use the authorized local inspection tool.", prompt)
            self.assertNotIn("without using tools", prompt)
            self.assertNotIn("instead of running it", prompt)
            self.assertNotIn("task and fixture only", prompt)

    def test_grader_metadata_requires_every_response(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = root / "candidate-skill"
            workspace = root / "workspace"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("candidate skill body\n")
            eval_item = {"id": 1, "name": "response-gate", "prompt": "raw task"}
            data = {"skill_name": "candidate-skill", "evals": [eval_item]}
            PREPARER.prepare_execution_workspace(workspace, skill_dir, data, runs=2)
            first_response = workspace / "eval-1-response-gate" / "with_skill" / "run-1" / "outputs"
            (first_response / "response.md").write_text("one response\n")

            with self.assertRaisesRegex(ValueError, "all responses must exist"):
                PREPARER.stage_grader_metadata(workspace, skill_dir, data, runs=2)

            self.assertEqual(list(workspace.rglob("eval_metadata.json")), [])

    def test_grader_metadata_preflight_is_atomic_across_evals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = root / "candidate-skill"
            workspace = root / "workspace"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("candidate skill body\n")
            eval_items = [
                {"id": 1, "name": "complete", "prompt": "first task"},
                {"id": 2, "name": "incomplete", "prompt": "second task"},
            ]
            data = {"skill_name": "candidate-skill", "evals": eval_items}
            PREPARER.prepare_execution_workspace(workspace, skill_dir, data, runs=1)
            complete_eval = workspace / "eval-1-complete"
            for run_kind in ("with_skill", "without_skill"):
                response = complete_eval / run_kind / "run-1" / "outputs" / "response.md"
                response.write_text("complete response\n")

            with self.assertRaisesRegex(ValueError, "all responses must exist"):
                PREPARER.stage_grader_metadata(workspace, skill_dir, data, runs=1)

            self.assertEqual(list(workspace.rglob("eval_metadata.json")), [])

    def test_execution_workspace_cannot_be_reprepared(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = root / "candidate-skill"
            workspace = root / "workspace"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("candidate skill body\n")
            eval_item = {"id": 1, "name": "fresh-only", "prompt": "raw task"}
            data = {"skill_name": "candidate-skill", "evals": [eval_item]}
            PREPARER.prepare_execution_workspace(workspace, skill_dir, data, runs=1)

            with self.assertRaisesRegex(ValueError, "new or empty"):
                PREPARER.prepare_execution_workspace(workspace, skill_dir, data, runs=1)

    def test_existing_empty_execution_workspace_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = root / "candidate-skill"
            workspace = root / "workspace"
            skill_dir.mkdir()
            workspace.mkdir()
            (skill_dir / "SKILL.md").write_text("candidate skill body\n")
            data = {
                "skill_name": "candidate-skill",
                "evals": [{"id": 1, "name": "empty", "prompt": "raw task"}],
            }

            PREPARER.prepare_execution_workspace(workspace, skill_dir, data, runs=1)

            self.assertTrue((workspace / PREPARER.EXECUTION_PLAN_NAME).is_file())

    def test_candidate_skill_entrypoint_must_not_be_a_symbolic_link(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = root / "candidate-skill"
            workspace = root / "workspace"
            skill_dir.mkdir()
            outside = root / "outside.md"
            outside.write_text("private outside content\n")
            (skill_dir / "SKILL.md").symlink_to(outside)
            data = {
                "skill_name": "candidate-skill",
                "evals": [{"id": 1, "name": "symlink-skill", "prompt": "raw task"}],
            }

            with self.assertRaisesRegex(ValueError, "must not be a symbolic link"):
                PREPARER.prepare_execution_workspace(workspace, skill_dir, data, runs=1)

            self.assertFalse(workspace.exists())

    def test_published_prompts_match_one_plan_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = root / "candidate-skill"
            fixture_dir = skill_dir / "evals" / "fixtures"
            workspace = root / "workspace"
            fixture_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("candidate skill body\n")
            (fixture_dir / "case.md").write_text("fixture body\n")
            data = {
                "skill_name": "candidate-skill",
                "evals": [
                    {
                        "id": 1,
                        "name": "snapshot",
                        "prompt": "raw task",
                        "files": ["evals/fixtures/case.md"],
                    }
                ],
            }

            PREPARER.prepare_execution_workspace(workspace, skill_dir, data, runs=3)

            plan = json.loads((workspace / PREPARER.EXECUTION_PLAN_NAME).read_text())
            prompt_bytes_by_kind: dict[str, list[bytes]] = {
                "with_skill": [],
                "without_skill": [],
            }
            for prompt_record in plan["prompts"]:
                prompt_path = workspace / prompt_record["prompt"]
                prompt_bytes = prompt_path.read_bytes()
                self.assertEqual(
                    hashlib.sha256(prompt_bytes).hexdigest(),
                    prompt_record["sha256"],
                )
                run_kind = prompt_path.parts[-3]
                prompt_bytes_by_kind[run_kind].append(prompt_bytes)
            for prompt_bytes in prompt_bytes_by_kind.values():
                self.assertEqual(len(set(prompt_bytes)), 1)

    def test_execution_workspace_rejects_symbolic_link(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = root / "candidate-skill"
            target = root / "target"
            workspace = root / "workspace"
            skill_dir.mkdir()
            target.mkdir()
            workspace.symlink_to(target, target_is_directory=True)
            (skill_dir / "SKILL.md").write_text("candidate skill body\n")
            data = {
                "skill_name": "candidate-skill",
                "evals": [{"id": 1, "name": "symlink", "prompt": "raw task"}],
            }

            with self.assertRaisesRegex(ValueError, "must not be a symbolic link"):
                PREPARER.prepare_execution_workspace(workspace, skill_dir, data, runs=1)

            self.assertEqual(list(target.iterdir()), [])

    def test_execution_workspace_preparation_is_atomic_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = root / "candidate-skill"
            workspace = root / "workspace"
            skill_dir.mkdir()
            workspace.mkdir()
            (skill_dir / "SKILL.md").write_text("candidate skill body\n")
            data = {
                "skill_name": "candidate-skill",
                "evals": [{"id": 1, "name": "atomic", "prompt": "raw task"}],
            }

            with mock.patch.object(
                PREPARER,
                "write_run_instructions",
                side_effect=OSError("injected failure"),
            ):
                with self.assertRaisesRegex(OSError, "injected failure"):
                    PREPARER.prepare_execution_workspace(workspace, skill_dir, data, runs=1)

            self.assertTrue(workspace.is_dir())
            self.assertEqual(list(workspace.iterdir()), [])
            self.assertEqual(list(root.glob(".workspace.prepare-*")), [])

    def test_grader_stage_must_match_prepared_run_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = root / "candidate-skill"
            workspace = root / "workspace"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("candidate skill body\n")
            eval_item = {"id": 1, "name": "run-count", "prompt": "raw task"}
            data = {"skill_name": "candidate-skill", "evals": [eval_item]}
            PREPARER.prepare_execution_workspace(workspace, skill_dir, data, runs=2)

            with self.assertRaisesRegex(ValueError, "execution plan does not match"):
                PREPARER.stage_grader_metadata(workspace, skill_dir, data, runs=1)

            self.assertEqual(list(workspace.rglob("eval_metadata.json")), [])

    def test_grader_stage_rejects_slug_equivalent_eval_rename(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = root / "candidate-skill"
            workspace = root / "workspace"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("candidate skill body\n")
            eval_item = {"id": 1, "name": "Alpha Beta", "prompt": "raw task"}
            data = {"skill_name": "candidate-skill", "evals": [eval_item]}
            PREPARER.prepare_execution_workspace(workspace, skill_dir, data, runs=1)
            eval_dir = workspace / "eval-1-alpha-beta"
            for run_kind in ("with_skill", "without_skill"):
                response = eval_dir / run_kind / "run-1" / "outputs" / "response.md"
                response.write_text("response\n")
            renamed_data = {
                "skill_name": "candidate-skill",
                "evals": [{"id": 1, "name": "alpha-beta", "prompt": "raw task"}],
            }

            with self.assertRaisesRegex(ValueError, "execution plan does not match"):
                PREPARER.stage_grader_metadata(
                    workspace,
                    skill_dir,
                    renamed_data,
                    runs=1,
                )

            self.assertEqual(list(workspace.rglob("eval_metadata.json")), [])

    def test_grader_stage_rejects_prompt_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = root / "candidate-skill"
            workspace = root / "workspace"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("candidate skill body\n")
            eval_item = {"id": 1, "name": "prompt-hash", "prompt": "raw task"}
            data = {"skill_name": "candidate-skill", "evals": [eval_item]}
            PREPARER.prepare_execution_workspace(workspace, skill_dir, data, runs=1)
            eval_dir = workspace / "eval-1-prompt-hash"
            for run_kind in ("with_skill", "without_skill"):
                response = eval_dir / run_kind / "run-1" / "outputs" / "response.md"
                response.write_text("response\n")
            prompt_path = eval_dir / "with_skill" / "run-1" / "subagent_prompt.md"
            prompt_path.write_text(prompt_path.read_text() + "tampered\n")

            with self.assertRaisesRegex(ValueError, "prompt does not match"):
                PREPARER.stage_grader_metadata(workspace, skill_dir, data, runs=1)

            self.assertEqual(list(workspace.rglob("eval_metadata.json")), [])

    def test_grader_stage_rejects_changed_grading_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = root / "candidate-skill"
            workspace = root / "workspace"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("candidate skill body\n")
            eval_item = {
                "id": 1,
                "name": "contract",
                "prompt": "raw task",
                "expected_output": "original expected output",
                "expectations": [{"text": "original assertion"}],
            }
            data = {"skill_name": "candidate-skill", "evals": [eval_item]}
            PREPARER.prepare_execution_workspace(workspace, skill_dir, data, runs=1)
            eval_dir = workspace / "eval-1-contract"
            for run_kind in ("with_skill", "without_skill"):
                response = eval_dir / run_kind / "run-1" / "outputs" / "response.md"
                response.write_text("response\n")
            changed_data = {
                "skill_name": "candidate-skill",
                "evals": [
                    {
                        **eval_item,
                        "expected_output": "changed after execution",
                        "expectations": [{"text": "changed assertion"}],
                    }
                ],
            }

            with self.assertRaisesRegex(ValueError, "execution plan does not match"):
                PREPARER.stage_grader_metadata(workspace, skill_dir, changed_data, runs=1)

            self.assertEqual(list(workspace.rglob("eval_metadata.json")), [])

    def test_eval_id_must_be_a_nonnegative_integer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"

            with self.assertRaisesRegex(ValueError, "nonnegative integer"):
                PREPARER.EvalSpec.from_mapping({"id": "../../outside", "prompt": "raw task"})

    def test_eval_name_must_not_be_a_falsy_non_string(self) -> None:
        for invalid_name in (False, 0, []):
            with self.subTest(invalid_name=invalid_name):
                with self.assertRaisesRegex(ValueError, "nonempty string"):
                    PREPARER.EvalSpec.from_mapping(
                        {"id": 1, "name": invalid_name, "prompt": "raw task"}
                    )

    def test_run_instructions_cover_every_run_and_use_python3(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workspace = root / "workspace with spaces"
            skill_dir = root / "skill with spaces"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("candidate skill body\n")
            data = {
                "skill_name": "skill with spaces",
                "evals": [{"id": 1, "name": "instructions", "prompt": "raw task"}],
            }

            PREPARER.prepare_execution_workspace(workspace, skill_dir, data, runs=3)

            instructions = (workspace / "RUN_INSTRUCTIONS.md").read_text()
            for run_number in range(1, 4):
                self.assertIn(f"with_skill/run-{run_number}/subagent_prompt.md", instructions)
                self.assertIn(f"without_skill/run-{run_number}/subagent_prompt.md", instructions)
            self.assertIn("python3 -m scripts.aggregate_benchmark", instructions)
            self.assertIn("python3 eval-viewer/generate_review.py", instructions)
            self.assertNotIn("\npython ", instructions)
            self.assertIn("read-isolated sandbox", instructions)
            normalized_instructions = " ".join(instructions.split())
            self.assertIn("report isolation unavailable", normalized_instructions)
            self.assertIn("A prompt sentence forbidding tools is not enforcement", instructions)
            self.assertIn("grader assertions were finalized before preparation", instructions)
            self.assertIn(shlex.quote(str(workspace.resolve())), instructions)
            self.assertIn(shlex.quote(str(skill_dir.resolve())), instructions)
            self.assertIn(shlex.quote("skill with spaces"), instructions)

    def test_cli_prepares_and_stages_grader_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = root / "candidate-skill"
            workspace = root / "workspace"
            (skill_dir / "evals").mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("candidate skill body\n")
            evals = {
                "skill_name": "candidate-skill",
                "evals": [{"id": 1, "name": "cli", "prompt": "raw task"}],
            }
            (skill_dir / "evals" / "evals.json").write_text(json.dumps(evals))
            command = [
                sys.executable,
                str(SCRIPT),
                "--skill-dir",
                str(skill_dir),
                "--workspace",
                str(workspace),
                "--runs",
                "1",
            ]

            prepared = subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertIn("Prepared behavioral eval workspace", prepared.stdout)
            eval_dir = workspace / "eval-1-cli"
            for run_kind in ("with_skill", "without_skill"):
                response = eval_dir / run_kind / "run-1" / "outputs" / "response.md"
                response.write_text("response\n")
            staged = subprocess.run(
                [*command, "--stage-grader-data"],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("Staged grader metadata", staged.stdout)
            self.assertEqual(len(list(workspace.rglob("eval_metadata.json"))), 3)

    def test_cli_rejects_grader_stage_with_different_run_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = root / "candidate-skill"
            workspace = root / "workspace"
            (skill_dir / "evals").mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("candidate skill body\n")
            evals = {
                "skill_name": "candidate-skill",
                "evals": [{"id": 1, "name": "cli-mismatch", "prompt": "raw task"}],
            }
            (skill_dir / "evals" / "evals.json").write_text(json.dumps(evals))
            base_command = [
                sys.executable,
                str(SCRIPT),
                "--skill-dir",
                str(skill_dir),
                "--workspace",
                str(workspace),
            ]
            subprocess.run(
                [*base_command, "--runs", "2"],
                check=True,
                capture_output=True,
                text=True,
            )

            staged = subprocess.run(
                [*base_command, "--stage-grader-data"],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(staged.returncode, 0)
            self.assertIn("execution plan does not match", staged.stderr)
            self.assertEqual(list(workspace.rglob("eval_metadata.json")), [])


if __name__ == "__main__":
    unittest.main()
