# Podman-to-OrbStack Migration PRD

## Problem Statement

OrbStack 2.2.1 is the forward container runtime, and the Docker CLI already
targets it. A stopped rootful Podman machine, `podman-machine-default`, still
contains the existing workload state. Its last recorded uptime was July 8,
2026; it has 8 CPUs, roughly 15 GB of RAM, a 465 GB virtual disk, and
approximately 441–442 GB of allocated data. It also exposes broad writable host
mounts that must not be reproduced blindly.

The repository keeps Docker's `currentContext` set to `orbstack` while
preserving unrelated Docker configuration and credentials. It also keeps the
Podman CLI available for unmigrated workloads. It does not describe the
workloads, images, volumes, secrets, networks, port bindings, architecture
requirements, or rollback procedures needed to migrate the actual machine
state.

Starting the Podman machine may activate restart-managed workloads, expose
ports, mutate data, or contact external systems. It must not be started without
explicit operator authorization. Migration must therefore begin with read-only
host and offline-disk inventory, record any facts that cannot be discovered
safely, and request a separate digest-bound authorization before any controlled
source start.

The desired outcome is a verified workload-by-workload migration to OrbStack
with compatibility fixes, least-privilege mounts, reproducible target
definitions, tested data restoration, and reversible cutovers. No Podman state
is retired or deleted until every runnable workload has either an accepted
migration or an explicit obsolete disposition from Ivan, all retained evidence
has an independently verified home, and Ivan separately approves retirement.

## Solution

Build a migration controller and private migration ledger around a canonical
workload inventory. The controller exposes read-only `inventory`, `plan`, and
`status` operations; evidence-only `verify`; and explicitly authorized
`discovery-start`, `snapshot`, `export`, `canary`, `accept`, `cutover`,
`rollback`, `retirement-approve`, and `retire` operations. Source start,
acceptance, and retirement are separate exact-plan transitions and never share
approval authority.

Read-only discovery first inventories host-visible Podman configuration,
machine and source-disk metadata, declarative workload sources, and connection
settings. It classifies unknowns and checks capacity without starting Podman. A
separate artifact plan creates and verifies an offline snapshot or clone while
the source remains stopped. If workload metadata or application-consistent
exports require a running source, the controller produces a separate
discovery-start plan describing activation risks, containment, commands,
expected evidence, and shutdown behavior. Only operator approval of that
immutable plan authorizes a start.

Each workload receives a compatibility and migration record covering its image
digest and architecture, process model, volumes, data-consistency requirements,
secrets, mounts, users and permissions, networks, ports, DNS names, health
checks, dependencies, restart behavior, target OrbStack form, canary procedure,
acceptance criteria, and rollback strategy.

Standard container workloads move to OrbStack's Docker-compatible engine and
Compose. Workloads requiring a full Linux userspace, systemd, a machine
lifecycle, or container-incompatible semantics move to explicitly configured
OrbStack machines. Podman-specific behavior is translated rather than emulated
silently; OrbStack machines are not represented as independent VMs.

Stateful workloads use application-consistent export and restore where
available. Raw filesystem transfer is permitted only when the workload
documents its quiescence, ownership, permission, extended-attribute, and restore
contracts. Every artifact receives a digest, provenance record, and restore
test. Retained content-bearing snapshots, exports, backups, and rollback
artifacts are encrypted at rest and are restore-tested beginning from their
retained ciphertext.

Canaries run without production port ownership and against copied data. Cutover
is workload-specific and operator-approved. Source state remains frozen as
rollback evidence. Once target writes begin, rollback must use the workload's
declared reverse-transfer or replay procedure rather than restarting stale
Podman data.

The Hindsight airlock may consume OrbStack after this migration architecture
exists, but it is not part of the Podman migration and does not determine
migration acceptance.

## User Stories

1. As Ivan, I want OrbStack treated as the forward runtime, so that new runtime
   work does not deepen Podman dependency.
2. As Ivan, I want the stopped Podman machine to remain stopped during initial
   discovery, so that inventory cannot activate workloads accidentally.
3. As Ivan, I want every Podman start to require explicit approval of an
   immutable plan, so that source activation is deliberate.
