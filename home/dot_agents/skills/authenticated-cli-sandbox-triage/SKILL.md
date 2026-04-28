---
name: authenticated-cli-sandbox-triage
description: Use when a CLI reports quota, auth, cache, DNS, network, read-only filesystem, or missing-state failures inside Codex or another sandbox
---

# Authenticated CLI Sandbox Triage

## Overview

Sandbox failures can look like real product failures. Before concluding that a CLI is unauthenticated, quota-limited, broken, or offline, verify whether it can see the host auth, config, cache, and writable state it normally uses.

## When To Use

Use this for CLIs such as `ctx7`, `gh`, `hf`, `coderabbit`, cloud CLIs, package managers, and vendor tools when they depend on host-side auth or mutable local state.

Do not use this to bypass approval, tenant policy, or external-disclosure rules.

## Procedure

1. Treat the first sandbox failure as an environment symptom, not the final answer, when the error mentions quota, login, missing credentials, cache, DNS, network, `EROFS`, or read-only filesystem.
2. Check the CLI identity command if it exists, such as `ctx7 whoami`, `gh auth status`, or `hf auth whoami`.
3. Inspect only metadata about likely auth/config locations, not secrets. Examples: `ls -la ~/.context7`, `find ~/.context7 -maxdepth 2 -type f -printf '%p %m %s bytes\n'`.
4. Rerun the same CLI command with `sandbox_permissions: "require_escalated"` when Codex approval rules allow it, so the command can see host auth/config/cache state and write the CLI's normal cache or metadata files.
5. If the rerun succeeds, use that result. Report the first failure as sandbox-related only if it matters.
6. If the rerun still fails, then treat the CLI's error as authoritative and report it directly.

## Context7 Pattern

For `ctx7`, do not treat `Monthly quota exceeded`, `not logged in`, npm cache `EROFS`, DNS errors, or fetch errors from the first sandboxed attempt as authoritative.

Run:

```bash
npx ctx7@latest whoami
npx ctx7@latest library "<name>" "<full user question>"
npx ctx7@latest docs <libraryId> "<full user question>"
```

When repo instructions require Context7 requests outside Codex's default sandbox, run `whoami`, `library`, and `docs` that way from the start. Do not reuse a sandboxed `library` result that came from an unauthenticated, quota-limited, DNS-failed, or cache-failed attempt.

## Common Mistakes

- Do not silently fall back to training data after a likely sandbox/auth-state failure.
- Do not print tokens, API keys, or credential file contents.
- Do not broaden the fix into permanent symlinks or copied secrets.
- Do not call a CLI unauthenticated until its identity command fails in a context that can see the host auth state.
