---
name: checkpointing-and-publishing-git-work
description: Use when handling any Git-backed change and safe task completion. Use when asked to implement a change in a repository and commit clean checkpoints; review a branch or repository for bugs, including review-only work; create commits or checkpoints; push and verify a remote branch; reconcile with an exact lease; integrate or discard a branch; classify or clean up a worktree; or close out Git work. If a repository task says "In Codex" or "In Claude Code," apply in either harness, even when mutation or publication is forbidden. Do not use for Git explanations or pasted summaries without repository action. Owns safe task-only commits, publication, completion choices, and provenance-aware cleanup without publishing non-task work.
---

# Checkpoint, Publish, And Finish Git Work

Own the local Git safety boundary. This skill is the sole local owner of Git baseline capture,
task-only checkpoint commits, publication and reconciliation,
exact CAS leases, remote verification, completion choices, local integration or
discard, and provenance-aware branch/worktree cleanup.

## Resolve Completion Only When Needed

Do not present a completion menu when the operator already chose the outcome or
the active workflow still owns ordinary iteration. Preserve every worktree and
branch while a PR is active or review feedback remains. When a completed,
verified named branch has no chosen outcome, offer the applicable choices:
merge locally, publish a PR, keep it, or discard it. A selected push follows this
skill's planner; PR creation and text/state publication belong to
`publishing-reviewable-prs`.

Verify the completed branch before offering or executing a choice. For detached
HEAD, offer keep-and-report or explicit new-branch publication. Never offer detached discard.

Before cleanup, classify the workspace from creation records, harness metadata,
or an explicit operator statement; a path-name heuristic is insufficient:

- A normal checkout has no linked worktree to remove.
- A directly agent-created worktree has an explicit record that this agent ran
  `git worktree add`; raw Git cleanup is permitted only for this class.
- A harness-created worktree must be cleaned up only through the harness's
  native cleanup actuator. Never run raw worktree removal against it.
- A user-created, externally managed, or unknown-provenance worktree is
  preserved and handed off without cleanup.

For local merge, integrate into the verified intended base, then run required
verification on the merged result. Only after merge and verification succeed may
terminal cleanup begin. Cleanup is target-local: act only on the selected branch
and its proven worktree registration. Never run global `git worktree prune`.
For a normal checkout, check out the verified safe base before deleting the normal-checkout branch. For a directly agent-created worktree, leave it, remove
that exact registered path, and delete only its merged branch. For a harness
worktree, invoke its native cleanup actuator. Preserve user/external worktrees.
If an action is not target-local, preserve and report the remaining state.

Discard is destructive. Enumerate the branch, commits, uncommitted files, and
worktree registration and path, then wait for the operator to type exactly `discard`.
The confirmation binds only that enumerated branch, worktree
registration and path, commit set, and dirty-path snapshot. Immediately before
any forced branch or worktree removal, re-enumerate those values and compare
them with the confirmed snapshot. If any value changed, invalidate the
confirmation, preserve and report the state, and require a new exact
confirmation. After a still-valid confirmation, use the same provenance-aware
terminal cleanup rules; force-delete a branch only for a normal checkout or
directly agent-created worktree. Use `git worktree remove --force` only after exact discard confirmation covered
every dirty path in that directly agent-created worktree and the immediate
re-enumeration still matches.
Otherwise preserve and report it. Never infer discard authority from a generic
completion request.

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
