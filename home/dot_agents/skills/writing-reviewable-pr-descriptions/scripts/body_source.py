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
FENCE = re.compile(r"^(?P<marker>`{3,}|~{3,})(?P<info>.*)$")
TAG_NAME = re.compile(r"^</?([A-Za-z][A-Za-z0-9-]*)")
COMPLETE_TAG = re.compile(
    r"^<(?:/[A-Za-z][A-Za-z0-9-]*\s*|[A-Za-z][A-Za-z0-9-]*(?:\s+[^<>]*?)?/?)>\s*$"
)
# CommonMark HTML block type 6 tag names. These start a block even mid-paragraph.
BLOCK_TAGS = frozenset(
    [
        "address",
        "article",
        "aside",
        "base",
        "basefont",
        "blockquote",
        "body",
        "caption",
        "center",
        "col",
        "colgroup",
        "dd",
        "details",
        "dialog",
        "dir",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "frame",
        "frameset",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "head",
        "header",
        "hr",
        "html",
        "iframe",
        "legend",
        "li",
        "link",
        "main",
        "menu",
        "menuitem",
        "nav",
        "noframes",
        "ol",
        "optgroup",
        "option",
        "p",
        "param",
        "search",
        "section",
        "summary",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "title",
        "tr",
        "track",
        "ul",
    ]
)
# CommonMark HTML block type 1. These end at their closing tag, not a blank line.
RAW_TEXT_TAGS = frozenset({"pre", "script", "style", "textarea"})
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


def _fence_marker(text: str) -> tuple[str, int] | None:
    """Return the fence character and run length that ``text`` opens."""
    match = FENCE.match(text)
    if match is None:
        return None
    marker = match.group("marker")
    return marker[0], len(marker)


def _closes_fence(text: str, fence: tuple[str, int]) -> bool:
    """Report whether ``text`` is a valid closing fence for ``fence``."""
    marker = _fence_marker(text)
    if marker is None:
        return False
    character, length = marker
    return (
        character == fence[0]
        and length >= fence[1]
        and not FENCE.match(text).group("info").strip()
    )


def _html_block_start(text: str, in_paragraph: bool) -> tuple[str, str] | None:
    """Return the HTML block kind and closer that ``text`` opens, if any."""
    if not text.startswith("<"):
        return None
    if text.startswith("<!--"):
        return "closer", "-->"
    if text.startswith("<?"):
        return "closer", "?>"
    if text.startswith("<![CDATA["):
        return "closer", "]]>"
    if re.match(r"^<![A-Za-z]", text):
        return "blank", ""
    name_match = TAG_NAME.match(text)
    if name_match is not None:
        name = name_match.group(1).lower()
        if name in RAW_TEXT_TAGS and not text.startswith("</"):
            return "closer", f"</{name}>"
        if name in BLOCK_TAGS:
            return "blank", ""
    # Type 7: a complete tag alone on its line, which cannot interrupt a
    # paragraph. Inline HTML inside prose therefore stays part of the paragraph.
    if not in_paragraph and COMPLETE_TAG.match(text):
        return "blank", ""
    return None


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
    fence: tuple[str, int] | None = None
    html: tuple[str, str] | None = None
    previous: str | None = None
    for index, raw in enumerate(lines):
        text = _quoteless(raw)
        if fence is not None:
            if _closes_fence(text, fence):
                fence = None
            previous = None
            continue
        marker = _fence_marker(text)
        if marker is not None:
            fence = marker
            previous = None
            continue
        if html is not None:
            kind, closer = html
            if (kind == "closer" and closer in text) or (kind == "blank" and not text):
                html = None
            previous = None
            continue
        if not text:
            previous = None
            continue
        started = _html_block_start(text, previous is not None)
        if started is not None:
            kind, closer = started
            # A raw-text or comment block may also close on its opening line.
            html = (
                None if kind == "closer" and closer in text[len(closer) :] else started
            )
            previous = None
            continue
        if previous is not None:
            kind = _classify(previous, raw)
            if kind is not None:
                offenses.append(Offense(index + 1, kind, previous.strip(), raw.strip()))
        previous = raw
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