4. As an operator, I want read-only host and offline-disk discovery first, so
   that safe facts are gathered before requesting broader authority.
5. As an operator, I want undiscoverable facts recorded as explicit gaps, so
   that the controller never guesses about hidden workloads or data.
6. As Ivan, I want an immutable source-disk snapshot before any authorized
   start, so that discovery itself has a rollback point.
7. As an operator, I want restart policies and activation risks identified
   before starting Podman, so that a discovery start cannot surprise me.
8. As Ivan, I want all containers, pods, images, volumes, networks, secrets,
   ports, and machine-managed processes inventoried, so that no workload is
   silently abandoned.
9. As Ivan, I want allocated storage classified as live data, image layers,
   caches, logs, archives, or unknown state, so that hundreds of gigabytes are
   not copied blindly.
10. As an operator, I want every workload assigned a stable migration identity,
    so that evidence and approvals remain traceable across retries.
11. As Ivan, I want each image recorded by digest, platform, and provenance, so
    that target execution uses the reviewed artifact.
12. As Ivan, I want local-only images exported or reproducibly rebuilt, so that
    they are not lost when Podman is retired.
13. As an operator, I want architecture compatibility checked for every image,
    so that ARM-native, multi-architecture, and emulated workloads are explicit.
14. As Ivan, I want native target images preferred over emulation, so that
    compatibility does not hide a permanent performance penalty.
15. As an operator, I want Podman pods mapped to Compose or an OrbStack machine
    explicitly, so that pod semantics are not approximated silently.
16. As Ivan, I want rootful, user-namespace, UID, GID, ownership, and permission
    assumptions tested, so that migrated data remains usable.
17. As Ivan, I want broad host mounts replaced with workload-specific
    least-privilege mounts, so that OrbStack does not inherit unnecessary host
    write access.
18. As an operator, I want platform-specific mount flags and socket assumptions
    translated, so that Podman-only options do not break target startup.
19. As Ivan, I want secret values excluded from inventories, plans, logs, and
    Git, so that migration evidence remains safe to retain.
20. As an operator, I want secret locators, consumers, ownership, and required
    permissions inventoried, so that secrets can be re-established without
    copying them into dotfiles.
21. As Ivan, I want network, DNS, hostname, and host-reachability assumptions
    mapped, so that service discovery remains intentional.
22. As an operator, I want every target port and bind address validated
    globally, so that canaries and cutovers cannot collide with existing
    services.
23. As Ivan, I want loopback and externally reachable ports distinguished, so
    that migration cannot widen exposure silently.
24. As an operator, I want application-consistent backups preferred for
    databases and stateful systems, so that a byte copy is not mistaken for a
    valid backup.
25. As Ivan, I want every migration artifact digested and restore-tested, so
    that an archive is not considered usable merely because it exists.
26. As an operator, I want source and target capacity checked before copying
    data, so that migration cannot exhaust local storage.
27. As Ivan, I want each workload canary-tested independently, so that one
    incompatible workload does not block unrelated migrations.
28. As an operator, I want canaries to use copied data and non-production
    endpoints, so that verification cannot corrupt source state or steal live
    traffic.
29. As Ivan, I want health, behavior, data integrity, and performance acceptance
    criteria declared per workload, so that "container started" is not
    sufficient evidence.
30. As an operator, I want stateful cutovers to declare their write-freeze and
    source-of-truth transition, so that concurrent writes cannot diverge.
31. As Ivan, I want rollback behavior declared before cutover, so that
    reversibility is real rather than aspirational.
32. As an operator, I want post-cutover writes accounted for in rollback, so
    that restarting stale Podman state cannot discard accepted data.
33. As Ivan, I want every cutover and acceptance bound to reviewed artifact
    digests, so that the tested workload is the one activated.
34. As Ivan, I want workload acceptance to remain explicit, so that passing
    automated checks cannot retire the source automatically.
35. As an operator, I want Podman retirement to be a separate export-backed
    plan, so that migration completion does not imply deletion authority.
36. As Ivan, I want the source disk, migration artifacts, and rollback records
    retained until retirement approval, so that early cleanup cannot remove
    recovery options.
37. As Ivan, I want the Podman PATH preference removed only after migration
    acceptance and retirement approval, so that configuration does not get
    ahead of source-state disposition.
