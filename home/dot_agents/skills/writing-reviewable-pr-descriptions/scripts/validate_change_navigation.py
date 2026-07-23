#!/usr/bin/env python3
"""Validate the first-viewport Stack and Diff disclosures in a PR body."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from change_navigation.badges import validate_badges
from change_navigation.diff import touched_file_count, validate_diff
from change_navigation.diff_files import file_operation_counts
from change_navigation.metrics import category_metric_map
from change_navigation.parsing import (
    extract_details,
    extract_leading_details,
    first_nonempty_line,
)
from change_navigation.stack import validate_stack
from change_navigation.stack_inventory import (
    current_item_identity,
    current_item_file_operation_count,
    current_item_file_operations,
    current_item_metrics,
)
from change_navigation.types import classify_disclosures


def validate(body: str, expected_repository: str, expected_pr: int) -> list[str]:
    """Return every change-navigation contract violation in a PR body."""
    errors: list[str] = []
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", expected_repository):
        errors.append("expected repository must use OWNER/REPO")
    if expected_pr < 1:
        errors.append("expected PR number must be positive")
    expected_identity = (expected_repository, expected_pr)
    lines = body.splitlines()
    first = first_nonempty_line(lines)
    if first < 0:
        return ["PR body is empty"]
    if lines[first].strip() != "<details>":
        errors.append("PR body must start with the Stack or Diff disclosure")

    blocks = extract_leading_details(lines)
    labels = classify_disclosures(blocks)
    has_canonical_diff_prefix = bool(
        labels
        and labels[0] == "DIFF"
        and all(label == "UNKNOWN" for label in labels[1:])
    )
    has_canonical_stack_prefix = bool(
        labels[:2] == ["STACK", "DIFF"]
        and all(label == "UNKNOWN" for label in labels[2:])
    )
    if not (has_canonical_diff_prefix or has_canonical_stack_prefix):
        errors.append(
            f"leading disclosure order must be [DIFF] or [STACK, DIFF], found {labels}"
        )
    all_labels = classify_disclosures(extract_details(lines))
    recognized_labels = [label for label in all_labels if label in {"STACK", "DIFF"}]
    expected_labels = ["STACK", "DIFF"] if labels[:1] == ["STACK"] else ["DIFF"]
    if recognized_labels != expected_labels:
        errors.append(
            "Stack and Diff disclosures must appear exactly once in the canonical prefix"
        )
    if "## Stack" in body:
        errors.append("do not add a separate ## Stack section")

    if labels and labels[0] == "STACK":
        validate_stack(blocks[0], errors)
        if len(blocks) < 2:
            errors.append("stacked PR is missing its Diff disclosure")
        else:
            validate_diff(blocks[1], errors, expected_identity)
            stack_metrics = current_item_metrics(blocks[0])
            diff_metrics = category_metric_map("\n".join(blocks[1][:2]))
            if stack_metrics != diff_metrics:
                errors.append(
                    "current Stack item category totals must match the Diff summary"
                )
            stack_files = current_item_file_operation_count(blocks[0])
            diff_files = touched_file_count(blocks[1])
            if (
                stack_files is not None
                and diff_files is not None
                and stack_files != diff_files
            ):
                errors.append(
                    "current Stack item file-operation total must match Diff touched files"
                )
            stack_operations = current_item_file_operations(blocks[0])
            diff_operations = file_operation_counts(blocks[1])
            if stack_operations is not None and diff_operations.consistent:
                ordinary = sum(
                    stack_operations[kind] for kind in ("added", "modified", "removed")
                )
                if (
                    ordinary != diff_operations.ordinary
                    or stack_operations["moved"] != diff_operations.moved
                    or stack_operations["copied"] != diff_operations.copied
                ):
                    errors.append(
                        "current Stack item file-operation kinds must match Diff files"
                    )
        identity = current_item_identity(blocks[0])
        if identity != expected_identity:
            errors.append(
                f"current Stack item must be PR #{expected_pr} in {expected_repository}"
            )
    elif blocks:
        validate_diff(blocks[0], errors, expected_identity)
    else:
        errors.append("Diff disclosure is missing")

    recognized_blocks = blocks[:2] if labels[:2] == ["STACK", "DIFF"] else blocks[:1]
    navigation_text = "\n".join("\n".join(block) for block in recognized_blocks)
    validate_badges(navigation_text, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "body", type=Path, help="Markdown file containing the complete PR body"
    )
    parser.add_argument("--repository", required=True, help="Expected OWNER/REPO")
    parser.add_argument("--pr", required=True, type=int, help="Expected PR number")
    args = parser.parse_args()
    errors = validate(args.body.read_text(encoding="utf-8"), args.repository, args.pr)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Change navigation is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
