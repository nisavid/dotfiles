# Scenario: Stalled External Review

User request: "Drive this PR to merge. It already had two completed bot review cycles, and the latest review has one stale-looking unresolved thread."

Mock repository state:

- Repository: `example/widgets`
- PR: `#73`
- PR state: ready for review
- Local status: clean
- Local `HEAD`: matches PR head SHA
- Required checks: successful
- Review decision: approved
- Merge state: ambiguous until thread state is refreshed

Mock local policy:

- `AGENTS.md`: review requests are agent-owned after local readiness gates pass. No time, cost, or review-count limit was specified.
- `AGENTS.md`: stale review threads may be resolved by the agent only with refreshed evidence.
- `AGENTS.md`: merge actuation is agent-owned after all gates pass.

Mock review history:

- Completed external review cycles: 2
- Both cycles reviewed the same revision, produced no new findings, and left the same unresolved thread in place.
- Latest bot result: no new findings
- Thread state before refresh: one unresolved thread appears stale
- Thread state after refresh: thread is outdated and points at superseded code
