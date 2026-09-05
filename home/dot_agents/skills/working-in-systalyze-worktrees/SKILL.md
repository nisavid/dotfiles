---
name: working-in-systalyze-worktrees
description: Use when a task's target is a Systalyze checkout or worktree, including target discovery, target-mode selection, pre-merge stack consumption or publication, safety preparation, local-cluster-role routing, or product-history cleanup.
---

# Working in Systalyze worktrees

Own target checkout discovery, target-mode selection, preservation and safety boundaries, local-cluster-role routing, and keeping local development scaffolding out of pushed product history.

## Establish live authority

Before planning or mutation, dynamically inspect the current branch and worktree state, the selected target checkout, and applicable repo-local instructions. Current repo-local AGENTS files, development skills, manifests, scripts, and CI own exact package runners, setup commands, branch topology, and verification breadth. Derive any required gitlink handling from those current sources too.

Current repository evidence takes precedence over frozen global guidance unless the operator explicitly overrides it. If applicable instructions conflict or precedence remains ambiguous, stop before consequential mutation and ask the operator to resolve the boundary.

Do not freeze branch stacks, package runners, gitlink handling, or universal smoke commands into this skill. Re-discover them from the target repository each time.

## Apply the temporary pre-merge contract

While `references/premerge-stack.json` exists, it is the sole source of the temporary grounding-docs and dev-tooling stack alias names. Before creating or publishing product work, or publishing either provider stack, read `references/premerge-stack-surfaces.md` and run this block against the verified Systalyze remote:

```sh
(
  unset LD_AUDIT LD_LIBRARY_PATH LD_PRELOAD \
    DYLD_FALLBACK_FRAMEWORK_PATH DYLD_FALLBACK_LIBRARY_PATH \
    DYLD_FRAMEWORK_PATH DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH \
    DYLD_ROOT_PATH DYLD_SHARED_CACHE_DIR \
    DYLD_VERSIONED_FRAMEWORK_PATH DYLD_VERSIONED_LIBRARY_PATH \
    OPENSSL_CONF OPENSSL_CONF_INCLUDE OPENSSL_ENGINES OPENSSL_MODULES &&
  exec /usr/bin/python3 -I -S -c '
import os
import pwd
import runpy
import sys

account_home = pwd.getpwuid(os.getuid()).pw_dir
os.environ["HOME"] = account_home
resolver = os.path.join(
    account_home,
    ".agents/skills/working-in-systalyze-worktrees/scripts/resolve_premerge_stack.py",
)
sys.argv[0] = resolver
runpy.run_path(resolver, run_name="__main__")
' --repo <checkout> --remote=<remote>
)
```

The launch block clears the listed injection-capable dynamic-loader and OpenSSL provider or engine configuration overrides before Python starts. Isolated Python derives the installed skill path from the account record rather than ambient `HOME`, restores that account home for the resolver, and rejects any listed override that remains. The resolver strips those overrides plus Git repository-layout and shallow-file overrides from every child command, then snapshots repository-local plus enabled per-worktree Git configuration. It verifies the selected remote's raw `remote.<name>.url` entries from that snapshot without applying `url.*.insteadOf` rewrites, and rejects effective HTTPS cookie persistence so reads cannot rewrite a configured cookie jar. It uses only its pinned Git and GitHub CLI installations. If either is unavailable, stop rather than substituting an executable found through `PATH`. For SSH remotes it also rejects caller-provided SSH arguments and configuration; use the trusted bare system SSH command or stop.

The resolver binds fresh aliases to immutable OIDs and one live PR head each, verifies their required common history, and reports current containment in both directions. A missing, stale, structurally inconsistent, concurrently moved, or unexpectedly rewritten alias is a stop condition. Report the observed refs and OIDs and coordinate with the owning stack task. Do not substitute ordinary PR branches, cached OIDs, remembered PR numbers, or a previously working local tree.

Product work descends from the resolved `product-base` OID. Before publication, test its unchanged product head through the resolved `qa-overlay` OID in a disposable local-only projection. Never publish the projection or its merge commit.

A workflow that publishes or restacks an accepted provider tip is incomplete until it advances its owned alias with an exact CAS lease and verifies the remote OID. A verified PR branch does not replace this alias-maintenance step.

## Select the target mode

Identify the actual checkout that owns the requested work before changing files. Determine whether it is:

- a product-development worktree;
- the checkout currently hosting a local cluster or runtime;
- a local-only scaffolding branch or stack; or
- a review/read-only target.

Inspect current status, branch, upstream, linked worktrees, submodules or nested repositories, and uncommitted or untracked state. Do not assume the invoking directory is the target.

## Preserve local state

Follow the current repo-local workflow for branch preparation, synchronization, setup scaffolding, submodule or gitlink preservation, generated files, and cluster handoff. Do not pull, switch, rebase, clean, or rewrite history when doing so would disturb local-only or unpushed work; surface the state first.

Treat shared development clusters and their resources as separate mutable state. Confirm the active context, ownership boundary, and target checkout's handoff procedure before mutation.

## Keep product history clean

Use local scaffolding only where current repository policy calls for it. Before committing or pushing product work, inspect the outgoing history and diff, remove local setup, grounding, runtime-policy, or cluster-host scaffolding from the pushed product lineage, and verify the resulting base and head reflect only the intended product work.

Run the verification required by current repo policy and the changed contract. Never substitute a remembered universal command list for current evidence.

After a provider stack merges, first verify its destination contains the aliased revision. Retiring the manifest and restoring ordinary discovery is a separate skill change; deleting a remote alias requires separate authorization.
