---
name: publishing-reviewable-prs
description: >-
  Use when and only when performing a live GitHub pull-request mutation through the owned guarded helpers: create a draft, store reviewer-facing text, or transition an existing draft to ready. Also use as the mutation stage of Graphite submission, fork sync, fixup publication, or explicit ship, publish, and yeet work only when the requested result includes one of those live PR mutations. Never use for generating or improving PR text in chat when GitHub must remain unchanged, or for read-only inspection, comments, checks, threads, labels, base changes, branch-only shipping, or merge-only work with unchanged PR text and readiness.
---

# Publishing Reviewable PRs

## Contract

This skill is the external-mutation orchestrator for PR creation, title/body publication, and draft-to-ready transitions. `checkpointing-and-publishing-git-work` owns task-only commits and pushes; Graphite may own stack metadata; `writing-reviewable-pr-descriptions` owns the complete title and body. It is a required composition sub-skill whenever this skill creates or changes PR text. For requested PR-text mutations, both skill descriptions intentionally match: this skill orchestrates and the writer composes because loading one skill does not load the other transitively.

GitHub exposes no conditional title/body/readiness mutation. These helpers use guarded best effort: exact preflight, one mutation, and a final re-read. They detect observed drift but cannot eliminate the final read/write race. Never claim atomicity, automatic rollback, or that a concurrent edit cannot be overwritten.

## Routing

- For a chat-only title/body draft, use `writing-reviewable-pr-descriptions` alone and stop before GitHub mutation.
- For PR creation or an actual title/body change, use this skill as the orchestrator and load `writing-reviewable-pr-descriptions` for composition.
- For a draft-to-ready-only transition, use this skill alone. If the stored body needs revision, stop unless the request also authorizes a text change.
- For read-only inspection, comments, checks, threads, or merge-only work with unchanged text and state, use neither skill.

## Workflow

1. Resolve the exact repository, PR, qualified head and owner, intended base, pushed base/head OIDs, and existing PR, if any.
2. Confirm the remote head contains exactly the commits the PR should describe.
3. Read repository instructions and templates.
4. For creation or a text update, use `writing-reviewable-pr-descriptions` to prepare the complete title/body from the exact pushed diff and resolved stack. For a draft-to-ready-only transition, validate the exact stored body and skip composition; do not prepare or publish replacement text.
5. For an existing PR, capture the helper's `preimage` JSON immediately before the owned text or ready operation. For creation, invoke the owned creator after the body is complete. Record an ambiguous-success warning without retrying. Stop on preflight drift, an unexpected final state, or any other ambiguity; never retry or roll back automatically.
6. Re-read and report repository, base/head names and OIDs, head owner, title, body, and draft/ready state.
7. Inspect live collapsed and expanded GitHub rendering whenever structured HTML, badges, disclosures, images, or media changed.

## Create

Put `__PUBLISHING_REVIEWABLE_PRS_PR_NUMBER__` everywhere the assigned number must appear in an absolute body-template file, then run:

```bash
python3 "$HOME/.agents/skills/publishing-reviewable-prs/scripts/create_reviewable_pr.py" \
  --repository OWNER/REPO \
  --base BASE --base-oid EXPECTED_BASE_OID \
  --head OWNER:BRANCH --head-owner OWNER --head-oid EXPECTED_HEAD_OID \
  --title "CONVENTIONAL TITLE" \
  --body-template /absolute/path/to/pr-body-template.md
```

The creator verifies no matching open PR exists and creates a draft whose neutral transport comment contains a unique transaction nonce. An ambiguous create is recovered only when exactly one open draft matches that nonce plus the exact repository, base/head names and OIDs, owner, title, and body. The creator then performs one canonical-body mutation and a final re-read. It always leaves the PR as a draft so live rendering can be inspected before review begins.

## Update Existing PR Text

Capture the exact stored preimage immediately before the call:

```bash
preimage_json="$(python3 "$HOME/.agents/skills/publishing-reviewable-prs/scripts/update_reviewable_pr.py" preimage \
  --repository OWNER/REPO --pr PR_NUMBER)"
```

