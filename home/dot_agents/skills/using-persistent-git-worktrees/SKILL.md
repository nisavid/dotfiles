---
name: using-persistent-git-worktrees
description: Use with using-git-worktrees when starting feature work that needs isolation from the current workspace, before executing implementation plans in a git worktree, choosing, auditing, moving, repairing, cleaning up, or handing off persistent worktrees, or resolving the local failure mode where coding agents use `.worktrees`, `worktrees`, `/tmp`, or global worktree paths instead of sibling `.wt` setup.
---

# Using Persistent Git Worktrees

Read the applicable base worktree skill first, then apply this policy for
durable, human-discoverable coding-agent worktrees.

This skill is an override for persistent coding worktrees:

- Use a sibling `.wt` directory beside the main clone.
- Do not follow the base skill's `.worktrees` / `worktrees` directory
  selection, ignore-check, or ask-the-user fallback when this persistent
  worktree policy applies.
- After the worktree exists, continue with the base skill's project setup and
  baseline verification unless the user or repo docs say otherwise.

Precedence is: user instruction, then repo-local policy, then this skill, then
the base worktree skill.

## Use When

- starting substantial work that should not reuse the active checkout
- before executing an implementation plan in a git worktree
- choosing or auditing persistent worktree locations
- moving, repairing, cleaning up, or handing off agent worktrees
- resolving sandbox or approval friction around sibling `.wt` setup

## Directory Policy

Default to a sibling `.wt` directory beside the main clone unless repo docs or
the user explicitly require a different persistent location.

```text
~/src/project
~/src/project.wt/<branch-or-task-name>
```

Do not place persistent coding worktrees under `/tmp`, cache directories, or
other automatically cleaned locations. Use temporary paths only for disposable
experiments that contain no in-progress branch work.

Report the full worktree path and branch name after creation.

## Sandbox And Approval Policy

If the sibling `.wt` path or shared `git worktree` metadata writes need
approval because they sit outside the writable roots, request escalation.
Do not reroute persistent branch work to `/tmp` just because it is writable.

## Creation Pattern

For `/path/to/project` and branch `feature-x`:

```bash
mkdir -p /path/to/project.wt
git worktree add /path/to/project.wt/feature-x -b feature-x
cd /path/to/project.wt/feature-x
git worktree list --porcelain
git status --short
```

If the branch already exists, omit `-b`:

```bash
git worktree add /path/to/project.wt/feature-x feature-x
```

After creation, continue with the base skill's project setup and baseline
verification from inside the worktree.

## Context Checks

At the start and end of substantial tasks, and before switching focus, run:

```bash
git worktree list --porcelain
git status --short
```

When the active worktree differs from the main checkout, check both and report
which path is active.

## Submodules

In a new worktree, initialize submodules recursively when the task depends on
upstream, recipe, fixture, or reference source:

```bash
git submodule update --init --recursive
```

Do this before treating missing submodule content as unavailable.

## Moving Wrongly Placed Worktrees

If a worktree was created in the wrong location, prefer:

```bash
git worktree move <old-path> <new-path>
```

Do not copy a worktree with `cp -a`; duplicate filesystem copies can share Git
administrative state and leave agents operating in the wrong path.

If `git worktree move` cannot move the worktree and it has no uncommitted work,
remove and recreate it:

```bash
git -C <old-path> status --short
git worktree remove <old-path>
git worktree add <new-path> <branch>
git -C <new-path> status --short
git worktree list --porcelain
```

If the wrongly placed worktree has uncommitted work, stop and ask before moving
or recreating it.

## Handoff

Every worktree handoff should state:

- main checkout path and status
- active worktree path and branch
- latest relevant commits
- uncommitted files, if any
- stale worktree copies or cleanup still needed

## Guardrails

- Do not switch the user's main checkout away from `main` just to start work.
- Do not leave the active path ambiguous in a handoff.
