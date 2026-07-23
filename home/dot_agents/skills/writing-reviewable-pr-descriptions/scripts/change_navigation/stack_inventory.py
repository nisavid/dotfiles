"""Validate the expanded stack inventory."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape, unescape
from typing import Optional

from .metrics import Metric, category_metric_items, category_metric_map
from .model import SHIELD_IMAGE_RE, alt_values
from .types import validate_category_order


STACK_ITEM_RE = re.compile(
    r"^- \*\*\[#(\d+) — (.+)\]\(https://github\.com/([^/]+)/([^/]+)/pull/(\d+)\)\*\*"
    r"( \*\*← this PR\*\*)?<br>(.+)$"
)
STACK_FILE_OPERATIONS_RE = re.compile(
    r"FILES: (\d+) added, (\d+) modified, (\d+) removed"
    r"(?:, ([1-9]\d*) moved)?(?:, ([1-9]\d*) copied)?"
)
MARKDOWN_ESCAPE_RE = re.compile(r"([\\`*_\[\]])")
MARKDOWN_UNESCAPE_RE = re.compile(r"\\([\\`*_\[\]])")
TAXONOMY_NOTE = (
    "<sup>IMPL means non-test source and configuration. TEST, DOC, GEN, and OTHER "
    "are counted separately. FILES shows added, modified, and removed files as +, "
    "~, and −.</sup>"
)
BLOCK_CONTEXT_RE = re.compile(
    r"^(?:\s|#{1,6}\s|>|\||[-+*]\s|\d+[.)]\s|```|~~~|"
    r"(?:[*_-]\s*){3,}$|\[[^]]+\]:\s*\S)|!\[|[<>]|\|"
)


def escape_markdown_title(title: str) -> str:
    escaped = MARKDOWN_ESCAPE_RE.sub(r"\\\1", title)
    return escape(escaped, quote=False)


def unescape_markdown_title(title: str) -> str:
    return MARKDOWN_UNESCAPE_RE.sub(r"\1", unescape(title))


@dataclass(frozen=True)
class StackItem:
    number: int
    title: str
    repository: str
    destination_number: int
    current: bool
    metrics: str

    @property
    def destination_text(self) -> str:
        return f"#{self.number} — {unescape_markdown_title(self.title)}"


def inventory(block: list[str]) -> list[StackItem]:
    items: list[StackItem] = []
    for line in block:
        match = STACK_ITEM_RE.fullmatch(line)
        if match:
            items.append(
                StackItem(
                    number=int(match.group(1)),
                    title=match.group(2),
                    repository=f"{match.group(3)}/{match.group(4)}",
                    destination_number=int(match.group(5)),
                    current=bool(match.group(6)),
                    metrics=match.group(7),
                )
            )
    return items


def validate_inventory(
    block: list[str], position_match: Optional[re.Match[str]], errors: list[str]
) -> None:
    items = inventory(block)
    if not items:
        errors.append("Stack expansion needs its complete linked PR inventory")
        return
    current_items = [index for index, item in enumerate(items, start=1) if item.current]
    if len(current_items) != 1:
        errors.append("Stack inventory must mark exactly one current PR item")
    numbers = [item.number for item in items]
    if len(numbers) != len(set(numbers)):
        errors.append("Stack inventory must not repeat a PR")
    repositories = {item.repository for item in items}
    if len(repositories) != 1:
        errors.append("all Stack inventory PRs must use one repository")
    _validate_item_metrics(items, errors)
    for item in items:
        semantic_title = unescape_markdown_title(item.title)
        if item.title != escape_markdown_title(semantic_title):
            errors.append(
                f"Stack item #{item.number} title must use canonical Markdown escaping"
            )
        if item.number != item.destination_number:
            errors.append(
                f"Stack item #{item.number} links to PR #{item.destination_number}"
            )
    if position_match:
        _validate_position(items, current_items, position_match, errors)
    _validate_expansion_grammar(block, errors)


def _validate_item_metrics(items: list[StackItem], errors: list[str]) -> None:
    for item in items:
        metric_items = category_metric_items(item.metrics)
        if not metric_items:
            errors.append("each Stack item needs at least one category metric")
        validate_category_order(item.metrics, errors, f"Stack item #{item.number}")
        if len(metric_items) != len(dict(metric_items)):
            errors.append(f"Stack item #{item.number} repeats a category metric")
        files_badges = [
            badge for badge in alt_values(item.metrics) if badge.startswith("FILES:")
        ]
        if len(files_badges) != 1 or not STACK_FILE_OPERATIONS_RE.fullmatch(
            files_badges[0]
        ):
            errors.append("each Stack item needs complete file-operation metrics")
        if "<br>" in item.metrics:
            errors.append(f"Stack item #{item.number} must use exactly one line break")
        images = SHIELD_IMAGE_RE.findall(item.metrics)
        canonical_metrics = " ".join(f"<picture>{image}</picture>" for image in images)
        metric_alts = alt_values(item.metrics)
        allowed_alts = [category for category, _ in metric_items] + ["FILES"]
        actual_alts = [value.split(":", 1)[0] for value in metric_alts]
        if item.metrics != canonical_metrics or actual_alts != allowed_alts:
            errors.append(
                f"Stack item #{item.number} metric row contains unsupported content"
            )


def current_item_file_operation_count(block: list[str]) -> int | None:
    operations = current_item_file_operations(block)
    return sum(operations.values()) if operations is not None else None


def current_item_file_operations(block: list[str]) -> dict[str, int] | None:
    for item in inventory(block):
        if not item.current:
            continue
        for badge in alt_values(item.metrics):
            match = STACK_FILE_OPERATIONS_RE.fullmatch(badge)
            if match:
                return dict(
                    zip(
                        ("added", "modified", "removed", "moved", "copied"),
                        (int(value or 0) for value in match.groups()),
                    )
                )
    return None


def _validate_expansion_grammar(block: list[str], errors: list[str]) -> None:
    significant = [line for line in block if line.strip()]
    if len(significant) < 5:
        errors.append("Stack expansion is incomplete")
        return
    content = significant[2:-1]
    item_count = 0
    while item_count < len(content) and STACK_ITEM_RE.fullmatch(content[item_count]):
        item_count += 1
    if item_count == 0:
        errors.append(
            "Stack expansion contains unsupported content before its inventory"
        )
        return
    remainder = content[item_count:]
    if not remainder or remainder[0] != TAXONOMY_NOTE:
        errors.append("Stack expansion needs the exact canonical taxonomy note")
        return
    context = remainder[1:]
    if len(context) > 1 or any(BLOCK_CONTEXT_RE.search(line) for line in context):
        errors.append("Stack expansion contains unsupported residual content")


def current_item_metrics(block: list[str]) -> dict[str, Metric]:
    for item in inventory(block):
        if item.current:
            return category_metric_map(item.metrics)
    return {}


def current_item_identity(block: list[str]) -> tuple[str, int] | None:
    for item in inventory(block):
        if item.current:
            return item.repository, item.number
    return None


def _validate_position(
    items: list[StackItem],
    current_items: list[int],
    position_match: re.Match[str],
    errors: list[str],
) -> None:
    current_position = int(position_match.group(1))
    total = int(position_match.group(2))
    if len(items) != total:
        errors.append(
            f"Stack summary claims {total} PRs but expansion lists {len(items)}"
        )
    if current_items and current_items[0] != current_position:
        errors.append(
            f"Stack summary position {current_position} does not match item {current_items[0]}"
        )
