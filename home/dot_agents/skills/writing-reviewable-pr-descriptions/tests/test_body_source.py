from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import body_source as BODY_SOURCE


class BareNewlineTests(unittest.TestCase):
    def test_paragraph_continued_on_the_next_source_line_is_an_accidental_break(
        self,
    ) -> None:
        body = "One paragraph that the author\nwrapped at some column.\n"
        offenses = BODY_SOURCE.wrap_offenses(body)
        self.assertEqual(
            [(2, "accidental-break")], [(o.line, o.kind) for o in offenses]
        )

    def test_a_wrapped_list_item_continuation_is_an_accidental_break(self) -> None:
        body = "- A bullet whose text the author\n  wrapped at some column.\n"
        self.assertEqual(
            [(2, "accidental-break")],
            [(o.line, o.kind) for o in BODY_SOURCE.wrap_offenses(body)],
        )

    def test_a_lazy_continuation_of_a_blockquote_is_an_accidental_break(self) -> None:
        # CommonMark treats an unprefixed line after a quote as part of it.
        body = "> A quoted sentence the author\nwrapped without the marker.\n"
        self.assertEqual(
            [(2, "accidental-break")],
            [(o.line, o.kind) for o in BODY_SOURCE.wrap_offenses(body)],
        )

    def test_a_wrapped_blockquote_line_is_an_accidental_break(self) -> None:
        body = "> A quoted sentence the author\n> wrapped at some column.\n"
        self.assertEqual(
            [(2, "accidental-break")],
            [(o.line, o.kind) for o in BODY_SOURCE.wrap_offenses(body)],
        )


class BlockBoundaryTests(unittest.TestCase):
    """A new block element on the next line is a boundary, never a wrap."""

    def assert_clean(self, body: str) -> None:
        self.assertEqual([], BODY_SOURCE.wrap_offenses(body))

    def test_blank_line_separated_paragraphs_are_clean(self) -> None:
        self.assert_clean("First paragraph.\n\nSecond paragraph.\n")

    def test_consecutive_list_items_are_clean(self) -> None:
        self.assert_clean("- First bullet.\n- Second bullet.\n* Third.\n+ Fourth.\n")

    def test_consecutive_ordered_list_items_are_clean(self) -> None:
        self.assert_clean("1. First step.\n2. Second step.\n3) Third step.\n")

    def test_nested_list_items_are_clean(self) -> None:
        self.assert_clean("- Parent bullet.\n  - Nested bullet.\n    - Deeper.\n")

    def test_heading_after_paragraph_is_clean(self) -> None:
        self.assert_clean("Trailing paragraph.\n## Changes\nFollowing paragraph.\n")

    def test_table_rows_are_clean(self) -> None:
        self.assert_clean("| a | b |\n| --- | --- |\n| 1 | 2 |\n")

    def test_thematic_break_is_clean(self) -> None:
        self.assert_clean("A paragraph.\n\n---\n\nAnother paragraph.\n")

    def test_paragraph_directly_under_a_setext_underline_is_clean(self) -> None:
        # `---` under a paragraph line is a setext heading underline, so the
        # line above it is heading text and the line below opens a new block.
        self.assert_clean("A heading\n---\nFollowing paragraph.\n")

    def test_a_blockquote_interrupting_a_paragraph_is_clean(self) -> None:
        self.assert_clean("A paragraph.\n> A quote that interrupts it.\n")

    def test_a_deeper_blockquote_level_is_clean(self) -> None:
        self.assert_clean("> Outer quote.\n> > Nested quote.\n")

    def test_link_reference_definition_is_clean(self) -> None:
        self.assert_clean("Text with [a link][ref].\n[ref]: https://example.com/x\n")


