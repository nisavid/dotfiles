from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_ROOT = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

from change_navigation.diff_inventory import (
    ChangeFile,
    plan_diff_inventory,
)

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40


class DiffInventoryPlanTests(unittest.TestCase):
    def test_keeps_complete_inventory_at_100_files(self) -> None:
        files = [
            ChangeFile(
                target_path=f"src/file-{index:03}.ts",
                category="IMPL",
                additions=1,
                deletions=0,
            )
            for index in range(100)
        ]

        plan = plan_diff_inventory(
            files,
            repository="acme/app",
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
        )

        self.assertFalse(plan.bounded)
        self.assertEqual(plan.total_files, 100)
        self.assertEqual(plan.shown_files, tuple(files))
        self.assertEqual(plan.remainder_files, 0)
        self.assertEqual(plan.total_additions, 100)
        self.assertEqual(plan.total_deletions, 0)

    def test_bounds_101_files_and_groups_the_first_100_in_source_order(self) -> None:
        categories = ("DOC", "IMPL", "TEST", "GEN", "OTHER")
        files = [
            ChangeFile(
                target_path=f"path-{index:03}",
                category=categories[index % len(categories)],
                additions=index + 1,
                deletions=index % 3,
            )
            for index in range(101)
        ]

        plan = plan_diff_inventory(
            files,
            repository="acme/app",
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
        )

        self.assertTrue(plan.bounded)
        self.assertEqual(plan.total_files, 101)
        self.assertEqual(plan.shown_files, tuple(files[:100]))
        self.assertEqual(plan.remainder_files, 1)
        self.assertEqual(
            tuple(plan.shown_by_category), ("IMPL", "TEST", "DOC", "GEN", "OTHER")
        )
        self.assertEqual(
            plan.shown_by_category["DOC"],
            tuple(files[index] for index in range(0, 100, 5)),
        )
        self.assertEqual(plan.total_additions, 5151)
        self.assertEqual(plan.total_deletions, 100)
        self.assertEqual(plan.category_totals["DOC"], (1071, 21))
        self.assertEqual(
            plan.comparison_url,
            f"https://github.com/acme/app/compare/{BASE_SHA}...{HEAD_SHA}",
        )

    def test_requires_immutable_comparison_identity_for_a_bounded_inventory(
        self,
    ) -> None:
        files = [ChangeFile(f"file-{index}", "OTHER", 0, 0) for index in range(101)]

        with self.assertRaisesRegex(ValueError, "repository, base SHA, and head SHA"):
            plan_diff_inventory(files)

    def test_retains_a_full_category_that_has_no_shown_files(self) -> None:
        files = [
            *[ChangeFile(f"src/file-{index}", "IMPL", 1, 0) for index in range(100)],
            ChangeFile("docs/omitted.md", "DOC", 1, 0),
        ]

        plan = plan_diff_inventory(
            files,
            repository="acme/app",
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
        )

        self.assertEqual(tuple(plan.shown_by_category), ("IMPL", "DOC"))
        self.assertEqual(plan.shown_by_category["DOC"], ())
        self.assertEqual(plan.category_totals["DOC"], (1, 0))

    def test_omits_an_unshown_category_with_no_line_totals(self) -> None:
        files = [
            *[ChangeFile(f"src/file-{index}", "IMPL", 1, 0) for index in range(100)],
            ChangeFile("assets/omitted.png", "OTHER", 0, 0, operation="BINARY"),
        ]

        plan = plan_diff_inventory(
            files,
            repository="acme/app",
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
        )

        self.assertEqual(tuple(plan.shown_by_category), ("IMPL",))
        self.assertEqual(plan.category_totals["OTHER"], (0, 0))

    def test_preserves_rename_and_binary_entries_in_a_630_file_selection(
        self,
    ) -> None:
        files = [
            ChangeFile(
                "assets/new.png",
                "IMPL",
                1,
                1,
                source_path="assets/old.png",
                operation="MOVED",
            ),
            ChangeFile("assets/image.png", "OTHER", 0, 0, operation="BINARY"),
            *[
                ChangeFile(f"src/file-{index:03}.ts", "IMPL", 1, 0)
                for index in range(2, 630)
            ],
        ]

        plan = plan_diff_inventory(
            files,
            repository="acme/app",
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
        )

        self.assertEqual(plan.total_files, 630)
        self.assertEqual(len(plan.shown_files), 100)
        self.assertEqual(plan.remainder_files, 530)
        self.assertEqual(plan.shown_files[0].operation, "MOVED")
        self.assertEqual(plan.shown_files[0].source_path, "assets/old.png")
        self.assertEqual(plan.shown_files[1].operation, "BINARY")
        self.assertEqual(plan.total_additions, 629)
        self.assertEqual(plan.total_deletions, 1)

    def test_rejects_duplicate_target_paths_before_selection(self) -> None:
        files = [
            ChangeFile("same", "IMPL", 1, 0),
            ChangeFile("same", "TEST", 1, 0),
        ]

        with self.assertRaisesRegex(ValueError, "duplicate target path"):
            plan_diff_inventory(files)


if __name__ == "__main__":
    unittest.main()
