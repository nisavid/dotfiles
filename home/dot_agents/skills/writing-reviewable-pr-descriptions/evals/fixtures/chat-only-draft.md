# Chat-only draft

Repository: `example/widgets`

Title convention: Conventional Commits.

Pull request: `#84`, draft, exact pushed base/head already resolved.

The request is chat-only: propose a better title and body here and change
nothing on GitHub.

The required collapsed Diff disclosure is already valid and must remain first.

Stored title: `WIP retry work`.

Stored body: `Retry ledger work.` with no custom links or still-current
reviewer instructions.

Exact diff:

- `src/retry_ledger.py`: records retry attempts and exposes the exhausted
  state; 42 implementation additions and 3 implementation deletions.
- `tests/test_retry_ledger.py`: covers attempt recording and exhaustion; 35
  test additions and 0 deletions.
- Two added files. No modified, removed, moved, copied, or binary files.

Observed verification:

- `python3 -m unittest tests/test_retry_ledger.py` passed 7 tests at the
  repository root.

Repository template: requires Summary, Changes, Verification, and Follow-up.

There are no blockers or follow-up items.
