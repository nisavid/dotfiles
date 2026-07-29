# Plan mutations before applying them

Type: grilling
Status: resolved

## Question

How should `secretctl` perform multi-store mutations?

## Answer

Compute a credential-free reconciliation plan and bind explicit approval to
that plan's digest and observed-state preconditions. Reject stale approval.
Before the first mutation, persist an idempotent non-secret journal; resume or
compensate partial work under the rules settled by
[issue 21](./21-define-reconciliation-and-recovery.md), and report convergence
only after every journaled step verifies. Non-interactive automation requires
an explicit approval flag.
