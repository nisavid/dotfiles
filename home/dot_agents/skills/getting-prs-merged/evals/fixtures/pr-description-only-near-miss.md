# Scenario: PR Description Only Near Miss

User request: "Update the stored pull request description on GitHub, and leave
it draft."

Mock repository state:

- Repository: `example/widgets`
- PR: `#14`
- PR state: draft
- Local status: clean
- Existing PR body: sparse and stale
- Required checks: pending
- Review threads: none

Mock local policy:

- `AGENTS.md`: do not mark draft PRs ready without explicit request.
- `AGENTS.md`: do not request review or merge when the user asks only for PR text.

Expected behavior focus:

- Use `publishing-reviewable-prs` as the update orchestrator and
  `writing-reviewable-pr-descriptions` for the complete reviewer-facing text.
- Do not use the merge-closeout wrapper.
- Refresh the PR body from the pushed diff and current verification while
  preserving the draft state.
- Do not mark ready.
- Do not request review.
- Do not merge.
