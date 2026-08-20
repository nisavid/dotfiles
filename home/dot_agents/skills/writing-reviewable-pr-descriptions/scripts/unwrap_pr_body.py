#!/usr/bin/env python3
"""Repair misencoded source line breaks in a PR body.

Joins every block element that a column budget split across source lines and
rewrites trailing-whitespace breaks as explicit `<br>`. The transformation
touches whitespace and break markers only: the word sequence is preserved, so a
repaired body can be compared with its published original before publication.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from body_source import (
    ACCIDENTAL_BREAK,
    INVISIBLE_BREAK,
    QUOTE_MARKER,
    validate_source_breaks,
    wrap_offenses,
)


def unwrap(body: str) -> str:
    """Return ``body`` with every misencoded source line break repaired."""
    kinds = {offense.line: offense.kind for offense in wrap_offenses(body)}
    repaired: list[str] = []
    for number, line in enumerate(body.split("\n"), start=1):
        kind = kinds.get(number)
        if kind == ACCIDENTAL_BREAK and repaired:
            continuation = QUOTE_MARKER.sub("", line).strip()
            repaired[-1] = f"{repaired[-1].rstrip()} {continuation}"
            continue
        if kind == INVISIBLE_BREAK and repaired:
            repaired[-1] = f"{repaired[-1].rstrip()}<br>"
        repaired.append(line)
    return "\n".join(repaired)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "body", type=Path, help="Markdown file containing the complete PR body"
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Rewrite the file instead of printing the repaired body",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Report offenses and change nothing. This check needs no repository"
            " or PR identity, so it also covers a chat-only draft."
        ),
    )
    args = parser.parse_args()
    original = args.body.read_text(encoding="utf-8")
    if args.check:
        errors: list[str] = []
        validate_source_breaks(original, errors)
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        if errors:
            return 1
        print(f"{args.body} encodes every line break as intended")
        return 0
    repaired = unwrap(original)
    if "".join(original.replace("<br>", " ").split()) != "".join(
        repaired.replace("<br>", " ").split()
    ):
        print("ERROR: repair would change body words; refusing", file=sys.stderr)
        return 1
    if args.in_place:
        args.body.write_text(repaired, encoding="utf-8")
        print(f"Repaired {args.body}")
        return 0
    sys.stdout.write(repaired)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
