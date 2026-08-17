# Global agent equipment implementation handoff

This handoff closes the design route in Issues #44–#61. It is the work
contract for an ordinary production implementation. It does not authorize a
runtime migration, a live plugin change, or a rewrite of any harness-owned
state.

## Fixed destination

Build one CPython 3.12+ controller, entered through chezmoi for read-only status
and through a separately authorized operator invocation for apply, with:

- one versioned authored catalog and one generated resolved lock;
- one pure resolver that preserves the canonical harness coverage record from
  catalog through lock, inventory, plan, and adapter request;
- native-manager and narrow file-overlay adapters for global Claude Code,
  Codex, and Cursor;
- distinct `status`, `unmanaged`, `add`, `update`, and `apply` commands with the
  mutation boundaries in `ARCHITECTURE.md`; and
- a durable per-operation checkpoint executor with pre-state-restoring
  compensation and fresh status observation before retry.

The first complete production release inventories all observed skills,
plugins, plugin components, and MCPs. It actively reconciles only accepted
skill, plugin, and MCP entries. Hooks and other plugin components participate
in coverage and conflict resolution even when their standalone adapters remain
deferred.

## V1 foundation freeze

At this handoff boundary, no production adapter or execution-authority v1
record has been emitted or accepted. The required immutable-content correction
therefore remains eligible for the atomic pre-release exception.

Before any production producer emits or production consumer accepts a v1
adapter or execution-authority record, a contract correction may keep the v1
major only when normative prose, authoritative and installed Schemas, digest
pins, validators, and all fixtures change atomically. The first emitted or
accepted production record permanently freezes that major. Every later field,
enum, canonicalization, or semantic change requires the new major prescribed by
`ARCHITECTURE.md`; a partial current-major rollout is never permitted.

## Authoritative artifacts

| Artifact | Role |
| --- | --- |
| `docs/agent-equipment/CONTEXT.md` | Domain language and identity boundaries |
| `docs/agent-equipment/ARCHITECTURE.md` | Resolver, command, adapter, and executor contract |
| `docs/agent-equipment/catalog-v1.schema.json` | Authored catalog serialization contract |
| `docs/agent-equipment/lock-v1.schema.json` | Expanded lock serialization contract |
| `docs/agent-equipment/captured-state-v1.schema.json` | Pre-mutation runtime capture and recovery-evidence contract |
| `docs/agent-equipment/plan-action-set-v1.schema.json` | Closed projection of every independently validated automated plan action supplied to captured-state validation |
| `docs/agent-equipment/adapter-contract-v1.schema.json` | Closed capability, request, observation, action, and receipt serialization contract, including immutable-content evidence |
| `docs/agent-equipment/acceptance-evidence-v1.schema.json` | Closed expected-case, candidate evidence, and post-run attestation contract |
| `docs/agent-equipment/execution-authority-v1.schema.json` | Ten closed records with the same normalized immutable-content state: apply authorization, capture-observation-authority set, prepared-action-authority set, checkpoint-store snapshot, checkpoint set, compensation authorization and transition claim, run terminal, release archive manifest, and release receipt |
| `docs/agent-equipment/initial-catalog.proposed.json` | Schema-valid initial desired-state proposal; no live authority |
| `docs/agent-equipment/initial-lock.proposed.json` | Generated 132-record lock bound to the proposed catalog digest |
| `docs/agent-equipment/INVENTORY.md` and `initial-inventory.json` | Dated, secret-free read-only observation and initial classification |
| `docs/agent-equipment/PROTOTYPE_FINDINGS.md` | Disposable-prototype evidence and resulting design constraints |
| `docs/agent-equipment/MIGRATION.md` | Separately authorized migration and rollback contract |
| `docs/agent-equipment/ACCEPTANCE.md` | Requirement-to-fixture production release gate |
| `scripts/agent_equipment_design.py` and `tests/test_agent_equipment_design.py` | Executable schema, expansion, and fail-closed design model |
| `scripts/agent_equipment_json_schema.py` and `tests/test_agent_equipment_json_schema.py` | Shared strict local-schema gate used by every public design, adapter, and capture validator |
| `scripts/agent_equipment_acceptance_model.py` and `tests/test_agent_equipment_acceptance.py` | Disposable fake-manager convergence, checkpoint, compensation, and migration-boundary evidence |
| `scripts/agent_equipment_acceptance_evidence.py`, `tests/agent_equipment_acceptance_evidence_fixtures.py`, and `tests/test_agent_equipment_acceptance_evidence.py` | Design-only three-document release gate, shared deterministic evidence fixtures, adversarial binding checks, and strict CLI fixtures |
| `tests/test_agent_equipment_deployment_contract.py` | Design-only capture-observation/prepared-state authority, apply/compensation authorization, terminal/archive/receipt, deployment-separation, and runtime-gate contract vectors |
| `scripts/agent_equipment_captured_state.py` and `tests/test_agent_equipment_captured_state.py` | Captured-state capability/action-set digests and fail-closed cross-record semantic validation against separately supplied plan actions |
| `scripts/agent_equipment_adapter_contract.py`, `tests/test_agent_equipment_adapter_contract.py`, and `tests/fixtures/agent-equipment/schema/*-adapter-*.json` | Cross-record semantic binding validator plus executable positive and fail-closed adapter-contract examples |