38. As an operator, I want ordinary `chezmoi apply` to remain incapable of
    starting engines, copying state, cutting over ports, or deleting Podman, so
    that dotfile convergence is safe.
39. As Ivan, I want a content-free migration ledger, so that actions are
    auditable without duplicating secrets or workload payloads.
40. As a maintainer, I want compatibility fixes kept narrow to migrated workload
    behavior, so that migration does not become unrelated application
    refactoring.
41. As Ivan, I want Hindsight airlocks treated only as a future OrbStack
    consumer, so that their design cannot expand or block this migration.
42. As an operator, I want all version, runtime, disk, and workload facts
    reverified immediately before an action plan is approved, so that stale
    inventory cannot authorize mutation.

## Implementation Decisions

- The canonical workflow states are `discovered`, `inventoried`, `planned`,
  `canary-ready`, `verified`, `accepted`, `cut-over`, `retirement-approved`, and
  `retired`. State transitions are append-only and digest-bound.
- The operation transition matrix is:
  - `discovery-start`: `discovered` to `inventoried` after the bounded start,
    capture, stop, and stop verification complete.
  - `snapshot`: from `discovered` or `inventoried`, retaining the predecessor
    state while appending the verified snapshot artifact.
  - `export`: from `inventoried` or `planned`, retaining the predecessor state
    while appending the verified export artifact.
  - `canary`: `planned` to `canary-ready` after isolated target creation.
  - `verify`: `canary-ready` to `verified` after every declared compatibility,
    data-integrity, isolation, and rollback check succeeds against the bound
    canary artifacts.
  - `accept`: `verified` to `accepted` only after Ivan authorizes the exact
    immutable acceptance plan; the authenticated identity, operation scope,
    expiry, nonce, and bound-state checks must all pass at execution.
  - `cutover`: `accepted` to `cut-over` after the approved freeze, final catch-up,
    target activation, source stop, and post-cutover verification complete.
  - `rollback`: from `cut-over` to `planned` for a new attempt after the declared
    reverse export, replay, or data-loss bound is satisfied; the prior cutover
    and rollback outcome remain in the append-only history.
  - `retirement-approve`: `cut-over` to `retirement-approved` only after the
    complete retirement predicate passes and Ivan authorizes the exact immutable
    retirement plan under the same identity, scope, expiry, nonce, and
    bound-state guards.
  - `retire`: `retirement-approved` to `retired` after every deletion and final
    postcondition succeeds.
  Every mutating operation in the matrix requires an authenticated identity,
  exact operation and workload scope, an unexpired single-use nonce, the exact
  immutable digest-bound plan, and execution-time equality for every bound state
  value. This applies to discovery-start, snapshot, export, canary, verify,
  accept, cutover, rollback, `retirement-approve`, and retire. Replay after
  nonce consumption is rejected without side effects or a new transition.
  `status` is a non-consuming read of current workflow and operation state;
  repeated reads remain valid and create no ledger record or transition. A
  separate read-only operation-result lookup retrieves the recorded result for
  a committed request by operation ID. A failed or incomplete mutating attempt
  cannot reuse its approval; retry requires fresh observed state, a new
  digest-bound plan, and a new approval.
- A workload identity remains stable across source containers, target
  containers, retries, and rollback artifacts.
- The private workload inventory records source definitions, image identity,
  platform, commands, dependency order, health behavior, restart policy, mounts,
  volumes, secret references, networking, ports, data-consistency rules, target
  form, acceptance criteria, and rollback procedure.
- A source coverage manifest assigns every discovered container, pod, image,
  volume, network, secret reference, machine-managed process, declarative source,
  and classified storage allocation one disposition: `accepted-migration`,
  `approved-obsolete`, `retained-evidence`, or `unknown`. A retained-evidence
  disposition names an independent, digested, restore-tested artifact and keeps
  that artifact outside the deletion set. Unknown, conflicting, duplicate, or
  undisposed items block retirement.
