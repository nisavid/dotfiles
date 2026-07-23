"""Parse category metrics shared by Stack and Diff validators."""

from __future__ import annotations

import re

from .model import ATTRIBUTE_BOUNDARY


CATEGORY_METRIC_RE = re.compile(
    rf'{ATTRIBUTE_BOUNDARY}alt="(IMPL|TEST|DOC|GEN|OTHER): '
    r'(\d+) additions, (\d+) deletions"'
)
Metric = tuple[int, int]


def category_metric_items(text: str) -> list[tuple[str, Metric]]:
    return [
        (category, (int(additions), int(deletions)))
        for category, additions, deletions in CATEGORY_METRIC_RE.findall(text)
    ]


def category_metric_map(text: str) -> dict[str, Metric]:
    return dict(category_metric_items(text))
