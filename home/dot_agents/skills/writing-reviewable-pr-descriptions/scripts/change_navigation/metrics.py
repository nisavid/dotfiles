"""Parse category metrics shared by Stack and Diff validators."""

from __future__ import annotations

import re

from .model import (
    ATTRIBUTE_BOUNDARY,
    LINE_METRIC_TEXT_PATTERN,
    parse_line_metric_text,
)


CATEGORY_METRIC_RE = re.compile(
    rf'{ATTRIBUTE_BOUNDARY}alt="(IMPL|TEST|DOC|GEN|OTHER): '
    rf'({LINE_METRIC_TEXT_PATTERN})"'
)
Metric = tuple[int, int]


def category_metric_items(text: str) -> list[tuple[str, Metric]]:
    items: list[tuple[str, Metric]] = []
    for category, metric_text in CATEGORY_METRIC_RE.findall(text):
        metric = parse_line_metric_text(metric_text)
        if metric is not None:
            items.append((category, metric))
    return items


def category_metric_map(text: str) -> dict[str, Metric]:
    return dict(category_metric_items(text))
