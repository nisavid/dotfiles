# Ralph Review Criteria

Read this when the target is code, a plan, spec, doc, durable instruction, or when a cycle has ambiguous findings.

## Code Review

Prioritize bugs, regressions, missing tests, security risk, compatibility risk, operational risk, and maintainability traps.

## Plan, Spec, And Doc Review

Check for:
- Decision completeness.
- Ambiguous precedence.
- Contradictions.
- Missing test or verification coverage.
- Rollout and rollback gaps.
- Compatibility risk.
- Implementation traps.

## Finding States

- Valid: fix it before the next cycle.
- Fixed: verify the revised surface.
- Rejected: state the evidence that makes the finding wrong or out of scope.
- Operator-blocked: identify the missing stakeholder decision or unavailable access.

## Common Mistakes

- Stopping after fixing the first review's findings.
- Reporting a revision as a clean review without another cycle.
- Dropping `Ralph Review Cycle N` labels after the first pass.
- Applying only code-review criteria to plans, specs, docs, or durable instructions.
- Treating an ordinary review cycle as Ralph review without an operator request or an active instruction that routes to Ralph review.
