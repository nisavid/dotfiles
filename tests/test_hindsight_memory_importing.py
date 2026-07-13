from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "home/private_dot_local/lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from hindsight_memory_control_plane.importing import (
    ImportError,
    apply_import_plan,
    build_import_plan,
    inspect_items,
    project_import,
    reconcile_import,
    validate_projection,
)


def record(native_id="m1", content="Prefer exact lease pushes.", **overrides):
    value = {
        "source_locator": "memories/MEMORY.md",
        "source_native_id": native_id,
        "timestamp": "2026-07-01T12:34:56Z",
        "line_start": 10,
        "line_end": 12,
        "content": content,
        "kind": "rule",
        "intended_scope": "repo:dotfiles",
        "relationships": ["repo:dotfiles", "workflow:git-publication"],
        "coverage_disposition": "proposed_novel",
        "coverage_reason": "absent-from-target",
    }
    value.update(overrides)
    return value


class ImportProjectionTest(unittest.TestCase):
    def test_projects_stable_identity_time_provenance_tags_scope_and_relationships(self):
        item = inspect_items("codex", [record()])[0]
        self.assertEqual(len(item.item_id), 64)
        self.assertEqual(item.timestamp, "2026-07-01T12:34:56Z")
        self.assertEqual(item.provenance, {"source_locator": "memories/MEMORY.md", "line_start": 10, "line_end": 12})
        self.assertEqual(item.tags, ("kind:rule", "repo:dotfiles", "scope:active", "source:codex-memory-archive"))
        self.assertEqual(item.intended_scope, "repo:dotfiles")
        self.assertEqual(item.relationships, ("repo:dotfiles", "workflow:git-publication"))
        self.assertEqual(item.coverage_disposition, "proposed_novel")
        with self.assertRaises(FrozenInstanceError):
            item.item_id = "different"

    def test_identity_uses_locator_and_native_id_not_content_or_order(self):
        first = inspect_items("codex", [record(), record("m2", "Use current evidence.")])
        edited = inspect_items("codex", [record("m1", "Updated wording."), record("m2", "Use current evidence.")])
        self.assertEqual(first[0].item_id, edited[0].item_id)
        left = project_import(first)
        right = project_import(tuple(reversed(first)))
        self.assertEqual(left.projection_digest, right.projection_digest)
        self.assertEqual(left.to_dict(), right.to_dict())

    def test_each_source_item_has_exactly_one_closed_coverage_disposition(self):
        for disposition in ("proposed_novel", "proposed_duplicate", "proposed_conflict", "omitted"):
            item = inspect_items("portable-jsonl", [record(coverage_disposition=disposition)])[0]
            self.assertEqual(item.coverage_disposition, disposition)
        for bad in (None, ["omitted", "proposed_novel"], "accepted"):
            with self.assertRaises(ImportError):
                inspect_items("codex", [record(coverage_disposition=bad)])

    def test_closed_records_malformed_time_provenance_tags_and_secret_like_content_fail(self):
        bad_records = [
            record(extra=True),
            record(timestamp="yesterday"),
            record(line_start=13, line_end=12),
            record(kind="credential"),
            record(intended_scope="branch:volatile"),
            record(content="password = hunter2"),
            record(content="-----BEGIN PRIVATE KEY-----"),
        ]
        for value in bad_records:
            with self.subTest(value=value):
                with self.assertRaises(ImportError):
                    inspect_items("claude", [value])

    def test_resume_skips_only_matching_identity_and_content_digest(self):
        items = inspect_items("codex", [record(), record("m2", "Use current evidence.")])
        resume = {items[0].item_id: items[0].content_digest, items[1].item_id: "0" * 64}
        projection = project_import(items, resume_state=resume)
        self.assertEqual(projection.skipped_item_ids, (items[0].item_id,))
        self.assertEqual([item.item_id for item in projection.pending_items], [items[1].item_id])

    def test_projection_validation_detects_tampering(self):
        projection = project_import(inspect_items("codex", [record()]))
        validate_projection(projection)
        object.__setattr__(projection, "projection_digest", "0" * 64)
        with self.assertRaises(ImportError):
            validate_projection(projection)

    def test_plan_is_digest_bound_and_apply_requires_exact_later_approval(self):
        projection = project_import(inspect_items("codex", [record()]))
        plan = build_import_plan(projection, controller_plan_digest="a" * 64)
        calls = []
        with self.assertRaises(ImportError):
            apply_import_plan(plan, approved_plan_digest=None, controller_apply=calls.append)
        with self.assertRaises(ImportError):
            apply_import_plan(plan, approved_plan_digest="b" * 64, controller_apply=calls.append)
        result = apply_import_plan(plan, approved_plan_digest=plan.plan_digest, controller_apply=calls.append)
        self.assertEqual(result, plan.plan_digest)
        self.assertEqual(calls, [plan.to_dict()])

    def test_reconcile_is_complete_only_for_exact_item_and_digest_receipts(self):
        projection = project_import(inspect_items("codex", [record(), record("m2", "Use current evidence.")]))
        receipts = [{"item_id": item.item_id, "content_digest": item.content_digest, "status": "imported"} for item in projection.pending_items]
        result = reconcile_import(projection, receipts)
        self.assertTrue(result.complete)
        self.assertEqual(result.missing_item_ids, ())
        with self.assertRaises(ImportError):
            reconcile_import(projection, [{**receipts[0], "content_digest": "f" * 64}, receipts[1]])


if __name__ == "__main__":
    unittest.main()
