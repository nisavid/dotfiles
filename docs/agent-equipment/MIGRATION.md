# Agent equipment migration and recovery contract

This is the design deliverable for Issue #59. It specifies a future migration;
it does not authorize, start, or perform one. Running it requires separate
authorization for one fully resolved plan and its exact digests.

The migration changes provider routes without treating a distribution as an
atomic capability. Every plugin skill, MCP, hook, and other component is
classified before the plan chooses a preferred route, a supplementary route,
or no provider. The currently reviewed Matt plugin is a special case with one
25-skill activation group and no plugin-level hooks, MCPs, agents, commands,
monitors, executables, or LSP servers. A refreshed manifest must prove that
fact again before migration.

## Preconditions and authority gate

Complete all of these before the executor opens an action checkpoint:

1. Refresh the live inventory and every selected native manager channel. For
   Matt, refresh the official marketplace entry, upstream plugin manifest,
   exported skill set, plugin version, current standalone provenance, Claude
   projections, and installed plugin state. A change from the reviewed fixture
   invalidates the plan.
2. Resolve an authored catalog and digest-bound lock through the contract in
   `ARCHITECTURE.md`. The resolved plan must name every affected surface and
   contain no glob, inferred ownership, name-only disablement, or recursive
   filesystem operation.
3. Validate the complete plan, including the last action, before creating the
   first action checkpoint. Every automated mutation must be on a
   `reconciler_owned` route, have supported compare and verification
   capabilities, and declare `restore_captured_pre_state` compensation.
4. Reject stale catalog or lock digests, unresolved provenance, an unknown
   capability needed by the plan, a native-rolling version outside the reviewed
   baseline, and any operator-owned mutating action.
5. Prove that the catalog-driven Claude projector can be installed without
   invoking projection reconciliation. It must exclude plugin-provided Matt
   skills before any existing Claude link is removed.
6. Prove that recovery material can restore every mutable surface. Store the
   checkpoint directory with mode `0700` and files with mode `0600`; use atomic
   write, file `fsync`, rename, and parent-directory `fsync` for every state
   transition.
7. Acquire the reconciler's exclusive apply lease. Native managers and external
   editors remain outside that lease, so the compare guards below remain
   mandatory.
8. Present the secret-free dry-run, catalog digest, lock digest, plan digest,
   capability digest, exact surface set, and native-rolling limitations for
   operator review. Obtain separate authorization for that exact plan.

Planning, inventory, import, update, and adopt remain runtime-read-only. Only an
authorized `apply` may execute this runbook. Authorization for one plan does not
carry to a recomputed plan.

## Captured state

`captured-state-v1.schema.json` defines the secret-free manifest for one
migration run. The executor seals it after authorization and immediately before
the first mutation. Its four bindings make the capture unusable with another
catalog, lock, plan, or adapter capability set.

The manifest records every affected provider route with:

- its route identity, harness, and complete equipment identity set;
- its route control owner and single provenance owner;
- immutable revision, artifact reference, and content digest, or the
  native-rolling channel, observed version or absence, observation source, and
  native update control; and
- explicit captured or `not_applicable` references for installation,
  enablement, MCP-selection, and plugin-selection surfaces.

It records these surfaces separately:

- **Legacy Claude projector:** Presence, enabled state, `blanket`,
  `catalog_driven`, or `retired` mode, implementation digest, exact owned
  source/control location, and private recovery material.
- **Candidate Claude skill entry:** Catalog identity, projection route, path,
  `lstat` type, applicable metadata, and provenance. A symlink also records
  exact link text plus its resolved target or original broken state.
- **Canonical Agent Skills entry:** The same path evidence under
  `~/.agents/skills`, with mutation policy `forbidden`. Deterministic manifests
  and digests represent regular-file bytes, directory content, nested entry
  types, and applicable metadata.
- **Plugin installation:** Native identity, manager, scope, presence, channel,
  observed version, and observation source.
- **Plugin enablement:** Applicability and the exact enabled or disabled state.
- **MCP selection:** Narrow owning source and key path, presence,
  secret-redacted structural state, and private exact recovery material.
- **Plugin selection:** Narrow owning source and key path, presence,
  secret-redacted structural state, and private exact recovery material.

Surface and route identifiers are unique. Every route reference resolves to
exactly one surface of the required kind, every route named by a surface exists,
and the surface's route and equipment identities agree with the resolved plan.
These cross-reference checks are semantic validation in addition to JSON Schema
validation.

### Filesystem observation

