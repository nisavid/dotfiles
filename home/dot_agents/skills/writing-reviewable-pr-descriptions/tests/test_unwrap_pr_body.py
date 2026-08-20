"""The unwrap helper repairs exactly what the body validator rejects."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import body_source
import unwrap_pr_body

RICH_BODY = """<details>

<summary>Diff</summary>

- [`a/b.py`](https://example.com/x) <picture><img alt="+1 -0" src="s"></picture>

</details>

## Summary

A paragraph the author wrapped
at a column budget, continuing
across three source lines.

## Changes

- **Publisher:** the description now selects only live guarded mutations
  and excludes chat-only drafting.
- Optional `widgets preview --port 0` run against the demo tree.<br>
  Observed: one loopback URL.<br>
  Cleanup: none required.

| Surface | State |
| --- | --- |
| Publisher | changed |

```bash
python3 validate.py \\
  --repository OWNER/REPO body.md
```

> [!NOTE]
> A quoted note the author wrapped
> across two source lines.
"""


CLEAN_BODY = """## Summary

One paragraph on one source line, however long it runs in the source file.

- One bullet on one source line.<br>
  Observed: an intended break, explicitly encoded.
"""


def words(text: str) -> list[str]:
    """Return the words of ``text`` ignoring break and blockquote markers."""
    stripped = "\n".join(
        body_source.QUOTE_MARKER.sub("", line) for line in text.split("\n")
    )
    return stripped.replace("<br>", " ").split()


class UnwrapTests(unittest.TestCase):
    def test_a_wrapped_paragraph_becomes_one_source_line(self) -> None:
        body = "First line of prose\nand its continuation.\n"
        self.assertEqual(
            "First line of prose and its continuation.\n", unwrap_pr_body.unwrap(body)
        )

    def test_a_wrapped_list_item_keeps_its_bullet_and_joins_its_text(self) -> None:
        body = "- A bullet whose text\n  wrapped here.\n- Second bullet.\n"
        self.assertEqual(
            "- A bullet whose text wrapped here.\n- Second bullet.\n",
            unwrap_pr_body.unwrap(body),
        )

    def test_a_wrapped_blockquote_line_keeps_exactly_one_marker(self) -> None:
        body = "> A quoted sentence\n> wrapped here.\n"
        self.assertEqual(
            "> A quoted sentence wrapped here.\n", unwrap_pr_body.unwrap(body)
        )

    def test_trailing_whitespace_breaks_become_explicit_br(self) -> None:
        body = "Command run.  \nObserved: it passed.\n"
        self.assertEqual(
            "Command run.<br>\nObserved: it passed.\n", unwrap_pr_body.unwrap(body)
        )

    def test_a_body_with_no_offense_is_returned_unchanged(self) -> None:
        self.assertEqual(CLEAN_BODY, unwrap_pr_body.unwrap(CLEAN_BODY))


class InvariantTests(unittest.TestCase):
    """Properties that make unwrapping a published body safe to verify."""

    def test_unwrapping_preserves_every_word_in_order(self) -> None:
        self.assertEqual(words(RICH_BODY), words(unwrap_pr_body.unwrap(RICH_BODY)))

    def test_unwrapping_leaves_no_line_break_offense(self) -> None:
        self.assertEqual(
            [], body_source.wrap_offenses(unwrap_pr_body.unwrap(RICH_BODY))
        )

    def test_unwrapping_is_idempotent(self) -> None:
        once = unwrap_pr_body.unwrap(RICH_BODY)
        self.assertEqual(once, unwrap_pr_body.unwrap(once))

    def test_fenced_code_survives_byte_for_byte(self) -> None:
        fence = (
            "```bash\npython3 validate.py \\\n  --repository OWNER/REPO body.md\n```"
        )
        self.assertIn(fence, unwrap_pr_body.unwrap(RICH_BODY))

    def test_table_rows_stay_one_per_line(self) -> None:
        unwrapped = unwrap_pr_body.unwrap(RICH_BODY)
        self.assertIn("| Publisher | changed |\n", unwrapped)

    def test_disclosure_inventory_rows_stay_one_per_line(self) -> None:
        unwrapped = unwrap_pr_body.unwrap(RICH_BODY)
        self.assertIn("<summary>Diff</summary>\n", unwrapped)
        self.assertEqual(1, unwrapped.count("<picture>"))

    def test_literal_scenario_markers_keep_their_line_positions(self) -> None:
        unwrapped = unwrap_pr_body.unwrap(RICH_BODY).splitlines()
        self.assertTrue(any(line.startswith("- Optional ") for line in unwrapped))
        self.assertTrue(any(line.strip().startswith("Cleanup:") for line in unwrapped))

    def test_a_github_alert_marker_keeps_its_own_line(self) -> None:
        unwrapped = unwrap_pr_body.unwrap(RICH_BODY).splitlines()
        self.assertIn("> [!NOTE]", unwrapped)
        self.assertIn(
            "> A quoted note the author wrapped across two source lines.", unwrapped
        )


class CommandLineTests(unittest.TestCase):
    def test_the_command_writes_the_unwrapped_body_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "body.md"
            path.write_text("First line\nand its continuation.\n", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "unwrap_pr_body.py"),
                    "--in-place",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual(
                "First line and its continuation.\n", path.read_text(encoding="utf-8")
            )


    def test_check_reports_offenses_without_rewriting_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "body.md"
            original = "First line\nand its continuation.\n"
            path.write_text(original, encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "unwrap_pr_body.py"),
                    "--check",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(1, completed.returncode)
            self.assertIn("line 2", completed.stderr)
            self.assertEqual(original, path.read_text(encoding="utf-8"))

    def test_check_succeeds_on_a_body_with_no_offense(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "body.md"
            path.write_text(CLEAN_BODY, encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "unwrap_pr_body.py"),
                    "--check",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)


if __name__ == "__main__":
    unittest.main()
