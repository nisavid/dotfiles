---
name: using-persistent-git-worktrees
description: Use when starting feature work that needs isolation from the current workspace, before executing implementation plans in a git worktree, choosing or auditing git worktree locations, using Superpowers using-git-worktrees, or moving, repairing, cleaning up, or handing off agent worktrees.
---

# Using Persistent Git Worktrees

This skill extends `using-git-worktrees` and
`superpowers:using-git-worktrees`.

Read the base worktree skill first. Then apply this local policy for durable,
human-discoverable coding-agent worktrees. If this skill conflicts with the
base location policy, this local policy wins.

## Directory Policy

Default to a sibling `.wt` directory beside the main clone. This overrides the
base skill's nested `.worktrees/` and `worktrees/` preference unless repo docs
or the user explicitly require a deliberate ignored in-repo worktree directory.

```text
~/src/project
~/src/project.wt/<branch-or-task-name>
```

Do not place persistent coding worktrees under `/tmp`, cache directories, or
other automatically cleaned locations. Use temporary paths only for disposable
experiments that contain no in-progress branch work.

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

After creation, report the full path and branch name, then continue with the
base skill's project setup and baseline verification from inside the worktree.

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