Observe a skill entry with `lstat`; use `readlink` for link text. Resolution of
a link target is read-only evidence and never changes the object selected for a
write. A directory manifest walks entries in deterministic bytewise relative-
path order without traversing directory symlinks. For every entry it records
type and applicable metadata; it records regular-file size and byte digest,
directory metadata, and symlink text plus resolved or broken state. The
canonical JSON digest of that manifest is the directory content claim.

The metadata record states the capture platform and records mode, uid, gid,
nanosecond mtime, flags when supported, and digests or explicit
`none`/`unsupported` results for ACLs and extended attributes. A comparison uses
exactly the fields declared applicable at capture.

Every `~/.agents/skills/<name>` surface is verification-only. The migration may
read its entry and, when resolvable, its target. It may not delete, replace,
rename, chmod, chown, rewrite, traverse through a symlink for a write, or use it
as the destination of a native installer. Drift on one of these surfaces stops
the migration; rollback never writes to it.

### Recovery material and secrets

The manifest contains secret reference names, never resolved values. Exact raw
pre-state needed to restore an owned config key or projector file is sealed in
the private checkpoint content-addressed store. The manifest references the
blob by a digest of its sealed ciphertext. Comparisons involving secret-bearing
state happen locally against the unsealed recovery blob and emit only
match/mismatch evidence. Logs, diagnostics, diffs, receipts, and generated
artifacts contain neither values nor unsalted digests of values.

A Claude symlink needs no raw target content: its exact link text, link metadata,
and broken or resolved state are sufficient recovery material. Native-manager
recovery is an inverse operation bound to the captured normalized native state.

## Compare contract

The unit of comparison is the narrowest surface an action can mutate: one path
entry, one plugin identity and scope, one enablement bit, or one owned config
key path. An adapter preserves unrelated keys and native state. It never uses a
whole-file rewrite when a narrow owned overlay is available.

Immediately before each action:

1. If this run has not changed the surface, observe it and require exact
   equality with captured pre-state.
2. If an earlier completed action in this run changed the surface, require
   exact equality with that action's expected post-state.
3. Reverify every canonical Agent Skills entry on which the action depends.
4. Persist the comparison result in the mutation receipt without including
   secret values.

Immediately before compensation, observe every surface in the action and
require exact equality with the post-state written by that action. Restore only
after that comparison succeeds. This is compare-before-restore, not a request
to force the old value.

- **Projector:** Compare the owned source/control location, presence, enabled
  state, mode, and implementation bytes through their private or secret-free
  digest.
- **Claude or Agent Skills entry:** Compare `lstat` type and applicable
  metadata, then file bytes, the deterministic directory manifest, or exact
  link text and resolution evidence according to type.
- **Plugin installation:** Compare native identity, scope, presence, channel,
  observed version, and manager-reported source.
- **Plugin enablement:** Compare plugin identity, scope, applicability, and
  enabled state.
- **MCP or plugin selection:** Compare presence and exact raw value at the owned
  key path inside the private process boundary. Put only the secret-redacted
  structure in the receipt.

A mismatch is concurrent or manager-driven drift. The executor preserves the
observed state, writes a secret-free drift report, stops all forward processing,
and begins compensation only for surfaces whose restore guards still match.
If a restore guard mismatches, compensation also stops. It never overwrites the
external change to make rollback appear complete.

## Ordered migration

Each numbered mutation is a separately checkpointed action or a deterministic
series of separately checkpointed actions. A completion criterion follows each
step.

### 1. Resolve, authorize, capture, and seal

Resolve and validate the entire plan, obtain exact-plan authorization, acquire
the apply lease, recapture every route and surface, and resolve again against
that capture. If the recapture changes the plan, release the lease and return a
new proposal for separate authorization. Atomically seal the captured-state
manifest and its private recovery blobs.

Completion: the authorized plan and sealed capture have identical bindings;
all route and surface cross-references validate; no harness state has changed;
no action checkpoint exists yet.

### 2. Replace the blanket Claude projector

Prepare a checkpoint for the projector control surface. Compare it with its
captured state, install the catalog-driven replacement without running
projection reconciliation, and verify that it projects only catalog-selected
standalone routes. Its exclusion set must include every Claude identity whose
preferred route is the Matt plugin. Mark the checkpoint completed.

The replacement must be effective before link removal and must not create,
remove, or rewrite a Claude skill entry as a side effect of installation.

Completion: a verified catalog-driven projector owns future projections; every
candidate Claude and canonical Agent Skills entry still equals captured state.

### 3. Remove only identified Matt projections

