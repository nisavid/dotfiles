---
name: using-serena-projects
description: Use when Serena setup, initialization, repair, or use is needed in a repository or worktree
---

# Using Serena Projects

Keep Serena configuration repository-aware: shared configuration belongs to the repository, while worktree identity and other machine-local settings remain local.

## Configuration Ownership

Prefer a committed `.serena/project.yml` plus an ignored `.serena/project.local.yml`. Inspect and preserve existing configuration before changing or initializing Serena. Do not overwrite repository-owned setup.

When local setup is absent, follow this rule: Infer languages from project manifests. Do not guess unsupported Serena configuration keys; if the available schema or tooling does not establish a valid setting, surface the missing schema or tooling context.

## Project Boundaries

Configure ignore rules for in-repo agent worktrees, external sibling worktrees, dependency directories, caches, generated environments, and Serena runtime state.

Treat nested Git repositories and submodules as separate Serena projects. Never add sibling worktrees as additional workspace folders. Give each worktree a unique local `project_name` in its ignored local configuration.
