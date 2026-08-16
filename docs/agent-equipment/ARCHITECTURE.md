# Global agent equipment architecture

This document is the implementation contract produced by Issues #55 and #56.
The JSON Schemas are authoritative for serialized shape; this document owns
resolution order, command boundaries, adapter responsibilities, and recovery
semantics.

## Sources of truth

| State | Owner | Authority |
| --- | --- | --- |
| Authored catalog | dotfiles repository | Desired distributions, equipment, coverage, ownership, restore claims, and exceptions |
| Resolved lock | generated dotfiles artifact | Exact expanded inventory and complete route records bound to the catalog digest |
| Native manager locks | native manager | Import and provenance evidence only |
| Harness files and CLIs | harness or native manager | Observable runtime state |
| Caches, databases, credentials, usage state | harness or native manager | Never catalog state |
| Apply authorization | external operator authority | One time-bounded, one-run grant for one exact pre-mutation binding tuple and execution domain |
| Execution domain | external operator authority | Independently trusted identity of the one authoritative CAS nonce-ledger namespace and target |
| Authorization ledger | reconciler runtime state directory | Durable one-time nonce claims inside the exact execution domain; never authority issuance |
| Capture observation authority set | trusted pre-invocation validator | Sealed all-and-only plan-action projection of normalized capture observations, with identity/digest later bound by apply authority |
| Prepared action authority set | trusted pre-invocation validator | Sealed all-and-only plan-action projection of adapter-derived normalized pre-state and expected post-state |
| Compensation authorization | external operator authority | Time-bounded grant for one fresh public compensation invocation against one original run and checkpoint set |
| Apply checkpoints | reconciler runtime state directory | Recovery evidence for one immutable plan |
| Expected acceptance cases | production evidence writer | Exact release cases projected from one validated plan and authorized binding tuple |
| Acceptance evidence bundle | fixture and live runners | Candidate results only; never desired state or mutation authority |
| Release attestation | external release authority | Post-run authorization of one exact evidence-bundle digest and attestor set |
| Release launcher | external release authority | Candidate-independent validation, create-only archival, and receipt issuance |
| Release archive manifest | external release authority | Closed identity/digest contract over exact archived bytes, execution tuple, launcher, and destination |
| Release receipt | external release authority | Terminal proof of one launcher-authenticated, atomically archived release tuple |

The catalog and lock are public, secret-free data. They contain environment
variable names or opaque `secret-exec` profile names, never resolved values.

## Serialized artifacts

The catalog uses `catalog-v1.schema.json`. It contains:

- the exact active harness list: `claude`, `codex`, and `cursor`;
- distributions with source selectors and either `all` or explicit equipment
  selection;
- named coverage templates for source-wide expansion;
- explicit equipment identities and exact per-harness coverage records or
  whole-record template references;
- complete active provider routes, including the component controls already
  selected as enabled or disabled, the activation group that remains after
  those controls, route control owner, provenance owner, restore class, native update
  control, secret references, operation dispositions, and compensation; and
- explicit overlap exceptions with a rationale.

Distribution membership is resolved into the lock. One logical identity may be
supplied by several distributions; no authored equipment row owns exactly one
distribution. A source-wide `all` selection expands to exact lock membership,
while an explicit selection must equal its resolved membership.

There is no field-by-field inheritance. Expansion uses this precedence:

1. An exact equipment-and-harness coverage record.
2. The named coverage template referenced by that exact entry.
3. The one unambiguous selected distribution template for that harness.

When several selected distributions supply the same identity, step 3 is
ambiguous and an exact identity-and-harness record is required. A referenced
template must declare the target harness. Each selected source-wide identity
must resolve at step 3 or an earlier exact record. An exact record or template
replaces the lower-precedence record as a whole; null, recursive, and partial
merges are invalid.

The lock uses `lock-v1.schema.json`. Canonical hashing serializes UTF-8 JSON
with sorted object keys and no insignificant whitespace. Checked-in JSON may be
pretty-printed for review; formatting never enters a digest. `catalog_digest`
is the SHA-256 digest of the catalog's canonical serialization. The lock:

- records the exact selected distribution revision, artifact reference,
  content digest, and `not_applicable` native-update state when immutable
  restore is available;
- records the channel, reviewed observed-version baseline, observation source,
  and `unknown`, `suppressible`, or `unsuppressible` native-update state for
  native-rolling routes;
- expands every accepted equipment identity across every active harness;
- stores one complete harness coverage record per identity and harness; and
- copies each explicit overlap exception into the affected provider selection.

Formatting-only catalog edits therefore do not stale the lock. Any semantic
catalog change does. Apply rejects an absent, malformed, or stale lock before
opening its checkpoint store.

`acceptance-evidence-v1.schema.json` owns three closed release documents. The
pre-mutation expected-case manifest binds the candidate, installed manifest,
catalog, lock, plan, plan-action set, capability set, sealed capture, fixture
version, and every route's exact provider selector, route digest, capability,
and manager-version evidence. It carries the complete v1 requirement registry,
static cases, sealed automated action identities, explicit verification nodes,
and explicit mutating migration boundaries. It is a projection of an already
validated plan, not a replacement for plan validation.

The evidence bundle repeats the exact bindings and route evidence, adds the
post-authorization execution binding—apply-authorization identity and canonical
digest, execution-domain identity, execution nonce, and run identity—and
records the
public harness and manager versions, and contains one aggregate plus the exact
closed child registry. A child's identity is the canonical digest of its
requirement ID, fixture family, and sealed subject identity. The semantic
validator expands the repeated checkpoint matrix only over the manifest's
sealed actions and mutating migration boundaries. It maps migration cases only
through explicit node-to-requirement records; it never invents plan nodes from
prose.

The post-run attestation binds the same execution binding, the recomputed
complete evidence-bundle digest, the expected-case manifest digest, and the
exact candidate/artifact bindings.
Its canonically ordered attestors are the automated runner, live operator, and
release reviewer, each with a distinct identity, runner or signing-policy
implementation version, and UTC attestation time after all bound evidence. The
live operator is the signer of every passing live child. Its own canonical
digest is independently authenticated by an external release authority. The
candidate bundle cannot authenticate its own manager versions, harness
versions, live sign-offs, receipts, or results.

The candidate-independent release launcher supplies the trusted candidate,
installed-manifest digest, pre-mutation expected-case manifest digest, and post-
run attestation digest. The validator recomputes all three document digests,
requires exact cross-document bindings and route capability membership,
requires every route's manager-evidence digest to have a manager-version
receipt, and derives aggregate pass from complete passing child results. It
does not authenticate attestor identities, signatures, or receipt truth; the
external authority authenticates the attestation digest. Opaque artifact
references plus digests identify evidence without embedding filesystem paths,
URLs, native output, or secret values. Manager and harness version strings are
public native-manager observations; diagnostics never echo their supplied
contents.

`execution-authority-v1.schema.json` owns ten closed records with independent
purposes. `CaptureObservationAuthoritySet` replaces the former raw observation-
list input with one closed, canonically sealed artifact. Its bindings name the
exact candidate, installed implementation, plan, plan-action set, capability
set, and captured-state identity/digest. It contains one canonically ordered
observation for every plan action and no others. Each observation binds the
action identity and ordinal, exact surface and controlled-component identities,
and complete normalized captured pre-state plus its canonical digest. Before
apply issuance, an independent trust channel supplies and validates the set's
exact identity and complete digest. `ApplyAuthorization` then binds that tuple;
a coordinated projection reseal requires a new authorization.