Acceptance-evidence tests synthesize the compact expected-case manifest and its
full child projection in temporary directories. This avoids checking in one
dated 75-aggregate, plan-sized generated bundle as if it were release evidence.
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
home/private_dot_local/bin/executable_agent-equipment
home/private_dot_local/lib/agent-equipment/schemas/catalog-v1.schema.json
home/private_dot_local/lib/agent-equipment/schemas/lock-v1.schema.json
home/private_dot_local/lib/agent-equipment/schemas/captured-state-v1.schema.json
home/private_dot_local/lib/agent-equipment/schemas/plan-action-set-v1.schema.json
home/private_dot_local/lib/agent-equipment/schemas/adapter-contract-v1.schema.json
home/private_dot_local/lib/agent-equipment/schemas/acceptance-evidence-v1.schema.json
home/private_dot_local/lib/agent-equipment/schemas/execution-authority-v1.schema.json
home/private_dot_local/lib/agent-equipment/agent_equipment/__init__.py
home/private_dot_local/lib/agent-equipment/agent_equipment/model.py
home/private_dot_local/lib/agent-equipment/agent_equipment/canonical.py
home/private_dot_local/lib/agent-equipment/agent_equipment/_json_schema.py
home/private_dot_local/lib/agent-equipment/agent_equipment/validator.py
home/private_dot_local/lib/agent-equipment/agent_equipment/resolver.py
home/private_dot_local/lib/agent-equipment/agent_equipment/inventory.py
home/private_dot_local/lib/agent-equipment/agent_equipment/checkpoint.py
home/private_dot_local/lib/agent-equipment/agent_equipment/authorization.py
home/private_dot_local/lib/agent-equipment/agent_equipment/executor.py
home/private_dot_local/lib/agent-equipment/agent_equipment/secrets.py
home/private_dot_local/lib/agent-equipment/agent_equipment/evidence.py
home/private_dot_local/lib/agent-equipment/agent_equipment/adapters/base.py
home/private_dot_local/lib/agent-equipment/agent_equipment/adapters/standalone_skills.py
home/private_dot_local/lib/agent-equipment/agent_equipment/adapters/claude_projection.py
home/private_dot_local/lib/agent-equipment/agent_equipment/adapters/claude_plugin.py
home/private_dot_local/lib/agent-equipment/agent_equipment/adapters/claude_mcp.py
home/private_dot_local/lib/agent-equipment/agent_equipment/adapters/codex_plugin.py
home/private_dot_local/lib/agent-equipment/agent_equipment/adapters/codex_skill_policy.py
home/private_dot_local/lib/agent-equipment/agent_equipment/adapters/codex_mcp.py
home/private_dot_local/lib/agent-equipment/agent_equipment/adapters/cursor_plugin.py
home/private_dot_local/lib/agent-equipment/agent_equipment/adapters/cursor_mcp.py
home/run_onchange_after_status-agent-equipment.zsh.tmpl
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
`~/.local/lib/agent-equipment/agent_equipment/`. The installed launcher first
gates CPython 3.12 or newer plus isolated, no-bytecode, and no-site flags, before
importing any candidate module or reading runtime state. Its launcher-owned
bootstrap may resolve the selected launcher and system-CPython executable
targets once, then holds descriptors for those resolved targets. It opens child
paths descriptor-relatively without following links, requires the package and
Schema directory inventories to be closed, captures the exact launcher,
package, and Schema bytes plus the bytes at the selected interpreter executable
path, and hashes that closed v1 byte set into the installed-implementation
manifest. Every launcher, package, Schema, and runtime-executable read and
every closed-inventory enumeration is bounded; a bound or validation failure
emits only a redacted launcher diagnostic and exits before candidate import.
The manifest binds the stable selected system-CPython identity
`cpython:<major>.<minor>.<micro>` and the digest of the exact bytes read from
its executable path alongside the launcher, package, and Schema bytes. It does
not claim a complete standard-library, dynamic-loader, or shared-library
closure or authenticate the already-running process image.

The candidate package directory is not placed on `sys.path`. The bootstrap
executes candidate modules only from the captured package-byte mapping through
a closed launcher-owned loader with no filesystem or source-checkout fallback.
It supplies the captured Schema-byte mapping directly to schema and semantic
validation, which performs no Schema reread. Immediately before invoking
`main`, the launcher revalidates every held descriptor and path identity plus
each closed directory inventory. A stable byte change to an allowed package or
Schema entry before a new capture begins produces a new candidate manifest; it
does not fail capture. Once capture begins, any missing or extra closed-
inventory entry, disallowed link, shared inode, or nonregular entry, or any in-
flight path, byte, metadata, or inventory change exits without a candidate
entry point, native observation, adapter call, or checkpoint-store access.
Assurance for the executing process image or a complete runtime closure
requires a future pinned interpreter or runtime-native bootstrap that
establishes and measures that stronger boundary before candidate execution.