The output contains `expected_title_sha256`, `expected_body_sha256`, and `expected_state`. Pass those values back without trimming, normalizing, or rehashing them:

```bash
python3 "$HOME/.agents/skills/publishing-reviewable-prs/scripts/update_reviewable_pr.py" text \
  --repository OWNER/REPO --pr PR_NUMBER \
  --base BASE --base-oid EXPECTED_BASE_OID \
  --head OWNER:BRANCH --head-owner OWNER --head-oid EXPECTED_HEAD_OID \
  --expected-title-sha256 "$(jq -r '.expected_title_sha256' <<<"$preimage_json")" \
  --expected-body-sha256 "$(jq -r '.expected_body_sha256' <<<"$preimage_json")" \
  --expected-state "$(jq -r '.expected_state' <<<"$preimage_json")" \
  --title "CONVENTIONAL TITLE" --body-file /absolute/path/to/pr-body.md
```

The helper accepts any exactly captured preimage body, including legacy, Graphite transport, sparse, or otherwise noncanonical text. It validates the desired body, snapshots those validated bytes to a private temporary file, and publishes that snapshot once. Preserve still-current custom content while constructing the desired canonical body.

## Mark Existing Draft Ready

After all readiness gates and required live-render inspection pass, refresh `preimage_json` with the `preimage` command above and run:

```bash
python3 "$HOME/.agents/skills/publishing-reviewable-prs/scripts/update_reviewable_pr.py" ready \
  --repository OWNER/REPO --pr PR_NUMBER \
  --base BASE --base-oid EXPECTED_BASE_OID \
  --head OWNER:BRANCH --head-owner OWNER --head-oid EXPECTED_HEAD_OID \
  --expected-title-sha256 "$(jq -r '.expected_title_sha256' <<<"$preimage_json")" \
  --expected-body-sha256 "$(jq -r '.expected_body_sha256' <<<"$preimage_json")" \
  --expected-state "$(jq -r '.expected_state' <<<"$preimage_json")"
```

The helper validates the current body, then reruns the exact identity, title/body digest, and draft-state preflight immediately before the mutation. Validation therefore cannot authorize readiness after intervening body drift.

## Mutation Outcomes

For both text and ready mutations, a command error followed by the exact intended final state is ambiguous success. The helper emits a `WARNING` on stderr, returns the verified stored state, and exits successfully. Record that warning and do not retry or roll back. Any other unexpected final state is an operator-inspection gate.

## Hard Rules

- Never use raw PR create, title/body edit, or ready commands or connectors.
- `--head` must use `OWNER:BRANCH`, and its owner must exactly match `--head-owner`.
- Resolve expected OIDs from live pushed state. Resolve title/body/state preimage values through the helper immediately before publication. Do not infer or compute either separately.
- On identity or OID drift, stop. Never refresh the expected OIDs and retry.
- Graphite transport text is the only other temporary-body exception. Replace it immediately through the existing-PR helper before handoff or review.
- Body files and templates must be existing absolute literal paths. Do not pass variables, `~`, relative paths, process substitution, stdin, or inline multiline bodies as paths/content.
- Never describe unpushed changes or discard still-current custom content.
- A successful `git push` does not prove `gh` can access the repository; Git and `gh` may use different credentials. On `Could not resolve to a Repository`, verify the active `gh` account and repository access before treating it as an outage.
- Stop when base, stack membership, preservation, or authority cannot be established safely.

## Completion Evidence

Report the PR URL, exact base/head and OIDs, stored title/body and digest verification, draft/ready state, checks used, and remaining operator action.

The personal PreToolUse guard is inactive until its exact definition is trusted. After applying a new or changed hook definition, have the operator open `/hooks`, review it, and mark it trusted. It is bounded defense in depth over recognized static command, script, API-client, and connector surfaces; it fails closed on recognized but unprovable routes, but does not interpret arbitrary opaque programs or runtime-generated behavior. The hard rules above remain primary. Do not claim even that bounded enforcement until `/hooks` shows this command enabled and trusted; this manual activation gate is intentional for the user-level hook.
