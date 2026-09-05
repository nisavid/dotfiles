# Temporary pre-merge stack surfaces

The manifest beside this file owns every temporary alias name and lineage rule. Read it at runtime; do not copy its refs or current OIDs into plans, durable policy, or product commits.

## Resolve a consumer snapshot

Run `/usr/bin/python3 -I -S "$HOME/.agents/skills/working-in-systalyze-worktrees/scripts/resolve_premerge_stack.py" --repo <checkout> --remote <remote>` before branch preparation and again immediately before product publication. The absolute interpreter and both isolation flags are part of the trust boundary; do not substitute an activated or PATH-resolved runtime. The resolver pins Git to `/usr/bin/git` and accepts GitHub CLI only from `/opt/homebrew/bin/gh`, `/usr/local/bin/gh`, or `/usr/bin/gh`; it never follows ambient `PATH` for either command. Git 2.29 or newer is required because preserving `FETCH_HEAD` depends on `git fetch --no-write-fetch-head`. SSH remotes require the trusted system executable at `/usr/bin/ssh`; a wrapper or lookalike executable is a stop condition.

The resolver:

- normalizes scheme-default ports, rejects credential-bearing remote URLs, verifies that the selected remote is one of the manifest's Systalyze endpoints, requires certificate verification for HTTPS, and binds every network read to that verified URL and SSH destination using a pinned OpenSSH variant with proxy routing and connection sharing disabled and strict host-key checking enforced;
- freezes the caller's authentication and HTTP transport settings, drops URL rewrite rules, ignores ambient Git executable and template overrides, and performs network Git reads from a private bare SHA-1 transport repository;
- queries GitHub with the active host token through an empty temporary CLI configuration, excluding configured Unix-socket routes;
- rejects grafted, shallow, or promisor repositories and remotes without the standard branch-cache refspec before trusting local graph state;
- snapshots each present cached alias before network access, rejects one whose object cannot peel to a commit, and advertises only locally present commits exposed as heads or bases by the bound provider PRs as fetch negotiation tips;
- runs Git and GitHub reads without credential prompts and with a finite per-command timeout that terminates the command's process group and bounds final pipe cleanup;
- queries both aliases without relying on local remote-tracking refs;
- fetches only the immutable objects, without moving refs, writing `FETCH_HEAD`, recursing into nested repositories, or starting automatic repository maintenance;
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