Step 1 computes the candidate's closed v1 installed manifest but does not
select, authenticate, or compare an expected digest. The independent expected-
manifest input enters the Step 4 authorization boundary, and Step 9 rechecks
the current capture against the exactly authorized digest before mutation.
Neither boundary is the candidate-independent release authority deployed in
Step 8a.

The installed CLI reads the catalog and lock from
`~/.config/agent-equipment/`. Checkpoints live under
`~/.local/state/agent-equipment/checkpoints/`; neither checkpoints nor
observed inventory are chezmoi-managed. The checked-in lock is regenerated only
by `agent-equipment update` and reviewed like source. The chezmoi `run_onchange`
script invokes only `agent-equipment status`; it accepts no authorization input
and cannot invoke apply, open the authorization ledger, or create an action
checkpoint. Its template input includes a canonical manifest
of every installed package file path and content digest, the launcher digest,
and the rendered catalog and lock digests, so any implementation-only change
reruns the read-only status command. The same closed v1 installed-implementation
manifest digest is bound alongside the distinct candidate commit or artifact
identity in plans, action sets, captures, checkpoints, receipts, and
authorization evidence. It never performs source discovery, updates, or
runtime reconciliation implicitly.

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

The executor has one forward-mutation seam and one separately authorized public
compensation seam:

```python
execute(
    validated_plan,
    apply_authorization_bytes,
    adapters,
    checkpoint_store,
    authorization_ledger,
    *,
    trusted_apply_authorization_digest,
    trusted_execution_domain_identity,
    trusted_operator_review_package_digest,
    trusted_clock,
) -> ApplyReport

compensate(
    validated_plan,
    compensation_authorization_bytes,
    adapters,
    checkpoint_store,
    authorization_ledger,
    *,
    trusted_compensation_authorization_digest,
    trusted_execution_domain_identity,
    trusted_clock,
) -> CompensationReport
```

After validating `ApplyAuthorization`, the executor obtains the expected
capture-observation-authority identity/digest from its closed bindings. Every
checkpoint, compensation, recovery, terminal, archive, and receipt validator
takes the exact `CaptureObservationAuthoritySet` plus that expected tuple. The
public API has no raw observation-list or caller-supplied observation-digest
form. Public compensation recovery obtains the same tuple from the archived,
revalidated apply authorization.

The operator invocation supplies the exact authorization file from
`~/.local/state/agent-equipment/authorization-inbox/<authorization_identity>.json`
and its separately authenticated `trusted_apply_authorization_digest`. The CLI
does not discover a newest authorization, infer its digest, or fall back to an
environment/config value. Before the first action checkpoint it strictly parses
and validates the record, checks the complete binding tuple, exact top-level
`execution_domain_identity` against `trusted_execution_domain_identity`, and
UTC window,
performs the final authorized live comparison, and only then durably claims its
execution nonce under
`~/.local/state/agent-equipment/authorization-ledger/`, whose independently
trusted execution-domain identity names that one authoritative CAS namespace
and target. Exclusive creation plus file and parent-directory fsync make the
claim one-time. A claimed, expired, misbound, foreign-domain, or unpersistable
authorization performs zero adapter calls. Recovery
may reopen only the same claimed run, execution domain, and surviving
checkpoints; a new action or run requires a fresh authorization and nonce.

The public `compensate` seam accepts only the closed
`CompensationAuthorization` (`agent-equipment-compensation-authorization/v1`)
and its independently authenticated digest. The record uses
`compensation_authorization_identity`, `command: compensate`, issuer and UTC
window, a fresh `compensation_nonce`, and exact bindings to the original apply
identity/digest, execution-domain identity, execution nonce, run identity,
checkpoint-set digest, and plan-action-set digest. The executor claims the
checkpoint-set digest only from a validated `CheckpointSetManifest`: while
holding the exclusive lease it enumerates the authoritative store at one
generation, recomputes each complete durable record digest, requires all-and-
only deterministic membership against the validated plan actions, and rejects
empty, missing, extra, duplicate, foreign, stale, reordered, malformed, or
resealed entries. It repeats that enumeration and generation check immediately
before claiming the nonce or writing a transition; concurrent change fails.
The executor claims the
compensation nonce once by compare-and-swap in the same authoritative
execution-domain ledger namespace before any `compensating` transition. A
missing, expired, replayed, foreign-domain, or unpersistable authorization
performs no adapter call or checkpoint transition. Immediate reverse
compensation after a later failure stays inside the already invoked claimed
apply run; it does not reuse apply authority as a public compensation grant.
Recovery after the public nonce claim is a separate continuation path. It
requires the archived original compensation authorization and pretransition
checkpoint manifest, the independently trusted durable ledger claim for their
exact identity/digest/nonce, and a race-rechecked current checkpoint store. The
current store must preserve checkpoint membership and forward invocation intent,
carry only claims for that original authority, and strictly advance each changed
record and the store generation. It may equal the original store when the crash
occurred after the ledger CAS but before the first checkpoint transition. It
does not mint a fresh nonce or reapply the expired clock window.
`compensation_blocked` requires separate operator disposition, and public
recovery never replaces `automatic_apply` provenance.

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
objects, or mutate a surface outside the action. Before apply issuance, validate
every input shape and seal the complete `CaptureObservationAuthoritySet` from
the trusted plan and capture. Validate its independently trusted identity/digest,
then seal the complete `PreparedActionAuthoritySet` from that artifact and the
adapter-derived normalized pre/post state. Before
adapter invocation, construct the `ApplySequence` authority context from that
validated set and the prepared checkpoint, and enforce its same
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

