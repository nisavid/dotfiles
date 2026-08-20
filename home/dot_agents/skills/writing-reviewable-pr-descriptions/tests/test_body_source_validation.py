"""The shared body validator rejects misencoded source line breaks."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location(
    "validate_change_navigation", SCRIPTS / "validate_change_navigation.py"
)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules["validate_change_navigation"] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)

WRAPPED = """## Summary

Selecting between two skills was ambiguous at the edges, so this change
states one routing contract on both sides.
"""

UNWRAPPED = """## Summary

Selecting between two skills was ambiguous at the edges, so this change states one routing contract on both sides.
"""


def line_break_errors(body: str) -> list[str]:
    return [
        error
        for error in VALIDATOR.validate(body, "acme/app", 2)
        if "line break" in error or "bare newline" in error
    ]


class BodySourceValidationTests(unittest.TestCase):
    def test_a_wrapped_paragraph_fails_validation(self) -> None:
        errors = line_break_errors(WRAPPED)
        self.assertEqual(1, len(errors), errors)
        self.assertIn("line 4", errors[0])

    def test_an_unwrapped_paragraph_raises_no_line_break_error(self) -> None:
        self.assertEqual([], line_break_errors(UNWRAPPED))

    def test_every_wrapped_line_is_reported_not_only_the_first(self) -> None:
        body = "## Summary\n\nOne\ntwo\nthree\nfour.\n"
        errors = line_break_errors(body)
        self.assertEqual(3, len(errors), errors)
        self.assertEqual(
            ["body line 4", "body line 5", "body line 6"],
            [error.split(" continues")[0] for error in errors],
        )

    def test_the_error_names_the_intended_break_encoding(self) -> None:
        self.assertIn("<br>", line_break_errors(WRAPPED)[0])

    def test_trailing_whitespace_breaks_report_their_own_reason(self) -> None:
        body = "## Summary\n\nCommand run.  \nObserved: it passed.\n"
        errors = line_break_errors(body)
        self.assertEqual(1, len(errors), errors)
        self.assertIn("invisible", errors[0])


if __name__ == "__main__":
    unittest.main()
