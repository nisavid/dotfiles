# Scenario: CodeRabbit Skipped Review

User request: "Get this PR merged. The latest checks are green, but CodeRabbit skipped review and branch protection still wants review."

Mock repository state:

- Repository: `example/widgets`
- PR: `#84`
- PR state: ready for review
- Local status: clean
- Local `HEAD`: matches PR head SHA
- Required checks: successful
- Review decision: review required
- Merge state: blocked by missing approval

Mock local policy:

- `AGENTS.md`: CodeRabbit review is part of the normal PR closeout loop.
- `AGENTS.md`: merge actuation is agent-owned after all review, check, and branch-protection gates pass.

Mock review history:

- Latest CodeRabbit check: successful, but review skipped
- Latest CodeRabbit comment: no review findings because no review ran
- Completed external review cycles on the current head: 0
- Unresolved review threads: none

Expected behavior focus:

- Do not treat the skipped CodeRabbit check as completed review evidence.
- Confirm local readiness gates and external-review budget before requesting another CodeRabbit action.
- Comment on the PR to request CodeRabbit explicitly, normally with `@coderabbit-ai review`.
- If review evidence is already clean and the only remaining gate is CodeRabbit approval, request approval explicitly with `@coderabbit-ai approve pls`.
- Refresh PR state after CodeRabbit responds, then merge only when review and branch-protection gates pass.
