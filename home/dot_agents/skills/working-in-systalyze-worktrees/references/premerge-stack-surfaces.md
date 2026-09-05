# Temporary pre-merge stack surfaces

The manifest beside this file owns every temporary alias name and lineage rule. Read it at runtime; do not copy its refs or current OIDs into plans, durable policy, or product commits.

## Resolve a consumer snapshot

Run this block before branch preparation and again immediately before product publication:

```sh
(
  LD_AUDIT= \
  LD_LIBRARY_PATH=/dev/null \
  LD_PRELOAD= \
  DYLD_FALLBACK_FRAMEWORK_PATH=/dev/null \
  DYLD_FALLBACK_LIBRARY_PATH=/dev/null \
  DYLD_FRAMEWORK_PATH=/dev/null \
  DYLD_INSERT_LIBRARIES= \
  DYLD_LIBRARY_PATH=/dev/null \
  DYLD_ROOT_PATH=/dev/null \
  DYLD_SHARED_CACHE_DIR=/dev/null \
  DYLD_VERSIONED_FRAMEWORK_PATH=/dev/null \
  DYLD_VERSIONED_LIBRARY_PATH=/dev/null \
  OPENSSL_CONF=/dev/null \
  OPENSSL_CONF_INCLUDE=/dev/null \
  OPENSSL_ENGINES=/dev/null \
  OPENSSL_MODULES=/dev/null &&
  /usr/bin/python3 -I -S -c '
import os

startup_environment_variables = (
    "LD_AUDIT",
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "DYLD_FALLBACK_FRAMEWORK_PATH",
    "DYLD_FALLBACK_LIBRARY_PATH",
    "DYLD_FRAMEWORK_PATH",
    "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH",
    "DYLD_ROOT_PATH",
    "DYLD_SHARED_CACHE_DIR",
    "DYLD_VERSIONED_FRAMEWORK_PATH",
    "DYLD_VERSIONED_LIBRARY_PATH",
    "OPENSSL_CONF",
    "OPENSSL_CONF_INCLUDE",
    "OPENSSL_ENGINES",
    "OPENSSL_MODULES",
)
for variable in startup_environment_variables:
    os.environ.pop(variable, None)

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

The guarded assignment-only command runs in a subshell, gives every inherited listed dynamic-loader and OpenSSL provider or engine configuration override an inert value, and prevents the first external process from starting if any assignment fails. Isolated Python removes the variables before importing anything beyond `os`. Because the launcher does not call shell `unset` or `exec`, imported functions with those names cannot intercept cleanup or dispatch. Python then derives the installed skill path from the account record rather than ambient `HOME`, restores that account home for the resolver, and rejects any listed override that remains. The resolver strips those overrides from every child command. The absolute interpreter and both isolation flags are part of the trust boundary; do not substitute an activated or PATH-resolved runtime. The resolver pins Git to `/usr/bin/git` and accepts GitHub CLI only from `/opt/homebrew/bin/gh`, `/usr/local/bin/gh`, or `/usr/bin/gh`; it never follows ambient `PATH` for either command. Git 2.29 or newer and a SHA-1 checkout object format are required; preserving `FETCH_HEAD` depends on `git fetch --no-write-fetch-head`, and the temporary aliases are SHA-1 OIDs. SSH remotes accept only the bare trusted system executable at `/usr/bin/ssh`; the resolver supplies `/dev/null` as its user configuration and rejects caller-provided wrappers, arguments, or configuration files.

The resolver:

- normalizes scheme-default ports, rejects credential-bearing remote URLs, verifies the selected remote's raw repository/worktree URL entries against the manifest's Systalyze endpoints without applying `url.*.insteadOf` rewrites, requires certificate verification and rejects cookie persistence for HTTPS, and binds every network read to that verified URL and SSH destination using a pinned OpenSSH variant with proxy routing and connection sharing disabled and strict host-key checking enforced;
- snapshots repository-local and enabled per-worktree Git configuration, discards checkout-provided Git credential configuration and authorization headers, authenticates HTTPS Git reads with the active host token only for the verified URL while disabling redirects, credential-bearing traces, and TLS key logging, freezes the caller's remaining HTTP transport settings, drops URL rewrite rules, ignores ambient Git executable, template, repository-layout, shallow-file, and OpenSSH security-key helper and provider overrides, and performs network Git reads from a private bare SHA-1 transport repository;
- queries GitHub with the active host token through an empty temporary CLI configuration, excluding configured Unix-socket routes;
- rejects alternate object databases, grafted, shallow, promisor, or non-SHA-1 repositories and remotes without the standard branch-cache refspec before trusting local state;
- snapshots each present cached alias before network access and rejects one whose checkout object cannot peel to a commit;
- runs Git and GitHub reads without credential prompts and with a finite per-command timeout that terminates the command's process group even when its leader exits before a pipe-holding descendant, and bounds final pipe cleanup;
- queries both aliases without relying on local remote-tracking refs;
- fetches the immutable commit graphs into the private transport repository without advertising checkout objects, moving refs, writing the checkout object database or `FETCH_HEAD`, recursing into nested repositories, or starting automatic repository maintenance;
- requires each OID to equal exactly one current open head in the Systalyze repository;
- verifies the manifest's common-history rule, reports both containment directions, and checks any non-fast-forward change from a cached alias; and
- queries both PR identities and the aliases again so a concurrent move or PR replacement fails the run.

Keep the JSON result with the task evidence. Use its OIDs, not its PR numbers or branch names, for preparation and testing. If it fails, preserve the checkout and report the error code plus the observed remote state to the owner. Command-level failures carry only a return code and output digests because raw Git or credential-helper output may contain sensitive material. Reconstructing the stack from ordinary PR topology is not a fallback.

## Keep product work and QA separate

Let `G` be the resolved `product-base` OID, `P` the product head descended from `G`, and `D` the resolved `qa-overlay` OID. Require `G` to be an ancestor of `P`. Inspect the resolver's relationship result for `G` and `D`; do not assume either stack tip contains the other.

The reviewable branch is `G..P`. Build QA in a directly task-created disposable worktree detached at `P`, then create a local merge commit whose first parent is `P` and second parent is `D`. Run only the current checkout's required, task-authorized verification there. Shared cluster or host mutation still needs its own authority.

After QA, prove the reviewable product ref still equals `P` and contains no merge or setup commits from the projection. Never push the detached projection. Preserve or remove its exact worktree through `checkpointing-and-publishing-git-work` according to its recorded provenance.

If either alias changes, discard the old QA result. Re-resolve both surfaces, reconcile the product branch through its owning stack workflow when needed, and create a fresh projection.

## Advance a provider alias

This procedure applies to the owner of the stack whose accepted tip changed:

For the `qa-overlay` surface, only the owner of the current accepted stack top may advance the alias. After a lower layer changes, cascade it through every published descendant and verify the resulting top before updating the alias. A verified lower-layer publication alone does not authorize the alias move.

1. Finish the provider branch's own publication and verification first. Establish the immutable new tip and its live PR identity.
2. Read the destination ref from the manifest. Query its current remote OID and preserve that OID as the expected target. If the alias is missing, stop and report it; only the one-time bootstrap that created these refs may create an alias. The alias is a fetch-only coordination channel for consumers; do not open a PR from it.
3. Use `checkpointing-and-publishing-git-work` to plan this alias as a separate destination. Classify every outgoing, adopted, or target-only commit exactly; a restack does not waive removal authorization.
4. Review the `ready` plan, rerun it immediately, require an exact match, and execute only its immutable source refspec and exact existing-OID lease.
5. Require the planner's terminal `verified` result and an independent remote-ref read showing the new OID. Then notify the other stack owner and active consumers.

Advance only the alias for the stack you own. If both stacks moved, their owners complete and verify separate updates before consumers resume.

## Retire the temporary contract

After a provider stack merges, verify the live destination contains its aliased OID. Changing this skill and manifest back to ordinary repository discovery is a separate reviewed change. Remote-ref deletion is destructive and requires a separately authorized workflow; leaving an alias present is not deletion authority.
