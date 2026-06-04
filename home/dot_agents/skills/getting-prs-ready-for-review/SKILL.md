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

- Use this over `yeet`, `tightening-code-for-review`, and `writing-reviewable-pr-descriptions` when the requested outcome is a review-ready PR.
- Use `yeet` alone for draft PR creation or publish flows that should remain draft.
- Use `tightening-code-for-review` alone for report-only or reviewability-only passes.
- Use `writing-reviewable-pr-descriptions` alone for PR title or body work.
- Use this as the top-level workflow over `pr-review-orchestration` when the requested outcome is a review-ready PR. Use `pr-review-orchestration` for PR state, review-thread state, external review, or readiness-ledger substeps.
- Use the merge or full-closeout workflow, such as `getting-prs-merged` when installed, for merge, ship, or full closeout goals.

## Workflow

1. Resolve the target repository, branch, change set, and PR if one already exists.
2. Use `tightening-code-for-review` on the scoped change set.
3. Stop before publishing new commits or marking ready if tightening reports unresolved valid blockers or pending operator decisions.
4. Use `yeet` only when local changes need staging, committing, pushing, or no PR exists, and only when the entire dirty worktree belongs to the scoped change set. If unrelated local changes exist, do not use `yeet`; stage, commit, and push only the scoped files manually when safe, or stop for operator input. If unrelated changes overlap the same files as scoped changes, stop for operator input unless you can verify the exact staged diff before committing.
5. If a draft PR already exists and the branch is pushed, continue from that PR instead of invoking `yeet`.
6. Use `writing-reviewable-pr-descriptions` to make the PR title and body reviewable for the actual pushed diff.
7. Mark the PR ready for review only after the tightening report and PR description are clean and ready actuation is agent-owned.

## Mark Ready

Resolve the PR from the current branch after the branch has been pushed:

```bash
branch="$(git branch --show-current)"
pr_json="$(gh pr view "$branch" --json number,isDraft,url,headRefOid)"
pr_number="$(jq -r '.number' <<<"$pr_json")"
is_draft="$(jq -r '.isDraft' <<<"$pr_json")"
pr_url="$(jq -r '.url' <<<"$pr_json")"
pr_head="$(jq -r '.headRefOid' <<<"$pr_json")"
local_head="$(git rev-parse HEAD)"
if [ "$pr_head" != "$local_head" ]; then
  printf 'PR head %s does not match local HEAD %s; push and reverify before marking ready.\n' "$pr_head" "$local_head" >&2
  exit 1
fi
if [ "$is_draft" = "true" ]; then
  gh pr ready "$pr_number"
fi
printf '%s\n' "$pr_url"
```

If the PR is already ready, leave it ready and report the PR URL.

If repo or operator policy does not allow the agent to mark ready, stop after tightening and PR-description polish, then report that ready-for-review actuation is operator-owned.

## Guardrails

- Do not mark a PR ready while known valid blockers remain.
- Do not skip the PR description pass because `yeet --fill` produced text.
- Do not turn a report-only tightening pass into a claim that code was tightened.
- Preserve unrelated local changes.
- If `yeet` finds an existing PR, respect its current state until this skill's final mark-ready step.
- If `gh pr ready` fails, report the failure and leave the PR state unchanged.
