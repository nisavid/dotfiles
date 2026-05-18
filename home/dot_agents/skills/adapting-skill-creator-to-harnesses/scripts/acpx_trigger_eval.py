#!/usr/bin/env python3
"""Run ACPX Codex skill trigger evals.

This runner is intentionally separate from ``codex_trigger_eval.py`` because it
measures a different harness path: ACPX launching Codex through ACP. Version 1
supports only the ``acpx-codex`` driver. When v2 begins, remove this note and
replace the fixed driver with a capability-gated harness catalog plus runtime
scouting for skill loading, isolation, permissions, and output compatibility.

The eval remains classification-only. Each counted run uses an isolated HOME,
a locked generated CODEX_HOME, and a temporary probe skill whose body only
emits a sentinel marker. A run is counted as triggered only when Codex reads
the selected temporary skill body and then emits that body's sentinel.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from trigger_eval_core import (
    EFFORTS,
    build_probe_prompt,
    expected_applied_config,
    home_probe_failure_class,
    home_probe_implication,
    load_trigger_evals,
    marker_detection,
    parse_frontmatter,
    skill_body_load_diagnostic,
    slugify,
    source_skill_paths,
    summarize_trigger_results,
    tool_call_diagnostic,
    write_probe_skill,
    write_summary_markdown as write_core_summary_markdown,
)


DRIVER_ID = "acpx-codex"
DETECTOR = "acpx-codex-sentinel"
CODEX_MODE = "read-only"
CODEX_APPROVAL_POLICY = "never"
CODEX_WEB_SEARCH = "disabled"
CODEX_SHELL_TOOL = True
LOCKED_CODEX_CONFIG = f"""sandbox_mode = "{CODEX_MODE}"
approval_policy = "{CODEX_APPROVAL_POLICY}"
web_search = "{CODEX_WEB_SEARCH}"

