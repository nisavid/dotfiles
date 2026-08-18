"""Define badge patterns shared by change-navigation validators."""

from __future__ import annotations

import re
from html import unescape


ATTRIBUTE_BOUNDARY = r"(?<!\S)"
COUNT_PATTERN = r"(?:0|[1-9][0-9]{0,17})"
POSITIVE_COUNT_PATTERN = r"(?:[1-9][0-9]{0,17})"
LINE_METRIC_TEXT_PATTERN = (
    rf"{COUNT_PATTERN} additions?, {COUNT_PATTERN} deletions?"
)
IMAGE_RE = re.compile(r"<img\b[^>]*>")
SHIELD_IMAGE_RE = re.compile(
    rf'<img\b[^>]*{ATTRIBUTE_BOUNDARY}src="https://img\.shields\.io/[^"]+"[^>]*>'
)
ALT_RE = re.compile(rf'{ATTRIBUTE_BOUNDARY}alt="([^"]*)"')
TITLE_RE = re.compile(rf'{ATTRIBUTE_BOUNDARY}title="([^"]*)"')
HEIGHT_RE = re.compile(rf'{ATTRIBUTE_BOUNDARY}height="16"')
LINKED_PR_BADGE_RE = re.compile(
    r'<a href="https://github\.com/[^/]+/[^/]+/pull/(\d+)"><img\b([^>]*)></a>'
)
LINKED_SHIELD_RE = re.compile(
    rf'<a href="([^"]+)">(<img\b[^>]*{ATTRIBUTE_BOUNDARY}'
    r'src="https://img\.shields\.io/[^"]+"[^>]*>)</a>'
)
PICTURE_SHIELD_RE = re.compile(
    rf"<picture>(<img\b[^>]*{ATTRIBUTE_BOUNDARY}"
    r'src="https://img\.shields\.io/[^"]+"[^>]*>)</picture>'
)
ATOMIC_FILE_BADGE_RE = re.compile(
    rf'{ATTRIBUTE_BOUNDARY}src="https://img\.shields\.io/badge/'
    rf"%2B({COUNT_PATTERN})-%E2%88%92({COUNT_PATTERN})-CF222E"
    r'\?style=flat&labelColor=1A7F37"'
)
LINE_METRIC_TEXT_RE = re.compile(LINE_METRIC_TEXT_PATTERN)
CATEGORY_RE = re.compile(rf'{ATTRIBUTE_BOUNDARY}alt="(IMPL|TEST|DOC|GEN|OTHER):')


def _count_text(value: int | str) -> str:
    text = str(value)
    if re.fullmatch(r"(?:0|[1-9][0-9]*)", text) is None:
        raise ValueError("count must be a canonical nonnegative integer")
    return text


def line_metric_text(additions: int | str, deletions: int | str) -> str:
    """Return grammatical accessibility text for line-count metrics."""
    addition_count = _count_text(additions)
    deletion_count = _count_text(deletions)
    addition_word = "addition" if addition_count == "1" else "additions"
    deletion_word = "deletion" if deletion_count == "1" else "deletions"
    return (
        f"{addition_count} {addition_word}, "
        f"{deletion_count} {deletion_word}"
    )


def parse_line_metric_text(value: str) -> tuple[int, int] | None:
    """Return counts only when line-metric text has canonical grammar."""
    match = LINE_METRIC_TEXT_RE.fullmatch(value)
    if not match:
        return None
    additions_text, deletions_text = re.findall(COUNT_PATTERN, value)
    if value != line_metric_text(additions_text, deletions_text):
        return None
    return int(additions_text), int(deletions_text)


def changed_files_text(count: int | str) -> str:
    """Return a grammatical changed-file count."""
    count_text = _count_text(count)
    noun = "file" if count_text == "1" else "files"
    return f"{count_text} changed {noun}"


def raw_attribute(tag: str, name: str) -> str:
    values = attribute_values(tag, name)
    return values[0] if values else ""


def attribute_values(tag: str, name: str) -> list[str]:
    return re.findall(rf'{ATTRIBUTE_BOUNDARY}{re.escape(name)}="([^"]*)"', tag)


def alt(image: str) -> str:
    return unescape(raw_attribute(image, "alt"))


def title(image: str) -> str:
    return unescape(raw_attribute(image, "title"))


def source(image: str) -> str:
    return raw_attribute(image, "src")


def alt_values(text: str) -> list[str]:
    return [unescape(value) for value in ALT_RE.findall(text)]
