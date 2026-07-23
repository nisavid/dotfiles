# Reviewer Body Contract

Read this reference while drafting the prose and review path around the required
first-viewport change navigation.

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

## Preservation

The live body is not disposable source. Carry forward still-current custom or
user-authored sections unless removal is explicit or current facts make them
stale: links, images, recordings, demo cards, captions, access details,
credentials intentionally placed in the PR, issue references, caveats, review
instructions, and rollout notes.

Before publication, compare baseline and proposal for unintended deletion.
After publication, re-read the stored body and repair any mismatch.

## Visuals

Use a visual only when relationships are materially harder to understand in
prose. Prefer the smallest focused interface, lifecycle, flow, or state diagram.
Split incompatible perspectives rather than producing one dense canvas. Use the
transitional atlas route in `SKILL.md` only after static views fail this test.

## Hard Rules And Acceptance

- Write the title and story from the exact pushed diff, not filenames alone.
- Do not publish machine-local paths, scratch artifacts, template instructions,
  placeholders, invented stack facts, or claims about unpushed changes.
- State observed verification and unresolved work precisely.
- The body must be proportional, scannable, preservation-safe, and faithful to
  the stored pushed state.
- Links must be useful; required disclosures must validate; stacked navigation
  must be complete and mark one current PR.
- GitHub must store and render the intended title/body before completion.
