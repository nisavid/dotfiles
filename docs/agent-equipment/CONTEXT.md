# Global Agent Equipment

This context describes portable desired state for skills, plugins, MCPs, and
other equipment exposed through global agent harnesses.

## Language

**Equipment identity**:
A typed, namespaced identity for one logical skill, MCP server, hook, or other
agent component independent of its packaging.
_Avoid_: Package name, command name

**Distribution**:
An installable bundle that supplies one or more equipment identities.
_Avoid_: Equipment, capability

**Provider route**:
One concrete route by which a distribution supplies an equipment identity to a
harness.
_Avoid_: Package, projection

**Provider selection**:
One preferred provider route plus zero or more explicitly allowed
supplementary routes for an equipment identity in one harness. Every member is
an active provider route.
_Avoid_: Inferred overlap, interchangeable providers

**Harness coverage outcome**:
The single declared result for an equipment identity in one harness. Its exact
serialized literal is `managed_provider`, `manually_managed_provider`,
`intentional_omission`, or `unsupported`.
_Avoid_: Operation capability, provider preference

**Harness coverage record**:
The complete record for one equipment identity in one harness: exactly one
harness coverage outcome plus either a provider selection for a provider
outcome or the exact `no_provider` value for `intentional_omission` and
`unsupported`.
_Avoid_: Bare coverage outcome, single provider route

**Coverage template**:
An authored, named harness coverage record expanded for every identity selected
from one distribution. An exact identity-and-harness record replaces a
template as a whole.
_Avoid_: Partial override, inferred default

**Operation disposition**:
The declared capability of an active provider route for one operation. Its
exact serialized literal is `automated`, `operator_action`, or `unavailable`.
_Avoid_: Harness coverage outcome, manual provider

**Route control owner**:
The authority allowed to mutate runtime state through an active provider route.
Its exact serialized literal is `reconciler_owned` or `operator_owned`.
_Avoid_: Provenance owner, artifact owner

**Provenance owner**:
The one source or native manager responsible for the artifact and restore
evidence of an active provider route. It is an exact reference derived from the
selected distribution and provider, not a free-form label within the same
manager or source namespace.
_Avoid_: Logical package owner, runtime cache

**Restore class**:
The strength of a provider route's restore claim: `immutable` identifies
verified reproducible content, while `native_rolling` identifies a manager
channel whose exact prior artifact cannot be promised.
_Avoid_: Version, update policy

**Native-update state**:
The explicit update-control claim on every active route. It is
`not_applicable` for immutable controller-restored content, or `unknown`,
`suppressible`, or `unsuppressible` for a native-rolling manager route.
_Avoid_: Restore class, observed version

**Secret reference**:
An environment-variable name or opaque `secret-exec` profile name that lets an
adapter locate credentials without serializing their values.
_Avoid_: Secret value, credential file path

**Activation group**:
The smallest set of equipment that a harness or distribution activates as one
unit after every supported selective component control is applied.
_Avoid_: Plugin, distribution

**Component control**:
One explicit enabled or disabled equipment-identity selection applied on a
provider route before the remaining activation group is formed. The route
records desired control state; adapter capabilities prove whether the harness
can realize it.
_Avoid_: Operation disposition, inferred plugin atom

**Authored catalog**:
The repo-owned desired state that declares distributions, identities, coverage,
provider routes, ownership, restore claims, and explicit exceptions.
_Avoid_: Inventory, native lock, runtime config

**Resolved lock**:
The generated, catalog-digest-bound snapshot that expands selections and
templates into exact equipment identities and complete harness coverage
records.
_Avoid_: Native manager lock, cache

**Source tracking policy**:
The authored rule that chooses what `update` follows. A Git source follows its
current default branch unless the catalog names one branch. A native-manager
source follows `latest` unless the catalog names one channel. It never stands
in for an exact resolved revision or version.
_Avoid_: Lock entry, resolved source, restore evidence

