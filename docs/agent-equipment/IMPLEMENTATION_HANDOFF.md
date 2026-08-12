# Global agent equipment implementation handoff

This handoff closes the design route in Issues #44–#61. It is the work
contract for an ordinary production implementation. It does not authorize a
runtime migration, a live plugin change, or a rewrite of any harness-owned
state.

## Fixed destination

Build one Python 3.12+ controller, entered through chezmoi, with:

- one versioned authored catalog and one generated resolved lock;
- one pure resolver that preserves the canonical harness coverage record from
  catalog through lock, inventory, plan, and adapter request;
- native-manager and narrow file-overlay adapters for global Claude Code,
  Codex, and Cursor;
- distinct `audit`, `import`, `adopt`, `update`, and `apply` commands with the
  mutation boundaries in `ARCHITECTURE.md`; and
- a durable per-operation checkpoint executor with pre-state-restoring
  compensation and audit-before-retry.

The first complete production release inventories all observed skills,
plugins, plugin components, and MCPs. It actively reconciles only accepted
skill, plugin, and MCP entries. Hooks and other plugin components participate
in coverage and conflict resolution even when their standalone adapters remain
deferred.

## Authoritative artifacts

| Artifact | Role |
| --- | --- |
| `docs/agent-equipment/CONTEXT.md` | Domain language and identity boundaries |
| `docs/agent-equipment/ARCHITECTURE.md` | Resolver, command, adapter, and executor contract |
| `docs/agent-equipment/catalog-v1.schema.json` | Authored catalog serialization contract |
| `docs/agent-equipment/lock-v1.schema.json` | Expanded lock serialization contract |
| `docs/agent-equipment/captured-state-v1.schema.json` | Pre-mutation runtime capture and recovery-evidence contract |
| `docs/agent-equipment/plan-action-set-v1.schema.json` | Closed projection of every independently validated automated plan action supplied to captured-state validation |
| `docs/agent-equipment/adapter-contract-v1.schema.json` | Closed capability, request, observation, action, and receipt serialization contract |
| `docs/agent-equipment/initial-catalog.proposed.json` | Schema-valid initial desired-state proposal; no live authority |
| `docs/agent-equipment/initial-lock.proposed.json` | Generated 132-record lock bound to the proposed catalog digest |
| `docs/agent-equipment/INVENTORY.md` and `initial-inventory.json` | Dated, secret-free read-only observation and initial classification |
| `docs/agent-equipment/PROTOTYPE_FINDINGS.md` | Disposable-prototype evidence and resulting design constraints |
| `docs/agent-equipment/MIGRATION.md` | Separately authorized migration and rollback contract |
| `docs/agent-equipment/ACCEPTANCE.md` | Requirement-to-fixture production release gate |
| `scripts/agent_equipment_design.py` and `tests/test_agent_equipment_design.py` | Executable schema, expansion, and fail-closed design model |
| `scripts/agent_equipment_acceptance_model.py` and `tests/test_agent_equipment_acceptance.py` | Disposable fake-manager convergence, checkpoint, compensation, and migration-boundary evidence |
| `scripts/agent_equipment_captured_state.py` and `tests/test_agent_equipment_captured_state.py` | Captured-state capability/action-set digests and fail-closed cross-record semantic validation against separately supplied plan actions |
| `scripts/agent_equipment_adapter_contract.py`, `tests/test_agent_equipment_adapter_contract.py`, and `tests/fixtures/agent-equipment/schema/*-adapter-*.json` | Cross-record semantic binding validator plus executable positive and fail-closed adapter-contract examples |

Research notes are dated evidence, not desired state. Native locks, runtime
files, caches, credentials, application databases, and manager timestamps are
observations, never competing authorities.

The executable design model has no adapters, checkpoint store, or command that
can mutate runtime state. Its `mutation_plan` is an unordered, non-production
evidence set of declared automated operations used to prove all-or-nothing
validation. Stable serialization or lexical sorting does not make it safe to
execute. It must not be promoted as the production resolver until it carries a
closed, cycle-free dependency graph and derives a deterministic topological
order from that graph.

