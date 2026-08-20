"""Classify source line breaks in a GitHub comment-field body.

GitHub renders pull request bodies, issue bodies, and comments with hard line
breaks enabled, so every newline inside a block element becomes a visible break.
A repository file wrapped to a column budget is correct; the same prose in a
comment field is not. This module names the difference so the body validator and
the unwrap helper agree on exactly which breaks are misencoded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BLOCK_START = re.compile(
    r"""^(?:
          \s*[-*+][ \t]        # bullet list item
        | \s*\d+[.)][ \t]      # ordered list item
        | \#{1,6}[ \t]         # ATX heading
        | \|                   # table row
        | <                    # raw HTML
        | ```|~~~              # fenced code
        | (?:-{3,}|\*{3,}|_{3,})\s*$   # thematic break
        | \[[^\]]+\]:          # link or footnote reference definition
    )""",
    re.VERBOSE,
)
BLOCK_END = re.compile(
    r"""^(?:
          \#{1,6}[ \t]                   # ATX heading, a single-line block
        | \|                             # table row
        | (?:-{3,}|\*{3,}|_{3,}|={3,})\s*$  # thematic break or setext underline
    )""",
    re.VERBOSE,
)
FENCE = re.compile(r"^\s*(?:```|~~~)")
QUOTE_MARKER = re.compile(r"^\s*(?:>\s?)+")
ALERT = re.compile(r"^\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$")
EXPLICIT_BREAK = re.compile(r"(?:<br\s*/?>|\\)$")

ACCIDENTAL_BREAK = "accidental-break"
INVISIBLE_BREAK = "invisible-break"


@dataclass(frozen=True)
class Offense:
    """One source line break that a comment field renders against intent."""

    line: int
    kind: str
    previous: str
    current: str


def _quoteless(line: str) -> str:
    """Return ``line`` without its leading blockquote markers."""
    return QUOTE_MARKER.sub("", line).strip()


def _quote_depth(line: str) -> int:
    """Return how many blockquote levels ``line`` opens."""
    marker = QUOTE_MARKER.match(line)
    return marker.group(0).count(">") if marker else 0


def _classify(previous: str, current: str) -> str | None:
    """Return the offense kind for a break between two content lines."""
    quoteless_previous = _quoteless(previous)
    if _quote_depth(current) > _quote_depth(previous):
        # A blockquote may interrupt a paragraph, and a deeper level opens a
        # nested block. A shallower line is a lazy continuation of the quote.
        return None
    if not quoteless_previous or ALERT.match(quoteless_previous):
        return None
    if BLOCK_END.match(quoteless_previous):
        return None
    if EXPLICIT_BREAK.search(previous.rstrip()):
        return None
    if BLOCK_START.match(_quoteless(current)) or BLOCK_START.match(current):
        return None
    if previous.endswith(("  ", "\t")):
        return INVISIBLE_BREAK
    return ACCIDENTAL_BREAK


def wrap_offenses(body: str) -> list[Offense]:
    """Return every misencoded source line break in ``body``."""
    lines = body.split("\n")
    offenses: list[Offense] = []
    in_fence = False
    in_raw_html = False
    for index, current in enumerate(lines):
        if FENCE.match(current):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not _quoteless(current):
            # A blank line, or a bare `>`, separates blocks and ends any raw
            # HTML block.
            in_raw_html = False
            continue
        if in_raw_html:
            continue
        if current.lstrip().startswith("<"):
            # A raw HTML block runs to the next blank line, and HTML collapses
            # its own newlines, so breaks inside it are not reader-visible.
            in_raw_html = True
            continue
        if index == 0 or not _quoteless(lines[index - 1]):
            continue
        kind = _classify(lines[index - 1], current)
        if kind is not None:
            offenses.append(
                Offense(index + 1, kind, lines[index - 1].strip(), current.strip())
            )
    return offenses


def validate_source_breaks(body: str, errors: list[str]) -> None:
    """Append every misencoded source line break in ``body`` to ``errors``."""
    for offense in wrap_offenses(body):
        if offense.kind == INVISIBLE_BREAK:
            errors.append(
                f"body line {offense.line - 1} ends in trailing whitespace used as a"
                " line break; that encoding is invisible in source and formatters"
                " strip it, so write an intended break as <br>"
            )
            continue
        errors.append(
            f"body line {offense.line} continues a block element after a bare"
            " newline; a GitHub comment field renders every newline as a line"
            " break, so join it onto the previous line or write an intended break"
            " as <br>"
        )
