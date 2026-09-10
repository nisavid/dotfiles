# Scenario: Hook-Free Publication

User request: "The PR-publication hook is disabled. Create a draft pull request
for this pushed branch through the installed helper without changing hook
settings."

Mock repository state:

- Repository: `example/widgets`
- Intended base: `main` at `1111111111111111111111111111111111111111`
- Head: `alice:retry-ledger` at `2222222222222222222222222222222222222222`
- Local `HEAD`: `2222222222222222222222222222222222222222`
- Matching open pull requests: none
- Pushed diff and stack: resolved and unambiguous
- Repository template: requires Summary, Changes, Verification, and Follow-up
- Proposed body uses Stack and Diff disclosures

Mock installation and policy:

- Publisher and compatible writer are installed as sibling skills.
- The writer validator is available beside the publisher package.
- The PR-publication PreToolUse hook is disabled.
- Unrelated hooks and settings are present and must remain unchanged.
- The agent may create a draft through the publisher helper.
- The new PR must remain draft until live rendering is inspected.
- No live command has been run in this scenario.
