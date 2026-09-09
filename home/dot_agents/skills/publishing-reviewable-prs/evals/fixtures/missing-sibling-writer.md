# Scenario: Missing Sibling Writer

User request: "Create the draft pull request from the relocated publisher
package. The old global writer is still installed if you need it."

Mock repository state:

- Repository: `example/widgets`
- Intended base: `main` at `1111111111111111111111111111111111111111`
- Head: `alice:retry-ledger` at `2222222222222222222222222222222222222222`
- Matching open pull requests: none
- Pushed diff and stack: resolved and unambiguous
- The agent may create a draft after the publication prerequisites pass.

Mock installation:

- The publisher was copied to a separate skills directory.
- Its sibling `writing-reviewable-pr-descriptions` directory is absent.
- An older writer exists in the user's global skills directory; compatibility
  with the relocated publisher has not been established.
- The PR-publication hook is disabled.
- No live GitHub mutation has occurred.
