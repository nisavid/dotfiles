from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_validate_change_navigation import (
    PRODUCTION_VALIDATE,
    STACK,
    atomic_metric,
    badge,
)

REPOSITORY = "acme/app"
PR_NUMBER = 2
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40


def bounded_diff_body(total_files: int) -> str:
    shown_files = min(total_files, 100)
    summary = " ".join(
        [
            badge("DIFF", "DIFF-57606A", style="for-the-badge"),
            badge(
                f"IMPL: {total_files} additions, 0 deletions",
                f"IMPL-%2B{total_files}%20%E2%88%920-0969DA",
            ),
            badge(f"FILES: {total_files} touched", f"FILES-{total_files}-5F6B78"),
        ]
    ).replace("</picture> ", "</picture>&nbsp;", 1)
    category = " ".join(
        [
            badge(
                f"IMPL: {total_files} additions, 0 deletions",
                f"IMPL-%2B{total_files}%20%E2%88%920-0969DA",
            ),
            badge(
                f"FILES: {shown_files} shown implementation files",
                f"FILES-{shown_files}-5F6B78",
            ),
        ]
    )
    rows = []
    for index in range(shown_files):
        path = f"src/file-{index:03}.ts"
        anchor = hashlib.sha256(path.encode()).hexdigest()
        rows.append(
            f"  - [`{path}`](https://github.com/{REPOSITORY}/pull/{PR_NUMBER}/"
            f"files#diff-{anchor}) {atomic_metric(1, 0)}"
        )
    remainder = total_files - shown_files
    remainder_noun = "file" if remainder == 1 else "files"
    return "\n".join(
        [
            "<details>",
            f"<summary>{summary}</summary>",
            "",
            f"- {category}",
            *rows,
            f"- {badge(f'REMAINDER: {remainder} changed {remainder_noun}', f'REMAINDER-%2B{remainder}%20MORE-5F6B78')}",
            (
                f"  - [Complete immutable comparison](https://github.com/"
                f"{REPOSITORY}/compare/{BASE_SHA}...{HEAD_SHA})"
            ),
            "",
            "</details>",
            "",
        ]
    )


def complete_diff_body(total_files: int) -> str:
    body = bounded_diff_body(total_files)
    summary = next(line for line in body.splitlines() if line.startswith("<summary>"))
    complete_summary = " ".join(
        [
            badge("DIFF", "DIFF-57606A", style="for-the-badge"),
            badge(
                f"IMPL: {total_files} additions, 0 deletions",
                f"IMPL-%2B{total_files}%20%E2%88%920-0969DA",
            ),
            badge(f"FILES: {total_files} touched", f"FILES-{total_files}-5F6B78"),
        ]
    ).replace("</picture> ", "</picture>&nbsp;", 1)
    bounded_category = next(
        line for line in body.splitlines() if line.startswith("- <picture>")
    )
    complete_category = bounded_category.replace(
        " shown implementation", " implementation"
    )
    remainder = total_files - min(total_files, 100)
    remainder_noun = "file" if remainder == 1 else "files"
    return (
        body.replace(summary, f"<summary>{complete_summary}</summary>")
        .replace(bounded_category, complete_category)
        .replace(
            f"- {badge(f'REMAINDER: {remainder} changed {remainder_noun}', f'REMAINDER-%2B{remainder}%20MORE-5F6B78')}\n",
            "",
        )
        .replace(
            "  - [Complete immutable comparison]"
            f"(https://github.com/{REPOSITORY}/compare/{BASE_SHA}...{HEAD_SHA})\n",
            "",
        )
    )


def bounded_diff_body_with_omitted_category() -> str:
    body = (
        bounded_diff_body(101)
        .replace("IMPL: 101 additions, 0 deletions", "IMPL: 100 additions, 0 deletions")
        .replace("IMPL-%2B101%20%E2%88%920", "IMPL-%2B100%20%E2%88%920")
    )
    summary = next(line for line in body.splitlines() if line.startswith("<summary>"))
    files_badge = badge("FILES: 101 touched", "FILES-101-5F6B78")
    doc_metric = badge("DOC: 1 addition, 0 deletions", "DOC-%2B1%20%E2%88%920-3F7770")
    doc_group = " ".join(
        [
            doc_metric,
            badge(
                "FILES: 0 shown documentation files",
                "FILES-0-5F6B78",
            ),
        ]
    )
    remainder = next(line for line in body.splitlines() if 'alt="REMAINDER:' in line)
    return body.replace(
        summary, summary.replace(files_badge, f"{doc_metric} {files_badge}")
    ).replace(remainder, f"- {doc_group}\n{remainder}")


