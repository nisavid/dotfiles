"""A leading disclosure must end its raw HTML block before the next block."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from change_navigation.parsing import (
    leading_details_spans,
    validate_details_separation,
)

DISCLOSURE = ["<details>", "<summary>DIFF</summary>", "", "- a row", "</details>"]


def errors_for(lines: list[str]) -> list[str]:
    errors: list[str] = []
    validate_details_separation(lines, errors)
    return errors


class LeadingDetailsSpanTests(unittest.TestCase):
    def test_a_single_disclosure_reports_its_open_and_close_lines(self) -> None:
        self.assertEqual([(0, 4)], leading_details_spans(DISCLOSURE))

    def test_two_leading_disclosures_report_both_spans(self) -> None:
        lines = DISCLOSURE + [""] + DISCLOSURE
        self.assertEqual([(0, 4), (6, 10)], leading_details_spans(lines))

    def test_an_unterminated_disclosure_reports_no_span(self) -> None:
        self.assertEqual(
            [], leading_details_spans(["<details>", "<summary>x</summary>"])
        )


class DetailsSeparationTests(unittest.TestCase):
    def test_a_blank_line_after_the_disclosure_is_clean(self) -> None:
        self.assertEqual([], errors_for(DISCLOSURE + ["", "## Summary"]))

    def test_the_disclosure_ending_the_body_is_clean(self) -> None:
        self.assertEqual([], errors_for(DISCLOSURE))
        self.assertEqual([], errors_for(DISCLOSURE + [""]))

    def test_a_heading_on_the_next_line_is_swallowed_and_rejected(self) -> None:
        errors = errors_for(DISCLOSURE + ["## Summary", "", "Prose."])
        self.assertEqual(1, len(errors), errors)
        self.assertIn("line 6", errors[0])
        self.assertIn("blank", errors[0])
        self.assertIn("swallowed", errors[0])

    def test_prose_on_the_next_line_is_swallowed_and_rejected(self) -> None:
        self.assertEqual(1, len(errors_for(DISCLOSURE + ["Prose immediately after."])))

    def test_an_adjacent_disclosure_is_clean_because_it_stays_valid_html(self) -> None:
        # Stacked bodies place Stack and Diff on consecutive source lines.
        self.assertEqual([], errors_for(DISCLOSURE + DISCLOSURE))

    def test_adjacent_raw_html_is_clean(self) -> None:
        self.assertEqual([], errors_for(DISCLOSURE + ["<sup>taxonomy</sup>"]))

    def test_a_table_row_on_the_next_line_is_rejected(self) -> None:
        self.assertEqual(1, len(errors_for(DISCLOSURE + ["| a | b |"])))

    def test_a_list_item_on_the_next_line_is_rejected(self) -> None:
        self.assertEqual(1, len(errors_for(DISCLOSURE + ["- swallowed bullet"])))

    def test_each_unseparated_disclosure_is_reported_once(self) -> None:
        lines = DISCLOSURE + [
            "",
            "<details>",
            "<summary>x</summary>",
            "</details>",
            "## Next",
        ]
        self.assertEqual(1, len(errors_for(lines)))


if __name__ == "__main__":
    unittest.main()
