---
name: checkpointing-and-publishing-git-work
description: Use when handling any Git-backed change and safe task completion. Use when asked to implement a change in a repository and commit clean checkpoints; review a branch or repository for bugs, including review-only work; create commits or checkpoints; push and verify a remote branch; reconcile with an exact lease; integrate a branch; or close out Git work. If a repository task says "In Codex" or "In Claude Code," apply in either harness, even when mutation or publication is forbidden. Do not use for Git explanations or pasted summaries without repository action. Owns safe task-only commits and publication; extends finishing-a-development-branch without conflicting completion menus or force rules and without publishing non-task work.
---

# Checkpoint And Publish Git Work

Own the local Git safety boundary. This skill is the sole local owner of Git baseline capture, task-only checkpoint commits, publication and reconciliation, exact CAS leases, and remote verification.

## Coordinate Completion Choices

Use `finishing-a-development-branch` only when a named-branch merge, PR, keep, or discard choice is genuinely unresolved. It supplies that choice; this skill owns any selected push, a PR workflow owns PR creation, and finishing may execute an explicitly selected merge, discard, or cleanup.

For detached HEAD, default to a keep-and-report gate or an explicit new branch plus remote publication. Never offer detached discard.

## Establish The Baseline

Before task work, record the repository and worktree, immutable source SHA, branch or detached state, index and worktree state, pre-existing unpublished state, push configuration, and in-progress Git operations. Treat pre-existing state as unrelated unless the task explicitly adopts it. Review-only tasks never mutate or publish.

Stop on pre-existing Git operations or incomplete and alternate graph conditions reported by the planner. Identity, repository policy or protection, required verification or review, conflicts, ambiguous ownership or destination, and inability to preserve remote work remain gates.

## Follow The Checkpoint Workflow

Use this order:

1. Resolve task constraints.
2. Capture the baseline.
3. Run applicable verification and review.
4. Create a literal-path, task-only commit.
5. Bind and rerun final verification and review against that immutable commit.
6. Plan publication.
7. Reconcile when required, then rerun the affected gates and planner.
8. Execute the exact CAS push.
9. Post-verify the exact push endpoint and full destination ref, then end on a terminal `verified` plan.

Audit the index and worktree before committing. Use `git --literal-pathspecs commit --only -- <owned paths>` only when every selected whole path is task-owned. Verify the committed path set and preservation of the unrelated index. Mixed ownership within a path blocks the commit.

## Plan And Publish

Run:

```sh
scripts/plan_git_publication.py --repo <path> --request <json-file>
```

Follow only the planner's `blocked`, `needs_reconciliation`, `ready`, or `verified` state. Never infer around a gate; use the command's `--help` and JSON contract for the full decision matrix.

When step 6 returns `ready`, capture and review that plan as the publication baseline. If step 7 reconciliation is required, establish or replace the baseline only after the affected gates pass and the planner returns a new `ready` plan. Immediately before every push, rerun the planner and require the entire rerun plan to match the reviewed `ready` baseline, including `source_sha`, destination, lease, refspec, `destination.config_digest`, and `destination.endpoint_fingerprint`. Execute only its immutable source SHA, one explicit nonempty `<source_sha>:<full-ref>` branch-update refspec, exact existing or absent lease, options before `--`, no followed tags, and submodule mode `check`. Never use a deletion refspec such as `:<full-ref>`, mutable `HEAD`, bare, `--all`, `--mirror`, a wildcard, multiple refspecs, or unconditional force.

Never remove a SHA listed in `target_only_shas` unless that exact SHA appears in `removal_authorized_commits`. If missing removal authorization is the sole gate, preserve the planner's `needs_reconciliation` status; if another gate also remains, require `blocked`. When all target-only SHAs are authorized and no other gate remains, the planner may return `ready`. Remote-ref deletion is outside this skill and planner; use a separately authorized branch-deletion workflow.

End only after the planner post-verifies the exact push endpoint and exact full ref and returns `verified`. If local HEAD moved after the immutable push, report the remaining local work.

## Preserve Evaluation Integrity

For behavior evaluation, give execution agents only the raw prompt and fixture and, for with-skill runs, this candidate skill body. Do not expose paths, expectations, or expected output. Allow no tool use. Give expectations to a separate grader only after execution, then validate the isolated run workspace with `scripts/check_eval_gate.py --workspace <path> --evals <evals.json> --runs 3`.
