---
name: working-in-systalyze-worktrees
description: Use for any task whose target is the `systalyze` repo or a `systalyze` checkout, including read-only scouting, code review, edits, checks, commits, rebases, cherry-picks, pushes, deploys, `/Users/ivan/src/systalyze`, `/Users/ivan/.codex/worktrees/*/systalyze`, PR branches, local-only setup branches, auxiliary branches such as `ivan/setup-local` or `ivan/impeccable`, detached HEADs, and cases where the agent is homed in one Systalyze worktree but operates in another.
---

# Working In Systalyze Worktrees

## Overview

Treat each Systalyze checkout as a target with its own branch state. Inspect the target checkout before deciding whether the task is read-only, PR product work, auxiliary branch work, or branch rescue. Keep local setup and grounding scaffolding out of pushed product history, and make every push to a PR branch an explicit cherry-pick of intended commits.

When running dev scripts, package scripts, local services, or `scripts/sz.zsh`, also read the target checkout's `.agents/skills/using-dev-environment/SKILL.md` when it exists. That repo-local skill owns the Vite Plus, `vp`/`vpr`, and `sz -s/--src` command policy. If that file is missing and the task depends on local services, `vp`, `vpr`, or `sz` behavior, stop and surface the missing target-checkout setup context instead of guessing.

Read-only tasks do not need local setup commits merely to inspect files, answer questions, or review diffs. State-changing tasks use the appropriate target mode below.

## Preconditions

- Identify every Systalyze Git root you will touch before changing state. Do not infer the target checkout from the shell's current directory.
- For each target root, inspect branch, status, upstream, and recent history before rebasing, cherry-picking, committing, or pushing.
- If a path is outside the current `cwd`, use explicit `workdir` or `git -C <target-root>` commands.
- If the worktree is dirty with changes you did not make, preserve them and work around them. Ask only when they make the requested work impossible.

## Branch Roles

| Role | Meaning |
| --- | --- |
| `PR_BRANCH` | The remote-backed or intended future branch for product commits that belong in a PR |
| `LOCAL_BRANCH` | A local-only merge branch used for scouting, setup-local scaffolding, checks, edits, and local commits |
| `AUX_BRANCH` | A non-product support branch such as `ivan/setup-local`, `ivan/impeccable`, or another explicitly named auxiliary branch |
| `ivan/setup-local` | Auxiliary branch for local setup scripts, worktree setup, and local development tooling |
| `ivan/impeccable` | Auxiliary branch for grounding docs, agent-facing context, domain, product, and design guidance |

Names can vary by task. Verify the actual PR head and branch ownership from Git and, when relevant, the live PR.

## Choose Target Mode

Choose one mode before changing Git state.

### Read-only or Review Mode

Use when answering questions, inspecting state, reviewing code, or gathering evidence without editing, committing, pushing, or running setup-dependent local services.

1. Identify the target Git root.
2. Inspect branch, status, upstream, and relevant history.
3. Avoid branch changes unless the requested inspection cannot be done safely from the current state.
4. If the task becomes state-changing, pause and switch to the appropriate mode.

### Existing PR Mode

Use when there is a known PR branch or the user names the active PR branch. This is the normal product-work path: product commits are made on `LOCAL_BRANCH`, then cherry-picked to `PR_BRANCH`.

### New PR Mode

Use when the work is product work but no PR branch exists yet.

1. Fetch and update `origin/main` unless doing so would disturb local-only or unpushed work.
2. Choose or create the intended `PR_BRANCH` from current `origin/main`, using `ivan/<slug>` unless instructed otherwise.
3. Create `LOCAL_BRANCH` from that `PR_BRANCH`.
4. Continue through the standard workflow.

### Auxiliary Branch Mode

Use when the task explicitly targets `ivan/setup-local`, `ivan/impeccable`, or another support branch. Do not invent a `PR_BRANCH`.

1. Identify the `AUX_BRANCH` and its owner branch.
2. Make branch-owned changes directly on that branch, or use `LOCAL_BRANCH` plus `format-patch` when the user asks for the local setup workflow.
3. Push the auxiliary branch only when requested or when the task explicitly includes publishing it.
4. If auxiliary work was temporarily committed on `LOCAL_BRANCH`, squash or fix it into the appropriate auxiliary commit and refresh `LOCAL_BRANCH` from the updated auxiliary branch instead of carrying a duplicate patch.