- Inventory payloads, exported data, secret metadata, logs, snapshots, and
  workload evidence remain in private machine-local state and out of Git. Git
  may contain schemas, controller code, synthetic fixtures, and non-sensitive
  documentation. Every retained content-bearing snapshot, export, backup, and
  rollback artifact is encrypted at rest. Plans and ledgers bind only a
  non-secret key locator resolved through an approved machine-local key
  provider; key material never enters plans, logs, fixtures, or Git. Restore
  proof begins from the retained ciphertext and covers controlled key
  resolution, decryption, digest verification, and the workload restore test.
- Initial inventory is non-mutating. It may inspect installed binaries,
  Docker/Podman connection metadata, machine metadata, declarative sources, disk
  metadata, and pre-existing offline disk copies. It must not create a large
  snapshot, start Podman, mount its live disk read-write, or contact workload
  endpoints.
- Snapshot creation is its own capacity-checked, digest-bound artifact plan. It
  keeps the source stopped, records whether the artifact is a filesystem clone,
  sparse image copy, or another immutable form, and verifies that the result can
  be opened read-only before it authorizes any source start.
- If offline inspection is insufficient, the controller emits a discovery-start
  plan. The plan identifies workloads that may auto-start, network and port
  risks, snapshot evidence, containment steps, permitted commands, timeout,
  expected outputs, and mandatory stop verification.
- Approval to start Podman is scoped to the exact discovery or export plan. It
  does not authorize workload mutation, cutover, or retirement.
- Every approval binds an authenticated approver identity, operation kind,
  workload or migration identity, exact immutable plan digest, issuance time,
  expiry time, and unique nonce. Approval redemption atomically checks and
  consumes the nonce before the transition. Expired, replayed, already consumed,
  mismatched, or cross-operation approvals fail closed. Source start,
  acceptance, and retirement each require a separately issued approval; only
  Ivan may approve acceptance or retirement.
- Standard workloads target OrbStack's Docker-compatible engine. Workloads
  needing systemd, a separate Linux userspace and lifecycle, or incompatible
  container semantics target a declared OrbStack Linux machine. That target is
  not treated as VM-level isolation.
- The compatibility mapper handles Podman pod semantics, rootful assumptions,
  user namespaces, engine socket differences, host aliases, Compose differences,
  mount-label options, UID/GID ownership, restart behavior, health checks,
  network names, and port bindings.
- Broad writable source-machine mounts are never copied as target defaults. Each
  required host path must have a workload-specific purpose, access mode, and
  least-privilege target mapping.
- Images are pulled or rebuilt by immutable digest when possible. Local-only
  images use a digest-verified export/import or a reproducible build. Mutable
  tags alone are insufficient.
- Every image declares supported architecture. Emulation requires an explicit
  performance and reliability acceptance criterion; it is not an invisible
  fallback.
- Secret inventories contain identifiers and locators only. Target secrets are
  resolved at activation from approved machine-local stores and never rendered
  into committed files, migration plans, process arguments, or persistent logs.
- Network plans declare target network membership, DNS identity, host access,
  inter-workload dependencies, exposed ports, bind addresses, and firewall
  expectations. Undeclared exposure fails validation.
- Stateful workloads prefer logical, application-consistent exports.
  Filesystem-level exports require source quiescence and preservation of
  ownership, modes, links, extended attributes, and required filesystem
  semantics.
- Each backup artifact records source workload identity, source state watermark,
  format, size, ciphertext digest, creation method, non-secret key locator, and
  restore-test result beginning from the retained ciphertext.
- A workload canary uses isolated names, networks, volumes, and non-production
  ports. It must not write to source data or own production endpoints.
- Canary verification covers startup, health, dependency resolution,
  representative behavior, data counts or checksums, secret resolution,
  permissions, network reachability, port exposure, logs, shutdown, restart, and
  resource use.
- Cutover plans bind the inventory digest, target-definition and profile digest,
  runtime and architecture facts, expected live-state digest, idle operations
  snapshot, accepted canary artifact, source watermark, encrypted backup digest,
  target endpoint, expected port changes, downtime procedure, rollback trigger,
  and post-cutover observation checks. Any execution-time mismatch against a
  bound value invalidates the immutable plan and requires replanning and fresh
  approval.
- Stateful cutover establishes one source of truth. The source remains frozen
  after target writes begin. Rollback after that point requires a declared
  reverse export, replay, or accepted data-loss bound.
