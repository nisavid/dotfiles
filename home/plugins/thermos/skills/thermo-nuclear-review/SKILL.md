---
name: thermo-nuclear-review
description: Audit changed branch/PR code for correctness, security, breaking behavior, devex regressions, and feature leaks. Use when the user asks for thermo nuclear, thermonuclear, deep review, or bug/security diff audit.
---

# Thermo Nuclear Review

Perform a comprehensive security and correctness audit of changed code.

## Workflow

1. Define the base, head, changed files, and any excluded paths.
2. Read `references/audit-checklist.md`.
3. Inspect the diff first, then open enough surrounding source to verify behavior end to end.
4. Report only issues caused by added or modified code. Treat pre-existing untouched issues as context, not findings.
5. If there is a PR and you have medium-or-higher findings, read PR/MR discussion after the independent audit and validate, dedupe, and attribute any external findings you include.

## Output

Put high-conviction findings first, ordered by severity. Each finding needs file:line evidence, causal chain, impact, and a concrete fix direction. Never present unfinished research when related code is accessible.
