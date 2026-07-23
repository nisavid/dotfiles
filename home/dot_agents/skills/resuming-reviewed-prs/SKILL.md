---
name: resuming-reviewed-prs
description: Use when returning to an existing open PR that already has review comments or threads and needs merge-focused refresh, conflict or CI repair, review-comment triage, scope trimming, or draft replies. Also use when given a PR number and/or branch for a stale, bloated, neglected, or long-running reviewed PR.
---

# Resuming Reviewed PRs

## Overview

Use this when picking up a reviewed PR and moving it toward merge without short-circuiting reviewer trust. Refresh the branch, evaluate every comment against the current diff, fix and tighten what belongs in scope, then continue through the repo-authorized closeout path.

Core principle: make the PR easier to approve without hiding new behavior. Keep an auditable handling plan, but do not pause for approval on routine repo-ops actuation when the current repo policy assigns that work to autonomous agents.

## Required Routing

- Use `pr-review-orchestration` for PR state, review-thread state, ledgers, external-review budgets, and merge-readiness gates.
- Use `publishing-reviewable-prs` whenever refreshed commits, verification, scope, stack state, or review decisions require a PR title/body update.
- Use `receiving-code-review` before accepting or rejecting reviewer feedback.
- Use `ralph-review-until-clean` when fixes and judgments need review.
- Use `tightening-code-for-review` after review-comment fixes are in place.
- Use `resolving-workflow-ownership` before posting replies, resolving threads, marking ready, merging, or deciding who owns a blocked state.
- Respect repo-local authority policy. In repos where autonomous agentic repo ops are the default, do not pause for separate Ivan approval before making in-scope local edits, commits, ordinary pushes, review replies, evidenced thread resolutions, ready-for-review actions, or merges once the required gates pass.
- Pause before actuation only when current instructions or repo policy reserve the action for Ivan, the action requires a human/product decision, a required approval is missing, the needed push is a force-push without clear authorization, or the control surface is unavailable.
- Use `shepherd-pr` instead only when Ivan asks for ongoing autonomous PR maintenance beyond the current review/merge closeout session.

## Inputs And Authority

Accept a PR number, branch name, URL, or any combination of those, plus optional focus context. If the PR and branch disagree, stop and ask. Treat focus context as priority, not permission to skip unrelated comments, checks, or conflicts.

Authority comes from the current instruction, repo policy, and `resolving-workflow-ownership`. In repos whose policy says agents should drive execution, review loops, commits, publication steps, and cleanup autonomously, that repo policy is sufficient authority for routine PR-review work: local edits, commits, ordinary pushes, posting scoped replies, resolving evidenced handled threads, marking ready, and merging after merge-readiness gates pass. If no repo or current instruction grants that authority, assume draft-only GitHub authority by default. "Rebase it" authorizes the local rebase; it does not by itself authorize force-pushing the remote branch unless repo policy or current instruction also authorizes the force-push.

## Workflow

1. Resolve the PR, branch, base, head SHA, and current local worktree state.
   Preserve unrelated local changes.
2. Inventory the PR before editing: all review threads, top-level PR comments, non-thread review comments, review bodies, requested-changes reviews, checks, conflicts, changed files, linked requirements, and acceptance criteria.
3. Refresh the branch. Fetch and rebase or merge as instructed. Resolve
   conflicts semantically. Push only when the current instruction and git policy
   authorize the needed push mode; never force-push by implication.
4. Refresh PR state after branch changes. Re-anchor comments against the current diff. Stale or outdated comments still need evidence before they are passed over.
5. Build a ledger for every comment, review, and check. For questions, draft answers from accepted requirements when possible; otherwise mark `needs_human_decision` when the answer affects product behavior or acceptance criteria. For critiques, decide validity, scope, proposed disposition, required fix, and verification.
6. Fix valid, in-scope blockers first: conflicts, CI failures caused by the PR, correctness/security issues, then review findings and safe simplifications.
7. Delegate independent investigations or fixes when useful or requested, but keep triage, scope, disposition, and merge-readiness judgments in the parent agent. Verify subagent output against the code, diff, and checks.
8. Run relevant verification after each meaningful batch. Report skipped checks with the reason.
9. Pass fixes and judgments through `ralph-review-until-clean`. One review pass is not Ralph review.
10. Apply `tightening-code-for-review` to reduce reader burden without changing acceptance criteria. Reviewer-unmentioned bloat is fair game when introduced or amplified by the PR. Remove compatibility shims only when no persisted data, public API, deployed customer behavior, or accepted requirement depends on them. If the PR is too broad to make reviewable safely, recommend splitting, deferring, or narrowing instead of polishing around it.
11. Close out according to the authority model. In autonomous repo-ops contexts,
    post scoped replies, resolve evidenced handled threads, refresh PR state,
    update stale title/body facts through `publishing-reviewable-prs`, rerun
    required review/check gates, mark ready, and merge when
    `pr-review-orchestration` merge-readiness gates and workflow ownership pass.
    If actuation is not agent-owned, prepare the pause packet and stop.

## Triage Ledger

Use `pr-review-orchestration` categories:
`valid_fix_required`, `valid_but_already_fixed`, `stale_or_outdated`,
`conflicts_with_spec`, `non_actionable_preference`, `duplicate`, and
`needs_human_decision`.

Each item records reviewer, URL, file or topic, synopsis, category, evidence, action taken or proposed, verification, and draft reply.

## Pause Packet

Present:

- Refresh summary: rebase/merge result, conflicts, commits, push state.
- CI summary: each failing or relevant check, whether it is stale/current and PR-caused/external, diagnosis, fix, and current state.
- Per-comment ledger: synopsis, disposition, evidence, and draft reply.
- Fix summary: what changed, what was delegated, and how it was verified.
- Ralph review result: cycle labels, findings handled, and latest clean cycle.
- Tightening report: fixed, discarded, deferred with gates, and pending items.
- Merge-readiness assessment against `pr-review-orchestration` gates.
- Branch authority state: local-only, committed, pushed, or blocked on push or force-push authorization.
- Explicit next actions awaiting Ivan: replies to post, threads to resolve, follow-up commits, ready-for-review action, merge action, or human decisions.

## Guardrails

- Do not treat green CI, a clean rebase, or one reviewer/bot approval as merge readiness.
- Do not treat stale comments as ignorable without refreshed-state evidence.
- Do not implement reviewer suggestions before verifying validity and scope.
- Do not let tightening become cosmetic-only formatting or broad unrelated refactoring.
- Do not change acceptance criteria under the label of cleanup.
- Do not trust subagent conclusions without independent verification.
- Draft replies as Ivan in first person, and post them when workflow ownership
  and repo policy make reply actuation agent-owned.
- Do not resolve reviewer-owned threads unless ownership and disposition
  evidence make resolution agent-owned for this PR.

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Focusing only on unresolved inline threads | Include top-level PR comments, reviews, and non-thread review comments. |
| Rebase first, then forget old comments | Inventory first, refresh, then re-evaluate every item. |
| Calling one review pass Ralph review | Continue labeled cycles until the latest cycle has no findings. |
| Accepting subagent work as fact | Verify against current code, diff, and checks. |
| Pausing despite repo-owned autonomous closeout authority | Continue through the evidenced fix, push, reply, thread-resolution, and merge-readiness loop. |
| Posting because the draft looks ready | Act only after ledger, evidence, checks, and workflow-ownership gates pass; otherwise pause with the packet. |
