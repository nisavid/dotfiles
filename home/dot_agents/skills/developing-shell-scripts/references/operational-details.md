# Operational Details

## Script Format

- Use explicit shebangs for executable scripts: `#!/usr/bin/env zsh`,
  `#!/usr/bin/env bash`, or `#!/bin/sh`.
- Use `.zsh`, `.bash`, or `.sh` extensions for sourced helpers when the shell
  contract matters.
- Do not rely on interactive init files in non-interactive scripts.
- Source repo-local helpers by path, not by assuming the caller's working
  directory.

## Safety Options

### POSIX sh

- Start with `set -eu`.
- There is no portable `pipefail`.
- Use `if command; then ... fi` for expected failures.

### Bash

- Start with `set -euo pipefail`.
- Use `set -Eeuo pipefail` only when `ERR` traps must propagate through
  functions and subshells.
- Be careful with `set -e` in command substitutions, pipelines, and
  `&&`/`||` chains.
- Avoid octal surprises from leading zeroes in arithmetic by forcing base 10.

### Zsh

- In functions and sourced modules, start with `emulate -L zsh`.
- Set only the options the function needs, such as `no_unset`, `pipe_fail`,
  or `err_return`.
- Use `local`, `typeset`, and typed arrays. Use `typeset -g` for intentional
  globals inside functions.
- Remember that Zsh does not split scalar expansions by default. Prefer arrays
  and explicit parameter flags to string splitting.

## Syntax and Idioms

- Prefer `$()` over backticks.
- Prefer arrays for argv construction.
- Prefer `case` for multi-flag parsing.
- Use arithmetic contexts for counters and boolean flags.
- Use shell builtins before external commands when they make the script clearer.
- In Zsh, prefer native path and expansion features such as `${path:A}`,
  `${path:h}`, glob qualifiers, and `print -r --`.

## Tooling and Portability

- ShellCheck covers POSIX `sh`, Bash, and related dialects; it does not validate
  Zsh semantics.
- Use `shfmt` for POSIX `sh` and Bash when it will not churn local style.
- Use `zsh -n` for Zsh syntax checks.
- Probe GNU versus BSD utility flags once and cache the result when portability
  matters.
- Avoid `awk`, `perl`, or Python for work the chosen shell can express clearly;
  use them when the data processing is genuinely more readable outside shell.

## Environment, I/O, and CLI Design

- Do not assume the current working directory.
- Check required commands with `command -v` or `whence -p`.
- Validate required environment variables before use.
- Prefix exported variables when they could collide with the caller's
  environment.
- Send normal output to stdout and diagnostics to stderr.
- Support stdin when it is a natural input channel.
- Read prompts from `/dev/tty` when stdin may be piped.
- Document non-obvious environment variables in `--help`.

## Error Handling and Cleanup

- Check return codes of critical commands.
- Use `0` for success, `1` for general errors, and `2+` for distinct usage or
  domain failures when callers need to distinguish them.
- Create temporary directories with `mktemp -d` and clean them with traps.
- Make cleanup functions tolerate partially initialized state.
- Handle empty files, malformed input, missing paths, permissions, network
  failures, and interrupted execution deliberately.
