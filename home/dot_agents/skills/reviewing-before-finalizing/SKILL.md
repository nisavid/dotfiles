---
name: reviewing-before-finalizing
description: Use when changes appear ready to commit, merge, deploy, ship, release, finalize, or when the operator requests a review cycle, Ralph review, Ralph-review, or review and revise until clean.
---

# Reviewing Before Finalizing

Before finalizing changes, choose the review strategy deliberately. Non-trivial changes default to review. Uncertainty means stronger review.

## Operator Terms

Honor an explicit operator review policy first.

| Operator says | Meaning |
| --- | --- |
| "review cycle" | Run one complete review cycle. |
| "Ralph review" | Run review cycles until a review yields no issues. |
| "Ralph-review" | Same as Ralph review. |
| "review and revise until clean" | Same as Ralph review. |

A review cycle means:
1. Use `requesting-code-review`.
2. Use `receiving-code-review`.
3. Address every valid issue.
4. Verify the fixes.
5. Re-review only when the chosen strategy or reviewer requires it.

## Choose the Strategy

If the operator did not already choose, classify the change:

| Change shape | Strategy |
| --- | --- |
| Complete consequences are trivially understood and accounted for | No external review required. Still self-review the exact diff and run relevant verification. |
| Simple, low-risk, low-impact, well monitored, and cheap to repair | One review cycle. |
| Anything broader, riskier, harder to observe, harder to repair, security-sensitive, data-sensitive, or architecture-affecting | Ralph review. |

When unsure, choose Ralph review.

## Ralph Review

A Ralph review is not "one more review." It is a loop:

1. Run a review cycle.
2. If the review raises issues, address them with technical rigor.
3. Run another review cycle.
4. Stop only when the latest review raises no issues.

Do not count an issue as resolved because it is inconvenient, tests pass, or rollback exists. If a reviewer is wrong, use `receiving-code-review`: verify, explain the pushback, and continue only after the issue is resolved or rejected for a sound reason.

## Subagent Use

For substantial finalization work, prefer a fresh review subagent with precise context: goal, requirements, base/head diff, tests run, and known risks. Do not pass session history as review context. If `subagent-driven-development` applies, keep its stronger gates; this skill is not a shortcut.

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
| Treating "Ralph review" as ambiguous | It means repeat review cycles until no issues are raised. |
| Stopping after fixing the first review's findings | Re-review until no issues remain. |
| Letting easy rollback replace review | Rollback reduces consequence, not uncertainty. |
| Skipping review for non-functional concerns | Consider review for clarity, maintainability, docs quality, UX, and operational risk. |
| Applying this instead of a stricter workflow | Follow the stricter operator or workflow policy. |
