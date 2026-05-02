---
name: syncing-forks-with-upstream
description: Use when syncing a fork with upstream, clicking Sync fork, using gh repo sync, merging upstream changes, or handling protected-main fork updates where upstream commit identity or intentional fork behavior must be preserved.
---

# Syncing Forks With Upstream

## Overview

Fork sync preserves upstream commit identity and local contracts. Use before choosing a merge method, resolving conflicts, pushing a sync branch, or merging a sync PR.

## Start With The Fork Contract

Before syncing:

1. Read always-loaded agent instructions such as `AGENTS.md`.
2. Look for fork policy files: `.agents/fork-sync-policy.toml`, `docs/maintainers/fork-divergences.md`, or `docs/maintainers/fork-sync-policy.md`.
3. Identify direct upstream, source upstream, fork remote, target branch, upstream baseline, generated/runtime artifacts, and branch protection.
4. If no policy exists, stop and use `onboarding-forks-for-agent-maintenance` before broad sync.

## Merge Method

| Situation | Use | Avoid |
| --- | --- | --- |
| Fork can be updated directly | GitHub **Sync fork** or `gh repo sync OWNER/FORK -b BRANCH` | PR rebase/squash merge |
| Conflicts block direct sync | Conflict-resolution PR, then normal merge commit | Replaying upstream commits |
| Branch protection requires PR | PR merged with a merge commit | Rebase merge, squash merge, cherry-pick series |
| Local command-line sync is needed | `git fetch upstream`; `git merge upstream/main` | `git rebase upstream/main` |

Never force sync, force-push, or overwrite fork history unless the operator explicitly asks to replace history.

## PR Target Guard

Before creating or updating a sync PR, verify the PR target repository is the fork being maintained, not the source upstream:

```bash
git remote -v
gh repo view --json nameWithOwner,parent
```

For downstream fork sync PRs, pass the fork explicitly to GitHub CLI commands, such as `gh pr create --repo OWNER/FORK`, `gh pr view --repo OWNER/FORK`, `gh pr ready --repo OWNER/FORK`, `gh pr checks --repo OWNER/FORK`, and `gh pr merge --repo OWNER/FORK`.

If `gh` opens a PR against the source upstream or parent repository, stop treating that PR as the sync PR. Close it if appropriate, recreate the PR against the maintained fork, and record the mistake in the handoff notes.

## Sync Ledger And Contract Review

Keep a short PR-body or temporary ledger:

- refs fetched, baseline commit, and inventory update;
- policy files read;
- intentional divergences checked;
- affected contracts classified as preserved, upstream now implements it, obsolete by policy, intentionally changed, or uncertain;
- exact local gates run before push;
- unresolved uncertainty for maintainer triage.

For changes touching names, paths, packaging, generated artifacts, release flow, security boundaries, updater behavior, or docs, adapt upstream behavior under local contracts. Do not push or merge while contracts are unchecked, uncertainty is untriaged, or local gates are missing. Generated/runtime artifacts are evidence, not durable fixes.

## Verification

Run repo-local gates before pushing. If policy names a local build gate, CI is secondary. After syncing, verify history shape:

```bash
git fetch origin upstream
git merge-base --is-ancestor upstream/main origin/main
git log --oneline --left-right --cherry-pick origin/main...upstream/main
```

The ancestor check should pass. Patch equivalence is not commit identity.

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Planning only for commit identity | Review fork contracts before push. |
| Accepting upstream names, paths, versions, or docs by default | Check local policy and adapt upstream behavior. |
| Rewriting README, maintainer docs, package templates, or generated-app sources broadly | Do divergence review first. |
| Pushing before local gates pass | Run policy gates and record exact commands. |
| Creating the sync PR against the source upstream | Close the mistaken PR if appropriate, then recreate it with `--repo OWNER/FORK`. |
| Inferring GitHub blockers from summary status | Inspect blocking checks, alerts, reviews, and threads directly. |
| Closing review comments without revalidation | Revalidate the changed surface first. |
