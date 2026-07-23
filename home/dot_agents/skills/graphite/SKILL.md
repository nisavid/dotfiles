---
name: graphite
description: >-
  Use when working with Graphite `gt` stacks: creating or tracking stacked
  branches, navigating or reparenting a stack, restacking, submitting or
  updating stacked PRs, fixing Graphite metadata, or diagnosing stack ancestry
  and publication state.
---

# Graphite Stacks

## Boundary

Graphite owns stack topology, ancestry-aware branch operations, restacking, and
stack submission. `checkpointing-and-publishing-git-work` owns task-only commit
and push safety. `publishing-reviewable-prs` owns every created or updated PR,
and `writing-reviewable-pr-descriptions` owns its title and body.

Do not maintain a second PR-body format here. A successful `gt submit` is not a
completed publication until every affected PR has a verified canonical body.

## Establish Live State

Before mutation, inspect:

```bash
git status --short --branch
gt log short
gt trunk
```

Confirm the current branch, direct parent, complete stack order, remote tracking,
open PRs, and unrelated worktree changes. Do not infer parentage from branch or
PR title conventions when `gt` or Git can establish it.

## Common Operations

```bash
# Navigate
gt up
gt down
gt top
gt bottom
gt checkout <branch>

# Track an existing branch and choose its parent
gt track

# Create or amend the current stack branch
gt create <branch-name> -m "<conventional commit>"
gt modify -m "<conventional commit>"

# Recompute descendants after an ancestor changes
gt restack

# Reparent or rename
gt move --onto <new-parent>
gt rename <new-branch-name>

# Publish
gt submit --stack --draft --no-edit --no-ai --no-interactive
```

Use `gt` operations when they express the intended topology change. Use raw Git
only when Graphite cannot represent the operation or a documented recovery path
requires it, then restore and verify Graphite tracking before continuing.

## Create Or Extend A Stack

1. Start from the intended parent branch and verify it is tracked correctly.
2. Keep each branch cohesive and independently reviewable. Split on behavior,
   contract, deployment, or review-boundary changes—not arbitrary line counts.
3. Stage only task-owned paths. Create the branch/commit with a repository-valid
   name and Conventional Commit message when required.
4. Run branch-appropriate checks at each clean checkpoint.
5. Restack and verify the complete ancestry before submission.

When adopting branches created outside Graphite, check out each branch in
bottom-to-top order and run `gt track`, selecting the true parent. A worktree
branch can be tracked without moving or deleting the worktree.

## Submit Or Update PRs

1. Verify the stack is rooted on the intended trunk or external base.
2. Run required local checks and confirm each remote head will match local HEAD.
3. Prepare the canonical title/body for every affected branch before
   submission. Submit the exact intended branch or stack with `--draft`,
   `--no-edit`, `--no-ai`, and non-interactive flags. Never let Graphite open
   an editor or make an affected PR ready as part of transport.
4. Resolve the resulting PR number, base, head SHA, title, and body for every
   affected branch.
5. Use `publishing-reviewable-prs` immediately on every created or updated PR.
   Graphite transport text is the one permitted temporary body; replace it
   before handoff or review request. Rebuild Stack and Diff disclosures from
   each PR's exact pushed base/head; never reuse the top PR's totals for
   descendants.
6. Verify the stored and rendered bodies, full denominator, direct bases,
   additional dependencies, next/top navigation, and one current marker per PR.
7. Inspect every stored and rendered canonical body. Keep newly created or
   already-draft PRs draft during inspection. Preserve an existing ready PR's
   state unless the task explicitly changes it; do not toggle readiness merely
   for inspection. After all gates pass, use `publishing-reviewable-prs` and its
   guarded `ready` helper only for PRs that should transition from draft.

Graphite-generated text is temporary transport output, not an acceptable final
body. The canonical bodies must already be prepared, and replacement plus
stored/rendered verification is part of the same publication transaction. Never
use `gh pr create --fill` as a fallback.

## Restack And Recovery

- Before a restack, checkpoint task work and record the expected branch order.
- Resolve conflicts from the bottommost affected branch upward, rerunning
  targeted checks after each resolution.
- After raw `git rebase`, run the appropriate `gt track`, `gt modify`, or
  `gt restack` operation and verify `gt log short` before push.
- If interrupted, inspect Git's current operation and Graphite's view before
  continuing or aborting. Do not start a second rebase blindly.
- After a force-update, regenerate all affected PR navigation and diff data.

## Destructive Changes

Deleting a branch, discarding commits, moving a subtree, or rewriting a
published stack requires a verified impact inventory and the authority supplied
by the operator and repository policy. Preserve remote work with exact leases.
Never delete a harness-owned worktree as incidental Graphite cleanup.

## Completion

Report the final bottom-to-top stack, each branch and PR URL, base/head SHAs,
validation, submission result, canonical-body verification, and any unresolved
Graphite or reviewer-owned action.
