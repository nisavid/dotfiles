# Scenario: Draft PR Resume

User request: "PR #42 is already open as a draft. Mark it review-ready and drive it to merge."

Mock repository state:

- Repository: `example/widgets`
- Current branch: `codex/retry-ledger`
- PR: `#42`
- PR state: draft
- Local status: clean
- Local `HEAD`: matches PR head SHA
- Existing PR body: stale verification section says "not run"

Mock local policy:

- `AGENTS.md`: read PR template before editing the PR body.
- PR template requires `Summary`, `Changes`, `Verification`, and `Follow-up`.
- `AGENTS.md`: ready-for-review actuation is agent-owned when checks pass and the body has current evidence.
- `AGENTS.md`: merge actuation is agent-owned only after approvals and required checks pass.

Mock GitHub state:

- Required checks: successful.
- Review decision: no review yet.
- Requested reviewers: `team/backend`
- Review threads: none.
- Merge state: blocked by pending requested reviewer.

Expected behavior focus:

- Do not create a duplicate PR.
- Refresh the PR body before marking ready.
- Mark ready only after readiness gates pass.
- Stop at the requested-reviewer gate instead of claiming merge readiness.
