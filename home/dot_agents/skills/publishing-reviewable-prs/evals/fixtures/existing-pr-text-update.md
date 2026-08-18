# Scenario: Existing PR Text Update

User request: "Update pull request #84's title and body on GitHub, and leave its
draft state unchanged."

Mock repository state:

- Repository: `example/widgets`
- Pull request: `#84`
- Base: `main` at `1111111111111111111111111111111111111111`
- Head: `alice:retry-ledger` at `2222222222222222222222222222222222222222`
- Local `HEAD`: `2222222222222222222222222222222222222222`
- Pull-request state: ready for review
- Stored title and body: stale because the latest pushed verification is absent
- Pushed diff and stack: resolved and unambiguous
- Repository template: requires Summary, Changes, Verification, and Follow-up

Mock policy:

- The agent may update pull-request text.
- A text-only update must preserve the current draft or ready state.
- Automatic retry and rollback after an ambiguous mutation are prohibited.
