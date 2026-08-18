# Scenario: New Draft PR

User request: "Create a draft pull request for this pushed branch with a
complete reviewer-facing title and body."

Mock repository state:

- Repository: `example/widgets`
- Intended base: `main` at `1111111111111111111111111111111111111111`
- Head: `alice:retry-ledger` at `2222222222222222222222222222222222222222`
- Local `HEAD`: `2222222222222222222222222222222222222222`
- Matching open pull requests: none
- Pushed diff and stack: resolved and unambiguous
- Repository template: requires Summary, Changes, Verification, and Follow-up
- Proposed body uses Stack and Diff disclosures

Mock policy:

- The agent may create a pull request for this pushed branch.
- Every new pull request must remain draft until its live rendering is inspected.
- Generated fill text and raw pull-request create commands are prohibited.
