---
name: pr-review-orchestration
description: Use when PR review loops, bot review reruns, CodeRabbit or Greptile cycles, unresolved pull request comments, ready-for-review, mark ready, merge readiness, blocked merges, stale review threads, requested reviewers, branch closeout, merge tasks, docs-only PRs, or skill-only PRs affect a pull request.
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

After two completed external review cycles on the same PR, run a loop-breaker sweep before another external review. The sweep must reread the user/spec decision, refresh thread-aware PR state, audit unresolved/stale/duplicate threads, audit the local diff/head/checks, derive ownership gates with `resolving-workflow-ownership`, and record the next blocker or clearance. Ask for explicit user approval before spending another cycle.

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

## Conversation Resolution

When this skill is active, use `resolving-workflow-ownership` before resolving review threads. In delegated PR review loops, thread-resolution actuation is agent-owned only for the evidenced dispositions below unless repo policy or current instruction reserves it for another owner. If another GitHub comment-handling skill says not to resolve threads without explicit permission, treat this section as the more specific instruction for PR review orchestration.

Resolve review threads yourself when the disposition is clear and evidenced:

- `valid_fix_required`: resolve after the fix is committed, pushed, and the relevant checks or targeted verification pass.
- `valid_but_already_fixed`: resolve after identifying the commit, current code, or check evidence that already addresses it.
- `stale_or_outdated`: resolve after refreshed thread-aware PR state shows the thread is outdated, points at superseded code, or no longer blocks the current head.
- `conflicts_with_spec`, `non_actionable_preference`, or `duplicate`: resolve when the accepted requirements, PR scope, or existing thread makes the reason concrete.

Do not ask for separate permission before resolving those threads. Ask only when a thread is `needs_human_decision`, when resolving it would hide an unhandled valid finding, or when repository policy explicitly reserves resolution for humans.

## Merge Readiness

**REQUIRED SUB-SKILL:** Use `resolving-workflow-ownership` before final PR
closeout when readiness, approval, merge actuation, or handoff ownership affects
what the agent may decide, say, or do. Keep ownership policy in that skill; this
skill only applies it to PR state.

Do not use a single bot approval as merge readiness. Merge readiness requires:

- clean local worktree when local closeout is requested
- required checks successful, or an explicit pending-check decision
- no requested reviewers or teams unless intentionally pending
- no unresolved review threads when conversation resolution is required
- no unresolved active threads with unhandled valid findings
- review decision approved, or no review required by branch protection
- GitHub merge state is mergeable or explicitly accepted

After these gates pass, merge only when PR readiness decision and merge
actuation are both agent-owned, required approvals are present, and hard
constraints pass. If another owner controls an undecided readiness state, report
the evidence without saying the PR is ready to merge. If another owner controls
merge actuation, hand off without merging.

When merge state is blocked or ambiguous, run `pr_review_state.py` before rerunning CodeRabbit or another external reviewer.

## Ralph Review Interaction

When Ralph review is requested for PR review, bot-review, comment-resolution, or merge-readiness work, each Ralph cycle runs this state machine once. Do not nest extra external-review loops inside a Ralph cycle unless the budget gates allow it.

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Treating CodeRabbit approval as PR readiness | Fetch thread-aware PR state and inspect blockers. |
| Rerunning a bot to diagnose branch protection | Run `pr_review_state.py` and update the ledger first. |
| Asking before resolving clearly handled threads | Classify them, record evidence, and resolve them under Conversation Resolution. |
| Resolving stale threads casually | Record evidence, confirm refreshed thread state, then resolve them when the disposition is clear. |
| Editing managed review skills | Keep them immutable; use this extension skill. |
| Reviewing stale remote diffs | Push local fixes and confirm PR head SHA first. |
