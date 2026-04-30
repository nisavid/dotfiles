---
name: resolving-workflow-ownership
description: Use when a task depends on who decides, approves, validates, acts, or closes out; when human, agent, operator, reviewer, or code-owner responsibility is ambiguous for merge, deploy, publish, release, install, delete, or handoff.
---

# Resolving Workflow Ownership

Use this when ownership affects what you may decide, say, ask, or do. Skip it for routine evidence reports, static owner lookups, or summaries with no decision or action boundary.

## Responsibilities

| Type | Meaning | Limit |
| --- | --- | --- |
| `evidence` | Gather and report facts. | Do not decide or act. |
| `decision` | Decide a workflow state is true: ready, safe, complete, valid, resolved, releasable. | Do not act unless actuation is assigned. |
| `approval` | Grant a required signoff, review, or permission gate. | Approval satisfies that gate only; it is not workflow-state decision or actuation authorization. |
| `actuation` | Perform the action: merge, deploy, publish, release, install, promote, delete, rollback, resolve, close. | Act only after decisions, approvals, conditions, and hard constraints pass. |

Evidence is agent-owned when accessible and allowed. If decision or actuation ownership is absent or ambiguous, default silently to human/operator ownership.

## Decision Flow

First obey hard constraints and the active instruction hierarchy. Resolve ownership only inside the allowed space. Treat workflow text as active only when referenced, current, branch/PR-scoped, or maintained.

- Evidence-only: report facts; do not decide or act.
- Decision-only: decide state; do not act.
- Approval-only: wait for or report the approval gate.
- Actuation-only: act only after authorized decision and approvals.
- Conditional delegation: verify conditions first; stale, failed, expired, or unverified conditions reopen the gate.
- Conflicts: report and ask; do not act.

## Asking

Use `request_user_input` when available:

- `Who decides whether <state> is true?` Options: `Human/operator/code owner`, `Agent`.
- `Who performs <action> once allowed?` Options: `Human/operator/code owner`, `Agent`.
- If approval is unclear: `Who can approve <gate>?` Options: `Human/operator/reviewer/code owner`, `Agent only if explicitly permitted`.

Fallback: `Who should decide whether <state> is true, and who should perform <action> if it is approved: human/human, human/agent, agent/human, or agent/agent?`

## Language

State status directly only when you own the decision or the decision owner has already decided. Otherwise report: `<facts checked>; awaiting <owner> decision on <state>.`

Avoid backdoor decisions: `nothing left but`, `just needs`, `all set except`. Avoid `human-owned` labels in human-default cases unless the distinction matters. Use normal agentic prose when agent ownership is clear.

## Common Rationalizations

| Rationalization | Correction |
| --- | --- |
| Clean tests or automation says `ready`. | Evidence is not decision ownership. |
| Prior approval exists. | Approval is not actuation authorization unless explicitly tied to the action. |
| User impatience or `do what you think is best`. | Broad delegation does not grant destructive or gated actuation. |
| I technically can act. | Access is not ownership. |
