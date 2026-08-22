#!/usr/bin/env python3
"""Prepare isolated skill-creator behavioral eval workspaces in two phases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


EXECUTION_PLAN_NAME = ".execution-plan.json"
RUN_KINDS = ("with_skill", "without_skill")


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "eval"


def selected_files(eval_item: dict) -> tuple[str, ...]:
    files = eval_item.get("files")
    legacy_files = eval_item.get("fixture_paths")
    if files is not None and legacy_files is not None and files != legacy_files:
        raise ValueError("eval files and fixture_paths disagree")
    selected = files if files is not None else legacy_files
    if selected is None:
        return ()
    if not isinstance(selected, list) or any(not isinstance(value, str) for value in selected):
        raise ValueError("eval files must be a list of strings")
    return tuple(selected)


@dataclass(frozen=True)
class EvalSpec:
    eval_id: int
    name: str
    prompt: str
    files: tuple[str, ...]
    expected_output: str
    expectations: tuple[dict, ...]

    @classmethod
    def from_mapping(cls, eval_item: dict) -> EvalSpec:
        if not isinstance(eval_item, dict):
            raise ValueError("each eval must be an object")
        eval_id = eval_item.get("id")
        if type(eval_id) is not int or eval_id < 0:
            raise ValueError("eval id must be a nonnegative integer")
        prompt = eval_item.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("eval prompt must be a nonempty string")
        supplied_name = eval_item.get("name")
        if supplied_name is not None and not isinstance(supplied_name, str):
            raise ValueError("eval name must be a nonempty string")
        name = supplied_name or slugify(prompt)[:48]
        expected_output = eval_item.get("expected_output", "")
        if not isinstance(expected_output, str):
            raise ValueError("eval expected_output must be a string")
        expectations = eval_item.get("expectations", [])
        if not isinstance(expectations, list) or any(not isinstance(item, dict) for item in expectations):
            raise ValueError("eval expectations must be a list of objects")
        return cls(
            eval_id=eval_id,
            name=name,
            prompt=prompt,
            files=selected_files(eval_item),
            expected_output=expected_output,
            expectations=tuple(expectations),
        )

    @property
    def directory_name(self) -> str:
        return f"eval-{self.eval_id}-{slugify(self.name)}"

    def metadata(self) -> dict:
        return {
            "eval_id": self.eval_id,
            "eval_name": self.name,
            "prompt": self.prompt,
            "expected_output": self.expected_output,
            "assertions": list(self.expectations),
        }

    def grading_contract(self) -> dict:
        return {
            **self.metadata(),
            "files": list(self.files),
        }


@dataclass(frozen=True)
class EvaluationSuite:
    skill_name: str
    evals: tuple[EvalSpec, ...]

    @classmethod
    def from_mapping(cls, data: dict) -> EvaluationSuite:
        if not isinstance(data, dict):
            raise ValueError("eval data must be an object")
        skill_name = data.get("skill_name")
        if not isinstance(skill_name, str) or not skill_name:
            raise ValueError("skill_name must be a nonempty string")
        raw_evals = data.get("evals")
        if not isinstance(raw_evals, list) or not raw_evals:
            raise ValueError("evals must be a nonempty list")
        evals = tuple(EvalSpec.from_mapping(item) for item in raw_evals)
        eval_ids = [item.eval_id for item in evals]
        if len(eval_ids) != len(set(eval_ids)):
            raise ValueError("eval ids must be unique")
        return cls(skill_name=skill_name, evals=evals)


@dataclass(frozen=True)
class RunSpec:
    eval_spec: EvalSpec
    run_kind: str
    run_number: int

    @property
    def relative_run_directory(self) -> Path:
        return Path(self.eval_spec.directory_name) / self.run_kind / f"run-{self.run_number}"

    @property
    def relative_prompt(self) -> Path:
        return self.relative_run_directory / "subagent_prompt.md"

    @property
    def relative_response(self) -> Path:
        return self.relative_run_directory / "outputs" / "response.md"


@dataclass(frozen=True)
class PreparedRun:
    run_spec: RunSpec
    prompt_bytes: bytes
    prompt_sha256: str


def build_run_specs(suite: EvaluationSuite, runs: int) -> tuple[RunSpec, ...]:
    if type(runs) is not int or runs < 1:
        raise ValueError("runs must be a positive integer")
    return tuple(
        RunSpec(eval_spec=eval_spec, run_kind=run_kind, run_number=run_number)
        for eval_spec in suite.evals
        for run_kind in RUN_KINDS
        for run_number in range(1, runs + 1)
    )


def fixture_text(*, skill_dir: Path, eval_item: EvalSpec | dict) -> str:
    files = eval_item.files if isinstance(eval_item, EvalSpec) else selected_files(eval_item)
    if not files:
        return ""
    skill_root = skill_dir.resolve(strict=True)
    contents: list[str] = []
    for file_value in files:
        relative_path = Path(file_value)
        if relative_path.is_absolute():
            raise ValueError("eval input path must be relative to the skill")
        input_path = (skill_root / relative_path).resolve(strict=True)
        try:
            input_path.relative_to(skill_root)
        except ValueError as error:
            raise ValueError("eval input path must stay within the skill") from error
        if not input_path.is_file():
            raise ValueError("eval input path must be a regular file")
        contents.append(input_path.read_text().rstrip("\n"))
    return "\n\n".join(contents)


def candidate_skill_text(skill_dir: Path) -> str:
    skill_root = skill_dir.resolve(strict=True)
    skill_entrypoint = skill_root / "SKILL.md"
    if skill_entrypoint.is_symlink():
        raise ValueError("candidate SKILL.md must not be a symbolic link")
    resolved_entrypoint = skill_entrypoint.resolve(strict=True)
    try:
        resolved_entrypoint.relative_to(skill_root)
    except ValueError as error:
        raise ValueError("candidate SKILL.md must stay within the skill") from error
    if not resolved_entrypoint.is_file():
        raise ValueError("candidate SKILL.md must be a regular file")
    return resolved_entrypoint.read_text().rstrip("\n")


def render_prompt(*, prompt: str, fixture: str, candidate_skill: str | None) -> str:
    fixture_section = f"\n\nFixture:\n{fixture}" if fixture else ""
    if candidate_skill is not None:
        skill_section = (
            f"Candidate skill:\n{candidate_skill}\n\n"
            "Apply the candidate skill before answering."
        )
    else:
        skill_section = "No candidate skill is provided."
    return f"""Execute this skill behavioral eval.