**Source resolution**:
The update-time, read-only act of resolving one authored tracking policy to an
exact revision or typed version, optional immutable content digest, and complete
authoritative equipment listing. The source resolver returns only those closed
facts; it cannot author source policy, restore policy, selected membership, or a
Source Manifest. Source resolution is not runtime equipment observation and
does not install the result.
_Avoid_: Status observation, apply, package installation

**Source resolution facts**:
The closed, request-bound public facts returned by a source resolver: exact
revision or typed version, immutable content digest when applicable, and the
complete authoritative equipment listing. The controller combines them with
reviewed policy from the validated base; unrestricted prose is never a source
resolution fact.
_Avoid_: Source Manifest, restore policy, resolver-authored metadata

**Source Manifest**:
One controller-constructed, canonical, digest-bound resolved distribution
record containing its reviewed source tracking policy, exact resolved source,
complete available equipment, controller-derived membership-evidence digest,
selected equipment, and reviewed restore policy combined with resolved facts.
_Avoid_: Authored catalog, runtime inventory, package-manager lock

**Historical Source Manifest**:
An unchanged prior Source Manifest retained in the resolved lock because a
retirement still binds its exact provider and restore evidence. History
contains every such non-current manifest and no unreferenced manifest.
_Avoid_: Current source resolution, orphan history

**Runtime observation**:
A secret-free factual statement of equipment state reported through a
supported file, CLI, or harness surface. It never claims ownership or proposes
authored state.
_Avoid_: Desired state, proposal

**Unmanaged equipment**:
Equipment positively observed on the machine but absent from the authored
catalog. A cataloged operator-owned route is not unmanaged.
_Avoid_: Unknown runtime state, manually managed provider

**Unmanaged observation record**:
A canonical, secret-free runtime observation record emitted for unmanaged
equipment. It is factual evidence, not a catalog proposal or ownership claim.
_Avoid_: Catalog addition proposal, desired state

**Catalog addition proposal**:
One atomic, reviewable pair containing the complete proposed authored catalog
and resolved lock after adding positively observed unmanaged equipment. It does
not change runtime state.
_Avoid_: Unmanaged observation record, runtime mutation

**Immutable-content observation**:
A tagged runtime statement that an immutable route is absent, unknown, or at
one freshly verified revision and content digest; native-rolling routes mark it
not applicable. It never treats an echoed restore claim as observed evidence.
_Avoid_: Observed version, configuration digest, requested content digest

**Mutation plan**:
A fully validated, deterministically ordered set of reconciler-owned automated
operations derived from one authored catalog, resolved lock, and runtime
inventory.
_Avoid_: Status report, adapter command list

**Checkpoint**:
A durable record that binds one planned mutation to its captured pre-state,
expected post-state, and current execution phase.
_Avoid_: Log entry, global transaction

**Compensation**:
A declared route operation that restores the captured pre-state after a later
failure, subject to compare-before-restore.
_Avoid_: Best-effort cleanup, rollback claim

**Apply authorization**:
An externally issued, time-bounded, one-run grant to execute `apply` for one
exact candidate, desired-state, plan, capability, capture, and expected-case
binding tuple.
_Avoid_: Plan approval, release attestation, candidate-authored permission

**Prepared action authority set**:
The sealed, complete pre-invocation projection of every validated plan action's
adapter-derived normalized pre-state and expected post-state. It binds the
complete plan, capability set, sealed capture, exact controlled-component set,
and per-action operation and compensation context before apply authority is
issued.
_Avoid_: Caller state map, partial checkpoint prefix, post-mutation observation

**Capture observation authority set**:
The sealed, complete normalized pre-state projection for every action in one
captured plan. Its exact identity and digest are granted by apply authority.
_Avoid_: Raw observation list, caller state map, self-authenticating capture

**Execution nonce**:
The issuer-generated one-time identity that prevents one apply authorization
from starting another run.
_Avoid_: Run identity, checkpoint ordinal

**Execution domain identity**:
The independently trusted identity of the one authoritative compare-and-swap
nonce-ledger namespace and target in which an execution nonce may be claimed.
It follows the authorized run through evidence, checkpoints, archives, and
receipts so a claim in another ledger cannot satisfy the run.
_Avoid_: Filesystem path, caller-selected ledger, execution nonce