`PreparedActionAuthoritySet` is sealed after complete plan, capture-observation-
authority, and adapter-context validation and before apply issuance. It contains one
canonically ordered authority for every plan action and no others. Each member
binds the exact candidate and implementation, catalog, lock, plan, capability
set and route capability, operation and compensation, surface set, sealed
capture identity/digest, and complete normalized captured pre-state and expected
post-state with self-digests. Both normalized states contain a sorted, unique
component identity set equal to the action's exact controlled-equipment set, and
the expected post-state must include the action's desired-state fragment. The
set has an independently trusted canonical identity and digest; a caller map or
a coordinated reseal does not replace that trust. Every prepared pre-state must
equal its matching member of the validated `CaptureObservationAuthoritySet`.

`ApplyAuthorization` is the only serialized authority that may start
forward mutation. It binds `command: apply`, issuer and validity times, one run
identity, one issuer-generated execution nonce, the independently trusted
`execution_domain_identity`, and the complete candidate, installed-
implementation, catalog, lock, plan, plan-action-set, capture-observation-
authority-set identity/digest, prepared-action-authority-set identity/digest,
capability-set, sealed-capture, expected-case-manifest, and
operator-review-package tuple. The review-
package digest binds the exact proposed live mutations, rollback material, and
operator review content presented to the issuer. Its identity is the canonical
digest of the record excluding `authorization_identity`; the separately supplied
`trusted_apply_authorization_digest` is the canonical digest of the complete
record. Equality with candidate-authored fields is not authorization.

`CheckpointSetManifest` is the canonical, nonempty, ordered projection of all
durable checkpoints eligible for one exact apply authorization, execution
domain, run, and complete validated plan-action set at one checkpoint-store
generation. The store may contain a strict prepared prefix after an early
crash; it is not required to echo every plan action. Each entry
binds durable generation and record version, phase, invocation state, action
identity and ordinal, an immutable checkpoint identity, and the canonical
digest of the complete closed durable checkpoint record, including phase
history, capability binding, compensation operation, and pre/post state. The
manifest identity is the canonical digest of the record excluding both identity
and digest; its complete digest excludes only the digest. The executor derives
this manifest while holding the exclusive lease by independently enumerating
the authoritative checkpoint store and matching every action/ordinal against
the complete closed `agent-equipment-plan-action-set/v1` artifact. That artifact
is schema-checked, its action and set identities/digests are recomputed, and its
candidate, implementation, plan, and set digest are compared with independent
trusted inputs. Each checkpoint maps uniquely to one artifact action, while the
manifest remains all-and-only the authoritative store. It re-enumerates the
store and checks the same
generation immediately before claiming the compensation nonce or writing the
first transition; any missing, extra, duplicate, reordered, foreign, stale, or
concurrently changed record fails closed. Every durable record itself includes
the apply-authorization identity/digest, execution nonce, run, domain, and the
full `CHK-10` tuple; those fields participate in its immutable checkpoint
identity and are checked against independent apply inputs. Before accepting any
checkpoint, validation revalidates the complete captured-state artifact,
`CaptureObservationAuthoritySet`, and `PreparedActionAuthoritySet`, requires the
checkpoint sequence to be the exact canonical plan prefix, and matches its step
ID, normalized pre/post state,
capability-set digest, and all other immutable fields to the corresponding
prepared authority. Each public checkpoint, compensation, recovery, terminal,
archive, and receipt validation seam receives the closed capture-observation
artifact plus the expected identity/digest tuple obtained from the validated
`ApplyAuthorization`; no seam accepts a raw observation list or derives trust
from the artifact under review.
The cross-record lifecycle must also be reachable: before compensation it is
zero or more `completed` records followed by at most one final `prepared`
record; during compensation it is zero or more `completed` records, at most one
lowest `compensating` or `compensation_blocked` frontier, then only
`compensated` records in ascending ordinal order. This enforces the reverse-
topological walk across records, not merely each record's local phase matrix.

`CompensationAuthorization` is the only serialized authority for a fresh or
public `compensate` invocation. Its Schema version is
`agent-equipment-compensation-authorization/v1`; its identity is
`compensation-authorization:` plus the canonical SHA-256 digest of the record
excluding `compensation_authorization_identity`. It binds `command: compensate`,
issuer and validity times, a fresh `compensation_nonce`, and a closed tuple of
the original apply-authorization identity/digest, execution-domain identity,
execution nonce, run identity, checkpoint-set digest, and plan-action-set
digest. The checkpoint-set digest is derived from the validated complete
manifest, never accepted as a caller echo. Its complete canonical digest is
supplied independently as
`trusted_compensation_authorization_digest`. It cannot start a forward action
or authorize another run. Immediate reverse compensation after a later failure
continues inside the already invoked, durably claimed apply run; it does not
mint or reuse this public authority. Each compensation-state checkpoint carries
`compensation_authority_kind`: `automatic_apply` preserves original-run
provenance, while `public_compensation` requires a separate closed transition
claim. That claim binds the immutable checkpoint identity and independently
validated compensation-authorization identity/digest and nonce; its canonical
identity and complete digest do not alter the immutable checkpoint identity.
All claim members must satisfy their closed string and digest formats, and a
checkpoint manifest containing any public claim is invalid unless the validator
received the independently validated non-null compensation-authority tuple.
After the compensation nonce is durably claimed, restart uses the archived
original authorization and pretransition checkpoint manifest plus the exact
durable ledger claim. It race-checks the current store and accepts only a
monotonic descendant with the same checkpoint identities, unchanged forward
invocation intent, strictly advanced record/store generations for changes, and
surviving claims bound to that original authority. This recovery mode has no new
clock or nonce check: the durable ledger claim is the continuation authority,
including the crash window before the first checkpoint transition. A
`compensation_blocked` descendant still requires separate operator disposition,
and public recovery cannot replace durable `automatic_apply` provenance.

`RunTerminalRecord` authenticates success for one exact apply tuple. It binds
the complete plan-action-set digest, validated checkpoint-set identity/digest
and store generation, and `state: succeeded`. Terminal validation requires one
unique completed checkpoint for every action in the complete plan-action set,
with durable generations increasing in canonical action order.
An early-crash checkpoint prefix may authorize compensation but cannot
authorize release. Terminal validation revalidates the exact capture-observation-
authority and prepared-action-authority sets against the tuple bound by the
validated apply authorization. The `run-terminal:` identity excludes identity and digest;
the complete digest excludes only the digest.

`ReleaseArchiveManifest` is a closed semantic manifest over the candidate and
installed implementation, exact execution binding including the execution
domain, complete plan-action-set digest, checkpoint-set identity/digest,
authenticated run-terminal identity/digest, launcher
identity/manifest, authority-store identity/key, `absent` compare token,
generation `1`, and eleven SHA-256 digests of the exact UTF-8 byte streams of
the authorization, complete plan-action set, captured-state manifest,
capture-observation-authority set, prepared-action-authority set, complete
checkpoint-store snapshot, checkpoint-set manifest, run-terminal record,
expected-case manifest, evidence bundle, and attestation. The sealed
checkpoint-store snapshot contains the ordered full durable records and is the
replay authority; the checkpoint-set manifest remains its closed projection.
Every checkpoint-store generation advance is a durable record write, so a
complete snapshot's `checkpoint_store_generation` must equal its maximum
`durable_generation`; a lower or higher generation is not the named store image.
Exact-byte digests are distinct
from semantic canonical digests: differently formatted JSON may have the same
semantic digest but different archive byte digests. The archive identity is
`release-archive:` plus the canonical digest of its payload; its manifest digest
is the canonical digest of the complete record excluding only
`archive_manifest_digest`.

