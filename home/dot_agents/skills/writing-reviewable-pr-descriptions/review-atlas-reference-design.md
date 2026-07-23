# Transitional Review Atlas Reference Design

> This is personal review-tooling material, not application-repository documentation. It defines the current stopgap used by `writing-reviewable-pr-descriptions` and preserves source and design material for a forthcoming dedicated personal project. The Systalyze batch-math stack is the first worked application, not the ownership boundary.

## Contents

- [Purpose](#summary): summary, context, goals, non-goals, and design principles
- [Model](#architecture): architecture, semantic manifest, and adaptive lenses
- [Review experience](#reviewer-interaction-model): interaction model and current stack map
- [Publication](#pr-body-delivery): PR-body delivery, safety, validation, and testing
- [Delivery](#reference-implementation-boundaries): boundaries, sequence, success criteria, and deferred direction

## Summary

The batch-math PR stack needs a review aid that explains both the architecture and the sequence of changes without forcing every concern into one dense diagram. The reference implementation will replace the current collection of isolated static diagrams with a manifest-driven review atlas: one canonical semantic model rendered as a guided set of related architectural lenses, with cumulative Graphite PR overlays and exact routes back to GitHub, Graphite, files, symbols, tests, and evidence.

This reference applies only after visual escalation selects the atlas because
normal Stack, Diff, and prose navigation is insufficient. Without that
selection, the ordinary review path remains authoritative and no atlas preview
is required. When the atlas is selected, each affected PR body contains a
compact inline orientation image. Selecting that image opens the atlas at the
relevant lens, PR, and changed seam rather than at a generic landing page.
GitHub and Graphite remain the systems of record for code, comments, checks,
approvals, and stack ancestry. The atlas guides review; it does not conduct or
record review.

This work is a repository-agnostic personal reference implementation, first applied to the current 11-PR Systalyze batch-math stack. It is not application product code or the proposed reusable personal review product. A PAT-backed, live review application merits a separate `nisavid` project, but creating that project requires a separate explicit decision.

## Context

The current diagrams establish useful visual regions and have a coherent visual language, but they leave three review problems unresolved:

1. A focused diagram does not sufficiently explain where it sits in the full framework.
2. A reviewer cannot reliably tell which PR, file, symbol, or diff owns a node or seam.
3. Several diagrams contain enough simultaneous arcs and labels that tracing a specific review question is harder than it should be.

Protected hosting also prevents the current SVGs from rendering inline in GitHub PR bodies because GitHub's image proxy cannot authenticate to the protected site. Density is a secondary problem at PR-body width. The atlas therefore needs two delivery surfaces: private GitHub-hosted inline previews for orientation and a protected interactive atlas for deeper exploration.

## Goals

- Give reviewers an architecture-first mental model of the mathematical framework and its batch-inference application.
- Explain what exists before a selected PR, what that PR changes, what the cumulative stack produces, and what remains outside the stack.
- Let reviewers move from an architectural claim to the narrowest relevant diff, file, symbol, test, or evidence artifact.
- Preserve nearby context while allowing a selected subsystem, node, or seam to expand into a legible focused view.
- Generate every published view from one semantic manifest with deterministic rendering and validation.
- Let a capable agent produce the atlas autonomously in the normal case and request author input only for materially consequential ambiguity.
- Keep the reference implementation narrow enough to improve the current stack without committing to a general review product.

## Non-goals

- Embedding complete diffs, comments, approvals, checks, or review actions in the atlas.
- Making the atlas a system of record.
- Polling GitHub or Graphite from the published static site.
- Shipping a PAT, GitHub credential, raw source or diff content, private API responses, unnecessary repository data, or live review metadata in browser assets.
- Building a reusable cross-repository web application in this round.
- Creating the separate personal `nisavid` project without another explicit approval.
- Hard-coding seven lenses as a universal limit or requiring one diagram per PR.

## Design principles

### Architecture first, chronology second

The canonical model describes the system's entities, seams, flows, and regions independently of PRs. Graphite chronology is an overlay on that model. A component does not change identity merely because a later PR changes it.

### Guided exploration with bounded freedom

The atlas offers curated lenses framed as concrete review questions. Reviewers may pan, zoom, select nodes or seams, and follow related lenses, but they do not begin from an undifferentiated infinite canvas.

### Progressive disclosure

The overview shows the major regions and primary flow. A focused lens shows the selected concern and muted one-hop context. Selecting a seam expands its constituent relationships into separated lanes. Files, symbols, diffs, tests, and risks appear in the inspector rather than crowding the canvas.

### Claims carry provenance

The atlas distinguishes observed, declared, inferred, and unknown or conflicted claims. Inference can help build a useful model, but inference alone cannot assert authoritative future scope, ownership, guarantees, or promotion status.

### Source systems remain authoritative

The repository owns code and tests. Graphite owns stack ancestry and navigation. GitHub owns PRs, diffs, comments, checks, approvals, and attachments. The atlas links to those systems and can be regenerated from them, but it does not replace them.

## Architecture

The generation pipeline has four stages:

1. **Discoverable inputs:** repository and Git graph, Graphite stack metadata, GitHub PR metadata, and material author intent.
2. **Agentic synthesis:** repository and review analysis produces a canonical semantic review model, then validates claims, provenance, ambiguity, and required review contracts.
3. **Deterministic generation:** a bounded view grammar derives lens specifications, renders the atlas and PR previews, and validates the outputs.
4. **Review delivery:** a protected static atlas provides exploration, while private GitHub attachments provide inline PR entry points. GitHub, Graphite, and the repository remain the systems of record.

The model performs architectural synthesis. Deterministic tooling owns layout, rendering, validation, repeatability, and publication inputs. Published views cannot contain hand-authored markup or geometry that bypasses the manifest.

## Semantic manifest

The durable input to the renderer is a typed semantic manifest. Its conceptual top-level structure is:

```text
ReviewAtlasManifest
├── sourceSnapshot
│   ├── repository
│   ├── baseCommit
│   ├── stackBranchesAndCommits
│   ├── pullRequests
│   └── authorDeclarations
├── graph
│   ├── entities
│   ├── seams
│   ├── flows
│   └── regions
├── baseState
├── changeSets
├── claims
├── reviewContracts
├── reviewQuestions
├── personaPresets
├── deliveryEntries
└── validatedOverrides
```

All graph objects have stable semantic IDs. Rendered IDs, CSS selectors, PR numbers, file paths, and display labels are references to those semantic objects rather than their identities.

`baseState` lists the graph objects and claims active at `baseCommit`. The canonical graph may define objects introduced later in the stack, but those objects are absent from `baseState` until an `Add` operation activates them. Unchanged pre-stack context is present in `baseState` even when no PR change set targets it.

`authorDeclarations` captures every consequential answer obtained during grilling as a typed, attributable source. Each declaration records the author identity, recorded time, exact answer, affected semantic IDs or claims, durable source location when one exists, and a content digest. The generated atlas never depends on an ephemeral conversation answer that is absent from the manifest or another durable reviewable artifact.

### Temporal change model

Each PR has a typed change set ordered by Graphite ancestry. A change targets a stable semantic ID or claim and uses one of four operations:

- **Add:** introduce an object or claim that did not exist in the prior cumulative state.
- **Modify:** change specified fields while retaining semantic identity.
- **Remove:** end an object's or claim's lifetime in the stack model.
- **Reclassify:** change claim provenance, architectural role, or temporal status without pretending that the underlying subject is a new object.

Each operation records its before and after state, owning PR, required predecessor objects or claims, and any cross-PR dependency. The state builder validates `baseState` against `baseCommit`, begins from that state, folds change sets in Graphite order, and rejects adding an active ID, changing or removing an inactive ID, an incorrect before state, or an unsatisfied dependency. This model derives the Before, This PR, and Stack Outcome views; review-contract prose does not reconstruct temporal state.

### Published payload boundary

Browser assets may contain semantic IDs, human-written architectural claims, display labels, PR, branch, and commit identifiers, repo-relative file paths, symbol names, test and evidence labels, and non-secret deep links needed for review routing. A deep link may rely on the destination's access control, but it must not embed a bearer token, signed credential, or other authentication material. Browser assets may not contain raw source files, diff bodies, comments, private API payloads, credentials, or unrelated repository metadata. Generation retains richer source evidence locally and publishes only the minimum review-facing representation.

### Review contracts

Every stack-changed entity rendered as a node, and every stack-changed seam, must have a complete review contract:

- the architectural claim and its practical significance;
- owning PR and stack dependencies;
- files and symbols that implement the change;
- focused GitHub diff and Graphite links;
- tests, validation, or evidence supporting the claim;
- temporal status before the PR, in the selected PR, and in the stack outcome; and
- risks, assumptions, ambiguities, and known conflicts.

Changed flows, regions, and claims must retain ownership, provenance, and source routing, but may be covered by the contract of the node or seam they explain. They require a separate review contract only when the renderer promotes them to independently selectable review subjects.

An incomplete required contract blocks the affected lens and PR preview. It does not silently produce a partial authoritative view.

### Claim provenance

Each material claim is classified as one of:

- **Observed:** directly supported by code, tests, Git history, or review metadata.
- **Declared:** explicitly supplied by the author or durable product or design documentation.
- **Inferred:** synthesized from available evidence and marked as an inference.
- **Unknown or conflicted:** evidence is absent or mutually inconsistent.

Each claim records the source references that justify its classification. Unknown or conflicted claims remain visible where useful, with their affected scope clearly marked.

### Ambiguity handling

The generator asks the author a question only when the answer would materially change architecture, ownership, review routing, or a published claim. It does not ask about diagram mechanics, layout preferences, colors, or routine decomposition.

Ambiguity blocks only dependent outputs. Ambiguity in a local seam blocks the relevant child lens and PR preview. Ambiguity in the system's primary regions or flow blocks the required overview.

## Adaptive lens decomposition

Every atlas has one required architecture overview. The agent records semantic review questions, allowed focus objects, required context anchors, and optional view-grammar hints in the manifest. Deterministic decomposition turns those inputs into concrete lens specifications and layout. The agent does not author rendered lens geometry, and the renderer does not invent architectural questions or semantic focus.

Additional lenses are derived from the review questions and graph density, not from a fixed count.

The decomposition procedure is:

1. Identify the primary architectural regions and end-to-end flow.
2. Identify the concrete questions a reviewer must answer to evaluate the changes.
3. Select the smallest appropriate view grammar for each question, such as lifecycle, boundary, comparison, state, identity, evidence, or flow.
4. Include the focused objects and muted one-hop context needed to locate them in the overview.
5. Split a lens when routes become difficult to trace, labels collide, unrelated perspectives compete, or the inspector would need to compensate for an overloaded canvas.
6. Validate that every changed node and seam appears in at least one reviewable lens, changed flows and regions remain reachable through their owning contracts, and every lens states the question it answers.

There is no universal maximum depth or lens count. The current stack resolves to seven lenses; this is an outcome of its semantics and density, not a framework constraint.

Layout overrides are bounded, schema-validated adjustments such as ordering hints, lane preferences, or approved label positions. They cannot add semantic objects, suppress required context, or introduce a hand-authored published view.

## Reviewer interaction model

### Workspace

The reviewer workspace has five persistent parts:

1. **Header:** atlas name, active lens, persona preset, and selected PR position.
2. **Guided lens navigation:** curated lenses and a persistent minimap showing the active region in the full architecture.
3. **Canvas:** the current review question, focused graph objects, and muted one-hop context.
4. **Review-contract inspector:** claim, provenance, PR ownership, source routes, evidence, temporal state, risks, and assumptions for the selected object.
5. **Stack scrubber:** base state, selected PR, and cumulative stack outcome.

### Layered focus

At rest, a lens shows the major flow and only the relationships needed for its question. Selecting a node or seam:

- gives the selection visual priority;
- expands a composite seam into separated lanes when necessary;
- keeps one-hop context visible but muted;
- collapses unrelated secondary relationships behind an explicit count; and
- updates the inspector without changing the selected PR or lens.

This treatment directly addresses dense, closely spaced arcs while preserving the reviewer's location in the larger framework.

### Persona presets

All personas use the same canonical model. Presets change initial emphasis and explanatory depth, not facts:

- **Reviewer:** starts with changed contracts, risks, verification, and focused diff routes.
- **Author:** starts with ownership, missing contracts, ambiguity, and generation diagnostics.
- **Explorer:** starts with the overview and adds more explanatory context and related-lens routes.

### Temporal model

The stack scrubber uses cumulative Graphite states. Selecting a PR exposes:

- **Before:** the cumulative state immediately before the PR;
- **This PR:** objects and claims introduced, changed, removed, or reclassified by the PR; and
- **Stack outcome:** the cumulative state at the current top of the stack.

Work beyond the stack appears only when an authoritative source explicitly declares it. The atlas does not infer future scope from naming, TODOs, or architectural possibility.

### Review handoff

The inspector summarizes the review contract and links to the narrowest available source view. It does not reproduce a full diff or comment thread. A reviewer can move from an architectural seam to a focused GitHub diff, exact files and symbols, relevant tests or evidence, and the PR in Graphite.

## Current stack lens map

The reference atlas for the batch-math stack has these lenses:

1. End-to-end framework map.
2. Request-to-trace lifecycle.
3. Batch adapter and framework boundary.
4. Runtime registry and product trace.
5. Fair holdout comparison.
6. Evidence binding and promotion.
7. Candidate identity and distinct attainable-SOL roles.

Each PR has one recommended entry lens and may participate in related lenses:

| Stack PR                                                  | Recommended entry lens                               | Related lenses                                                   |
| --------------------------------------------------------- | ---------------------------------------------------- | ---------------------------------------------------------------- |
| [#1341](https://github.com/systalyze/systalyze/pull/1341) | End-to-end framework map                             | Request-to-trace lifecycle; batch adapter and framework boundary |
| [#1376](https://github.com/systalyze/systalyze/pull/1376) | Batch adapter and framework boundary                 | End-to-end framework map; fair holdout comparison                |
| [#1379](https://github.com/systalyze/systalyze/pull/1379) | Batch adapter and framework boundary                 | Fair holdout comparison; evidence binding and promotion          |
| [#1344](https://github.com/systalyze/systalyze/pull/1344) | Request-to-trace lifecycle                           | Candidate identity and distinct attainable-SOL roles             |
| [#1377](https://github.com/systalyze/systalyze/pull/1377) | Request-to-trace lifecycle                           | Candidate identity and distinct attainable-SOL roles             |
| [#1345](https://github.com/systalyze/systalyze/pull/1345) | Runtime registry and product trace                   | Candidate identity and distinct attainable-SOL roles             |
| [#1412](https://github.com/systalyze/systalyze/pull/1412) | Evidence binding and promotion                       | Fair holdout comparison                                          |
| [#1342](https://github.com/systalyze/systalyze/pull/1342) | Runtime registry and product trace                   | Request-to-trace lifecycle; batch adapter and framework boundary |
| [#1346](https://github.com/systalyze/systalyze/pull/1346) | Candidate identity and distinct attainable-SOL roles | Runtime registry and product trace                               |
| [#1380](https://github.com/systalyze/systalyze/pull/1380) | Runtime registry and product trace                   | Candidate identity and distinct attainable-SOL roles             |
| [#1382](https://github.com/systalyze/systalyze/pull/1382) | Runtime registry and product trace                   | Request-to-trace lifecycle                                       |

This table is the initial reference mapping. The semantic review contracts are authoritative: implementation may refine a related-lens assignment when source evidence demonstrates a better route, but changing a recommended entry lens requires a corresponding design correction rather than a layout convenience.

## PR-body delivery

This section applies only when visual escalation has selected the atlas. Other
PRs keep the canonical Stack, Diff, and prose review path without an atlas
preview. Each affected PR body contains a compact inline orientation image
hosted as a private GitHub attachment. The image shows the PR's focused region
or seam, its immediate architectural context, and its direction toward the
stack outcome. It must remain legible at normal PR-body width.

The image links to the exact atlas state for:

- the recommended lens;
- the selected PR overlay;
- the selected node or seam when applicable; and
- the Reviewer persona preset.

Adjacent text states the review question, identifies the stack position, and provides compact links to related lenses. The canonical leading Stack and Diff disclosures and still-current custom body content remain intact.

The protected atlas is not used as the inline image source. The renderer produces a 1200-by-675 attachment-ready PNG whose text remains at least 12 CSS pixels high when displayed at 640 CSS pixels wide. The publication adapter records its association with the PR and target deep link. If GitHub does not provide a stable supported attachment-upload automation path, uploading the generated attachment is the only permitted manual publication step; it is not an input to semantic generation.

### Publication safety

The publication bundle includes the source snapshot digest, manifest digest,
generated asset digests, target PRs, each expected title and title digest,
expected PR-body digests, replacement atlas sections, and original atlas
sections. Each managed PR-body section is enclosed by stable ownership markers
containing the manifest digest. Re-running publication for the same digest
replaces or verifies the owned section instead of appending a duplicate.

Publication uses a two-phase workflow:

1. Publish and verify the complete protected atlas, generate every preview, obtain every required GitHub attachment URL, and prepare every body replacement without changing a PR body.
2. Immediately revalidate the base commit, every PR head commit, every expected
   title and title digest, every expected PR-body digest, and every atlas deep
   link. Then delegate each body mutation, in Graphite order, to the existing-PR helper in
   `publishing-reviewable-prs`. Each call uses exact identity and preimage
   digests, performs one write, and final-reads the result.

The publisher keeps a local resumable journal with each original and intended
title, its digest, original and intended body content, and the result of each
write. It preserves the exact expected title while changing the managed body
section. A failed upload or preflight changes no PR bodies. If a body update
fails after earlier updates succeeded, publication stops without retry or
rollback and reports the exact mixed state for operator resolution. GitHub
provides no conditional title/body mutation, so rollback could itself overwrite
a newer edit. Unreferenced uploaded attachments may remain. Final verification re-reads every title and body, verifies each title and digest, and checks all 11
bodies' ownership markers, images, deep links, and manifest digest.

## Validation and error handling

Generation is successful only when all applicable gates pass.

### Gate 1: schema and referential integrity

- The manifest satisfies its schema.
- Semantic IDs are unique and stable.
- Every relationship, claim, stack reference, and delivery entry resolves.
- The captured base and PR head commits still match the intended source snapshot.
- The base state contains only semantic objects and claims active at the captured base commit.
- Consequential author declarations are attributable, content-addressed, and present in a durable input.

### Gate 2: review-contract completeness

- Every stack-changed node and seam has a complete review contract.
- Every material claim has provenance and source references.
- Every PR has one recommended entry lens.
- Every changed node and seam appears in at least one lens; changed flows and regions remain reachable through their owning contract.

### Gate 3: visual and interaction budgets

- Labels do not overlap nodes, regions, controls, or each other; clipping and unintended overlap tolerance is zero.
- Focused parallel edge lanes maintain at least 16 CSS pixels between centerlines, and labels maintain at least 12 CSS pixels of clearance from unrelated edges and shapes.
- Major flows are traceable without crossing unrelated labels.
- Atlas views pass at 1024-by-768, 1280-by-800, and 1512-by-982 CSS-pixel desktop viewports. Viewports below 1024 CSS pixels are explicitly unsupported by this reference implementation rather than silently degraded.
- PR previews remain legible at 640 CSS pixels wide with rendered text at least 12 CSS pixels high.
- Keyboard navigation, focus visibility, contrast, text alternatives, and reduced-motion behavior pass their checks.

Automated checks own overlap, clipping, clearance, minimum text size, viewport fit, and accessibility rules. A human acceptance gate owns residual judgments such as whether a primary route is easy to follow, whether grouping conveys the intended architecture, and whether a generated split answers one coherent review question.

### Gate 4: rendered routing

- Every PR preview opens the expected lens, PR state, and selection.
- Every lens links back to the overview and appropriate related lenses.
- Inspector links resolve to the intended PR, diff, file, symbol, test, or evidence route.
- No published browser asset contains credentials, private API responses, or unneeded repository content.
- PR-body publication is fresh, idempotent, resumable, and either fully verified or explicitly reported as a blocked mixed state.

A validation failure blocks only the affected publish output unless it invalidates the overview or the canonical semantic graph. Errors report the semantic IDs, claims, lenses, and PR entries involved rather than only renderer coordinates.

## Testing strategy

The reference implementation requires:

- schema tests for valid and invalid manifests;
- property tests for stable IDs, referential integrity, typed change-set folding, invalid temporal operations, cross-PR dependencies, and cumulative PR-state construction;
- fixture tests for provenance and ambiguity propagation;
- contract tests for changed node and seam coverage, flow and region reachability, and PR entry routing;
- deterministic renderer tests based on semantic structure and bounded layout properties rather than fragile full-pixel snapshots;
- browser tests for lens navigation, minimap location, focus expansion, inspector updates, stack scrubbing, deep links, keyboard use, and responsive layouts;
- automated overlap, clipping, edge-separation, link-integrity, and accessibility checks;
- publication tests for stale source snapshots, concurrent PR-body edits,
  idempotent reruns, attachment failure, mid-stack body failure, partial-state
  reporting, resume, and final verification;
- package checks proving that every published view is manifest-derived; and
- a final human review of the seven-lens atlas at PR-body and full-atlas sizes.

The existing named overlap and disconnected-edge regressions remain fixtures until the generalized layout checks cover them directly.

## Reference implementation boundaries

The current implementation is maintained in personal or transient tooling space, separately from application repositories and their product branches, so diagram work cannot alter product code or ancestry. The semantic manifest, deterministic generator, tests, and documentation belong to personal tooling. Generated hosted artifacts and private GitHub attachments are publication outputs, not product runtime assets.

The implementation should reuse the current diagram package's strongest visual conventions while replacing hand-authored views with manifest-derived lenses. Discovery mockups may be manual, but no manual HTML, SVG, or geometry may enter the final published package.

## Delivery sequence

1. Define and test the semantic manifest and review-contract schema.
2. Encode the 11-PR stack, typed change sets, and attributable declarations, then validate provenance, ownership, and source routes.
3. Implement the overview and adaptive lens grammar.
4. Generate the seven reference lenses and cumulative PR overlays.
5. Implement the inspector, minimap, persona presets, stack scrubber, and deep links.
6. Generate compact PR entry previews and validate them at GitHub body width.
7. Run structural, visual, interaction, accessibility, and link validation.
8. Prepare the publication bundle, publish the protected atlas and private GitHub attachments, and pass the freshness preflight.
9. Update all PR bodies through the idempotent managed section while preserving the canonical leading Stack and Diff disclosures and still-current custom body content.
10. Verify every PR body, entry point, atlas route, and source handoff as a reviewer.

## Success criteria

- All 11 PRs have a legible inline orientation image and exact atlas deep link.
- The atlas provides one architecture overview and every justified focused lens without a fixed global depth limit.
- Reviewers can locate any changed node or seam in the full framework, identify its owning PR and dependencies, and reach its focused source and evidence.
- Selecting a dense seam separates its relationships enough to trace them without losing one-hop context.
- Before, selected-PR delta, and stack-outcome states are explicit and consistent with Graphite ancestry.
- Every changed node and seam has a complete, provenance-backed review contract; other changed subjects retain ownership and source routing through those contracts.
- All published views are generated from the manifest and pass the four validation gates.
- The static artifact contains no credentials or live review data.
- Atlas source, implementation, manifests, tests, documentation, and generated
  assets remain outside application repositories. Only PR-body links and
  private attachments are publication outputs on the application review
  surface.

## Deferred product direction

A broadly reusable review application could add PAT-backed repository access, live checks and review-status overlays, embedded source views, comment and approval integrations, repository adapters, persisted reviewer state, and multi-repository hosting. That is a distinct product with a different security, data-retention, and operational model. The reference implementation should inform its requirements, but must not grow into it implicitly. Work on that application pauses until its separate personal-project direction is explicitly approved.
