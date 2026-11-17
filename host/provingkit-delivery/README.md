# Protected host boundary for Provingkit delivery

This source specifies one dedicated delivery service, its protected setup
boundary and disposable qualification. It is outside `home/`, so chezmoi does
not install it into the ordinary agent user's home. The
[operating procedure](../../docs/agent-equipment/provingkit-delivery.md) is its
maintained enrollment, stop, recovery and verification entrypoint.

There is no executable or service unit in this increment. The
[configuration](config.example.json) is disabled and unbound; the
[case registry](qualification-cases.json) separates seven synthetic observations
from one disabled, externally owned live qualification specification. No case
is executed by this source. It creates no system account, operates no provider
and qualifies no service.

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

Qualification must explicitly reject ordinary-user credential replacement,
including direct writes, rename replacement, symlink substitution, credential
profile replacement and available delegated-privilege paths. After a clean
restart, the original bound synthetic marker and account context must remain
intact. Synthetic markers establish only the disposable boundary exercise,
not qualification of the eventual credential backend.

## Closed supplier interfaces

The service consumes authenticated promotion records binding the approved
channel, audience, source/components, immutable artifact digests and delivery
versions. It uses the existing producer, verifier and issuer. Notifications,
artifacts, journal entries and adapter replies cannot choose an executable,
change trust roots or broaden the enrolled target set.

### Rejection effect boundary

Every promotion mismatch or unsafe archive path must produce zero delivery
target intents and no delivery effects through either path: no ChatGPT delivery
calls or Claude commits/ref changes/pushes. Delivery destinations, protected
code/config/trust/credential material, extraction targets and repository state
must remain unchanged. Snapshot these domains, not the entire service state.

Rejection separately requires bounded service-owned effects: journal the
rejection, maintain the run lock, and publish nonsecret logs or notices through
their accepted interfaces. Permit only those journal/lock/log/notice locations
and operations; they cannot change a delivery target, protected material,
extraction target or repository. Missing evidence is not successful rejection.

Preserve exactly one correlated rejection record with only `event_id`,
`input_digest`, a producer-controlled `reason_code`, and `outcome: rejected`.
Identical repeated observations retain that record without duplicating the
unresolved event. Logs and notices derive only from the same nonsecret fields;
never copy a rejected body, credential, raw diagnostic or executable command.
Lock transitions and any log/notice count are bounded by the same attempt's
declared lifecycle. Persistence failure remains unavailable and admits no
delivery work.

Exercise every rejection fixture through both paths. Prove zero forbidden
effects alongside the exact secret-free rejection record and the bounded
allowlisted service effects. A zero provider-write count alone is insufficient,
and synthetic success does not qualify live provider or repository controls.

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
| `plan-upgrade` | Bind the expected installed revision and mutable-state compatibility, plus the admission conditions below; preserve trust, credentials and state outside the selected update. A read-only plan does not establish quiescence. |
| `apply-upgrade` | Require upgrade admission and hold the shared delivery exclusion through replacement and verification. Return `upgraded` only after `verify-installation` matches every expected postimage; partial or complete-but-wrong replacement is non-successful. Remain stopped afterward; verification failure permits no service restart or delivery mutation. |
| `inspect-partial` | Reconcile actual ownership/content against recorded actions, with no replay or cleanup. |
| `recover-partial` | Consume a separately reviewed recovery plan for the inspected state; stop on drift and preserve unexplained files/accounts. |
| `verify-installation` | Compare the observed identity, protected code/config/trust digests, ownership, permissions, dependency bindings and state compatibility with every bound expected postimage; report mismatches and remaining live-use gates. Readback alone is not passing verification. |

Setup does not enroll accounts, obtain credentials, enable a service or release
a hold. Partial setup does not authorize deleting a pre-existing account,
reverting unknown files or blindly replaying completed actions. A recovery plan
names each selected action and expected state; a later mismatch stops it.

An upgrade whose verification fails or remains unknown cannot report success
or admit service restart or delivery mutation. Preserve the actual result for
inspection and recovery. Passing verification does not itself authorize service
activation or release any remaining live-use gate.

### Upgrade admission

Before replacement, durably withdraw ordinary release-trigger and catch-up
admission for both delivery paths. Establish quiescence by finishing or safely
reconciling the actual in-flight attempt; process absence alone is insufficient.
An unresolved intent, active write or unavailable reconciliation blocks
replacement without killing, replaying or guessing the attempt's outcome.

Acquire the same exclusive lock used by delivery and retain it through
replacement and `verify-installation`. Under that exclusion, recheck the stopped
admission state, reconciled intent and bound installation preimages immediately
before mutation. Drift, failure to obtain exclusion or a queued trigger cannot
be bypassed. Queued triggers remain unable to start delivery while stopped.
Success, failure, uncertainty and reboot leave ordinary admission stopped; a
separate explicit resume transition is required after applicable gates pass.

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
content already eligible for subscription propagation. The ordinary admission
state is durable, including across reboot. A recovery authorization does not
change that state to running or release queued ordinary work.

### Stopped recovery and separate resume

While stopped, admit at most one recovery under an authorization bound to its
identity, exact channel, target/account/entry, retained artifact digest and a
delivery version higher than the observed target version under the approved
issuer's comparison contract. Validate applicable authority, holds and target
preimages. An applicable existing grant may cover issuance; no new human prompt
is required solely because the operation is recovery.

Acquire the shared delivery lock, recheck those bindings and ordinary stop,
then durably consume that authorization for the one original intent before
writing. Only its bound recovery action is permitted. All ordinary triggers
stay disabled. Success, failure, uncertainty or reboot returns to stopped,
retaining consumed authority and any unfinished intent. Inspect and reconcile
an uncertain attempt without automatically replaying it or reusing authority.

Ordinary delivery requires a separately authorized explicit resume transition
under the shared lock, with current installation/authority/hold and per-target
intent checks. Recovery success is not resume authority. Unresolved targets
remain blocked; resume does not erase their attempts. This source defines no
automatic resume or executable transition control.

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

The disposable harness may select only `synthetic_cases` with kind `synthetic`.
Reject any external or mixed selection, even if explicitly requested; no flag
can opt the provider-owned live case into that harness. The separate external
case stays disabled and requires its existing provider owner's acceptance,
authorized account route/audience and final-revision Daybreak coverage before
use. Its fresh readback and useful consumer are required results, not facts
established by this static registry. No selection implementation is supplied.

The existing host producer conditionally prepares setup and post-setup
verification. It does not thereby accept privileged execution or ongoing
service operation. Provider canaries and version issuance proceed through their
existing owners; the all-account objective requires evidence for every scope.