It binds the canonical semantic bundle digest, candidate/artifact tuple, and the
canonical automated-runner, live-operator, and release-reviewer records. Each attestor
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
    expected_execution_domain_identity,
    expected_execution_nonce,
    expected_run_identity,
) -> tuple[Diagnostic, ...]

release_candidate(
    apply_authorization_bytes,
    plan_action_set_bytes,
    captured_state_bytes,
    capture_observation_authority_set_bytes,
    prepared_action_authority_set_bytes,
    checkpoint_store_snapshot_bytes,
    checkpoint_set_manifest_bytes,
    run_terminal_record_bytes,
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
    trusted_apply_execution_tuple,
    artifact_store,
) -> ReleaseReceipt
```

The candidate-independent release launcher obtains the expected-case manifest
digest from the exact trusted pre-mutation authorization and the attestation
digest from the separate post-run release authority. It first verifies its own
installed bytes against the independently supplied launcher identity and
manifest digest. The release command strictly parses all eleven exact byte
inputs, invokes the validator with the trusted digests, and refuses a release
receipt on any diagnostic. It obtains the expected capture-observation-authority
identity/digest from the validated apply authorization and revalidates the exact
capture-observation and prepared-action authority sets. It hashes each exact
input byte stream independently of its semantic canonical digest and supplies no
caller-authored archive-digest map. The release validator recomputes all eleven
archive byte digests solely from the supplied bytes after bounded strict parsing.
For the historical apply authorization it rechecks the closed schema, canonical
identity and independently trusted digest, execution tuple, and bindings
derivable from the replay streams. It deliberately does not rerun the apply-time
issuer, clock-window, or nonce-claim checks: release has no trusted issuer or
apply-time clock inputs, and later expiry cannot invalidate a completed run's
archive. It constructs the
closed `ReleaseArchiveManifest`, derives the complete plan, captured state,
store generation, and full durable checkpoint records only from the exact
plan-action-set, captured-state, and sealed checkpoint-store-snapshot bytes,
validates the checkpoint manifest as the snapshot's exact projection, and
validates an authenticated `RunTerminalRecord`. Success requires one completed
checkpoint for every plan action and `state: succeeded`. It stages and fsyncs
the authorization, plan-action set, captured-state manifest,
capture-observation-authority set, prepared-action-authority set,
checkpoint-store snapshot, checkpoint manifest, terminal record, three release
documents, and archive manifest, then commits generation `1` with a create-only
compare-and-swap rename. An existing identical generation is an idempotent read;
different existing bytes are a conflict. It emits a `ReleaseReceipt` only after
that archive commit is durable; compensated, blocked, and nonterminal runs
cannot yield a passed receipt. Candidate code cannot call the authority's
receipt/archive capability, and a candidate-authored lookalike record is not a
receipt. The launcher does not call apply, adapters, native managers, or
migration recovery.

## Dependency-ordered implementation backlog

Each step is a clean checkpoint and an independently reviewable pull request.
Later steps do not begin until the named evidence passes.

### 1. Promote the design validator into the production model

- Add the CPython 3.12+ and isolated/no-bytecode/no-site fail-before-import
  gate. In launcher-owned bootstrap code, resolve the selected launcher and
  system-CPython executable targets once and hold their descriptors. Open child
  paths descriptor-relatively without following links, require the package and
  Schema inventories to be closed, and capture and hash the exact launcher,
  package, and Schema bytes plus the bytes at the selected executable path into
  the closed v1 installed-implementation manifest before any candidate import.
  Bind the stable selected runtime identity and executable-byte digest into
  that manifest; do not claim a complete runtime closure or executing-image
  authentication.
- Execute the candidate namespace only from captured package bytes through a
  closed launcher-owned loader with no filesystem or source-checkout import
  fallback. Supply captured Schema bytes directly to validation without a
  reread, then revalidate all held descriptors, path identities, stable
  metadata, and closed inventories immediately before invoking `main`.
- Prove an absent, older, or non-CPython runtime; missing, extra, or disallowed
  closed-inventory entry; in-flight path, byte, metadata, or inventory change
  after capture starts; Schema reread; or filesystem import attempt reaches
  neither the candidate entry point, native observation, nor checkpoint store.
  Prove a stable pre-capture byte change to an allowed package or Schema entry
  instead yields a new candidate manifest. Bound every capture read and closed-
  inventory enumeration; prove limit failures expose only a redacted launcher
  error before candidate import.
- Treat the computed manifest as candidate evidence only. Expected-digest
  authentication and comparison remain the Step 4 and Step 9 boundaries;
  independent release-launcher trust remains Step 8a.
- Implement immutable typed model objects, canonical JSON, schema validation,
  template expansion, and every cross-field invariant.
- Make the catalog digest and lock binding stable test vectors.
- Promote the checked-in proposed catalog only through a reviewed catalog
  addition or production-source change; its `.proposed.json` name conveys zero
  live authority.
- Reject all malformed input before native capability discovery.
- Evidence: `CAT-01` through `CAT-09`, the catalog-level compensation and
  fail-closed portion of `CAT-10`, and `CAT-11` through `CAT-14` in
  `ACCEPTANCE.md`; static type checking; and mutation testing of each
  catalog/lock cross-field guard. Matching adapter capability remains a Step 2
  resolver gate because Step 1 has no capability records.

### 2. Implement read-only inventory and the pure resolver

- Implement adapter capability and observation records without mutation.
- Require every normalized state to carry closed `immutable_content` evidence.
  Immutable present state admits freshly verified observed revision and content
  digest or truthful `unknown`; absence uses `route_absent`; partial or unknown
  presence uses `unknown`. Immutable `observed_version`, native-update control,
  native-update suppression state, and manager drift are `not_applicable`;
  native-rolling routes tag `immutable_content` as `not_applicable`.
- Classify an immutable active route as converged only when its observed tuple
  exactly equals `route_record.restore`. Plan `install` for confirmed absence,
  `restore` for a known mismatch, and no mutation for unknown evidence. Remove
  an immutable losing route only when its observed tuple exactly matches the
  reviewed retirement tuple.
- Preserve exactly one complete coverage record per identity and harness.
- Apply selective component controls before forming activation groups.
- Keep active `equipment_identities` separate from exact
  `controlled_equipment_identities`; a disabled controlled `no_provider`
  identity remains inactive while still naming an authorized control surface.
- Produce stable diagnostics, provider selections, operation matrices, and
  owned overlay proposals. Derive a complete action-dependency graph, reject
  missing dependencies, orphans, and cycles, then topologically order it with
  lexical tie-breaks only among ready actions.
- Close the remaining `CAT-10` fixture by rejecting an unsupported automated
  final action against the matching adapter capability before producing a plan
  or opening the checkpoint store.
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

- `unmanaged` reads runtime state and the authored catalog without changing
  either. It emits canonical secret-free observation records only for equipment
  positively observed on the machine and absent from the catalog. Exclude every
  cataloged operator-owned route.
- Treat each runtime observation as fact, never as a proposal or ownership
  claim.
- `add` always performs a fresh targeted unmanaged observation during its own
  invocation; a prior `unmanaged` invocation is neither required nor consumed.
  Revalidate the observed state and every binding before emitting one atomic
  proposed catalog addition. If state or bindings change, fail with no partial
  proposal.
- `update` follows the configured source tracking policy and resolves immutable
  revisions and reviewed native-rolling baselines into one atomic proposed
  catalog-and-resolved-lock update. It installs nothing; the catalog and
  digest-bound lock advance together or neither does.
- None opens a runtime checkpoint store or invokes a mutating adapter method.
- Evidence: `CMD-02` through `CMD-04` with byte-identical runtime snapshots and
  catalog snapshots for `unmanaged`.

### 4. Implement checkpointing before any production adapter mutation

- Implement the closed `ApplyAuthorization` parser and semantic validator plus
  the durable authorization ledger. The public executor requires exact
  authorization bytes and the separately supplied
  `trusted_apply_authorization_digest`, `trusted_execution_domain_identity`, and
  trusted operator-review-package digest; validate the canonical identity, full
  tuple, command, UTC window, run, and nonce before the first action checkpoint.
  Require the authorization's top-level execution domain to equal that trusted
  identity and the one authoritative ledger namespace and CAS target. Claim the
  nonce with an exclusive, fsynced create in that domain. Test missing, extra,
  expired, not-yet-valid, replayed, cross-run, cross-plan, cross-domain, and
  persistence-fault cases for zero adapter calls and zero action checkpoints.
- Put a 256 KiB raw-byte limit ahead of UTF-8 decoding, JSON parsing, regular
  expressions, credential scanning, and hashing for every ordinary public
  execution-authority record. Give the aggregate release replay plan-action-set,
  captured-state, full checkpoint-store-snapshot, expected-case,
  evidence-bundle, and attestation streams separate 16 MiB raw and canonical
  byte limits. Reject duplicate members, non-UTF-8,
  `NaN`/infinity, oversized
  records, and timestamps with more than nine fractional digits. At every
  parsed-object authority boundary, canonicalize only to enforce the same 256
  KiB ceiling before Schema, regular-expression, credential, or digest work.
- Carry the required `immutable_content` tag through every execution-authority
  normalized pre-state and expected post-state. Capture-observation,
  prepared-action, checkpoint, snapshot, and checkpoint-set validation must
  preserve the exact tuple in their canonical digests and compare guards.
- Implement the separate closed `CompensationAuthorization` parser and public
  `compensate` boundary. Require `command: compensate`, canonical
  `compensation_authorization_identity`, independently trusted complete digest,
  issuer and UTC window, a fresh `compensation_nonce`, and exact original apply,
  execution-domain, execution-nonce, run, checkpoint-set, and plan-action-set
  bindings. Derive the checkpoint-set binding from the complete independently
  enumerated manifest under the exclusive lease, then repeat the exact
  generation/content check immediately before mutation. Claim the compensation
  nonce once by CAS in the same authoritative execution-domain ledger before
  writing `compensating`. Never reuse
  `ApplyAuthorization` for this seam. Test missing, expired, replayed,
  cross-domain, cross-run, cross-checkpoint, cross-action-set, and persistence-
  fault cases for zero adapter calls and checkpoint transitions. Keep automatic
  compensation after a later apply failure inside that already invoked claimed
  run.
- Add a distinct public-compensation recovery validator. Revalidate the archived
  original authorization and pretransition checkpoint manifest, require the
  independently trusted durable compensation-ledger claim, and race-check that
  the current store is a monotonic descendant with unchanged forward invocation
  intent and surviving claims bound only to the original authority. Cover the
  crash after ledger CAS but before any checkpoint change, direct `prepared` to
  `compensating`, strict record/store generation advancement, automatic-
  provenance takeover rejection, and blocked-state refusal. Recovery does not
  mint a new nonce or reapply the original clock window.
- Persist apply-authorization identity/digest and execution nonce in every
  durable checkpoint, include them with the full `CHK-10` tuple in its immutable
  identity, and validate them against independent apply inputs. Enforce the
  complete phase-history, current-phase, invocation-state matrix.
- Enforce one reachable lifecycle across the canonical checkpoint prefix:
  `completed*` plus at most one final `prepared` record before compensation, or
  `completed*`, at most one lowest nonterminal compensation frontier, then
  `compensated*` during reverse execution. Reject a later completed action after
  an earlier prepared one and reject a lower compensated action while a higher
  dependent remains forward.
- Distinguish compensation provenance with `compensation_authority_kind`.
  Automatic rollback uses `automatic_apply` without a public claim. The public
  seam uses `public_compensation` and a separate closed transition claim binding
  checkpoint identity plus the independently validated compensation authority
  identity/digest and nonce. Reject missing, ambiguous, and canonically resealed
  foreign claims before transition. Enforce every closed claim member's string
  and digest format and require the independently validated non-null public
  compensation tuple whenever any claim is present.
- Accept the complete closed `agent-equipment-plan-action-set/v1` artifact at
  checkpoint and terminal seams. Validate its Schema, canonical action/set
  identities and digests, independent candidate/implementation/plan/set
  bindings, and one identical catalog/lock tuple across every action, then map
  the all-and-only checkpoint-store subset uniquely into it.
  Never replace it with a naked caller action list.
- Before apply issuance, derive and seal one complete
  `CaptureObservationAuthoritySet`. Obtain its expected identity and complete
  digest through an independent trusted channel; never derive either expected
  value from the artifact under review. Its closed bindings name the exact
  candidate, implementation, plan, plan-action set, capability set, and captured
  state. Each all-and-only ordered observation binds action identity and ordinal,
  captured-state identity/digest, exact surface scope, controlled-component
  identities, complete normalized pre-state, and its canonical digest. Bind the
  validated set identity/digest into `ApplyAuthorization`. The raw observation-
  list and standalone expected-observation-digest API is removed.
- Derive and independently validate one complete sealed
  `PreparedActionAuthoritySet` from that validated capture-observation artifact.
  Require each prepared pre-state to equal its matching observation exactly, plus
  all-and-only canonical plan membership, exact candidate, implementation,
  plan, capability, and capture bindings, normalized pre/post self-digests and
  native-update invariants, exact sorted controlled-component identities in
  both states, and the planned desired-state fragment in expected post-state.
  Bind the prepared set identity/digest into `ApplyAuthorization`; every public
  validation seam takes both closed artifacts and gets both expected tuples from
  the validated authorization. Checkpoints consume the prepared set's exact
  state rather than a caller map or raw capture observation.
- Add the closed `RunTerminalRecord`, bound to the exact apply tuple, complete
  plan-action-set digest, checkpoint-set identity/digest, store generation, and
  `state: succeeded`. Require full plan coverage by unique completed checkpoints
  whose durable generations increase in canonical action order. Release derives
  the plan, captured state, store generation, and full durable records only from
  the exact plan-action-set, captured-state, and checkpoint-store-snapshot bytes,
  requires the complete snapshot's store generation to equal its maximum durable
  record generation,
  validates all eleven exact streams, recomputes and archives all eleven byte
  digests solely from those streams;
  accept no lossy projection, naked checkpoint digest, or terminal-state scalar.
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
  run. Preserve immutable plan bindings, fresh status observation before retry,
  and reverse compensation. A restore-guard mismatch persists
  `compensation_blocked`,
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
  then replace only a catalog-owned canonical entry.
- Emit observed immutable content only after freshly verifying installed bytes
  and integrity-bound installed provenance. Never echo the requested catalog or
  lock revision or digest as observation evidence; emit `unknown` when either
  verification is unavailable or fails.
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
- Validate the complete captured-state artifact against that plan and seal the
  exact `CaptureObservationAuthoritySet` over every normalized pre-state. Derive
  the adapter-normalized post-state context and seal the exact
  `PreparedActionAuthoritySet` before requesting `ApplyAuthorization`. Bind both
  independently trusted identity/digest tuples into that authorization. Reject a
  missing/extra action, duplicate ordinal or component identity, capability-set
  mismatch, capture/prepared-state mismatch, desired-post fragment mismatch, or
  independently trusted set-identity/digest mismatch before issuance.
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
  validation of the authorization, complete plan-action set, captured-state
  manifest, capture-observation-authority set, prepared-action-authority set,
  full-record checkpoint-store snapshot, checkpoint-set manifest, run-terminal
  record, and all three release documents; create-only
  compare-and-swap archival, idempotent retrieval of an identical generation,
  conflict rejection, the closed `ReleaseArchiveManifest` identity/digest
  formula over exact byte digests, and the closed `ReleaseReceipt` formula.
  Test that candidate-owned paths, candidate-minted receipts, skipped archive
  commits, and altered launcher bytes never satisfy release.
- Evidence: deployment ownership inspection, launcher-manifest verification,
  create-only archive concurrency/fault fixtures, and release-receipt vectors in
  `tests/test_agent_equipment_deployment_contract.py`.

### 8b. Bind the coordinated six-distribution source-skill reconciliation receipt

- Treat the release tracked in
  [`nisavid/agents#41`](https://github.com/nisavid/agents/issues/41) as one
  coordinated release of six distributions: Rolecasting, Tricritical,
  Versionkeeping, Mergecraft, Artifact Customs, and Task Witness. Do not call
  this release "Agent Plugins v1". Agent Plugins Specification v1.0.0 is the
  packaging standard, and this step does not defer support for that standard.
