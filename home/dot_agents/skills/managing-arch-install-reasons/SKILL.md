---
name: managing-arch-install-reasons
description: Use when installing packages with pacman or paru for build, test, debug, packaging, or other transient work, especially when those packages should not remain explicitly installed after the task.
---

# Managing Arch Install Reasons

## Overview

Arch tracks whether a package was installed explicitly or as a dependency. That distinction matters.

If a package is needed only to satisfy build-time, test-time, debug-time, or other temporary task requirements, install it as a dependency. Do not leave transient support packages marked as explicitly installed.

## Core Rule

- Use `--asdeps` when installing packages needed only for the current task.
- If a package was installed explicitly by mistake, convert it to a dependency immediately.
- Install a package explicitly only when it is intended to remain a user-managed top-level tool.

## When To Treat a Package as a Dependency

Use dependency installs for packages that are needed only to:

- satisfy `makedepends`, `checkdepends`, or similar packaging requirements
- run builds, tests, or linters for a specific task
- provide temporary debugging or inspection utilities
- satisfy helper tooling needed only to complete the current job

If the package is not something the user would reasonably want to keep as a top-level install after the task, it should usually be installed as a dependency.

## Commands

### Install as a dependency

With `pacman`:

```bash
sudo pacman -S --asdeps <package>
```

With `paru`:

```bash
paru -S --asdeps <package>
```

### Repair an incorrect explicit install

With `pacman`:

```bash
sudo pacman -D --asdeps <package>
```

With `paru`:

```bash
paru -D --asdeps <package>
```

### Promote to an explicit install when appropriate

If a package should remain installed as a user-managed top-level tool:

```bash
sudo pacman -D --asexplicit <package>
```

or:

```bash
paru -D --asexplicit <package>
```

## Working Rules

1. Before installing, decide whether the package is transient or durable.
2. If it is transient, install it with `--asdeps`.
3. If a command or previous step installed it explicitly, fix the install reason right away with `-D --asdeps`.
4. If a set of packages has mixed intent, split the install into separate commands instead of assigning one install reason to all of them.
5. Do not assume that "I installed it for the task" is enough. The recorded install reason must match the intent.

## Quick Reference

- Build backend for packaging task: install as dependency
- Test-only tool needed for one verification run: install as dependency
- Debug helper used only for current investigation: install as dependency
- CLI the user wants available long-term: install explicitly
- Mistaken explicit install during task execution: convert with `-D --asdeps`

## Common Mistakes

### Installing transient packages explicitly

This leaves temporary support packages pinned as top-level installs and prevents normal dependency cleanup.

### Assuming build-time dependencies do not matter after the task

They still matter if they remain marked explicit. Install reason affects future pruning and orphan cleanup.

### Mixing permanent and temporary packages in one install

If one package should be explicit and another should be a dependency, install them separately or fix their reasons afterward.

### Forgetting to repair a mistaken install

If the package is already installed and the reason is wrong, correct it immediately instead of leaving cleanup for later.
