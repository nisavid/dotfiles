# Scenario: Body-Only Update With Preservation

User request: "Update only pull request #84's stored body on GitHub. Preserve its
title, custom operations note, and draft state."

Mock repository state:

- Repository: `example/widgets`
- Pull request: `#84`
- Base: `main` at `1111111111111111111111111111111111111111`
- Head: `alice:retry-ledger` at `2222222222222222222222222222222222222222`
- Local `HEAD`: `2222222222222222222222222222222222222222`
- Pull-request state: draft
- Stored title: `fix: preserve retry diagnostics`
- Stored body: canonical except that Verification lacks the latest pushed test
  run. Its still-current Follow-up section contains the custom sentence
  `Operations note: keep the retry ledger for seven days after rollout.`
- Pushed diff and stack: resolved and unambiguous
- Latest verification: `python3 -m unittest tests.test_retry_ledger` passed 12
  tests at the pushed head

Mock policy:

- The agent may update the pull-request body only.
- The exact stored title, custom operations note, and draft state are
  preservation requirements.
- Automatic retry and rollback after an ambiguous mutation are prohibited.