Iterate the resolved Matt equipment identities in canonical order. For each
`~/.claude/skills/<name>` candidate:

- an absent captured entry is a verified no-op;
- a captured symlink is eligible only when its exact link text, target or
  broken state, catalog identity, route, and provenance prove it is the
  catalog-owned standalone projection for that identity; and
- a regular file, directory, unknown-provenance link, or link to an unexpected
  target is fatal drift and is not removed.

For each eligible link, reverify its canonical Agent Skills entry, persist a
prepared checkpoint, compare the link with captured state, and unlink the link
entry itself. Do not resolve the path before unlinking and do not use recursive
removal. Verify the Claude path is absent, then persist completion before
advancing to the next link.

The current research fixture observes 21 eligible links and four absent
projections among 25 Matt identities. Those counts are dated evidence, not an
execution constant; the refreshed catalog-identified set controls the run.

Completion: every eligible Claude projection is absent, every ineligible entry
was preserved or stopped the run, the projector remains catalog-driven, and all
25 canonical Agent Skills entries remain byte-, type-, link-, and
metadata-equivalent to capture.

### 4. Install the official Matt plugin when absent

Compare the captured plugin installation surface. If the official plugin is
absent, run the locked install operation for
`mattpocock-skills@claude-plugins-official` at user scope and verify the native
identity, channel, observed plugin version, manager source, and full 25-skill
activation group. Persist the native state that installation actually writes,
including enablement when the manager couples it to install.

If the plugin was already installed at the reviewed route and baseline, install
is a no-op. A different marketplace route, version, source, or component set is
manager-driven drift and requires replanning. The migration never updates or
reinstalls a pre-existing native-rolling artifact.

Completion: the reviewed official plugin route is installed once, or the
pre-existing reviewed installation remains untouched. The installation
checkpoint's expected post-state includes every native surface changed by the
install command.

### 5. Enable the Matt plugin

Compare against captured state or the installation checkpoint's expected state,
whichever is newer. Enable the plugin only when installed and disabled. If
installation already enabled it, or it was enabled before migration, record a
verified no-op. Verify all 25 exported skills are active as one inseparable
activation group; this Claude route has no supported per-skill suppression.

Completion: the official Matt plugin is enabled, and a completed enablement
checkpoint exists only when this step changed enablement.

### 6. Reconcile MCP selections component by component

For every MCP identity in the plan, compare each exact selection surface and
apply only its catalog-selected route change. Prefer a plugin-provided MCP only
when its entire required equipment set is present and the harness exposes a
supported component control. If a plugin also supplies a hook, skill, or other
component that the standalone routes cannot replace, retain the plugin, retain
an explicitly allowed supplementary route, select supported components, or
stop for a case-by-case operator decision. Plugin installation alone never
implies that all of its components are selected.

Treat each independently controllable MCP selection as one action. Treat a
manager's inseparable component set as one activation-group action. An
operator-owned Cursor plugin remains verify-and-report-only until a stable
mutation contract exists.

Completion: every MCP has exactly the preferred route plus only documented
supplementary routes; every removed selection has a completed checkpoint and
private exact recovery material; unrelated config and native state are
unchanged.

### 7. Reconcile plugin and component selections

Apply the remaining plugin selection, standalone-skill suppression, and
selective component controls from the plan. Use component controls before
treating a plugin as atomic. Disable a standalone Codex or Cursor skill only by
its exact catalog-owned path and only when the preferred plugin component is
verified active. Preserve an overlap only through an explicit `allow_overlap`
exception that names the complete active route set and rationale.

Operator-owned selections produce instructions and evidence, not automated
mutations. A required operator action leaves the automated migration incomplete
until it is performed under separate authority and a fresh audit confirms it.

Completion: every equipment identity has exactly one canonical harness coverage
record and every active provider route has its declared operation disposition;
the effective route set matches the plan with no inferred duplicate.

### 8. Verify and complete the run

Audit from supported runtime surfaces and verify all of these together:

- the catalog and lock bindings still match the authorized plan;
- the blanket projector cannot recreate excluded links;
- only catalog-identified Matt Claude symlinks are absent;
- every canonical Agent Skills entry remains exactly as captured;
- the official Matt plugin exposes the refreshed, reviewed activation group and
  has its intended enablement;
- MCP and plugin selections match preferred and allowed supplementary routes;
- every active route has one provenance owner, supported restore evidence, and
  a complete operation matrix;
- no managed duplicate remains and every intentional overlap is explicit;
- operator-owned and unavailable operations are reported without mutation; and
- artifacts, logs, diagnostics, diffs, receipts, and checkpoints disclose no
  secret value.

