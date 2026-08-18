# Scenario: Ready State Only

User request: "The stored title and body are already current. Mark pull request
#84 ready for review without rewriting them."

Mock repository state:

- Repository: `example/widgets`
- Pull request: `#84`
- Base: `main` at `1111111111111111111111111111111111111111`
- Head: `alice:retry-ledger` at `2222222222222222222222222222222222222222`
- Pull-request state: draft
- Stored title and body: canonical and current for the exact pushed diff
- Required checks: successful
- Known valid blockers: none
- Live collapsed and expanded rendering: inspected successfully

Mock policy:

- The agent may mark a canonical draft ready after all readiness gates pass.
- This request does not authorize a title or body edit.
- Raw ready commands and automatic retry after ambiguity are prohibited.
