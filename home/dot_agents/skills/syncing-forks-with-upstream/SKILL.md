---
name: syncing-forks-with-upstream
description: Use when syncing a fork with upstream, clicking Sync fork, using gh repo sync, merging upstream changes, or handling protected-main fork updates where upstream commit identity or intentional fork behavior must be preserved.
---

# Syncing Forks With Upstream

## Overview

Fork sync preserves upstream commit identity and intentional local contracts. Use this before choosing a merge method, resolving conflicts, pushing a sync branch, or merging a protected-main sync PR.

## Start With The Fork Contract

Before syncing:

1. Read always-loaded agent instructions such as `AGENTS.md`.
2. Look for repo-local fork policy files such as `.agents/fork-sync-policy.toml`, `docs/maintainers/fork-divergences.md`, or `docs/maintainers/fork-sync-policy.md`.
3. Identify direct upstream, source upstream when different, fork remote, target branch, current upstream baseline, generated/runtime artifacts, and branch protection.
4. If no policy exists, stop and use `onboarding-forks-for-agent-maintenance` before doing a broad sync.

## Merge Method

| Situation | Use | Avoid |
| --- | --- | --- |
| Fork can be updated directly | GitHub **Sync fork** or `gh repo sync OWNER/FORK -b BRANCH` | PR rebase/squash merge |
| Conflicts block direct sync | Conflict-resolution PR, then normal merge commit | Replaying upstream commits |
| Branch protection requires PR | PR merged with a merge commit | Rebase merge, squash merge, cherry-pick series |
| Local command-line sync is needed | `git fetch upstream`; `git merge upstream/main` | `git rebase upstream/main` |

Never force sync, force-push, or overwrite fork history unless the operator explicitly asks to replace history.

## Sync Ledger And Contract Review

Keep a short PR-body or temporary ledger:

- refs fetched and baseline commit;
- policy files read;
- intentional divergences checked;
- affected contracts classified as preserved, upstream now implements it, obsolete by policy, intentionally changed, or uncertain;
- exact local gates run before push;
- unresolved uncertainty for maintainer triage.

For changes touching names, paths, packaging, generated artifacts, release flow, security boundaries, updater behavior, or docs, adapt upstream behavior under local contracts. Do not push or merge while contracts are unchecked, uncertainty is untriaged, or required local gates are missing. Generated/runtime artifacts are evidence, not durable fixes.

## Verification

Run repo-local gates before pushing. If policy names a local build gate, CI is secondary evidence. After syncing, verify history shape:

```bash
git fetch origin upstream
git merge-base --is-ancestor upstream/main origin/main
git log --oneline --left-right --cherry-pick origin/main...upstream/main
```

The ancestor check should pass. Patch equivalence does not prove commit identity.

## Red Flags And Fixes

- The plan only discusses commit identity and does not mention fork contracts.
- A conflict accepts upstream names, paths, package versions, or docs without checking local policy.
- A broad sync rewrites README, maintainer docs, package templates, or generated-app sources without divergence review.
- The branch is pushed before local build gates named in policy have passed.
- GitHub merge state or code-scanning blockers are inferred from summary checks instead of inspecting the blocking review/check/alert details.
- Review comments are closed before the exact changed surface is revalidated.
