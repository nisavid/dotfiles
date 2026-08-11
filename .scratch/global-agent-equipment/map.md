# Wayfinder: Global Agent Equipment

## Destination

Produce a reviewer-ready, decision-complete architecture, acceptance matrix,
and sequenced implementation handoff for chezmoi-managed global agent
equipment, including the Matt Pocock migration. The map ends before runtime
migration; execution resumes from the handoff produced by
[Produce the implementation handoff](https://github.com/nisavid/dotfiles/issues/61).

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
  complete harness coverage records across Claude Code, Codex, and Cursor rather
  than identical artifacts, with operation dispositions modeled separately on
  every selected active provider route.
- [Choose catalog and runtime ownership][decision-03] — make the chezmoi
  catalog authoritative desired state while native caches remain runtime state.
- [Define equipment identities and providers][decision-04] — identify each
  component independently from the distributions and provider routes that
  supply it.
- [Define provider selection and deduplication][decision-05] — resolve the
  effective component set after selective controls, keep provider selection
  separate from operation disposition, declare runtime control ownership on
  every active route, preserve the canonical coverage-record shape, then reject
  unexplained overlap.
- [Define inventory selection and version semantics][decision-06] — support
  source-wide and explicit selection, lock reproducible targets immutably,
  classify native-rolling routes explicitly, and update separately from
  ordinary apply.
- [Choose lock and provenance authority][decision-07] — use a generated
  repo-owned lock for deterministic restore where providers expose reproducible
  artifacts while retaining native manager locks as provenance.
- [Define reconciliation and drift boundaries][decision-08] — mutate only
  catalog-managed, reconciler-owned routes, keep operator-owned routes
  verify-and-report-only, report other drift, and require explicit adoption.
- [Scope the first implementation slice][decision-09] — inventory all global
  equipment and actively reconcile skills, plugins, and MCPs without secrets.
- [Choose the reconciliation architecture][decision-10] — use one catalog,
  one resolver and lock, and native manager and harness adapters with
  full-plan ownership and compensation validation before mutation.
- [Research current harness and manager behavior][decision-11] — base the
  design on verified Claude, Codex, Cursor, chezmoi, and `skills` constraints.

## Open work

- [#55: Design the catalog and lock schema](https://github.com/nisavid/dotfiles/issues/55) — current implementation frontier.
- [#56: Design the resolver and adapter contracts](https://github.com/nisavid/dotfiles/issues/56) — depends on #55.
- [#57: Prototype Matt, MCP, and update-channel resolution](https://github.com/nisavid/dotfiles/issues/57) — depends on #55 and #56.
- [#58: Classify the initial live inventory](https://github.com/nisavid/dotfiles/issues/58) — depends on #55 and #57.
- [#59: Specify the migration and rollback](https://github.com/nisavid/dotfiles/issues/59) — depends on #56, #57, and #58.
- [#60: Define the acceptance matrix](https://github.com/nisavid/dotfiles/issues/60) — depends on #56–#59.
- [#61: Produce the implementation handoff](https://github.com/nisavid/dotfiles/issues/61) — depends on #59 and #60.

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

[decision-01]: https://github.com/nisavid/dotfiles/issues/44
[decision-02]: https://github.com/nisavid/dotfiles/issues/45
[decision-03]: https://github.com/nisavid/dotfiles/issues/46
[decision-04]: https://github.com/nisavid/dotfiles/issues/47
[decision-05]: https://github.com/nisavid/dotfiles/issues/48
[decision-06]: https://github.com/nisavid/dotfiles/issues/49
[decision-07]: https://github.com/nisavid/dotfiles/issues/50
[decision-08]: https://github.com/nisavid/dotfiles/issues/51
[decision-09]: https://github.com/nisavid/dotfiles/issues/52
[decision-10]: https://github.com/nisavid/dotfiles/issues/53
[decision-11]: https://github.com/nisavid/dotfiles/issues/54
