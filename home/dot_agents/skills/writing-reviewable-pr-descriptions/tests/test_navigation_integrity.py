from __future__ import annotations

import unittest
import hashlib

from test_validate_change_navigation import (
    DIFF,
    MODULE,
    PRODUCTION_VALIDATE,
    STACK,
    atomic_metric,
    badge,
    linked_badge,
)


def stack_document(summary_badges: list[str], item_lines: list[str]) -> str:
    summary = " ".join(summary_badges).replace("</picture> ", "</picture>&nbsp;", 1)
    return "\n".join(
        [
            "<details>",
            f"<summary>{summary}</summary>",
            "",
            *item_lines,
            "",
            "<sup>IMPL means non-test source and configuration. TEST, DOC, GEN, "
            "and OTHER are counted separately. FILES shows added, modified, and "
            "removed files as +, ~, and −.</sup>",
            "",
            "</details>",
            "",
        ]
    )


def split_category_diff() -> str:
    anchor = hashlib.sha256(b"src/widget.ts").hexdigest()
    summary = " ".join(
        [
            badge("DIFF", "DIFF-57606A", style="for-the-badge"),
            badge("IMPL: 5 additions, 2 deletions", "IMPL-%2B5%20%E2%88%922-0969DA"),
            badge("TEST: 4 additions, 1 deletions", "TEST-%2B4%20%E2%88%921-6F5F9A"),
            badge("FILES: 1 touched", "FILES-1-5F6B78"),
        ]
    ).replace("</picture> ", "</picture>&nbsp;", 1)
    link = f"https://github.com/acme/app/pull/2/files#diff-{anchor}"
    return "\n".join(
        [
            "<details>",
            f"<summary>{summary}</summary>",
            "",
            "- "
            + badge("IMPL: 5 additions, 2 deletions", "IMPL-%2B5%20%E2%88%922-0969DA")
            + " "
            + badge("FILES: 1 implementation file", "FILES-1-5F6B78"),
            f"  - [`src/widget.ts`]({link}) " + atomic_metric(5, 2),
            "- "
            + badge("TEST: 4 additions, 1 deletions", "TEST-%2B4%20%E2%88%921-6F5F9A")
            + " "
            + badge("FILES: 1 test file", "FILES-1-5F6B78"),
            f"  - [`src/widget.ts`]({link}) " + atomic_metric(4, 1),
            "",
            "</details>",
            "",
        ]
    )


