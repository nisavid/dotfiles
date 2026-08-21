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


def prompt_text(
    *,
    skill_dir: Path,
    eval_item: dict,
    run_kind: str,
) -> str:
    prompt_parts = [eval_item["prompt"]]
    prompt_parts.extend(read_scoped_text(skill_dir, fixture_path) for fixture_path in eval_item["fixture_paths"])
    if run_kind == "with_skill":
        prompt_parts.append(read_scoped_text(skill_dir, "SKILL.md"))
    return "\n\n".join(prompt_parts)


def write_eval(workspace: Path, skill_dir: Path, eval_item: dict, runs: int) -> None:
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
            prompt = prompt_text(
                skill_dir=skill_dir,
                eval_item=eval_item,
                run_kind=run_kind,
            )
            (run_dir / "subagent_prompt.md").write_text(prompt)


def write_run_instructions(workspace: Path, skill_name: str) -> None:
    instructions = f"""# Behavioral Eval Run Instructions

This workspace was generated for the `skill-creator` behavioral eval flow.

For each `eval-*` directory:

1. Spawn one subagent with `with_skill/run-1/subagent_prompt.md`.
2. Spawn one baseline subagent with `without_skill/run-1/subagent_prompt.md`.
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

    skill_dir = args.skill_dir.resolve()
    workspace = args.workspace.resolve()
    data = load_evals(skill_dir)
    workspace.mkdir(parents=True, exist_ok=True)

    for eval_item in data["evals"]:
        write_eval(workspace, skill_dir, eval_item, args.runs)

    write_run_instructions(workspace, data["skill_name"])
    print(f"Prepared behavioral eval workspace: {workspace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
