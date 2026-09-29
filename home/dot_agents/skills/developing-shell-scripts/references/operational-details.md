## Table of Contents

- [Table of Contents](#table-of-contents)
- [Script Format](#script-format)
- [Shell Options and Safety](#shell-options-and-safety)
  - [POSIX `sh`](#posix-sh)
  - [Bash](#bash)
  - [Zsh](#zsh)
- [Syntax and Idioms](#syntax-and-idioms)
- [Tooling and Portability](#tooling-and-portability)
- [Environment, I/O, and CLI Design](#environment-io-and-cli-design)
- [Error Handling and Validation](#error-handling-and-validation)

## Script Format

- Use explicit shebangs for executable scripts: `#!/usr/bin/env zsh`, `#!/usr/bin/env bash`, or `#!/bin/sh`
- Use shell-specific extensions for libraries or sourced files so the required feature set is obvious
- Do not rely on interactive init files in non-interactive contexts
- Keep scripts self-contained, or source repo-local helpers explicitly

- Bash: target modern Bash 5.2 behavior unless the script says otherwise
- Zsh: assume current Zsh 5.9 behavior unless the environment says otherwise

## Shell Options and Safety

### POSIX `sh`

- Start with `set -eu`
- There is no `pipefail`
- Guard expected failures explicitly with `if` blocks

### Bash

- Start with `set -Eeuo pipefail` when using ERR traps, otherwise `set -euo pipefail`
- Be mindful of `set -e` footguns in command substitutions, pipelines, and `&&` or `||` chains
- Avoid octal surprises from leading zeros in arithmetic; use base-forcing such as `10#$n`

### Zsh

- For executable Zsh scripts, use `set -euo pipefail`
- In source-callable entrypoints and option-sensitive functions, including functions defined by sourced modules, start with `emulate -L zsh`; do not put top-level `emulate -L zsh` in sourced modules because it resets the caller's option state
- Opt into options explicitly so caller state does not leak in; combine related options into one `setopt` when readable
- In Zsh scripts, make failure helpers `exit`, not `return`: under `errexit`, zsh skips the script's top-level `trap ... EXIT` or `TRAPEXIT` when `errexit` fires inside a function's scope, including on the function's own `return 1`, and it never runs `zshexit` on an `errexit` exit; `exit` from inside a function runs the EXIT trap and `zshexit`
- For other in-function command failures, turn `errexit` off with `emulate -L zsh` and set `err_return`, or an equivalent, in every function between the failure and top level, so `errexit` fires at top level and the EXIT trap runs; do not re-enable `errexit` in those functions, because `err_return` does not help while it is on, and `emulate -L zsh` without `err_return` continues past the failure
- In Zsh 5.9.2, when the script's top level has `errexit` on, as `set -euo pipefail` sets, an unset variable under `nounset` skips the script's `trap ... EXIT` at top level and inside functions, even functions that turn `errexit` off; with `nounset` alone the trap runs. `${var:?message}` runs that trap at top level but skips it inside a function whether or not `errexit` is on. Validate required variables before creating temporary resources. Once resources exist, expand with `${var-}` and reject missing values with an explicit `exit` so the trap runs.
- Declare variables with type and local scope by default: `local`, `integer`, `local -a`, and `local -A`
- Prefer specific builtins: `readonly` instead of `local -r`, and `integer` instead of `local -i`
- Use `typeset -g` only for intentional globals inside functions to avoid dynamic scoping surprises

## Syntax and Idioms

- Prefer `$()` over backticks
- Use `[[ ... ]]` in Bash or Zsh, and `[ ... ]` or `test` in POSIX `sh`
- Use `case` for multi-flag parsing
- Use arithmetic contexts for boolean flags and math

### Zsh Idioms

When intentionally writing Zsh, avoid fork/exec and prefer native features.

- **Quoting:** unquoted scalar expansions do not word-split, so omit quotes in assignments, `[[ ]]`, `(( ))`, and `case`. Quote path or arbitrary-value arguments at command boundaries (`git -C "$dir"`, `source "$file"`, `"$runtime" image rm "$ref"`) and redirection targets (`>"$out"`); this preserves exact argv and paths for commands
- **Expansion modifiers:** use `${path:A}` to resolve, `${path:h}` for the directory, `${path:t}` for the tail, and `${${(%):-%N}:A}` for the current script path
- **Join and split delimiters:** use the `< >` delimiter form, such as `${(j< >)array}` and `${(s< >)value}`; quote-escape argv for display with `${(@q)argv}`
- **Arithmetic:** prefer `while (( $# ))`, `if (( flag ))`, `(( ${#array} ))`, and membership checks such as `(( ${+assoc[$key]} ))`
- **Arrays and associative arrays:** use them for collecting, filtering, indexing, matching, and sorting; iterate sorted associative keys with `${(ok)assoc}` and sorted arrays with `${(o)array}`
- **Builtins:** prefer `print -r --`, `whence` or `command -v`, `read` loops, parameter expansion, and globbing before external text tools
- **Modules and zfuncs:** use `zsh/stat` (`zstat`), `zsh/datetime`, `zsh/mathfunc`, `zsh/regex`, and helpers such as `zparseopts` when they replace a fork or clarify intent

#### File Tests and Glob Qualifiers

Express existence, type, permission, and symlink behavior directly.

| Intent                          | Form      |
| ------------------------------- | --------- |
| Omit nonexistent matches        | `N`       |
| Dereference symlinks for checks | `-`       |
| Existing readable regular file  | `(N-.r)`  |
| Readable regular files in cwd   | `*(N-.r)` |
| Existing directories            | `(N/)`    |
| Symlinks without dereference    | `(N@)`    |

The `r` glob qualifier checks the owner-readable permission bit. Use `[[ -r $file ]]` when effective-user readability matters, and use `zstat` when exact mode bits matter.

## Tooling and Portability

- ShellCheck for `sh` or Bash
- `shfmt` for `sh` or Bash
- `zsh -n` for Zsh
- Prefer shell built-ins first, then standard utilities, then `npx`, then `python`
- Avoid `awk`, `sed`, `cut`, `grep`, and `perl` unless there is a strong reason or the native shell version would be less clear
- Probe for GNU vs BSD flag differences once and cache the result when portability matters

## Environment, I/O, and CLI Design

- Do not assume the current working directory; use a script-relative `cd` when needed
- Check required commands with `command -v`
- Validate required environment variables before using them
- Prefix exported variables to avoid namespace collisions
- Send normal output to stdout and diagnostics to stderr
- Support stdin where it makes sense
- Provide `--quiet` and `--verbose` or `--debug` modes for user-facing CLIs
- Avoid interactive prompts in non-interactive contexts; if a prompt is required, read from `/dev/tty`
- Support both short and long GNU-style options, and document `--help`

## Error Handling and Validation

- Check return codes of critical commands
- Use consistent exit codes: `0` for success, `1` for general error, and `2+` for specific classes of failure
- Clean up temporary files with traps; in Zsh, follow the [`errexit` rules](#zsh) so command failures inside functions do not skip the EXIT trap
- Handle empty or missing files, malformed input, filesystem errors, and network failures deliberately
- Check argument counts before access
- Validate file and directory existence, type, and permissions; in Zsh, prefer specific tests (`[[ -r $file ]]`), glob qualifiers (`(N-.r)`, `(N/)`, `(N@)`), and `zstat` over bare existence checks
- Handle special characters in paths, variables, and user input; in Zsh, this mainly means quoting path and arbitrary-value arguments at command boundaries and redirection paths