- Use the source-skill reconciliation receipt contract defined by
  [`nisavid/agents#45`](https://github.com/nisavid/agents/issues/45),
  [`#49`](https://github.com/nisavid/agents/issues/49),
  [`#50`](https://github.com/nisavid/agents/issues/50), and
  [`#51`](https://github.com/nisavid/agents/issues/51). The current exact
  agent-equipment v1 model and Schemas do not define or bind this receipt. Do
  not add a placeholder field, accept an open extension, or overload
  `ReleaseReceipt`.
- Complete the integration tracked in
  [`nisavid/dotfiles#80`](https://github.com/nisavid/dotfiles/issues/80) before
  Step 9 requests live `ApplyAuthorization` for a candidate that contains the
  coordinated six-distribution release. Use either a new closed, versioned
  adjacent record or a new major version of each affected closed Schema.
- Bind the exact receipt bytes and its canonical identity and digest to the
  exact candidate identity, catalog digest, lock digest, and coordinated
  release identity chain. Retain the exact receipt bytes in the release archive.
  For a candidate that contains the coordinated six-distribution release, fail
  closed before live authorization or release when the receipt is missing,
  malformed, duplicate, noncanonical, untrusted, misbound, or byte-different.
- Evidence: closed-Schema fixtures, canonical identity/digest vectors,
  candidate/catalog/lock/release cross-binding tests, archive byte-replay tests,
  and fail-closed Step 9 authorization tests.

### 9. Request exact runtime-migration authorization

- Refresh upstream source manifests, live inventory, harness versions, plugin
  capabilities, symlink set, and manager locks.
- Run `agent-equipment status`, acquire the apply lease, capture every affected
  route and surface, emit the independently validated plan-action projection,
  validate both Schemas then cross-record semantics, seal the action set and
  capture, and resolve again against them. Produce the exact candidate
  implementation identity and installed-manifest digest, catalog digest, lock
  digest, one immutable migration-plan digest, plan-action-set digest,
  capability-set digest, captured-state identity and digest, sealed capture-
  observation-authority-set identity/digest, sealed prepared-action-authority-set
  identity/digest, expected action list, explicit verification and migration
  nodes, sealed expected-case manifest and digest, compensation list, and
  rollback command.
- Ask for authorization naming that complete candidate, catalog, lock, plan,
  plan-action-set, capture-observation-authority-set identity/digest, prepared-
  action-authority-set identity/digest, capability-set, captured-state identity/
  digest, expected-case-manifest digest, operator-review-package digest, and independently
  selected execution-domain identity tuple.
  The authority emits the closed `ApplyAuthorization`, including command, issuer,
  time window, execution domain, run, and fresh execution nonce, then supplies
  its canonical
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
  archive commit. Its archive retains the exact apply authorization, plan-action
  set, captured-state manifest, capture-observation-authority set,
  prepared-action-authority set, checkpoint-store snapshot, checkpoint-set
  manifest, run-terminal record, expected-case manifest, bundle, and attestation
  byte streams plus their verified digests. Retain only successfully verified
  desired state.

## Retained and retired source map

### Retained now

| Path | Disposition |
| --- | --- |
| `home/run_after_sync-global-agent-skills-to-claude.zsh` | Retain unchanged until the production catalog projector passes fresh-home, no-op, and rollback gates. It remains the live owner. |
| `home/dot_claude/skills/symlink_*` | Retain until each projection has an explicit reviewed catalog addition and both owners cannot run concurrently. |
| `home/modify_private_dot_claude.json.tmpl` | Retain as live Claude MCP owner until accepted keys move atomically to the Claude MCP adapter. |
| `home/dot_claude/modify_private_settings.json.tmpl` | Retain as live Claude plugin-selection owner until the Claude plugin adapter owns the same exact keys. |
| `home/dot_codex/modify_private_config.toml.tmpl` | Retain unrelated preferences and runtime-field preservation. Later remove only MCP and skill-policy branches transferred to adapters. |
| `home/dot_config/modify_private_mcp-config.json.tmpl` | Retain as live Cursor MCP owner until accepted keys move atomically to the Cursor MCP adapter. |
| Native manager locks | Retain outside chezmoi authority as observation and provenance evidence. |
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
| Catalog-owned `home/dot_claude/skills/symlink_*` entries | Generated projection owns the exact same link and dual ownership is removed in one reviewed change. |
| MCP/plugin branches in existing modify overlays | Corresponding adapter passes fresh-home, narrow-diff, compensation, and secret-canary tests. |
| The 21 observed Matt symlinks in `~/.claude/skills` | Exact pre-state still matches, catalog marks only those projections owned and losing, the new projector is active, the official plugin is installed and enabled with its complete active Matt activation group verified, and plugin installation can be compensated after every removed link is restorable. |

No retirement rule deletes unmanaged equipment, a cataloged operator-owned
route, or a canonical `~/.agents/skills` entry.

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
   Step 8a from the protected release-authority source before any candidate can
   receive a release receipt. For a candidate that contains the coordinated
   six-distribution release, complete its source-skill reconciliation receipt
   binding in Step 8b before Step 9 can request live `ApplyAuthorization`. Do
   not combine implementation with a live catalog addition merely to shorten
   the stack.
5. Open a separate closed `ApplyAuthorization` containing the exact candidate
   implementation identity and installed-manifest digest, refreshed inventory,
   immutable plan, plan-action-set, already validated and sealed capture-
   observation-authority-set identity/digest, already validated and sealed
   prepared-action-authority-set identity/digest, capability-set, and already
   sealed captured-state identity/digest, sealed expected-case manifest and digest,
   issuer, validity window, independently trusted execution-domain identity,
   run, and fresh execution nonce. Bind the exact live
   mutations, rollback command/actions, and review receipts transitively through
   the closed `operator_review_package_digest`; do not embed those documents as
   open authorization fields. Supply its
   `trusted_apply_authorization_digest` outside the record. Require an exact post-
   authorization implementation and live comparison before the first action
   checkpoint; drift, a different ledger domain, or nonce reuse requires a new
   capture and authorization. A later fresh/public compensation invocation
   requires its own closed `CompensationAuthorization`, independently trusted
   digest, and one-time CAS claim of `compensation_nonce` in that same execution
   domain; it never reuses the apply record.

## Stop conditions

Stop before mutation when an identity is unresolved; a coverage record or
route is incomplete; an overlap lacks an exact exception; a required
capability is unknown; an operator-owned route exposes automated mutation; an
automated mutation lacks pre-state compensation; the catalog-lock binding is
stale; a secret value enters generated state; current state differs from
captured or expected state; the capability-set digest or a route binding is
invalid; the capture-observation or prepared-action authority set is missing,
misbound, incomplete, or differs from its apply-bound identity/digest; the post-
authorization comparison differs from the sealed capture; a
checkpoint cannot be made durable; CPython 3.12 or the manifest-bound runtime is
unavailable; the closed authorization is absent, expired, not yet valid,
misbound, names a foreign execution domain, is replayed, or cannot be claimed
durably; its canonical digest differs
from `trusted_apply_authorization_digest`; or the exact runtime plan, plan-
action-set, capture-observation-authority-set, prepared-action-authority-set,
captured-state, and expected-case-manifest digests lack
authorization.

Stop before a public compensation transition when `CompensationAuthorization`
is absent, expired, not yet valid, misbound to the original run, execution
domain, checkpoint set, or plan-action set, has a replayed `compensation_nonce`,
differs from `trusted_compensation_authorization_digest`, or cannot be claimed
by CAS in the same authoritative execution-domain ledger namespace.

Stop before release when the external launcher's identity or installed-manifest
digest differs from its trusted input; the exact apply authorization or
attestation digest lacks independent authorization; any of the eleven exact
release inputs fails strict parsing, artifact equality, or archived byte-digest
verification; any release document or binding differs; an attestor predates a bound result or live sign-off; the
canonical live operator differs from a passing live signer; any required child
or aggregate does not pass; or the create-only archive commit is absent or
conflicts. Candidate output never overrides a stop.
