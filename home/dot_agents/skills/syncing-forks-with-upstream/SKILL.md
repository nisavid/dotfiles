---
name: syncing-forks-with-upstream
description: Use when syncing a fork with upstream, clicking Sync fork, using gh repo sync, merging upstream changes, or handling protected-main fork updates where upstream commit identity should be preserved.
---

# Syncing Forks With Upstream

## Overview

When updating a fork from its source, preserve upstream commit objects. Fork sync is history maintenance first; PR review is secondary unless rules or conflicts force it.

This extends `gh-cli`, `pr-review-orchestration`, and PR comment skills. Apply it before choosing a merge method.

## Decision Rule

| Situation | Use | Avoid |
| --- | --- | --- |
| Fork can be updated directly | GitHub **Sync fork** or `gh repo sync OWNER/FORK -b BRANCH` | PR rebase/squash merge |
| Direct sync is blocked by conflicts | Conflict-resolution PR, then normal merge commit | Replaying upstream commits |
| Branch protection requires PR | PR merged with a merge commit | Rebase merge, squash merge, cherry-pick series |
| Local command-line sync is needed | `git fetch upstream`; `git merge upstream/main` | `git rebase upstream/main` |

## Required Checks

Before syncing:

1. Identify fork remote, upstream remote, branch names, and branch protection.
2. State whether preserving upstream commit identity is required. Default to required.
3. Prefer `gh repo sync <fork> -b <branch>` or GitHub Sync fork when it can fast-forward or merge directly.
4. If a PR is unavoidable, choose the merge method that preserves the upstream commit objects. On GitHub, that means a normal merge commit, not rebase or squash.
5. Do not use `gh repo sync --force`, force-push, or overwrite history unless the user explicitly asks to replace fork history.

After syncing:

```bash
git fetch origin upstream
git merge-base --is-ancestor upstream/main origin/main
git log --oneline --left-right --cherry-pick origin/main...upstream/main
```

The ancestor check should pass. The cherry-pick check is only diagnostic; patch equivalence does not mean history was preserved.

## Red Flags

- The command includes `gh pr merge --rebase`, `--squash`, `git rebase`, or `git cherry-pick` for upstream commits.
- The command includes `gh repo sync --force` or force-push during routine fork sync.
- A protected-branch PR is treated as permission to change the history shape.
- Review automation chooses merge method based on linear history preference instead of fork-sync identity.
- `git range-diff` shows `=` but `git merge-base --is-ancestor upstream/main origin/main` fails.
- The PR branch has upstream commits intact, but the selected merge method will replay them.

## Common Mistakes

| Mistake | Correction |
| --- | --- |
| Using PR auto-merge with rebase because checks and reviews are required | Keep the PR, but select merge commit. |
| Treating patch-equivalent commits as good enough | Verify ancestry; Git history depends on commit object identity. |
| Assuming branch protection forbids structure-preserving sync | Check whether Sync fork or merge-commit PR is allowed before choosing rebase. |
| Letting PR closeout skills decide the merge method alone | Apply this skill first, then run PR review orchestration inside that constraint. |
