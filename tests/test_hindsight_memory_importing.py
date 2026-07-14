from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import sys
import tempfile
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
    inspect_source,
    parse_claude_memory,
    parse_codex_memory,
    parse_portable_jsonl,
    parse_portable_markdown,
    project_import,
    reconcile_import,
    validate_projection,
)
from hindsight_memory_control_plane.import_runner import run_import_inspection


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
    def test_curated_codex_and_claude_markdown_adapters_emit_stable_records(self):
        timestamp = "2026-07-01T12:34:56Z"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = root / "MEMORY.md"
            codex.write_text(
                "# Memory\n\n## Safe publication\n\n"
                "Use exact lease pushes with [[repo:dotfiles]] and "
                "[[workflow:git-publication]].\n",
                encoding="utf-8",
            )
            claude = root / "CLAUDE.md"
            claude.write_text(
                "# Claude memory\n\n## Review posture\n\n"
                "Review the claimed behavior, not implementation narration.\n",
                encoding="utf-8",
            )

            codex_record = parse_codex_memory(codex, timestamp=timestamp)[0]
            claude_record = parse_claude_memory(claude, timestamp=timestamp)[0]
            self.assertEqual(codex_record["source_native_id"], "safe-publication")
            self.assertEqual(codex_record["line_start"], 5)
            self.assertEqual(codex_record["line_end"], 5)
            self.assertEqual(
                codex_record["relationships"],
                ["repo:dotfiles", "workflow:git-publication"],
            )
            self.assertEqual(codex_record["intended_scope"], "repo:dotfiles")
            self.assertEqual(claude_record["source_native_id"], "review-posture")

            first = inspect_source("codex", codex, timestamp=timestamp)[0]
            codex.write_text(
                "# Memory\n\n## Safe publication\n\n"
                "Updated guidance for [[repo:dotfiles]].\n",
                encoding="utf-8",
            )
            edited = inspect_source("codex", codex, timestamp=timestamp)[0]
            self.assertEqual(first.item_id, edited.item_id)
            self.assertNotEqual(first.content_digest, edited.content_digest)

    def test_curated_adapters_use_embedded_dates_and_reject_ambiguous_headings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "MEMORY.md"
            source.write_text(
                "# Memory\n\n## 2026-07-12\n\n### Stable checkpoint\n\nFirst.\n\n"
                "## 2026-07-14\n\n### Current checkpoint\n\nSecond.\n",
                encoding="utf-8",
            )
            records = parse_codex_memory(source, timestamp="2026-01-01T00:00:00Z")
            self.assertEqual(
                [(item["source_native_id"], item["timestamp"]) for item in records],
                [
                    ("stable-checkpoint", "2026-07-12T00:00:00Z"),
                    ("current-checkpoint", "2026-07-14T00:00:00Z"),
                ],
            )

            source.write_text(
                "# Memory\n\n## Same identity\n\nFirst.\n\n## Same identity\n\nSecond.\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ImportError, "stable source identity"):
                parse_codex_memory(source, timestamp="2026-01-01T00:00:00Z")

    def test_portable_markdown_and_jsonl_adapters_preserve_manifest_metadata(self):
        metadata = {
            "id": "portable-1",
            "timestamp": "2026-07-02T03:04:05Z",
            "kind": "runbook",
            "scope": "workflow:release",
            "relationships": ["repo:dotfiles", "workflow:release"],
            "disposition": "proposed_conflict",
            "reason": "differs-from-target",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            markdown = root / "portable.md"
            markdown.write_text(
                f"<!-- hindsight-memory: {json.dumps(metadata, sort_keys=True)} -->\n"
                "Verify the immutable release checkpoint.\n",
                encoding="utf-8",
            )
            jsonl = root / "portable.jsonl"
            jsonl.write_text(
                json.dumps({**metadata, "content": "Verify the immutable release checkpoint."})
                + "\n",
                encoding="utf-8",
            )

            markdown_record = parse_portable_markdown(markdown)[0]
            jsonl_record = parse_portable_jsonl(jsonl)[0]
            for value in (markdown_record, jsonl_record):
                self.assertEqual(value["source_native_id"], "portable-1")
                self.assertEqual(value["timestamp"], metadata["timestamp"])
                self.assertEqual(value["kind"], "runbook")
                self.assertEqual(value["intended_scope"], "workflow:release")
                self.assertEqual(value["coverage_disposition"], "proposed_conflict")
                self.assertEqual(value["relationships"], metadata["relationships"])
            self.assertEqual(markdown_record["line_start"], 2)
            self.assertEqual(jsonl_record["line_start"], 1)

    def test_source_adapters_fail_closed_on_ambiguous_or_unknown_manifest_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            markdown = root / "portable.md"
            markdown.write_text("unframed content\n", encoding="utf-8")
            with self.assertRaises(ImportError):
                parse_portable_markdown(markdown)

            jsonl = root / "portable.jsonl"
            jsonl.write_text(
                json.dumps(
                    {
                        "id": "portable-1",
                        "timestamp": "2026-07-02T03:04:05Z",
                        "kind": "rule",
                        "scope": "global",
                        "relationships": [],
                        "disposition": "proposed_novel",
                        "reason": "unreviewed",
                        "content": "Durable guidance.",
                        "unknown": True,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ImportError):
                parse_portable_jsonl(jsonl)

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

    def test_projection_orders_items_by_source_timestamp_then_stable_identity(self):
        items = inspect_items(
            "codex",
            [
                record("late", timestamp="2026-07-03T00:00:00Z"),
                record("early", timestamp="2026-07-01T00:00:00Z"),
            ],
        )
        projection = project_import(items)
        self.assertEqual(
            [item.source_native_id for item in projection.items],
            ["early", "late"],
        )

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

    def test_bounded_inspection_run_is_resumable_and_rate_limit_aware(self):
        items = inspect_items(
            "codex",
            [record("m1"), record("m2", "Use current evidence."), record("m3", "Keep logs content-free.")],
        )
        projection = project_import(items)
        current_time = [0.0]
        sleeps = []
        calls = []

        def clock():
            return current_time[0]

        def sleep(seconds):
            sleeps.append(seconds)
            current_time[0] += seconds

        result = run_import_inspection(
            projection,
            inspector=lambda item: calls.append(item.item_id),
            max_items=3,
            requests_per_window=2,
            window_seconds=10.0,
            clock=clock,
            sleep=sleep,
        )
        self.assertEqual(tuple(calls), result.completed_item_ids)
        self.assertEqual(sleeps, [10.0])
        self.assertEqual(result.deferred_item_ids, ())
        self.assertEqual(
            result.resume_state,
            {item.item_id: item.content_digest for item in projection.items},
        )
        self.assertTrue(all(set(event) == {"item_id", "status"} for event in result.events))

        resumed_calls = []
        resumed = run_import_inspection(
            projection,
            inspector=lambda item: resumed_calls.append(item.item_id),
            resume_state={
                items[0].item_id: items[0].content_digest,
                items[1].item_id: "0" * 64,
            },
            max_items=1,
            requests_per_window=1,
            window_seconds=1.0,
            clock=lambda: 0.0,
            sleep=lambda _seconds: None,
        )
        self.assertEqual(len(resumed_calls), 1)
        self.assertNotIn(items[0].item_id, resumed_calls)
        self.assertEqual(len(resumed.deferred_item_ids), 1)

    def test_inspection_failure_is_content_free_and_resumable(self):
        projection = project_import(
            inspect_items("codex", [record("m1"), record("m2", "Use current evidence.")])
        )
        call_count = [0]

        def fail_second(_item):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("private payload must not enter the run record")

        partial = run_import_inspection(
            projection,
            inspector=fail_second,
            max_items=2,
        )
        self.assertEqual([event["status"] for event in partial.events], ["inspected", "failed"])
        self.assertNotIn("private payload", repr(partial.events))
        self.assertEqual(len(partial.resume_state), 1)

        completed = run_import_inspection(
            projection,
            inspector=lambda _item: None,
            resume_state=partial.resume_state,
            max_items=2,
        )
        self.assertEqual(len(completed.completed_item_ids), 2)
        self.assertEqual(completed.deferred_item_ids, ())

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
