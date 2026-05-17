---
name: getting-prs-merged
description: >-
  Use when the user asks to get a GitHub branch or pull request merged end to end: "get this merged", "drive it to merge", "ship this PR", "merge and close out this branch", or resume PR closeout with review-ready, unresolved comments, review reruns, merge blockers, or branch cleanup still ahead. Do not use for PR-description-only, review-only, status-only, issue-triage, or publish-only requests unless merge closeout is the stated goal.
---

# Getting PRs Merged

## Overview

This is the convenience wrapper for PR closeout when merge is the requested outcome. It coordinates the narrower skills and starts at the current state instead of replaying completed steps.

Core principle: move autonomously toward merge while keeping every gate evidence-backed and stopping when a decision, approval, or risk belongs to someone else.

## Required Sub-Skills

Use the narrower skill when its boundary becomes active:

| Situation | Skill |
| --- | --- |
| Stage, commit, push, or create the draft PR | `yeet` |
| Write or refresh reviewer-facing PR text | `writing-reviewable-pr-descriptions` |
| Mark ready, run review loops, inspect merge blockers, resolve threads, or merge | `pr-review-orchestration` |
| Inspect and address actionable unresolved review threads | `github:gh-address-comments` |
| Decide who owns readiness, thread resolution, or merge actuation | `resolving-workflow-ownership` through `pr-review-orchestration` |

Read the applicable sub-skill before acting. Do not copy a weaker local substitute into this wrapper.

## Workflow

1. Resolve the target repository, branch, and PR.
   - Use the current git remote and branch when the user points at "this" branch or PR.
   - If no target can be discovered, ask for the missing repo, branch, or PR.
2. Inventory state before changing anything.
   - Check `gh` auth, branch status, local changes, existing PR, PR head SHA, current draft/ready state, checks, reviewers, and thread-aware review state.
   - Preserve unrelated user changes. Ask before touching ambiguous or unrelated dirty work.
3. Start at the first incomplete stage.
   - No PR yet: use `yeet` to stage, commit, push, and open a draft PR.
   - Draft or stale PR body: use `writing-reviewable-pr-descriptions` to update the body from the real pushed diff and current verification.
   - Ready gate pending: use `pr-review-orchestration`; mark ready only after local readiness gates pass and the PR body records evidence.
   - Review comments or requested changes present: use `github:gh-address-comments`, then `pr-review-orchestration` for classification, evidence, thread resolution, and ledger updates.
   - Merge blockers present: use `pr-review-orchestration` to identify the next blocker before spending another review cycle.
4. Iterate until merged or blocked.
   - After each fix, run the targeted checks, push the verified head, refresh PR state, update the PR body or ledger when status changed, and continue.
   - Request or rerun external review only when local readiness gates allow it and the review budget rules allow another cycle.
5. Merge only when the ownership and readiness gates pass.
   - Required checks are successful or explicitly accepted under repo policy.
   - Required approvals are present or not required.
   - No unresolved active thread contains an unhandled valid finding.
   - The PR is mergeable, and merge actuation is agent-owned.
   - Use the repo's expected merge method and cleanup policy.

## Stop Conditions

Stop and report the exact blocker when:

- GitHub authentication, repository scope, or PR identity is missing.
- Required checks fail, required approvals are absent, or branch protection blocks merge.
- A review item needs a human decision or conflicts with accepted requirements.
- Merge actuation is not agent-owned.
- Another external review cycle needs explicit approval under `pr-review-orchestration`.
- The next step would delete, overwrite, force-push, or otherwise risk user work without clear permission.

## Closeout

Finish with the PR URL, merge result or blocker, exact verification evidence, review-thread disposition, branch/worktree cleanup, and any repo-required deploy or follow-up commands.

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Treating "PR exists" as review-ready | Refresh the body, verification, and readiness ledger first. |
| Treating "checks pass" as merge-ready | Inspect approvals, requested reviewers, thread state, mergeability, and ownership. |
| Re-running review to diagnose a blocked merge | Read thread-aware PR state and branch protection first. |
| Continuing past a human-owned decision | Report evidence and the decision owner instead of deciding by implication. |
| Applying this to any PR-related request | Use this wrapper only when merge closeout is the goal. |