Only after the whole verification passes may the executor durably mark the run
`succeeded`. A second audit of the same catalog, lock, and live state must
produce an empty mutation plan.

Completion: the success marker is durable and fsynced, the apply lease is
released, and steady-state audit is a no-op. Any failed condition enters the
recovery procedure.

## Checkpoints and idempotence

One checkpoint binds a single adapter action and every surface that action can
change. It records the run and action identity, deterministic ordinal, four
plan bindings, adapter and capability identity, captured pre-state reference,
expected post-state, compensation operation, attempt receipts, and phase.

The action state machine is:

```text
prepared -> completed -> compensating -> compensated
```

Persist and fsync `prepared` before the adapter runs. Persist and fsync
`completed` only after post-state verification. Before rollback, persist and
fsync `compensating`; after restoration and verification, persist and fsync
`compensated`. Records are append-only state transitions or compare-and-swap
replacements; an older writer cannot overwrite a newer phase.

Recover a surviving `prepared` checkpoint by audit:

- observed pre-state means the action did not take effect and can be retried;
- observed expected post-state means it took effect, so record completion
  without replay; and
- any other observation is partial or concurrent drift, which is preserved and
  requires operator recovery.

Recover `compensating` by the inverse rule: captured pre-state means record
compensation without replay; expected post-state means retry compensation after
the restore guard passes; any other state is preserved and stops recovery.

A completed run whose live state still equals its expected state is a no-op on
rerun. A compensated run is historical evidence, not a license to replay; a new
apply requires a fresh capture and exact-plan authorization.

## Step-level compensation

Rollback processes completed actions in reverse ordinal order. An ambiguous
prepared or compensating action is audited and classified before rollback
continues.

- **Install the catalog-driven projector.** No-op when the exact implementation
  digest and control state are already present. Compensation restores captured
  projector bytes and control state, but restores a blanket projector only
  after every removed link. The guard requires the projector to still equal the
  replacement written by this run.
- **Remove one Claude skill link.** No-op when the captured entry was absent.
  Compensation recreates the exact symlink text at the same path and restores
  applicable link metadata and broken/resolved semantics without writing
  through the link. The guard requires the Claude path to remain absent and its
  canonical Agent Skills entry to equal capture.
- **Install the Matt plugin.** No-op when the reviewed route was already
  installed. Compensation uninstalls only when installation was absent before
  migration. The guard covers plugin installation and every install-coupled
  surface in this action's expected post-state.
- **Enable the Matt plugin.** No-op when it was already enabled or installation
  coupled the desired enablement. Compensation restores captured enablement and
  retains a pre-existing plugin. The guard requires enablement to still equal
  the state written by this run.
- **Change one MCP selection or inseparable activation group.** No-op when the
  exact desired selection is present. Compensation restores exact captured
  presence and value from private recovery material. Every owned key must still
  equal this action's expected post-state.
- **Change one plugin or component selection.** No-op when the exact desired
  selection is present. Compensation restores the captured selection or exact
  standalone suppression entry. Every owned key and affected activation group
  must still equal this action's expected post-state.

If the Matt plugin was absent initially, reverse enablement first when it was a
separate action, then uninstall it. If installation itself enabled the plugin,
the installation checkpoint owns both surfaces and uninstall is its one
compensation. If the plugin existed initially, rollback never uninstalls it and
restores its exact prior enablement. A native-rolling route never claims an
exact old artifact restore; this migration avoids changing an existing
artifact so rollback needs only presence and enablement restoration.

Canonical Agent Skills entries have no compensation because they have no
authorized mutation. Their mismatch is a hard stop, not an invitation to repair
or replace them.

## Failure-injection contract

The acceptance matrix must exercise these boundaries against disposable homes
and deterministic fake adapters. Every case proves processing stops, checkpoint
state is durable, retry is audit-first, external changes survive, and eventual
forward completion or compensation is idempotent.

- **Full-plan rejection:** Inject an invalid final action, stale lock, missing
  compensation, or operator-owned automated mutation. Reject before the first
  action checkpoint with zero harness mutation.
- **Capture persistence:** Fail the captured-state or private recovery write.
  Create no action checkpoint and perform zero harness mutation.
- **Prepared persistence:** Fail its write or fsync. Never call the adapter.
- **After prepared:** Stop before comparison or adapter call. Recovery observes
  pre-state and may retry once.
- **Compare-before-mutate:** Inject an external change on every surface in
  separate cases. Preserve it, skip the adapter, and stop forward processing.