Task:
{prompt}{fixture_section}

{skill_section}

Return only the final response or action trace.
"""


def prompt_text(*, skill_dir: Path, eval_item: EvalSpec | dict, run_kind: str) -> str:
    if run_kind not in RUN_KINDS:
        raise ValueError("run kind is invalid")
    prompt = eval_item.prompt if isinstance(eval_item, EvalSpec) else eval_item.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("eval prompt must be a nonempty string")
    fixture = fixture_text(skill_dir=skill_dir, eval_item=eval_item)
    candidate_skill = candidate_skill_text(skill_dir) if run_kind == "with_skill" else None
    return render_prompt(prompt=prompt, fixture=fixture, candidate_skill=candidate_skill)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def materialize_runs(skill_dir: Path, run_specs: tuple[RunSpec, ...]) -> tuple[PreparedRun, ...]:
    candidate_skill = candidate_skill_text(skill_dir)
    fixture_cache: dict[int, str] = {}
    prompt_cache: dict[tuple[int, str], tuple[bytes, str]] = {}
    prepared_runs: list[PreparedRun] = []
    for run_spec in run_specs:
        eval_id = run_spec.eval_spec.eval_id
        if eval_id not in fixture_cache:
            fixture_cache[eval_id] = fixture_text(
                skill_dir=skill_dir,
                eval_item=run_spec.eval_spec,
            )
        cache_key = (run_spec.eval_spec.eval_id, run_spec.run_kind)
        if cache_key not in prompt_cache:
            prompt = render_prompt(
                prompt=run_spec.eval_spec.prompt,
                fixture=fixture_cache[eval_id],
                candidate_skill=(
                    candidate_skill if run_spec.run_kind == "with_skill" else None
                ),
            )
            prompt_bytes = prompt.encode()
            prompt_cache[cache_key] = (
                prompt_bytes,
                hashlib.sha256(prompt_bytes).hexdigest(),
            )
        prompt_bytes, prompt_sha256 = prompt_cache[cache_key]
        prepared_runs.append(
            PreparedRun(
                run_spec=run_spec,
                prompt_bytes=prompt_bytes,
                prompt_sha256=prompt_sha256,
            )
        )
    return tuple(prepared_runs)


def execution_plan(suite: EvaluationSuite, prepared_runs: tuple[PreparedRun, ...]) -> dict:
    prompts = []
    for prepared_run in prepared_runs:
        run_spec = prepared_run.run_spec
        prompts.append(
            {
                "eval_id": run_spec.eval_spec.eval_id,
                "prompt": run_spec.relative_prompt.as_posix(),
                "sha256": prepared_run.prompt_sha256,
            }
        )
    grading_json = json.dumps(
        [eval_spec.grading_contract() for eval_spec in suite.evals],
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "schema_version": 1,
        "skill_name": suite.skill_name,
        "runs": max(prepared_run.run_spec.run_number for prepared_run in prepared_runs),
        "grading_contract_sha256": sha256_text(grading_json),
        "prompts": prompts,
    }


def write_execution_files(root: Path, prepared_runs: tuple[PreparedRun, ...]) -> None:
    for prepared_run in prepared_runs:
        run_spec = prepared_run.run_spec
        run_dir = root / run_spec.relative_run_directory
        (run_dir / "outputs").mkdir(parents=True, exist_ok=False)
        (root / run_spec.relative_prompt).write_bytes(prepared_run.prompt_bytes)


def write_run_instructions(
    output_root: Path,
    published_workspace: Path,
    skill_dir: Path,
    suite: EvaluationSuite,
    prepared_runs: tuple[PreparedRun, ...],
) -> None:
    run_numbers = sorted(
        {prepared_run.run_spec.run_number for prepared_run in prepared_runs}
    )
    run_pairs = "\n".join(
        f"- `with_skill/run-{run_number}/subagent_prompt.md` and "
        f"`without_skill/run-{run_number}/subagent_prompt.md`"
        for run_number in run_numbers
    )
    quoted_script = shlex.quote(str(Path(__file__).resolve()))
    quoted_skill_dir = shlex.quote(str(skill_dir.resolve()))
    quoted_workspace = shlex.quote(str(published_workspace.resolve()))
    quoted_skill_name = shlex.quote(suite.skill_name)
    quoted_benchmark = shlex.quote(str((published_workspace / "benchmark.json").resolve()))
    quoted_review = shlex.quote(str((published_workspace / "review.html").resolve()))
    runs = max(run_numbers)
    instructions = f"""# Behavioral Eval Run Instructions

