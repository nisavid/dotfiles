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
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from isolated_codex_runtime import (
    DEFAULT_IMAGE,
    PROBE_CWD,
    IsolationError,
    IsolatedCodexRuntime,
    add_runtime_arguments,
)
from trigger_eval_core import (
    EFFORTS,
    build_probe_prompt,
    load_trigger_evals,
    parse_frontmatter,
    slugify,
    summarize_trigger_results,
    write_probe_skill,
    write_summary_markdown as write_core_summary_markdown,
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
    container_runtime: str = "docker",
    runtime_image: str = DEFAULT_IMAGE,
) -> dict[str, Any]:
    if sandbox != "read-only":
        raise IsolationError("Trigger evaluation requires the isolated container runtime; alternate host sandbox modes are unsupported")
    run_slug = f"{query_index:02d}-{slugify(query)[:56]}-{uuid.uuid4().hex[:8]}"
    run_dir = workspace / effort / run_slug
    run_dir.mkdir(parents=True, exist_ok=True)
    home = run_dir / "home"
    cwd = run_dir / "cwd"
    cwd.mkdir(parents=True, exist_ok=True)
    marker = f"CODEX_TRIGGERED_{skill_name}_{effort}_{query_index}_{uuid.uuid4().hex[:12]}"
    skill_path = write_probe_skill(
        home,
        name=skill_name,
        description=description,
        marker=marker,
        harness_label="Codex",
    )
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
        "--skip-git-repo-check",
        "--sandbox",
        "danger-full-access",  # Inside the enforced outer container only.
        "-C",
        str(PROBE_CWD),
        "-c",
        f"model_reasoning_effort={effort}",
    ]
    if model:
        cmd.extend(["-m", model])
    probe_prompt = build_probe_prompt(query, allow_skill_body_read_command=False)
    cmd.append(probe_prompt)

    started = time.monotonic()
    timed_out = False
    try:
        with IsolatedCodexRuntime(
            codex_home=codex_home, skill_path=skill_path,
            engine=container_runtime, image=runtime_image, timeout=timeout,
        ) as runtime:
            completed = runtime.run(cmd, timeout=timeout)
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
        "isolation": "credential-separated-container",
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not keep_home:
        shutil.rmtree(home, ignore_errors=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Codex-native trigger evals")
    parser.add_argument("--skill-dir", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--codex-home", type=Path, help="Credential source for the separate broker; never mounted in the evaluator")
    add_runtime_arguments(parser)
    parser.add_argument("--model")
    parser.add_argument("--effort", action="append", choices=EFFORTS)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--sandbox", default="read-only", choices=("read-only",), help="Legacy compatibility option; the container boundary is always required")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--index", type=int, action="append", help="Run only the specified trigger eval index; repeatable")
    parser.add_argument("--keep-probe-homes", action="store_true")
    args = parser.parse_args()

    skill_dir = args.skill_dir.resolve()
    workspace = args.workspace.resolve()
    codex_home = (args.codex_home or Path.home() / ".codex").resolve()
    frontmatter = parse_frontmatter(skill_dir / "SKILL.md")
    evals = load_trigger_evals(skill_dir, args.index, args.limit)

    efforts = args.effort or ["medium"]
    workspace.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for effort in efforts:
        for item in evals:
            print(f"[{effort}] query {item.index}: {item.query[:80]}", flush=True)
            result = run_one(
                codex_bin=args.codex_bin,
                codex_home=codex_home,
                workspace=workspace,
                skill_name=frontmatter["name"],
                description=frontmatter["description"],
                effort=effort,
                model=args.model,
                query_index=item.index,
                query=item.query,
                should_trigger=item.should_trigger,
                timeout=args.timeout,
                sandbox=args.sandbox,
                keep_home=args.keep_probe_homes,
                container_runtime=args.container_runtime,
                runtime_image=args.runtime_image,
            )
            results.append(result)

    summary = summarize_trigger_results(
        results=results,
        skill_name=frontmatter["name"],
        runner=None,
        driver_id=None,
        detector="codex-native-sentinel",
    )
    (workspace / "trigger_results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_core_summary_markdown(
        summary,
        workspace / "trigger_summary.md",
        title="Codex Trigger Eval Summary",
        detector="codex-native-sentinel",
        explanatory_lines=[
            "This measures whether Codex loads the skill body and follows its sentinel instruction.",
            "It does not depend on private router traces.",
        ],
    )
    print(f"Wrote {workspace / 'trigger_results.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (IsolationError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