`ReleaseReceipt` is terminal release evidence, never apply authority. Its
identity is `release-receipt:` plus the canonical digest of its closed payload.
That payload binds the independently trusted release-launcher identity and
manifest digest, exact candidate, installed implementation, execution binding
including the execution domain, plan-action-set digest, checkpoint-set
identity/digest, authenticated successful run-terminal identity/digest, archive
identity/digest,
store/key, and one create-only generation. A passed receipt cannot exist for a
compensated, blocked, or nonterminal run. A JSON object
with the same shape is not a receipt unless the independent launcher produced
it in the external authority's compare-and-swap archive.

## Runtime and launcher trust boundary

The production candidate requires CPython 3.12 or newer in isolated,
no-bytecode, and no-site mode. Before importing the candidate package, reading
a native manager, acquiring the apply lease, or opening the checkpoint store,
the installed wrapper requires `sys.implementation.name == "cpython"`,
`sys.version_info >= (3, 12)`, and the corresponding interpreter flags.
It computes the selected interpreter's implementation/version identity and
executable digest and requires both in the complete installed-implementation
manifest. A missing, older, changed, or non-CPython runtime fails before the
first action checkpoint and performs no harness mutation. The future
implementation may instead ship a pinned interpreter, but that interpreter's
complete installed bytes remain part of the same manifest binding.

The candidate-independent release launcher is a separately deployed,
root-owned executable outside the candidate package, candidate installed-
implementation manifest, and chezmoi `run_onchange` evaluation. It neither
imports candidate modules nor uses the candidate-selected interpreter. Its
caller supplies `trusted_release_launcher_identity` and
`trusted_release_launcher_manifest_digest` from the external release authority;
the launcher verifies its installed bytes before parsing candidate evidence.
Candidate code has no receipt-issuing or archive-commit capability. Release
consumers accept only a receipt retrieved with the matching generation from the
external authority store, never candidate output or a caller-selected path.

## Resolver interface

The production resolver should expose one deep, side-effect-free interface:

```text
resolve(command, catalog, lock, inventory, capabilities) -> resolution
```

`resolution` contains diagnostics, the expanded coverage matrix, the operation
matrix, generated overlays or authored proposals for the selected command, and
a mutation plan only for apply. Adapters do not select providers or rewrite
coverage outcomes.

Resolution phases are fixed:

1. Parse and structurally validate every input.
2. Bind the lock to the canonical catalog digest.
3. Expand distribution selections and coverage templates.
4. Require exactly one coverage record per identity and active harness.
5. Validate and apply the route's declared selective component controls against
   adapter capabilities.
6. Form only the remaining inseparable activation groups recorded by the route.
7. Resolve preferred and supplementary routes and bind overlap exceptions.
8. Validate route control, provenance, restore, operation, and compensation
   invariants.
9. Classify runtime state and manager-driven drift from observations.
10. Derive the selected command's report, proposal, or candidate action set.
11. Derive the complete action-dependency graph, including every required
    verification prerequisite and provider-switch dependency.
12. Reject a graph with a missing dependency, orphan action, cycle, or
    incomplete provider-switch dependency before returning any executable plan.
13. Produce a deterministic topological action order. Use the canonical
    equipment, harness, route, operation, and action-identity tuple only to
    break ties among actions whose dependencies are already satisfied.
14. Validate the complete result before returning any executable plan.

Every diagnostic has a stable code, equipment identity when applicable,
harness and route when applicable, a secret-free message, and evidence source.
An unresolved identity, incomplete route, invalid overlap, coverage-control
mismatch, stale lock, unknown capability needed by an automated operation,
operator-owned automated mutation, or missing compensation is fatal for apply.
Fatal validation yields no mutation plan.

The dependency graph is the ordering authority. An edge means a mutation
predecessor's post-state must be verified and its action checkpoint completed,
or a read-only verification predecessor's plan-bound evidence must be accepted
in the run journal, before the successor can start. A provider switch therefore includes explicit edges from verified
projector readiness to winner activation, from the winner's complete verified
active activation group to every losing-route retirement, and from all route
changes to final coverage verification. Existing desired winner state may
discharge an activation prerequisite only through a plan-bound fresh
observation; absence of a mutation does not erase the dependency.

The graph keeps active `equipment_identities` distinct from
`controlled_equipment_identities`. A disabled controlled identity with
`intentional_omission` / `no_provider` coverage can name a write surface and a
retirement dependency, but it is not evidence that the winner's active
activation group verified. Lexical ordering never substitutes for a dependency
edge. Reverse compensation uses the reverse topological order, so losing
projections are restored before the winner is disabled or uninstalled and the
legacy projector is restored last.

The validated plan binds the complete dependency edge set and its deterministic
topological result into `plan_digest`. A `PlannedAction.ordinal` is only the
sealed projection of that result; an action record or lexically sorted action
array cannot reconstruct or authorize a missing graph. The executor revalidates
graph closure, acyclicity, topological ordinals, and the required
winner-verification edges before it creates any checkpoint.

The graph has two closed node kinds:

- A `mutation` node references exactly one validated `PlannedAction`. It owns a
  durable action checkpoint and participates in reverse compensation.
- A `verification` node is read-only and has an identity
  `verification:sha256:<hex>` derived from its canonical definition excluding
  the identity and runtime result. That definition contains its purpose
  (`projector_readiness`, `winner_activation`, or `final_coverage`), exact
  candidate/catalog/lock/plan, route and capability bindings when applicable,
  active activation membership, read-surface scope, required normalized-state
  predicate or coverage predicate, and predecessor identities. The complete
  node definition and graph edges are included in `plan_digest`.

Executing a verification node produces a fresh, secret-free observation or
coverage report bound to the node identity, its predicate digest, the complete
plan bindings, and the exact predecessor result digests. The executor accepts
the node only when its read surfaces and predicate verify after every
predecessor mutation completed. It persists that evidence in the run journal,
not an action checkpoint, and performs no native mutation. A converged winner
therefore discharges its prerequisite through fresh plan-bound evidence without
creating a mutation checkpoint; final coverage uses the same rule. Reverse
compensation skips verification nodes while following the reverse topological
order of mutation nodes. A missing, stale, failed, or misbound verification
result blocks every dependent action.

## Coverage and operation invariants

A provider outcome uses an object-valued `provider_selection`; an omission or
unsupported outcome uses the exact string `no_provider`.

- `managed_provider` selects one preferred route and optional supplementary
  routes, all `reconciler_owned`.
- `manually_managed_provider` selects one preferred route and optional
  supplementary routes, with at least one `operator_owned` route.
- `intentional_omission` and `unsupported` select no active route.
- Every supplementary route is named by one matching `allow_overlap`
  exception. The exception lists the complete active route set and a rationale.
- Every active route has one provenance owner and one restore class. A
  standalone source owner is exactly `source:<distribution suffix>`; a native
  plugin owner is exactly `manager:<harness>-plugins/<plugin_id>`; a direct MCP
  owner is exactly `overlay:<harness>/mcp`; and a Claude projection uses only
  `projection:claude/standalone-skill`. A plausible but different source,
  manager namespace, plugin, or overlay is invalid.
- Every active route carries the exact selected component controls as unique
  equipment identity plus `enabled` or `disabled` state. Conflicting controls
  are invalid; an empty array states that no selective control applies.
- Every active route has exactly one disposition for every operation in the
  operation matrix.
- `suppress_native_update` is `unavailable` for `not_applicable` and
  `unsuppressible` routes; `operator_action` or `unavailable` while the route
  classification is `unknown`; and `automated`, `operator_action`, or
  `unavailable` only when the route is `suppressible`. Automated suppression
  retains the ordinary captured-pre-state compensation requirement.
- `operator_owned` routes are verify-and-report-only. Their mutating operations
  are `operator_action` or `unavailable`.
