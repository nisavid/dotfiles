# Owner-signed age admission result contract

This contract describes the result that the repository-scoped `Owner-signed age
admission` App publishes for each pull-request head. It is separate from the
`privacy-age-admission/v1` owner receipt and from the coordinated agent-equipment
release receipt.

## Result record

Every successful result carries `version: privacy-age-admission-result/v1` and
is bound to the exact `repository`, `base_commit`, and
`head_commit` supplied to the trusted-base verifier. `protected_paths` is the
sorted, all-and-only set of protected paths whose trusted-base tree entries
differ from the candidate tree entries. The result vocabulary is closed:

| `outcome` | `protected_paths` | `receipt_required` | Meaning |
| --- | --- | --- | --- |
| `no_protected_paths_changed` | empty | `false` | The trusted-base computation completed and found no protected transition. This is terminal success; no owner receipt is parsed or required. |
| `owner_admission_verified` | nonempty | `true` | The trusted-base computation found a protected transition and verified one exact owner receipt for it. |

The empty result is not a fallback. Checkout, tree, classifier, repository,
base/head, freshness, or provenance uncertainty must produce a blocking failure,
never `no_protected_paths_changed`. A result with an unknown outcome, an
unsorted or duplicate path list, a mismatched receipt flag, or a changed
base/head is invalid.

The live binding carried alongside the result is a separate
`privacy-age-admission-snapshot/v1` record. It includes the pull-request number,
open/closed state, base ref, base and head repositories, exact base/head SHAs,
and `body_sha256`. The event payload is used only to locate the repository and
pull-request number; the trusted-base snapshot helper rereads all of these
values from GitHub. A verifier state envelope binds the snapshot to either a
validated result or a bounded failure code. State and result files are
duplicate-key-free canonical JSON and are transferred between jobs only as a
short, authenticated handoff.

The begin job checks out the immutable workflow event revision and captures
its Git object ID as the trusted tool revision; verify and publication check
out and compare that same revision. A later default-branch update cannot
silently change the verifier or publisher between those state-machine stages.

## Delivery contract

The workflow is an explicit begin -> verify -> completion state machine. The
begin and verify jobs run trusted-base code only; candidate checkout contents
are data for the scanner and transition classifier. The completion job is the
only secret-bearing job and publishes through the repository App (4695065) using
a short-lived installation token. It is gated by an admin-owned protected
environment; the App private key is never present in compute jobs, artifacts,
or logs. The installation token is limited to the repository Checks API
permission (`checks:write`); read-only pull-request access stays on the
workflow token. The completion edge publishes a failure when verification is
unavailable, but cannot run after cancellation.

The App publishes the stable required context for every supported
pull-request-head event (`opened`, `reopened`, `synchronize`, `ready_for_review`,
and `edited`). Results are keyed by pull request and exact head commit, and the
canonical external identity also binds the base ref and current pull-request
body digest. `external_id` is audit/reconciliation metadata, not authorization
or uniqueness: the publisher paginates check runs and validates App ID, exact
name, exact head, and exact external identity. One canonical prior identity
for the same repository, pull request, and head may be deterministically
superseded for a base/body/state edit or retry. Duplicate, legacy, different-
transition, same-head-across-PR, and ambiguous retries fail closed rather than
silently adopting or overwriting a run. A body edit or new head triggers a
fresh trusted computation, and an expired or ambiguous protected receipt never
selects the empty outcome.

A push that advances the default branch does not itself identify one pull
request. The App/event layer must therefore re-evaluate every affected open
pull request against the new base before treating an existing result as
current. Because the base SHA is part of the identity, that means every open
pull request targeting `main`, not only PRs whose changed paths overlap the
push. This workflow deliberately does not enumerate pull requests from a push
payload or publish a result without the trusted verifier handoff. The bounded,
paginated enumeration, base-advance reconciliation, and live delivery proof
remain an App and operator deployment gate, not an implicit branch-protection
assumption.
The installation proof must show that the App receives default-branch push and
pull-request events with the minimum read permissions needed to enumerate and
bind those PRs; that coordinator authority is separate from the publisher
job's short-lived `checks:write` token.

The final live-state guard rereads repository identity, pull-request number,
state, base ref and SHA, head repository and SHA, and body digest immediately
before a success or failure write. A changed snapshot aborts publication; it is
never retargeted to a newer event.

When an existing check run is being superseded, the publisher fetches that run
again after the live pull-request guard and requires the same run ID, App ID,
name, head, and prior reconciliation identity before issuing an update. A
changed run identity aborts; App-side serialization and post-write
reconciliation still remain required for the residual update race.

An old success on the same head must not survive a body edit, retarget, reopen,
base advance, canceled computation, duplicate create race, or accepted-write
response loss. The App event layer must serialize each PR transition and make
the current binding non-successful before asynchronous verification can be
canceled; any ambiguous or partially observed publication must be reconciled
to a blocking App result. `external_id` is not a lock or uniqueness primitive.
Those event-time invalidation and compensating-reconciliation behaviors require
separate source and live proof before activation.

The Checks API ref listing is bounded by GitHub's per-ref history limit even
when `filter=all` and Link pagination are used. The installation lane must
either prove the relevant check-suite history stays within that bound or use a
separately reviewed suite-by-suite reconciliation path; this publisher does
not infer completeness beyond the API's reported total.

For a fork head, GitHub's Checks API may not populate a pull-request
association even when a check-run write is accepted. A successful HTTP response
therefore is not delivery proof for a fork; the App installation lane must
prove the exact PR-visible, App-attributed context (or publish a blocking
failure) before activation.

The production workflow cannot evaluate its own implementation pull request
before it is on `main` while this App context is already required. Deliveries
are idempotent and an out-of-order event cannot replace a newer binding.
Therefore, a separately reviewed immutable event-driven bootstrap publisher,
bound to this same verifier/result contract, must be deployed before production
activation.
Manual helper publication, dynamic branch-protection edits, Actions-substituted
required contexts, and receipt minting for an unprotected transition are not
bootstrap mechanisms. The bootstrap publisher remains available through the
rollback window or the resulting fail-closed outage is surfaced explicitly.
Activation also requires an operator-owned App-key rotation, revocation, and
emergency procedure plus a rollback proof naming the immutable publisher
revision that remains available. A rollback that cannot publish the required
App result is an explicit fail-closed outage; it is not repaired by a manual
check or protection edit.

The App delivers this result for every supported pull-request head.

The App-pinned context remains the required branch-protection boundary. The
trusted Actions workflow is advisory evidence for the App, not a replacement
for it, and no branch-protection rule is edited dynamically.
