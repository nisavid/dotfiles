# Global agent equipment implementation handoff

This handoff closes the design route in Issues #44–#61. It is the work
contract for an ordinary production implementation. It does not authorize a
runtime migration, a live plugin change, or a rewrite of any harness-owned
state.

## Fixed destination

Build one CPython 3.12+ controller, entered through chezmoi for read-only audit
and through a separately authorized operator invocation for apply, with:

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
| `docs/agent-equipment/acceptance-evidence-v1.schema.json` | Closed expected-case, candidate evidence, and post-run attestation contract |
| `docs/agent-equipment/execution-authority-v1.schema.json` | Closed apply authorization, release archive manifest, and terminal receipt contract |
| `docs/agent-equipment/initial-catalog.proposed.json` | Schema-valid initial desired-state proposal; no live authority |
| `docs/agent-equipment/initial-lock.proposed.json` | Generated 132-record lock bound to the proposed catalog digest |
| `docs/agent-equipment/INVENTORY.md` and `initial-inventory.json` | Dated, secret-free read-only observation and initial classification |
| `docs/agent-equipment/PROTOTYPE_FINDINGS.md` | Disposable-prototype evidence and resulting design constraints |
| `docs/agent-equipment/MIGRATION.md` | Separately authorized migration and rollback contract |
| `docs/agent-equipment/ACCEPTANCE.md` | Requirement-to-fixture production release gate |
| `scripts/agent_equipment_design.py` and `tests/test_agent_equipment_design.py` | Executable schema, expansion, and fail-closed design model |
| `scripts/agent_equipment_json_schema.py` and `tests/test_agent_equipment_json_schema.py` | Shared strict local-schema gate used by every public design, adapter, and capture validator |
| `scripts/agent_equipment_acceptance_model.py` and `tests/test_agent_equipment_acceptance.py` | Disposable fake-manager convergence, checkpoint, compensation, and migration-boundary evidence |
| `scripts/agent_equipment_acceptance_evidence.py` and `tests/test_agent_equipment_acceptance_evidence.py` | Design-only three-document release gate, adversarial binding checks, and strict CLI fixtures |
| `tests/test_agent_equipment_deployment_contract.py` | Design-only apply-authorization, release-receipt, deployment-separation, and runtime-gate contract vectors |
| `scripts/agent_equipment_captured_state.py` and `tests/test_agent_equipment_captured_state.py` | Captured-state capability/action-set digests and fail-closed cross-record semantic validation against separately supplied plan actions |
| `scripts/agent_equipment_adapter_contract.py`, `tests/test_agent_equipment_adapter_contract.py`, and `tests/fixtures/agent-equipment/schema/*-adapter-*.json` | Cross-record semantic binding validator plus executable positive and fail-closed adapter-contract examples |

Acceptance-evidence tests synthesize the compact expected-case manifest and its
full child projection in temporary directories. This avoids checking in one
dated 74-aggregate, plan-sized generated bundle as if it were release evidence.
CI independently checks the Schema metaschema, while the public API and CLI
tests pass all three synthesized documents through the checked-in Schema gate.

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