- Every automated mutating operation declares
  `restore_captured_pre_state`. The adapter capability record must support that
  compensation for the route and operation.

The required operation set is `inspect`, `install`, `configure`, `enable`,
`disable`, `remove`, `restore`, and `suppress_native_update`. Only `inspect` is
read-only. `repair` and provider switching are resolved sequences of these
operations rather than additional operation kinds.

## Command boundaries

| Command | Runtime reads | Network | Authored writes | Runtime writes |
| --- | --- | --- | --- | --- |
| `audit` | Yes | No by default | None | None |
| `import` | Yes | No by default | Emits a proposal only | None |
| `update` | Yes | Allowed for source resolution | Proposed atomic catalog and resolved-lock pair | None |
| `adopt` | Yes | No by default | Proposed catalog ownership transfer | None |
| `apply` | Yes | Allowed only for locked restore | Checkpoint and authorization ledgers only | Automated operations on reconciler-owned routes, after exact external authorization |
| `compensate` | Yes | No by default | Checkpoint and authorization ledgers only | Guarded restoration for one original run, after exact compensation authorization |

`import` does not claim ownership. `adopt` requires the exact imported
observation identity and changes authored ownership only; a later apply performs
any runtime reconciliation. `update` advances the catalog's resolved route
evidence and the digest-bound lock together for immutable revisions or reviewed
native-rolling baselines, without installing them. Apply never advances either
artifact.

Chezmoi's `run_onchange` integration invokes `audit` only. It can report a
candidate plan but cannot accept an authorization path or digest, open the
authorization ledger, create an action checkpoint, or invoke `apply`. An
explicit operator workflow invokes `apply` with exact authorization bytes and a
separately supplied `trusted_apply_authorization_digest`; neither value is read
from a template variable, candidate configuration, environment fallback, or
the authorization record itself. A later public `compensate` invocation has the
same closed-input rule for exact `CompensationAuthorization` bytes and
`trusted_compensation_authorization_digest`. It cannot reuse `ApplyAuthorization`.

An imported observation identity is the canonical digest of its surface,
observed-state digest, catalog digest, and inventory digest. Adoption accepts
only a previously emitted observation record whose identity, bindings, value,
and digest still agree; a newly constructed self-consistent record is not an
import reference. The production controller persists imported observations as
authored proposals, while the disposable acceptance fixture keeps the same
registry in memory.

## Adapter interface

Each production adapter should satisfy one internal seam:

```text
capabilities() -> capability records or discovery error
observe(request) -> runtime observation
apply(action, expected_pre_state) -> mutation receipt
verify(request) -> runtime observation
compensate(action, expected_post_state, captured_pre_state) -> mutation receipt
```

Requests carry only resolved route data and secret references. The runner
resolves secret references inside the child process boundary; adapters, logs,
diagnostics, lock diffs, and receipts never receive the resolved value.

The authoritative serialized shapes are
`docs/agent-equipment/adapter-contract-v1.schema.json`; the prose below defines
their behavioral semantics. Capability discovery wraps its capability records
in one closed success-or-error result; requests, observations, actions, and
receipts use closed tagged record envelopes. Every named field is required
unless this section says otherwise, and an unknown field is an error.
Their `contract_version` is `adapter-contract-v1`. Identifiers are non-empty,
secret-free strings; every `*_digest` is a lowercase SHA-256 digest over the
canonical JSON of the named object. A digest field is excluded from its own
digest input. Timestamps are RFC 3339 UTC values and never affect state
digests.

JSON Schema owns each serialized shape. The pure
`scripts/agent_equipment_adapter_contract.py` sequence validator additionally
accepts only one closed `ApplySequence` success proof. It binds the capability
selected from plural discovery to the route provider, recomputes digests whose
payloads are embedded, rejects conflicting component identities, and validates
the capture, action, receipt, and verification records against one authority
context. Individual valid records do not grant mutation authority.

Every fallible observation or mutation result uses the same tagged envelope.
An `ok` result contains only the success payload defined for that record. An
`error` result
contains `code`, `classification`, `message`, `retry`, `mutation_state`, and
`evidence_references`. `code` is stable and machine-readable;
`classification` is one of `invalid_request`, `unsupported`,
`capability_changed`, `concurrent_change`, `secret_resolution_failed`,
`native_failure`, or `partial_change`; `retry` is `never` or
`after_audit`; and `mutation_state` is `not_started`, `possibly_changed`, or
`unknown`. Observation failures use `not_started`. Capability discovery is
all-or-error: on discovery failure it returns this error envelope and no
partial records. Messages and referenced evidence are redacted by
construction. Native stdout, stderr, environment, and resolved secret values
are not record fields.

### `CapabilityRecord`

One record describes one adapter's support for one exact harness and route
family. `capabilities()` returns records sorted by harness, provider kind,
route-family selector, and capability identity. Capability discovery may run
only the manager's narrow, read-only version query needed to populate
`manager_version_evidence`; it is not permission to inspect equipment state or
mutate runtime state. The evidence record contains the manager identity,
observed version, observation source, and its canonical digest. Any changed
manager-version evidence changes the enclosing capability digest.

| Field | Contract |
| --- | --- |
| `contract_version` | Exact adapter record version. |
| `capability_identity` | Stable identity for this adapter and route-family capability; it does not change merely because a process restarts. |
| `adapter_identity`, `adapter_version` | Implementation provenance. The version identifies the exact executable implementation used for planning and execution. |
| `harness` | Exactly one of `claude`, `codex`, or `cursor`. |
| `provider_match` | A closed, secret-free selector over the catalog provider discriminant: standalone canonical root, native manager and scope, or direct-MCP transport and overlay family. Values are literal; regex and glob matching are forbidden. It never selects an equipment identity or preferred provider. |
| `manager_version_evidence` | Narrow read-only manager-version observation, source, and digest. The manager-version evidence digest is echoed separately by every request, observation, action, and receipt. |
| `surface_identity_rule` | Closed `rule` and `version`. V1 supports `shared_equipment_identity`, `route_and_equipment_identity`, and `route_identity`; it maps resolved identities to sorted logical surface identities without reading runtime state. |
| `operation_support` | Exactly one entry for each required operation. Each entry has `mode`; automated mutations additionally have `compare_before_mutate: true`, `idempotency: state_convergent`, and `compensation: restore_captured_pre_state`. |
| `component_control_support` | `mode`; exact `selector_granularity: equipment_identity`; sorted supported equipment identities; supported states drawn from `enabled` and `disabled`; and `mutation_boundary`, which is `selected_component` for automation and `none` otherwise. |
| `native_update_support` | `version_observation` and `baseline_comparison`, each `automated`, `inspect_only`, or `unavailable`; `native_update_control`, exactly `unknown`, `suppressible`, `unsuppressible`, or `not_applicable`; `suppression`, using any operation-support mode; and `suppression_scope`, exactly `route`, `manager`, or `none`. It distinguishes observing manager drift from preventing it. |
| `record_versions` | The exact `ObserveRequest`, `RuntimeObservation`, `PlannedAction`, `MutationReceipt`, and captured-state major versions accepted or emitted. |
| `automated_control_owners` | Exact one-element array `["reconciler_owned"]`. An adapter must never advertise automated mutation for `operator_owned`. |
| `capability_digest` | Digest of the complete record excluding this field. It binds resolution, plans, requests, receipts, and checkpoints. |

An operation-support `mode` is one of:

- `automated`: the adapter implements the operation. For `inspect` this is
  read-only; for every other operation the capability must declare the three
  mutation guarantees in the table.
- `inspect_only`: the adapter can observe and verify the state associated with
  the operation but cannot initiate it. The entry includes the exact normalized
  state fields it can observe.
