#!/usr/bin/env python3
"""Run Codex-native skill trigger evals.

This runner measures Codex implicit skill loading by installing one temporary
probe skill into an isolated HOME for each query. The probe uses the candidate
skill's actual name and description, but its body only instructs Codex to emit a
unique sentinel marker. Each Codex run receives a classification-only probe
prompt so non-triggering queries cannot perform repository or GitHub work. A run
is counted as triggered when the marker appears in Codex's JSONL output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any


EFFORTS = ("low", "medium", "high", "xhigh")


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "query"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_frontmatter(skill_md: Path) -> dict[str, str]:
    text = read_text(skill_md)
    if not text.startswith("---\n"):
        raise ValueError(f"{skill_md} does not start with YAML frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError(f"{skill_md} has unterminated YAML frontmatter")
    lines = text[4:end].splitlines()
    result: dict[str, str] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.startswith((" ", "\t")):
            index += 1
            continue
        if ":" not in line:
            index += 1
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if value in {">", ">-", "|", "|-"}:
            block: list[str] = []
            index += 1
            while index < len(lines):
                next_line = lines[index]
                if next_line and not next_line.startswith((" ", "\t")):
                    break
                block.append(next_line.strip())
                index += 1
            if value.startswith(">"):
                result[key] = " ".join(part for part in block if part)
            else:
                result[key] = "\n".join(block)
            continue
        result[key] = value.strip("\"'")
        index += 1
    for key in ("name", "description"):
        if not result.get(key):
            raise ValueError(f"{skill_md} frontmatter is missing {key!r}")
    return result


def folded_description(description: str) -> str:
    words = description.split()
    lines: list[str] = []
    current: list[str] = []
    current_len = 0
    for word in words:
        extra = len(word) + (1 if current else 0)
        if current and current_len + extra > 88:
            lines.append("  " + " ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += extra
    if current:
        lines.append("  " + " ".join(current))
    return "\n".join(lines)


def write_probe_skill(home: Path, *, name: str, description: str, marker: str) -> Path:
    skill_dir = home / ".agents" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                "description: >-",
                folded_description(description),
                "---",
                "",
                "# Codex Trigger Probe",
                "",
                "This temporary skill is used only by Codex trigger eval tooling.",
                "",
                "If this skill is loaded for the user's request, the final answer must be",
                f"exactly `{marker}` and nothing else. Do not run commands, inspect files,",
                "or continue the underlying workflow.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return skill_md


def build_probe_prompt(query: str) -> str:
    return "\n".join(
        [
            "Request to classify for skill triggering:",
            query,
            "",
            "This is a trigger-selection probe, not a request to perform the task.",
            "Do not run commands, inspect files, call external tools, access GitHub, or mutate any state.",
            "Do not use any skill merely because this is a probe or because a temporary skill exists.",
            "Use the temporary skill only when its description matches the request text above.",
            "If an available temporary skill applies to the request above, load and use that skill now,",
            "then follow its SKILL.md instructions exactly and stop. Do not answer from the skill name",
            "or description alone; the triggered answer is defined only inside the loaded skill body.",
            "If no temporary skill is loaded, answer exactly: SKILL_NOT_TRIGGERED",
        ]
    )


def parse_jsonl(stdout: str) -> tuple[list[dict[str, Any]], list[str], dict[str, Any] | None]:
    events: list[dict[str, Any]] = []
    messages: list[str] = []
    usage: dict[str, Any] | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(event)
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str):
                messages.append(text)
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = event["usage"]
    return events, messages, usage


def run_one(
    *,
    codex_bin: str,
    codex_home: Path,
    workspace: Path,
    skill_name: str,
    description: str,
    effort: str,
    model: str | None,
    query_index: int,
    query: str,
    should_trigger: bool,
    timeout: int,
    sandbox: str,
    keep_home: bool,
) -> dict[str, Any]:
    run_slug = f"{query_index:02d}-{slugify(query)[:56]}"
    run_dir = workspace / effort / run_slug
    run_dir.mkdir(parents=True, exist_ok=True)
    home = run_dir / "home"
    cwd = run_dir / "cwd"
    cwd.mkdir(parents=True, exist_ok=True)
    marker = f"CODEX_TRIGGERED_{skill_name}_{effort}_{query_index}_{uuid.uuid4().hex[:12]}"
    skill_md = write_probe_skill(home, name=skill_name, description=description, marker=marker)
    (run_dir / "query.json").write_text(
        json.dumps(
            {
                "query": query,
                "effort": effort,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    cmd = [
        codex_bin,
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--sandbox",
        sandbox,
        "-C",
        str(cwd),
        "-c",
        f"model_reasoning_effort={effort}",
    ]
    if model:
        cmd.extend(["-m", model])
    probe_prompt = build_probe_prompt(query)
    cmd.append(probe_prompt)

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["CODEX_HOME"] = str(codex_home)
    env.setdefault("NO_COLOR", "1")

    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = None
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
    duration = time.monotonic() - started

    (run_dir / "stdout.jsonl").write_text(stdout, encoding="utf-8")
    (run_dir / "stderr.log").write_text(stderr, encoding="utf-8")
    events, messages, usage = parse_jsonl(stdout)
    joined_messages = "\n".join(messages)
    triggered = marker in joined_messages
    passed = triggered == should_trigger and returncode == 0 and not timed_out
    result = {
        "query_index": query_index,
        "query": query,
        "probe_prompt": probe_prompt,
        "should_trigger": should_trigger,
        "triggered": triggered,
        "passed": passed,
        "effort": effort,
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_seconds": round(duration, 3),
        "usage": usage,
        "marker": marker,
        "messages": messages,
        "event_count": len(events),
        "run_dir": str(run_dir),
        "command": cmd,
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not keep_home:
        shutil.rmtree(home, ignore_errors=True)
    return result


def summarize(results: list[dict[str, Any]], skill_name: str) -> dict[str, Any]:
    by_effort: dict[str, dict[str, Any]] = {}
    for effort in EFFORTS:
        effort_results = [item for item in results if item["effort"] == effort]
        if not effort_results:
            continue
        passed = sum(1 for item in effort_results if item["passed"])
        expected_true = [item for item in effort_results if item["should_trigger"]]
        expected_false = [item for item in effort_results if not item["should_trigger"]]
        true_hits = sum(1 for item in expected_true if item["triggered"])
        false_avoids = sum(1 for item in expected_false if not item["triggered"])
        by_effort[effort] = {
            "total": len(effort_results),
            "passed": passed,
            "pass_rate": passed / len(effort_results),
            "true_positive_rate": true_hits / len(expected_true) if expected_true else None,
            "true_negatives": false_avoids,
            "false_positive_count": sum(1 for item in expected_false if item["triggered"]),
            "false_negative_count": sum(1 for item in expected_true if not item["triggered"]),
            "failed_indices": [item["query_index"] for item in effort_results if not item["passed"]],
            "mean_duration_seconds": sum(item["duration_seconds"] for item in effort_results)
            / len(effort_results),
        }
    return {
        "skill_name": skill_name,
        "detector": "codex-native-sentinel",
        "efforts": by_effort,
        "results": results,
    }


def write_summary_markdown(summary: dict[str, Any], output: Path) -> None:
    lines = [
        f"# Codex Trigger Eval Summary: {summary['skill_name']}",
        "",
        "Detector: `codex-native-sentinel`.",
        "",
        "| Effort | Passed | Pass Rate | TP Rate | False Positives | False Negatives | Mean Seconds | Failed Query Indices |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for effort, data in summary["efforts"].items():
        tp_rate = data["true_positive_rate"]
        lines.append(
            "| {effort} | {passed}/{total} | {pass_rate:.1%} | {tp_rate} | {fp} | {fn} | {seconds:.1f} | {failed} |".format(
                effort=effort,
                passed=data["passed"],
                total=data["total"],
                pass_rate=data["pass_rate"],
                tp_rate="n/a" if tp_rate is None else f"{tp_rate:.1%}",
                fp=data["false_positive_count"],
                fn=data["false_negative_count"],
                seconds=data["mean_duration_seconds"],
                failed=", ".join(str(item) for item in data["failed_indices"]) or "-",
            )
        )
    lines.extend(
        [
            "",
            "This measures whether Codex loads the skill body and follows its sentinel instruction.",
            "It does not depend on private router traces.",
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Codex-native trigger evals")
    parser.add_argument("--skill-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--effort", action="append", choices=EFFORTS)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--sandbox", default="read-only", choices=("read-only", "workspace-write", "danger-full-access"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--index", type=int, action="append", help="Run only the specified trigger eval index; repeatable")
    parser.add_argument("--keep-probe-homes", action="store_true")
    args = parser.parse_args()

    skill_dir = args.skill_dir.resolve()
    workspace = args.workspace.resolve()
    codex_home = (args.codex_home or Path.home() / ".codex").resolve()
    frontmatter = parse_frontmatter(skill_dir / "SKILL.md")
    evals = list(enumerate(json.loads(read_text(skill_dir / "evals" / "trigger-evals.json"))))
    if args.index:
        requested_indices = set(args.index)
        evals = [(index, item) for index, item in evals if index in requested_indices]
    if args.limit is not None:
        evals = evals[: args.limit]

    efforts = args.effort or ["medium"]
    workspace.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for effort in efforts:
        for index, item in evals:
            print(f"[{effort}] query {index}: {item['query'][:80]}", flush=True)
            result = run_one(
                codex_bin=args.codex_bin,
                codex_home=codex_home,
                workspace=workspace,
                skill_name=frontmatter["name"],
                description=frontmatter["description"],
                effort=effort,
                model=args.model,
                query_index=index,
                query=item["query"],
                should_trigger=bool(item["should_trigger"]),
                timeout=args.timeout,
                sandbox=args.sandbox,
                keep_home=args.keep_probe_homes,
            )
            results.append(result)

    summary = summarize(results, frontmatter["name"])
    (workspace / "trigger_results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_summary_markdown(summary, workspace / "trigger_summary.md")
    print(f"Wrote {workspace / 'trigger_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
