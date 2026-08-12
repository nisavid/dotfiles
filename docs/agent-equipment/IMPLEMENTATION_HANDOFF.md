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
| `docs/agent-equipment/adapter-contract-v1.schema.json` | Closed capability, request, observation, action, and receipt serialization contract |
| `docs/agent-equipment/initial-catalog.proposed.json` | Schema-valid initial desired-state proposal; no live authority |
| `docs/agent-equipment/initial-lock.proposed.json` | Generated 132-record lock bound to the proposed catalog digest |
| `docs/agent-equipment/INVENTORY.md` and `initial-inventory.json` | Dated, secret-free read-only observation and initial classification |
| `docs/agent-equipment/PROTOTYPE_FINDINGS.md` | Disposable-prototype evidence and resulting design constraints |
| `docs/agent-equipment/MIGRATION.md` | Separately authorized migration and rollback contract |
| `docs/agent-equipment/ACCEPTANCE.md` | Requirement-to-fixture production release gate |
| `scripts/agent_equipment_design.py` and `tests/test_agent_equipment_design.py` | Executable schema, expansion, and fail-closed design model |
| `scripts/agent_equipment_acceptance_model.py` and `tests/test_agent_equipment_acceptance.py` | Disposable fake-manager convergence, checkpoint, compensation, and migration-boundary evidence |
| `tests/test_agent_equipment_adapter_contract.py` and `tests/fixtures/agent-equipment/schema/*-adapter-*.json` | Executable positive and fail-closed adapter-contract examples |

Research notes are dated evidence, not desired state. Native locks, runtime
files, caches, credentials, application databases, and manager timestamps are
observations, never competing authorities.

The executable design model has no adapters, checkpoint store, or command that
can mutate runtime state. Its `mutation_plan` is a deterministic grouping of
declared automated operations used to prove all-or-nothing validation; it is
not a state-diff plan and must not be promoted as the production resolver.

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
scripts/agent_equipment/__init__.py
scripts/agent_equipment/model.py
scripts/agent_equipment/canonical.py
scripts/agent_equipment/validator.py
scripts/agent_equipment/resolver.py
scripts/agent_equipment/inventory.py
scripts/agent_equipment/checkpoint.py
scripts/agent_equipment/executor.py
scripts/agent_equipment/secrets.py
scripts/agent_equipment/adapters/base.py
scripts/agent_equipment/adapters/standalone_skills.py
scripts/agent_equipment/adapters/claude_projection.py
scripts/agent_equipment/adapters/claude_plugin.py
scripts/agent_equipment/adapters/claude_mcp.py
scripts/agent_equipment/adapters/codex_plugin.py
scripts/agent_equipment/adapters/codex_skill_policy.py
scripts/agent_equipment/adapters/codex_mcp.py
scripts/agent_equipment/adapters/cursor_plugin.py
scripts/agent_equipment/adapters/cursor_mcp.py
home/run_onchange_after_reconcile-agent-equipment.zsh.tmpl
tests/agent_equipment/
```

The installed CLI reads the catalog and lock from
`~/.config/agent-equipment/`. Checkpoints live under
`~/.local/state/agent-equipment/checkpoints/`; neither checkpoints nor
observed inventory are chezmoi-managed. The checked-in lock is regenerated only
by `agent-equipment update` and reviewed like source. The chezmoi script invokes
only `agent-equipment apply`; it hashes the rendered controller, catalog, and
lock so a change reruns reconciliation. It never performs source discovery or
updates implicitly.

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
objects, or mutate a surface outside the action.

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
- Produce stable diagnostics, provider selections, operation matrices, owned
  overlay proposals, and deterministic action order.
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

- Use canonical, compare-and-swap writes to a same-filesystem temporary file,
  fsync the file and parent directory, then atomically rename.
- Implement `prepared`, `completed`, `compensating`, and `compensated` states,
  immutable plan bindings, audit-before-retry, and reverse compensation.
- Make current-state comparison an executor precondition rather than optional
  adapter behavior.
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

- Use Claude's CLI for install, enable, disable, and uninstall; preserve the
  official Matt route as `native_rolling` unless an independently fetched,
  digest-verified artifact route is selected.
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
- Implement all accepted entries, non-automated reporting, idempotent repair,
  provider switching, manager-driven drift, and owned retirement in disposable
  homes.
- Run the complete automated acceptance matrix on macOS and Linux where the
  adapter exists. Record unsupported harness behavior explicitly.
- Evidence: all `CMD-*`, `CON-*`, and `CHK-*` requirements.

### 9. Request exact runtime-migration authorization

- Refresh upstream source manifests, live inventory, harness versions, plugin
  capabilities, symlink set, and manager locks.
- Run `agent-equipment audit` and produce one immutable migration-plan digest,
  captured-state digest, expected action list, compensation list, and rollback
  command.
- Ask for authorization naming those exact digests. General approval of this
  architecture is not authorization to execute them.

### 10. Execute and verify the migration

- Follow `MIGRATION.md` without substitution or scope expansion.
- Replace the blanket projector first; remove only positively identified,
  catalog-owned Matt Claude links; keep all standalone targets untouched;
  install and enable the official plugin; then reconcile MCP and plugin
  selections.
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
| The 21 observed Matt symlinks in `~/.claude/skills` | Exact pre-state still matches, catalog marks only those projections owned and losing, the new projector is active, and plugin installation can be compensated. |

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
5. Open a separate migration authorization containing the refreshed inventory,
   immutable plan and captured-state digests, exact live mutations, rollback
   command, and review receipts.

## Stop conditions

Stop before mutation when an identity is unresolved; a coverage record or
route is incomplete; an overlap lacks an exact exception; a required
capability is unknown; an operator-owned route exposes automated mutation; an
automated mutation lacks pre-state compensation; the catalog-lock binding is
stale; a secret value enters generated state; current state differs from
captured or expected state; a checkpoint cannot be made durable; or the exact
runtime plan lacks authorization.
