"""Classify disclosures and validate shared category ordering."""

from __future__ import annotations

import re

from .model import ATTRIBUTE_BOUNDARY, CATEGORY_RE


METRIC_BADGE_RE = re.compile(
    rf'{ATTRIBUTE_BOUNDARY}alt="(IMPL|TEST|DOC|GEN|OTHER|FILES):'
)
SUMMARY_ALT_RE = re.compile(
    r"\balt\s*=\s*(?P<quote>['\"]?)(?P<label>STACK|DIFF)(?P=quote)(?=\s|/?>)",
    re.IGNORECASE,
)


def classify_disclosures(blocks: list[list[str]]) -> list[str]:
    labels: list[str] = []
    for block in blocks:
        block_text = "\n".join(block)
        summary_match = re.search(
            r"<summary\b[^>]*>(.*?)</summary>", block_text, re.IGNORECASE | re.DOTALL
        )
        summary_text = summary_match.group(1) if summary_match else ""
        alt_match = SUMMARY_ALT_RE.search(summary_text)
        labels.append(alt_match.group("label").upper() if alt_match else "UNKNOWN")
    return labels


def validate_category_order(value: str, errors: list[str], label: str) -> None:
    categories = CATEGORY_RE.findall(value)
    expected_categories = [
        category
        for category in ["IMPL", "TEST", "DOC", "GEN", "OTHER"]
        if category in categories
    ]
    metrics = METRIC_BADGE_RE.findall(value)
    if metrics != expected_categories + ["FILES"]:
        errors.append(
            f"{label} metrics must use canonical category order with one terminal FILES"
        )
