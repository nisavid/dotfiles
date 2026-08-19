# Process-Scoped Secret Injection

This context governs how managed hosts make selected credentials available to
individual consumer processes without creating ambient shell credentials.

## Language

**Managed host**:
A machine enrolled to provide process-scoped credentials to its local
consumers.
_Avoid_: Client, node

**Trusted user session**:
The logged-in OS-user context within which the host agent, provider session,
and consumer bindings are trusted to operate.
_Avoid_: Security sandbox, hostile tenant

**Host agent**:
A Proton Pass agent identity dedicated to one managed host and authorized to
establish that host's provider session.
_Avoid_: Shared agent, consumer agent

**Provider session**:
The host-local authenticated relationship through which credential values are
resolved from Proton Pass.
_Avoid_: Login, user session

**Consumer**:
An executable process that receives a selected credential profile.
_Avoid_: App, command

**Consumer binding**:
The declared relationship that routes a consumer through one credential
profile on a supported invocation surface.
_Avoid_: Global interception, ambient export

**Credential profile**:
A named set of credential bindings granted together to one or more consumers.
_Avoid_: Environment, secret group

**Injection vault**:
The Proton Pass vault containing credential items eligible for process-scoped
injection.
_Avoid_: Keyring, credential store

**Injection catalog**:
The credential-value-free desired state that relates managed hosts, credential
profiles, and consumers.
_Avoid_: Secret store, environment file

**Bootstrap token**:
The host-local credential that authenticates a host agent solely to establish
its provider session.
_Avoid_: Injected secret, user credential

**Secret control plane**:
The operator-facing surface for enrollment, inspection, mapping, readiness,
and rotation.
_Avoid_: Admin scripts, helper commands

**Secret data plane**:
The consumer-facing path that resolves a credential profile and injects it
into one process.
_Avoid_: Secret control plane, environment loader

## Planning and evidence

- [Wayfinder](./WAYFINDER.md) records accepted decisions, the current frontier,
  and the sequenced planning handoff.
- [Proton agent and PAT lifecycle](./research/proton-agent-lifecycle.md) records
  the provider constraints behind enrollment and rotation.
- [Native host credential and readiness lifecycle](./research/native-host-lifecycle.md)
  records the macOS and Linux platform constraints.
- [GitHub Issues #87–#96](https://github.com/nisavid/dotfiles/issues?q=is%3Aissue+label%3Asecret-injection)
  own the remaining open work.
