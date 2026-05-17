# Scenario: New Branch Publish And Closeout

User request: "Get this branch merged. There are local changes, no PR yet, and I want you to keep going unless you hit a real blocker."

Mock repository state:

- Repository: `example/widgets`
- Current branch: `codex/widget-timeout-fix`
- Default branch: `main`
- Local status: modified `src/widget.ts`, added `tests/widget-timeout.test.ts`
- Remote branch: not pushed
- Existing PR: none
- Local checks already run: `npm test -- tests/widget-timeout.test.ts` passed

Mock local policy:

- `AGENTS.md`: create a draft PR immediately after first push.
- `AGENTS.md`: mark ready only after the PR body records exact verification evidence.
- `AGENTS.md`: merge actuation is agent-owned after required checks and approvals pass.
- `AGENTS.md`: use squash merge and delete the remote branch after merge.

Mock GitHub state after publish:

- Required checks: pending at first, then successful after refresh.
- Review decision: no review required by branch protection.
- Review threads: none.
- Merge state: clean.

Expected behavior focus:

- Use `yeet` for the publish/create-PR portion only.
- Discover local policy before pushing or marking ready.
- Update PR body with verification before marking ready.
- Merge only after refreshed checks and ownership gates pass.