def bounded_diff_body_with_binary_only_category() -> str:
    body = bounded_diff_body(101)
    group = next(line for line in body.splitlines() if line.startswith("- <picture>"))
    first_file = next(line for line in body.splitlines() if line.startswith("  - [`"))
    binary_file = (
        first_file.split(") ", 1)[0]
        + ") "
        + badge("BINARY", "BINARY-5F6B78", title="BINARY")
    )
    other_group = " ".join(
        [
            badge(
                "OTHER: 0 additions, 0 deletions",
                "OTHER-%2B0%20%E2%88%920-57606A",
            ),
            badge("FILES: 1 shown other file", "FILES-1-5F6B78"),
        ]
    )
    remainder = next(line for line in body.splitlines() if 'alt="REMAINDER:' in line)
    return (
        body.replace(
            group,
            group.replace(
                "FILES: 100 shown implementation files",
                "FILES: 99 shown implementation files",
            ).replace("FILES-100-5F6B78", "FILES-99-5F6B78"),
        )
        .replace(first_file + "\n", "")
        .replace(remainder, f"- {other_group}\n{binary_file}\n{remainder}")
    )


def complete_101_file_body() -> str:
    body = bounded_diff_body(101)
    remainder = next(line for line in body.splitlines() if 'alt="REMAINDER:' in line)
    comparison = next(
        line for line in body.splitlines() if "Complete immutable comparison" in line
    )
    path = "src/file-100.ts"
    anchor = hashlib.sha256(path.encode()).hexdigest()
    extra_file = (
        f"  - [`{path}`](https://github.com/{REPOSITORY}/pull/{PR_NUMBER}/"
        f"files#diff-{anchor}) {atomic_metric(1, 0)}"
    )
    return (
        body.replace(
            "FILES: 100 shown implementation files",
            "FILES: 101 implementation files",
        )
        .replace("FILES-100-5F6B78", "FILES-101-5F6B78")
        .replace(remainder, extra_file)
        .replace(comparison + "\n", "")
    )


def pr131_shaped_diff_body() -> str:
    groups = (
        ("IMPL", "implementation", "0969DA", 200, 55),
        ("TEST", "test", "6F5F9A", 100, 1),
        ("DOC", "documentation", "3F7770", 150, 41),
        ("GEN", "generated", "76652F", 100, 1),
        ("OTHER", "other", "57606A", 80, 2),
    )
    summary_badges = [badge("DIFF", "DIFF-57606A", style="for-the-badge")]
    summary_badges.extend(
        badge(
            f"{category}: {additions} additions, 0 deletions",
            f"{category}-%2B{additions}%20%E2%88%920-{color}",
        )
        for category, _, color, additions, _ in groups
    )
    summary_badges.append(badge("FILES: 630 touched", "FILES-630-5F6B78"))
    summary = " ".join(summary_badges).replace("</picture> ", "</picture>&nbsp;", 1)
    expansion = []
    for category, descriptor, color, additions, shown in groups:
        file_noun = "file" if shown == 1 else "files"
        expansion.append(
            "- "
            + badge(
                f"{category}: {additions} additions, 0 deletions",
                f"{category}-%2B{additions}%20%E2%88%920-{color}",
            )
            + " "
            + badge(
                f"FILES: {shown} shown {descriptor} {file_noun}",
                f"FILES-{shown}-5F6B78",
            )
        )
        for index in range(shown):
            path = f"{category.lower()}/file-{index:03}.txt"
            anchor = hashlib.sha256(path.encode()).hexdigest()
            expansion.append(
                f"  - [`{path}`](https://github.com/{REPOSITORY}/pull/"
                f"{PR_NUMBER}/files#diff-{anchor}) {atomic_metric(1, 0)}"
            )
    return "\n".join(
        [
            "<details>",
            f"<summary>{summary}</summary>",
            "",
            *expansion,
            f"- {badge('REMAINDER: 530 changed files', 'REMAINDER-%2B530%20MORE-5F6B78')}",
            (
                f"  - [Complete immutable comparison](https://github.com/"
                f"{REPOSITORY}/compare/{BASE_SHA}...{HEAD_SHA})"
            ),
            "",
            "</details>",
            "",
        ]
    )