### Detached-head Rescue Mode

Use when the target checkout is detached or history shape is suspicious.

1. Record `HEAD`, nearby branch refs, `git status`, and unpushed commits before switching branches.
2. Identify the intended target branch from Git, the live PR, or the user request.
3. Preserve work with a safety branch or patch before rebasing, cherry-picking, or checkout.
4. Continue in read-only, existing PR, new PR, or auxiliary branch mode once the branch owner is clear.

If mode selection is ambiguous and the ambiguity affects what branch will receive commits or pushes, ask before changing Git state.

## Standard Workflow

Use this workflow for existing PR mode and new PR mode.

### 1. Prepare the Local Branch

Before scouting, checks, implementation, or troubleshooting:

1. Fetch the refs needed to identify `origin/main`, the PR branch, `ivan/setup-local`, and `ivan/impeccable`.
2. Identify the real `PR_BRANCH`. Be suspicious of detached HEADs, stale worktrees, stacked branches, and unusual commit history.
3. If `LOCAL_BRANCH` already exists, record and classify `PR_BRANCH..LOCAL_BRANCH` before moving it:
   - product commits intended for the PR;
   - setup commits from `ivan/setup-local`;
   - grounding commits from `ivan/impeccable`;
   - user or unknown commits that must be preserved.
4. Create or update `LOCAL_BRANCH` from the PR branch tip while preserving any intended product or user commits.
5. Cherry-pick the local scaffolding range onto `LOCAL_BRANCH`:
   - `main..ivan/setup-local` for local setup and toolchain scaffolding.
   - `main..ivan/impeccable` only when grounding docs or agent-facing context are needed and equivalent changes are not already present.
6. Keep `LOCAL_BRANCH` checked out while scouting, troubleshooting, running local checks, editing, and making local commits.

Before applying `main..ivan/impeccable`, check whether its commits or equivalent patches are already present. Prefer ancestry checks when possible; otherwise compare `git cherry` or patch IDs for the `main..ivan/impeccable` range against the target branch. Do not duplicate grounding commits merely because their original commit IDs differ.

Do not push `LOCAL_BRANCH`. Do not push the setup or grounding commits as part of the PR branch unless the user explicitly asks for that branch's own scaffolding changes to be part of the PR.

### 2. Commit Product Work Locally

Commit intended product changes on `LOCAL_BRANCH`.

- Keep setup or grounding changes in separate commits from product changes.
- Use Conventional Commits.
- Before commit, check the diff against the PR branch, not only against the local setup branch, so setup scaffolding does not hide what will be pushed.
- If a commit mixes product work with setup or grounding edits, split it before pushing.

### 3. Push Through the PR Branch

When it is time to push:

1. Re-fetch the PR branch.
2. If the PR branch advanced, rebase or recreate `LOCAL_BRANCH` from the new PR tip and reapply only the intended local product commits.
3. List candidate commits from `PR_BRANCH..LOCAL_BRANCH` and classify each as product, setup, grounding, user, or unknown.
4. Stop before modifying `PR_BRANCH` if any candidate commit cannot be classified.
5. Create a local safety ref for the current `PR_BRANCH` tip before cherry-picking.
6. Switch to `PR_BRANCH`.
7. Cherry-pick only the product commits meant for the PR.
8. Verify the post-cherry-pick state:
   - `origin/PR_BRANCH..HEAD` contains only intended product commits;
   - the diff from `origin/PR_BRANCH` excludes setup-local and grounding-only changes;
   - the pushed branch does not include `main..ivan/setup-local` or `main..ivan/impeccable` unless explicitly requested.
9. If the wrong commits are present locally before push, reset `PR_BRANCH` to the safety ref and redo the cherry-pick.
10. Run the checks appropriate to the pushed change from the PR branch state.
11. Push `PR_BRANCH`.
12. Switch back to `LOCAL_BRANCH` before continuing work.

If wrong commits already reached `origin`, stop and report the exact commits and branch state. Do not force-push or rewrite the remote branch without explicit instruction.

