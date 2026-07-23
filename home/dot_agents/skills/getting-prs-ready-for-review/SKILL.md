---
name: getting-prs-ready-for-review
description: >-
  Use when the operator asks to get a branch, change set, draft PR, or pull
  request ready for review end to end: "get this PR review-ready", "make this
  ready for review", "prepare this draft PR for review", "mark ready for
  review", "tighten then publish for review", or "review-ready yeet". Do not
  use for review-only, status-only, PR-description-only, draft-PR-only,
  publish-only, merge, ship, or closeout requests unless the operator also
  states a ready-for-review outcome.
---

# Getting PRs Ready For Review

## Overview

This is the convenience wrapper for PR review-readiness when ready-for-review is the requested outcome. It coordinates tightening, publishing, and reviewer-facing PR text, then marks the PR ready only when local readiness gates pass.

Use this only when the operator explicitly wants the PR ready for review. Otherwise, use the narrower skill that matches the requested step.

## Precedence

- Use this over `publishing-reviewable-prs`, `tightening-code-for-review`, and `writing-reviewable-pr-descriptions` when the requested outcome is a review-ready PR.
- Use `publishing-reviewable-prs` alone for draft PR creation or title/body publication that should remain draft.
- Use `tightening-code-for-review` alone for report-only or reviewability-only passes.
- Use `writing-reviewable-pr-descriptions` alone only for chat-only drafting.
  Use `publishing-reviewable-prs` for every actual title or body change.
- Use this as the top-level workflow over `pr-review-orchestration` when the requested outcome is a review-ready PR. Use `pr-review-orchestration` for PR state, review-thread state, external review, or readiness-ledger substeps.
- Use the merge or full-closeout workflow, such as `getting-prs-merged` when installed, for merge, ship, or full closeout goals.

## Workflow

1. Resolve the target repository, branch, change set, and PR if one already exists.
2. Use `tightening-code-for-review` on the scoped change set.
3. Stop before publishing new commits or marking ready if tightening reports unresolved valid blockers or pending operator decisions.
4. Use `checkpointing-and-publishing-git-work` when scoped changes need staging, committing, or pushing. Preserve unrelated local changes and stop for operator input when ownership overlaps within a file.
5. Use `publishing-reviewable-prs` to create or update the draft PR. It must use `writing-reviewable-pr-descriptions` for the complete title and body from the actual pushed diff.
6. If a draft PR already exists and the branch is pushed, update that PR instead of creating another one.
7. Mark the PR ready for review only after the tightening report and PR description are clean and ready actuation is agent-owned.

## Mark Ready

Create every new PR as a draft. Verify its exact stored body, then inspect the
live collapsed and expanded rendering. After those and all other readiness gates
pass, refresh the draft's exact identity and preimage and use the `ready`
operation in `publishing-reviewable-prs`. Use the same operation for an existing
draft. It performs one ready mutation and a final re-read. Treat a command error
followed by a verified ready state as ambiguous success; otherwise stop and
report the observed state. Do not invoke raw `gh pr ready`.

If the PR is already ready, leave it ready and report the PR URL.

If repo or operator policy does not allow the agent to mark ready, stop after tightening and PR-description polish, then report that ready-for-review actuation is operator-owned.

## Guardrails

- Do not mark a PR ready while known valid blockers remain.
- Do not use generated `--fill` text or skip the canonical PR-description pass.
- Do not turn a report-only tightening pass into a claim that code was tightened.
- Preserve unrelated local changes.
- Preserve an existing PR's state until this skill's final mark-ready step.
- Never claim a failed ready command left state unchanged. Use the final stored
  state reported by the owned helper.
