# Documentation flag correction

Repository: `example/widgets`

Title convention: Conventional Commits.

Pull request: `#17`, draft, exact pushed base/head already resolved.

The required collapsed Diff disclosure is already valid and must remain first.

Exact diff:

- `docs/cli.md`: corrects the documented flag from `--dryrun` to the implemented
  `--dry-run` spelling.
- One line changed. No runtime, test, generated, deployment, or configuration
  files changed.

Observed verification:

- `widgets deploy --help` prints `--dry-run`.
- Markdown link checking passed.

Preservation input:

- Keep `Fixes #16`, which still describes the documentation defect.

There are no blockers or follow-up items.