The executable acceptance model has only in-memory fake-manager state,
fixture-local files, and fixture-local durable checkpoints. It exercises the
production contract's convergence and recovery semantics without reading or
mutating a real harness, user home, native manager, or credential store. It is
evidence for the handoff, not the production controller or runtime-migration
authority.

## Production source shape

Add these exact source paths in dependency order:

```text
home/dot_config/agent-equipment/catalog-v1.json
home/dot_config/agent-equipment/lock-v1.json
home/dot_local/bin/executable_agent-equipment
home/dot_local/lib/agent-equipment/schemas/catalog-v1.schema.json
home/dot_local/lib/agent-equipment/schemas/lock-v1.schema.json
home/dot_local/lib/agent-equipment/schemas/captured-state-v1.schema.json
home/dot_local/lib/agent-equipment/schemas/plan-action-set-v1.schema.json
home/dot_local/lib/agent-equipment/schemas/adapter-contract-v1.schema.json
home/dot_local/lib/agent-equipment/agent_equipment/__init__.py
home/dot_local/lib/agent-equipment/agent_equipment/model.py
home/dot_local/lib/agent-equipment/agent_equipment/canonical.py
home/dot_local/lib/agent-equipment/agent_equipment/validator.py
home/dot_local/lib/agent-equipment/agent_equipment/resolver.py
home/dot_local/lib/agent-equipment/agent_equipment/inventory.py
home/dot_local/lib/agent-equipment/agent_equipment/checkpoint.py
home/dot_local/lib/agent-equipment/agent_equipment/executor.py
home/dot_local/lib/agent-equipment/agent_equipment/secrets.py
home/dot_local/lib/agent-equipment/agent_equipment/adapters/base.py
home/dot_local/lib/agent-equipment/agent_equipment/adapters/standalone_skills.py
home/dot_local/lib/agent-equipment/agent_equipment/adapters/claude_projection.py
home/dot_local/lib/agent-equipment/agent_equipment/adapters/claude_plugin.py
home/dot_local/lib/agent-equipment/agent_equipment/adapters/claude_mcp.py
home/dot_local/lib/agent-equipment/agent_equipment/adapters/codex_plugin.py
home/dot_local/lib/agent-equipment/agent_equipment/adapters/codex_skill_policy.py
home/dot_local/lib/agent-equipment/agent_equipment/adapters/codex_mcp.py
home/dot_local/lib/agent-equipment/agent_equipment/adapters/cursor_plugin.py
home/dot_local/lib/agent-equipment/agent_equipment/adapters/cursor_mcp.py
home/run_onchange_after_reconcile-agent-equipment.zsh.tmpl
tests/agent_equipment/
```

Chezmoi installs the package verbatim below
`~/.local/lib/agent-equipment/agent_equipment/`; the launcher resolves that
directory relative to its own installed `~/.local/bin` path and prepends only
that exact directory to its private Python import path. It never imports from a
source checkout or the process working directory. The five authoritative
Schemas install beside the package under `~/.local/lib/agent-equipment/schemas/`;
the validator reads those exact bytes before semantic validation, verifies
their compiled-in version and digest manifest, and fails closed on a missing or
changed Schema. The installed CLI reads the catalog and lock from
`~/.config/agent-equipment/`. Checkpoints live under
`~/.local/state/agent-equipment/checkpoints/`; neither checkpoints nor
observed inventory are chezmoi-managed. The checked-in lock is regenerated only
by `agent-equipment update` and reviewed like source. The chezmoi script invokes
only `agent-equipment apply`. Its template input includes a canonical manifest
of every installed package file path and content digest, the launcher digest,
and the rendered catalog and lock digests, so any implementation-only change
reruns reconciliation. The same complete installed-implementation manifest
digest is bound alongside the distinct candidate commit or artifact identity in
plans, action sets, captures, checkpoints, receipts, and authorization evidence.
It never performs source discovery or updates implicitly.

