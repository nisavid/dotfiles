---
name: developing-shell-scripts
description: Use when writing or reviewing `.sh`, `.bash`, or `.zsh` files, Makefile shell snippets, CI shell commands, or choosing between Zsh, Bash, and POSIX `sh` in this repo.
---

# Developing Shell Scripts

## Overview

Choose the simplest shell that meets the runtime constraints, then make the script explicit about safety, dependencies, and I/O behavior. In this repo, prefer Zsh for developer-facing scripts when availability allows, then Bash, then POSIX `sh`.

## When to Use

- Writing or reviewing shell scripts in this repo
- Adding shell snippets to Makefiles or CI configuration
- Choosing between Zsh, Bash, and POSIX `sh`
- Hardening script error handling, quoting, option parsing, or cleanup behavior

Do not use this skill for non-shell implementation work or as a substitute for checking the runtime environment the script will actually run in.

## Quick Reference

| Context                                | Default                                                                                                                                               |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Developer-facing script on macOS/Linux | Zsh with `#!/usr/bin/env zsh`                                                                                                                         |
| CI or minimal container                | Bash with `#!/usr/bin/env bash`                                                                                                                       |
| Maximum portability                    | POSIX `sh` with `#!/bin/sh`                                                                                                                           |
| Safety prologue                        | `set -euo pipefail` for Bash, add `-E` when relying on ERR traps, use `set -eu` for `sh`, and `emulate -L zsh` plus explicit options in Zsh functions |
| Output channels                        | stdout for actual output, stderr for errors and diagnostics                                                                                           |
| Tool preference                        | Shell built-ins first, then standard utilities, then `npx`, then `python`                                                                             |
| Bash script directory                  | Resolve the script file with `realpath -- "${BASH_SOURCE[0]}"`, then derive its directory with parameter expansion                                    |
| Static checks                          | ShellCheck and `shfmt` for `sh` or Bash, and `zsh -n` for Zsh                                                                                         |

## Implementation

- Use shell-specific extensions and shebangs for executable scripts; omit the shebang only for sourced shell libraries
- Keep scripts self-contained and do not rely on interactive init files such as `.zshrc` or `.bashrc`
- In Bash scripts, locate the script with `script_path="$(realpath -- "${BASH_SOURCE[0]}")"` and `script_dir="${script_path%/*}"`; this resolves symlinked script files, unlike `cd "$(dirname ...)" && pwd`, and stays portable across the repo's current macOS and Linux floor when used without GNU-only `realpath` flags
- Prefer `$()` over backticks, and use `case` or arithmetic contexts where they improve clarity
- In Zsh, follow Zsh expansion rules: do not quote ordinary scalar expansions just from Bash/POSIX habit; keep quotes where they preserve argv exactly, protect literal text, or are required by another shell or file format
- Put reusable logic in functions, declare locals locally, and route top-level execution through `main "$@"`
- In Zsh functions, start with `emulate -L zsh` and opt into options explicitly so caller settings do not leak into control flow
- Check prerequisites with `command -v`, validate required environment variables, and clean up temporary files with traps
- Prefer `print -r --` in Zsh, keep help text in single quotes or heredocs, and support both short and long GNU-style options when a CLI is user-facing

Read [references/operational-details.md](references/operational-details.md) for shell-specific safety details, CLI parsing, portability gotchas, toolchain choices, and cleanup patterns.

## Common Mistakes

- Picking a shell that the target environment does not reliably provide
- Letting caller options leak into Zsh library behavior
- Relying on interactive shell startup files in non-interactive contexts
- Leaving variables unquoted or assuming the current working directory
- Mixing normal output with diagnostics on stdout
