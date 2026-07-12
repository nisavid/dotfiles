from __future__ import annotations

import json
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
TRIGGER_EVALS = SKILL_DIR / "evals" / "trigger-evals.json"


class TriggerEvalContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = json.loads(TRIGGER_EVALS.read_text(encoding="utf-8"))

    def test_schema_and_queries_are_unique(self) -> None:
        self.assertIsInstance(self.items, list)
        self.assertTrue(self.items)
        for item in self.items:
            self.assertIsInstance(item, dict)
            self.assertEqual(set(item), {"query", "should_trigger"})
            self.assertIsInstance(item["query"], str)
            self.assertTrue(item["query"].strip())
            self.assertIsInstance(item["should_trigger"], bool)
        queries = [item["query"] for item in self.items]
        self.assertEqual(len(queries), len(set(queries)))

    def test_required_trigger_boundaries_are_covered(self) -> None:
        cases = {(item["query"], item["should_trigger"]) for item in self.items}
        required = {
            ("Implement the parser in this repository and commit clean checkpoints.", True),
            ("In Codex, implement the parser in this repository and commit clean checkpoints.", True),
            ("In Claude Code, review this repository without changing or publishing it.", True),
            ("Close out this Git branch at the current stopping point.", True),
            ("Explain what git push --force-with-lease means; take no action.", False),
            ("Summarize this pasted diff without accessing a repository or taking action.", False),
        }
        self.assertEqual(required - cases, set())
        self.assertTrue(any(item["should_trigger"] for item in self.items))
        self.assertTrue(any(not item["should_trigger"] for item in self.items))


if __name__ == "__main__":
    unittest.main()
