---
name: syncing-forks-with-upstream
description: Use when syncing a fork with upstream, clicking Sync fork, using gh repo sync, merging upstream changes, or handling protected-main fork updates where upstream commit identity or intentional fork behavior must be preserved.
---

# Syncing Forks With Upstream

## Overview

Fork sync preserves upstream commit identity and local contracts. Use before choosing a merge method, resolving conflicts, pushing a sync branch, or merging a sync PR.

The default completed state is that the maintained fork's target branch
contains the synced upstream head. When branch protection requires a PR, the
sync work includes opening the PR, driving it through required checks and review
state, merging it with the repo-approved sync merge method, and verifying the
post-merge target branch. Stop at an open PR only when the operator explicitly
asks for that handoff, merge actuation is not agent-owned, or a concrete blocker
remains.

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

For downstream fork sync PRs, pass `--repository OWNER/FORK` to the owned
creator in `publishing-reviewable-prs`. Use its owned helper for ready
actuation. Pass the fork explicitly to subsequent read/merge commands, such as
`gh pr view --repo OWNER/FORK`, `gh pr checks --repo OWNER/FORK`, and
`gh pr merge --repo OWNER/FORK`.

Use `publishing-reviewable-prs` for every sync PR creation, title edit, or body
edit. It must use `writing-reviewable-pr-descriptions` and an explicit body file;
never use `gh pr create --fill`. Preserve the sync ledger in the canonical body.

If `gh` opens a PR against the source upstream or parent repository, stop treating that PR as the sync PR. Close it if appropriate, recreate the PR against the maintained fork, and record the mistake in the handoff notes.

## Sync Ledger And Contract Review

Keep a short PR-body or temporary ledger:

- refs fetched, baseline commit, and inventory update;
- policy files read;
- intentional divergences checked;
- affected contracts classified as preserved, upstream now implements it, obsolete by policy, intentionally changed, or uncertain;
- exact local gates run before push;
- unresolved uncertainty escalated to the operator, or linked to a durable,
  discoverable follow-up when escalation is unavailable.

For changes touching names, paths, packaging, generated artifacts, release flow, security boundaries, updater behavior, or docs, adapt upstream behavior under local contracts. Do not push or merge while contracts are unchecked, uncertainty is untriaged, or local gates are missing. Generated/runtime artifacts are evidence, not durable fixes.

## Policy Gap Closeout

During a sync, treat a discovered repeatable failure mode as part of the work.
If you notice a hazard that future sync agents could miss, codify the rule
before handoff instead of leaving it only in chat, the PR description, or local
memory.

Use the narrowest durable surface that will load at the right time:

- repo-local fork policy for repository-specific names, paths, rename maps,
  contracts, gates, and source boundaries;
- this skill for fork-sync behavior that applies across maintained forks;
- always-loaded repo instructions only for rules needed before a workflow can
  choose the right triggered guidance;
- tests or scripts for repeatable mechanical checks.

Record the policy update in the sync ledger. If the right owner is unclear,
escalate to the operator when the session allows. Only defer the decision when
escalation is unavailable or the operator requested an uninterrupted run; in
that case, record a durable, discoverable follow-up where the escalation would
have happened. Preserve the safest local guard that prevents silent data loss,
dropped upstream changes, history replay, or contract drift.

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
| Creating the sync PR against the source upstream | Close the mistaken PR if appropriate, then recreate it through `publishing-reviewable-prs` with `--repository OWNER/FORK`. |
| Letting `--fill` or a sync tool's generated text become the final body | Publish through `publishing-reviewable-prs` and verify the stored canonical body. |
| Noticing a repeatable sync hazard but leaving it in chat only | Add it to the narrowest durable policy surface and record that closeout. |
| Inferring GitHub blockers from summary status | Inspect blocking checks, alerts, reviews, and threads directly. |
| Closing review comments without revalidation | Revalidate the changed surface first. |
| Treating the draft or open sync PR as the finished sync | Continue through ready-for-review, review/blocker resolution, merge, and post-merge verification unless explicitly handed off or blocked. |
