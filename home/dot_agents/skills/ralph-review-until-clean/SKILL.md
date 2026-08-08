---
name: ralph-review-until-clean
description: "Use when Ralph review semantics apply or reviewing-before-finalizing routes work to Ralph review: ralph-review, Ralph review, Ralph-review, review until clean, repeat until clean, clean review, or review and revise until clean for code, plans, specs, docs, branches, releases, PR readiness, or other artifacts."
---

# Ralph Review Until Clean

Ralph review overrides broader review ladders. Its latest labeled cycle must be clean.

## Core Loop

For each `Ralph Review Cycle N`:
1. Review the current artifact or diff.
2. Classify findings as valid, fixed, rejected with evidence, or operator-blocked.
3. Fix valid findings and verify the revised surface.
4. Review the revised state in the next labeled cycle.

Stop only when the latest cycle has no findings. Report blocking decisions as blocked findings.

## Escalation Checkpoint

When a corrected finding category recurs or adjacent counterexamples repeatedly expose one seam, pause. Resume only after an explicit decision materially changes the boundary or design: narrow the claim, redesign, authorize a residual-risk disposition, or validate user value and bound further assurance. If the decision requires the operator, keep the finding operator-blocked.

## Scope

For non-PR artifacts or ambiguous finding states, read [references/review-criteria.md](references/review-criteria.md).

For PR comments, bot reruns, readiness, merge state, stale threads, or requested reviewers, run `pr-review-orchestration` once per cycle and follow its external-review budget gates.

## Pushback

Reject only with evidence; tests, rollback, urgency, or inconvenience do not refute a finding.

## Anti-Recursion

When reviewing review-loop instructions, label cycles on the instruction artifact; stop instead of recursing.