The executable acceptance-evidence validator is also design-only. It validates
closed files against independently supplied trust inputs, but it neither emits
the production expected-case projection nor authenticates a plan. It never
publishes a release or grants runtime-migration authority.

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
home/dot_local/lib/agent-equipment/schemas/acceptance-evidence-v1.schema.json
home/dot_local/lib/agent-equipment/schemas/execution-authority-v1.schema.json
home/dot_local/lib/agent-equipment/agent_equipment/__init__.py
home/dot_local/lib/agent-equipment/agent_equipment/model.py
home/dot_local/lib/agent-equipment/agent_equipment/canonical.py
home/dot_local/lib/agent-equipment/agent_equipment/validator.py
home/dot_local/lib/agent-equipment/agent_equipment/resolver.py
home/dot_local/lib/agent-equipment/agent_equipment/inventory.py
home/dot_local/lib/agent-equipment/agent_equipment/checkpoint.py
home/dot_local/lib/agent-equipment/agent_equipment/authorization.py
home/dot_local/lib/agent-equipment/agent_equipment/executor.py
home/dot_local/lib/agent-equipment/agent_equipment/secrets.py
home/dot_local/lib/agent-equipment/agent_equipment/evidence.py
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
home/run_onchange_after_audit-agent-equipment.zsh.tmpl
tests/agent_equipment/
```

The candidate-independent release authority is a different protected source and
deployment unit. Its exact source path is
`agent-equipment-release-authority/src/executable_agent-equipment-release`; that
path is not in this dotfiles repository or any evaluated controller candidate.
An operator-owned installation step places its verified bytes at
`/usr/local/libexec/agent-equipment-release/v1/agent-equipment-release` and its
independent Schema/manifest set under
`/usr/local/share/agent-equipment-release/v1/`. Both installed trees are
root-owned and nonwritable by the controller user. They are excluded from the
controller's installed-implementation manifest. The release authority has its
own identity, manifest digest, invocation policy, and create-only archive
capability; the candidate has none of those capabilities.

Chezmoi installs the package verbatim below
`~/.local/lib/agent-equipment/agent_equipment/`; the launcher resolves that
directory relative to its own installed `~/.local/bin` path and prepends only
that exact directory to its private Python import path. It never imports from a
source checkout or the process working directory. The seven authoritative
Schemas install beside the package under `~/.local/lib/agent-equipment/schemas/`;
the validator reads those exact bytes before semantic validation, verifies
their compiled-in version and digest manifest, and fails closed on a missing or
changed Schema. The installed wrapper first gates on CPython 3.12 or newer,
before importing the package or reading runtime state. The complete installed-
implementation manifest binds `cpython:<major>.<minor>.<micro>` and the selected
interpreter executable digest alongside the launcher, package, and Schema bytes.
A missing, older, changed, or non-CPython runtime exits before the first action
checkpoint with no adapter call. A future independently installed pinned
interpreter is acceptable only when all of its installed bytes enter that same
manifest. The installed CLI reads the catalog and lock from
`~/.config/agent-equipment/`. Checkpoints live under
`~/.local/state/agent-equipment/checkpoints/`; neither checkpoints nor
observed inventory are chezmoi-managed. The checked-in lock is regenerated only
by `agent-equipment update` and reviewed like source. The chezmoi `run_onchange`
script invokes only `agent-equipment audit`; it accepts no authorization input
and cannot invoke apply, open the authorization ledger, or create an action
checkpoint. Its template input includes a canonical manifest
of every installed package file path and content digest, the launcher digest,
and the rendered catalog and lock digests, so any implementation-only change
reruns the read-only audit. The same complete installed-implementation manifest
digest is bound alongside the distinct candidate commit or artifact identity in
plans, action sets, captures, checkpoints, receipts, and authorization evidence.
It never performs source discovery, updates, or runtime reconciliation
implicitly.

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
execute(
    validated_plan,
    apply_authorization_bytes,
    adapters,
    checkpoint_store,
    authorization_ledger,
    *,
    trusted_apply_authorization_digest,
    trusted_operator_review_package_digest,
    trusted_clock,
) -> ApplyReport
```

The operator invocation supplies the exact authorization file from
`~/.local/state/agent-equipment/authorization-inbox/<authorization_identity>.json`
and its separately authenticated `trusted_apply_authorization_digest`. The CLI
does not discover a newest authorization, infer its digest, or fall back to an
environment/config value. Before the first action checkpoint it strictly parses
and validates the record, checks the complete binding tuple and UTC window,
performs the final authorized live comparison, and only then durably claims its
execution nonce under
`~/.local/state/agent-equipment/authorization-ledger/`. Exclusive creation plus
file and parent-directory fsync make the claim one-time. A claimed, expired,
misbound, or unpersistable authorization performs zero adapter calls. Recovery
may reopen only the same claimed run and surviving checkpoints; a new action or
run requires a fresh authorization and nonce.

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

The production candidate evidence writer has two nonmutating seams:

```python
project_expected_acceptance_cases(
    validated_plan,
    sealed_capture,
    static_requirement_registry,
    route_capability_bindings,
) -> ExpectedCaseManifest

write_acceptance_evidence(
    expected_cases,
    child_results,
    harness_versions,
    manager_versions,
) -> AcceptanceEvidenceBundle
```

The first projection includes every sealed automated action and every explicit
verification or mutating migration node. It never infers nodes from prose. The
second derives every aggregate from the complete child set and writes only to
an operator-selected artifact directory. It cannot write release attestations.

A separately authorized release-attestation writer owns the post-run authority
record:

```python
write_release_attestation(
    evidence_bundle_bytes,
    authorized_expected_case_manifest_digest,
    authenticated_attestors,
) -> AcceptanceAttestation
```

It binds the exact bundle bytes, candidate/artifact tuple, and the canonical
automated-runner, live-operator, and release-reviewer records. Each attestor
time follows every bound result and live sign-off; the live-operator identity
equals every passing live signer's identity. Attestor versions identify the
runner or signing-policy implementation used for that role.

The pure release validator and nonmutating release command are separate:

```python
validate_acceptance_evidence(
    bundle,
    expected_case_manifest,
    attestation_manifest,
    *,
    expected_candidate_identity,
    expected_implementation_manifest_digest,
    expected_case_manifest_digest,
    expected_attestation_manifest_digest,
    expected_apply_authorization_identity,
    expected_apply_authorization_digest,
    expected_execution_nonce,
    expected_run_identity,
) -> tuple[Diagnostic, ...]

release_candidate(
    apply_authorization_bytes,
    expected_case_manifest_bytes,
    evidence_bundle_bytes,
    attestation_manifest_bytes,
    *,
    trusted_apply_authorization_digest,
    trusted_release_launcher_identity,
    trusted_release_launcher_manifest_digest,
    trusted_candidate_identity,
    trusted_implementation_manifest_digest,
    authorized_expected_case_manifest_digest,
    authorized_attestation_manifest_digest,
    trusted_execution_binding,
    artifact_store,
) -> ReleaseReceipt
```

The candidate-independent release launcher obtains the expected-case manifest
digest from the exact trusted pre-mutation authorization and the attestation
digest from the separate post-run release authority. It first verifies its own
installed bytes against the independently supplied launcher identity and
manifest digest. The release command strictly parses all four exact byte inputs,
invokes the validator with the trusted digests, and refuses a release receipt on
any diagnostic. It hashes each exact input byte stream independently of its
semantic canonical digest, constructs the closed `ReleaseArchiveManifest`,
stages and fsyncs the authorization, three release documents, and archive
manifest, then commits generation `1` with a create-only
compare-and-swap rename. An existing identical generation is an idempotent read;
different existing bytes are a conflict. It emits a `ReleaseReceipt` only after
that archive commit is durable. Candidate code cannot call the authority's
receipt/archive capability, and a candidate-authored lookalike record is not a
receipt. The launcher does not call apply, adapters, native managers, or
migration recovery.

## Dependency-ordered implementation backlog

Each step is a clean checkpoint and an independently reviewable pull request.
Later steps do not begin until the named evidence passes.

### 1. Promote the design validator into the production model

- Add the CPython 3.12+ fail-before-import gate and bind the selected runtime
  identity and executable digest into the installed-implementation manifest.
  Prove an absent, older, changed, or non-CPython runtime reaches neither native
  observation nor the checkpoint store.
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
  into one proposed catalog-and-lock pair. Resolved route evidence in the
  catalog and the digest-bound lock advance atomically or neither does.
- None opens a runtime checkpoint store or invokes a mutating adapter method.
- Evidence: `CMD-02` through `CMD-04` with byte-identical runtime snapshots.

### 4. Implement checkpointing before any production adapter mutation

- Implement the closed `ApplyAuthorization` parser and semantic validator plus
  the durable authorization ledger. The public executor requires exact
  authorization bytes and the separately supplied
  `trusted_apply_authorization_digest` and trusted operator-review-package
  digest; validate the canonical identity, full
  tuple, command, UTC window, run, and nonce before the first action checkpoint.
  Claim the nonce with an exclusive, fsynced create. Test missing, extra,
  expired, not-yet-valid, replayed, cross-run, cross-plan, and persistence-fault
  cases for zero adapter calls and zero action checkpoints.
- After complete-plan validation, emit its exact closed
  `agent-equipment-plan-action-set/v1` projection. Validate the separately
  produced action set and capture with their checked-in JSON Schemas, then run
  `agent_equipment_captured_state.py --authoritative-plan-actions SET
  --expected-candidate-identity CANDIDATE
  --expected-implementation-manifest-digest MANIFEST_DIGEST CAPTURE`. The
  explicit operator apply invocation supplies those last two values from the
  implementation it actually verified; neither validator input may be derived
  from the action set or capture under review. The separate release launcher
  does not participate in apply or captured-state validation.
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
- Implement the production candidate evidence writer and pure acceptance-
  evidence validator. Project the complete static
  requirement registry, sealed plan-action identities, and explicit
  verification and mutating migration nodes into one digest-bound expected-case
  manifest. Emit exact child receipts, derive aggregates, and reject missing,
  extra, duplicate, foreign-bound, or incomplete evidence.
- Require every passing `LIVE-*` child to carry a live receipt and human
  sign-off. Require every route capability and manager-evidence binding to have
  a matching public manager-version receipt. Bind all three exact documents,
  require the canonical attestor set after the latest evidence time, and bind
  the live signer to the live-operator attestor. Keep opaque references,
  diagnostics, and archives secret-free.
- Run the complete automated acceptance matrix on macOS and Linux where the
  adapter exists. Record unsupported harness behavior explicitly.
- Evidence: all `CMD-*`, `CON-*`, and `CHK-*` requirements plus adversarial
  acceptance-evidence writer, validator, and release-command fixtures.

### 8a. Deploy the independent release authority