class BreakEncodingTests(unittest.TestCase):
    """An intended break stays available; only its encoding is constrained."""

    def kinds(self, body: str) -> list[tuple[int, str]]:
        return [(o.line, o.kind) for o in BODY_SOURCE.wrap_offenses(body)]

    def test_an_explicit_br_encodes_an_intended_break(self) -> None:
        self.assertEqual([], self.kinds("Command run.<br>\nObserved: it passed.\n"))

    def test_a_self_closing_br_encodes_an_intended_break(self) -> None:
        self.assertEqual([], self.kinds("Command run.<br />\nObserved: passed.\n"))

    def test_an_intended_break_is_allowed_at_any_point_in_a_block(self) -> None:
        body = (
            "- `widgets build` succeeded.<br>\n"
            "  Observed: 12 targets.<br>\n"
            "  Cleanup: none required.\n"
        )
        self.assertEqual([], self.kinds(body))

    def test_trailing_spaces_are_an_invisible_break_not_an_accidental_one(self) -> None:
        self.assertEqual(
            [(2, BODY_SOURCE.INVISIBLE_BREAK)],
            self.kinds("Command run.  \nObserved: it passed.\n"),
        )

    def test_a_trailing_backslash_encodes_an_intended_break(self) -> None:
        self.assertEqual([], self.kinds("Command run.\\\nObserved: it passed.\n"))


class SkippedRegionTests(unittest.TestCase):
    """Regions whose newlines are not reader-visible breaks stay untouched."""

    def kinds(self, body: str) -> list[int]:
        return [o.line for o in BODY_SOURCE.wrap_offenses(body)]

    def test_fenced_code_keeps_its_own_line_structure(self) -> None:
        body = (
            "Run this:\n\n```bash\n"
            "python3 validate.py \\\n  --repository OWNER/REPO \\\n  body.md\n"
            "```\n\nThen inspect the output.\n"
        )
        self.assertEqual([], self.kinds(body))

    def test_tilde_fenced_code_keeps_its_own_line_structure(self) -> None:
        self.assertEqual([], self.kinds("~~~\nsome wrapped\ncode text\n~~~\n"))

    def test_a_raw_html_block_collapses_its_own_newlines(self) -> None:
        body = "<table>\n<tr><td>Prose that the author\nwrapped here.</td></tr>\n</table>\n"
        self.assertEqual([], self.kinds(body))

    def test_markdown_after_a_blank_line_inside_details_is_still_checked(self) -> None:
        body = (
            "<details>\n\n<summary>Diff</summary>\n\n"
            "A paragraph the author\nwrapped inside the disclosure.\n\n</details>\n"
        )
        self.assertEqual([6], self.kinds(body))

    def test_a_github_alert_marker_owns_its_own_line(self) -> None:
        body = "> [!NOTE]\n> The alert body must follow on the next line.\n"
        self.assertEqual([], self.kinds(body))

    def test_an_empty_blockquote_line_separates_quoted_blocks(self) -> None:
        self.assertEqual([], self.kinds("> First quoted line.\n>\n> Second block.\n"))


class FenceDelimiterTests(unittest.TestCase):
    """A fence closes only on its own delimiter, at least as long."""

    def kinds(self, body: str) -> list[int]:
        return [o.line for o in BODY_SOURCE.wrap_offenses(body)]

    def test_a_tilde_line_does_not_close_a_backtick_fence(self) -> None:
        body = "```\nwrapped code\n~~~\nstill code\n```\n"
        self.assertEqual([], self.kinds(body))

    def test_a_shorter_run_does_not_close_a_longer_fence(self) -> None:
        body = "````\nwrapped code\n```\nstill code\n````\n"
        self.assertEqual([], self.kinds(body))

    def test_a_longer_run_closes_a_shorter_fence(self) -> None:
        body = "```\ncode\n````\n\nProse.\n"
        self.assertEqual([], self.kinds(body))

    def test_prose_directly_after_a_closing_fence_is_its_own_block(self) -> None:
        # GitHub renders this as a separate paragraph, not a continuation.
        body = "Intro:\n\n```sh\necho hi\n```\nProse after the fence.\n"
        self.assertEqual([], self.kinds(body))

    def test_a_quoted_fence_is_detected_after_stripping_markers(self) -> None:
        body = "> ```\n> wrapped code\n> still code\n> ```\n"
        self.assertEqual([], self.kinds(body))