Keep the production package free of third-party runtime dependencies. Use the
standard library for JSON, hashing, filesystem inspection, subprocesses, and
durable writes. Invoke native managers as argument arrays, never through a
shell. Parse their documented JSON or stable file inputs and fail closed when a
required capability is unavailable.

## Public seams

The resolver has one side-effect-free entry point:

```python
resolve(command, catalog, lock, inventory, capabilities) -> Resolution
```

The executor has one mutating entry point:

```python
execute(validated_plan, adapters, checkpoint_store) -> ApplyReport
```

Every adapter implements:

```python
capabilities() -> tuple[CapabilityRecord, ...] | AdapterError
observe(request: ObserveRequest) -> RuntimeObservation
apply(action: PlannedAction, expected_pre_state: StateDigest) -> MutationReceipt
verify(request: ObserveRequest) -> RuntimeObservation
compensate(
    action: PlannedAction,
    expected_post_state: StateDigest,
    captured_pre_state: CapturedState,
) -> MutationReceipt
```

`AdapterError` is the closed common error object defined by
`adapter-contract-v1.schema.json`; capability discovery is all-or-error and
returns no partial capability tuple.

Adapters receive resolved complete route records. They do not choose providers,
merge coverage defaults, rewrite outcomes, resolve secret values into returned
objects, or mutate a surface outside the action. Before adapter invocation,
validate every input shape, construct the `ApplySequence` authority context from
the trusted plan, capture, and prepared checkpoint, and enforce its same
pre-mutation bindings. After receipt and verification, the pure cross-record
validator accepts only the complete success proof; it re-derives exact surfaces,
proves complete desired component state against the route and capability, and
binds the receipt and verification back to the capture and authority context.

## Dependency-ordered implementation backlog

Each step is a clean checkpoint and an independently reviewable pull request.
Later steps do not begin until the named evidence passes.

### 1. Promote the design validator into the production model

- Implement immutable typed model objects, canonical JSON, schema validation,
  template expansion, and every cross-field invariant.
- Make the catalog digest and lock binding stable test vectors.
- Promote the checked-in proposed catalog only through a reviewed `adopt` or
  production-source change; its `.proposed.json` name conveys zero live
  authority.
- Reject all malformed input before native capability discovery.
- Evidence: all `CAT-*` fixtures in `ACCEPTANCE.md`, static type checking, and
  mutation testing of each cross-field guard.

### 2. Implement read-only inventory and the pure resolver

- Implement adapter capability and observation records without mutation.
- Preserve exactly one complete coverage record per identity and harness.
- Apply selective component controls before forming activation groups.
- Keep active `equipment_identities` separate from exact
  `controlled_equipment_identities`; a disabled controlled `no_provider`
  identity remains inactive while still naming an authorized control surface.
- Produce stable diagnostics, provider selections, operation matrices, and
  owned overlay proposals. Derive a complete action-dependency graph, reject
  missing dependencies, orphans, and cycles, then topologically order it with
  lexical tie-breaks only among ready actions.
- Make every losing-route retirement depend on verification of the complete
  preferred winner activation group. Projector readiness precedes the Matt
  winner; verified Matt installation and enablement precede each identified
  Claude-link retirement; final coverage verification follows all route changes.
- Represent projector readiness, winner activation, and final coverage as
  closed read-only verification nodes in the plan graph. Bind their canonical
  definitions and edges into `plan_digest`; persist fresh predicate evidence in
  the run journal without creating mutation checkpoints. Dependent actions may
  start only after that evidence verifies, and reverse compensation skips these
  read-only nodes.
- Evidence: `RES-*`, `CMD-01`, and repeated-run golden digests.

### 3. Implement authored proposal commands

- `import` emits unowned observation proposals.
- `adopt` requires an exact imported observation and emits catalog ownership
  changes only.
