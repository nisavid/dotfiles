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
evidence of an active provider route.
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

**Runtime observation**:
A secret-free statement of equipment state reported through a supported file,
CLI, or harness surface without claiming ownership.
_Avoid_: Desired state, adoption

**Mutation plan**:
A fully validated, deterministically ordered set of reconciler-owned automated
operations derived from one authored catalog, resolved lock, and runtime
inventory.
_Avoid_: Audit report, adapter command list

**Checkpoint**:
A durable record that binds one planned mutation to its captured pre-state,
expected post-state, and current execution phase.
_Avoid_: Log entry, global transaction

**Compensation**:
A declared route operation that restores the captured pre-state after a later
failure, subject to compare-before-restore.
_Avoid_: Best-effort cleanup, rollback claim

**Projection**:
A harness-visible entry derived from an active provider route.
_Avoid_: Source of truth, installed source
