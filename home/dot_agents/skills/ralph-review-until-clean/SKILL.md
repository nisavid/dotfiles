---
name: ralph-review-until-clean
description: Use when the operator says ralph-review, Ralph review, Ralph-review, review until clean, repeat until clean, clean review, or review and revise until clean for code, plans, specs, docs, branches, releases, or other artifacts.
---

# Ralph Review Until Clean

Ralph review means repeated review cycles until the latest review raises no findings. One pass plus revision is not a Ralph review.

## Precedence

Apply this skill whenever the operator explicitly asks for Ralph semantics, regardless of any broader review strategy ladder. This skill also applies when `reviewing-before-finalizing` classifies a change as requiring Ralph review.

When Ralph review targets PR review comments, bot review reruns, ready-for-review,
merge readiness, stale review threads, requested reviewers, or blocked GitHub
merge state, each Ralph cycle uses `pr-review-orchestration` once and follows
its external-review budget gates.

## Review Loop

Label each cycle as `Ralph Review Cycle N`.

For each cycle:
1. Run a review against the current artifact or diff.
2. Treat findings as unresolved until verified, fixed, or rejected for a stated technical reason.
3. Revise after every valid finding.
4. Run the relevant verification for the revised surface.
5. Start the next labeled cycle.

Stop only when the latest labeled cycle has no findings.

## What To Review

For code, prioritize bugs, regressions, missing tests, security risk, compatibility risk, operational risk, and maintainability traps.

For plans, specs, docs, and durable instructions, also check:

- Decision completeness.
- Ambiguous precedence.
- Contradictions.
- Missing test or verification coverage.
- Rollout and rollback gaps.
- Compatibility risk.
- Implementation traps.

## Valid Pushback

Do not dismiss a finding because tests pass, rollback exists, the change is urgent, or the fix is inconvenient. If a finding is wrong, explain the evidence and continue the loop only after it is soundly rejected.

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Stopping after fixing the first review's findings | Run another labeled cycle. |
| Reporting a revision as a clean review | A clean review is a latest cycle with no findings. |
| Dropping labels after the first pass | Keep cycle labels visible until completion. |
| Applying only code criteria to plans or specs | Use the plan/spec/doc criteria too. |
| Treating "review cycle" as Ralph review | A review cycle is one pass unless explicit Ralph terms or a stronger policy apply. |
