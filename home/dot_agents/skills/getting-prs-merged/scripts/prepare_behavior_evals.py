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
    evals_path = skill_dir / "evals" / "evals.json"
    return json.loads(evals_path.read_text())


def prompt_text(
    *,
    skill_dir: Path,
    eval_item: dict,
    run_kind: str,
    outputs_dir: Path,
) -> str:
    files = eval_item.get("files", [])
    file_lines = "\n".join(f"- {skill_dir / file_path}" for file_path in files) or "- none"
    expectations = "\n".join(f"- {item}" for item in eval_item.get("expectations", []))

    if run_kind == "with_skill":
        skill_line = f"- Skill path: {skill_dir}"
        setup = "Read and apply the skill before answering."
    else:
        skill_line = "- Skill path: none"
        setup = "Do not read or apply the skill. Answer from the prompt and files only."

    return f"""Execute this skill behavioral eval.

{skill_line}
- Task: {eval_item["prompt"]}
- Input files:
{file_lines}
- Save outputs to: {outputs_dir}
- Outputs to save: `response.md` containing the final response or action trace.

{setup}

Do not run live git or GitHub commands. Treat the input files as the complete
mock repository and PR state. If you would normally run a command, describe the
command and the expected gate it checks instead.

Expected behavior:
{eval_item.get("expected_output", "")}

Assertions the grader will check:
{expectations}
"""


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
                outputs_dir=outputs_dir,
            )
            (run_dir / "subagent_prompt.md").write_text(prompt)


def write_run_instructions(workspace: Path, skill_name: str) -> None:
    instructions = f"""# Behavioral Eval Run Instructions

This workspace was generated for the `skill-creator` behavioral eval flow.

For each `eval-*` directory:

1. Spawn one subagent with `with_skill/run-1/subagent_prompt.md`.
2. Spawn one baseline subagent with `without_skill/run-1/subagent_prompt.md`.
3. Ask each subagent to save `response.md` under its listed `outputs/` directory.
4. Grade each run against `eval_metadata.json` assertions and save `grading.json`
   in the run directory using skill-creator's required fields:
   `expectations[].text`, `expectations[].passed`, and `expectations[].evidence`.
5. Run:

```bash
cd /home/nisavid/.agents/skills/skill-creator
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
        default=Path(__file__).resolve().parents[1],
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