- **Adapter before mutation:** Fail the call before mutation. Leave the
  checkpoint prepared; audit observes pre-state.
- **Adapter ambiguous failure:** Return failure after a partial or complete
  mutation. Audit classifies pre-state, expected post-state, or other drift
  before retry.
- **After mutation:** Stop before verification. Recovery avoids blind replay;
  expected post-state becomes completed without a second mutation.
- **Verification failure:** Reverse-compensate earlier completed actions and an
  audited completed current action.
- **Completed persistence:** Fail its write or fsync. Audit the surviving
  prepared state and record expected post-state completed without replay.
- **After projector replacement:** Restore every captured surface and restore
  the projector last.
- **After each individual Claude-link removal:** Restore that link and every
  earlier link exactly. Canonical Agent Skills entries never change.
- **After plugin installation:** Uninstall only when initially absent; retain a
  pre-existing installation.
- **After plugin enablement:** Restore prior enablement without uninstalling a
  pre-existing plugin.
- **After each MCP reconciliation:** Restore all changed selection keys exactly
  and preserve unrelated keys.
- **After each plugin/component selection:** Restore changed selections and
  suppressions exactly, including their activation groups.
- **Compensating persistence:** Fail its write or fsync. Never call the restore
  adapter.
- **Compare-before-restore:** Inject an external change separately on the
  projector, each link, plugin installation, enablement, every MCP selection,
  and every plugin selection. Preserve it and stop compensation durably.
- **Compensation ambiguous failure:** Fail before, during, and after restoration.
  Audit classifies captured pre-state, expected post-state, or other drift
  before retry.
- **Compensated persistence:** Fail its write or fsync. Audit recognizes
  restored pre-state and records compensation without destructive replay.

Run the mutation-boundary cases once for every planned action, not once per
adapter kind. Include resolved and broken Claude symlinks, regular-file and
directory canonical entries, applicable metadata changes, install commands that
couple enablement, native-rolling version drift, selective and inseparable
component controls, and secret-bearing selection values. Scan every observable
output for seeded secret values.

## Operator failure and recovery

1. Stop new applies and retain the exclusive lease. Do not rerun native manager
   commands, chezmoi projection hooks, or ad hoc link repair.
2. Locate the newest nonterminal run and verify its catalog, lock, plan, and
   capability digests against the authorized receipt. A mismatch requires a
   new read-only investigation, not checkpoint editing.
3. Audit every `prepared` and `compensating` checkpoint from supported surfaces.
   Record whether each surface equals captured pre-state, the action's expected
   post-state, or neither.
4. Resume forward only when the exact authorized plan remains valid, every
   ambiguous action is classified, and all next-action compare guards pass.
   Otherwise compensate completed actions in reverse order.
5. At a compare-before-restore mismatch, preserve the external state and stop.
   Report the exact surface, expected secret-free state, observation source,
   and checkpoint. Obtain an explicit decision to retain the external change
   in a new plan or have its owner restore the expected migration state before
   compensation resumes.
6. At a native compensation failure, audit before retry. If a plugin absent at
   capture now differs from the installation written by this run, do not
   uninstall it. If a plugin existed at capture, never uninstall it; restore
   only enablement or selections that still pass their guards.
7. After compensation, verify every mutable surface equals captured state and
   every canonical Agent Skills entry remains unchanged. Mark the run
   `compensated` only when all restorations are durable. Otherwise mark it
   `needs_operator` and retain every checkpoint and recovery blob.
8. Release the lease only after a terminal `succeeded` or `compensated` state,
   or after recording a deliberate operator handoff for `needs_operator`.
   Archive checkpoints according to retention policy; never delete evidence to
   clear an error.

Successful recovery restores every captured mutable surface unless a concurrent
change makes restoration unsafe. In that case, preserving the external change
and stopping is the stronger invariant; completion waits for a separately
authorized replan.

## Postconditions

After success:

- the Claude projector is catalog-driven and cannot recreate the retired Matt
  projections;
- only catalog-identified Matt links are absent from `~/.claude/skills`;
- every `~/.agents/skills` entry remains in its captured type and state;
- the reviewed official Matt plugin route is installed and enabled;
- MCPs, plugins, component controls, and standalone suppressions match complete
  provider selections without undocumented duplication; and
- a repeated audit proposes no mutation.

After compensation, every mutable surface equals captured state and the legacy
projector is restored only after its projections. A concurrent-change stop is
neither success nor completed rollback; it is durable `needs_operator` state.
