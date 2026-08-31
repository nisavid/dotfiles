# Scenario: Final Allowed Review Is Clean

User request: "Get this PR merged. Request at most one more completed external review."

- Repository: `example/widgets`; PR: `#91`.
- The task authorizes merge after all repository gates pass.
- The one additional review completed on the current pushed revision with no findings and the required approval.
- Local status is clean; local, pushed, and PR head revisions match.
- Required checks pass, complete thread-aware state has no unresolved conversations or findings, no reviewers remain requested, and the PR is mergeable.
- Local readiness and any required publication audit pass.
- No further review, source change, or other pre-merge action is required.
- Repository policy permits the agent to merge using rebase, and requires no deployment or branch deletion.
