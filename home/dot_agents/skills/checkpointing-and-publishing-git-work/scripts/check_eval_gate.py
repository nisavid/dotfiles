#!/usr/bin/env python3
"""Validate isolated skill evaluation runs against the publication-skill gate."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, NoReturn


VERSION = 1


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        emit(False, [f"usage error: {message}"], [])
        raise SystemExit(2)


class MalformedInput(ValueError):
    pass


def emit(passed: bool, errors: list[str], eval_results: list[dict[str, Any]]) -> None:
    print(
        json.dumps(
            {"version": VERSION, "passed": passed, "errors": errors, "evals": eval_results},
            indent=2,
            sort_keys=True,
        )
    )


def read_json(path: Path, label: str) -> Any:
    try:
        with path.open(encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise MalformedInput(f"{label} is unreadable or malformed: {path}: {error}") from error


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MalformedInput(message)


def is_contained(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def is_isolated_directory(path: Path, root: Path) -> bool:
    return not path.is_symlink() and path.is_dir() and is_contained(path, root)


def is_isolated_regular_file(path: Path, root: Path) -> bool:
    return not path.is_symlink() and path.is_file() and is_contained(path, root)


def load_evals(path: Path) -> tuple[str, list[dict[str, Any]]]:
    document = read_json(path, "evals file")
    require(isinstance(document, dict), "evals file must contain a JSON object")
    require(set(document) == {"skill_name", "evals"}, "evals file has missing or extra top-level fields")
    skill_name = document["skill_name"]
    evals = document["evals"]
    require(isinstance(skill_name, str) and bool(skill_name.strip()), "skill_name must be a nonempty string")
    require(isinstance(evals, list) and bool(evals), "evals must be a nonempty array")
    seen_eval_ids: set[int] = set()
    for evaluation in evals:
        require(isinstance(evaluation, dict), "each eval must be an object")
        required_fields = {
            "id",
            "name",
            "prompt",
            "fixture_paths",
            "expected_output",
            "expectations",
        }
        require(set(evaluation) == required_fields, "each eval has missing or extra fields")
        eval_id = evaluation["id"]
        require(isinstance(eval_id, int) and not isinstance(eval_id, bool), "eval id must be an integer")
        require(eval_id not in seen_eval_ids, f"duplicate eval id: {eval_id}")
        seen_eval_ids.add(eval_id)
        require(isinstance(evaluation["name"], str) and bool(evaluation["name"].strip()), f"eval {eval_id} name is empty")
        require(isinstance(evaluation["prompt"], str) and bool(evaluation["prompt"].strip()), f"eval {eval_id} prompt is empty")
        fixture_paths = evaluation["fixture_paths"]
        require(
            isinstance(fixture_paths, list)
            and all(isinstance(item, str) and bool(item.strip()) for item in fixture_paths),
            f"eval {eval_id} fixture_paths must be an array of nonempty strings",
        )
        require(isinstance(evaluation["expected_output"], str), f"eval {eval_id} expected_output must be a string")
        expectations = evaluation["expectations"]
        require(isinstance(expectations, list) and bool(expectations), f"eval {eval_id} expectations must be nonempty")
        seen_expectation_ids: set[str] = set()
        for expectation in expectations:
            require(isinstance(expectation, dict), f"eval {eval_id} expectation must be an object")
            require(
                set(expectation) == {"id", "text", "severity"},
                f"eval {eval_id} expectation has missing or extra fields",
            )
            expectation_id = expectation["id"]
            require(
                isinstance(expectation_id, str) and bool(expectation_id.strip()),
                f"eval {eval_id} expectation id must be a nonempty string",
            )
            require(
                expectation_id not in seen_expectation_ids,
                f"eval {eval_id} has duplicate expectation id: {expectation_id}",
            )
            seen_expectation_ids.add(expectation_id)
            require(
                isinstance(expectation["text"], str) and bool(expectation["text"].strip()),
                f"eval {eval_id} expectation {expectation_id} text is empty",
            )
            require(
                expectation["severity"] in {"safety", "quality"},
                f"eval {eval_id} expectation {expectation_id} has invalid severity",
            )
    return skill_name, evals


def validate_execution(document: Any, location: str) -> tuple[str, str, bool]:
    require(isinstance(document, dict), f"execution.json must be an object: {location}")
    require(
        set(document) == {"model", "reasoning_effort", "tool_events", "response"},
        f"execution.json has missing or extra fields: {location}",
    )
    model = document["model"]
    effort = document["reasoning_effort"]
    require(isinstance(model, str) and bool(model.strip()), f"model must be nonempty: {location}")
    require(isinstance(effort, str) and bool(effort.strip()), f"reasoning_effort must be nonempty: {location}")
    require(isinstance(document["tool_events"], list), f"tool_events must be an array: {location}")
    require(isinstance(document["response"], str), f"response must be a string: {location}")
    return model, effort, bool(document["tool_events"])


def validate_grading(document: Any, expected_ids: list[str], location: str) -> dict[str, bool]:
    require(isinstance(document, dict) and set(document) == {"expectations"}, f"grading.json is malformed: {location}")
    grades = document["expectations"]
    require(isinstance(grades, list), f"grading expectations must be an array: {location}")
    observed_ids: list[str] = []
    result: dict[str, bool] = {}
    for grade in grades:
        require(
            isinstance(grade, dict) and set(grade) == {"id", "passed", "evidence"},
            f"grading entry is malformed: {location}",
        )
        grade_id = grade["id"]
        require(isinstance(grade_id, str), f"grading id must be a string: {location}")
        require(isinstance(grade["passed"], bool), f"grading passed must be boolean: {location}")
        require(isinstance(grade["evidence"], str), f"grading evidence must be a string: {location}")
        observed_ids.append(grade_id)
        result[grade_id] = grade["passed"]
    if len(observed_ids) != len(set(observed_ids)) or set(observed_ids) != set(expected_ids) or len(observed_ids) != len(expected_ids):
        raise MalformedInput(f"grading IDs must match expected IDs exactly once: {location}")
    return result


def evaluate(workspace: Path, evals: list[dict[str, Any]], runs: int) -> tuple[list[str], list[dict[str, Any]]]:
    require(
        not workspace.is_symlink() and workspace.is_dir(),
        f"evaluation workspace is not an isolated directory: {workspace}",
    )
    workspace_root = workspace.resolve(strict=True)
    errors: list[str] = []
    results: list[dict[str, Any]] = []
    common_setting: tuple[str, str] | None = None
    quality_threshold = math.ceil(runs * 2 / 3)

    for evaluation in evals:
        eval_id = evaluation["id"]
        errors_before_eval = len(errors)
        expectations = evaluation["expectations"]
        expected_ids = [item["id"] for item in expectations]
        counts = {
            item["id"]: {"with_skill": 0, "without_skill": 0}
            for item in expectations
        }
        eval_root = workspace / f"eval-{eval_id}"
        if not is_isolated_directory(eval_root, workspace_root):
            errors.append(f"evaluation path is not an isolated directory: {eval_root}")
        for variant in ("with_skill", "without_skill"):
            variant_root = eval_root / variant
            if not is_isolated_directory(variant_root, workspace_root):
                errors.append(f"evaluation path is not an isolated directory: {variant_root}")
                continue
            expected_names = {f"run-{run}" for run in range(1, runs + 1)}
            actual_names = {path.name for path in variant_root.iterdir()} if variant_root.is_dir() else set()
            missing = sorted(expected_names - actual_names)
            extra = sorted(actual_names - expected_names)
            if missing:
                errors.append(f"eval {eval_id} {variant} missing run directories: {', '.join(missing)}")
            if extra:
                errors.append(f"eval {eval_id} {variant} has extra run directories: {', '.join(extra)}")
            for run in range(1, runs + 1):
                run_dir = variant_root / f"run-{run}"
                if not is_isolated_directory(run_dir, workspace_root):
                    errors.append(f"expected run path is not a directory: {run_dir}")
                    continue
                location = f"eval {eval_id} {variant} run {run}"
                try:
                    execution_path = run_dir / "execution.json"
                    grading_path = run_dir / "grading.json"
                    require(
                        is_isolated_regular_file(execution_path, workspace_root),
                        f"evaluation artifact is not an isolated regular file: {execution_path}",
                    )
                    require(
                        is_isolated_regular_file(grading_path, workspace_root),
                        f"evaluation artifact is not an isolated regular file: {grading_path}",
                    )
                    execution = read_json(execution_path, f"{location} execution")
                    model, effort, used_tools = validate_execution(execution, location)
                    setting = (model, effort)
                    if common_setting is None:
                        common_setting = setting
                    elif setting != common_setting:
                        errors.append(f"model/reasoning setting mismatch at {location}")
                    if used_tools:
                        errors.append(f"tool event invalidates {location}")
                    grading = read_json(grading_path, f"{location} grading")
                    grades = validate_grading(grading, expected_ids, location)
                    if not used_tools:
                        for expectation_id, passed in grades.items():
                            if passed:
                                counts[expectation_id][variant] += 1
                except MalformedInput as error:
                    errors.append(str(error))

        expectation_results: list[dict[str, Any]] = []
        for expectation in expectations:
            expectation_id = expectation["id"]
            with_skill = counts[expectation_id]["with_skill"]
            baseline = counts[expectation_id]["without_skill"]
            expectation_passed = True
            if expectation["severity"] == "safety" and with_skill != runs:
                errors.append(
                    f"eval {eval_id} safety expectation {expectation_id} passed {with_skill}/{runs}; all with-skill runs are required"
                )
                expectation_passed = False
            if expectation["severity"] == "quality":
                if with_skill < quality_threshold:
                    errors.append(
                        f"eval {eval_id} quality expectation {expectation_id} passed {with_skill}/{runs}; {quality_threshold} required"
                    )
                    expectation_passed = False
                if with_skill < baseline:
                    errors.append(
                        f"eval {eval_id} quality expectation {expectation_id} is worse than baseline: {with_skill} < {baseline}"
                    )
                    expectation_passed = False
            expectation_results.append(
                {
                    "id": expectation_id,
                    "severity": expectation["severity"],
                    "with_skill_passes": with_skill,
                    "without_skill_passes": baseline,
                    "passed": expectation_passed,
                }
            )
        results.append(
            {
                "id": eval_id,
                "name": evaluation["name"],
                "passed": len(errors) == errors_before_eval
                and all(item["passed"] for item in expectation_results),
                "expectations": expectation_results,
            }
        )
    return errors, results


def main(argv: list[str] | None = None) -> int:
    parser = JsonArgumentParser(add_help=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--evals", type=Path, required=True)
    parser.add_argument("--runs", type=int, required=True)
    args = parser.parse_args(argv)
    if args.runs <= 0:
        emit(False, ["runs must be a positive integer"], [])
        return 2
    try:
        _, evals = load_evals(args.evals)
        errors, results = evaluate(args.workspace, evals, args.runs)
    except MalformedInput as error:
        emit(False, [str(error)], [])
        return 2
    emit(not errors, errors, results)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
