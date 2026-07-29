# Review atlas reference design

## Purpose

A review atlas is an optional navigation aid for a pull request or stacked
change that cannot be explained clearly with prose and a conventional diff
alone. It presents one semantic model through a small set of related
architectural views and routes each claim back to authoritative review
evidence.

The atlas guides review. The repository and code-review platform remain the
systems of record for code, diffs, comments, checks, and approvals.

## When to use an atlas

Use an atlas only when a visual model materially improves review of one or more
of these relationships:

- several changes affect the same architectural boundary;
- behavior spans three or more components or lifecycle stages;
- a stack changes the same system over multiple pull requests;
- ownership, dependency, or state transitions are difficult to explain
  linearly; or
- a reviewer needs multiple focused views without losing system context.

For a small or local change, keep the normal prose-and-diff review path.

## Design principles

### Architecture first

Model entities, seams, flows, and regions independently of pull-request
chronology. A component keeps one stable semantic identity as later changes
modify it.

### Guided exploration

Start with an architecture overview. Add focused lenses that each answer one
concrete review question. Preserve enough surrounding context for reviewers to
understand where a focused view belongs.

### Progressive disclosure

Keep the canvas limited to the relationships needed for the active question.
Put files, symbols, evidence, assumptions, and risks in a detail inspector
instead of crowding the diagram.

### Claims carry provenance

Classify every material claim as:

- **Observed:** supported directly by code, tests, history, or review metadata.
- **Declared:** supplied by an authoritative design or product source.
- **Inferred:** synthesized from evidence and clearly marked as an inference.
- **Unknown or conflicted:** unsupported or contradicted by available evidence.

Unknown and conflicted claims remain visible when useful. They must not be
presented as established behavior.

## Semantic model

The renderer consumes a typed manifest with this conceptual structure:

```text
ReviewAtlasManifest
├── sourceSnapshot
│   ├── repository
│   ├── baseCommit
│   ├── changes
│   └── pullRequests
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
├── lenses
└── deliveryEntries
```

Graph objects use stable semantic IDs. Display labels, rendered element IDs,
file paths, and pull-request references point to those IDs; they are not the
objects' identities.

### Temporal changes

Each change set applies ordered operations to stable objects:

- **Add:** activate a new object or claim.
- **Modify:** change fields while retaining semantic identity.
- **Remove:** end an object's or claim's active lifetime.
- **Reclassify:** change provenance, role, or temporal status.

Each operation records its before and after state, owner, prerequisites, and
cross-change dependencies. Validation rejects an incorrect before state,
duplicate activation, modification of an inactive object, and unsatisfied
dependencies.

The resulting views distinguish:

- **Before:** state immediately before the selected change;
- **Selected change:** additions, modifications, removals, and
  reclassifications owned by that change; and
- **Outcome:** cumulative state after all selected changes.

### Review contracts

Every changed node or seam needs a complete review contract:

- the claim and why it matters;
- change ownership and dependencies;
- implementing files and symbols;
- focused diff routes;
- tests or other evidence;
- temporal state;
- risks, assumptions, and unresolved conflicts.

Changed flows, regions, and claims may use the contract of the node or seam
they explain. Promote them to independent review subjects only when reviewers
must evaluate them separately.

An incomplete contract blocks its affected view. It must not yield a partial
view presented as authoritative.

## Lens decomposition

Every atlas has one overview. Derive additional lenses from review questions
and graph density rather than from a fixed count.

For each lens:

1. State the review question.
2. Select the smallest useful view type, such as lifecycle, boundary,
   comparison, state, identity, evidence, or flow.
3. Include the focused objects and the minimum context needed to locate them in
   the overview.
4. Split the lens if routes are hard to trace, labels collide, unrelated
   concerns compete, or the inspector would need to compensate for an
   overloaded canvas.
5. Verify that every changed node and seam appears in at least one lens and
   that every lens links back to the overview.

Layout hints may control ordering, lanes, or label placement. They must not add
semantic objects, hide required context, or bypass the manifest.

## Reviewer experience

A review workspace should provide:

1. the atlas name, active lens, and selected change;
2. guided lens navigation and an overview indicator;
3. a canvas showing the current review question;
4. an inspector with claim, provenance, ownership, source routes, evidence,
   temporal state, risks, and assumptions; and
5. controls for moving between base, selected-change, and outcome states.

Selecting an object gives it visual priority, keeps immediate context visible,
and updates the inspector without changing the active temporal state.

The inspector links to the narrowest authoritative source view. It summarizes
the contract but does not reproduce a full diff or discussion thread.

## Publication boundary

Publish only the minimum review-facing representation. A rendered atlas may
contain semantic IDs, architectural claims, display labels, public review
identifiers, repository-relative paths, symbol names, evidence labels, and
non-secret deep links.

Do not publish:

- source-file or diff bodies;
- discussion or API payloads;
- credentials, signed links, or authentication material;
- private machine paths or host details; or
- unrelated repository metadata.

Access control on a linked destination does not make embedded credentials safe.

## Validation

Generation succeeds only when:

- the manifest satisfies its schema and all references resolve;
- captured source revisions still match the intended snapshot;
- semantic IDs are unique and stable;
- every changed node and seam has a complete review contract;
- every material claim has provenance;
- every change has a recommended entry lens;
- every changed object appears in a reviewable lens;
- labels and routes are legible at supported viewports;
- keyboard navigation, focus, contrast, text alternatives, and reduced-motion
  behavior pass accessibility checks;
- source and evidence links resolve to their intended targets; and
- published assets contain no credentials or unnecessary source content.

A local ambiguity should block only dependent views. An ambiguity in the
primary architecture or flow blocks the overview and therefore the atlas.

## Testing

Use synthetic fixtures for schema, temporal operations, provenance,
contract-completeness, lens coverage, routing, publication safety, and
accessibility tests. Add visual checks for overlap, clipping, route
traceability, and minimum text size at supported viewports.

Human review remains necessary for judgments such as whether the primary flow
is easy to follow, whether grouping conveys the intended architecture, and
whether each lens answers one coherent review question.