- Automated verification may mark a workload `verified`; only Ivan may mark it
  `accepted`.
- Retirement is never implied by acceptance. A separate plan inventories all
  remaining Podman references and evaluates one authoritative predicate: every
  runnable workload is `accepted-migration` or `approved-obsolete`; every other
  source object has exactly one valid disposition; every retained-evidence
  artifact is independently present and restore-tested; no unknown, conflicting,
  duplicate, or undisposed item remains; and every accepted target still passes
  its checks. The plan then lists each deletion or configuration change and
  every retained item explicitly.
- Every source lifecycle mutator, including source start, mount, unmount, and
  write paths, and every retirement deletion path acquires the same OS-backed
  exclusive source-lifecycle lock. Retirement holds that lock continuously from
  the final atomic verification that Podman is stopped, the source disk is
  unmounted and unwritten, and the observed source digest matches the approved
  plan through all deletions. Any failed check, competing mutator, or source
  change aborts retirement before deletion and requires a new plan and approval.
  The exclusion must also stop non-controller Podman, VM, mount, and direct disk
  mutations through an OS-enforced source freeze or equivalent exclusive
  mechanism. Where the platform cannot provide that mechanism, execution
  is unavailable: observation or continuous revalidation alone never
  authorizes a destructive step.
- Removing the Podman machine, disk, images, volumes, connections, binaries, or
  PATH preference requires retirement approval.
- The existing Podman PATH injection remains until retirement. The final
  retirement plan removes it and verifies that Docker and Compose continue to
  resolve to OrbStack.
- `chezmoi apply` may render controller code, schemas, inactive plans, and
  runtime preferences. It must never execute inventory starts, migrations,
  cutovers, or retirement.
- The controller ledger stores workload IDs, artifact digests, plan digests,
  approvals, transitions, timestamps, results, and reason codes without payload
  or secret content.
- OrbStack 2.2.1 is the verified planning baseline, not a perpetual unverified
  assumption. Execution rechecks the installed version, Docker context, target
  health, storage capacity, and architecture.
- Hindsight airlocks are a separate forward consumer of OrbStack. They do not
  import Podman state and are not part of migration acceptance.

## Testing Decisions

- The primary acceptance seam is the migration controller interface. Tests
  invoke inventory, discovery-start, plan, status, snapshot, export, canary,
  verify, accept, cutover, rollback, `retirement-approve`, and retire against
  disposable source and target adapters and assert observable plans, artifacts,
  gates, and state transitions. `retirement-approve` separately exercises the
  `cut-over` to `retirement-approved` transition before `retire`.
- Tests describe operator-visible behavior rather than internal function calls.
- Read-only inventory tests prove that default discovery does not start Podman,
  contact workload endpoints, mount live storage read-write, or modify
  connection state.
- Authorization tests cover discovery-start, snapshot, export, canary, verify,
  accept, cutover, rollback, `retirement-approve`, and retire. Every operation
  rejects missing, stale, or mismatched plan digests; unauthenticated or
  unauthorized identities; wrong operation, workload, or migration scope;
  expired approvals; consumed or replayed nonces; and execution-time drift from
  any bound state. `retirement-approve` has its own identity, migration-scope,
  nonce, plan-digest, expiry, replay, and execution-time drift cases before the
  existing retire authorization cases. Acceptance and `retirement-approve`
  additionally reject every approver except Ivan.
- Status tests prove repeated reads remain valid and create no side effect,
  ledger record, nonce consumption, or state transition. Operation-result tests
  prove committed results remain retrievable by operation ID.
- Inventory fixtures cover standalone containers, pods, Compose workloads,
  systemd-managed containers, local images, named volumes, bind mounts, secrets,
  custom networks, restart policies, and unknown state.
- Coverage tests prove that every source object and classified storage allocation
  receives exactly one disposition; approved-obsolete items require Ivan's
  approval; retained-evidence items require an independently present,
  restore-tested artifact outside the deletion set; and unknown, conflicting,
  duplicate, or undisposed entries block retirement.
- Storage tests classify image layers, active volume data, caches, logs,
  archives, and unknown allocations without assuming the whole virtual disk is
  migratable workload state.
