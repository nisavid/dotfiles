# Protected host boundary for Provingkit delivery

This source specifies one dedicated delivery service, its protected setup
boundary and disposable qualification. It is outside `home/`, so chezmoi does
not install it into the ordinary agent user's home. The
[operating procedure](../../docs/agent-equipment/provingkit-delivery.md) is its
maintained enrollment, stop, recovery and verification entrypoint.

There is no executable or service unit in this increment. The
[configuration](config.example.json) is disabled and unbound; the
[cases](qualification-cases.json) are synthetic observation specifications.
Neither creates a system account, operates a provider or qualifies a service.

## Identity and protected destinations

The candidate service identity is `provingkit-delivery`, without interactive
login. Provisioning must reject an unexplained existing identity or destination
rather than adopting it. UID/GID selection belongs to the accepted setup step.
All paths below are relative to the enrolled system root, never to an agent
home or an untrusted artifact's extraction root.

| Destination | Owner and permitted change |
| --- | --- |
| `usr/lib/provingkit-delivery` | Privileged installation owner; service and ordinary agents cannot write executable code or dependencies. |
| `etc/provingkit-delivery` | Privileged installation owner; service and ordinary agents cannot change selected configuration. |
| `etc/provingkit-delivery/trust` | Privileged trust owner; public channel verification material, unavailable for mutation through the delivery service. |
| `var/lib/provingkit-delivery` | Service identity; journal and selected mutable state, inaccessible to ordinary agents. |
| `run/provingkit-delivery` | Service identity; exclusive run lock and transient state, recreated and reconciled after restart. |

The supported credential store is a separate bound interface. No credential
location or credential value is selected by this example. Its owner must prove
ordinary agents cannot read or replace credentials or impersonate the service.
Inspect actual delegated privilege paths during qualification; ownership labels
and file modes alone do not establish isolation.

## Closed supplier interfaces

The service consumes authenticated promotion records binding the approved
channel, audience, source/components, immutable artifact digests and delivery
versions. It uses the existing producer, verifier and issuer. Notifications,
artifacts, journal entries and adapter replies cannot choose an executable,
change trust roots or broaden the enrolled target set.

Each reviewed provider adapter supplies account/entry observation, a bounded
mutation and fresh content readback, including removed files and enabled state.
Its contract declares expected-release enforcement or the accepted
exclusive-writer limitation. A shared native cache cannot identify multiple
cloud accounts. Claude repository controls must prevent unauthorized promotion,
including bypass through ordinary agent credentials.

Bind the actual component revisions, dependency identities and clean Daybreak
coverage before live use, including qualification tools. Unknown or changed
coverage stops that use. The example cannot authenticate its own promotion or
declare its own review passed.

## Setup and upgrade interface

The narrow setup package implements the following request/response interface;
no implementation or callable CLI is supplied here. These operation names are
literal contract values, not commands to execute from this document.

Every request binds the reviewed source revision, complete package/dependency
digests, selected system root, approved identity and destination allowlist, and
expected previous installation identity. Replies identify observed preimages,
the closed proposed action list, conflicts, completed actions and postimages.
Use a trusted installation context, not executable instructions embedded in a
downloaded promotion or candidate-owned journal.

| Operation | Required effect and terminal reply |
| --- | --- |
| `plan-setup` | Observe identity/destinations without mutation; return a complete proposed setup with `planned` or a concrete `conflict`. |
| `apply-setup` | Consume the reviewed plan and matching preimages once; install only bound identity, protected files and state ownership; return `installed` only after verification, otherwise `partial` with completed-action evidence. |
| `plan-upgrade` | Bind the expected installed revision and mutable-state compatibility; preserve trust, credentials and state outside the selected update. |
| `apply-upgrade` | Apply only that bound upgrade, preserving evidence across interruption; never treat a partial replacement as successful. |
| `inspect-partial` | Reconcile actual ownership/content against recorded actions, with no replay or cleanup. |
| `recover-partial` | Consume a separately reviewed recovery plan for the inspected state; stop on drift and preserve unexplained files/accounts. |
| `verify-installation` | Read back identity, protected code/config/trust digests, dependency bindings, permissions and state compatibility; report remaining live-use gates. |

Setup does not enroll accounts, obtain credentials, enable a service or release
a hold. Partial setup does not authorize deleting a pre-existing account,
reverting unknown files or blindly replaying completed actions. A recovery plan
names each selected action and expected state; a later mismatch stops it.

At an actual privilege gate use `handling-privileged-steps`: freeze the reviewed
executable, literal argv, workdir, exact selected effects, handback signal and
verification before privileged execution. An interface design is not a grant
for sudo, account provisioning or host writes.

## Journal, locking and stop

The release trigger and catch-up timer share one exclusive lock and one durable
journal. A target intent binds channel, artifact digest, account, entry and
delivery version. Distinguish validation, recorded write intent, confirmed
delivery, blocked targets and uncertain outcomes. Persist intent before a
provider write, and confirm actual state afterward.

After a crash, lost reply, stale job or lock interruption, reconcile state
before attempting another write. Unknown outcomes stop their dependent work;
they are neither failures safe to repeat nor evidence of completion. Logs and
notices contain nonsecret identities and results, not raw credential-bearing
diagnostics. Independent eligible targets remain independent where the shared
safety boundary is intact.

A stop freezes both ChatGPT mutation and Claude promotion. It does not retract
content already eligible for subscription propagation. Forward recovery uses
retained known-good content at a higher approved delivery version and verifies
its actual result.

## First results and later qualification

The first source result is this static contract, disabled configuration and
case set, with independent final-revision review and applicable source checks.
An existing privileged installer is not a prerequisite to that result.

The next implementation result is a reviewed narrow setup package and a
reviewed stub harness that can exercise the literal operations in a disposable
multi-identity environment. Bind its source/dependency revisions and Daybreak
coverage before live-use qualification. A same-user temporary directory test
cannot qualify ordinary-agent/service isolation. Return a missing execution
interface as that specific gap rather than inventing another platform or role.

The existing host producer conditionally prepares setup and post-setup
verification. It does not thereby accept privileged execution or ongoing
service operation. Provider canaries and version issuance proceed through their
existing owners; the all-account objective requires evidence for every scope.