class NavigationIntegrityTests(unittest.TestCase):
    def test_requires_and_enforces_expected_pr_identity(self) -> None:
        with self.assertRaises(TypeError):
            PRODUCTION_VALIDATE(DIFF)  # type: ignore[call-arg]
        errors = PRODUCTION_VALIDATE(DIFF, "other/repo", 99)
        self.assertTrue(any("must link to PR #99" in error for error in errors))

    def test_rejects_invalid_expected_identity(self) -> None:
        errors = PRODUCTION_VALIDATE(DIFF, "not-a-repository", 0)
        self.assertTrue(any("OWNER/REPO" in error for error in errors))
        self.assertTrue(any("must be positive" in error for error in errors))

    def test_rejects_missing_diff_file_inventory(self) -> None:
        broken = DIFF.replace("  - [`src/widget.ts`]", "  * [`src/widget.ts`]")
        self.assertTrue(
            any("claims 1 files" in error for error in MODULE.validate(broken))
        )

    def test_rejects_missing_stack_inventory_item(self) -> None:
        first_item = next(
            line for line in STACK.splitlines() if line.startswith("- **[#1")
        )
        broken = STACK.replace(first_item + "\n", "") + DIFF
        self.assertTrue(
            any("claims 2 PRs" in error for error in MODULE.validate(broken))
        )

    def test_rejects_linked_metric_badge(self) -> None:
        metric = badge(
            "IMPL: 9 additions, 3 deletions",
            "IMPL-%2B9%20%E2%88%923-0969DA",
        )
        linked = metric.replace("<picture>", '<a href="https://example.com">').replace(
            "</picture>", "</a>"
        )
        broken = DIFF.replace(metric, linked, 1)
        self.assertTrue(any("GitHub PR" in error for error in MODULE.validate(broken)))

    def test_rejects_wrong_category_color(self) -> None:
        broken = DIFF.replace("0969DA?style=flat", "DEADBE?style=flat", 1)
        self.assertTrue(any("0969DA" in error for error in MODULE.validate(broken)))

    def test_rejects_misleading_atomic_metric_text(self) -> None:
        broken = DIFF.replace(
            'alt="9 additions, 3 deletions" title="9 additions, 3 deletions"',
            'alt="0 additions, 0 deletions" title="0 additions, 0 deletions"',
        )
        self.assertTrue(any("must match" in error for error in MODULE.validate(broken)))

    def test_rejects_conflicting_linked_badge_title(self) -> None:
        broken = (STACK + DIFF).replace(
            'title="#1 — feat: base"', 'title="#1 — feat: different"', 1
        )
        self.assertTrue(
            any("destinations differ" in error for error in MODULE.validate(broken))
        )

    def test_rejects_category_total_that_disagrees_with_files(self) -> None:
        broken = DIFF.replace(
            'alt="IMPL: 9 additions, 3 deletions"',
            'alt="IMPL: 10 additions, 3 deletions"',
        )
        self.assertTrue(
            any("file badges total" in error for error in MODULE.validate(broken))
        )

    def test_rejects_stack_item_linking_to_a_different_number(self) -> None:
        broken = (STACK + DIFF).replace(
            "[#1 — feat: base](https://github.com/acme/app/pull/1)",
            "[#1 — feat: base](https://github.com/acme/app/pull/99)",
        )
        self.assertTrue(
            any("links to PR #99" in error for error in MODULE.validate(broken))
        )

    def test_rejects_current_stack_metrics_that_disagree_with_diff(self) -> None:
        broken_stack = STACK.replace(
            'alt="IMPL: 9 additions, 3 deletions"',
            'alt="IMPL: 8 additions, 3 deletions"',
        )
        self.assertTrue(
            any(
                "current Stack item" in error
                for error in MODULE.validate(broken_stack + DIFF)
            )
        )

    def test_rejects_current_stack_file_operations_that_disagree_with_diff(
        self,
    ) -> None:
        broken_stack = STACK.replace(
            "FILES: 0 added, 1 modified, 0 removed",
            "FILES: 0 added, 999 modified, 0 removed",
        ).replace(
            "FILES-%2B0%20~1%20%E2%88%920-5F6B78",
            "FILES-%2B0%20~999%20%E2%88%920-5F6B78",
        )
        self.assertTrue(
            any(
                "file-operation total" in error
                for error in MODULE.validate(broken_stack + DIFF)
            )
        )

    def test_rejects_stack_operation_kinds_that_disagree_with_diff(self) -> None:
        broken_stack = STACK.replace(
            "FILES: 0 added, 1 modified, 0 removed",
            "FILES: 0 added, 0 modified, 0 removed, 1 moved",
        ).replace(
            "FILES-%2B0%20~1%20%E2%88%920-5F6B78",
            "FILES-%2B0%20~0%20%E2%88%920%20MOVED%201-5F6B78",
        )
        self.assertTrue(
            any(
                "file-operation kinds" in error
                for error in MODULE.validate(broken_stack + DIFF)
            )
        )

    def test_accepts_matching_stack_move_or_copy_operation(self) -> None:
        file_line = next(line for line in DIFF.splitlines() if line.startswith("  - ["))
        for operation in ("MOVED", "COPIED"):
            with self.subTest(operation=operation):
                changed_file = file_line.replace(
                    "`src/widget.ts`", "`src/old.ts` → `src/widget.ts`"
                ).replace(
                    ") <picture>",
                    ") "
                    + badge(operation, f"{operation}-5F6B78", title=operation)
                    + " <picture>",
                )
                changed_diff = DIFF.replace(file_line, changed_file)
                changed_stack = STACK.replace(
                    "FILES: 0 added, 1 modified, 0 removed",
                    f"FILES: 0 added, 0 modified, 0 removed, 1 {operation.lower()}",
                ).replace(
                    "FILES-%2B0%20~1%20%E2%88%920-5F6B78",
                    f"FILES-%2B0%20~0%20%E2%88%920%20{operation}%201-5F6B78",
                )
                self.assertEqual(MODULE.validate(changed_stack + changed_diff), [])

    def test_rejects_visual_metric_that_disagrees_with_alt_text(self) -> None:
        broken = DIFF.replace("IMPL-%2B9%20%E2%88%923", "IMPL-%2B999%20%E2%88%923")
        self.assertTrue(
            any("visual badge" in error for error in MODULE.validate(broken))
        )

    def test_rejects_anchor_that_does_not_match_path(self) -> None:
        anchor_start = DIFF.index("#diff-") + len("#diff-")
        broken = DIFF[:anchor_start] + "0" * 64 + DIFF[anchor_start + 64 :]
        self.assertTrue(
            any("anchor does not match" in error for error in MODULE.validate(broken))
        )

    def test_rejects_multiple_atomic_badges_for_one_file(self) -> None:
        file_line = next(
            line
            for line in DIFF.splitlines()
            if line.startswith("  - [`src/widget.ts`]")
        )
        metric = file_line.split(") ", 1)[1]
        broken = DIFF.replace(file_line, f"{file_line} {metric}")
        self.assertTrue(
            any("exactly one" in error for error in MODULE.validate(broken))
        )

    def test_rejects_extra_supported_badge_on_file_item(self) -> None:
        file_line = next(
            line
            for line in DIFF.splitlines()
            if line.startswith("  - [`src/widget.ts`]")
        )
        extra = badge("FILES: 1 touched", "FILES-1-5F6B78")
        broken = DIFF.replace(file_line, f"{file_line} {extra}")
        self.assertTrue(
            any("no other badges" in error for error in MODULE.validate(broken))
        )
        trailing_text = DIFF.replace(file_line, f"{file_line} extra")
        self.assertTrue(
            any(
                "only its link and allowed badges" in error
                for error in MODULE.validate(trailing_text)
            )
        )

    def test_rejects_duplicate_file_with_inflated_touched_count(self) -> None:
        broken = DIFF.replace(
            "IMPL: 9 additions, 3 deletions", "IMPL: 18 additions, 6 deletions"
        ).replace("IMPL-%2B9%20%E2%88%923", "IMPL-%2B18%20%E2%88%926")
        broken = broken.replace("FILES: 1 touched", "FILES: 2 touched").replace(
            "FILES-1-5F6B78", "FILES-2-5F6B78", 1
        )
        broken = broken.replace(
            "FILES: 1 implementation file", "FILES: 2 implementation files"
        ).replace("FILES-1-5F6B78", "FILES-2-5F6B78", 1)
        file_line = next(
            line
            for line in broken.splitlines()
            if line.startswith("  - [`src/widget.ts`]")
        )
        broken = broken.replace(file_line, f"{file_line}\n{file_line}")
        errors = MODULE.validate(broken)
        self.assertTrue(any("must not repeat" in error for error in errors))
        self.assertTrue(any("1 unique files" in error for error in errors))

    def test_accepts_one_file_split_across_auditable_categories(self) -> None:
        self.assertEqual(MODULE.validate(split_category_diff()), [])

    def test_rejects_unconsumed_diff_list_rows_and_prose(self) -> None:
        file_line = next(line for line in DIFF.splitlines() if line.startswith("  - ["))
        group = next(
            line for line in DIFF.splitlines() if line.startswith("- <picture>")
        )
        cases = (
            DIFF.replace(group, file_line + "\n" + group),
            DIFF.replace(group, "* unexpected row\n" + group),
            DIFF.replace(group, "unexpected prose\n" + group),
        )
        for broken in cases:
            with self.subTest(broken=broken):
                self.assertTrue(
                    any(
                        "unsupported content" in error
                        for error in MODULE.validate(broken)
                    )
                )

    def test_rejects_unconsumed_stack_rows_and_residual_item_content(self) -> None:
        first = next(line for line in STACK.splitlines() if line.startswith("- **[#1"))
        binary = badge("BINARY", "BINARY-5F6B78", title="BINARY")
        cases = (
            STACK.replace(first, first + "\n" + first.replace("- **[#1", "* **[#1")),
            STACK.replace(first, first + " trailing text"),
            STACK.replace(first, first + " " + binary),
        )
        for broken_stack in cases:
            with self.subTest(broken_stack=broken_stack):
                self.assertTrue(MODULE.validate(broken_stack + DIFF))

    def test_accepts_one_documented_stack_context_line(self) -> None:
        contextual = STACK.replace(
            "\n</details>",
            "\n(#99, the former base, is now merged.)\n\n</details>",
        )
        self.assertEqual(MODULE.validate(contextual + DIFF), [])

    def test_rejects_noncanonical_taxonomy_and_block_context(self) -> None:
        taxonomy = next(line for line in STACK.splitlines() if line.startswith("<sup>"))
        binary = badge("BINARY", "BINARY-5F6B78", title="BINARY")
        invalid_taxonomy = STACK.replace(taxonomy, f"<sup>{binary}</sup>")
        self.assertTrue(
            any(
                "canonical taxonomy" in error
                for error in MODULE.validate(invalid_taxonomy + DIFF)
            )
        )
        for context in (
            "## Fake Stack",
            "> quoted",
            "| table | row |",
            "```code```",
            "***",
            "[reference]: https://example.com",
            "<table><tr><td>fake</td></tr></table>",
            "![image](https://example.com/image.png)",
        ):
            with self.subTest(context=context):
                broken = STACK.replace("\n</details>", f"\n{context}\n</details>")
                self.assertTrue(
                    any(
                        "unsupported residual" in error
                        for error in MODULE.validate(broken + DIFF)
                    )
                )

    def test_rejects_duplicate_stack_pr(self) -> None:
        first = next(line for line in STACK.splitlines() if line.startswith("- **[#1"))
        second = next(line for line in STACK.splitlines() if line.startswith("- **[#2"))
        duplicate = first.replace("<br>", " **← this PR**<br>")
        broken = STACK.replace(second, duplicate) + DIFF
        self.assertTrue(
            any("must not repeat" in error for error in MODULE.validate(broken))
        )

    def test_rejects_plural_mismatch(self) -> None:
        broken = DIFF.replace("1 implementation file", "1 implementation files")
        self.assertTrue(
            any("must use file" in error for error in MODULE.validate(broken))
        )

    def test_ignores_badges_in_a_later_unrelated_disclosure(self) -> None:
        unrelated = (
            "<details>\n<summary>Extra</summary>\n"
            '<picture><img alt="EXTRA" src="https://img.shields.io/badge/EXTRA-red">'
            "</picture>\n</details>\n"
        )
        self.assertEqual(MODULE.validate(DIFF + unrelated), [])

        documented_navigation = (
            "<details>\n<summary>Navigation markup example</summary>\n"
            "```html\n"
            + badge("DIFF", "DIFF-57606A", style="for-the-badge")
            + "\n```\n</details>\n"
        )
        self.assertEqual(MODULE.validate(DIFF + documented_navigation), [])

    def test_rejects_interposed_or_later_change_navigation_disclosures(self) -> None:
        unrelated = "<details>\n<summary>Extra</summary>\nExtra\n</details>\n"
        cases = (
            DIFF + unrelated + STACK,
            DIFF + "\n## Summary\nBody\n\n" + DIFF,
            DIFF
            + "\n## Summary\nBody\n\n"
            + DIFF.replace("<details>", "<details open>", 1),
            STACK + unrelated + DIFF,
        )
        for broken in cases:
            with self.subTest(broken=broken):
                self.assertTrue(
                    any(
                        "canonical prefix" in error or "disclosure order" in error
                        for error in MODULE.validate(broken)
                    )
                )

    def test_ignores_change_navigation_markup_inside_a_code_fence(self) -> None:
        example = "```md\n" + STACK + "```\n"
        self.assertEqual(MODULE.validate(DIFF + example), [])

    def test_accepts_edited_move_with_old_and_new_path(self) -> None:
        file_line = next(
            line
            for line in DIFF.splitlines()
            if line.startswith("  - [`src/widget.ts`]")
        )
        moved = file_line.replace("`src/widget.ts`", "`src/old.ts` → `src/widget.ts`")
        moved = moved.replace(
            ") <picture>",
            ") " + badge("MOVED", "MOVED-5F6B78", title="MOVED") + " <picture>",
        )
        self.assertEqual(MODULE.validate(DIFF.replace(file_line, moved)), [])

    def test_rejects_mixed_operation_kinds_for_one_target_path(self) -> None:
        diff = split_category_diff()
        file_line = next(line for line in diff.splitlines() if line.startswith("  - ["))
        moved = file_line.replace("`src/widget.ts`", "`src/old.ts` → `src/widget.ts`")
        moved = moved.replace(
            ") <picture>",
            ") " + badge("MOVED", "MOVED-5F6B78", title="MOVED") + " <picture>",
        )
        broken = diff.replace(file_line, moved, 1)
        self.assertTrue(
            any("one operation kind" in error for error in MODULE.validate(broken))
        )

    def test_rejects_mixed_operation_sources_for_one_target_path(self) -> None:
        diff = split_category_diff()
        file_lines = [line for line in diff.splitlines() if line.startswith("  - [")]
        moved_rows = []
        for source_path, file_line in zip(
            ("src/first.ts", "src/second.ts"), file_lines
        ):
            moved_rows.append(
                file_line.replace(
                    "`src/widget.ts`", f"`{source_path}` → `src/widget.ts`"
                ).replace(
                    ") <picture>",
                    ") " + badge("MOVED", "MOVED-5F6B78", title="MOVED") + " <picture>",
                )
            )
        broken = diff
        for file_line, moved in zip(file_lines, moved_rows):
            broken = broken.replace(file_line, moved, 1)
        self.assertTrue(
            any("source path" in error for error in MODULE.validate(broken))
        )

    def test_rejects_move_or_copy_badge_after_line_metrics(self) -> None:
        file_line = next(
            line
            for line in DIFF.splitlines()
            if line.startswith("  - [`src/widget.ts`]")
        )
        for operation in ("MOVED", "COPIED"):
            with self.subTest(operation=operation):
                changed = file_line.replace(
                    "`src/widget.ts`", "`src/old.ts` → `src/widget.ts`"
                )
                changed += " " + badge(
                    operation, f"{operation}-5F6B78", title=operation
                )
                self.assertTrue(
                    any(
                        "must order" in error
                        for error in MODULE.validate(DIFF.replace(file_line, changed))
                    )
                )

    def test_rejects_move_badge_without_old_and_new_path(self) -> None:
        file_line = next(
            line
            for line in DIFF.splitlines()
            if line.startswith("  - [`src/widget.ts`]")
        )
        moved = file_line.replace(
            ") <picture>",
            ") " + badge("MOVED", "MOVED-5F6B78", title="MOVED") + " <picture>",
        )
        self.assertTrue(
            any(
                "source and target" in error
                for error in MODULE.validate(DIFF.replace(file_line, moved))
            )
        )

    def test_accepts_literal_arrow_in_an_ordinary_filename(self) -> None:
        file_line = next(line for line in DIFF.splitlines() if line.startswith("  - ["))
        path = "src/a → b.ts"
        old_anchor = hashlib.sha256(b"src/widget.ts").hexdigest()
        new_anchor = hashlib.sha256(path.encode()).hexdigest()
        changed = file_line.replace("src/widget.ts", path).replace(
            old_anchor, new_anchor
        )
        self.assertEqual(MODULE.validate(DIFF.replace(file_line, changed)), [])

    def test_accepts_literal_arrows_inside_structured_move_paths(self) -> None:
        file_line = next(line for line in DIFF.splitlines() if line.startswith("  - ["))
        source_path = "src/old → archive.ts"
        target_path = "src/new → final.ts"
        old_anchor = hashlib.sha256(b"src/widget.ts").hexdigest()
        new_anchor = hashlib.sha256(target_path.encode()).hexdigest()
        moved = file_line.replace(
            "`src/widget.ts`", f"`{source_path}` → `{target_path}`"
        ).replace(old_anchor, new_anchor)
        moved = moved.replace(
            ") <picture>",
            ") " + badge("MOVED", "MOVED-5F6B78", title="MOVED") + " <picture>",
        )
        self.assertEqual(MODULE.validate(DIFF.replace(file_line, moved)), [])

    def test_rejects_diff_link_to_another_pr(self) -> None:
        broken = (STACK + DIFF).replace(
            "https://github.com/acme/app/pull/2/files",
            "https://github.com/other/repo/pull/999/files",
        )
        self.assertTrue(
            any("must link to PR #2" in error for error in MODULE.validate(broken))
        )

    def test_rejects_dep_that_repeats_base(self) -> None:
        dependency = linked_badge(1, "DEP: #1 — feat: base", "DEP-%231-5F6B78")
        broken_stack = STACK.replace(
            linked_badge(1, "BASE: #1 — feat: base", "BASE-%231-5F6B78"),
            linked_badge(1, "BASE: #1 — feat: base", "BASE-%231-5F6B78")
            + " "
            + dependency,
        )
        self.assertTrue(
            any(
                "must not repeat BASE" in error
                for error in MODULE.validate(broken_stack + DIFF)
            )
        )

    def test_rejects_transitive_stack_member_as_dep(self) -> None:
        first, second = [
            line for line in STACK.splitlines() if line.startswith("- **[#")
        ]
        first_metrics = first.split("<br>", 1)[1]
        second_metrics = second.split("<br>", 1)[1]
        summary = [
            badge("STACK", "STACK-57606A", style="for-the-badge"),
            badge("STACK POSITION: 3 OF 3", "3%20OF%203-5F6B78"),
            linked_badge(2, "BASE: #2 — feat: middle", "BASE-%232-5F6B78"),
            linked_badge(1, "DEP: #1 — feat: base", "DEP-%231-5F6B78"),
            badge("STACK STATUS: TOP", "TOP-5F6B78"),
        ]
        stack = stack_document(
            summary,
            [
                "- **[#1 — feat: base](https://github.com/acme/app/pull/1)**<br>"
                + first_metrics,
                "- **[#2 — feat: middle](https://github.com/acme/app/pull/2)**<br>"
                + first_metrics,
                "- **[#3 — feat: top](https://github.com/acme/app/pull/3)** "
                "**← this PR**<br>" + second_metrics,
            ],
        )
        diff = DIFF.replace("/pull/2/files", "/pull/3/files")
        errors = PRODUCTION_VALIDATE(stack + diff, "acme/app", 3)
        self.assertTrue(any("any Stack inventory PR" in error for error in errors))

    def test_rejects_bottom_base_that_points_into_stack(self) -> None:
        first, second = [
            line for line in STACK.splitlines() if line.startswith("- **[#")
        ]
        first_metrics = first.split("<br>", 1)[1]
        second_metrics = second.split("<br>", 1)[1]
        stack = stack_document(
            [
                badge("STACK", "STACK-57606A", style="for-the-badge"),
                badge("STACK POSITION: 1 OF 2", "1%20OF%202-5F6B78"),
                linked_badge(2, "BASE: #2 — feat: top", "BASE-%232-5F6B78"),
                linked_badge(2, "NEXT: #2 — feat: top", "NEXT-%232-5F6B78"),
            ],
            [
                "- **[#1 — feat: base](https://github.com/acme/app/pull/1)** "
                "**← this PR**<br>" + second_metrics,
                "- **[#2 — feat: top](https://github.com/acme/app/pull/2)**<br>"
                + first_metrics,
            ],
        )
        diff = DIFF.replace("/pull/2/files", "/pull/1/files")
        errors = PRODUCTION_VALIDATE(stack + diff, "acme/app", 1)
        self.assertTrue(any("outside the Stack inventory" in error for error in errors))

    def test_requires_bottom_pr_base_to_link_to_its_pr(self) -> None:
        first, second = [
            line for line in STACK.splitlines() if line.startswith("- **[#")
        ]
        first_metrics = first.split("<br>", 1)[1]
        second_metrics = second.split("<br>", 1)[1]
        stack = stack_document(
            [
                badge("STACK", "STACK-57606A", style="for-the-badge"),
                badge("STACK POSITION: 1 OF 2", "1%20OF%202-5F6B78"),
                badge(
                    "BASE: #99 — feat: external",
                    "BASE-%2399-5F6B78",
                    title="#99 — feat: external",
                ),
                linked_badge(2, "NEXT: #2 — feat: top", "NEXT-%232-5F6B78"),
            ],
            [
                "- **[#1 — feat: base](https://github.com/acme/app/pull/1)** "
                "**← this PR**<br>" + second_metrics,
                "- **[#2 — feat: top](https://github.com/acme/app/pull/2)**<br>"
                + first_metrics,
            ],
        )
        diff = DIFF.replace("/pull/2/files", "/pull/1/files")
        errors = PRODUCTION_VALIDATE(stack + diff, "acme/app", 1)
        self.assertTrue(any("PR-valued BASE must link" in error for error in errors))

    def test_accepts_unlinked_branch_base_on_bottom_pr(self) -> None:
        first, second = [
            line for line in STACK.splitlines() if line.startswith("- **[#")
        ]
        first_metrics = first.split("<br>", 1)[1]
        second_metrics = second.split("<br>", 1)[1]
        stack = stack_document(
            [
                badge("STACK", "STACK-57606A", style="for-the-badge"),
                badge("STACK POSITION: 1 OF 2", "1%20OF%202-5F6B78"),
                badge("BASE: main", "BASE-main-5F6B78"),
                linked_badge(2, "NEXT: #2 — feat: top", "NEXT-%232-5F6B78"),
            ],
            [
                "- **[#1 — feat: base](https://github.com/acme/app/pull/1)** "
                "**← this PR**<br>" + second_metrics,
                "- **[#2 — feat: top](https://github.com/acme/app/pull/2)**<br>"
                + first_metrics,
            ],
        )
        diff = DIFF.replace("/pull/2/files", "/pull/1/files")
        self.assertEqual(PRODUCTION_VALIDATE(stack + diff, "acme/app", 1), [])

    def test_accepts_stack_move_and_copy_counts_in_alt_and_visual(self) -> None:
        broken = STACK.replace(
            'alt="FILES: 1 added, 0 modified, 0 removed"',
            'alt="FILES: 1 added, 0 modified, 0 removed, 1 moved, 2 copied"',
            1,
        ).replace(
            "FILES-%2B1%20~0%20%E2%88%920-5F6B78",
            "FILES-%2B1%20~0%20%E2%88%920%20MOVED%201%20COPIED%202-5F6B78",
            1,
        )
        self.assertEqual(MODULE.validate(broken + DIFF), [])

    def test_rejects_noncanonical_stack_file_operations(self) -> None:
        cases = (
            (
                "FILES: 1 added, 0 modified, 0 removed bananas",
                "FILES-1-5F6B78",
            ),
            (
                "FILES: 1 added, 0 modified, 0 removed, 1 copied, 2 moved",
                "FILES-1-5F6B78",
            ),
            (
                "FILES: 1 added, 0 modified, 0 removed, 0 moved",
                "FILES-1-5F6B78",
            ),
        )
        for text, visual in cases:
            with self.subTest(text=text):
                broken = STACK.replace(
                    "FILES: 1 added, 0 modified, 0 removed", text, 1
                ).replace("FILES-%2B1%20~0%20%E2%88%920-5F6B78", visual, 1)
                self.assertTrue(
                    any(
                        "file-operation metrics" in error
                        for error in MODULE.validate(broken + DIFF)
                    )
                )

    def test_rejects_wrong_group_descriptor(self) -> None:
        broken = DIFF.replace("FILES: 1 implementation file", "FILES: 1 test file")
        self.assertTrue(MODULE.validate(broken))

    def test_rejects_duplicate_summary_pair_on_one_line(self) -> None:
        broken = DIFF.replace("</summary>", "</summary><summary></summary>", 1)
        self.assertTrue(
            any(
                "exactly one summary pair" in error for error in MODULE.validate(broken)
            )
        )

    def test_rejects_data_attributes_that_masquerade_as_real_attributes(self) -> None:
        cases = {
            "src": DIFF.replace(" src=", " data-src="),
            "height": DIFF.replace(" height=", " data-height="),
            "title": DIFF.replace(" title=", " data-title="),
        }
        for attribute, broken in cases.items():
            with self.subTest(attribute=attribute):
                self.assertTrue(MODULE.validate(broken))

    def test_rejects_data_src_on_a_single_stack_inventory_badge(self) -> None:
        stack_item = next(
            line for line in STACK.splitlines() if line.startswith("- **[#1")
        )
        broken_item = stack_item.replace(" src=", " data-src=", 1)
        errors = MODULE.validate(STACK.replace(stack_item, broken_item) + DIFF)
        self.assertTrue(
            any("structurally valid Shields badge" in error for error in errors)
        )

    def test_rejects_data_src_on_a_single_diff_group_badge(self) -> None:
        group = next(
            line for line in DIFF.splitlines() if line.startswith("- <picture>")
        )
        broken_group = group.replace(" src=", " data-src=", 1)
        errors = MODULE.validate(DIFF.replace(group, broken_group))
        self.assertTrue(
            any("structurally valid Shields badge" in error for error in errors)
        )

    def test_requires_exact_image_attribute_and_title_cardinality(self) -> None:
        duplicate_height = DIFF.replace(
            '<img alt="DIFF"', '<img alt="DIFF" height="99"', 1
        )
        duplicate_alt = DIFF.replace('<img alt="DIFF"', '<img alt="DIFF" alt="DIFF"', 1)
        duplicate_src = DIFF.replace(
            'src="https://img.shields.io/badge/DIFF-57606A?style=for-the-badge"',
            'src="https://img.shields.io/badge/DIFF-57606A?style=for-the-badge" '
            'src="https://img.shields.io/badge/DIFF-57606A?style=for-the-badge"',
            1,
        )
        misleading_title = DIFF.replace(
            '<img alt="IMPL: 9 additions, 3 deletions"',
            '<img alt="IMPL: 9 additions, 3 deletions" '
            'title="0 additions, 999 deletions"',
            1,
        )
        for broken in (
            duplicate_height,
            duplicate_alt,
            duplicate_src,
            misleading_title,
        ):
            with self.subTest(broken=broken):
                self.assertTrue(MODULE.validate(broken))

    def test_accepts_html_code_link_for_path_containing_backticks(self) -> None:
        file_line = next(line for line in DIFF.splitlines() if line.startswith("  - ["))
        metric = file_line.split(") ", 1)[1]
        path = "src/weird`name&more.ts"
        anchor = hashlib.sha256(path.encode()).hexdigest()
        html_line = (
            '<a href="https://github.com/acme/app/pull/2/files#diff-'
            f'{anchor}"><code>src/weird`name&amp;more.ts</code></a> {metric}'
        )
        html_line = "  - " + html_line
        self.assertEqual(MODULE.validate(DIFF.replace(file_line, html_line)), [])

    def test_accepts_structured_html_move_paths_containing_backticks(self) -> None:
        file_line = next(line for line in DIFF.splitlines() if line.startswith("  - ["))
        atomic = file_line.split(") ", 1)[1]
        target_path = "src/new`name → final.ts"
        anchor = hashlib.sha256(target_path.encode()).hexdigest()
        html_line = (
            '  - <a href="https://github.com/acme/app/pull/2/files#diff-'
            f'{anchor}"><code>src/old`name&amp;archive.ts</code> → '
            "<code>src/new`name → final.ts</code></a> "
            + badge("MOVED", "MOVED-5F6B78", title="MOVED")
            + " "
            + atomic
        )
        self.assertEqual(MODULE.validate(DIFF.replace(file_line, html_line)), [])

    def test_rejects_noncanonical_html_code_file_links(self) -> None:
        file_line = next(line for line in DIFF.splitlines() if line.startswith("  - ["))
        metric = file_line.split(") ", 1)[1]
        cases = ("src/ordinary.ts", "src/weird`name&more.ts")
        for path in cases:
            with self.subTest(path=path):
                anchor = hashlib.sha256(path.encode()).hexdigest()
                html_line = (
                    '  - <a href="https://github.com/acme/app/pull/2/files#diff-'
                    f'{anchor}"><code>{path}</code></a> {metric}'
                )
                self.assertTrue(MODULE.validate(DIFF.replace(file_line, html_line)))

    def test_requires_semantic_html_attribute_escaping(self) -> None:
        raw = STACK.replace("feat: base", "feat: base & firm")
        errors = MODULE.validate(raw + DIFF)
        self.assertTrue(any("canonical HTML escaping" in error for error in errors))
        encoded = (
            raw.replace(
                'alt="BASE: #1 — feat: base & firm"',
                'alt="BASE: #1 — feat: base &amp; firm"',
            )
            .replace(
                'title="#1 — feat: base & firm"',
                'title="#1 — feat: base &amp; firm"',
            )
            .replace(
                "[#1 — feat: base & firm]",
                "[#1 — feat: base &amp; firm]",
            )
        )
        self.assertEqual(MODULE.validate(encoded + DIFF), [])

    def test_rejects_unescaped_markdown_in_stack_titles(self) -> None:
        for title in (
            "feat: [docs](https://evil.example)",
            "feat: **bold**",
            "feat: `code`",
        ):
            with self.subTest(title=title):
                broken = STACK.replace("[#1 — feat: base]", f"[#1 — {title}]")
                errors = MODULE.validate(broken + DIFF)
                self.assertTrue(
                    any("canonical Markdown escaping" in error for error in errors)
                )

    def test_accepts_canonical_markdown_and_html_escaping_in_stack_titles(self) -> None:
        attribute_title = "feat: [docs] &amp; **safe** `code`"
        visible_title = r"feat: \[docs\] &amp; \*\*safe\*\* \`code\`"
        encoded = (
            STACK.replace(
                'alt="BASE: #1 — feat: base"',
                f'alt="BASE: #1 — {attribute_title}"',
            )
            .replace(
                'title="#1 — feat: base"',
                f'title="#1 — {attribute_title}"',
            )
            .replace("[#1 — feat: base]", f"[#1 — {visible_title}]")
        )
        self.assertEqual(MODULE.validate(encoded + DIFF), [])

    def test_rejects_noncanonical_badge_url_encoding(self) -> None:
        for encoded in ("IMPL-+9%20%E2%88%923", "IMPL-%2b9%20%E2%88%923"):
            with self.subTest(encoded=encoded):
                broken = DIFF.replace("IMPL-%2B9%20%E2%88%923", encoded, 1)
                self.assertTrue(
                    any(
                        "canonical percent encoding" in error
                        for error in MODULE.validate(broken)
                    )
                )
        atomic = DIFF.replace("%2B9-%E2%88%923-CF222E", "+9-%E2%88%923-CF222E", 1)
        self.assertTrue(
            any(
                "canonical percent encoding" in error
                for error in MODULE.validate(atomic)
            )
        )

    def test_rejects_non_exact_style_and_extra_shield(self) -> None:
        wrong_style = DIFF.replace("style=flat", "xstyle=flat", 1)
        self.assertTrue(
            any("style=flat" in error for error in MODULE.validate(wrong_style))
        )
        extra = badge("risk", "risk-low-5F6B78")
        broken = DIFF.replace("</summary>", " " + extra + "</summary>", 1)
        self.assertTrue(
            any("unsupported" in error for error in MODULE.validate(broken))
        )


if __name__ == "__main__":
    unittest.main()
