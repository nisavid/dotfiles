from __future__ import annotations

import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Optional


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_change_navigation.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("validate_change_navigation", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PRODUCTION_VALIDATE = MODULE.validate


def validate_fixture(body: str) -> list[str]:
    return PRODUCTION_VALIDATE(body, "acme/app", 2)


MODULE.validate = validate_fixture


def badge(
    alt: str,
    path: str,
    *,
    style: str = "flat",
    title: Optional[str] = None,
    label_color: Optional[str] = None,
) -> str:
    query = f"style={style}"
    if label_color:
        query += f"&labelColor={label_color}"
    title_attribute = f' title="{title}"' if title else ""
    return (
        f'<picture><img alt="{alt}"{title_attribute} '
        f'src="https://img.shields.io/badge/{path}?{query}" height="16"></picture>'
    )


def linked_badge(pr_number: int, alt: str, path: str) -> str:
    destination = alt.split(": ", 1)[1]
    image = (
        badge(alt, path, title=destination)
        .removeprefix("<picture>")
        .removesuffix("</picture>")
    )
    return f'<a href="https://github.com/acme/app/pull/{pr_number}">{image}</a>'


def atomic_metric(additions: int, deletions: int) -> str:
    title = f"{additions} additions, {deletions} deletions"
    path = f"%2B{additions}-%E2%88%92{deletions}-CF222E"
    return badge(title, path, title=title, label_color="1A7F37")


def diff_body() -> str:
    anchor = hashlib.sha256(b"src/widget.ts").hexdigest()
    summary = " ".join(
        [
            badge("DIFF", "DIFF-57606A", style="for-the-badge"),
            badge("IMPL: 9 additions, 3 deletions", "IMPL-%2B9%20%E2%88%923-0969DA"),
            badge("FILES: 1 touched", "FILES-1-5F6B78"),
        ]
    ).replace("</picture> ", "</picture>&nbsp;", 1)
    category = " ".join(
        [
            badge("IMPL: 9 additions, 3 deletions", "IMPL-%2B9%20%E2%88%923-0969DA"),
            badge("FILES: 1 implementation file", "FILES-1-5F6B78"),
        ]
    )
    file_item = (
        f"  - [`src/widget.ts`](https://github.com/acme/app/pull/2/files#diff-{anchor}) "
        + atomic_metric(9, 3)
    )
    return "\n".join(
        [
            "<details>",
            f"<summary>{summary}</summary>",
            "",
            f"- {category}",
            file_item,
            "",
            "</details>",
            "",
            "## Summary",
            "- Add the widget.",
            "",
        ]
    )


def stack_body() -> str:
    summary = " ".join(
        [
            badge("STACK", "STACK-57606A", style="for-the-badge"),
            badge("STACK POSITION: 2 OF 2", "2%20OF%202-5F6B78"),
            linked_badge(1, "BASE: #1 — feat: base", "BASE-%231-5F6B78"),
            badge("STACK STATUS: TOP", "TOP-5F6B78"),
        ]
    ).replace("</picture> ", "</picture>&nbsp;", 1)
    base_metrics = " ".join(
        [
            badge("IMPL: 1 additions, 0 deletions", "IMPL-%2B1%20%E2%88%920-0969DA"),
            badge(
                "FILES: 1 added, 0 modified, 0 removed",
                "FILES-%2B1%20~0%20%E2%88%920-5F6B78",
            ),
        ]
    )
    top_metrics = " ".join(
        [
            badge("IMPL: 9 additions, 3 deletions", "IMPL-%2B9%20%E2%88%923-0969DA"),
            badge(
                "FILES: 0 added, 1 modified, 0 removed",
                "FILES-%2B0%20~1%20%E2%88%920-5F6B78",
            ),
        ]
    )
    return "\n".join(
        [
            "<details>",
            f"<summary>{summary}</summary>",
            "",
            "- **[#1 — feat: base](https://github.com/acme/app/pull/1)**<br>"
            + base_metrics,
            "- **[#2 — feat: top](https://github.com/acme/app/pull/2)** "
            "**← this PR**<br>" + top_metrics,
            "",
            "<sup>IMPL means non-test source and configuration. TEST, DOC, GEN, "
            "and OTHER are counted separately. FILES shows added, modified, and "
            "removed files as +, ~, and −.</sup>",
            "",
            "</details>",
            "",
        ]
    )


DIFF = diff_body()
STACK = stack_body()


class ValidateChangeNavigationTests(unittest.TestCase):
    def test_accepts_unstacked_diff(self) -> None:
        self.assertEqual(MODULE.validate(DIFF), [])

    def test_accepts_stack_then_diff(self) -> None:
        self.assertEqual(MODULE.validate(STACK + DIFF), [])

    def test_rejects_split_file_metrics(self) -> None:
        broken = DIFF.replace(
            atomic_metric(9, 3),
            badge("9 additions", "%2B9-1A7F37")
            + " "
            + badge("3 deletions", "%E2%88%923-CF222E"),
        )
        self.assertTrue(any("atomic" in error for error in MODULE.validate(broken)))

    def test_rejects_separate_stack_heading(self) -> None:
        self.assertTrue(
            any(
                "Stack section" in error
                for error in MODULE.validate(STACK + DIFF + "\n## Stack\n")
            )
        )

    def test_rejects_unclosed_later_duplicate_diff_disclosure(self) -> None:
        duplicate = DIFF.split("</details>", 1)[0]
        errors = MODULE.validate(DIFF + "\n" + duplicate)
        self.assertTrue(any("exactly once" in error for error in errors))

    def test_rejects_unclosed_canonical_diff_disclosure(self) -> None:
        unclosed = DIFF.replace("\n</details>", "", 1)
        self.assertTrue(MODULE.validate(unclosed))

    def test_rejects_inline_later_duplicate_diff_disclosure(self) -> None:
        summary = DIFF.splitlines()[1]
        duplicate = f"<details>{summary}duplicate</details>"
        errors = MODULE.validate(DIFF + "\n" + duplicate)
        self.assertTrue(any("exactly once" in error for error in errors))

    def test_rejects_uppercase_later_duplicate_diff_disclosure(self) -> None:
        summary = DIFF.splitlines()[1]
        uppercase_summary = summary.replace("<summary>", "<SUMMARY>").replace(
            "</summary>", "</SUMMARY>"
        )
        uppercase_summary = uppercase_summary.replace('alt="DIFF"', 'ALT="DIFF"')
        duplicate = f"<DETAILS>{uppercase_summary}duplicate</DETAILS>"
        errors = MODULE.validate(DIFF + "\n" + duplicate)
        self.assertTrue(any("exactly once" in error for error in errors))

    def test_rejects_unquoted_alt_later_duplicate_diff_disclosure(self) -> None:
        summary = DIFF.splitlines()[1].replace('alt="DIFF"', "alt=DIFF")
        duplicate = f"<details>{summary}duplicate</details>"
        errors = MODULE.validate(DIFF + "\n" + duplicate)
        self.assertTrue(any("exactly once" in error for error in errors))

    def test_rejects_wrong_height(self) -> None:
        broken = DIFF.replace('height="16"', 'height="20"', 1)
        self.assertTrue(any("16px" in error for error in MODULE.validate(broken)))


if __name__ == "__main__":
    unittest.main()