If CI appears stale after a successful local cherry-pick, compare the PR head SHA to local `HEAD`; GitHub will not test a detached or local-only commit until it has been pushed to the PR branch.

## Auxiliary Branch Work

### Setup-local Changes

Use `ivan/setup-local` for durable changes to local setup scripts, local worktree setup, Vite Plus or `vp`/`vpr` development setup, shell helpers, and agent workflows that exist to prepare a local working branch.

Recommended flow:

1. Make and commit the change on `LOCAL_BRANCH`.
2. Export it with `git format-patch` or an equivalent patch from the local commit.
3. Apply it to `ivan/setup-local`.
4. Squash or fix it into the appropriate setup-local commit.
5. Push the auxiliary branch only when requested or when the task explicitly includes updating that branch.
6. Recreate or rebase `LOCAL_BRANCH` so it contains the updated auxiliary commit instead of a duplicate local patch commit.

### Grounding And Agent Context Changes

Use `ivan/impeccable` for durable changes to `CONTEXT.md`, `PRODUCT.md`, `DESIGN.md`, `docs/agents/**`, agent-facing policy, domain modeling, product framing, design guidance, and review-polish instructions.

Recommended flow:

1. Make and commit the change on `LOCAL_BRANCH`.
2. Convert it to a patch.
3. Apply it to `ivan/impeccable`.
4. Squash or fix it into the appropriate grounding commit.
5. If the active PR needs reviewers to see the patch before `ivan/impeccable` merges, include the patch content or a concise pointer in the PR body when requested.
6. Rebase or recreate `LOCAL_BRANCH` from the refreshed auxiliary branches.

When a change has both product and auxiliary parts, split the commits by ownership before any push.

### Publishing Auxiliary Branches

Before pushing an auxiliary branch:

1. Create a local safety ref for the current auxiliary branch tip.
2. Verify the final auxiliary branch contains only branch-owned changes.
3. Prefer a normal fast-forward push.
4. If squashing, fixing up, or rebasing makes the push non-fast-forward, stop and ask before any force push or remote rewrite unless the user already gave explicit rewrite instructions for that auxiliary branch.
5. After a successful auxiliary push, refresh any `LOCAL_BRANCH` that carries the old auxiliary commits so the local branch does not retain duplicate setup or grounding patches.

## Cross-worktree And Tooling Edge Cases

- If the agent is homed in one Systalyze worktree but acts in another, apply this workflow to the target worktree, not the home worktree.
- Use explicit target roots for Git operations, checks, setup scripts, and `sz` commands. For `sz`, use the target worktree's `scripts/sz.zsh`, or pass `sz -s/--src <target-root>` for a one-off source override.
- Do not run setup, checks, or deploy helpers from a different worktree unless that is intentional and the target source root is explicit.
- Parallel worktrees may have different local service ports and environment files. Use the dev-environment skill before starting services or interpreting local URLs.
- If a `git cherry-pick` or index update fails with `index.lock: Operation not permitted`, treat permissions or sandboxing as the first suspect, not a merge conflict.
- If branch history looks strange, inspect the branch-owned patch set before rebasing. Do not trust visible tip shape alone.

## Final Reporting

For any task that changes Git state, report:

- Target mode.
- Target worktree path and final checked-out branch.
- Local commits created.
- Candidate commits considered for push and which were cherry-picked.
- Product commits cherry-picked to the PR branch and pushed, if any.
- Safety ref used for PR-branch cherry-picking, if any.
- Auxiliary branches touched, if any.
- Checks run and their result.
- Any setup or grounding commits intentionally kept local-only.

## Common Mistakes

- Editing in a local setup branch and pushing that branch to origin.
- Cherry-picking `main..ivan/setup-local` directly onto the PR branch.
- Running checks before the target worktree has the local setup and grounding commits the task depends on.
- Assuming the current shell's worktree is the worktree affected by a path, script, or helper command.
- Letting setup, grounding, and product edits share one commit.
- Treating read-only review work as if it needs local setup commits.
- Duplicating `ivan/impeccable` grounding commits because only commit IDs were checked.
- Pushing before listing and classifying `LOCAL_BRANCH` commits.
- Forgetting to switch back to `LOCAL_BRANCH` after pushing the PR branch.
