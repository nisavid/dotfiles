# Wayfinder: Global Agent Equipment

## Destination

Produce a reviewer-ready, decision-complete architecture, acceptance matrix,
and sequenced implementation handoff for chezmoi-managed global agent
equipment, including the Matt Pocock migration. The map ends before runtime
migration; execution resumes from the handoff produced by
[Produce the implementation handoff](./issues/18-produce-the-implementation-handoff.md).

## Notes

- This map is planning-only.
- Use `grilling` and `domain-modeling` for unresolved decisions.
- Use `research` and `context7-mcp` for current public harness and package-manager contracts.
- Use `checkpointing-and-publishing-git-work` for repository checkpoints and publication.
- Treat written plans as hypotheses and re-check live harness state before mutation.
- Cover global Claude Code, Codex, and Cursor equipment in the first program.
- The first implementation slice actively reconciles skills, plugins, and MCPs.
- Model hooks and other plugin components when resolving coverage even when their standalone reconciliation is deferred.
- Never put credentials or secret values in the catalog, lock, generated files, logs, tests, tickets, or reports.
- Preserve harness-owned caches, databases, credentials, timestamps, and unrelated runtime state.

## Decisions so far

- [Bound the Wayfinder destination][decision-01] — produce the architecture,
  acceptance matrix, and implementation sequence before runtime migration.
- [Define parity and the active harnesses][decision-02] — require explicit,
  explainable equipment coverage across Claude Code, Codex, and Cursor rather
  than identical artifacts.
- [Choose catalog and runtime ownership][decision-03] — make the chezmoi
  catalog authoritative desired state while native caches remain runtime state.
- [Define equipment identities and providers][decision-04] — identify each
  component independently from the distributions and providers that supply it.
- [Define provider selection and deduplication][decision-05] — resolve the
  effective component set after selective controls, then reject unexplained overlap.
- [Define inventory selection and version semantics][decision-06] — support
  source-wide and explicit selection, resolve both to reviewed immutable locks,
  and update separately from ordinary apply.
- [Choose lock and provenance authority][decision-07] — use a generated
  repo-owned lock for restore while retaining native manager locks as provenance.
- [Define reconciliation and drift boundaries][decision-08] — mutate only
  catalog-managed state, report other drift, and require explicit adoption.
- [Scope the first implementation slice][decision-09] — inventory all global
  equipment and actively reconcile skills, plugins, and MCPs without secrets.
- [Choose the reconciliation architecture][decision-10] — use one catalog,
  one resolver and lock, and native manager and harness adapters.
- [Research current harness and manager behavior][decision-11] — base the
  design on verified Claude, Codex, Cursor, chezmoi, and `skills` constraints.

## Not yet specified

- Whether a future standard Agent Plugin format can replace parts of the
  catalog or become another provider adapter without changing equipment identities.
- How later slices should reconcile standalone hooks, commands, agents,
  subagents, rules, and other component kinds after the first slice settles.
- How Cursor's adapter should simplify if Cursor gains a documented portable
  user-plugin manifest, install CLI, or path-specific skill controls.

## Out of scope

- Executing the runtime migration inside the Wayfinder map; implementation
  begins only after the handoff is approved.
- Project, workspace, repository, team, and organization-scoped equipment in
  the first program; the active scope is global user equipment.
- Owning or copying harness caches, opaque application databases, credentials,
  usage state, timestamps, or authentication material.
- Designing or standardizing a cross-vendor Agent Plugin specification.
- Active standalone reconciliation of hooks, commands, agents, subagents, and
  rules in the first slice, except for modeling plugin coverage and conflicts.
- Harnesses other than Claude Code, Codex, and Cursor in the first program.

[decision-01]: ./issues/01-bound-the-destination.md
[decision-02]: ./issues/02-define-parity-and-active-harnesses.md
[decision-03]: ./issues/03-choose-catalog-and-runtime-ownership.md
[decision-04]: ./issues/04-define-equipment-identities-and-providers.md
[decision-05]: ./issues/05-define-provider-selection-and-deduplication.md
[decision-06]: ./issues/06-define-inventory-selection-and-version-semantics.md
[decision-07]: ./issues/07-choose-lock-and-provenance-authority.md
[decision-08]: ./issues/08-define-reconciliation-and-drift-boundaries.md
[decision-09]: ./issues/09-scope-the-first-implementation-slice.md
[decision-10]: ./issues/10-choose-the-reconciliation-architecture.md
[decision-11]: ./issues/11-research-current-harness-and-manager-behavior.md
