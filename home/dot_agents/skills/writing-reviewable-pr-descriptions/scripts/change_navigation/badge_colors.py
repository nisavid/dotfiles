"""Validate canonical badge labels and colors."""

from __future__ import annotations

import re
from urllib.parse import quote, unquote, urlsplit

from .model import (
    COUNT_PATTERN,
    LINE_METRIC_TEXT_PATTERN,
    LINE_METRIC_TEXT_RE,
    POSITIVE_COUNT_PATTERN,
    changed_files_text,
    parse_line_metric_text,
)

EXPECTED_BADGE_COLORS = {
    "IMPL": "0969DA",
    "TEST": "6F5F9A",
    "DOC": "3F7770",
    "GEN": "76652F",
    "OTHER": "57606A",
    "FILES": "5F6B78",
    "REMAINDER": "5F6B78",
    "BASE": "5F6B78",
    "DEP": "5F6B78",
    "NEXT": "5F6B78",
    "BINARY": "5F6B78",
    "MOVED": "5F6B78",
    "COPIED": "5F6B78",
}


def _decoded_badge_path(source_url: str) -> str:
    path = unquote(urlsplit(source_url).path)
    return path.split("/badge/", 1)[1] if "/badge/" in path else ""


def _raw_badge_path(source_url: str) -> str:
    path = urlsplit(source_url).path
    return path.split("/badge/", 1)[1] if "/badge/" in path else ""


def _expected_badge_path(image_alt: str) -> str | None:
    if image_alt in {"STACK", "DIFF"}:
        return f"{image_alt}-57606A"
    category = re.fullmatch(
        rf"(IMPL|TEST|DOC|GEN|OTHER): ({LINE_METRIC_TEXT_PATTERN})", image_alt
    )
    if category:
        label, metric_text = category.groups()
        metric = parse_line_metric_text(metric_text)
        if metric is None:
            return None
        additions, deletions = metric
        return f"{label}-+{additions} −{deletions}-{EXPECTED_BADGE_COLORS[label]}"
    file_operations = re.fullmatch(
        rf"FILES: ({COUNT_PATTERN}) added, ({COUNT_PATTERN}) modified, "
        rf"({COUNT_PATTERN}) removed"
        rf"(?:, ({POSITIVE_COUNT_PATTERN}) moved)?"
        rf"(?:, ({POSITIVE_COUNT_PATTERN}) copied)?",
        image_alt,
    )
    if file_operations:
        added, modified, removed, moved, copied = file_operations.groups()
        message = f"+{added} ~{modified} −{removed}"
        if moved is not None:
            message += f" MOVED {moved}"
        if copied is not None:
            message += f" COPIED {copied}"
        return f"FILES-{message}-5F6B78"
    files = re.fullmatch(
        rf"FILES: ({COUNT_PATTERN}) (?:touched|"
        r"(?:shown )?(?:implementation|test|documentation|generated|other) files?)",
        image_alt,
    )
    if files:
        return f"FILES-{files.group(1)}-5F6B78"
    remainder = re.fullmatch(
        rf"REMAINDER: ({POSITIVE_COUNT_PATTERN}) changed files?", image_alt
    )
    if remainder and image_alt == (
        f"REMAINDER: {changed_files_text(remainder.group(1))}"
    ):
        return f"REMAINDER-+{remainder.group(1)} MORE-5F6B78"
    navigation = re.fullmatch(r"(BASE|DEP|NEXT): #(\d+) — .+", image_alt)
    if navigation:
        return f"{navigation.group(1)}-#{navigation.group(2)}-5F6B78"
    branch_base = re.fullmatch(r"BASE: (.+)", image_alt)
    if branch_base:
        return f"BASE-{branch_base.group(1)}-5F6B78"
    position = re.fullmatch(r"STACK POSITION: (\d+) OF (\d+)", image_alt)
    if position:
        return f"{position.group(1)} OF {position.group(2)}-5F6B78"
    if image_alt == "STACK STATUS: TOP":
        return "TOP-5F6B78"
    if image_alt in {"BINARY", "MOVED", "COPIED"}:
        return f"{image_alt}-5F6B78"
    atomic = parse_line_metric_text(image_alt)
    if atomic:
        return f"+{atomic[0]}-−{atomic[1]}-CF222E"
    return None


def validate_color_and_label(
    image_alt: str, source_url: str, errors: list[str]
) -> None:
    expected_path = _expected_badge_path(image_alt)
    category = re.fullmatch(
        rf"(?:IMPL|TEST|DOC|GEN|OTHER): ({LINE_METRIC_TEXT_PATTERN})", image_alt
    )
    metric_text = category.group(1) if category else image_alt
    if (
        LINE_METRIC_TEXT_RE.fullmatch(metric_text)
        and parse_line_metric_text(metric_text) is None
    ):
        errors.append(f"metric badge has ungrammatical accessibility text: {image_alt}")
        return
    remainder = re.fullmatch(
        rf"REMAINDER: ({POSITIVE_COUNT_PATTERN}) changed files?", image_alt
    )
    if remainder and image_alt != (
        f"REMAINDER: {changed_files_text(remainder.group(1))}"
    ):
        errors.append(
            f"remainder badge has ungrammatical accessibility text: {image_alt}"
        )
        return
    if expected_path and _decoded_badge_path(source_url) != expected_path:
        errors.append(
            f"{image_alt} visual badge text/color must encode {expected_path}"
        )
        return
    if expected_path and _raw_badge_path(source_url) != quote(expected_path, safe="-~"):
        errors.append(f"{image_alt} badge URL must use canonical percent encoding")
        return
    prefix = image_alt.split(":", 1)[0]
    expected_color = EXPECTED_BADGE_COLORS.get(prefix)
    if expected_color and not expected_path:
        errors.append(f"{prefix} badge has unsupported accessibility text")
