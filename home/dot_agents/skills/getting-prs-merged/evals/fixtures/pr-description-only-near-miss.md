# Scenario: PR Description Only Near Miss

User request: "Please just write a better PR description for this pull request."

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

- Use `writing-reviewable-pr-descriptions`, not the merge-closeout wrapper as the main workflow.
- Refresh the PR body from the pushed diff and current verification.
- Do not mark ready.
- Do not request review.
- Do not merge.
