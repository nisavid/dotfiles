---
name: reviewing-before-finalizing
description: Use when changes appear ready to commit, merge, deploy, ship, release, finalize, or when the operator requests a review cycle, Ralph review, Ralph-review, ralph-review, review until clean, repeat until clean, clean review, or review and revise until clean.
---

# Reviewing Before Finalizing

Before finalizing changes, choose the review strategy deliberately. Non-trivial changes default to review. Uncertainty means stronger review.

## Operator Terms

Honor an explicit operator review policy first.

| Operator says | Meaning |
| --- | --- |
| "review cycle" | Run one complete review cycle. |
| "Ralph review", "Ralph-review", or "ralph-review" | Use `ralph-review-until-clean`. |
| "review until clean", "repeat until clean", "clean review", or "review and revise until clean" | Use `ralph-review-until-clean`. |

A review cycle means:
1. Use `requesting-code-review`.
2. Use `receiving-code-review`.
3. Address every valid issue.
4. Verify the fixes.
5. Re-review only when the chosen strategy or reviewer requires it.

Explicit Ralph terms take precedence over the strategy ladder below.

## Pull Request Review State

If finalization involves PR review comments, bot review reruns, ready-for-review,
merge readiness, stale review threads, requested reviewers, or blocked GitHub
merge state, use `pr-review-orchestration` for that portion of the work.

## Choose the Strategy

If the operator did not already choose, classify the change:

| Change shape | Strategy |
| --- | --- |
| Complete consequences are trivially understood and accounted for | No external review required. Still self-review the exact diff and run relevant verification. |
| Simple, low-risk, low-impact, well monitored, and cheap to repair | One review cycle. |
| Anything broader, riskier, harder to observe, harder to repair, security-sensitive, data-sensitive, or architecture-affecting | Ralph review with `ralph-review-until-clean`. |

When unsure, choose Ralph review with `ralph-review-until-clean`.

## Subagent Use

For substantial finalization work, prefer an independent review subagent with a precise review contract:

- exact requirements or spec, without advocacy for the implementation;
- immutable base and head for the task or whole change, never an inferred `HEAD~1`;
- the exact diff, verification evidence, and named risks;
- a request for evidence-backed findings, without suggested verdicts, severity ceilings, or instructions about what not to flag.

Do not pass session history as review context or let the implementation report substitute for inspection. Use task-scoped review when an independently testable unit is risky enough to benefit from an early gate. Always review the complete integrated change at the strength selected above; task reviews do not replace that final view.

When a final review returns several compatible findings, send one coherent fix wave to a suitably scoped worker when that avoids repeated context reconstruction and verification. Preserve disjoint parallelism when separate fix scopes truly do not share state. Verify the integrated fixes, then continue the selected review strategy; Ralph still requires a clean latest cycle.

## Red Flags

- "Tests passed, so review is unnecessary."
- "Monitoring will catch it."
- "Rollback is easy."
- "The operator said ship."
- "The risky path is unlikely."
- "I understand the main path."
- "It is probably just a small change."

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Treating explicit Ralph terms as optional | Load and apply `ralph-review-until-clean`. |
| Treating "review cycle" as a Ralph loop | Run exactly one review cycle unless a stronger policy applies. |
| Letting easy rollback replace review | Rollback reduces consequence, not uncertainty. |
| Skipping review for non-functional concerns | Consider review for clarity, maintainability, docs quality, UX, and operational risk. |
| Applying this instead of a stricter workflow | Follow the stricter operator or workflow policy. |
