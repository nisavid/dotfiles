# Reviewer Body Contract

Read this reference while drafting the prose and review path around the required
first-viewport change navigation.

## Reviewer Decision Path

Write for an unfamiliar, skeptical, time-constrained peer deciding whether the
exact pushed change deserves approval. Lead with the resulting behavior and why
it matters, not the author's effort or implementation chronology. Answer each
concern where it naturally arises:

- what concrete problem it solves, why the change is needed, and what outcome
  it creates;
- what is in scope, what remains unchanged, and what belongs to later work;
- where review should start and whether any generated or mechanical surface can
  be de-emphasized based on regeneration or verification evidence;
- which contracts, risks, or non-obvious choices deserve scrutiny and why the
  resulting shape is maintainable; and
- which observed evidence supports the claims and which work remains open.

Do not turn these questions into a mandatory section inventory. A tiny change
may answer them in one sentence; a large change may need a review map, explicit
boundaries, or a temporal comparison. Use warm, direct peer-engineer language.
Prefer falsifiable technical claims to superlatives, reassurance, salesmanship,
or condescension. Do not generalize away materially distinct affected contexts,
callers, or environments supplied by verified source when they establish the
need or scope.

Write the title as the smallest concrete line that names the primary
reviewer-visible behavior or outcome and follows the repository's title
convention. Preserve a required stack index or still-current scope prefix. Do not
promote author effort, urgency, implementation inventory, or impact beyond the
exact pushed diff.

For a large or stacked change, turn the review entry point into an ordered path
through authored responsibility boundaries. Put generated output after the
contract or generator input it derives from and name the evidence that makes
de-emphasis safe. For a stack, identify the immediate prerequisite or prior
state, this PR's exact transition, and the later members without omitting the
before-state that makes the current slice intelligible. A current-path
description plus future members is incomplete without an explicit prerequisite
or Before state.

Treat this explanation as a gate on readiness and approval claims. When an
honest account exposes an unsupported abstraction, excessive scope or
permissions, an unresolved authority path, or missing evidence required to
support a material approval claim, do not market around the weakness or present
the PR as approval-ready. For a draft or
prose-only request, state the blocker or open decision and the evidence or
design change needed; do not mutate implementation without task authority. When
the task does authorize implementation, return to the change and narrow,
redesign, or validate it before making the approval case. When several
weaknesses are visible, use `grilling` to select the one consequential product,
scope, or authority decision that controls the next step; ask that decision and
stop instead of bundling a redesign checklist. Other gaps may explain why that
decision matters, but do not turn them into simultaneous questions.

## Proportional Shape

- **Tiny:** navigation, one short paragraph or 1-3 bullets, and verification.
- **Straightforward:** `Summary`, `Changes`, and `Verification`; add blockers or
  follow-up only when real.
- **Large, stacked, cross-cutting, or readiness-ambiguous:** add only the
  reviewer aids justified by the change: review path, contracts, dependencies,
  risks, rollout, blockers, or follow-up.

Prefer bullets and short sections. Group changes by interface or responsibility
boundary, not package inventory or commit order. Use concrete headings such as
`API Contracts` or `Worker Lifecycle`.

## Scope And Classification

Use the exact pushed PR base/head. Refresh remote refs before local merge-base
work. Establish the intended base explicitly when no PR exists.

Classify changed lines in this order:

1. **IMPL:** non-test source/configuration affecting runtime, build, deployment,
   migration, tooling, or CI.
2. **TEST:** tests, fixtures, helpers, test-only setup/configuration, and
   test-only dependency changes.
3. **DOC:** documentation and prose-only examples.
4. **GEN:** lockfiles and generated artifacts/data.
5. **OTHER:** assets, manifests, or metadata not covered above.

Inspect mixed files. Split lines only when the patch makes the split auditable;
otherwise use `OTHER`. Pure moves/copies are operations, not changed lines.
Edited moves/copies count only modified lines. Binary files count as operations.

## Links And Evidence

- Link every actionable reviewer reference: changed files, PRs, issues, unusual
  CI, docs, media, dashboards, and specs.
- Changed files should open the PR's Files changed anchor. Supporting unchanged
  files may use immutable blob/tree links.
- Summarize routine green CI. Link jobs only when they explain a failure,
  pending gate, flake, or unusual validation.
- Write verification as command plus observed result; include a working
  directory when it was not run at repository root.
- Separate PR-readiness blockers from follow-up that belongs outside this PR.

## Manual Operational Testing

Include a manual plan only when interaction or operational behavior adds useful
confidence beyond automated checks. Teach the affected surface without turning
the author's full qualification matrix into reviewer homework:

1. State the operational surface, prerequisites, safe execution context, and
   working directory when it is not the repository root.