- `operator_action`: the adapter can return a stable, secret-free description
  of an operator procedure, but cannot execute it. The entry includes a stable
  `operator_action_reference`, not an interpolated shell command.
- `unavailable`: the adapter can neither execute the operation nor claim an
  operator procedure. It may still report that the route or state is opaque.

Entries are closed by mode. Automated `inspect` has only `mode` and its
normalized observed fields. Automated mutations have `mode` and the three
guarantees above. Inspect-only and operator-action entries have only `mode` and
their respective field. Unavailable has only `mode`. The map contains exactly
`inspect`, `install`, `configure`, `enable`, `disable`, `remove`, `restore`,
and `suppress_native_update`.

Surface-identity rule v1 is exact. `shared_equipment_identity` emits one
`surface:shared/<equipment-identity>` per selected equipment identity;
`route_and_equipment_identity` emits one
`surface:<route-identity>/<equipment-identity>` per selected identity; and
`route_identity` emits only `surface:<route-identity>`. Identity strings are
used verbatim after the shown prefix, then sorted by Unicode code point. The
shared rule therefore maps the same canonical standalone entry to one surface
across harnesses. Requests and actions must carry exactly this derived list;
copying a coordinated but independently chosen scope through later records does
not grant access to that scope.

A catalog `automated` disposition requires an exact `automated` capability. A
catalog `operator_action` disposition accepts `operator_action` or
`inspect_only`; neither produces a `PlannedAction`. A catalog `unavailable`
disposition never produces an action even if a newer adapter could automate
it. Thus capability discovery can reject or report a route, but cannot broaden
its operation dispositions or change its provider selection.

### `ObserveRequest`

`observe` and `verify` receive the same request shape. A verifier accepts only
`verify_post_state` or `verify_compensation`; the executor derives that request
from the action or receipt, supplies a new request identity and exact expected
state digest, and preserves every binding without loss.
Automatic-compensation verification remains part of the original `apply`
command. `compensate` is reserved for a separately authorized public
`CompensationAuthorization` flow and is not an `ObserveRequest` command value.

| Field | Contract |
| --- | --- |
| `contract_version`, `request_identity`, `correlation_identity` | Record version, one-call identity, and command-run correlation identity. Recovery creates a new request identity under the same run correlation. |
| `command`, `purpose` | Command is `audit`, `import`, `update`, `adopt`, or `apply`; purpose is `inventory`, `capture_pre_state`, `verify_post_state`, `recovery`, or `verify_compensation`. Neither field grants mutation authority. |
| `candidate_identity`, `implementation_manifest_digest`, `catalog_digest`, `lock_digest`, `plan_digest` | Exact input bindings. Candidate identity names the immutable implementation candidate commit or artifact; the distinct manifest digest authenticates the canonical installed implementation manifest for that candidate. `plan_digest` is `null` only for non-apply inventory before a plan exists; the member and all other binding fields remain required. |
| `capability_identity`, `capability_digest`, `manager_version_evidence_digest` | Exact discovered capability and manager-version evidence selected by the resolver. A mismatch or disappearance is an error, not a fallback. |
| `harness`, `route_identity`, `route_digest`, `route_record` | The exact resolved route. `route_record` is complete and must digest to `route_digest`; its harness comes from the coverage record and its `control_owner` remains visible to the adapter. |
| `equipment_identities`, `controlled_equipment_identities`, `activation_group` | `equipment_identities` is sorted active activation membership. `controlled_equipment_identities` is the exact identity projection of `route_record.component_controls` and may include disabled would-be duplicates whose coverage is `intentional_omission` / `no_provider`. Neither set implies membership in the other. |
| `surface_scope` | Sorted logical surface identities that the adapter may read, derived from the union of active and controlled identities. Native paths, keys, plugin IDs, or server names derived by the adapter must remain within this scope. |
| `secret_references` | The route's unresolved environment-variable or secret-profile references. The adapter validates names; only the runner resolves values inside the native child boundary. |
| `expected_state_digest` | Optional only for inventory and pre-state capture. Required for post-state, recovery, and compensation verification. |

An observation request is idempotent and read-only. Repeating it against
unchanged runtime state must produce the same normalized state digest even when
timestamps, native ordering, or non-semantic manager output differ.

### `RuntimeObservation`

The observation echoes `contract_version`, `request_identity`,
`correlation_identity`, candidate identity, installed implementation-manifest
digest, all other available input digests, capability identity,
manager-version evidence digest, harness, route identity, route digest, control
owner, active and controlled equipment identities, activation group, and
surface scope. It adds
`observed_at` and a tagged `result`.

An `ok` result contains one closed `normalized_state` payload plus observation
evidence and capture metadata. `state_digest` is recomputed from exactly that
payload; timestamps, surface-evidence storage, and captured-state object
metadata are outside the payload. Its fields are:

| Field | Contract |
| --- | --- |
| `route_presence` | `present`, `absent`, `partial`, or `unknown`. Partial and unknown are never silently normalized to absence. |
| `enablement` | `enabled`, `disabled`, `mixed`, `not_applicable`, or `unknown`. |
| `configuration` | Tagged `observed` with the digest of the adapter-owned normalized configuration, or tagged `not_applicable` or `unknown`; never raw secret-bearing configuration. |
| `component_states` | Sorted exact equipment-identity records with `enabled`, `disabled`, `absent`, or `unknown`. The list covers every selected control and does not invent controls. |
| `observed_version` | Tagged `observed` with a value, `route_absent`, or `unknown`. Unknown version makes a native-rolling route ineligible for mutation and cannot be written as captured-state restore evidence. |
| `native_update_control` | Route classification: `unknown`, `suppressible`, `unsuppressible`, or `not_applicable`. It echoes the reviewed route classification; it is not observed toggle state. |
| `native_update_suppression_state` | Observed toggle state: `enabled`, `disabled`, `unavailable`, `unknown`, or `not_applicable`. This does not claim suppression can be automated. |
| `manager_drift` | `none`, `changed_from_reviewed_baseline`, `unobservable`, or `not_applicable`, with the reviewed baseline and observation source when applicable. The resolver, not the adapter, decides the command consequence. |
| `surface_evidence` | Sorted secret-free references and digests for every surface read, including absence evidence. |
| `captured_state` | Tagged `captured` with a reference to a validated `captured-state-v1` object when purpose is capture or recovery, or tagged `not_applicable`. |
| `state_digest` | Canonical SHA-256 digest of the embedded complete `normalized_state` payload. |

An error result carries the common error shape and echoes the same identities
and bindings. It has no `state_digest`, and cannot be interpreted as absence,
an empty component set, or permission to proceed.

The two native-update fields have one interpretation: `not_applicable` control
maps to `not_applicable` state; `unsuppressible` maps to `unavailable`;
`suppressible` may be `enabled`, `disabled`, `unknown`, or `unavailable` when
the setting cannot be observed; and `unknown` control may report only
`unknown` or `unavailable`. The adapter-contract schema rejects other pairings
even when each leaf value is individually well formed.

### `PlannedAction`

Only the resolver creates planned actions, only after complete-plan validation,
and only for a route operation whose catalog disposition and matching adapter
capability are both `automated`. The record contains:

