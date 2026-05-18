#!/usr/bin/env python3
"""Run Claude Code skill trigger evals.

This runner installs one temporary project skill under ``.claude/skills`` for
each query and runs Claude Code in non-interactive stream-json mode. A positive
case is counted only when Claude invokes the matching ``Skill`` tool, receives
the synthetic skill body, and emits that body's unique sentinel. A negative case
is counted only when Claude emits no sentinel and makes no tool calls.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from trigger_eval_core import (
    EFFORTS,
    build_probe_prompt,
    load_trigger_evals,
    marker_detection,
    parse_frontmatter,
    slugify,
    summarize_trigger_results,
    write_probe_skill,
    write_summary_markdown as write_core_summary_markdown,
)


RUNNER = "claude-code"
DETECTOR = "claude-code-skill-sentinel"


def parse_stream_json(stdout: str) -> tuple[list[dict[str, Any]], list[str], dict[str, Any] | None]:
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
        if event.get("type") == "result":
            result = event.get("result")
            if isinstance(result, str):
                messages.append(result)
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
            continue
        message = event.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for item in message.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                messages.append(item["text"])
    return events, messages, usage


def claude_tool_diagnostic(events: list[dict[str, Any]], skill_name: str, marker: str) -> dict[str, Any]:
    tool_uses: list[dict[str, Any]] = []
    skill_loads: list[dict[str, Any]] = []
    synthetic_skill_bodies = 0
    for event in events:
        message = event.get("message")
        if isinstance(message, dict):
            if message.get("role") == "assistant":
                for item in message.get("content") or []:
                    if not isinstance(item, dict) or item.get("type") != "tool_use":
                        continue
                    tool_uses.append(
                        {
                            "name": item.get("name"),
                            "input": item.get("input"),
                            "id": item.get("id"),
                        }
                    )
                    if item.get("name") == "Skill" and isinstance(item.get("input"), dict):
                        if item["input"].get("skill") == skill_name:
                            skill_loads.append({"id": item.get("id"), "skill": skill_name})
            if message.get("role") == "user":
                for item in message.get("content") or []:
                    if not isinstance(item, dict):
                        continue
                    text = item.get("text") or item.get("content")
                    if isinstance(text, str) and "Base directory for this skill:" in text and marker in text:
                        synthetic_skill_bodies += 1
    disallowed = [
        tool
        for tool in tool_uses
        if not (tool.get("name") == "Skill" and isinstance(tool.get("input"), dict) and tool["input"].get("skill") == skill_name)
    ]
    return {
        "total": len(tool_uses),
        "skill_load_count": len(skill_loads),
        "skill_loads": skill_loads,
        "synthetic_skill_body_count": synthetic_skill_bodies,
        "disallowed_count": len(disallowed),
        "disallowed": disallowed,
    }


def check_claude_binary(claude_bin: str, timeout: int) -> dict[str, Any]:
    resolved = shutil.which(claude_bin)
    result: dict[str, Any] = {
        "name": "claude_binary",
        "ok": bool(resolved),
        "binary": claude_bin,
        "resolved": resolved,
    }
    if not resolved:
        result["reason"] = f"{claude_bin!r} was not found on PATH"
        return result
    started = time.monotonic()
    completed = subprocess.run(
        [resolved, "--version"],
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=timeout,
    )
    result.update(
        {
            "ok": completed.returncode == 0,
            "version_output": (completed.stdout or completed.stderr).strip().splitlines()[:5],
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    )
    if completed.returncode != 0:
        result["reason"] = completed.stderr.strip() or "claude --version failed"
    return result


def run_preflight(*, claude_bin: str, timeout: int) -> dict[str, Any]:
    checks = [check_claude_binary(claude_bin, timeout=min(timeout, 10))]
    ok = all(check.get("ok") for check in checks if check.get("required", True))
    unsupported_reason = None if ok else "preflight checks failed: " + ", ".join(
        check["name"] for check in checks if not check.get("ok")
    )
    return {
        "ok": ok,
        "driver_id": RUNNER,
        "checks": checks,
        "unsupported_reason": unsupported_reason,
    }


def run_one(
    *,
    claude_bin: str,
    workspace: Path,
    skill_name: str,
    description: str,
    effort: str | None,
    model: str | None,
    query_index: int,
    query: str,
    should_trigger: bool,
    timeout: int,
    keep_home: bool,
    preflight: dict[str, Any],
) -> dict[str, Any]:
    effort_label = effort or "default"
    run_slug = f"{query_index:02d}-{slugify(query)[:56]}"
    run_dir = workspace / effort_label / run_slug
    run_dir.mkdir(parents=True, exist_ok=True)
    home = run_dir / "home"
    cwd = run_dir / "cwd"
    cwd.mkdir(parents=True, exist_ok=True)
    marker = f"CLAUDE_TRIGGERED_{skill_name}_{effort_label}_{query_index}_{uuid.uuid4().hex[:12]}"
    write_probe_skill(
        home,
        name=skill_name,
        description=description,
        marker=marker,
        harness_label="Claude Code",
        skill_root=cwd / ".claude" / "skills",
    )
    probe_prompt = build_probe_prompt(query, allow_skill_body_read_command=False)
    requested_config = {
        "model": model,
        "effort": effort,
        "permission_mode": "dontAsk",
        "setting_sources": "project",
        "allowed_tools": ["Skill"],
        "output_format": "stream-json",
    }
    (run_dir / "query.json").write_text(
        json.dumps({"query": query, "effort": effort, "requested_config": requested_config}, indent=2)
        + "\n",
        encoding="utf-8",
    )

    cmd = [
        claude_bin,
        "-p",
        "--verbose",
        "--output-format",
        "stream-json",
        "--permission-mode",
        "dontAsk",
        "--setting-sources",
        "project",
        "--add-dir",
        str(cwd),
        "--allowedTools",
        "Skill",
        "--disallowedTools",
        "Bash,Edit,Write,Read,WebFetch,WebSearch",
    ]
    if model:
        cmd.extend(["--model", model])
    if effort:
        cmd.extend(["--effort", effort])

    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")

    started = time.monotonic()
    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            input=probe_prompt,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        returncode = None
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        timed_out = True
    duration = time.monotonic() - started

    (run_dir / "stdout.jsonl").write_text(stdout, encoding="utf-8")
    (run_dir / "stderr.log").write_text(stderr, encoding="utf-8")
    events, messages, usage = parse_stream_json(stdout)
    detection = marker_detection(messages, marker, skill_name)
    tool_calls = claude_tool_diagnostic(events, skill_name, marker)
    triggered = detection["sentinel_present_anywhere"]
    tool_contract_ok = (
        tool_calls["disallowed_count"] == 0
        and (
            tool_calls["skill_load_count"] > 0 and tool_calls["synthetic_skill_body_count"] > 0
            if should_trigger
            else tool_calls["total"] == 0
        )
    )
    passed = triggered == should_trigger and returncode == 0 and not timed_out and tool_contract_ok
    raw_events_path = run_dir / "events.json"
    raw_events_path.write_text(json.dumps(events, indent=2) + "\n", encoding="utf-8")
    result = {
        "query_index": query_index,
        "query": query,
        "probe_prompt": probe_prompt,
        "should_trigger": should_trigger,
        "triggered": triggered,
        "passed": passed,
        "effort": effort,
        "runner": RUNNER,
        "detector": DETECTOR,
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_seconds": round(duration, 3),
        "usage": usage,
        "requested_config": requested_config,
        "marker": marker,
        "messages": messages,
        "detection": detection,
        "tool_calls": tool_calls,
        "tool_contract_ok": tool_contract_ok,
        "preflight": {
            "ok": preflight["ok"],
            "unsupported_reason": preflight.get("unsupported_reason"),
        },
        "event_count": len(events),
        "raw_events_path": str(raw_events_path),
        "run_dir": str(run_dir),
        "command": cmd,
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not keep_home:
        shutil.rmtree(home, ignore_errors=True)
    return result


def write_unsupported(workspace: Path, skill_name: str, preflight: dict[str, Any]) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    summary = {
        "skill_name": skill_name,
        "runner": RUNNER,
        "driver_id": RUNNER,
        "detector": DETECTOR,
        "preflight": preflight,
        "unsupported_reason": preflight.get("unsupported_reason"),
        "efforts": {},
        "results": [],
    }
    (workspace / "trigger_results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# Claude Code Trigger Eval Summary: {skill_name}",
        "",
        "Preflight: `failed`.",
        f"Unsupported reason: {preflight.get('unsupported_reason') or 'unknown'}.",
        "",
        "No trigger eval results were counted.",
        "",
    ]
    (workspace / "trigger_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Claude Code trigger evals")
    parser.add_argument("--skill-dir", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--model")
    parser.add_argument("--effort", action="append", choices=EFFORTS)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--index", type=int, action="append", help="Run only the specified trigger eval index; repeatable")
    parser.add_argument("--keep-probe-homes", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()

    skill_dir = args.skill_dir.resolve()
    workspace = args.workspace.resolve()
    frontmatter = parse_frontmatter(skill_dir / "SKILL.md")
    efforts = args.effort or ["medium"]

    preflight = run_preflight(claude_bin=args.claude_bin, timeout=args.timeout)
    (workspace / "preflight.json").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "preflight.json").write_text(json.dumps(preflight, indent=2) + "\n", encoding="utf-8")
    if args.preflight_only:
        if preflight["ok"]:
            print(f"Preflight passed for {RUNNER}")
            return 0
        write_unsupported(workspace, frontmatter["name"], preflight)
        print(preflight.get("unsupported_reason") or "preflight failed")
        return 1
    if not preflight["ok"]:
        write_unsupported(workspace, frontmatter["name"], preflight)
        print(preflight.get("unsupported_reason") or "preflight failed")
        return 1

    evals = load_trigger_evals(skill_dir, args.index, args.limit)
    workspace.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for effort in efforts:
        for item in evals:
            print(f"[{effort}] query {item.index}: {item.query[:80]}", flush=True)
            results.append(
                run_one(
                    claude_bin=args.claude_bin,
                    workspace=workspace,
                    skill_name=frontmatter["name"],
                    description=frontmatter["description"],
                    effort=effort,
                    model=args.model,
                    query_index=item.index,
                    query=item.query,
                    should_trigger=item.should_trigger,
                    timeout=args.timeout,
                    keep_home=args.keep_probe_homes,
                    preflight=preflight,
                )
            )

    summary = summarize_trigger_results(
        results=results,
        skill_name=frontmatter["name"],
        runner=RUNNER,
        driver_id=RUNNER,
        detector=DETECTOR,
        preflight=preflight,
    )
    (workspace / "trigger_results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_core_summary_markdown(
        summary,
        workspace / "trigger_summary.md",
        title="Claude Code Trigger Eval Summary",
        detector=DETECTOR,
        explanatory_lines=[
            "This measures whether Claude Code invokes the selected temporary project skill and",
            "emits that skill body's unique sentinel. Positive cases must invoke only the matching",
            "`Skill` tool and receive the synthetic skill body; negative cases must make no tool",
            "calls and must not emit the sentinel.",
        ],
    )
    print(f"Wrote {workspace / 'trigger_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
