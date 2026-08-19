# Plan mutations before applying them

Status: accepted

## Context

How should `secretctl` perform multi-store mutations?

## Decision

Compute a credential-free reconciliation plan and bind explicit approval to
that plan's digest and observed-state preconditions. Reject stale approval.
Before the first mutation, persist an idempotent non-secret journal; resume or
compensate partial work under the rules settled by
[GitHub Issue #90](https://github.com/nisavid/dotfiles/issues/90), and report
convergence only after every journaled step verifies. Non-interactive
automation requires an explicit approval flag.