| Field | Contract |
| --- | --- |
| `contract_version`, `action_identity`, `correlation_identity`, `ordinal` | Version; canonical `action:sha256:<digest>` identity derived from plan digest, ordinal, route, operation, and desired-state digest; run correlation; and unique deterministic topological execution order. |
| `candidate_identity`, `implementation_manifest_digest`, `catalog_digest`, `lock_digest`, `plan_digest` | Immutable implementation and plan bindings. Candidate identity and the distinct installed implementation-manifest digest must both match executor trust inputs; any mismatch invalidates the whole plan before checkpointing. |
| `capability_identity`, `capability_digest`, `manager_version_evidence_digest`, `adapter_identity`, `adapter_version` | Exact implementation capability and manager-version evidence used to derive the action. Substitution requires re-resolution and a new plan. |
| `harness`, `route_identity`, `route_digest`, `route_record` | Complete selected route and digest. `route_record.control_owner` must be `reconciler_owned`. |
| `equipment_identities`, `controlled_equipment_identities`, `activation_group`, `surface_scope` | Sorted active membership, the exact identity projection of selected component controls, and surfaces derived from their union. A disabled `no_provider` duplicate is controlled without becoming active coverage. One activation group maps to one route identity per harness. |
| `operation`, `operation_disposition` | One required operation and the exact value `automated`. Inspect is never emitted as a mutating action. |
| `desired_state`, `desired_state_digest` | Non-empty, closed, secret-free normalized target fragment and its digest. It may contain only route presence, enablement, normalized configuration digest, selected component states, and native-update suppression state. |
| `secret_references` | Unresolved references copied from the route; no value or value-derived digest is allowed. |
| `preconditions` | Exact candidate, installed implementation-manifest, catalog, lock, plan, route, capability, adapter, ownership, activation-group, and surface bindings; `prepared_checkpoint_required: true`; and `compare_before_mutate: true`. The executor supplies the captured pre-state digest separately to `apply`. |
| `compensation` | Exact `restore_captured_pre_state`, plus the captured-state version required by the capability. |

The action is a declaration, not runtime authority by itself. Execution also
requires an apply command, the still-valid complete plan, a durable prepared
checkpoint, and a current observation equal to the executor-supplied expected
pre-state digest. A planned action is immutable. A changed desired state,
capability, adapter version, activation-group membership, or surface scope
requires a new action identity and plan digest.

Every action in one complete plan-action set binds the same catalog and lock
digests. A self-consistent action and set reseal with a different catalog or lock
on any later action is foreign authority and invalidates the whole set.

The identity digest is the SHA-256 of canonical JSON for exactly
`plan_digest`, `ordinal`, `route_id` (from `route_identity`), `operation`, and
`desired_state_digest`. This is the same formula used by the closed
`agent-equipment-plan-action-set/v1` projection. The adapter validator
recomputes it before a sequence can authorize mutation.

### `ApplySequence`

`ApplySequence` is the public semantic-validation boundary for one successful
apply or compensation attempt. Its closed `sequence` contains one authority
context, capability discovery, pre-state request and observation, planned
action, mutation receipt, and post-state request and observation. The executor
creates the authority context from already validated plan inputs, a validated
captured-state object, and a durably prepared checkpoint before it invokes the
adapter. It appends the receipt and verification records, then validates the
complete success proof before marking the checkpoint completed or compensated.
The validator requires the candidate identity and installed implementation-
manifest digest as separate operator-invocation trust inputs; it never derives
them from the sequence it is validating. Omitting either input,
or presenting an internally consistent sequence for a different candidate,
fails before the proof can authorize a checkpoint transition.

The authority context binds the exact apply command and phase-appropriate
capture or recovery purpose; request, action, and correlation identities; all
candidate, installed implementation-manifest, catalog, lock, plan, capability,
manager-version, adapter, harness,
route, active and controlled equipment, activation-group, and operation fields;
independently derived read and write surfaces; selected route controls;
captured-state object identity and digest; the embedded captured normalized
pre-state and its canonical digest; immediate expected pre-state guard; the
embedded expected normalized post-state and its canonical digest; the forward
post-state digest; and prepared-checkpoint reference. Post-state
verification must use the same route, equipment, surfaces, and unresolved secret
references as the action. A different self-consistent route is not valid
verification of that action.

The validator independently derives surfaces from the selected capability and
the union of active and controlled identities,
requires every route control to appear exactly once in desired component state,
and requires exact automated selected-component support. It also requires
successful observations with exact component and per-surface evidence coverage,
the route's native-update classification, an equal mutation pre-state guard,
complete mutation evidence, an equal post-verification digest, and explicit
post-observation fields that agree with every target fragment embedded in the
action. A failed receipt remains a valid standalone record but cannot form an
`ApplySequence` success proof.

This proof is not an external trust root. The semantic validator requires the
executor to supply the independently trusted current candidate identity and
installed implementation-manifest digest; neither value is learned from the
sequence. It rejects a self-consistent sequence whose implementation bindings
do not match those inputs. The production executor still proves that the plan
and checkpoint digests name its validated local artifacts and that the
checkpoint is durable. JSON Schema validation alone proves only closed shape,
not installed-implementation trust. `RuntimeObservation.state_digest`,
`captured_pre_state_digest`, and `expected_post_state_digest` are recomputed
from their embedded normalized-state payloads. `captured_state_digest` remains
the separate digest of the complete captured-state object. Apply binds the
captured normalized pre-state to the capture observation and verifies that the
desired action fragment matches the full normalized post-state. Compensation
restores that captured state, while its immediate guard equals the canonical
full forward-post state digest, not the partial `desired_state_digest`.

### `MutationReceipt`

`apply` and `compensate` return the same receipt envelope. It echoes
`contract_version`, action and correlation identities, ordinal, candidate and
installed implementation-manifest bindings, all plan and
capability bindings, adapter identity and version, harness, route identity and
digest, control owner, active and controlled equipment identities, activation group, surface scope,
operation, operation disposition, and `secret_references` as names only. It
adds `receipt_identity`, `attempt_identity`, `phase` (`apply` or
`compensate`), `started_at`, `finished_at`, `prepared_checkpoint_reference`,
and a tagged result.

The closed success proof uses UTC RFC 3339 timestamps ending in `Z` and requires
`pre_state_observation.observed_at <= started_at <= finished_at <=
post_state_observation.observed_at`. Equality is allowed for clocks whose
resolution coalesces adjacent events; any reversal, naive timestamp, or
non-UTC offset fails the sequence.

An `ok` result contains `effect` (`changed` or `already_satisfied`), the
expected and immediately observed pre-state digests, `comparison: equal`, the
observed post-state digest, secret-free native-result and surface-evidence
digests, and compensation evidence. Apply compensation evidence binds the
captured pre-state reference and declares `restore_captured_pre_state`;
successful compensation additionally proves that the restored state digest
equals `captured_pre_state_digest`, not the captured-state object digest. A
receipt reports adapter effects only;
the executor still calls `verify` and durably records `completed` or
`compensated` before treating the effect as accepted.

| Success field | Contract |
| --- | --- |
| `effect` | `changed` or `already_satisfied`; neither implies executor verification. |
| `expected_pre_state_digest`, `observed_pre_state_digest`, `comparison` | Echo the executor guard, the adapter's immediate pre-invocation observation, and exact `equal`. |
| `expected_post_state_digest`, `observed_post_state_digest` | For apply, the canonical full normalized post-state matching every desired fragment; for compensation, the canonical captured normalized pre-state. The immediate post-invocation observation must equal that phase-specific full-state target. |
| `native_result_digest` | Digest of normalized, redacted status fields only; raw or secret-derived native output is excluded. |
| `surface_evidence` | Sorted secret-free references and digests for every surface the invocation could affect. |
| `compensation_evidence` | For apply: tagged `prepared` with `restore_captured_pre_state`, captured-state reference and digest, and expected-post-state digest. For compensate: tagged `restored` with the same bindings, restored-state digest, and `comparison: equal`. |

