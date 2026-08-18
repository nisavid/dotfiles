"""Define badge patterns shared by change-navigation validators."""

from __future__ import annotations

import re
from html import unescape


ATTRIBUTE_BOUNDARY = r"(?<!\S)"
COUNT_PATTERN = r"(?:0|[1-9][0-9]{0,17})"
POSITIVE_COUNT_PATTERN = r"(?:[1-9][0-9]{0,17})"
NON_SINGULAR_COUNT_PATTERN = rf"(?:(?!1\b){COUNT_PATTERN})"
LINE_METRIC_COUNT_SHAPE_PATTERN = (
    rf"{COUNT_PATTERN} additions?, {COUNT_PATTERN} deletions?"
)
LINE_METRIC_TEXT_PATTERN = (
    rf"(?:1 additions?|{NON_SINGULAR_COUNT_PATTERN} additions), "
    rf"(?:1 deletions?|{NON_SINGULAR_COUNT_PATTERN} deletions)"
)
LINE_METRIC_SHAPE_PATTERN = r"\S+ additions?, \S+ deletions?"
BRANCH_BASE_TOKEN_RE = re.compile(r"[A-Za-z0-9._/-]{1,255}")
IMAGE_RE = re.compile(r"<img\b[^>]*>")
SHIELD_IMAGE_RE = re.compile(
    rf'<img\b[^>]*{ATTRIBUTE_BOUNDARY}src="https://img\.shields\.io/[^"]+"[^>]*>'
)
ALT_RE = re.compile(rf'{ATTRIBUTE_BOUNDARY}alt="([^"]*)"')
TITLE_RE = re.compile(rf'{ATTRIBUTE_BOUNDARY}title="([^"]*)"')
HEIGHT_RE = re.compile(rf'{ATTRIBUTE_BOUNDARY}height="16"')
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
LINE_METRIC_COUNT_SHAPE_RE = re.compile(
    rf"({COUNT_PATTERN}) additions?, ({COUNT_PATTERN}) deletions?"
)
LINE_METRIC_SHAPE_RE = re.compile(LINE_METRIC_SHAPE_PATTERN)
CATEGORY_RE = re.compile(rf'{ATTRIBUTE_BOUNDARY}alt="(IMPL|TEST|DOC|GEN|OTHER):')


def _count_text(value: int | str) -> str:
    text = str(value)
    if re.fullmatch(COUNT_PATTERN, text) is None:
        raise ValueError("count must be a bounded canonical nonnegative integer")
    return text


def parse_line_metric_counts(value: str) -> tuple[int, int] | None:
    """Return bounded ASCII counts without enforcing noun agreement."""
    match = LINE_METRIC_COUNT_SHAPE_RE.fullmatch(value)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def parse_line_metric_text(value: str) -> tuple[int, int] | None:
    """Return counts from grammatical or legacy plural-for-one metric text."""
    if LINE_METRIC_TEXT_RE.fullmatch(value) is None:
        return None
    return parse_line_metric_counts(value)


def changed_files_text(count: int | str) -> str:
    """Return a grammatical changed-file count."""
    count_text = _count_text(count)
    noun = "file" if count_text == "1" else "files"
    return f"{count_text} changed {noun}"


def branch_base_name(value: str) -> str | None:
    """Return a conservative canonical ASCII Git branch name."""
    if not value.startswith("BASE: "):
        return None
    name = value.removeprefix("BASE: ")
    if BRANCH_BASE_TOKEN_RE.fullmatch(name) is None:
        return None
    if (
        name == "HEAD"
        or name.startswith(("-", ".", "/"))
        or name.endswith((".", "/"))
        or ".." in name
        or "//" in name
    ):
        return None
    components = name.split("/")
    if any(
        component.startswith(".") or component.endswith(".lock")
        for component in components
    ):
        return None
    return name


def is_pr_base_shape(value: str) -> bool:
    """Return whether BASE text presents as a pull-request destination."""
    if not value.startswith("BASE: "):
        return False
    destination = value.removeprefix("BASE: ")
    return (
        destination.startswith(("#", "＃"))
        or " — " in destination
        or destination.startswith("PR ")
    )


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
