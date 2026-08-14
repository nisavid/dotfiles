"""Validate Diff disclosure semantics."""

from __future__ import annotations

import re

from .diff_files import is_bounded_inventory, validate_diff_file_items
from .diff_inventory import INVENTORY_LIMIT
from .diff_metrics import Identity
from .metrics import category_metric_items, category_metric_map
from .parsing import summary
from .types import validate_category_order


def validate_diff(
    block: list[str],
    errors: list[str],
    expected_identity: Identity | None = None,
    expected_comparison: tuple[str, str] | None = None,
) -> None:
    diff_summary = summary(block, errors, "Diff")
    if 'alt="DIFF"' not in diff_summary:
        errors.append(
            "Diff disclosure must follow Stack, or be first for an unstacked PR"
        )
    if not re.match(
        r'^<summary><picture><img alt="DIFF"[^>]*></picture>&nbsp;', diff_summary
    ):
        errors.append("Diff summary must use a non-breaking gap after its label")
    if diff_summary.count("&nbsp;") != 1:
        errors.append("Diff summary must use exactly one non-breaking label gap")
    files_match = re.search(r'alt="FILES: (\d+) touched"', diff_summary)
    if not files_match:
        errors.append("Diff summary needs a touched-files badge")
    bounded = is_bounded_inventory(block)
    validate_category_order(diff_summary, errors, "Diff summary")
    metric_items = category_metric_items(diff_summary)
    if len(metric_items) != len(dict(metric_items)):
        errors.append("Diff summary must not repeat a category metric")
    summary_metrics = category_metric_map(diff_summary)
    expected_files = int(files_match.group(1)) if files_match else None
    if expected_files is not None and expected_files > INVENTORY_LIMIT and not bounded:
        errors.append(
            f"Diffs with more than {INVENTORY_LIMIT} touched files must use a "
            "bounded expansion"
        )
    shown_files = INVENTORY_LIMIT if bounded else None
    validate_diff_file_items(
        block,
        errors,
        expected_files,
        summary_metrics,
        expected_identity,
        shown_files,
        expected_comparison,
    )


def touched_file_count(block: list[str]) -> int | None:
    diff_summary = next((line for line in block if "<summary>" in line), "")
    match = re.search(r'alt="FILES: (\d+) touched"', diff_summary)
    return int(match.group(1)) if match else None
