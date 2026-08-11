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
One preferred provider route plus zero or more explicitly allowed supplementary
routes for an equipment identity in one harness. Every member is an active
provider route.
_Avoid_: Inferred overlap, interchangeable providers

**Harness coverage outcome**:
The single declared result for an equipment identity in one harness. Its exact
serialized literal is `managed_provider`, `manually_managed_provider`,
`intentional_omission`, or `unsupported`.
_Avoid_: Operation capability, provider preference

**Operation disposition**:
The declared capability of an active provider route for one operation. Its
exact serialized literal is `automated`, `operator_action`, or `unavailable`.
_Avoid_: Harness coverage outcome, manual provider

**Provenance owner**:
The one source or native manager responsible for the artifact and restore
evidence of an active provider route.
_Avoid_: Logical package owner, runtime cache

**Projection**:
A harness-visible entry derived from an active provider route.
_Avoid_: Source of truth, installed source