- `update` resolves immutable revisions and reviewed native-rolling baselines
  into a proposed lock only.
- None opens a runtime checkpoint store or invokes a mutating adapter method.
- Evidence: `CMD-02` through `CMD-04` with byte-identical runtime snapshots.

### 4. Implement checkpointing before any production adapter mutation

- After complete-plan validation, emit its exact closed
  `agent-equipment-plan-action-set/v1` projection. Validate the separately
  produced action set and capture with their checked-in JSON Schemas, then run
  `agent_equipment_captured_state.py --authoritative-plan-actions SET
  --expected-candidate-identity CANDIDATE
  --expected-implementation-manifest-digest MANIFEST_DIGEST CAPTURE`. The
  candidate-independent launcher supplies those last two values from the
  implementation it actually verified; neither validator input may be derived
  from the action set or capture under review.
  The public API and CLI perform both checked-in schema gates before semantics;
  the CLI also rejects duplicate JSON object keys and non-JSON numeric
  constants before either gate;
  CI additionally uses the pinned independent schema checker to validate the
  schemas and fixtures themselves. None of these gates substitutes for another:
  Schema owns closed serialized shape; the plan validator owns complete and
  exact membership of every automated action in the authoritative plan; and
  the semantic validator owns canonical action/set digests, captured bindings,
  logical surface identities, references, ownership, route membership, native
  restore coherence, and canonical capability bindings and digest.
- Project the complete automated `PlannedAction`, not an install-only subset.
  Preserve catalog, lock, and plan digests; route identity and digest; the exact
  closed provider target; active `equipment_identities`; distinct
  `controlled_equipment_identities`; activation group; exact write-surface
  scope; closed physical write targets and derived target identities; operation
  and disposition; desired state and digest; executor
  capability, manager, adapter, and harness bindings; secret-reference names
  without values; compare/checkpoint preconditions; verification-only read
  dependencies; and compensation. Derive write authority from the union of
  active and controlled equipment without treating disabled controlled
  equipment as active coverage.
- Give every authoritative automated action exactly one captured provider-route
  owner and every reconciler-owned captured surface exactly one authoritative
  action owner. An action may write only the captured reconciler-owned surfaces
  named by its exact `surface_scope`. Operator-owned routes cannot reference an
  automated action, and operator-owned surfaces cannot carry native inverse
  compensation.
- Permit native remove compensation only when the same authoritative install
  action owns the exact plugin-installation physical target and its captured
  write binding. An install action scoped to another surface is not sufficient.
- Keep adapter `surface_scope` as logical identities. Project one closed
  secret-free physical target descriptor per actual write, derive its
  `target_identity` over canonical kind/equipment/locator coordinates, and map
  each target exactly once to one capture-local surface ID. Require exact kind,
  locator, equipment, route, route-slot, and reconciler-owner equality. Require
  equipment identity on MCP and plugin selections; omit it only for the
  route-wide legacy projector.
- Mirror the catalog provider variants in the projection, including
  `secret_profile_reference` arguments and the hardened static
  credential-free HTTPS grammar for HTTP MCPs. Match provider-consumed secret
  reference names exactly to the action's declared names; persist no resolved
  values. Treat destination allow/deny policy as a separate executor
  capability so reviewed private MCP endpoints remain representable.
- Give every mutable routed surface exactly one reference in the owning route's
  kind-specific slot. Installation and enablement are singleton slots;
  projector, MCP-selection, plugin-selection, and Claude-skill slots close the
  remaining mutable surface kinds. `canonical_skill_dependencies` is a separate
  verification-only read slot. Reject duplicate identifiers, duplicate
  canonical logical identities, orphan surfaces, duplicate references, and
  wrong-kind or wrong-route references. Canonical logical surface identity is
  kind plus route plus canonical locator plus equipment identity where present.
