"""Parse leading details blocks plus summaries."""

from __future__ import annotations

import re


DETAILS_OPEN_RE = re.compile(r"<details(?:\s[^>]*)?>", re.IGNORECASE)
DETAILS_CLOSE_RE = re.compile(r"</details>", re.IGNORECASE)


def first_nonempty_line(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if line.strip():
            return index
    return -1


def extract_leading_details(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    index = first_nonempty_line(lines)
    while _starts_details(lines, index):
        block, index = _extract_one_details(lines, index)
        if not block:
            break
        blocks.append(block)
    return blocks


def extract_details(lines: list[str]) -> list[list[str]]:
    """Extract every details block outside fenced code."""
    blocks: list[list[str]] = []
    index = 0
    fence: tuple[str, int] | None = None
    while index < len(lines):
        stripped = lines[index].lstrip()
        marker = _fence_marker(stripped)
        if marker and (
            fence is None or marker[0] == fence[0] and marker[1] >= fence[1]
        ):
            fence = None if fence else marker
            index += 1
            continue
        if fence is None and DETAILS_OPEN_RE.search(lines[index]):
            block, next_index = _extract_one_details(lines, index, inline=True)
            if block:
                blocks.append(block)
                index = next_index
                continue
        index += 1
    return blocks


def _fence_marker(line: str) -> tuple[str, int] | None:
    if line.startswith("```"):
        return "`", len(line) - len(line.lstrip("`"))
    if line.startswith("~~~"):
        return "~", len(line) - len(line.lstrip("~"))
    return None


def _starts_details(lines: list[str], index: int) -> bool:
    return 0 <= index < len(lines) and bool(
        DETAILS_OPEN_RE.fullmatch(lines[index].strip())
    )


def _extract_one_details(
    lines: list[str], start: int, *, inline: bool = False
) -> tuple[list[str], int]:
    depth = 0
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if inline:
            depth += len(DETAILS_OPEN_RE.findall(stripped))
            depth -= len(DETAILS_CLOSE_RE.findall(stripped))
        else:
            depth += bool(DETAILS_OPEN_RE.fullmatch(stripped))
            depth -= bool(DETAILS_CLOSE_RE.fullmatch(stripped))
        if depth == 0:
            return lines[start : index + 1], _next_nonempty(lines, index + 1)
    return (lines[start:] if inline else []), len(lines)


def _next_nonempty(lines: list[str], index: int) -> int:
    while index < len(lines) and not lines[index].strip():
        index += 1
    return index


def summary(block: list[str], errors: list[str], label: str) -> str:
    text = "\n".join(block)
    if text.count("<summary>") != 1 or text.count("</summary>") != 1:
        errors.append(f"{label} disclosure must contain exactly one summary pair")
        return ""
    summary_lines = [
        line for line in block if "<summary>" in line or "</summary>" in line
    ]
    if len(summary_lines) != 1:
        errors.append(f"{label} summary must occupy exactly one source line")
        return ""
    value = summary_lines[0].strip()
    if not (value.startswith("<summary>") and value.endswith("</summary>")):
        errors.append(f"{label} summary must open and close on the same line")
    return value