- Compatibility tests cover Podman pods, rootful ownership, user namespaces,
  platform-specific mount flags, engine sockets, host aliases, network names,
  DNS, health checks, restart policy, and port conflicts.
- Architecture tests cover native ARM images, multi-architecture manifests,
  x86-only images, explicit emulation, and native rebuilds.
- Secret tests prove that values never enter inventory output, plans, ledgers,
  logs, fixtures, or Git-rendered artifacts.
- Network tests assert exact intended reachability and prove that undeclared
  host, peer-workload, and external exposure is rejected.
- Data tests create logical and filesystem backups and prove a positive restore
  round trip begins with retained ciphertext, resolves only an approved
  machine-local key provider, verifies the ciphertext digest, decrypts, and
  restores the workload. Negative cases reject retained plaintext, unapproved
  key providers, wrong keys, and corrupted or truncated ciphertext before
  restore.
- Database fixtures verify application-consistent export, restored
  schema/version, record counts, representative queries, and restart behavior.
- Canary tests prove isolated names, networks, volumes, and ports and verify that
  source data remains unchanged.
- Cutover tests cover port handoff, dependency order, write freeze,
  source-of-truth transition, post-cutover checks, and bounded failure.
- Rollback tests distinguish pre-write rollback from post-write reverse
  migration and reject stale-source restart when accepted target writes would be
  lost.
- Acceptance tests prove that automated success cannot create operator
  acceptance.
- Retirement tests prove that no deletion, machine removal, disk removal,
  connection removal, binary removal, or PATH change occurs unless the complete
  retirement predicate passes and Ivan separately approves the exact plan. They
  also prove execution rechecks source quiescence atomically under the lifecycle
  lock and rejects a running Podman process, mounted or newly written source
  disk, digest drift, and any restart, mount, or write race before deletion.
  Failure to acquire or prove the OS-enforced freeze causes zero deletion;
  losing the freeze aborts before the next destructive action and requires a
  new plan and approval. Non-controller restart, mount, and write attempts
  cannot race retirement while the freeze is held.
- Chezmoi tests prove ordinary apply cannot start either runtime or execute
  migration operations.
- A local opt-in compatibility smoke test may use disposable Podman and OrbStack
  workloads. It must never target `podman-machine-default` or existing OrbStack
  state.
- No automated test starts the real Podman machine, migrates real data, takes
  production ports, or deletes source state.

## Out of Scope

- Starting `podman-machine-default` without a separately approved plan.
- Migrating or deleting source state during the read-only inventory phase.
- Blindly copying the complete Podman virtual disk into OrbStack.
- Reproducing broad writable host mounts.
- Storing secret values, private workload payloads, or exported data in Git or
  chezmoi.
- Unrelated product changes or broad application refactors.
- Automatic acceptance, retirement, deletion, or time-based cleanup.
- Deleting Podman binaries, machine state, images, volumes, or rollback artifacts
  as part of ordinary migration.
- Background synchronization between Podman and OrbStack after cutover.
- Treating a stale Podman workload as an automatic rollback target after
  OrbStack has accepted writes.
- Migrating non-Podman virtual machines or unrelated host services.
- Designing the Hindsight memory control plane or its airlock policy.
- Publishing private inventories, migration artifacts, or workload evidence.
- Replacing OrbStack or selecting a different forward runtime.

## Further Notes

- The source machine's size makes capacity planning and artifact classification
  mandatory before copying data.
- Rootful execution and broad writable mounts are migration risks to remove, not
  compatibility behavior to preserve automatically.
- Docker already points to OrbStack; compatibility checks must still inspect
  scripts and automation that infer Podman from command paths, sockets, output,
  or machine presence.
- The stopped source machine is valuable rollback evidence. Keeping it stopped
  also keeps its data stable until an explicitly authorized discovery or export
  requires otherwise.
- A successful container start is not migration acceptance. Restore evidence,
  representative behavior, exposure checks, restart behavior, and operator
  approval are all required.
- This PRD is intentionally separate from the Hindsight memory-system PRD. The
  only relationship is that future Hindsight airlocks may use OrbStack after the
  runtime is accepted.
- This repository has no configured issue-tracker publication contract for the
  PRD. The committed document is the durable work contract until an operator
  explicitly authorizes publication elsewhere.