This workspace was generated for the `skill-creator` behavioral eval flow.
The expected output and grader assertions were finalized before preparation.
Changing that contract requires a new workspace and fresh executions.

For each `eval-*` directory:

1. Require either harness-enforced tool removal or a read-isolated sandbox that
   cannot access the source skill, source evals, grader data, or other non-prompt
   artifacts. A prompt sentence forbidding tools is not enforcement. If neither
   boundary is available, do not execute the eval; report isolation unavailable.
2. Execute every with-skill and baseline prompt pair:
{run_pairs}
3. Give each execution agent only its prompt contents.
4. Save each returned final response as `response.md` under that run's `outputs/` directory.
5. After every response exists, stage grader-only metadata:

```bash
python3 {quoted_script} \\
  --skill-dir {quoted_skill_dir} \\
  --workspace {quoted_workspace} \\
  --runs {runs} \\
  --stage-grader-data
```

6. Grade each run against `eval_metadata.json` assertions and save `grading.json`
   in the run directory using skill-creator's required fields:
   `expectations[].text`, `expectations[].passed`, and `expectations[].evidence`.
7. Run:

```bash
cd <skill-creator-skill-dir>
python3 -m scripts.aggregate_benchmark {quoted_workspace} --skill-name {quoted_skill_name}
python3 eval-viewer/generate_review.py {quoted_workspace} \\
  --skill-name {quoted_skill_name} \\
  --benchmark {quoted_benchmark} \\
  --static {quoted_review}
```

