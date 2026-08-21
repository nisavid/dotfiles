#!/usr/bin/env python3
"""Prepare skill-creator behavioral eval workspace files.

This script does not run agents. It expands evals/evals.json into the
workspace layout expected by skill-creator's behavioral eval flow, including
per-eval metadata, run directories, output directories, and subagent prompts.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "eval"


def load_evals(skill_dir: Path) -> dict:
    return json.loads(read_scoped_text(skill_dir, "evals/evals.json"))


def read_scoped_text(skill_dir: Path, relative_path: str) -> str:
    skill_root = skill_dir.resolve(strict=True)
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"source path must stay within the skill directory: {relative_path}")

    candidate = skill_root
    for part in path.parts:
        candidate /= part
        if candidate.is_symlink():
            raise ValueError(f"source path must not contain symlinks: {relative_path}")

    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(skill_root) or not resolved.is_file():
        raise ValueError(f"source path must be a regular file within the skill directory: {relative_path}")
    return resolved.read_text(encoding="utf-8")


def prompt_variants(
    *,
    skill_dir: Path,
    eval_item: dict,
) -> dict[str, str]:
    prompt_parts = [eval_item["prompt"]]
    prompt_parts.extend(read_scoped_text(skill_dir, fixture_path) for fixture_path in eval_item["fixture_paths"])
    without_skill = "\n\n".join(prompt_parts)
    with_skill = "\n\n".join([*prompt_parts, read_scoped_text(skill_dir, "SKILL.md")])
    return {"with_skill": with_skill, "without_skill": without_skill}


def write_eval(
    workspace: Path,
    eval_item: dict,
    runs: int,
    prompts: dict[str, str],
) -> None:
    eval_name = eval_item.get("name") or slugify(eval_item["prompt"])[:48]
    eval_dir = workspace / f"eval-{eval_item['id']}-{slugify(eval_name)}"
    eval_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "eval_id": eval_item["id"],
        "eval_name": eval_name,
        "prompt": eval_item["prompt"],
        "assertions": eval_item.get("expectations", []),
    }
    (eval_dir / "eval_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")

    for run_kind in ("with_skill", "without_skill"):
        for run_number in range(1, runs + 1):
            run_dir = eval_dir / run_kind / f"run-{run_number}"
            outputs_dir = run_dir / "outputs"
            outputs_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "eval_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
            (run_dir / "subagent_prompt.md").write_text(prompts[run_kind])


def write_run_instructions(workspace: Path, skill_name: str, runs: int) -> None:
    instructions = f"""# Behavioral Eval Run Instructions

This workspace was generated for the `skill-creator` behavioral eval flow.

For each `eval-*` directory:

1. For every run from `run-1` through `run-{runs}`, spawn one subagent with the
   corresponding `with_skill/<run>/subagent_prompt.md`.
2. For every run from `run-1` through `run-{runs}`, spawn one baseline subagent
   with the corresponding `without_skill/<run>/subagent_prompt.md`.
3. Allow no tool use for either subagent.
4. Capture each subagent's final response and write it to that run's `outputs/response.md`.
5. Grade each run against `eval_metadata.json` assertions and save `grading.json`
   in the run directory using skill-creator's required fields:
   `expectations[].text`, `expectations[].passed`, and `expectations[].evidence`.
6. Run:

```bash
cd <skill-creator-skill-dir>
python -m scripts.aggregate_benchmark {workspace} --skill-name {skill_name}
python eval-viewer/generate_review.py {workspace} --skill-name {skill_name} --benchmark {workspace}/benchmark.json --static {workspace}/review.html
```

The static viewer at `review.html` is the human review artifact.
"""
    (workspace / "RUN_INSTRUCTIONS.md").write_text(instructions)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare behavioral eval workspace")
    parser.add_argument(
        "--skill-dir",
        type=Path,
        required=True,
        help="Path to the skill directory",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        required=True,
        help="Path to the iteration workspace to create",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Runs per configuration to scaffold",
    )
    args = parser.parse_args()
    if args.runs <= 0:
        parser.error("--runs must be greater than zero")

    skill_dir = args.skill_dir.resolve()
    workspace = args.workspace.resolve()
    data = load_evals(skill_dir)
    prepared_evals = [
        (eval_item, prompt_variants(skill_dir=skill_dir, eval_item=eval_item))
        for eval_item in data["evals"]
    ]
    workspace.mkdir(parents=True, exist_ok=True)

    for eval_item, prompts in prepared_evals:
        write_eval(workspace, eval_item, args.runs, prompts)

    write_run_instructions(workspace, data["skill_name"], args.runs)
    print(f"Prepared behavioral eval workspace: {workspace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
