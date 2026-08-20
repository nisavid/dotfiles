# Configuration loader precedence

Repository: `example/widgets`

Pull request: `#58`, draft, exact pushed base/head already resolved.

The required collapsed Diff disclosure is already valid and must remain first.

Repository instructions: this repository wraps prose in every Markdown file at
80 columns, and its `.editorconfig` sets `max_line_length = 80` for all files.
Every file quoted below follows that budget.

Change:

- `widgets config load` now resolves a setting from the first source that
  defines it, in the order command flag, environment variable, project file,
  then user file, and reports the winning source in `widgets config explain`.
- Previously the project file silently overrode an environment variable, so a
  CI job could not override a checked-in default without editing the file.
- A setting absent from every source keeps its documented default and
  `explain` reports `default`.
- Three implementation files and two test files changed, with 148 authored
  additions and 46 deletions.

Reason:

- Operators reported that `WIDGETS_ENDPOINT` was ignored whenever
  `widgets.toml` defined `endpoint`, which made per-environment overrides
  impossible.
- Support needs `explain` to name the winning source when a deployment
  disagrees with its configuration file.

Observed at the pushed head, in no intended presentation order:

- `go test ./internal/config` passed 64 tests covering every precedence pair
  and the absent-setting default.
- `WIDGETS_ENDPOINT=https://staging.example.com widgets config explain endpoint`
  printed `https://staging.example.com` and source `environment`.
- With the variable unset, the same command printed the `widgets.toml` value
  and source `project file`.
- `widgets config explain missing-key` printed the documented default and
  source `default`.
- No operator configuration outside the throwaway fixture tree was read or
  written.

Remaining work: the migration note for operators who relied on the old
project-file precedence is tracked separately and is not part of this change.
