---
name: developing-shell-scripts
description: Use when writing or reviewing shell scripts, .sh/.bash/.zsh files, shell libraries, Makefile shell snippets, CI shell commands, package maintainer scripts, or choosing between Zsh, Bash, and POSIX sh.
---

# Developing Shell Scripts

## Overview

Choose the simplest shell that the target runtime reliably provides, then make
the script explicit about its safety rules, dependencies, I/O, and cleanup.

Prefer Zsh for developer- and operator-facing scripts when Zsh is available.
Prefer Bash for CI, Linux build tooling, and ecosystems that already assume
Bash. Use POSIX `sh` only when portability is the requirement.

## When to Use

- Writing or reviewing executable shell scripts, sourced shell libraries, or
  package hook scripts
- Editing `.sh`, `.bash`, `.zsh`, `PKGBUILD`, `.install`, Makefile, or CI shell
  snippets
- Choosing between Zsh, Bash, and POSIX `sh`
- Fixing quoting, option parsing, pipelines, traps, temporary files, path
  handling, subprocess use, or non-interactive behavior

Do not use this skill for non-shell implementation work or as a substitute for
checking the runtime environment where the script actually runs.

## Shell Choice

| Target | Default |
| --- | --- |
| Developer or operator helper with known Zsh | `#!/usr/bin/env zsh` |
| CI, containers, Linux build automation | `#!/usr/bin/env bash` |
| Maximum portability or `/bin/sh` contract | `#!/bin/sh` |
| Makefile recipe | The Make `SHELL`; set it explicitly before relying on features |
| Arch `PKGBUILD` or makepkg functions | Bash syntax; do not convert to Zsh |
| Sourced library | No shebang; use a shell-specific extension or clear filename |

## Core Rules

- Use an explicit shebang for executable scripts and shell-specific file names
  for sourced libraries.
- Keep scripts self-contained. Do not rely on `.zshrc`, `.bashrc`, aliases, or
  interactive shell options.
- Route top-level execution through `main "$@"`.
- Prefer functions for reusable logic, and keep state local unless a global is
  intentional.
- Prefer arrays over string-built commands. Avoid `eval` unless the script's
  purpose is to evaluate shell code.
- Prefer `$()` over backticks.
- Quote parameter expansions unless you are intentionally using shell splitting
  or globbing. In Zsh, prefer arrays and parameter flags over string splitting.
- Send data to stdout; send diagnostics, prompts, progress, and errors to
  stderr.
- Check prerequisites with `command -v` or the shell's native equivalent before
  using them.
- Validate required arguments, environment variables, files, directories, and
  permissions before the first destructive or expensive action.
- Clean temporary files with traps, and make cleanup idempotent.

## Zsh

Use Zsh features when the target has Zsh and the script benefits from them:
arrays, parameter expansion flags, glob qualifiers, math expressions, modules,
`print`, `zparseopts`, and path modifiers such as `${path:A}` and `${path:h}`.

Inside functions and sourced modules, start with `emulate -L zsh`, then opt
into the options that function needs. This prevents caller options and dynamic
scope from changing control flow.

```zsh
helper() {
  emulate -L zsh
  setopt no_unset pipe_fail

  local -a files
  files=("$@")
  (( ${#files} )) || {
    print -ru2 -- 'error: expected at least one file'
    return 2
  }
}
```

Prefer `print -r --` for literal output and `print -P` only for deliberate
prompt-style formatting such as operator-facing colors. Use standard 16-color
prompt escapes for status lines. Use `typeset -g` only when a function is
intentionally setting global state.

## Bash and POSIX sh

- Bash: start with `set -euo pipefail`; add `-E` only when relying on `ERR`
  traps.
- POSIX `sh`: use `set -eu`; there is no portable `pipefail`.
- Guard expected failures with `if`, `case`, or explicit status checks instead
  of hiding them behind broad `|| true`.
- Use `[[ ... ]]` in Bash and Zsh. Use `[ ... ]` or `test` in POSIX `sh`.
- Force decimal arithmetic when parsing user input with possible leading
  zeroes, for example `10#$n` in Bash.

## CLI Shape

- Support `--help` for user-facing scripts.
- Use `case` or a shell-native parser for options. In Zsh, consider
  `zparseopts` for non-trivial flags.
- Support both short and long GNU-style options when the script is a reusable
  CLI.
- Avoid prompts in non-interactive contexts. If a prompt is required, read from
  `/dev/tty`.
- Add `--quiet`, `--verbose`, or `--debug` only when callers need them.

## Verification

Run checks that match the chosen shell and target:

| Shell | Checks |
| --- | --- |
| Zsh | `zsh -n script.zsh`; run the script's own smoke path |
| Bash | `bash -n script.bash`; ShellCheck; `shfmt` when formatting is safe |
| POSIX sh | `sh -n script.sh`; ShellCheck with the intended shell dialect |
| Makefile or CI snippet | Execute the real recipe/job path or a minimized equivalent |

Read [references/operational-details.md](references/operational-details.md)
for deeper notes on safety options, portability, I/O, cleanup, and traps.

## Common Mistakes

- Choosing Zsh, Bash, or `sh` from preference instead of target availability
- Letting caller shell options leak into Zsh functions
- Treating Makefile or `PKGBUILD` shell as generic `.sh`
- Building commands in strings instead of arrays
- Mixing machine-readable output with diagnostics on stdout
- Assuming the current working directory
- Leaving temporary files behind after interrupts or failures
- Using ShellCheck as if it validates Zsh
