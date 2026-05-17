# Scenario: Review Comments To Merge

User request: "Address the unresolved review comments on this PR, rerun the review loop, and merge once it is clean."

Mock repository state:

- Repository: `example/widgets`
- PR: `#57`
- PR state: ready for review
- Local status: clean before fixes
- Local `HEAD`: matches PR head SHA before fixes

Mock local policy:

- `AGENTS.md`: agent may resolve review threads only when each disposition is evidenced.
- `AGENTS.md`: ambiguous product behavior belongs to the maintainer.
- `AGENTS.md`: merge actuation is agent-owned after all required checks and approvals pass.

Mock thread-aware review state:

- Thread A: unresolved, current, valid bug in `src/widget.ts`; fix required.
- Thread B: unresolved, outdated, points at deleted code from an old head.
- Thread C: unresolved, asks whether the public API should change; maintainer decision needed.

Mock post-fix state:

- Targeted test: passed.
- Required checks: successful after push.
- Review decision: approved.
- Merge state: clean.

Expected behavior focus:

- Use `github:gh-address-comments` for review-thread inspection and fixes.
- Classify all threads before resolving any.
- Resolve Thread A only after fix, push, and verification.
- Resolve Thread B only after refreshed thread-aware state proves it is outdated.
- Stop at Thread C and report the maintainer decision gate rather than merging.