An error result uses the common error shape and includes the expected and
observed pre-state digests when observation succeeded, any observed post-state
digest, and secret-free evidence. A pre-state mismatch is
`concurrent_change` with `mutation_state: not_started`. A native failure after
invocation is `native_failure` or `partial_change` with
`mutation_state: possibly_changed` or `unknown`; the executor stops and audits
before retry or compensation. An adapter must never return `ok` after a
compare-before-mutate mismatch.

`action_identity` is the idempotency key. Repeating an observation is safe;
repeating a mutation is permitted only after checkpoint recovery observes the
captured pre-state. If recovery observes the expected post-state, the executor
records completion without replay. An adapter invoked on already satisfied
state may return `already_satisfied` only when that state also satisfies the
action's explicit precondition; it cannot use that result to hide concurrent
change.

Selected `component_controls` are desired route state, while adapter capability
records say whether the harness can realize each control. The resolver rejects
a selected control without an exact supported capability before it returns an
executable plan. Adapters do not silently broaden a control to a whole plugin.
When the route selects component controls, desired component state must contain
every selected control exactly once and no others. Each must name selected
action equipment, exactly match the route state, and be covered by an
`automated` capability with `selected_component` mutation boundary and exact
identity and state support. Recomputed route, capability, action, or plan
digests do not broaden this authority.

Adapters may mutate only the surface named by an automated action. They preserve
unrelated keys and native state, compare the current observation with the
expected observation immediately before mutation, and return observed evidence
rather than changing the provider selection.

### Route and control capability matrix

This matrix is the v1 implementation baseline, not evidence that a capability
exists on the current machine. Each adapter must emit the narrower live
`CapabilityRecord`; it cannot promote a catalog disposition. `A` means the
adapter may advertise automated support after its exact contract is proven;
`I` means inspect and verify only; `O` means operator action only; and `U`
means unavailable. A slash means the exact route, manager version, or selected
control decides between the listed modes and the capability record must choose
one. `Controls` covers per-equipment plugin or standalone-suppression state;
`Update` covers `suppress_native_update`, separately from version observation.

| Route or control surface | Inspect | Install | Configure | Enable | Disable | Remove | Restore | Controls | Update |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Shared standalone skill under `~/.agents/skills` | A | A | U | U | U | A | A | U | U |
| Claude skill projection symlink | A | A | U | U | U | A | A | U | U |
| Claude native plugin | A | A | U | A | A | O/U | U | I/O/U | O/U |
| Claude direct-MCP owned overlay | A | U | A | A | A | A | A | U | U |
| Codex native plugin | A | A | A | A | A | O/U | U | A/I/O/U | U |
| Codex standalone-skill disable entry | A | U | A | A | A | A | A | A | U |
| Codex direct-MCP owned overlay | A | U | A | A | A | A | A | U | U |
| Cursor native plugin | A/U | O/U | O/U | O/U | O/U | O/U | U | O/U | U |
| Cursor standalone-skill suppression | A/U | U | U | U | U | U | U | U | U |
| Cursor direct-MCP owned overlay | A | U | A | A | A | A | A | U | U |

The shared standalone adapter owns the canonical entry once, not one copy per
harness. Claude projection and Codex suppression are separate control-surface
adapters and never rewrite that canonical entry. Cursor standalone suppression
remains unavailable until a stable public control surface is proven; discovery
alone does not authorize an application-database edit.

Complete-plan validation permits at most one mutating action for a logical
surface. When several harness routes require the same canonical standalone
state, the resolver coalesces an otherwise identical operation under the first
route in the fixed plan order and emits read-only verification for every
dependent route. Different desired states, surface preconditions, or operations
over an overlapping surface are fatal. Coalescing changes neither route
coverage nor provenance; it only prevents duplicate writes and checkpoints.

For direct MCP, `configure`, `enable`, `disable`, `remove`, and `restore` are
narrow overlay transitions over the exact server entry. `install` remains
unavailable because package acquisition is a locked provider argument, not a
separate runtime surface. JSON and TOML adapters preserve unrelated keys and
plugin-provided effective servers. Stdio and HTTP transports use the same
record contracts; only their provider selector and normalized evidence differ.

For native plugins, component control is independent of whole-plugin
enablement. The capability record lists each selected equipment identity and
state it can realize. If one selected control is only inspectable or operator
owned, the resolver must use that narrower mode or reject an automated route;
it must not broaden the action to the activation group or whole plugin.
Similarly, version observation may be automated while update suppression is
operator-only or unavailable. An observed version outside the reviewed rolling
baseline is manager-driven drift; `update` may propose a reviewed baseline
advance, while `apply` neither advances the baseline nor assumes suppression.
Native-rolling plugin removal is operator-only or unavailable unless the live
capability proves that the captured artifact can be reconstructed exactly,
independently of a moving marketplace channel or cache. Compensation for an
installation that began from confirmed absence may remove that newly installed
instance; that narrow absence restore does not make general plugin removal an
automated route capability.

Every row is further constrained by route ownership. `operator_owned` routes
may use automated `inspect` but all mutating cells become `I`, `O`, or `U`,
regardless of what the native manager can technically do. Capability or native
manager drift after resolution invalidates the plan; adapters never select a
different row as a fallback.

### Adapter contract compatibility

Adapter-contract majors are independently versioned from catalog, lock,
captured-state, and evidence majors. A producer and consumer must agree on the
exact record major and on every `record_versions` entry before resolution. V1
records are closed shapes: an added, removed, renamed, or reinterpreted field;
a changed enum; a changed canonicalization rule; or weaker precondition,
ownership, idempotency, compensation, or redaction semantics requires a new
major. A catalog-schema change requires a new adapter-contract major only when
the resolved route projection or any adapter semantic changes.

Changing `adapter_version` or any live capability produces a new
`capability_digest`. Existing observations may remain historical evidence, but
existing plans, actions, and prepared checkpoints cannot execute under the new
digest. There is no implicit downgrade, field dropping, or best-effort record
conversion. A future converter must be pure, explicit, one major at a time,
and produce reviewable before-and-after records; apply never converts records.

## Apply and recovery interface

The executor should expose one deep interface:

```text
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
) -> apply_report

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
) -> compensation_report
```

The executor first validates `ApplyAuthorization`, then takes the expected
capture-observation-authority identity/digest from its closed bindings. Every
public validation path receives that expected tuple together with the exact
`CaptureObservationAuthoritySet` artifact. The former raw observation-list and
caller-supplied observation-digest API does not exist. Compensation recovery
uses the same tuple from the archived, revalidated apply authorization.

Before the first action checkpoint, the executor rejects a raw authority input
larger than 256 KiB before UTF-8 decoding, JSON parsing, regex evaluation,
credential scanning, or hashing. It strictly parses UTF-8 JSON, rejects
duplicate members, non-finite numbers, and non-JSON values, then validates the
closed `ApplyAuthorization`. Each parsed-object authority validator first
canonicalizes only to enforce the same 256 KiB ceiling before Schema, regex,
credential, or digest work; UTC fractional seconds are limited to nine digits.
The release replay boundary retains that 256 KiB ceiling for each ordinary
execution-authority record but gives the aggregate plan-action-set,
captured-state, full checkpoint-store-snapshot, expected-case, evidence-bundle,
and attestation streams separate 16 MiB raw and canonical byte ceilings. Each
raw-byte ceiling is enforced before UTF-8
decoding or parsing. After strict parsing, the parsed object is canonicalized
only to enforce its corresponding canonical ceiling before Schema, regex,
credential, or digest work.
The executor
validates its Schema and semantic digest/identity formulas, and requires its complete
tuple to equal the independently validated local artifacts and
`trusted_apply_authorization_digest` plus the trusted operator-review-package
digest. Its top-level `execution_domain_identity` must equal
`trusted_execution_domain_identity` and identify the same authoritative ledger
namespace and CAS target used for the nonce claim. It requires
`issued_at <= not_before <= trusted_clock.now < expires_at`, exact command,
issuer, and run identity, and the same post-authorization live comparison
required by the capture contract. It then exclusively creates an
authorization-ledger record in that execution domain for the execution nonce,
authorization digest, and run identity, fsyncing file and parent directory. A
claimed nonce, expired window, missing field, foreign tuple or execution domain,
digest mismatch, or ledger persistence failure rejects the run before the first
action checkpoint and performs zero adapter calls.