**Authorization ledger**:
The durable history of execution-nonce claims and their exact authorization and
run bindings inside one execution domain. It records consumption; it does not
issue authority.
_Avoid_: Apply authorization, checkpoint store

**Compensation authorization**:
An externally issued, time-bounded grant to invoke the public `compensate` seam
for one original authorized run and execution domain, one exact checkpoint and
plan-action set, and one fresh compensation nonce. It never authorizes a new
forward action and never reuses apply authority.
_Avoid_: Apply authorization, automatic in-run compensation, generic rollback

**Checkpoint-set manifest**:
The canonical nonempty ordered projection of all and only durable checkpoints
for one exact original apply/run/domain and validated plan action set at one
store generation. Its entries bind generation/version, phase, invocation
state, immutable identity, action/ordinal, and the digest of each complete
durable record; its digest is derived by trusted enumeration under the
exclusive lease and rechecked immediately before a public compensation claim
or transition.
_Avoid_: Caller-supplied digest, partial checkpoint list, mutable store view

**Checkpoint-store snapshot**:
The sealed, bounded, nonempty ordered full-record image of one trusted
checkpoint store generation for an exact apply, run, execution domain, and
plan-action set. Release replay derives the store generation and durable
checkpoint records from its exact archived bytes; the checkpoint-set manifest
is only its validated projection.
_Avoid_: Checkpoint-set projection, ambient record list, caller-supplied generation

**Compensation transition claim**:
The separate immutable provenance record for a public compensation transition.
It binds one immutable checkpoint identity to the independently validated
compensation-authorization identity, complete digest, and fresh nonce. Automatic
in-run rollback has an explicit `automatic_apply` authority kind and no public
claim.
_Avoid_: Checkpoint identity rewrite, self-authenticating claim, ambiguous null

**Public compensation recovery**:
Continuation of one already claimed public compensation invocation. It requires
the independently trusted original authorization and pretransition checkpoint
manifest, the durable compensation-ledger claim, and a race-rechecked current
checkpoint store that is a monotonic descendant carrying only the original
public claims. It does not mint a new nonce or reapply the original time window.
_Avoid_: Fresh compensation authorization, inferred authority, automatic rollback takeover

**Run terminal record**:
The closed authenticated success record for one exact apply execution tuple,
complete plan-action set, validated checkpoint-set manifest, and trusted store
generation. Success requires unique completed checkpoint coverage of every plan
action and strictly increasing durable generations in canonical action order.
_Avoid_: Caller-supplied state string, partial checkpoint prefix, release receipt

**Expected acceptance case manifest**:
The sealed, pre-execution registry of every release case required for one
candidate, plan, capture, and route-capability binding tuple.
_Avoid_: Test output, evidence bundle

**Acceptance evidence bundle**:
The candidate result set for exactly one expected acceptance case manifest. It
is evidence to be attested, not authority to authenticate itself or release a
candidate.
_Avoid_: Expected cases, release attestation

**Release attestation**:
A separately authenticated, post-execution statement that binds independent
runner and operator review to one exact acceptance evidence bundle.
_Avoid_: Candidate-authored receipt, migration authorization

**Release launcher**:
The independently trusted release-authority component that validates and
archives one exact release tuple and alone may issue its release receipt.
_Avoid_: Candidate CLI, evidence writer, acceptance validator

**Release archive manifest**:
The closed record binding all eleven exact release-document byte digests,
candidate and execution identity, trusted launcher, authority-store
destination, and the create-only generation contract.
_Avoid_: Release receipt, candidate artifact index

**Release receipt**:
The terminal record that an independently trusted release launcher validated
and atomically archived one exact authorization, candidate, expected-case
manifest, evidence bundle, and release attestation tuple.
_Avoid_: Apply checkpoint, migration authorization

**Projection**:
A harness-visible entry derived from an active provider route.
_Avoid_: Source of truth, installed source
