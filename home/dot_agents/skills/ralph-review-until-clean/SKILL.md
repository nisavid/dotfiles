---
name: ralph-review-until-clean
description: "Use when Ralph review semantics apply or reviewing-before-finalizing routes work to Ralph review: ralph-review, Ralph review, Ralph-review, review until clean, repeat until clean, clean review, or review and revise until clean for code, plans, specs, docs, branches, releases, PR readiness, or other artifacts."
---

# Ralph Review Until Clean

Ralph review is an iterative review-and-revise loop that overrides broader review ladders. One pass plus fixes is not enough; the latest labeled cycle must be clean.

## Core Loop

For each cycle:
1. Label it `Ralph Review Cycle N`.
2. Review the current artifact or diff.
3. Classify findings as valid, fixed, rejected with evidence, or operator-blocked.
4. Fix valid findings and verify the revised surface.
5. Start the next labeled cycle from revised state.

Stop only when the latest cycle has no findings. If a decision blocks progress, report the blocked finding.

## Scope

For code, plans, specs, docs, durable instructions, or ambiguous finding state, read [references/review-criteria.md](references/review-criteria.md).

For PR review comments, bot reruns, ready-for-review, merge readiness, stale threads, requested reviewers, or blocked GitHub merge state, run `pr-review-orchestration` once per cycle and follow its external-review budget gates.

## Pushback

Reject findings only with evidence; passing tests, rollback, urgency, or inconvenience are not enough.

## Anti-Recursion

When reviewing review-loop instructions, label cycles on the instruction artifact; do not recurse indefinitely.