class BoundedDiffTests(unittest.TestCase):
    def test_accepts_100_files_as_a_complete_inventory_without_remainder(self) -> None:
        self.assertEqual(
            PRODUCTION_VALIDATE(
                complete_diff_body(100),
                REPOSITORY,
                PR_NUMBER,
                BASE_SHA,
                HEAD_SHA,
            ),
            [],
        )

    def test_accepts_101_files_as_100_shown_plus_one_remainder(self) -> None:
        self.assertEqual(
            PRODUCTION_VALIDATE(
                bounded_diff_body(101),
                REPOSITORY,
                PR_NUMBER,
                BASE_SHA,
                HEAD_SHA,
            ),
            [],
        )

    def test_accepts_sha256_comparison_identity(self) -> None:
        base_sha = "a" * 64
        head_sha = "b" * 64
        body = bounded_diff_body(101).replace(BASE_SHA, base_sha).replace(
            HEAD_SHA, head_sha
        )

        self.assertEqual(
            PRODUCTION_VALIDATE(
                body,
                REPOSITORY,
                PR_NUMBER,
                base_sha,
                head_sha,
            ),
            [],
        )

    def test_accepts_a_full_category_with_zero_files_in_the_shown_set(self) -> None:
        self.assertEqual(
            PRODUCTION_VALIDATE(
                bounded_diff_body_with_omitted_category(),
                REPOSITORY,
                PR_NUMBER,
                BASE_SHA,
                HEAD_SHA,
            ),
            [],
        )

    def test_rejects_a_complete_inventory_above_the_100_file_limit(self) -> None:
        self.assertTrue(
            PRODUCTION_VALIDATE(
                complete_101_file_body(),
                REPOSITORY,
                PR_NUMBER,
                BASE_SHA,
                HEAD_SHA,
            )
        )

    def test_accepts_630_files_with_rename_and_binary_rows_in_the_shown_set(
        self,
    ) -> None:
        body = pr131_shaped_diff_body()
        first = next(
            line for line in body.splitlines() if "`impl/file-000.txt`" in line
        )
        binary_row = next(
            line for line in body.splitlines() if "`other/file-001.txt`" in line
        )
        moved = first.replace(
            "`impl/file-000.txt`", "`impl/old-file.txt` → `impl/file-000.txt`"
        ).replace(
            ") <picture>",
            ") " + badge("MOVED", "MOVED-5F6B78", title="MOVED") + " <picture>",
        )
        binary = (
            binary_row.split(") ", 1)[0]
            + ") "
            + badge("BINARY", "BINARY-5F6B78", title="BINARY")
        )
        body = body.replace(first, moved).replace(binary_row, binary)

        self.assertEqual(
            PRODUCTION_VALIDATE(
                body,
                REPOSITORY,
                PR_NUMBER,
                BASE_SHA,
                HEAD_SHA,
            ),
            [],
        )

    def test_accepts_bounded_diff_beneath_complete_stack_totals(self) -> None:
        stack = (
            STACK.replace(
                "IMPL: 9 additions, 3 deletions",
                "IMPL: 101 additions, 0 deletions",
            )
            .replace(
                "IMPL-%2B9%20%E2%88%923-0969DA",
                "IMPL-%2B101%20%E2%88%920-0969DA",
            )
            .replace(
                "FILES: 0 added, 1 modified, 0 removed",
                "FILES: 0 added, 101 modified, 0 removed",
            )
            .replace(
                "FILES-%2B0%20~1%20%E2%88%920-5F6B78",
                "FILES-%2B0%20~101%20%E2%88%920-5F6B78",
            )
        )

        self.assertEqual(
            PRODUCTION_VALIDATE(
                stack + bounded_diff_body(101),
                REPOSITORY,
                PR_NUMBER,
                BASE_SHA,
                HEAD_SHA,
            ),
            [],
        )

    def test_accepts_zero_line_binary_category_beneath_stack_totals(self) -> None:
        stack = (
            STACK.replace(
                "IMPL: 9 additions, 3 deletions",
                "IMPL: 101 additions, 0 deletions",
            )
            .replace(
                "IMPL-%2B9%20%E2%88%923-0969DA",
                "IMPL-%2B101%20%E2%88%920-0969DA",
            )
            .replace(
                "FILES: 0 added, 1 modified, 0 removed",
                "FILES: 0 added, 101 modified, 0 removed",
            )
            .replace(
                "FILES-%2B0%20~1%20%E2%88%920-5F6B78",
                "FILES-%2B0%20~101%20%E2%88%920-5F6B78",
            )
        )

        self.assertEqual(
            PRODUCTION_VALIDATE(
                stack + bounded_diff_body_with_binary_only_category(),
                REPOSITORY,
                PR_NUMBER,
                BASE_SHA,
                HEAD_SHA,
            ),
            [],
        )

    def test_rejects_malformed_bounded_inventory_disclosures(self) -> None:
        body = bounded_diff_body(101)
        remainder = next(
            line for line in body.splitlines() if 'alt="REMAINDER:' in line
        )
        comparison = next(
            line
            for line in body.splitlines()
            if "Complete immutable comparison" in line
        )
        first_file = next(
            line for line in body.splitlines() if line.startswith("  - [`")
        )
        extra_path = "src/extra.ts"
        extra_anchor = hashlib.sha256(extra_path.encode()).hexdigest()
        extra_file = (
            f"  - [`{extra_path}`](https://github.com/{REPOSITORY}/pull/"
            f"{PR_NUMBER}/files#diff-{extra_anchor}) {atomic_metric(1, 0)}"
        )
        group = next(
            line for line in body.splitlines() if line.startswith("- <picture>")
        )
        summary = next(
            line for line in body.splitlines() if line.startswith("<summary>")
        )
        wrong_summary_totals = summary.replace(
            "IMPL: 101 additions", "IMPL: 100 additions"
        ).replace("IMPL-%2B101", "IMPL-%2B100")
        empty_category = "- " + " ".join(
            [
                badge(
                    "OTHER: 0 additions, 0 deletions",
                    "OTHER-%2B0%20%E2%88%920-57606A",
                ),
                badge("FILES: 0 shown other files", "FILES-0-5F6B78"),
            ]
        )
        oversized_count = "9" * 5000
        cases = {
            "missing remainder": body.replace(remainder + "\n", ""),
            "total below shown rows": body.replace(
                "FILES: 101 touched", "FILES: 99 touched"
            ).replace("FILES-101-5F6B78", "FILES-99-5F6B78"),
            "oversized touched total": body.replace(
                "FILES: 101 touched", f"FILES: {oversized_count} touched"
            ).replace(
                "FILES-101-5F6B78", f"FILES-{oversized_count}-5F6B78"
            ),
            "ungrammatical singular remainder": body.replace(
                "REMAINDER: 1 changed file", "REMAINDER: 1 changed files"
            ),
            "incorrect remainder": body.replace(
                "REMAINDER: 1 changed file", "REMAINDER: 2 changed files"
            ).replace("REMAINDER-%2B1%20MORE", "REMAINDER-%2B2%20MORE"),
            "duplicate path": body.replace(first_file, first_file + "\n" + first_file),
            "more than 100 rows": body.replace(
                first_file, first_file + "\n" + extra_file
            ),
            "misleading complete wording": body.replace(
                group, group + "\n  - Complete per-file inventory"
            ),
            "misleading complete wording after disclosure": (
                body + "\nComplete per-file inventory.\n"
            ),
            "misleading unqualified complete wording after disclosure": (
                body + "\nComplete inventory.\n"
            ),
            "mutable comparison": body.replace(
                comparison,
                f"  - [Complete immutable comparison](https://github.com/{REPOSITORY}/compare/main...topic)",
            ),
            "mismatched comparison": body.replace(HEAD_SHA, "c" * 40),
            "wrong full totals": body.replace(summary, wrong_summary_totals),
            "remainder before a category": body.replace(
                f"{remainder}\n{comparison}\n\n</details>", "\n</details>"
            ).replace(group, f"{remainder}\n{comparison}\n{group}"),
            "remainder before a file row": body.replace(
                f"{first_file}\n",
                f"{remainder}\n{comparison}\n{first_file}\n",
            ).replace(
                f"{remainder}\n{comparison}\n\n</details>",
                "\n</details>",
            ),
            "zero-shown zero-line category": body.replace(
                remainder, f"{empty_category}\n{remainder}"
            ),
        }
        for label, broken in cases.items():
            with self.subTest(label=label):
                self.assertTrue(
                    PRODUCTION_VALIDATE(
                        broken,
                        REPOSITORY,
                        PR_NUMBER,
                        BASE_SHA,
                        HEAD_SHA,
                    )
                )


if __name__ == "__main__":
    unittest.main()
