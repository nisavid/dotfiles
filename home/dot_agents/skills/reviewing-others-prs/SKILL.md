---
name: reviewing-others-prs
description: Use when reviewing, re-reviewing, approving, requesting changes on, or drafting/posting comments for another person's open PR, including author updates or prior thread checks.
---

# Reviewing Others' PRs

Review, not repair. Inspect the live PR, run paired Thermos review, and return high-confidence author-actionable findings. Default to chat-only output unless posting, approval, thread resolution, branch edits, or merge are explicitly authorized and workflow-owned.

## Routing

- Use `thermos` for independent correctness/risk and maintainability/code-health passes before synthesis.
- Use `pr-review-orchestration` for live PR state, thread state, ledgers, checks, external-review budgets, and closeout gates.
- Apply `resuming-reviewed-prs` comment discipline for existing reviews: inventory threads, comments, reviews, checks, requested changes, and stale/outdated items before disposition.
- Use `receiving-code-review` before accepting, rejecting, answering, or resolving prior reviewer feedback.
- Use `resolving-workflow-ownership` before GitHub actuation or branch mutation.
- Use `code-review`/CodeRabbit only when requested, repo-required, or worth spending to resolve uncertainty.

## Inputs And Authority

Accept a PR URL, number, branch, repository, base/head pair, or checkout plus focus context. If PR and branch disagree, stop and ask.

Focus context sets priority, not exclusion. Re-reviews include prior Ivan-owned or agent-owned threads plus other reviewer threads needed for current risk.

Authority defaults to draft review in chat. When posting for Ivan, write terse reviewer prose; use first person only where natural.

## Workflow

1. Resolve PR state: base, head SHA, author, checks, review status, changed files, and local worktree state from live Git/GitHub.
2. Inventory conversations: active/outdated threads, top-level comments, review bodies, non-thread comments, requested-changes reviews, linked requirements, and relevant bot comments.
3. Define mode: chat findings, draft comments, posted review, request changes, approval, own-thread re-review, or branch edit.
4. Gather Thermos context: current diff plus enough surrounding code, tests, schemas, generated artifacts, deployment context, and requirements to avoid guessing.
5. Run paired Thermos passes independently, then synthesize.
6. Keep only findings that are high-confidence, author-owned, current on the PR head, deduplicated against existing comments, backed by file:line evidence, and paired with the smallest remedy.
7. For GitHub comments, re-review ledgers, approval/request-changes recommendations, or pause packets, read `references/review-output.md`. If posting or resolving, refresh head and thread state immediately before acting.

## Guardrails

- Do not edit the author's branch, post, approve, request changes, resolve threads, or merge without authority.
- Do not review stale local diff when live PR state is available.
- Do not ignore stale/outdated comments without refreshed evidence.
- Do not duplicate prior feedback unless new current evidence is necessary.
- Do not post speculative, preference-only, or low-confidence comments.
- Do not treat green checks, bot approval, or no findings as merge readiness.