- Also enforce mutable physical identity independently as kind plus canonical
  locator. Route or equipment relabeling cannot create a second capture,
  mutation owner, or recovery record for one physical surface. Shared
  verification-only observations remain explicitly nonmutable.
- Accept Agent and Claude skill locators only as direct root children with a
  non-empty basename other than `.` or `..`; reject NUL, slash, backslash, and
  platform separators in the basename. Execution retains independent
  filesystem containment checks.
- The semantic API requires the action set as a second argument. It accepts no
  captured-state-only mode and does not claim to authenticate the source of
  that input. The caller must supply the independently validated projection;
  constructing or changing it from captured route references is invalid.
- For every routed standalone or projected skill, capture exactly one canonical
  `~/.agents/skills` counterpart with forbidden mutation and verification-only
  recovery. Every Claude projection action binds its write surface to that
  canonical read surface, matching route, equipment identity, canonical target
  locator, and basename one-to-one.
- Permit native remove compensation only for a forward install from captured
  absence whose route reference resolves one-to-one by canonically derived
  identity and recomputed action digest to that supplied set. The identity
  binds plan digest, ordinal, route, operation, and desired-state digest. The
  capture also binds the canonical action-set digest. Matching only the plan
  digest, or editing both a route reference and the captured digest, is
  insufficient against the separately sealed set.
- Bind a native action's route digest and exact provider target to the captured
  installation locator: manager, native plugin identity, and scope must match
  exactly. Bind a native remove inverse's `expected_pre_state_digest` exactly
  to the action's distinct `expected_post_state_digest`, the canonical digest
  of the complete normalized forward-post state. Keep `desired_state_digest`
  as the target-fragment digest.
- Cross-check observation and recovery classes. An absent mutable entry or
  selection uses absence-noop recovery; a present Claude entry or
  secret-redacted selection requires private recovery material; and a present
  structured surface requires a structured or private snapshot.
- Use canonical, compare-and-swap writes to a same-filesystem temporary file,
  fsync the file, atomically rename, then fsync the parent directory.
- Implement `prepared`, `completed`, `compensating`, `compensated`, and terminal
  `compensation_blocked` states,
  plus a durable `prepared` invocation intent that advances from `not_started`
  to `started` after compare and before the adapter call. A failed intent write
  forbids invocation; only `started` can attribute expected post-state to this
  run. Preserve immutable plan bindings, audit-before-retry, and reverse
  compensation. A restore-guard mismatch persists `compensation_blocked`,
  moves the run to `needs_operator`, and can never report recovered.
- Make current-state comparison an executor precondition rather than optional
  adapter behavior.
- Construct one closed `ApplySequence` authority context before invocation and
  retain it unchanged through receipt and post-state verification. Validate the
  complete success proof before advancing a checkpoint to `completed` or
  `compensated`; standalone records and failed receipts never satisfy that gate.
- Recompute the action identity from the plan digest, ordinal, route identity,
  operation, and desired-state digest using the plan-action-set formula.
  Recompute every observation digest from its embedded closed normalized-state
  payload. For compensation, require the immediate pre-state guard to equal the
  full forward-post state digest and retain `captured_pre_state_digest` as the
  distinct full restore target.
- Carry active activation membership and controlled component identities as
  separate exact sets. Derive surface authority from their union; a disabled
  `intentional_omission` / `no_provider` duplicate may be controlled without
  becoming active coverage.
- Resolve the authority context's plan and checkpoint digests against trusted
  local artifacts. Cross-record equality proves binding, not artifact existence
  or checkpoint durability.
- Evidence: every `CHK-*` fixture against a state-machine fake adapter.

### 5. Implement standalone-skill and projection adapters

- Fetch immutable artifacts into staging, verify commit and content digest,
  then replace only an adopted canonical entry.
- Inspect existing entries with `lstat`; preserve file type, metadata, link
  text, resolved target, and broken-link state. Never follow an existing link
  for a write.
- Project only catalog-selected Claude links. Cursor consumes the canonical
  Agent Skills root directly; create no Cursor projection.