The static viewer at `review.html` is the human review artifact.
"""
    (output_root / "RUN_INSTRUCTIONS.md").write_text(instructions)


def prepare_execution_workspace(workspace: Path, skill_dir: Path, data: dict, runs: int) -> None:
    suite = EvaluationSuite.from_mapping(data)
    run_specs = build_run_specs(suite, runs)
    prepared_runs = materialize_runs(skill_dir, run_specs)
    plan = execution_plan(suite, prepared_runs)
    workspace = Path(os.path.abspath(workspace))
    if workspace.is_symlink():
        raise ValueError("execution workspace must not be a symbolic link")
    if workspace.exists() and (not workspace.is_dir() or any(workspace.iterdir())):
        raise ValueError("execution workspace must be new or empty")
    workspace.parent.mkdir(parents=True, exist_ok=True)
    workspace = workspace.parent.resolve(strict=True) / workspace.name
    staging = Path(tempfile.mkdtemp(prefix=f".{workspace.name}.prepare-", dir=workspace.parent))
    try:
        write_execution_files(staging, prepared_runs)
        (staging / EXECUTION_PLAN_NAME).write_text(json.dumps(plan, indent=2) + "\n")
        write_run_instructions(staging, workspace, skill_dir, suite, prepared_runs)
        os.replace(staging, workspace)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def contained_path(
    workspace: Path,
    relative_path: str,
    description: str,
    *,
    require_exists: bool,
) -> Path:
    if workspace.is_symlink():
        raise ValueError("execution workspace must not be a symbolic link")
    workspace_root = workspace.resolve(strict=True)
    relative = Path(relative_path)
    if relative.is_absolute():
        raise ValueError(f"{description} must stay within the workspace")
    path = (workspace_root / relative).resolve(strict=require_exists)
    try:
        path.relative_to(workspace_root)
    except ValueError as error:
        raise ValueError(f"{description} must stay within the workspace") from error
    return path


def stage_grader_metadata(workspace: Path, skill_dir: Path, data: dict, runs: int) -> None:
    suite = EvaluationSuite.from_mapping(data)
    run_specs = build_run_specs(suite, runs)
    prepared_runs = materialize_runs(skill_dir, run_specs)
    expected_plan = execution_plan(suite, prepared_runs)
    try:
        stored_plan = json.loads((workspace / EXECUTION_PLAN_NAME).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("execution plan is missing or invalid") from error
    if stored_plan != expected_plan:
        raise ValueError("execution plan does not match the requested grader stage")
    for prepared_run, prompt_record in zip(
        prepared_runs,
        stored_plan["prompts"],
        strict=True,
    ):
        run_spec = prepared_run.run_spec
        prompt_path = contained_path(
            workspace,
            prompt_record["prompt"],
            "execution prompt",
            require_exists=True,
        )
        if hashlib.sha256(prompt_path.read_bytes()).hexdigest() != prompt_record["sha256"]:
            raise ValueError("execution prompt does not match the prepared plan")
        response_path = contained_path(
            workspace,
            run_spec.relative_response.as_posix(),
            "execution response",
            require_exists=False,
        )
        if not response_path.is_file():
            raise ValueError("all responses must exist before staging grader metadata")
    metadata_by_eval = {
        eval_spec.eval_id: json.dumps(eval_spec.metadata(), indent=2) + "\n"
        for eval_spec in suite.evals
    }
    for eval_spec in suite.evals:
        eval_dir = contained_path(
            workspace,
            eval_spec.directory_name,
            "eval directory",
            require_exists=True,
        )
        (eval_dir / "eval_metadata.json").write_text(metadata_by_eval[eval_spec.eval_id])
    for run_spec in run_specs:
        run_dir = contained_path(
            workspace,
            run_spec.relative_run_directory.as_posix(),
            "run directory",
            require_exists=True,
        )
        (run_dir / "eval_metadata.json").write_text(metadata_by_eval[run_spec.eval_spec.eval_id])


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare behavioral eval workspace")
    parser.add_argument("--skill-dir", type=Path, required=True, help="Path to the skill directory")
    parser.add_argument("--workspace", type=Path, required=True, help="Iteration workspace")
    parser.add_argument("--runs", type=int, default=1, help="Runs per configuration")
    parser.add_argument(
        "--stage-grader-data",
        action="store_true",
        help="After all responses exist, add metadata needed only by graders",
    )
    args = parser.parse_args()
    try:
        skill_dir = args.skill_dir.resolve(strict=True)
        data = json.loads((skill_dir / "evals" / "evals.json").read_text())
        if args.stage_grader_data:
            stage_grader_metadata(args.workspace, skill_dir, data, args.runs)
            print(f"Staged grader metadata: {args.workspace.resolve()}")
        else:
            prepare_execution_workspace(args.workspace, skill_dir, data, args.runs)
            print(f"Prepared behavioral eval workspace: {args.workspace.resolve()}")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
