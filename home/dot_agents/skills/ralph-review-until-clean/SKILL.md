---
name: ralph-review-until-clean
description: "Use when Ralph review semantics apply or reviewing-before-finalizing routes work to Ralph review: ralph-review, Ralph review, Ralph-review, review until clean, repeat until clean, clean review, or review and revise until clean for code, plans, specs, docs, branches, releases, PR readiness, or other artifacts."
---

# Ralph Review Until Clean

Ralph overrides broader review ladders.

## Core Loop

For each cycle:
1. Label it `Ralph Review Cycle N`.
2. Review the artifact/diff; classify findings as valid, fixed, rejected with evidence, or operator-blocked.
3. Active checkpoints or operator-blocked findings pause before another cycle; otherwise fix valid findings, verify, and repeat.

Stop only when latest labeled cycle has no valid/operator-blocked findings or active checkpoint.

## Escalation Checkpoint

Track each claim/seam across cycles. After correction, activate when the tracked claim returns in any category or a second distinct counterexample exposes its seam; ignore unrelated category matches. Clear only after a materially new boundary/design; each choice must create one: narrow the claim, redesign, bound authorized residual risk outside the claim, or validate user value and set a new assurance boundary. Keep operator-owned decisions operator-blocked.

## Scope

For code, other durable artifacts, or ambiguous findings, read [references/review-criteria.md](references/review-criteria.md).

For every PR, including ambiguous findings, run `pr-review-orchestration` once per cycle under its external-review iteration policy.

## Pushback

Reject only with evidence covering the finding's claim and scope. Relevant tests may contribute; passing tests alone, rollback, urgency, or inconvenience do not refute it.

## Anti-Recursion

When reviewing review-loop instructions, label cycles on the instruction artifact; stop instead of recursing.
