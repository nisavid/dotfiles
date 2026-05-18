---
name: getting-prs-merged
description: >-
  Use when the user explicitly asks to get a GitHub branch or pull request merged, shipped, over the line, or closed out end to end: "get this merged", "drive it to merge", "ship this PR", "merge and close out this branch", or resume a previously stated merge/closeout workflow. Do not use for single-step PR operations, PR-description-only, review-only, status-only, issue-triage, check-only, CI-check-only, comment-only, ready-only, open-PR-only, draft-PR-only, or publish-only requests unless the user also states a merge or closeout goal. Requests to inspect checks, blockers, readiness, comments, or policy without asking to continue toward merge do not trigger this skill. Requests that say to open a PR, leave it draft, or that the PR is not ready to merge do not trigger this skill.
---

# Getting PRs Merged

## Overview

This is the convenience wrapper for PR closeout when merge is the requested outcome. It coordinates the narrower skills and starts at the current state instead of replaying completed steps.

Core principle: move toward merge under the current repo and workflow policy. Be autonomous only inside the authority the user, repository, and current PR state actually grant.

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
2. Discover local policy before acting.
   - Read applicable `AGENTS.md`, repo-local skills, maintainer docs, PR templates, and current user instructions.
   - Treat those as constraints on autonomy, review policy, commit style, PR body requirements, ready-for-review, thread resolution, merge method, deploy commands, and branch cleanup.
   - When local policy narrows autonomy, follow that policy and report the owner or gate instead of forcing full closeout.
3. Inventory state before changing anything.
   - Check `gh` auth, branch status, local changes, existing PR, PR head SHA, current draft/ready state, checks, reviewers, and thread-aware review state.
   - Use `pr-review-orchestration`'s `scripts/pr_review_state.py --summary` or an equivalent GraphQL review-thread query for thread state. Do not rely on `gh pr view`, status checks, bot status contexts, or auto-merge state alone to infer that conversations are resolved.
   - Preserve unrelated user changes. Ask before touching ambiguous or unrelated dirty work.
4. Start at the first incomplete stage.
   - No PR yet: use `yeet` to stage, commit, push, and open a draft PR.
   - Draft or stale PR body: use `writing-reviewable-pr-descriptions` to update the body from the real pushed diff and current verification.
   - Ready gate pending: use `pr-review-orchestration`; mark ready only after local readiness gates pass and the PR body records evidence.
   - Review comments or requested changes present: use `github:gh-address-comments`, then `pr-review-orchestration` for classification, evidence, thread resolution, and ledger updates.
   - Merge blockers present: use `pr-review-orchestration` to identify the next blocker before spending another review cycle.
5. Iterate until merged or blocked.
   - After each fix, run the targeted checks, push the verified head, refresh PR state, update the PR body or ledger when status changed, and continue.
   - Before diagnosing a blocked merge as missing approval, branch policy, last-pusher approval, or bot-review state, refresh thread-aware PR state. If GitHub says the PR is blocked while checks are green and the head is mergeable, unresolved conversations are a first-class blocker to check, not an afterthought.
   - When `pr-review-orchestration` classifies an unresolved review thread as fixed, already fixed, stale, outdated, duplicate, or otherwise handled with evidence, resolve it yourself as part of merge closeout. Do not ask for separate confirmation just because resolving the thread satisfies a branch-policy gate; ask only when the thread needs a human decision or repo policy reserves resolution for another owner.
   - Request or rerun external review only when local readiness gates allow it and the review budget rules allow another cycle.
   - When CodeRabbit is the expected external reviewer and its latest check or comment says the review was skipped, do not treat that as a completed external review cycle. If local readiness gates pass and the external review budget allows another attempt, comment on the PR to request CodeRabbit explicitly, normally with `@coderabbit-ai review`. If the diff is already clean and the only remaining branch-protection gate is CodeRabbit approval, request that explicitly with `@coderabbit-ai approve pls`.
6. Merge only when the ownership and readiness gates pass.
   - Required checks are successful or explicitly accepted under repo policy.
   - Required approvals are present or not required.
   - Refreshed thread-aware state shows no unresolved review conversations, including outdated unresolved threads when conversation resolution is required.
   - No unresolved active thread contains an unhandled valid finding.
   - Evidenced, handled review threads have been resolved under `pr-review-orchestration`; only human-decision or policy-reserved threads remain open, and those are reported as the blocker.
   - The PR is mergeable, and merge actuation is agent-owned.
   - Use the repo's expected merge method and cleanup policy.

## Stop Conditions

Stop and report the exact blocker when:

- GitHub authentication, repository scope, or PR identity is missing.
- Required checks fail, required approvals are absent, or branch protection blocks merge after thread-aware state confirms unresolved conversations are not the blocker.
- A review item needs a human decision or conflicts with accepted requirements.
- Merge actuation is not agent-owned.
- Local policy requires a step, approval, review strategy, deploy gate, or handoff that has not happened yet.
- Another external review cycle needs explicit approval under `pr-review-orchestration`.
- The next step would delete, overwrite, force-push, or otherwise risk user work without clear permission.

## Closeout

Finish with the PR URL, merge result or blocker, exact verification evidence, review-thread disposition, branch/worktree cleanup, and any repo-required deploy or follow-up commands.

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Treating "PR exists" as review-ready | Refresh the body, verification, and readiness ledger first. |
| Treating "checks pass" as merge-ready | Inspect approvals, requested reviewers, thread state, mergeability, and ownership. |
| Explaining a blocked green PR as approval or ruleset trouble before checking conversations | Run `pr_review_state.py --summary --json` or equivalent GraphQL review-thread state, then resolve or report unresolved threads first. |
| Assuming full autonomy from "get this merged" | Read repo and workflow policy first; autonomy is scoped by those instructions. |
| Skipping repo-local closeout rules | Apply local merge method, review policy, deploy guidance, and branch cleanup rules. |
| Treating a skipped CodeRabbit check as final review evidence | Comment on the PR to request CodeRabbit explicitly when gates and budget allow it. |
| Re-running review to diagnose a blocked merge | Read thread-aware PR state and branch protection first. |
| Continuing past a human-owned decision | Report evidence and the decision owner instead of deciding by implication. |
| Applying this to any PR-related request | Use this wrapper only when merge closeout is the goal. |