[features]
shell_tool = {str(CODEX_SHELL_TOOL).lower()}
"""
GLOBAL_SKILL_ROOTS = (
    Path.home() / ".agents" / "skills",
    Path.home() / ".codex" / "skills",
    Path.home() / ".local" / "share" / "chezmoi" / "home" / "dot_agents" / "skills",
)


def parse_json_stream(stdout: str) -> list[Any]:
    stripped = stdout.strip()
    if not stripped:
        return []
    try:
        return [json.loads(stripped)]
    except json.JSONDecodeError:
        pass
    events: list[Any] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _content_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        text: list[str] = []
        for item in value:
            if isinstance(item, str):
                text.append(item)
            elif isinstance(item, dict):
                candidate = item.get("text") or item.get("content")
                if isinstance(candidate, (str, list, dict)):
                    text.extend(_content_text(candidate))
        return text
    if isinstance(value, dict):
        candidate = value.get("text") or value.get("content")
        if isinstance(candidate, (str, list, dict)):
            return _content_text(candidate)
    return []


def _collect_assistant_messages(value: Any) -> list[str]:
    messages: list[str] = []
    if isinstance(value, dict):
        method = value.get("method")
        params = value.get("params")
        if method == "session/update" and isinstance(params, dict):
            update = params.get("update") if isinstance(params.get("update"), dict) else params
            update_type = update.get("sessionUpdate")
            content = update.get("content")
            if update_type in {"agent_message_chunk", "agent_message"}:
                messages.extend(_content_text(content))
        item = value.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            messages.extend(_content_text(item.get("text") or item.get("content")))
        if value.get("type") == "agent_message":
            messages.extend(_content_text(value.get("text") or value.get("content")))
        if value.get("role") == "assistant":
            messages.extend(_content_text(value.get("content") or value.get("text")))
        message = value.get("message")
        if isinstance(message, dict) and message.get("role") == "assistant":
            messages.extend(_content_text(message.get("content") or message.get("text")))
        for child in value.values():
            if isinstance(child, (dict, list)):
                messages.extend(_collect_assistant_messages(child))
    elif isinstance(value, list):
        for child in value:
            messages.extend(_collect_assistant_messages(child))
    return messages


def parse_acpx_output(stdout: str) -> tuple[list[Any], list[str]]:
    events = parse_json_stream(stdout)
    messages: list[str] = []
    chunk_buffer: list[str] = []
    for event in events:
        for message in _collect_assistant_messages(event):
            messages.append(message)
            chunk_buffer.append(message)
    if chunk_buffer:
        messages.append("".join(chunk_buffer))
    return events, messages


def _collect_config_values(value: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    if isinstance(value, dict):
        if isinstance(value.get("id"), str) and isinstance(value.get("currentValue"), str):
            values[value["id"]] = value["currentValue"]
        for child in value.values():
            if isinstance(child, (dict, list)):
                values.update(_collect_config_values(child))
    elif isinstance(value, list):
        for child in value:
            values.update(_collect_config_values(child))
    return values


def parse_config_values(stdout: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for event in parse_json_stream(stdout):
        values.update(_collect_config_values(event))
    return values


def build_base_cmd(
    *,
    acpx_bin: str,
    cwd: Path,
    timeout: int,
    model: str | None,
    strict_json: bool,
) -> list[str]:
    cmd = [
        acpx_bin,
        "--cwd",
        str(cwd),
        "--deny-all",
        "--non-interactive-permissions",
        "fail",
        "--no-terminal",
        "--format",
        "json",
        "--timeout",
        str(timeout),
    ]
    if strict_json:
        cmd.append("--json-strict")
    if model:
        cmd.extend(["--model", model])
    return cmd


def completed_result(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
) -> tuple[int | None, str, str, bool, float]:
    started = time.monotonic()
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
        return completed.returncode, completed.stdout, completed.stderr, False, time.monotonic() - started
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return None, stdout, stderr, True, time.monotonic() - started


def env_for_home(home: Path, codex_home: Path | None) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    if codex_home:
        env["CODEX_HOME"] = str(codex_home)
    env.setdefault("NO_COLOR", "1")
    return env


def render_locked_codex_config(skill_paths: list[Path]) -> str:
    blocks = [LOCKED_CODEX_CONFIG.rstrip()]
    for skill_path in skill_paths:
        blocks.extend(
            [
                "",
                "[[skills.config]]",
                f"path = {json.dumps(str(skill_path))}",
                "enabled = true",
            ]
        )
    return "\n".join(blocks) + "\n"


def write_codex_config(runtime_codex_home: Path, skill_paths: list[Path]) -> str:
    config_text = render_locked_codex_config(skill_paths)
    (runtime_codex_home / "config.toml").write_text(config_text, encoding="utf-8")
    return config_text


def write_locked_codex_home(runtime_codex_home: Path, source_codex_home: Path | None) -> dict[str, Any]:
    runtime_codex_home.mkdir(parents=True, exist_ok=True)
    config_path = runtime_codex_home / "config.toml"
    config_text = write_codex_config(runtime_codex_home, [])
    auth_source_present = False
    auth_linked = False
    if source_codex_home:
        auth_source = source_codex_home / "auth.json"
        auth_target = runtime_codex_home / "auth.json"
        auth_source_present = auth_source.exists()
        if auth_source_present:
            if auth_target.exists() or auth_target.is_symlink():
                auth_target.unlink()
            auth_target.symlink_to(auth_source)
            auth_linked = True
    return {
        "runtime_path": str(runtime_codex_home),
        "source_path": str(source_codex_home) if source_codex_home else None,
        "config_path": str(config_path),
        "config": config_text,
        "auth_source_present": auth_source_present,
        "auth_linked": auth_linked,
    }


def mirror_agent_skills_to_codex_home(home: Path, runtime_codex_home: Path) -> list[str]:
    source_root = home / ".agents" / "skills"
    target_root = runtime_codex_home / "skills"
    mirrored: list[str] = []
    if not source_root.exists():
        return mirrored
    target_root.mkdir(parents=True, exist_ok=True)
    for source_skill in sorted(source_root.iterdir()):
        if not (source_skill / "SKILL.md").is_file():
            continue
        target_skill = target_root / source_skill.name
        shutil.copytree(source_skill, target_skill, dirs_exist_ok=True)
        mirrored.append(str(target_skill / "SKILL.md"))
    return mirrored


def remove_runtime_auth(runtime_codex_home: Path) -> None:
    auth_target = runtime_codex_home / "auth.json"
    if auth_target.is_symlink():
        auth_target.unlink()


def run_prompt(
    *,
    acpx_bin: str,
    home: Path,
    codex_home: Path | None,
    cwd: Path,
    prompt: str,
    timeout: int,
    model: str | None,
    effort: str | None,
    strict_json: bool,
) -> dict[str, Any]:
    runtime_codex_home = home / ".codex"
    codex_home_metadata = write_locked_codex_home(runtime_codex_home, codex_home)
    mirrored_skill_paths = mirror_agent_skills_to_codex_home(home, runtime_codex_home)
    configured_skill_paths = [Path(path) for path in mirrored_skill_paths]
    source_paths = source_skill_paths(home)
    allowed_skill_body_paths = sorted(set(source_paths + mirrored_skill_paths))
    codex_home_metadata["source_skill_paths"] = source_paths
    codex_home_metadata["mirrored_skill_paths"] = mirrored_skill_paths
    codex_home_metadata["configured_skill_paths"] = [str(path) for path in configured_skill_paths]
    codex_home_metadata["allowed_skill_body_paths"] = allowed_skill_body_paths
    codex_home_metadata["config"] = write_codex_config(runtime_codex_home, configured_skill_paths)
    env = env_for_home(home, runtime_codex_home)
    base_cmd = build_base_cmd(
        acpx_bin=acpx_bin,
        cwd=cwd,
        timeout=timeout,
        model=model,
        strict_json=strict_json,
    )
    setup_commands: list[dict[str, Any]] = []
    applied_config_values: dict[str, str] = {}
    session_name = f"trigger-{uuid.uuid4().hex[:12]}"

    setup_steps = [base_cmd + ["codex", "sessions", "new", "--name", session_name]]
    if effort:
        setup_steps.append(base_cmd + ["codex", "set", "reasoning_effort", effort, "-s", session_name])
    for setup_cmd in setup_steps:
        returncode, stdout, stderr, timed_out, duration = completed_result(
            setup_cmd,
            cwd=cwd,
            env=env,
            timeout=timeout,
        )
        setup_config_values = parse_config_values(stdout)
        applied_config_values.update(setup_config_values)
        setup_commands.append(
            {
                "command": setup_cmd,
                "returncode": returncode,
                "stdout": stdout,
                "stderr": stderr,
                "timed_out": timed_out,
                "duration_seconds": round(duration, 3),
                "config_values": setup_config_values,
            }
        )
        if returncode != 0 or timed_out:
            result = {
                "command": setup_cmd,
                "setup_commands": setup_commands,
                "returncode": returncode,
                "stdout": stdout,
                "stderr": stderr,
                "timed_out": timed_out,
                "duration_seconds": round(duration, 3),
                "setup_failed": True,
                "messages": [],
                "events": [],
                "tool_calls": tool_call_diagnostic([], allowed_skill_body_paths),
                "applied_config_values": applied_config_values,
                "codex_home": codex_home_metadata,
            }
            remove_runtime_auth(runtime_codex_home)
            return result
    cmd = base_cmd + ["codex", "prompt", "-s", session_name, prompt]

    returncode, stdout, stderr, timed_out, duration = completed_result(
        cmd,
        cwd=cwd,
        env=env,
        timeout=timeout,
    )
    events, messages = parse_acpx_output(stdout)
    applied_config_values.update(parse_config_values(stdout))
    close_cmd = base_cmd + ["codex", "sessions", "close", session_name]
    close_result: dict[str, Any] | None = None
    if effort:
        close_returncode, close_stdout, close_stderr, close_timed_out, close_duration = completed_result(
            close_cmd,
            cwd=cwd,
            env=env,
            timeout=min(timeout, 10),
        )
        close_result = {
            "command": close_cmd,
            "returncode": close_returncode,
            "stdout": close_stdout,
            "stderr": close_stderr,
            "timed_out": close_timed_out,
            "duration_seconds": round(close_duration, 3),
        }
    remove_runtime_auth(runtime_codex_home)
    return {
        "command": cmd,
        "setup_commands": setup_commands,
        "close_command": close_result,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "duration_seconds": round(duration, 3),
        "setup_failed": False,
        "messages": messages,
        "events": events,
        "tool_calls": tool_call_diagnostic(events, allowed_skill_body_paths),
        "applied_config_values": applied_config_values,
        "codex_home": codex_home_metadata,
    }


def check_acpx_binary(acpx_bin: str, timeout: int) -> dict[str, Any]:
    resolved = shutil.which(acpx_bin)
    result: dict[str, Any] = {
        "name": "acpx_binary",
        "ok": bool(resolved),
        "binary": acpx_bin,
        "resolved": resolved,
    }
    if not resolved:
        result["reason"] = f"{acpx_bin!r} was not found on PATH"
        return result
    for args in (["--version"], ["--help"]):
        cmd = [resolved, *args]
        returncode, stdout, stderr, timed_out, duration = completed_result(
            cmd,
            cwd=Path.cwd(),
            env=os.environ.copy(),
            timeout=timeout,
        )
        if returncode == 0 and not timed_out:
            result.update(
                {
                    "version_command": cmd,
                    "version_output": (stdout or stderr).strip().splitlines()[:5],
                    "duration_seconds": round(duration, 3),
                }
            )
            return result
    result["ok"] = False
    result["reason"] = f"{acpx_bin!r} exists but neither --version nor --help succeeded"
    return result


def run_home_probe(
    *,
    acpx_bin: str,
    workspace: Path,
    skill_name: str,
    description: str,
    timeout: int,
    model: str | None,
    effort: str | None,
    strict_json: bool,
    codex_home: Path | None,
) -> dict[str, Any]:
    probe_dir = workspace / "preflight-home-probe"
    home = probe_dir / "home"
    cwd = probe_dir / "cwd"
    cwd.mkdir(parents=True, exist_ok=True)
    marker = f"ACPX_PREFLIGHT_{skill_name}_{uuid.uuid4().hex[:12]}"
    write_probe_skill(
        home,
        name=skill_name,
        description=description,
        marker=marker,
        harness_label="ACPX",
    )
    prompt = build_probe_prompt(
        "Get this merged and close out the PR when the gates pass.",
        allow_skill_body_read_command=True,
    )
    run = run_prompt(
        acpx_bin=acpx_bin,
        home=home,
        codex_home=codex_home,
        cwd=cwd,
        prompt=prompt,
        timeout=timeout,
        model=model,
        effort=effort,
        strict_json=strict_json,
    )
    detection = marker_detection(run["messages"], marker, skill_name)
    body_load = skill_body_load_diagnostic(run["messages"], skill_name)
    failure_class = home_probe_failure_class(detection, body_load)
    tool_calls = run["tool_calls"]
    tool_contract_ok = tool_calls["allowed_skill_read_count"] > 0 and tool_calls["disallowed_count"] == 0
    if failure_class is None and not tool_contract_ok:
        if tool_calls["disallowed_count"]:
            failure_class = "unexpected_tool_calls"
        else:
            failure_class = "skill_body_not_read_by_allowed_tool"
    applied_config, unsupported_config = expected_applied_config(
        requested_model=model,
        requested_effort=effort,
        observed_values=run["applied_config_values"],
    )
    ok = (
        run["returncode"] == 0
        and not run["timed_out"]
        and not run["setup_failed"]
        and detection["sentinel_present_anywhere"]
        and tool_contract_ok
        and not unsupported_config
    )
    return {
        "name": "isolated_home_probe",
        "ok": ok,
        "marker": marker,
        "run_dir": str(probe_dir),
        "returncode": run["returncode"],
        "timed_out": run["timed_out"],
        "setup_failed": run["setup_failed"],
        "detection": detection,
        "body_load": body_load,
        "tool_calls": tool_calls,
        "tool_contract_ok": tool_contract_ok,
        "failure_class": failure_class,
        "implication": home_probe_implication(failure_class),
        "applied_config": applied_config,
        "unsupported_config": unsupported_config,
        "observed_config_values": run["applied_config_values"],
        "codex_home": run["codex_home"],
        "stderr": run["stderr"],
        "command": run["command"],
        "setup_commands": run["setup_commands"],
    }


def run_shell_command_capability_probe(
    *,
    acpx_bin: str,
    workspace: Path,
    timeout: int,
    model: str | None,
    effort: str | None,
    strict_json: bool,
    codex_home: Path | None,
) -> dict[str, Any]:
    probe_dir = workspace / "preflight-shell-command-probe"
    home = probe_dir / "home"
    cwd = probe_dir / "cwd"
    cwd.mkdir(parents=True, exist_ok=True)
    prompt = "\n".join(
        [
            "This is a command-capability preflight.",
            "Attempt to run `pwd` using a terminal or command tool.",
            "If the command tool is unavailable, answer exactly: NO_SHELL_TOOL",
            "If the command is denied by policy, answer exactly: TOOL_DENIED",
        ]
    )
    run = run_prompt(
        acpx_bin=acpx_bin,
        home=home,
        codex_home=codex_home,
        cwd=cwd,
        prompt=prompt,
        timeout=timeout,
        model=model,
        effort=effort,
        strict_json=strict_json,
    )
    joined_messages = "\n".join(run["messages"])
    shell_command_executed = str(cwd) in joined_messages
    denied_signal = (
        "NO_SHELL_TOOL" in joined_messages
        or "TOOL_DENIED" in joined_messages
        or "tool unavailable" in joined_messages.lower()
        or "PERMISSION" in run["stderr"].upper()
        or "permission" in joined_messages.lower()
        or "cannot run" in joined_messages.lower()
        or "can't run" in joined_messages.lower()
        or "unable to run" in joined_messages.lower()
    )
    no_successful_tool_text = str(cwd) not in joined_messages
    applied_config, unsupported_config = expected_applied_config(
        requested_model=model,
        requested_effort=effort,
        observed_values=run["applied_config_values"],
    )
    observation_collected = denied_signal or shell_command_executed
    return {
        "name": "shell_command_capability_probe",
        "ok": bool(
            observation_collected
            and not run["setup_failed"]
            and not run["timed_out"]
            and not unsupported_config
        ),
        "required": False,
        "run_dir": str(probe_dir),
        "returncode": run["returncode"],
        "timed_out": run["timed_out"],
        "setup_failed": run["setup_failed"],
        "denied_signal": denied_signal,
        "shell_command_executed": shell_command_executed,
        "no_successful_tool_text": no_successful_tool_text,
        "implication": (
            "ACPX-launched Codex needs the shell tool to read SKILL.md bodies. In this "
            "configuration, read-only shell commands can execute, so the runner enforces "
            "per-result tool-call limits instead of claiming no-tool isolation."
            if shell_command_executed
            else "The shell command was unavailable or denied in this harness run."
        ),
        "applied_config": applied_config,
        "unsupported_config": unsupported_config,
        "observed_config_values": run["applied_config_values"],
        "codex_home": run["codex_home"],
        "messages": run["messages"],
        "stderr": run["stderr"],
        "command": run["command"],
        "setup_commands": run["setup_commands"],
    }


def run_optional_file_trace_probe() -> dict[str, Any]:
    strace = shutil.which("strace")
    return {
        "name": "global_skill_root_file_trace",
        "ok": strace is not None,
        "required": False,
        "tool": strace,
        "checked_roots": [str(path) for path in GLOBAL_SKILL_ROOTS],
        "reason": None if strace else "strace is not installed; exact file-access proof was not collected",
    }


def run_preflight(
    *,
    acpx_bin: str,
    workspace: Path,
    skill_name: str,
    description: str,
    timeout: int,
    model: str | None,
    effort: str | None,
    strict_json: bool,
    codex_home: Path | None,
    require_file_trace: bool,
) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []
    binary_check = check_acpx_binary(acpx_bin, timeout=min(timeout, 10))
    checks.append(binary_check)
    if not binary_check["ok"]:
        return {
            "ok": False,
            "driver_id": DRIVER_ID,
            "checks": checks,
            "unsupported_reason": binary_check["reason"],
        }

    checks.append(
        run_home_probe(
            acpx_bin=acpx_bin,
            workspace=workspace,
            skill_name=skill_name,
            description=description,
            timeout=timeout,
            model=model,
            effort=effort,
            strict_json=strict_json,
            codex_home=codex_home,
        )
    )
    checks.append(
        run_shell_command_capability_probe(
            acpx_bin=acpx_bin,
            workspace=workspace,
            timeout=timeout,
            model=model,
            effort=effort,
            strict_json=strict_json,
            codex_home=codex_home,
        )
    )
    trace_check = run_optional_file_trace_probe()
    if require_file_trace:
        trace_check["required"] = True
    checks.append(trace_check)
    required_checks = [check for check in checks if check.get("required", True)]
    ok = all(check.get("ok") for check in required_checks)
    unsupported_reason = None
    if not ok:
        failed = []
        for check in required_checks:
            if check.get("ok"):
                continue
            failure_class = check.get("failure_class")
            failed.append(f"{check['name']}:{failure_class}" if failure_class else check["name"])
        unsupported_reason = "preflight checks failed: " + ", ".join(failed)
    return {
        "ok": ok,
        "driver_id": DRIVER_ID,
        "checks": checks,
        "unsupported_reason": unsupported_reason,
    }


def run_one(
    *,
    acpx_bin: str,
    codex_home: Path | None,
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
    strict_json: bool,
    preflight: dict[str, Any],
) -> dict[str, Any]:
    effort_label = effort or "default"
    run_slug = f"{query_index:02d}-{slugify(query)[:56]}"
    run_dir = workspace / effort_label / run_slug
    run_dir.mkdir(parents=True, exist_ok=True)
    home = run_dir / "home"
    cwd = run_dir / "cwd"
    cwd.mkdir(parents=True, exist_ok=True)
    marker = f"ACPX_TRIGGERED_{skill_name}_{effort_label}_{query_index}_{uuid.uuid4().hex[:12]}"
    write_probe_skill(
        home,
        name=skill_name,
        description=description,
        marker=marker,
        harness_label="ACPX",
    )
    probe_prompt = build_probe_prompt(query, allow_skill_body_read_command=True)
    requested_config = {
        "model": model,
        "reasoning_effort": effort,
        "codex_sandbox_mode": CODEX_MODE,
        "codex_approval_policy": CODEX_APPROVAL_POLICY,
        "codex_web_search": CODEX_WEB_SEARCH,
        "codex_shell_tool": CODEX_SHELL_TOOL,
        "acpx_permission_mode": "deny-all",
        "acpx_terminal": False,
        "format": "json",
        "json_strict": strict_json,
    }
    (run_dir / "query.json").write_text(
        json.dumps(
            {
                "query": query,
                "effort": effort,
                "requested_config": requested_config,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    run = run_prompt(
        acpx_bin=acpx_bin,
        home=home,
        codex_home=codex_home,
        cwd=cwd,
        prompt=probe_prompt,
        timeout=timeout,
        model=model,
        effort=effort,
        strict_json=strict_json,
    )
    (run_dir / "stdout.jsonl").write_text(run["stdout"], encoding="utf-8")
    (run_dir / "stderr.log").write_text(run["stderr"], encoding="utf-8")
    detection = marker_detection(run["messages"], marker, skill_name)
    applied_config, unsupported_config = expected_applied_config(
        requested_model=model,
        requested_effort=effort,
        observed_values=run["applied_config_values"],
    )
    triggered = detection["sentinel_present_anywhere"]
    tool_calls = run["tool_calls"]
    tool_contract_ok = (
        tool_calls["disallowed_count"] == 0
        and (
            tool_calls["allowed_skill_read_count"] > 0
            if should_trigger
            else tool_calls["total"] == 0
        )
    )
    passed = (
        triggered == should_trigger
        and run["returncode"] == 0
        and not run["timed_out"]
        and not unsupported_config
        and tool_contract_ok
    )
    raw_events_path = run_dir / "events.json"
    raw_events_path.write_text(json.dumps(run["events"], indent=2) + "\n", encoding="utf-8")

    result = {
        "query_index": query_index,
        "query": query,
        "probe_prompt": probe_prompt,
        "should_trigger": should_trigger,
        "triggered": triggered,
        "passed": passed,
        "effort": effort,
        "runner": "acpx",
        "driver_id": DRIVER_ID,
        "detector": DETECTOR,
        "returncode": run["returncode"],
        "timed_out": run["timed_out"],
        "duration_seconds": run["duration_seconds"],
        "requested_config": requested_config,
        "applied_config": applied_config,
        "observed_config_values": run["applied_config_values"],
        "unsupported_config": unsupported_config,
        "codex_home": run["codex_home"],
        "preflight": {
            "ok": preflight["ok"],
            "unsupported_reason": preflight.get("unsupported_reason"),
        },
        "marker": marker,
        "messages": run["messages"],
        "detection": detection,
        "tool_calls": tool_calls,
        "tool_contract_ok": tool_contract_ok,
        "event_count": len(run["events"]),
        "raw_events_path": str(raw_events_path),
        "run_dir": str(run_dir),
        "command": run["command"],
        "setup_commands": run["setup_commands"],
        "close_command": run["close_command"],
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not keep_home:
        shutil.rmtree(home, ignore_errors=True)
    return result


def write_unsupported(workspace: Path, skill_name: str, preflight: dict[str, Any]) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    summary = {
        "skill_name": skill_name,
        "runner": "acpx",
        "driver_id": DRIVER_ID,
        "detector": DETECTOR,
        "preflight": preflight,
        "unsupported_reason": preflight.get("unsupported_reason"),
        "efforts": {},
        "results": [],
    }
    (workspace / "trigger_results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# ACPX Codex Trigger Eval Summary: {skill_name}",
        "",
        f"Driver: `{DRIVER_ID}`.",
        "Preflight: `failed`.",
        f"Unsupported reason: {preflight.get('unsupported_reason') or 'unknown'}.",
        "",
        "No trigger eval results were counted.",
        "",
    ]
    failed_checks = [check for check in preflight.get("checks", []) if check.get("required", True) and not check.get("ok")]
    if failed_checks:
        lines.extend(["Failed required checks:", ""])
        for check in failed_checks:
            detail = check.get("failure_class") or check.get("reason") or "failed"
            lines.append(f"- `{check.get('name', 'unknown')}`: {detail}.")
            if check.get("implication"):
                lines.append(f"  {check['implication']}")
        lines.append("")
    (workspace / "trigger_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ACPX Codex trigger evals")
    parser.add_argument("--skill-dir", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--acpx-bin", default="acpx")
    parser.add_argument(
        "--codex-home",
        type=Path,
        help="Source Codex home to borrow auth.json from; runtime config is generated and locked per run.",
    )
    parser.add_argument("--model")
    parser.add_argument("--effort", action="append", choices=EFFORTS)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--index", type=int, action="append", help="Run only the specified trigger eval index; repeatable")
    parser.add_argument("--keep-probe-homes", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--require-file-trace", action="store_true")
    parser.add_argument("--no-json-strict", action="store_true")
    args = parser.parse_args()

    skill_dir = args.skill_dir.resolve()
    workspace = args.workspace.resolve()
    codex_home = args.codex_home.resolve() if args.codex_home else None
    frontmatter = parse_frontmatter(skill_dir / "SKILL.md")
    strict_json = not args.no_json_strict
    efforts = args.effort or ["medium"]

    preflight = run_preflight(
        acpx_bin=args.acpx_bin,
        workspace=workspace / "preflight",
        skill_name=frontmatter["name"],
        description=frontmatter["description"],
        timeout=args.timeout,
        model=args.model,
        effort=efforts[0] if efforts else None,
        strict_json=strict_json,
        codex_home=codex_home,
        require_file_trace=args.require_file_trace,
    )
    (workspace / "preflight.json").write_text(json.dumps(preflight, indent=2) + "\n", encoding="utf-8")
    if args.preflight_only:
        if not preflight["ok"]:
            write_unsupported(workspace, frontmatter["name"], preflight)
            print(preflight.get("unsupported_reason") or "preflight failed", file=sys.stderr)
            return 1
        print(f"Preflight passed for {DRIVER_ID}")
        return 0
    if not preflight["ok"]:
        write_unsupported(workspace, frontmatter["name"], preflight)
        print(preflight.get("unsupported_reason") or "preflight failed", file=sys.stderr)
        return 1

    evals = load_trigger_evals(skill_dir, args.index, args.limit)

    workspace.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for effort in efforts:
        for item in evals:
            print(f"[{effort}] query {item.index}: {item.query[:80]}", flush=True)
            result = run_one(
                acpx_bin=args.acpx_bin,
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
                keep_home=args.keep_probe_homes,
                strict_json=strict_json,
                preflight=preflight,
            )
            results.append(result)

    summary = summarize_trigger_results(
        results=results,
        skill_name=frontmatter["name"],
        runner="acpx",
        driver_id=DRIVER_ID,
        detector=DETECTOR,
        preflight=preflight,
    )
    (workspace / "trigger_results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_core_summary_markdown(
        summary,
        workspace / "trigger_summary.md",
        title="ACPX Codex Trigger Eval Summary",
        detector=DETECTOR,
        explanatory_lines=[
            "This measures whether ACPX-launched Codex loads the temporary skill body and",
            "emits that body's unique sentinel. Positive cases must read only the selected",
            "temporary SKILL.md before emitting the sentinel; negative cases must make no",
            "tool calls and must not emit the sentinel. Exact marker-only output is recorded",
            "as a diagnostic, but ACPX/Codex may add a skill-selection preamble.",
        ],
    )
    print(f"Wrote {workspace / 'trigger_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