class HtmlBlockTests(unittest.TestCase):
    """Only a real HTML block exempts its newlines."""

    def kinds(self, body: str) -> list[int]:
        return [o.line for o in BODY_SOURCE.wrap_offenses(body)]

    def test_inline_html_opening_a_paragraph_does_not_exempt_the_wrap(self) -> None:
        # GitHub renders this as one paragraph joined by <br>.
        body = "<span>First</span> some prose\nthat the author wrapped here.\n"
        self.assertEqual([2], self.kinds(body))

    def test_a_block_level_tag_starts_a_raw_html_block(self) -> None:
        body = "<div>First</div>\nthat the author wrapped here.\n"
        self.assertEqual([], self.kinds(body))

    def test_inline_html_cannot_interrupt_a_paragraph(self) -> None:
        body = "Prose that runs on\n<span>and continues here.</span>\n"
        self.assertEqual([2], self.kinds(body))

    def test_a_block_level_tag_may_interrupt_a_paragraph(self) -> None:
        body = "Prose that runs on\n<table><tr><td>cell</td></tr></table>\n"
        self.assertEqual([], self.kinds(body))

    def test_a_script_block_ends_at_its_closing_tag_not_a_blank_line(self) -> None:
        body = "<script>\nvar a = 1;\n</script>\nProse that the author\nwrapped here.\n"
        self.assertEqual([5], self.kinds(body))

    def test_an_html_comment_block_is_exempt(self) -> None:
        body = "<!-- a comment\nspanning lines -->\n\nProse.\n"
        self.assertEqual([], self.kinds(body))


class SetextHeadingTests(unittest.TestCase):
    """A setext underline is a heading, not wrapped prose.

    GitHub renders `===` and a single `=` as H1, and a single `-` as H2, so the
    underline length is not bounded the way a thematic break's is.
    """

    def kinds(self, body: str) -> list[int]:
        return [o.line for o in BODY_SOURCE.wrap_offenses(body)]

    def test_an_equals_underline_of_any_length_is_a_heading(self) -> None:
        for underline in ("=", "==", "===", "======"):
            with self.subTest(underline=underline):
                self.assertEqual([], self.kinds(f"A heading\n{underline}\n"))

    def test_a_dash_underline_of_any_length_is_a_heading(self) -> None:
        for underline in ("-", "--", "---", "------"):
            with self.subTest(underline=underline):
                self.assertEqual([], self.kinds(f"A heading\n{underline}\n"))

    def test_prose_after_a_setext_underline_opens_a_new_block(self) -> None:
        self.assertEqual([], self.kinds("A heading\n===\nFollowing prose.\n"))
        self.assertEqual([], self.kinds("A heading\n=\nFollowing prose.\n"))

    def test_thematic_breaks_remain_boundaries(self) -> None:
        for rule in ("***", "___", "---"):
            with self.subTest(rule=rule):
                self.assertEqual([], self.kinds(f"Prose.\n\n{rule}\n\nMore.\n"))


class QuoteDepthRegressionTests(unittest.TestCase):
    """Pin the CommonMark laziness behavior against a plausible misreading."""

    def test_a_shallower_quote_line_continues_the_nested_paragraph(self) -> None:
        # Verified against GitHub's renderer: `> > nested` then `> outer`
        # produces one nested paragraph joined by <br>, so the quote level does
        # not close and this is a real accidental break.
        body = "> > nested\n> outer\n"
        self.assertEqual(
            [(2, BODY_SOURCE.ACCIDENTAL_BREAK)],
            [(o.line, o.kind) for o in BODY_SOURCE.wrap_offenses(body)],
        )


if __name__ == "__main__":
    unittest.main()