2. Put the shortest coherent scenario that directly exercises the PR's defining
   behavior or risk first. Give runnable commands, intended results, non-obvious
   outcomes, and the quality or alignment a human should judge. Do not compress
   that core into an evidence-only bullet: keep its runnable commands and
   distinguish intended results from observed results. Depending on the primary
   claim, this core may be a successful action, a rejection or failure, a
   recovery, or a multi-step transaction. Treat only orthogonal coverage as
   later scenarios. When a claim spans surfaces or steps, the core must exercise
   the comparison or transaction that establishes it, not only its first
   successful action. When concurrency or cross-instance comparison is the
   reason for the change, one successful instance cannot establish the core
   claim. A separately runnable step is not optional when it supplies necessary
   evidence: keep it in the core or classify it `Required` and state the gate.
   Once that minimum evidence is present, do not
   widen the core merely to absorb orthogonal failure injection, recovery,
   destructive reset, or environment variants. Keep cleanup for state or live
   processes created by the core inside the core path. If the source evidence
   does not establish that cleanup, state the gap instead of borrowing cleanup
   from another scenario. State a readiness effect only when verified source
   establishes one; otherwise do not turn the cleanup gap into a readiness
   gate.
3. Separate every scenario after the shortest core path. Prefix it `Optional`
   unless the source evidence explicitly makes it a readiness gate; then prefix
   it `Required` and state the gate. Begin the scenario's heading or bullet with
   that literal classification; words such as `additional`, `later`, or
   `extended` do not classify reviewer burden. Treat each distinct non-core
   manual command sequence or observed outcome as a scenario even when it is
   condensed under `Verification`; apply the same literal classification and
   cleanup rules to it. Mark slow, destructive,
   credentialed, shared-environment, or host-mutating scenarios explicitly. Do
   not infer a readiness gate merely because a scenario exercises changed
   code, a named risk, or stronger coverage; the source must establish the gate.
   For state-mutating scenarios, state the blast radius and narrow cleanup they
   require. Scenario optionality never makes cleanup optional: if an executed
   scenario created state or a live process, its cleanup is required and must be
   reported. End each executed scenario with `Cleanup:` or `Cleanup gap:`; one
   later shared cleanup may cover several scenarios only when each scenario
   names that shared cleanup.
4. Distinguish author-run evidence at the exact pushed head from optional,
   manual-only, or unrun scenarios. Do not imply that reviewers must repeat
   evidence already gathered unless independent reproduction is a real gate.

Before publication, autonomously run and verify every safe, authorized command
the plan relies on. Run destructive or host-mutating steps only with authority.
When a step cannot or should not run, mark it unrun and say why; never present a
proposed command as observed evidence. Keep checklist state accurate as evidence
changes.

## Preservation

The live body is not disposable source. Carry forward still-current custom or
user-authored sections unless removal is explicit or current facts make them
stale: links, images, recordings, demo cards, captions, access details,
issue references, caveats, review instructions, and rollout notes. Never carry
forward credentials or other secrets, even when intentionally authored in the
PR. Redact the published value and require revocation or rotation instead of
republishing it; preserve only non-secret access details that remain current.

Before publication, compare baseline and proposal for unintended deletion.
After publication, re-read the stored body and repair any mismatch.

## Temporal And Visual Explanations

Use prose for one simple relationship. Use a compact table or explicit
Before / This PR / Later explanation when temporal state, ownership, or stack
position is the source of confusion. Use a visual only when relationships are
materially harder to understand in prose and the visual shortens the review
path.

Prefer the smallest focused interface, lifecycle, flow, or state diagram that
answers one review question. Preserve meaningful module and ownership
boundaries, branch labels, and distinctions between current scope, successful
results, future work, and failures. Prefer Mermaid when it can express the view
clearly and durably. Use a custom or adaptive SVG only when necessary semantics,
theming, or legibility cannot survive Mermaid's constraints. Pair semantic
color with text or structure; never use color or decoration as the only
meaning. Before keeping prose, a table, or a visual that describes a flow,
verify every node and edge against the current contract. Do not infer a
connection merely because both components changed. Show legacy and future paths
separately and never imply planned work is already current. Omit unchanged
platform topology that does not help review this diff. Split incompatible
perspectives rather than producing one dense canvas. Use the guided atlas route
in `SKILL.md` only after static views fail this test.

## Hard Rules And Acceptance

- Write the title and story from the exact pushed diff, not filenames alone.
- Do not publish machine-local paths, scratch artifacts, template instructions,
  placeholders, invented stack facts, or claims about unpushed changes.
- Do not infer an issue-closing relationship from a PR number, branch name, or
  nearby identifier. Preserve only issue links and closure semantics supplied
  by verified source or the existing body.
- State observed verification and unresolved work precisely.
- The body must be proportional, scannable, preservation-safe, and faithful to
  the stored pushed state.
- The reviewer must be able to identify why the change is needed, its current
  boundaries, the efficient review path, the supporting evidence, and any open
  work without relying on marketing claims.
- Manual steps must identify the core confidence path, expected results, and
  actual evidence status. When optional variants or hazardous, host-mutating,
  or other state-mutating work exists, separate it, begin each non-core scenario
  with literal `Optional` or `Required`, and give every executed scenario an
  explicit `Cleanup:` or `Cleanup gap:` disposition.
- A stacked body must state the prerequisite or Before state, this PR's
  transition, and later members; current paths plus later work are incomplete.
- Links must be useful; required disclosures must validate; stacked navigation
  must be complete and mark one current PR.
- GitHub must store and render the intended title/body before completion.