- Add exact-path Codex standalone disable entries only when a preferred Codex
  plugin route wins.
- Evidence: `CON-01` through `CON-04` and `CON-10` for these surfaces, plus the
  matching checkpoint matrix.

### 6. Implement native plugin adapters

- Use Claude's CLI for supported install, enable, and disable operations;
  preserve the official Matt route as `native_rolling` unless an independently
  fetched, digest-verified artifact route is selected. Do not expose general
  native-rolling removal. Compensation may uninstall only the exact instance
  installed by this run from confirmed captured absence while its complete
  expected post-state still matches; it never claims prior-artifact restoration.
- Use Codex's documented/native CLI and stable config for plugin and selective
  plugin-MCP policy. Do not infer cache restoration.
- Keep Cursor plugin mutation operator-owned until a stable supported install
  interface exists. Observe through supported UI or CLI only; never edit its
  opaque database or cache.
- Record plugin equipment coverage before selecting individual components.
- Evidence: `LIVE-01` through `LIVE-04`, `CMD-06`, and adapter checkpoint
  matrices.

### 7. Implement MCP adapters and secret boundary

- Move only accepted MCP keys from the existing Claude JSON, Codex TOML, and
  Cursor JSON overlays behind adapter-owned narrow merges.
- Preserve the existing `secret-exec` child-process boundary. Catalog, lock,
  plan, logs, receipts, diagnostics, and diffs carry secret-reference names
  only.
- Resolve same-name direct and plugin-provided MCPs through explicit provider
  selections and supported component controls; never infer precedence.
- Evidence: `RES-04`, `RES-05`, `LIVE-05`, and recursive canary scans.

### 8. Integrate apply without migrating the live machine

- Validate the complete plan and every compensation before opening the first
  checkpoint.
- Require a closed, cycle-free dependency graph and execute only its
  deterministic topological order. Reverse compensation uses the reverse
  topological order.
- Implement all accepted entries, non-automated reporting, idempotent repair,
  provider switching, manager-driven drift, and owned retirement in disposable
  homes.
- Run the complete automated acceptance matrix on macOS and Linux where the
  adapter exists. Record unsupported harness behavior explicitly.
- Evidence: all `CMD-*`, `CON-*`, and `CHK-*` requirements.

### 9. Request exact runtime-migration authorization

- Refresh upstream source manifests, live inventory, harness versions, plugin
  capabilities, symlink set, and manager locks.
- Run `agent-equipment audit`, acquire the apply lease, capture every affected
  route and surface, emit the independently validated plan-action projection,
  validate both Schemas then cross-record semantics, seal the action set and
  capture, and resolve again against them. Produce the exact candidate
  implementation identity and installed-manifest digest, catalog digest, lock
  digest, one immutable migration-plan digest, plan-action-set digest,
  capability-set digest, captured-state identity and digest, expected action
  list, compensation list, and rollback command.
- Ask for authorization naming that complete candidate, catalog, lock, plan,
  plan-action-set, capability-set, and captured-state identity/digest tuple.
  General approval of this architecture is not authorization to execute it.
  After authorization and before any action checkpoint, recompute the installed
  manifest and compare it plus all affected live state and bound
  manager/capability evidence with the authorized sealed capture. Any mismatch
  requires recapture, resealing, re-resolution, and new authorization; mutate
  nothing.

### 10. Execute and verify the migration

- Follow `MIGRATION.md` without substitution or scope expansion.
- Replace the blanket projector first; install and enable the official plugin;
  verify its complete active Matt activation group; only then remove positively
  identified, catalog-owned Matt Claude links while keeping every standalone
  target untouched; then reconcile MCP and plugin selections.
- Run all `MIG-*` and applicable `LIVE-*` checks, archive the evidence bundle,
  and retain only successfully verified desired state.

## Retained and retired source map

### Retained now

