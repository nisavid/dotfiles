---
name: publishing-reviewable-prs
description: Use when creating or changing a GitHub PR, including drafts, title/body or draft/ready-state edits, `gh pr create/edit/ready`, Graphite submission, fork-sync or fixup PRs, and requests to yeet, ship, publish, or prepare a PR. Do not use for read-only inspection, comments, checks, threads, or merge-only work with unchanged PR text and state.
---

# Publishing Reviewable PRs

## Contract

This skill owns PR creation plus title/body and ready-state publication.
`checkpointing-and-publishing-git-work` owns task-only commits and pushes;
Graphite may own stack metadata; `writing-reviewable-pr-descriptions` owns the
complete title and body.

GitHub exposes no conditional title/body/readiness mutation. These helpers use
guarded best effort: exact preflight, one mutation, and a final re-read. They
detect observed drift but cannot eliminate the final read/write race. Never
claim atomicity, automatic rollback, or that a concurrent edit cannot be
overwritten.

## Workflow

1. Resolve the exact repository, PR, qualified head and owner, intended base,
   pushed base/head OIDs, and existing PR, if any.
2. Confirm the remote head contains exactly the commits the PR should describe.
3. Read repository instructions and templates. For an existing PR, capture the
   live title/body immediately before mutation and retain that preimage locally.
4. Use `writing-reviewable-pr-descriptions` to prepare the complete title/body
   from the exact pushed diff and resolved stack.
5. Use the owned create or existing-PR helper below. Stop on preflight drift,
   unexpected final state, or ambiguity; never retry or roll back automatically.
6. Re-read and report repository, base/head names and OIDs, head owner, title,
   body, and draft/ready state.
7. Inspect live collapsed and expanded GitHub rendering whenever structured
   HTML, badges, disclosures, images, or media changed.

## Create

Put `__PUBLISHING_REVIEWABLE_PRS_PR_NUMBER__` everywhere the assigned number
must appear in an absolute body-template file, then run:

```bash
python3 "$HOME/.agents/skills/publishing-reviewable-prs/scripts/create_reviewable_pr.py" \
  --repository OWNER/REPO \
  --base BASE --base-oid EXPECTED_BASE_OID \
  --head OWNER:BRANCH --head-owner OWNER --head-oid EXPECTED_HEAD_OID \
  --title "CONVENTIONAL TITLE" \
  --body-template /absolute/path/to/pr-body-template.md
```

The creator verifies no matching open PR exists and creates a draft whose
neutral transport comment contains a unique transaction nonce. An ambiguous
create is recovered only when exactly one open draft matches that nonce plus
the exact repository, base/head names and OIDs, owner, title, and body. The
creator then performs one canonical-body mutation and a final re-read. It always
leaves the PR as a draft so live rendering can be inspected before review begins.

## Update Existing PR Text

Capture SHA-256 digests of the exact live title and body immediately before the
call. Use `draft` or `ready` for the observed preimage state:

```bash
python3 "$HOME/.agents/skills/publishing-reviewable-prs/scripts/update_reviewable_pr.py" text \
  --repository OWNER/REPO --pr PR_NUMBER \
  --base BASE --base-oid EXPECTED_BASE_OID \
  --head OWNER:BRANCH --head-owner OWNER --head-oid EXPECTED_HEAD_OID \
  --expected-title-sha256 EXPECTED_TITLE_SHA256 \
  --expected-body-sha256 EXPECTED_BODY_SHA256 --expected-state draft \
  --title "CONVENTIONAL TITLE" --body-file /absolute/path/to/pr-body.md
```

The helper accepts any exactly captured preimage body, including legacy,
Graphite transport, sparse, or otherwise noncanonical text. It validates the
desired body, snapshots those validated bytes to a private temporary file, and
publishes that snapshot once. Preserve still-current custom content while
constructing the desired canonical body.

## Mark Existing Draft Ready

After all readiness gates and required live-render inspection pass, refresh
the exact preimage and run:

```bash
python3 "$HOME/.agents/skills/publishing-reviewable-prs/scripts/update_reviewable_pr.py" ready \
  --repository OWNER/REPO --pr PR_NUMBER \
  --base BASE --base-oid EXPECTED_BASE_OID \
  --head OWNER:BRANCH --head-owner OWNER --head-oid EXPECTED_HEAD_OID \
  --expected-title-sha256 EXPECTED_TITLE_SHA256 \
  --expected-body-sha256 EXPECTED_BODY_SHA256
```

A command error followed by the exact intended final state is ambiguous
success. Any other unexpected final state is an operator-inspection gate.
The helper validates the current body, then reruns the exact identity, title/body digest, and draft-state preflight immediately before the mutation.
Validation therefore cannot authorize readiness after intervening body drift.

## Hard Rules

- Never use raw PR create, title/body edit, or ready commands or connectors.
- `--head` must use `OWNER:BRANCH`, and its owner must exactly match
  `--head-owner`.
- Resolve expected OIDs and preimage digests from live pushed/stored state
  immediately before publication. Do not infer them.
- Graphite transport text is the only other temporary-body exception. Replace
  it immediately through the existing-PR helper before handoff or review.
- Body files and templates must be existing absolute literal paths. Do not pass
  variables, `~`, relative paths, process substitution, stdin, or inline
  multiline bodies as paths/content.
- Never describe unpushed changes or discard still-current custom content.
- Stop when base, stack membership, preservation, or authority cannot be
  established safely.

## Completion Evidence

Report the PR URL, exact base/head and OIDs, stored title/body and digest
verification, draft/ready state, checks used, and remaining operator action.

The personal PreToolUse guard is inactive until its exact definition is trusted.
After applying a new or changed hook definition, have the operator open `/hooks`,
review it, and mark it trusted. It is bounded defense in depth over recognized
static command, script, API-client, and connector surfaces; it fails closed on
recognized but unprovable routes, but does not interpret arbitrary opaque
programs or runtime-generated behavior. The hard rules above remain primary.
Do not claim even that bounded enforcement until `/hooks` shows this command
enabled and trusted; this manual activation gate is intentional for the
user-level hook.