The nonce claim is never deleted or reused. A crash recovery may use an existing
claim only for the same authorization digest, run, and surviving checkpoints;
it may compensate or finish an already invoked action. It cannot create the
first checkpoint, start a new planned action after authorization expiry, or
turn the claimed nonce into authority for a new run. A fresh apply requires a
new external authorization and nonce. The executor otherwise refuses an
unvalidated or digest-mismatched plan. It does not promise global atomicity. For
every action it:

1. Audits and captures the exact pre-state.
2. Derives the expected post-state and compensation from adapter capabilities.
3. Atomically persists and fsyncs a `prepared` checkpoint before mutation.
4. Compares current state with the captured pre-state.
5. Atomically advances and fsyncs the checkpoint's invocation intent from
   `not_started` to `started`. A failed intent write forbids the adapter call.
6. Executes the action.
7. Verifies the expected post-state.
8. Atomically persists and fsyncs `completed`.

On a later failure, completed actions compensate in reverse topological order.
This automatic reverse walk is recovery continuity for actions already invoked
inside the claimed apply run; it does not open the public `compensate` seam or
reuse the apply record as new authority.
Before each restore, current state must equal the post-state written by that
action. The executor persists `compensating` before restore and `compensated`
afterward. A mismatch preserves the external change, durably advances that
action to terminal `compensation_blocked`, marks the run `needs_operator`, and
stops. Recovery never reports success while any action is blocked.

A surviving `prepared` checkpoint is audited before retry. Expected post-state
can prove this run's effect only when its durable invocation intent is
`started`:

- observed pre-state: the mutation did not take effect and may be retried after
  persisting a new invocation intent;
- `started` plus observed expected post-state: record completion without replay;
- `not_started` plus observed expected post-state: preserve it as concurrent
  target-valued drift; never complete or compensate it as this run's effect;
- any other state: preserve it, report concurrent or partial drift, and stop.

A completion-checkpoint write failure therefore cannot cause duplicate replay.
A compensation failure remains durable and requires the same audit before a
retry. A fresh/public compensation request, including classification of an
ambiguous `prepared` action before beginning restoration, first validates the
closed `CompensationAuthorization`, its independently trusted digest and clock,
the trusted execution domain, original execution tuple, checkpoint-set digest,
plan-action-set digest, and fresh compensation nonce. It durably claims that
nonce in the same execution domain before writing `compensating`; an invalid,
expired, replayed, foreign-domain, or unpersistable record performs no adapter
call or checkpoint transition.
Once that nonce claim is durable, recovery validates the archived original
authorization and checkpoint manifest, its independently trusted ledger claim,
and the current race-rechecked descendant store. It resumes under the surviving
original claims without a fresh clock check, including a crash before the first
checkpoint transition or after a direct `prepared` to `compensating` write.
Forward invocation intent cannot change during this walk, every changed record
and store uses a strictly newer generation, and `compensation_blocked` stops for
operator disposition.

Checkpoint identities bind the apply-authorization identity and digest,
execution-domain identity, execution nonce, canonical catalog digest, lock digest,
plan digest, run and candidate identities, installed-implementation manifest
digest, sealed captured-state identity and digest, capability-set digest, route
capability and manager-evidence binding, action identity and ordinal, route,
operation, pre-state digest, and expected post-state digest. This is the
complete `CHK-10` binding; no subset or claim in another execution domain
authorizes replay. A compensation checkpoint additionally records the exact
authority kind. Automatic rollback records `automatic_apply` and preserves the
original apply provenance. A transition through the public seam records
`public_compensation` plus a separate immutable transition claim whose identity
and digest bind the checkpoint identity and independently validated
compensation-authorization identity/digest and nonce. A missing, foreign, or
self-consistently resealed claim fails before transition.

## Generated outputs

Generated overlays are proposals until apply. They contain owned fields only,
with provenance back to the route and catalog digest. Diagnostics and diffs
redact values by construction because the resolver accepts secret references,
not secret values.

The acceptance matrix in `ACCEPTANCE.md` is the release gate for production
implementation. The sequenced work and exact retained/retired source map are in
`IMPLEMENTATION_HANDOFF.md`.

The release evidence writer may write only the expected-case manifest and
candidate evidence bundle in the operator-selected artifact directory. It does
not mutate authored state or harness state. After the run, the external release
authority supplies the trusted digest of a separate attestation over the
canonical semantic bundle digest. The release validator is pure. The
candidate-independent release
launcher supplies its own externally trusted identity and manifest digest plus
the trusted execution tuple, including the execution domain, apply-authorization,
expected-case, and attestation digests. It strictly parses the eleven exact
release inputs, recomputes all eleven archive byte digests solely from those
streams, and validates the closed records. For the historical apply
authorization, release rechecks its closed schema, canonical identity and
trusted digest, execution tuple, and every binding derivable from the replay
streams. It does not rerun the apply-time issuer, clock-window, or nonce-claim
gates: those inputs are unavailable at release, and later expiry cannot make a
completed run unarchivable. It writes the exact
authorization, plan-action set, captured-state manifest,
capture-observation-authority set, prepared-action-authority set,
checkpoint-store snapshot, checkpoint-set manifest, run-terminal record,
expected-case manifest, evidence bundle, attestation, and archive manifest into
a same-filesystem staging directory, fsyncs them, and performs one create-only
compare-and-swap rename to the tuple's authority-store identity. `absent` is the
only first-write compare token and generation `1` is the only first committed
generation. An existing byte-identical generation is an idempotent read; an
existing different generation is a conflict. Only after the archive commit is
durable does the launcher emit the closed `ReleaseReceipt`. Candidate code
cannot mint, overwrite, skip, or treat absence of that receipt as success. No
release document grants apply or migration authority.

The checked-in `initial-catalog.proposed.json` and
`initial-lock.proposed.json` exercise this serialized contract with 44 accepted
identities, 132 complete coverage records, nine resolved distributions, and 23
owned losing surfaces. Their `.proposed.json` suffix is normative: neither
artifact is installed under the production source path or consumed by chezmoi
apply.

## Schema evolution

Catalog, lock, captured-state, plan-action-set, capture-observation-authority-set,
prepared-action-authority-set, apply-authorization, compensation-authorization,
compensation-transition-claim, checkpoint-store-snapshot, checkpoint-set,
run-terminal, evidence,
attestation, release-archive-manifest, and release-receipt formats use
independent explicit major versions. Adding an
optional field with unchanged meaning may remain in
the current major version only when old readers reject or safely ignore it by
contract; these v1 schemas use exact shapes, so additions normally require a
new major version. Renaming a field, changing an enum or default, weakening an
invariant, or changing canonicalization always requires a new major version.

An update implementation must provide a pure, deterministic migration from the
immediately previous version, emit a reviewable semantic diff, bind a newly
generated lock to the migrated catalog digest, and validate the result before
authored files change. Apply never migrates schemas. Unsupported future
versions fail closed. A production release retains golden old-version fixtures
and round-trip or one-way migration evidence for every supported transition.
