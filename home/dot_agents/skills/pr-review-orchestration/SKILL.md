---
name: pr-review-orchestration
description: Use when PR review loops, bot review reruns, CodeRabbit or Greptile cycles, unresolved pull request comments, ready-for-review, mark ready, merge readiness, blocked merges, stale review threads, or requested reviewers affect a coding task.
---

# PR Review Orchestration

This skill coordinates PR review work across local review, GitHub thread state, and external review bots. It extends `requesting-code-review`, `receiving-code-review`, GitHub comment-handling skills, CodeRabbit-style review skills, `reviewing-before-finalizing`, and `ralph-review-until-clean`.

Core principle: know the PR state and local readiness before spending another external review cycle.

## Ownership Boundary

Do not edit plugin-cache, lockfile-managed, generated, or byte-identical upstream skills to change this workflow. Keep those skills immutable and apply this user-local extension when their trigger language overlaps.

## State Machine

For PR review loops, ready-for-review, bot reruns, or merge readiness:

1. Inventory thread-aware GitHub PR state.
2. Create or update the review ledger.
3. Complete local readiness gates.
4. Run local review when the change is non-trivial or uncertainty remains.
5. Request external review only if the gates allow it.
6. Classify each review item and record a closure disposition.
7. Refresh GitHub PR state.
8. Close out only when blockers are gone; otherwise report the next blocker.

Use `scripts/pr_review_state.py` for PR state and ledger work:

```bash
python ~/.agents/skills/pr-review-orchestration/scripts/pr_review_state.py --repo OWNER/REPO --pr NUMBER --summary --write-ledger
```

Add `--json` when the exact machine-readable state is needed.

## Local Readiness Gate

Before external review, record these in the ledger or final summary:

- Acceptance criteria mapped to code and tests.
- Changed-file risk map.
- Unhappy-path audit.
- Exact verification commands and outcomes.
- Untested risks.
- Clean worktree, or an explicit user decision to review the current remote diff.
- PR head SHA matches the locally verified head before rerunning external review.

If local fixes exist after review, push them and refresh PR state before requesting another external review.

## External Review Budget

A completed external review cycle means the service accepted the current diff and produced a terminal result: approved, changes requested, commented with findings, or no findings.

Pending, authentication-blocked, policy-blocked, unavailable, rate-limited before review creation, timed-out-before-submission, or still-processing attempts are not completed cycles. Record the exact status or error.

After two completed external review cycles on the same PR, run a loop-breaker sweep before another external review. Ask for explicit user approval before spending another cycle.

## Review Item Handling

Classify every review item as one of:

- `valid_fix_required`
- `valid_but_already_fixed`
- `stale_or_outdated`
- `conflicts_with_spec`
- `non_actionable_preference`
- `duplicate`
- `needs_human_decision`

Record one closure disposition:

- fixed with commit and verification evidence
- answered in-thread
- resolved by reviewer
- manually resolved with evidence
- intentionally left open pending human decision
- rejected with evidence

Do not treat stale or outdated threads as safe to ignore unless refreshed PR state proves they are non-blocking, or they are manually resolved with evidence.

If a finding conflicts with the accepted spec or user decision, ask the user unless the spec is plainly obsolete and the correction is unambiguous.

## Merge Readiness

Do not use a single bot approval as merge readiness. Merge readiness requires:

- clean local worktree when local closeout is requested
- required checks successful, or an explicit pending-check decision
- no requested reviewers or teams unless intentionally pending
- no unresolved review threads when conversation resolution is required
- no unresolved active threads with unhandled valid findings
- review decision approved, or no review required by branch protection
- GitHub merge state is mergeable or explicitly accepted

When merge state is blocked or ambiguous, run `pr_review_state.py` before rerunning CodeRabbit or another external reviewer.

## Ralph Review Interaction

When Ralph review is requested for PR review, bot-review, comment-resolution, or merge-readiness work, each Ralph cycle runs this state machine once. Do not nest extra external-review loops inside a Ralph cycle unless the budget gates allow it.

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Treating CodeRabbit approval as PR readiness | Fetch thread-aware PR state and inspect blockers. |
| Rerunning a bot to diagnose branch protection | Run `pr_review_state.py` and update the ledger first. |
| Resolving stale threads casually | Record evidence and confirm blocking state. |
| Editing managed review skills | Keep them immutable; use this extension skill. |
| Reviewing stale remote diffs | Push local fixes and confirm PR head SHA first. |
