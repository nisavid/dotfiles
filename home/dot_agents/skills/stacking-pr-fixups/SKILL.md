---
name: stacking-pr-fixups
description: Use when creating a stacked PR-fixup, follow-up patch PR, companion review-fix PR, or branch named with suffixes like -p0/-p1 that targets another open PR branch.
---

# Stacking PR Fixups

## Overview

A PR-fixup branch is a narrow patch stacked on the PR under review. Its base is the reviewed PR's head branch, and its readiness depends on how complete the requested fixes are.

**Required sub-skills:** Use `writing-reviewable-pr-descriptions` for the PR body, `yeet` when the user asks for the full stage/commit/push/PR flow, and `ralph-review-until-clean` before publishing when requested.

## Workflow

1. Identify the base PR and author:
   - If the user gives a branch instead of a PR number or URL, first list matching open PRs with `gh pr list --head <branch> --state open --json number,headRefName,headRepository,headRepositoryOwner,baseRefName,url`.
   - Continue only when JSON filtering by head owner, repository, and branch identifies exactly one open PR.
   - `gh pr view <base-pr-or-branch> --json number,author,headRefName,headRefOid,headRepository,headRepositoryOwner,url`
   - The fixup PR base is `headRefName`, never the base PR's own base branch.
   - If the base PR head is from a fork or another repository, stop and ask whether to target a same-repository branch instead.
   - If no open PR is found, or multiple PRs match, stop and ask which PR to target.
2. Create the branch from the latest base PR head:
   - Fetch the base head ref.
   - Derive the branch by replacing the first path segment with `ivan/`; if there is no slash, prepend `ivan/`.
   - Remove a trailing `-p<N>` before adding the new suffix.
   - Append `-p<N>`, starting at `-p0` and incrementing to the next unused local head, relevant remote head, or open PR head in the target repository.
   - Example: `jason/multi-cred-test` becomes `ivan/multi-cred-test-p0`.
3. Keep scope narrow:
   - Apply only concrete fixes for the base PR.
   - Preserve unrelated dirty work; stage explicit files only.
   - Use Conventional Commits. Follow any user-requested commit split.
4. Verify the changed surface with focused checks, then any repo-required smoke checks that fit the change.
5. Publish the stacked PR:
   - Head: the fixup branch.
   - Base: the base PR's head branch.
   - Body: state that the PR is stacked on the base PR, list the fixes, and include verification.
   - Mark ready and request review from the base PR author only when the readiness rule below allows it; report any review-request failure instead of silently skipping it.
6. Comment on the base PR after the fixup PR exists:
   - Offer the fixup PR link.
   - Include only a terse, high-level summary of the issues addressed.
   - Keep detailed receipts in the fixup PR body.
7. Verify GitHub metadata after publishing: base branch, head branch, draft state, URL, requested reviewer, and base-PR comment.

## Readiness Rules

| Fix context | Stop point |
| --- | --- |
| The user provides a bounded fix list, or explicitly enumerated review issues are all addressed | Proceed through ready-for-review and request the base PR author's review. |
| Intended fixes are uncertain versus the review intent | Pause before marking ready and ask whether the PR is ready. |
| Some fixes are known, but more are likely | If the user asked to create a PR and the known fixes are committed, open or update a draft PR; otherwise branch-only is fine. Stop before ready-for-review and tell the user it is awaiting further additions. The user can say `Proceed` to mark ready and request review. |
| No fixes are provided yet | Check out the new fixup branch from the base PR head and pause; do not commit or open an empty PR. |

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Basing the fixup PR on `main` | Base it on the reviewed PR's head branch. |
| Reusing `-p0` after another fixup exists | Scan local heads, relevant remote heads, and open PR heads before choosing the suffix ordinal. |
| Marking ready while fixes are speculative or incomplete | Stop at draft or branch-only and ask for the readiness decision. |
| Requesting review while still draft | Request the base PR author's review only after ready-for-review. |
| Duplicating the full fixup rationale on the base PR | Post a short pointer comment and keep details in the fixup PR. |
| Sweeping nearby cleanup into the fixup | Keep the diff to the intended review fixes. |