- In the separate protected `agent-equipment-release-authority` source, build
  the launcher without importing the candidate package or using its interpreter.
  Install its independently verified v1 executable and Schemas at the exact
  root-owned paths above. Supply its identity and manifest digest from the
  external release authority, never from candidate output.
- Give only that launcher the release archive capability. Implement strict
  validation of the authorization plus all three release documents, create-only
  compare-and-swap archival, idempotent retrieval of an identical generation,
  conflict rejection, the closed `ReleaseArchiveManifest` identity/digest
  formula over exact byte digests, and the closed `ReleaseReceipt` formula.
  Test that candidate-owned paths, candidate-minted receipts, skipped archive
  commits, and altered launcher bytes never satisfy release.
- Evidence: deployment ownership inspection, launcher-manifest verification,
  create-only archive concurrency/fault fixtures, and release-receipt vectors in
  `tests/test_agent_equipment_deployment_contract.py`.

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
  list, explicit verification and migration nodes, sealed expected-case manifest
  and digest, compensation list, and rollback command.
- Ask for authorization naming that complete candidate, catalog, lock, plan,
  plan-action-set, capability-set, captured-state identity/digest, expected-
  case-manifest digest, and operator-review-package digest tuple.
  The authority emits the closed `ApplyAuthorization`, including command, issuer,
  time window, run, and fresh execution nonce, then supplies its canonical
  `trusted_apply_authorization_digest` independently of the file. General
  approval of this architecture is not authorization to execute it. After
  authorization and before any action checkpoint, recompute the installed
  manifest and compare it plus all affected live state and bound
  manager/capability evidence with the authorized sealed capture. Any mismatch
  requires recapture, resealing, re-resolution, and new authorization; mutate
  nothing. Only after that exact comparison succeeds, durably claim the fresh
  nonce; a failed or existing claim stops before the first action checkpoint.

### 10. Execute and verify the migration

- Follow `MIGRATION.md` without substitution or scope expansion.
- Replace the blanket projector first; install and enable the official plugin;
  verify its complete active Matt activation group; only then remove positively
  identified, catalog-owned Matt Claude links while keeping every standalone
  target untouched; then reconcile MCP and plugin selections.
- Run all exact expected `MIG-*` and applicable `LIVE-*` child cases, write the
  evidence bundle, obtain a separate post-run attestation and its externally
  trusted digest, and run the release gate against both authorized manifest
  digests. Archive the exact expected-case manifest, bundle, attestation, and
  release receipt from the independently trusted launcher after its create-only
  archive commit; retain only successfully verified desired state.

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
4. Publish production steps 1–8 as dependency-ordered controller pull requests
   with the acceptance evidence named above. Independently deploy and verify
   step 8a from the protected release-authority source before any candidate can
   receive a release receipt. Do not combine implementation with live adoption
   merely to shorten the stack.
5. Open a separate closed `ApplyAuthorization` containing the exact candidate
   implementation identity and installed-manifest digest, refreshed inventory,
   immutable plan, plan-action-set, capability-set, and already sealed
   captured-state identity/digest, sealed expected-case manifest and digest,
   issuer, validity window, run, and fresh execution nonce. Bind the exact live
   mutations, rollback command/actions, and review receipts transitively through
   the closed `operator_review_package_digest`; do not embed those documents as
   open authorization fields. Supply its
   `trusted_apply_authorization_digest` outside the record. Require an exact post-
   authorization implementation and live comparison before the first action
   checkpoint; drift or nonce reuse requires a new capture and authorization.

## Stop conditions

Stop before mutation when an identity is unresolved; a coverage record or
route is incomplete; an overlap lacks an exact exception; a required
capability is unknown; an operator-owned route exposes automated mutation; an
automated mutation lacks pre-state compensation; the catalog-lock binding is
stale; a secret value enters generated state; current state differs from
captured or expected state; the capability-set digest or a route binding is
invalid; the post-authorization comparison differs from the sealed capture; a
checkpoint cannot be made durable; CPython 3.12 or the manifest-bound runtime is
unavailable; the closed authorization is absent, expired, not yet valid,
misbound, replayed, or cannot be claimed durably; its canonical digest differs
from `trusted_apply_authorization_digest`; or the exact runtime plan, plan-
action-set, captured-state, and expected-case-manifest digests lack
authorization.

Stop before release when the external launcher's identity or installed-manifest
digest differs from its trusted input; the exact apply authorization or
attestation digest lacks independent authorization; any release document or
binding differs; an attestor predates a bound result or live sign-off; the
canonical live operator differs from a passing live signer; any required child
or aggregate does not pass; or the create-only archive commit is absent or
conflicts. Candidate output never overrides a stop.
