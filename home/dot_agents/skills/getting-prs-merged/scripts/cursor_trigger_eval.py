#!/usr/bin/env python3
"""Run Cursor Agent CLI skill trigger evals.

Cursor Agent does not expose a first-class skill invocation tool like Claude
Code. This runner uses a project ``AGENTS.md`` as a harness shim: the shim lists
the temporary skill metadata and body path, while the sentinel exists only in
``.cursor/skills/<name>/SKILL.md``. A positive case is counted only when Cursor
reads that temporary skill body and emits its sentinel. A negative case may read
the shim, but it must not read the skill body or emit the sentinel.
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


RUNNER = "cursor-agent"
DETECTOR = "cursor-agent-rule-sentinel"


def write_cursor_shim(cwd: Path, *, skill_name: str, description: str, skill_path: Path) -> Path:
    shim = cwd / "AGENTS.md"
    relative_skill_path = skill_path.relative_to(cwd)
    shim.write_text(
        "\n".join(
            [
                "# Trigger Eval Harness",
                "",
                "Available temporary skill:",
                f"- {skill_name}: {description} Body path: {relative_skill_path}",
                "",
                "If the user's request matches the temporary skill description, read the body path and follow the body exactly.",
                "If it does not match, answer exactly SKILL_NOT_TRIGGERED.",
                "Do not use any files or tools except this AGENTS.md shim and the matching temporary skill body.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return shim


def write_cursor_config(cwd: Path, *, shim_path: Path, skill_path: Path) -> Path:
    config_dir = cwd / ".cursor"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "cli.json"
    config_path.write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [
                        f"Read({shim_path.relative_to(cwd)})",
                        f"Read({skill_path.relative_to(cwd)})",
                    ],
                    "deny": [
                        "Shell(*)",
                        "Write(*)",
                        "WebFetch(*)",
                    ],
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path


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
        if event.get("type") == "assistant":
            message = event.get("message")
            if isinstance(message, dict):
                for item in message.get("content") or []:
                    if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                        messages.append(item["text"])
        if event.get("type") == "result":
            result = event.get("result")
            if isinstance(result, str):
                messages.append(result)
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
    return events, messages, usage


def _cursor_read_path(event: dict[str, Any]) -> str | None:
    tool_call = event.get("tool_call")
    if not isinstance(tool_call, dict):
        return None
    read_call = tool_call.get("readToolCall")
    if not isinstance(read_call, dict):
        return None
    args = read_call.get("args")
    if isinstance(args, dict) and isinstance(args.get("path"), str):
        return args["path"]
    return None


def cursor_tool_diagnostic(events: list[dict[str, Any]], *, shim_path: Path, skill_path: Path) -> dict[str, Any]:
    tool_calls: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "tool_call" or event.get("subtype") != "started":
            continue
        read_path = _cursor_read_path(event)
        tool_calls.append(
            {
                "kind": "read" if read_path else "unknown",
                "path": read_path,
                "call_id": event.get("call_id"),
            }
        )
    shim = str(shim_path)
    skill = str(skill_path)
    shim_reads = [call for call in tool_calls if call["path"] == shim]
    skill_reads = [call for call in tool_calls if call["path"] == skill]
    disallowed = [
        call
        for call in tool_calls
        if call["path"] not in {shim, skill}
    ]
    return {
        "total": len(tool_calls),
        "shim_read_count": len(shim_reads),
        "skill_body_read_count": len(skill_reads),
        "disallowed_count": len(disallowed),
        "disallowed": disallowed,
        "calls": tool_calls,
    }


def check_cursor_binary(cursor_bin: str, timeout: int) -> dict[str, Any]:
    resolved = shutil.which(cursor_bin)
    result: dict[str, Any] = {
        "name": "cursor_binary",
        "ok": bool(resolved),
        "binary": cursor_bin,
        "resolved": resolved,
    }
    if not resolved:
        result["reason"] = f"{cursor_bin!r} was not found on PATH"
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
        result["reason"] = completed.stderr.strip() or "cursor-agent --version failed"
    return result


def run_preflight(*, cursor_bin: str, timeout: int) -> dict[str, Any]:
    checks = [check_cursor_binary(cursor_bin, timeout=min(timeout, 10))]
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


def cursor_model_for_effort(effort: str | None) -> str:
    if effort in {None, "low"}:
        return "auto"
    return "auto"


def run_one(
    *,
    cursor_bin: str,
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
    marker = f"CURSOR_TRIGGERED_{skill_name}_{effort_label}_{query_index}_{uuid.uuid4().hex[:12]}"
    skill_path = write_probe_skill(
        home,
        name=skill_name,
        description=description,
        marker=marker,
        harness_label="Cursor Agent",
        skill_root=cwd / ".cursor" / "skills",
    )
    shim_path = write_cursor_shim(cwd, skill_name=skill_name, description=description, skill_path=skill_path)
    config_path = write_cursor_config(cwd, shim_path=shim_path, skill_path=skill_path)
    probe_prompt = build_probe_prompt(query, allow_skill_body_read_command=False)
    requested_model = model or cursor_model_for_effort(effort)
    requested_config = {
        "model": requested_model,
        "effort": effort,
        "mode": "ask",
        "output_format": "stream-json",
        "workspace": str(cwd),
        "config_path": str(config_path),
    }
    (run_dir / "query.json").write_text(
        json.dumps({"query": query, "effort": effort, "requested_config": requested_config}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    cmd = [
        cursor_bin,
        "-p",
        "--trust",
        "--workspace",
        str(cwd),
        "--output-format",
        "stream-json",
        "--mode",
        "ask",
        "--model",
        requested_model,
        probe_prompt,
    ]
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["NO_COLOR"] = "1"
    started = time.monotonic()
    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
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
    tool_calls = cursor_tool_diagnostic(events, shim_path=shim_path, skill_path=skill_path)
    triggered = detection["sentinel_present_anywhere"]
    tool_contract_ok = (
        tool_calls["disallowed_count"] == 0
        and (
            tool_calls["skill_body_read_count"] > 0
            if should_trigger
            else tool_calls["skill_body_read_count"] == 0
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
        f"# Cursor Agent Trigger Eval Summary: {skill_name}",
        "",
        "Preflight: `failed`.",
        f"Unsupported reason: {preflight.get('unsupported_reason') or 'unknown'}.",
        "",
        "No trigger eval results were counted.",
        "",
    ]
    (workspace / "trigger_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Cursor Agent trigger evals")
    parser.add_argument("--skill-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--cursor-bin", default="cursor-agent")
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
    preflight = run_preflight(cursor_bin=args.cursor_bin, timeout=args.timeout)
    workspace.mkdir(parents=True, exist_ok=True)
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
    results: list[dict[str, Any]] = []
    for effort in efforts:
        for item in evals:
            print(f"[{effort}] query {item.index}: {item.query[:80]}", flush=True)
            results.append(
                run_one(
                    cursor_bin=args.cursor_bin,
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
        title="Cursor Agent Trigger Eval Summary",
        detector=DETECTOR,
        explanatory_lines=[
            "Cursor Agent does not expose a native skill invocation event. This runner uses a",
            "project AGENTS.md shim that lists the temporary skill metadata and body path,",
            "with the sentinel present only inside the temporary skill body. Positive cases",
            "must read that skill body and emit its sentinel; negative cases may read the shim",
            "but must not read the skill body or emit the sentinel.",
        ],
    )
    print(f"Wrote {workspace / 'trigger_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