| Path | Disposition |
| --- | --- |
| `home/run_after_sync-global-agent-skills-to-claude.zsh` | Retain unchanged until the production catalog projector passes fresh-home, no-op, and rollback gates. It remains the live owner. |
| `home/dot_claude/skills/symlink_*` | Retain until each projection is explicitly adopted into the catalog and both owners cannot run concurrently. |
| `home/modify_private_dot_claude.json.tmpl` | Retain as live Claude MCP owner until accepted keys move atomically to the Claude MCP adapter. |
| `home/dot_claude/modify_private_settings.json.tmpl` | Retain as live Claude plugin-selection owner until the Claude plugin adapter owns the same exact keys. |
| `home/dot_codex/modify_private_config.toml.tmpl` | Retain unrelated preferences and runtime-field preservation. Later remove only MCP and skill-policy branches transferred to adapters. |
| `home/dot_config/modify_private_mcp-config.json.tmpl` | Retain as live Cursor MCP owner until accepted keys move atomically to the Cursor MCP adapter. |
| Native manager locks | Retain outside chezmoi authority as import and provenance evidence. |
| Harness caches, credentials, databases, timestamps, and usage state | Retain as harness-owned runtime state; never add to chezmoi. |

### Retired by this design pull request

| Path | Replacement |
| --- | --- |
| `.scratch/global-agent-equipment/CONTEXT.md` | `docs/agent-equipment/CONTEXT.md` |
| `.scratch/global-agent-equipment/map.md` | This handoff plus Issues #44–#61 and the durable architecture documents |

### Retired only during the separately authorized migration

| Path or behavior | Retirement gate |
| --- | --- |
| `home/run_after_sync-global-agent-skills-to-claude.zsh` | Catalog projector is installed first and passes `CON-01`, `CON-02`, `MIG-01`, and rollback injection. |
| Catalog-adopted `home/dot_claude/skills/symlink_*` entries | Generated projection owns the exact same link and dual ownership is removed in one reviewed change. |
| MCP/plugin branches in existing modify overlays | Corresponding adapter passes fresh-home, narrow-diff, compensation, and secret-canary tests. |
| The 21 observed Matt symlinks in `~/.claude/skills` | Exact pre-state still matches, catalog marks only those projections owned and losing, the new projector is active, the official plugin is installed and enabled with its complete active Matt activation group verified, and plugin installation can be compensated after every removed link is restorable. |

No retirement rule deletes an unmanaged observation or a canonical
`~/.agents/skills` entry.

## Publication plan

1. Merge this design slice with schemas, tests, dated research, prototype
   findings, inventory, migration contract, acceptance matrix, and handoff. It
   performs no runtime migration.
2. Keep the disposable prototype on its explicitly named branch and link its
   commit from Issue #57. Do not merge its UI or throwaway resolver.
3. Close Issues #55–#61 only after the design pull request is merged and every
   issue checklist points to merged evidence.
4. Publish production steps 1–8 as dependency-ordered pull requests with the
   acceptance evidence named above. Do not combine implementation with live
   adoption merely to shorten the stack.
5. Open a separate migration authorization containing the exact candidate
   implementation identity and installed-manifest digest, refreshed inventory,
   immutable plan, plan-action-set, capability-set, and already sealed
   captured-state identity/digest, exact live mutations, rollback command, and
   review receipts. Require an exact post-authorization implementation and live
   comparison before the first checkpoint; drift requires a new capture and
   authorization.

## Stop conditions

Stop before mutation when an identity is unresolved; a coverage record or
route is incomplete; an overlap lacks an exact exception; a required
capability is unknown; an operator-owned route exposes automated mutation; an
automated mutation lacks pre-state compensation; the catalog-lock binding is
stale; a secret value enters generated state; current state differs from
captured or expected state; the capability-set digest or a route binding is
invalid; the post-authorization comparison differs from the sealed capture; a
checkpoint cannot be made durable; or the exact runtime plan, plan-action-set,
and captured-state digests lack authorization.
