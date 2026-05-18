#!/usr/bin/env python3
"""Shared core for skill trigger eval harness runners."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


EFFORTS = ("low", "medium", "high", "xhigh")


@dataclass(frozen=True)
class TriggerEvalCase:
    index: int
    query: str
    should_trigger: bool


@dataclass(frozen=True)
class HarnessCapabilities:
    harness_id: str
    isolated_home: bool
    isolated_workspace: bool
    skill_body_load_proof: str
    tool_call_observability: str
    can_apply_reasoning_effort: bool
    notes: tuple[str, ...] = ()


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


def write_probe_skill(
    home: Path,
    *,
    name: str,
    description: str,
    marker: str,
    harness_label: str,
) -> Path:
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
                f"# {harness_label} Trigger Probe",
                "",
                f"This temporary skill is used only by {harness_label} trigger eval tooling.",
                "",
                "If this skill is loaded for the user's request, the final answer must be",
                f"exactly `{marker}` and nothing else. Do not run commands, inspect files,",
                "or continue the underlying workflow.",
                "",
                "Do not explain why the skill matched. Do not add a preamble, suffix,",
                "markdown, punctuation, or any other text.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return skill_md


def build_probe_prompt(query: str, *, allow_skill_body_read_command: bool) -> str:
    command_rule = (
        "Do not run commands except whatever Codex requires to read the selected temporary SKILL.md."
        if allow_skill_body_read_command
        else "Do not run commands, inspect files, call external tools, access GitHub, or mutate any state."
    )
    lines = [
        "Request to classify for skill triggering:",
        query,
        "",
        "This is a trigger-selection probe, not a request to perform the task.",
        command_rule,
    ]
    if allow_skill_body_read_command:
        lines.append("Do not inspect other files, call external tools, access GitHub, or mutate any state.")
    lines.extend(
        [
            "Do not use any skill merely because this is a probe or because a temporary skill exists.",
            "Use the temporary skill only when its description matches the request text above.",
            "If an available temporary skill applies to the request above, load and use that skill now,",
            "then follow its SKILL.md instructions exactly and stop. Do not answer from the skill name",
            "or description alone; the triggered answer is defined only inside the loaded skill body.",
            "Do not explain whether or why a skill applies.",
            "If no temporary skill is loaded, answer exactly: SKILL_NOT_TRIGGERED",
        ]
    )
    return "\n".join(lines)


def normalized_marker_text(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        value = value[1:-1].strip()
    return value


def strip_allowed_skill_preamble(message: str, skill_name: str) -> str:
    return re.sub(
        rf"^Using\s+`{re.escape(skill_name)}`\s+for\s+this\s+request\.\s*",
        "",
        message,
    )


def marker_detection(messages: list[str], marker: str, skill_name: str) -> dict[str, Any]:
    raw_normalized_messages = [normalized_marker_text(message) for message in messages]
    normalized_messages = [
        strip_allowed_skill_preamble(message, skill_name) for message in raw_normalized_messages
    ]
    return {
        "sentinel_exact_match": any(message == marker for message in normalized_messages),
        "sentinel_present_anywhere": any(marker in message for message in messages),
        "allowed_skill_preamble_stripped": raw_normalized_messages != normalized_messages,
        "raw_normalized_messages": raw_normalized_messages,
        "normalized_messages": normalized_messages,
    }


def source_skill_paths(home: Path) -> list[str]:
    source_root = home / ".agents" / "skills"
    if not source_root.exists():
        return []
    return [
        str(skill_path)
        for skill_path in sorted(source_root.glob("*/SKILL.md"))
        if skill_path.is_file()
    ]


def collect_tool_calls(value: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    if isinstance(value, dict):
        update = None
        params = value.get("params")
        if isinstance(params, dict) and isinstance(params.get("update"), dict):
            update = params["update"]
        if update and update.get("sessionUpdate") == "tool_call":
            calls.append(update)
        for child in value.values():
            if isinstance(child, (dict, list)):
                calls.extend(collect_tool_calls(child))
    elif isinstance(value, list):
        for child in value:
            calls.extend(collect_tool_calls(child))
    return calls


def tool_call_paths(call: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for location in call.get("locations") or []:
        if isinstance(location, dict) and isinstance(location.get("path"), str):
            paths.append(location["path"])
    raw_input = call.get("rawInput")
    if isinstance(raw_input, dict):
        for parsed_cmd in raw_input.get("parsed_cmd") or []:
            if isinstance(parsed_cmd, dict) and isinstance(parsed_cmd.get("path"), str):
                paths.append(parsed_cmd["path"])
    return sorted(set(paths))


def tool_call_diagnostic(events: list[Any], allowed_skill_paths: list[str]) -> dict[str, Any]:
    allowed = {str(Path(path)) for path in allowed_skill_paths}
    calls = collect_tool_calls(events)
    allowed_reads: list[dict[str, Any]] = []
    disallowed: list[dict[str, Any]] = []
    for call in calls:
        paths = tool_call_paths(call)
        raw_input = call.get("rawInput") if isinstance(call.get("rawInput"), dict) else {}
        parsed_cmds = raw_input.get("parsed_cmd") if isinstance(raw_input, dict) else []
        parsed_types = [
            parsed.get("type")
            for parsed in parsed_cmds or []
            if isinstance(parsed, dict) and isinstance(parsed.get("type"), str)
        ]
        is_allowed_read = (
            call.get("kind") == "read"
            and paths
            and all(path in allowed for path in paths)
            and (not parsed_types or all(kind == "read" for kind in parsed_types))
        )
        item = {
            "title": call.get("title"),
            "kind": call.get("kind"),
            "paths": paths,
            "parsed_types": parsed_types,
        }
        if is_allowed_read:
            allowed_reads.append(item)
        else:
            disallowed.append(item)
    return {
        "total": len(calls),
        "allowed_skill_read_count": len(allowed_reads),
        "allowed_skill_reads": allowed_reads,
        "disallowed_count": len(disallowed),
        "disallowed": disallowed,
    }


def expected_applied_config(
    *,
    requested_model: str | None,
    requested_effort: str | None,
    observed_values: dict[str, str],
) -> tuple[dict[str, str], list[str]]:
    applied: dict[str, str] = {}
    unsupported: list[str] = []
    if requested_model:
        observed_model = observed_values.get("model")
        if observed_model == requested_model:
            applied["model"] = observed_model
        else:
            unsupported.append("model")
    if requested_effort:
        observed_effort = observed_values.get("reasoning_effort") or observed_values.get("thought_level")
        if observed_effort == requested_effort:
            applied["reasoning_effort"] = observed_effort
        else:
            unsupported.append("reasoning_effort")
    return applied, unsupported


def skill_body_load_diagnostic(messages: list[str], skill_name: str) -> dict[str, Any]:
    joined = "".join(messages)
    skill_quoted = f"`{skill_name}`" in joined
    body_unavailable = (
        ("can't load" in joined or "cannot load" in joined or "unable to load" in joined)
        and ("skill body" in joined or "SKILL.md" in joined or "file-read tool" in joined)
    )
    return {
        "metadata_selected": skill_quoted,
        "body_unavailable": body_unavailable,
    }


def home_probe_failure_class(detection: dict[str, Any], body_load: dict[str, Any]) -> str | None:
    if detection["sentinel_present_anywhere"]:
        return None
    if body_load["metadata_selected"] and body_load["body_unavailable"]:
        return "skill_metadata_selected_but_body_unavailable"
    return "skill_not_loaded_or_body_not_followed"


def home_probe_implication(failure_class: str | None) -> str | None:
    if failure_class is None:
        return None
    if failure_class == "skill_metadata_selected_but_body_unavailable":
        return (
            "Codex recognized the skill metadata, but it did not read the temporary SKILL.md body. "
            "The runner cannot count this as proof that the skill would execute."
        )
    if failure_class == "unexpected_tool_calls":
        return (
            "Codex used tool calls outside the selected temporary SKILL.md read. The runner "
            "cannot count that as an isolated trigger-classification run."
        )
    if failure_class == "skill_body_not_read_by_allowed_tool":
        return (
            "Codex emitted the marker without a recorded read of the selected temporary SKILL.md. "
            "The runner cannot count that as proof that the skill body was loaded."
        )
    return (
        "Codex did not emit the unique marker from the temporary SKILL.md body. The runner cannot "
        "count this as proof that the skill loaded and followed its instructions."
    )


def load_trigger_evals(skill_dir: Path, indexes: list[int] | None, limit: int | None) -> list[TriggerEvalCase]:
    raw_cases = json.loads(read_text(skill_dir / "evals" / "trigger-evals.json"))
    indexed = [
        TriggerEvalCase(index=index, query=item["query"], should_trigger=bool(item["should_trigger"]))
        for index, item in enumerate(raw_cases)
    ]
    if indexes:
        requested = set(indexes)
        indexed = [case for case in indexed if case.index in requested]
    if limit is not None:
        indexed = indexed[:limit]
    return indexed


def summarize_trigger_results(
    *,
    results: list[dict[str, Any]],
    skill_name: str,
    runner: str | None,
    driver_id: str | None,
    detector: str,
    preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    by_effort: dict[str, dict[str, Any]] = {}
    efforts = sorted({item["effort"] or "default" for item in results})
    for effort in efforts:
        effort_results = [item for item in results if (item["effort"] or "default") == effort]
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
    summary: dict[str, Any] = {
        "skill_name": skill_name,
        "detector": detector,
        "efforts": by_effort,
        "results": results,
    }
    if runner is not None:
        summary["runner"] = runner
    if driver_id is not None:
        summary["driver_id"] = driver_id
    if preflight is not None:
        summary["preflight"] = preflight
    return summary


def write_summary_markdown(
    summary: dict[str, Any],
    output: Path,
    *,
    title: str,
    detector: str,
    explanatory_lines: list[str],
) -> None:
    lines = [
        f"# {title}: {summary['skill_name']}",
        "",
    ]
    if summary.get("driver_id"):
        lines.append(f"Driver: `{summary['driver_id']}`.")
    lines.append(f"Detector: `{detector}`.")
    if "preflight" in summary:
        lines.append(f"Preflight: `{'passed' if summary['preflight']['ok'] else 'failed'}`.")
    lines.extend(
        [
            "",
            "| Effort | Passed | Pass Rate | TP Rate | False Positives | False Negatives | Mean Seconds | Failed Query Indices |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
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
    lines.append("")
    lines.extend(explanatory_lines)
    lines.append("")
    capability_notes = [
        check
        for check in summary.get("preflight", {}).get("checks", [])
        if not check.get("required", True) and check.get("implication")
    ]
    if capability_notes:
        lines.extend(["Harness capability notes:", ""])
        for check in capability_notes:
            lines.append(f"- `{check.get('name', 'unknown')}`: {check['implication']}")
        lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")
