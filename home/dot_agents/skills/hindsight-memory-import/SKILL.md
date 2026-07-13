---
name: hindsight-memory-import
description: Use when inspecting, projecting, validating, planning, resuming, or reconciling imports from curated Codex memories, Claude memory files, or portable Markdown or JSONL manifests into the managed Hindsight memory system.
---

# Hindsight Memory Import

Use the managed controller workflow. Never retain directly to Hindsight, call a
data-plane endpoint, or treat a novelty or deduplication heuristic as approval.

## Workflow

1. Confirm the source set and target profile/bank policy. Prefer curated memory
   files. Treat raw transcript streams as a separate offline novelty pass.
2. Inspect source records with
   `hindsight_memory_control_plane.importing.inspect_items`. Reject malformed,
   secret-like, unprovenanced, or unsupported records rather than repairing
   them silently.
3. Project with `project_import`. Preserve stable source-native identity,
   timestamp, exact file/line provenance, deterministic tags, intended scope,
   relationship hints, and one coverage disposition for every source item.
4. Validate the canonical projection and review every proposed novel,
   duplicate, conflict, and omission disposition. Reordering input must not
   change the projection digest.
5. Build the import plan with `build_import_plan`, binding it to the current
   controller plan digest. Record resumable state only as item identity plus
   content digest.
6. Stop before apply. Show the exact import plan digest, coverage summary,
   target, and unresolved proposals. Wait for explicit approval of that exact
   digest.
7. If and only if the exact plan is approved, pass it through
   `apply_import_plan` to the controller apply gate. Do not bypass rollback,
   live-state, endpoint, operations-idle, or migration-completion gates.
8. Reconcile exact item/content receipts with `reconcile_import`. Report
   missing, changed, conflicted, or omitted items; do not infer completion.

## Hard Boundaries

- Keep source content and secrets out of controller ledgers and chat summaries.
- A resume entry skips an item only when both stable identity and content digest
  match.
- Never convert a proposed disposition into a mutation without the approved
  digest-bound plan.
- Do not perform live retain, consolidate, model refresh, template import,
  configuration mutation, or deletion while the migration gate is open.
