# Agent equipment migration and recovery contract

This is the design deliverable for Issue #59. It specifies a future migration;
it does not authorize, start, or perform one. Running it requires separate
authorization for one fully resolved plan and its exact digests.

Execution also requires the manifest-bound CPython 3.12 or newer runtime and a
closed, externally issued `ApplyAuthorization`. The exact authorization bytes
and independently supplied `trusted_apply_authorization_digest` are distinct
inputs; neither this runbook nor candidate output can create authority.
Its top-level `execution_domain_identity` must equal the independently trusted
identity of the one authoritative compare-and-swap nonce-ledger namespace and
target used for the run.
The authorization also binds the exact operator review package digest covering
the proposed live mutations, rollback material, and review receipts.

The migration changes provider routes without treating a distribution as an
atomic capability. Every plugin skill, MCP, hook, and other component is
classified before the plan chooses a preferred route, a supplementary route,
or no provider. The currently reviewed Matt plugin is a special case with one
25-skill activation group and no plugin-level hooks, MCPs, agents, commands,
monitors, executables, or LSP servers. A refreshed manifest must prove that
fact again before migration.

## Preconditions and authority gate

Complete all of these before the executor opens an action checkpoint:

0. Run the installed wrapper's CPython 3.12+ gate before importing candidate
   code or reading native state. Recompute the runtime identity and executable
   digest in the installed-implementation manifest. Any mismatch stops before
   the first action checkpoint with zero adapter calls.

1. Refresh the live inventory and every selected native manager channel. For
   Matt, refresh the official marketplace entry, upstream plugin manifest,
   exported skill set, plugin version, current standalone provenance, Claude
   projections, and installed plugin state. A change from the reviewed fixture
   invalidates the plan.
2. Resolve an authored catalog and digest-bound lock through the contract in
   `ARCHITECTURE.md`. The resolved plan must name every affected surface and
   contain no glob, inferred ownership, name-only disablement, or recursive
   filesystem operation.
3. Validate the complete plan, including the last action, before creating the
   first action checkpoint. Every automated mutation must be on a
   `reconciler_owned` route, have supported compare and verification
   capabilities, and declare `restore_captured_pre_state` compensation. Validate
   the complete dependency graph for closure, required provider-switch edges,
   and acyclicity; lexical order alone is not execution authority.
4. Reject stale catalog or lock digests, unresolved provenance, an unknown
   capability needed by the plan, a native-rolling version outside the reviewed
   baseline, and any operator-owned mutating action.
5. Prove that the catalog-driven Claude projector can be installed without
   invoking projection reconciliation. It must exclude plugin-provided Matt
   skills before any existing Claude link is removed.
6. Prove that recovery material can restore every mutable surface. Store the
   checkpoint directory with mode `0700` and files with mode `0600`; use atomic
   write, file `fsync`, rename, and parent-directory `fsync` for every state
   transition.
7. Acquire the reconciler's exclusive apply lease. Native managers and external
   editors remain outside that lease, so the compare guards below remain
   mandatory.
8. After complete-plan validation, emit and validate the closed
   `agent-equipment-plan-action-set/v1` projection described below. Capture every
   route and affected surface, close every route over the exact adapter
   capability and manager-version evidence it requires, validate both JSON
   Schemas and cross-record semantics against that separately supplied action
   set, and atomically seal the action set, captured-state manifest, and private
   recovery blobs. Resolve again against that capture; a changed plan or action
   projection must be regenerated, recaptured, and resealed. Then derive and
   independently validate the closed all-and-only
   `CaptureObservationAuthoritySet`, seal the `PreparedActionAuthoritySet` from
   that exact artifact and adapter-derived post-state, and retain both exact
   identity/digest tuples for authorization.
9. Project and seal the closed acceptance expected-case manifest from that
   validated plan and capture. Include the complete static registry, every
   automated action, and every explicit read-only verification and mutating
   migration node. Bind every route's exact capability and manager-version
   evidence. Do not derive plan nodes from `ACCEPTANCE.md` or this runbook.
10. Present the secret-free dry-run, exact candidate implementation identity and
   complete installed-implementation manifest digest, catalog digest, lock
   digest, plan digest, plan-action-set digest, capability-set digest, sealed
   captured-state identity and digest, capture-observation-authority-set
   identity/digest, prepared-action-authority-set identity/digest, expected-case
   manifest digest, exact surface set, native-rolling limitations, and the closed
   digest of that exact operator review package. Obtain
   separate authority. It emits a Schema-valid `ApplyAuthorization` naming that
   complete exact tuple, including both authority-set identity/digest bindings,
   plus `command: apply`, issuer, UTC issue/not-before/
   expiry times, one run identity, a fresh execution nonce, the independently
   selected execution-domain identity, and the operator-review-package digest.
   Obtain its
   canonical `trusted_apply_authorization_digest` through a separate authenticated
   channel; do not infer it from the record.
11. After authorization and before any action checkpoint or mutation, strictly
    parse the record and validate its canonical identity and complete digest.
    Reject a missing, unknown, expired, not-yet-valid, misbound, or foreign-
    domain authorization.
    Then observe every affected live surface and every bound capability and
    manager-version evidence source, and recompute the installed-implementation
    manifest digest
    under the same candidate identity. Require the complete authorized tuple and
    live evidence to equal the sealed capture. Any drift invalidates the
    authorization. Mutate nothing, recapture, resolve, reseal, and obtain new
    authorization for the new exact tuple. Only after that comparison succeeds,
    atomically claim the nonce in the durable authorization ledger named by that
    domain. A previously claimed or unpersistable nonce, or a claim in another
    ledger domain, stops before the first action checkpoint.

The current public command vocabulary is `status`, `unmanaged`, `add`, `update`,
and `apply`. `status`, `unmanaged`, `add`, and `update` are nonmutating.
At Step 3, the exact `apply` command is reserved and fails unavailable.
The retired `audit`, `import`, and `adopt` aliases remain rejected.
Only a later, separately authorized `apply` may execute this runbook, and
authority for one plan does not carry to a recomputed plan. Chezmoi's
`run_onchange` integration invokes `status` only and has no authorization or
mutation input.

## Captured state

`captured-state-v1.schema.json` defines the secret-free manifest for one
migration run. The executor validates and seals it before requesting
authorization. Its candidate implementation identity, complete installed-
implementation manifest digest, catalog, lock, plan, plan-action-set, and
capability-set digest bindings make the capture unusable with another
controller, resolution, action projection, or adapter capability set.

`capability_bindings` is a closed array of objects containing only
`capability_identity`, `capability_digest`, and
`manager_version_evidence_digest`. Sort the objects by that three-field tuple,
serialize the array as UTF-8 canonical JSON with sorted object keys and no
insignificant whitespace, and SHA-256 digest those bytes to produce
`capability_set_digest`. Every provider route repeats the one applicable closed
binding, which must exactly match a member of the top-level set.

The manifest records every affected provider route with:

- its route identity, harness, and complete equipment identity set;
- its route control owner, single provenance owner, and exact capability and
  manager-version evidence binding;
- when absence will be changed by install, a reference by exact identity and
  digest to the separately supplied validated plan-action set;
- immutable revision, artifact reference, and content digest, or the
  native-rolling channel, observed version or absence, observation source, and
  native update control; and
- explicit captured or `not_applicable` references for singleton installation,
  singleton enablement, and projector surfaces, plus complete reference arrays
  for MCP selections, plugin selections, and mutable Claude skill entries.

It records these surfaces separately:

- **Legacy Claude projector:** Presence, enabled state, `blanket`,
  `catalog_driven`, or `retired` mode, implementation digest, exact owned
  source/control location, and private recovery material.
- **Candidate Claude skill entry:** Catalog identity, projection route, path,
  `lstat` type, applicable metadata, and provenance. A symlink also records
  exact link text plus its resolved target or original broken state.
- **Canonical Agent Skills entry:** The same path evidence under
  `~/.agents/skills`, with mutation policy `forbidden`. Deterministic manifests
  and digests represent regular-file bytes, directory content, nested entry
  types, and applicable metadata.
- **Plugin installation:** Native identity, manager, scope, presence, channel,
  observed version, and observation source.
- **Plugin enablement:** Applicability and the exact enabled or disabled state.
- **MCP selection:** Narrow owning source and key path, presence,
  secret-redacted structural state, and private exact recovery material.
- **Plugin selection:** Narrow owning source and key path, presence,
  secret-redacted structural state, and private exact recovery material.

Surface and route identifiers are unique. A surface's canonical logical
identity is its kind, route, canonical locator, and equipment identity when the
surface carries one; logical identities are also unique. Every mutable routed
surface is referenced exactly once from its owning route's kind-specific slot.
Independently, `(kind, canonical locator)` is unique across all mutable
surfaces, regardless of route or equipment labels. One physical surface cannot
receive competing mutation owners, captures, or recovery records. A deliberately
shared verification-only observation remains one `forbidden` record or follows
another explicit nonmutable rule; it does not create duplicate mutable records.
Installation and enablement are singleton slots and must reference the route's
only surface of that kind. Each routed skill has exactly one
`canonical_skill_dependencies` reference to its verification-only
`~/.agents/skills` counterpart. Every route reference resolves to exactly one
surface of the required kind, every route named by a surface exists, and the
surface's route and equipment identities agree with the resolved plan. Orphan,
duplicate, contradictory, dangling, wrong-kind, and wrong-route surfaces
invalidate the capture.

The public `validate_captured_state` API and CLI load and enforce both checked-in
JSON Schemas before running these semantic checks. Schema-invalid input has no
semantic interpretation. CI also runs the pinned independent schema checker to
validate the schemas themselves and their fixtures. The CLI parses strict JSON:
duplicate object keys and non-JSON numeric constants are read failures, not
alternate spellings of a sealed artifact.

`plan-action-set-v1.schema.json` defines a separate, closed, secret-free
projection emitted only after the resolver validates the complete plan. It
contains every automated action from that plan, across install, configure,
enable, disable, remove, and restore where the settled target matrix has an
exact physical projection. Unsupported native operations, including native
update suppression, fail closed at projection; they do not produce a partial
artifact. `project_plan_action_set` consumes only the complete `ValidatedPlan`
and emits the complete immutable set or diagnostics only. It accepts no caller
target map and derives no authority from captured state or route references.
Separate admission still requires the independently trusted set digest.

Each projected payload preserves action identity and ordinal; catalog, lock,
and plan digests; capability, manager-version, adapter, and harness executor
bindings; route identity and digest; the exact closed provider target; active
equipment identities; distinct controlled equipment identities; activation
group; the exact write-surface scope; operation and automated disposition;
desired state and its target-fragment digest; secret-reference names without
values; complete compare/checkpoint preconditions; verification-only read
dependencies; and compensation. The plan projection does not carry complete
normalized post-state authority; that adapter-derived state and its digest are
sealed in the matching `PreparedActionAuthoritySet`. The action's surface
authority derives from the union of active
and controlled equipment; disabled controlled equipment does not become active
coverage.

`surface_scope` retains the adapter contract's sorted logical surface
identities. A separate closed `write_targets` set binds every logical identity
to its exact physical target kind, applicable equipment identity, and
secret-free locator. Derive each `target_identity` by canonicalizing the target's
kind, locator, and applicable equipment identity, then SHA-256 digesting that
physical coordinate set. Exclude `write_surface_identity`; validate that logical
binding separately. Captured action references bind every target identity
exactly once to one captured surface ID; the surface must match the target's
kind, equipment, locator, route, route slot, and reconciler ownership. MCP and
plugin selections always carry equipment identity in both the target and
capture; the route-wide legacy projector does not. This preserves the
authoritative adapter vocabulary without treating a capture-local record ID as
plan authority.

The provider projection uses the same closed standalone-skill, native-plugin,
and direct-MCP variants as the catalog. Direct-MCP arguments retain literals,
environment-reference templates, or opaque secret-profile references, never
resolved values. HTTP MCP endpoints use the same static credential-free HTTPS
grammar: no userinfo, query, fragment, encoded or platform separators,
traversal, malformed host labels, or credential-shaped path segments. The
executor applies separately reviewed network-destination policy; the serialized
grammar does not classify a syntactically valid private endpoint as public.

Recompute `desired_state_digest` over canonical desired-state JSON and
`action_digest` over the complete canonical projection. Derive
`action_identity` as `action:sha256:<hex>` over canonical JSON containing
exactly `plan_digest`, `ordinal`, `route_id`, `operation`, and
`desired_state_digest`. Serialize actions by the topological ordinal already
bound by the authoritative validated plan, then identity. This serialization
rule does not derive or validate dependencies. The complete plan owns the
closed, acyclic dependency graph and binds it into `plan_digest`; the executor
must validate that graph and every ordinal before emitting this projection.
Produce `action_set_digest` by canonicalizing exactly `schema_version`,
`candidate_identity`, `implementation_manifest_digest`, `plan_digest`, and
that ordered `actions` array, then SHA-256 digesting those bytes. The golden
vectors in `tests/test_agent_equipment_captured_state.py` bind both candidate
fields, including the empty-action-set case.

The captured manifest stores only `bindings.plan_action_set_digest` and each
route's closed `planned_actions` identity/digest references. Semantic
validation takes
the independently supplied action set as a required second input. It recomputes
the set, action, identity, and desired-state digests; requires the set's
`plan_digest` to equal `bindings.plan_digest`; requires the captured set digest
binding to match; and requires exact one-to-one ownership between supplied
actions and route references. Every reconciler-owned captured surface belongs
to exactly one action's write scope, and every write scope names only captured
reconciler-owned surfaces on its route. An operator-owned route cannot reference
an automated action or carry native inverse compensation. A self-consistent
action invented in captured state therefore cannot validate against the sealed
plan projection.

For a Claude skill projection, the action also binds the projection write
surface identity to exactly one canonical read dependency identity. The
captured action reference maps that dependency to one canonical surface record.
Route, equipment identity, canonical target locator, and skill basename all
match. The canonical surface remains `forbidden` and verification-only; it
never enters an action's write scope.

Derive each canonical skill `dependency_identity` as `dependency:` followed by
the canonical JSON SHA-256 digest of exactly `relationship` set to
`canonical_skill_projection`, the validated `write_surface_identity`, the
validated skill `equipment_identity`, and `target_locator` set to the canonical
JSON object `{"path":"~/.agents/skills/<validated basename>"}`. Admission
independently recomputes that identity. The identity is a semantic consistency
coordinate; it does not grant admission, mutation, provenance, or runtime
authority by itself.

This captured-state validator does not establish that its second input came
from the authoritative complete plan. The caller must first validate the plan
and its exact projected membership, then pass and seal that independently
produced artifact. Supplying a newly invented action set and changing the
captured binding to match is not authority.

Every native-rolling route references exactly one plugin-installation surface.
`route_absent` restore evidence agrees only with `installed: false`; without a
forward install, that surface carries `none/absent_noop` recovery. Only an
absent-to-present transition resolved through the independently validated
plan-action set may carry `native_inverse/remove`. That same install action must
own the exact plugin-installation physical target and its captured write
binding; an install action for another surface cannot authorize compensation.
Presence, resolved
forward-install evidence, and destructive inverse eligibility are checked
before restore-class handling,
so an immutable route cannot use remove compensation. An observed native
version agrees only with `installed: true` and identical version, channel, and
observation source, and uses non-mutating `already_desired` or `operator_owned`
recovery. Any contradiction invalidates the capture before authorization.
For a guarded remove inverse, `recovery.expected_pre_state_digest` equals the
matching `PreparedActionAuthoritySet` member's `expected_post_state_digest`,
the canonical digest of the complete normalized forward post-state. Plan-only
capture validation fails closed until that independently validated prepared
authority is available. The guard is distinct from `desired_state_digest`,
which binds only the planned target fragment.
Compensation may run only while the complete expected post-install state still
matches.

Recovery material agrees with observation state. An absent mutable entry or
selection uses `absent_noop`; a present Claude entry or secret-redacted
selection requires sealed private recovery material; and a present structured
surface requires a bound structured or private snapshot. A capture that claims
present state while retaining absence recovery is invalid.

### Acceptance expected cases and result bundle

`acceptance-evidence-v1.schema.json` closes three release documents. After the
plan-action set and capture are sealed, the production evidence writer projects
one expected-case manifest bound to their complete candidate, catalog, lock,
plan, capability, capture, and route-evidence tuple. Static records cover every
nonderived requirement, including `ADP-*`, `CAP-*`, and `LIVE-*`. The writer
adds every automated plan-action identity, every explicit read-only verification
node, and every explicit mutating migration boundary from the validated graph.

The semantic validator derives one `CHK-02` through `CHK-09` case for every
automated action and mutating migration boundary. It maps `MIG-*` only from each
sealed node's explicit requirement list. Before authorization, the projection
gate rejects a plan node absent from the manifest or a manifest node absent from
the validated plan graph. Release replay does not reconstruct that graph from
the eleven archived streams: it authenticates the closed verification and
migration nodes through the authorized manifest digest while independently
recomputing the manifest's exact artifact bindings, plan-action identities, and
plan/captured-state route capability set. This runbook is never parsed to invent
a node.

During execution, the evidence writer records one exact child per expected case
and derives the 75 aggregate results. Mutation cases bind before and after
observation digests. Checkpoint cases bind the ordered checkpoint and
compensation trace. Live cases require a live receipt and explicit human
sign-off; an automated or fake-manager receipt cannot pass them. Opaque artifact
references and public version strings never contain raw native output or secret
values.

The candidate-independent release launcher obtains the authorized expected-case
manifest digest from the exact trusted pre-mutation authorization. After
execution, a separate release authority attests the bundle's canonical semantic
digest and supplies the trusted attestation digest. The launcher is independently
installed at
`/usr/local/libexec/agent-equipment-release/v1/agent-equipment-release`, outside
the evaluated candidate and its installed manifest. It verifies its own exact
identity and manifest digest from external trust inputs, then strictly parses
the eleven exact release inputs: apply authorization, complete plan-action set,
captured-state manifest, capture-observation-authority set,
prepared-action-authority set, complete checkpoint-store snapshot,
checkpoint-set manifest, run-terminal record, expected-case manifest, bundle,
and attestation. It obtains the
expected capture-observation-authority identity/digest from the validated apply
authorization and revalidates that artifact before it performs one create-only
compare-and-swap archive commit using a closed `ReleaseArchiveManifest` over
the exact input byte digests and execution tuple, including the independently
trusted execution-domain identity, exact complete plan-action-set and captured-
state artifacts, the sealed full-record checkpoint-store snapshot, its
validated checkpoint-set projection, and authenticated `RunTerminalRecord` with
`state: succeeded`. All eleven exact byte streams are archived and bound by
byte digest. Only after generation `1` is
durable does it emit the closed `ReleaseReceipt`. Candidate output cannot mint,
overwrite, ignore, or substitute for that receipt. A compensated, blocked, or
nonterminal run cannot produce a passed receipt. The candidate evidence writer,
attestation writer, and validator do not grant apply authority or mutate harness
state.

### Filesystem observation

Observe a skill entry with `lstat`; use `readlink` for link text. Resolution of
a link target is read-only evidence and never changes the object selected for a
write. A directory manifest walks entries in deterministic bytewise relative-
path order without traversing directory symlinks. For every entry it records
type and applicable metadata; it records regular-file size and byte digest,
directory metadata, and symlink text plus resolved or broken state. The
canonical JSON digest of that manifest is the directory content claim.

A captured Agent or Claude skill path is exactly one direct child of its stated
skills root. Its basename is non-empty, is neither `.` nor `..`, and contains no
NUL, slash, backslash, or platform path separator. Production execution still
performs containment checks at the filesystem boundary; a sealed manifest does
not defer lexical validation until execution.

The metadata record states the capture platform and records mode, uid, gid,
nanosecond mtime, flags when supported, and digests or explicit
`none`/`unsupported` results for ACLs and extended attributes. A comparison uses
exactly the fields declared applicable at capture.

Every `~/.agents/skills/<name>` surface is verification-only. The migration may
read its entry and, when resolvable, its target. It may not delete, replace,
rename, chmod, chown, rewrite, traverse through a symlink for a write, or use it
as the destination of a native installer. Drift on one of these surfaces stops
the migration; rollback never writes to it.

### Recovery material and secrets

The manifest contains secret reference names, never resolved values. Exact raw
pre-state needed to restore an owned config key or projector file is sealed in
the private checkpoint content-addressed store. The manifest references the
blob by a digest of its sealed ciphertext. Comparisons involving secret-bearing
state happen locally against the unsealed recovery blob and emit only
match/mismatch evidence. Logs, diagnostics, diffs, receipts, and generated
artifacts contain neither values nor unsalted digests of values.

A Claude symlink needs no raw target content: its exact link text, link metadata,
and broken or resolved state are sufficient recovery material. Native-manager
recovery is an inverse operation bound to the captured normalized native state.

## Compare contract

The unit of comparison is the narrowest surface an action can mutate: one path
entry, one plugin identity and scope, one enablement bit, or one owned config
key path. An adapter preserves unrelated keys and native state. It never uses a
whole-file rewrite when a narrow owned overlay is available.

Immediately before each action:

1. If this run has not changed the surface, observe it and require exact
   equality with captured pre-state.
2. If an earlier completed action in this run changed the surface, require
   exact equality with that action's expected post-state.
3. Reverify every canonical Agent Skills entry on which the action depends.
4. Persist the comparison result in the mutation receipt without including
   secret values.

Immediately before compensation, observe every surface in the action and
require exact equality with the post-state written by that action. Restore only
after that comparison succeeds. This is compare-before-restore, not a request
to force the old value.

- **Projector:** Compare the owned source/control location, presence, enabled
  state, mode, and implementation bytes through their private or secret-free
  digest.
- **Claude or Agent Skills entry:** Compare `lstat` type and applicable
  metadata, then file bytes, the deterministic directory manifest, or exact
  link text and resolution evidence according to type.
- **Plugin installation:** Compare native identity, scope, presence, channel,
  observed version, and manager-reported source.
- **Plugin enablement:** Compare plugin identity, scope, applicability, and
  enabled state.
- **MCP or plugin selection:** Compare presence and exact raw value at the owned
  key path inside the private process boundary. Put only the secret-redacted
  structure in the receipt.

A mismatch is concurrent or manager-driven drift. The executor preserves the
observed state, writes a secret-free drift report, stops all forward processing,
and begins compensation only for surfaces whose restore guards still match.
If a restore guard mismatches, compensation also stops. It never overwrites the
external change to make rollback appear complete.

## Ordered migration

Each numbered mutation is a separately checkpointed action or a deterministic
series of separately checkpointed actions. The authorized plan represents these
actions as a closed dependency graph. It rejects missing references, orphan
actions, incomplete provider-switch dependencies, and cycles before opening the
checkpoint store. Execution uses a deterministic topological order; the
canonical equipment, harness, route, operation, and action-identity tuple is
only a tie-break among actions whose dependencies are already satisfied.

Projector readiness precedes official Matt activation. Installation precedes
enablement; verified enablement and the complete active Matt activation group
precede every losing Claude-link retirement. All route changes precede final
coverage verification. Reverse compensation walks the reverse topological
order, which restores every removed link before disabling or uninstalling the
winner and restores the legacy projector last. A completion criterion follows
each step.

### 1. Resolve, capture, seal, authorize, and compare

Resolve and validate the entire plan, emit and independently validate its exact
complete automated-action projection, acquire the apply lease, capture every
route and surface, validate the capture against the separately supplied action
set, and resolve again against it. If the capture changes the plan or action
projection, regenerate and recapture until the plan, action set, and capture
agree. Atomically seal the plan-action set, captured-state manifest, and private
recovery blobs. Before authorization issuance, derive and independently validate
the complete `CaptureObservationAuthoritySet`: one canonically ordered
observation per plan action and no others, with exact candidate, implementation,
plan, plan-action-set, capability, capture, surface, controlled-component, and
normalized-pre-state bindings. Seal its independently trusted identity and
digest. The raw observation-list and standalone expected-observation-digest API
does not exist. Derive the complete `PreparedActionAuthoritySet` from that exact
artifact: one canonically ordered member per plan action and no others, with
exact plan/capability/capture bindings, adapter-normalized pre/post states,
controlled-component identities, desired-state fragment, operation, surface,
and compensation. Require each prepared pre-state to equal its matching capture-
observation member, then seal the prepared set's independently trusted identity
and digest. Project and seal the exact acceptance expected-case manifest,
including all explicit verification and migration nodes, then obtain
the exact closed `ApplyAuthorization` naming the complete candidate,
implementation-manifest, catalog, lock, plan, action-set, capture-observation-
authority-set, prepared-action-authority-set, capability-set, captured-state,
and expected-case-manifest tuple
plus the command, run, validity
window, fresh nonce, independently trusted execution-domain identity, and exact
operator-review-package digest. Receive
`trusted_apply_authorization_digest` through
the external authority channel.

After authorization, strictly validate the exact bytes and digest and verify the
trusted time window. Then recompute the installed implementation manifest and
reread every affected surface and bound capability and manager-version evidence
source. Proceed only
when the candidate identity, implementation digest, and all live evidence equal
the authorized sealed capture. Otherwise release the proposal without mutation,
recapture, resolve, reseal, and obtain new authorization. A ledger claim is never
deleted for reuse. After the exact comparison and immediately before the first
action checkpoint, durably claim the nonce by CAS in the one authoritative
ledger namespace and target named by `execution_domain_identity`.

Completion: the authorized plan, sealed action set, sealed capture, and expected-
case manifest have identical bindings; the authorization identity and canonical
digest are exact; its execution domain is independently trusted; its nonce is
claimed once for this run in that domain; the post-authorization
live comparison is exact; both authority sets match the exact identity/digest
tuples bound by the validated apply authorization; all route and surface cross-references validate; no
harness state has changed; no action checkpoint exists yet.

### 2. Replace the blanket Claude projector

Prepare a checkpoint for the projector control surface. Compare it with its
captured state, install the catalog-driven replacement without running
projection reconciliation, and verify that it projects only catalog-selected
standalone routes. Its exclusion set must include every Claude identity whose
preferred route is the Matt plugin. Mark the checkpoint completed.

The replacement must be effective before link removal and must not create,
remove, or rewrite a Claude skill entry as a side effect of installation.

Completion: a verified catalog-driven projector owns future projections; every
candidate Claude and canonical Agent Skills entry still equals captured state.

### 3. Install the official Matt plugin when absent

Compare the captured plugin installation surface. If the official plugin is
absent, run the locked install operation for
`mattpocock-skills@claude-plugins-official` at user scope and verify the native
identity, channel, observed plugin version, manager source, and full 25-skill
activation group. Persist the native state that installation actually writes,
including enablement when the manager couples it to install.

If the plugin was already installed at the reviewed route and baseline, install
is a no-op. A different marketplace route, version, source, or component set is
manager-driven drift and requires replanning. The migration never updates or
reinstalls a pre-existing native-rolling artifact.

Completion: the reviewed official plugin route is installed once, or the
pre-existing reviewed installation remains untouched. The installation
checkpoint's expected post-state includes every native surface changed by the
install command. The projector remains catalog-driven and every candidate
Claude link still equals captured state.

### 4. Enable and verify the official Matt winner

Compare against captured state or the installation checkpoint's expected state,
whichever is newer. Enable the plugin only when installed and disabled. If
installation already enabled it, or it was enabled before migration, record a
verified no-op. Then obtain a fresh supported-runtime observation and verify all
25 exported skills are active as one inseparable activation group; this Claude
route has no supported per-skill suppression. The active
`equipment_identities` must equal the resolved preferred activation group.
Disabled `controlled_equipment_identities` remain control targets and do not
count as active winner coverage.

Completion: the official Matt plugin is installed and enabled, its complete
active activation group is freshly verified against the authorized plan, and a
completed enablement checkpoint exists only when this step changed enablement.
No losing projection has been removed.

### 5. Remove only identified Matt projections

Every removal action depends on the completed winner-verification prerequisite
from step 4. The executor stops without unlinking anything if the official Matt
activation group is incomplete, stale, or no longer enabled.

Iterate the resolved Matt equipment identities in canonical order. For each
`~/.claude/skills/<name>` candidate:

- an absent captured entry is a verified no-op;
- a captured symlink is eligible only when its exact link text, target or
  broken state, catalog identity, route, and provenance prove it is the
  catalog-owned standalone projection for that identity; and
- a regular file, directory, unknown-provenance link, or link to an unexpected
  target is fatal drift and is not removed.

For each eligible link, reverify the winner prerequisite and its canonical
Agent Skills entry, persist a prepared checkpoint, compare the link with
captured state, and unlink the link entry itself. Do not resolve the path before
unlinking and do not use recursive removal. Verify the Claude path is absent,
then persist completion before advancing to the next link.

The current research fixture observes 21 eligible links and four absent
projections among 25 Matt identities. Those counts are dated evidence, not an
execution constant; the refreshed catalog-identified set controls the run.

Completion: every eligible Claude projection is absent, every ineligible entry
was preserved or stopped the run, the verified official Matt activation group
remains active, the projector remains catalog-driven, and all 25 canonical
Agent Skills entries remain byte-, type-, link-, and metadata-equivalent to
capture.

### 6. Reconcile MCP selections component by component

For every MCP identity in the plan, compare each exact selection surface and
apply only its catalog-selected route change. Prefer a plugin-provided MCP only
when its entire required equipment set is present and the harness exposes a
supported component control. If a plugin also supplies a hook, skill, or other
component that the standalone routes cannot replace, retain the plugin, retain
an explicitly allowed supplementary route, select supported components, or
stop for a case-by-case operator decision. Plugin installation alone never
implies that all of its components are selected.

Treat each independently controllable MCP selection as one action. Treat a
manager's inseparable component set as one activation-group action. An
operator-owned Cursor plugin remains verify-and-report-only until a stable
mutation contract exists.

Completion: every MCP has exactly the preferred route plus only documented
supplementary routes; every removed selection has a completed checkpoint and
private exact recovery material; unrelated config and native state are
unchanged.

### 7. Reconcile plugin and component selections

Apply the remaining plugin selection, standalone-skill suppression, and
selective component controls from the plan. Use component controls before
treating a plugin as atomic. Disable a standalone Codex or Cursor skill only by
its exact catalog-owned path and only when the preferred plugin component is
verified active. Preserve an overlap only through an explicit `allow_overlap`
exception that names the complete active route set and rationale.

Operator-owned selections produce instructions and evidence, not automated
mutations. A required operator action leaves the automated migration incomplete
until it is performed under separate authority and a fresh `status` observation
confirms it.

Completion: every equipment identity has exactly one canonical harness coverage
record and every active provider route has its declared operation disposition;
the effective route set matches the plan with no inferred duplicate.

### 8. Verify and complete the run

Run `status` against supported runtime surfaces and verify all of these together:

- the catalog and lock bindings still match the authorized plan;
- the blanket projector cannot recreate excluded links;
- only catalog-identified Matt Claude symlinks are absent;
- every canonical Agent Skills entry remains exactly as captured;
- the official Matt plugin exposes the refreshed, reviewed activation group and
  has its intended enablement;
- MCP and plugin selections match preferred and allowed supplementary routes;
- every active route has one provenance owner, supported restore evidence, and
  a complete operation matrix;
- no managed duplicate remains and every intentional overlap is explicit;
- operator-owned and unavailable operations are reported without mutation; and
- artifacts, logs, diagnostics, diffs, receipts, and checkpoints disclose no
  secret value.

Only after the whole verification passes may the executor durably mark the run
`succeeded`. A second `status` invocation against the same catalog, lock, and
live state must produce an empty mutation plan.

The evidence writer then seals the exact migration and live child receipts into
the candidate bundle and derives the aggregates. The candidate-independent
release authority attests the bundle's canonical semantic digest after every
result and live sign-off, and the release command validates all three documents
against the authorized expected-case and attestation manifest digests. The
external launcher also validates the exact apply authorization and its own trusted launcher
identity/digest, then commits the authorization, capture-observation-authority
set, prepared-action-authority set, plan-action set, captured-state manifest,
checkpoint-store snapshot, checkpoint-set manifest, run-terminal record, three
release documents, and
closed archive manifest over their exact serialized byte digests and execution
tuple, including `execution_domain_identity`, the validated checkpoint-set
digest, and the authenticated run-terminal identity and run-terminal digest,
with an `absent` compare token.
Generation `1` is create-only;
identical existing bytes are idempotent and different bytes are a conflict.
Missing, extra, duplicated, nonpassing, stale-attested, or misbound evidence—or
a failed/conflicting archive commit—withholds the release receipt and preserves
the complete run evidence; it never edits a checkpoint or fabricates rollback
authority.

Completion: the success marker is durable and fsynced, the apply lease is
released, steady-state `status` is a no-op, and the exact apply authorization,
plan-action set, captured-state manifest, capture-observation-authority set,
prepared-action-authority set, checkpoint-store snapshot, checkpoint-set
manifest, run-terminal record, expected-case manifest, evidence bundle,
attestation, archive manifest, and
closed `ReleaseReceipt` are durably present in the independent authority store.
Any failed runtime condition enters the recovery procedure.

## Checkpoints and idempotence

One checkpoint binds a single adapter action and every surface that action can
change. It records the complete `CHK-10` tuple: apply-authorization identity and
digest, execution-domain identity, execution nonce, run and candidate identities;
installed-implementation manifest digest; catalog, lock, plan, capability-set,
sealed captured-state identity/digest, and prepared-action-authority-set
identity/digest bindings; the route's closed
capability and manager-evidence binding; action identity and deterministic
ordinal; route and operation; captured pre-state and expected post-state
digests; and compensation operation. It additionally records attempt receipts,
phase, durable invocation intent (`not_started` or `started`), and
`compensation_authority_kind`. The apply-authorization identity/digest,
execution nonce, run, and domain participate in the immutable checkpoint
identity and are validated against independent apply inputs.

The action state machine is:

```text
prepared --forward verified--> completed
prepared --explicit rollback after fresh status observation--> compensating
completed --rollback--> compensating
compensating --restore verified--> compensated
prepared | completed | compensating --ambiguity or drift--> compensation_blocked
```

The direct `prepared` to `compensating` transition requires a fresh status
observation of the prepared action and a closed `CompensationAuthorization`.
That record uses Schema version
`agent-equipment-compensation-authorization/v1`, identity prefix
`compensation-authorization:sha256:`, `command: compensate`, issuer and validity
window, a fresh `compensation_nonce`, and exact bindings to the original
apply identity/digest, execution-domain identity, execution nonce, run,
checkpoint-set digest, and plan-action-set digest. Its canonical complete digest
is supplied independently. Under the exclusive lease, enumerate all and only
the authoritative durable checkpoints for that exact original apply/run/domain
and validated plan action set into a closed `CheckpointSetManifest`. Each
ordered entry projects the durable generation/version, phase, invocation state,
immutable checkpoint identity, action/ordinal, and canonical digest of the
complete checkpoint record. Reject empty, missing, extra, duplicate, reordered,
foreign, stale, malformed, or resealed records. Derive the authorization's
checkpoint-set digest from that manifest, then re-enumerate the store and check
the same generation immediately before the nonce claim and first transition;
any concurrent change fails closed. Before the transition, claim
`compensation_nonce` once by CAS in the same authoritative execution-domain
ledger namespace. Crash
recovery cannot infer this public compensation authority merely from a surviving
`prepared` record or reuse `ApplyAuthorization`. It resumes only from the
archived original authorization and pretransition manifest plus the independently
trusted durable compensation-ledger claim. The current store must be a race-
rechecked monotonic descendant: the same checkpoint identities, unchanged
forward invocation intent, strictly newer record/store generations for every
change, and only public claims bound to the original authority. The ledger claim
also closes the crash window before the first checkpoint transition, so recovery
does not mint a new nonce or reapply the expired clock window. A blocked
checkpoint still requires separate operator disposition.

The independently validated plan input is the complete closed
`agent-equipment-plan-action-set/v1` artifact, not a caller-projected action
list. Recompute every action identity/digest and the complete set digest, compare
its candidate, installed implementation, plan, and set bindings with independent
inputs, and require every stored checkpoint to map uniquely into that complete
set. The store remains all-and-only the prepared checkpoint subset, so an early
crash is recoverable without pretending unstarted actions have checkpoints.
At every checkpoint, compensation, recovery, terminal, archive, and receipt
validation seam, supply the exact `CaptureObservationAuthoritySet` and expected
identity/digest taken from the validated `ApplyAuthorization`. Revalidate its
all-and-only projection before matching each prepared pre-state; never accept a
raw observation list or derive the expected digest from the supplied artifact.
That prefix must also have one reachable cross-record lifecycle. Forward state
is `completed*` plus at most one final `prepared` action. Reverse state is
`completed*`, then at most one lowest nonterminal compensation frontier, then
`compensated*` in ascending ordinal order. A lower action cannot compensate
while a higher dependent remains forward. Every public claim uses the closed
non-null identity/digest/nonce formats and is validated against independently
supplied original compensation authority.

Persist and fsync `prepared` with `invocation_state: not_started`, then compare
current state with the captured pre-state. Immediately before the adapter call,
persist and fsync `invocation_state: started`; failure to persist that intent
forbids the call. Persist and fsync `completed` only after post-state
verification. Before rollback, persist and fsync `compensating`; after
restoration and verification, persist and fsync `compensated`. Records are
append-only state transitions or compare-and-swap replacements; an older writer
cannot overwrite a newer phase or invocation intent.

Automatic reverse compensation within the claimed apply invocation records
`compensation_authority_kind: automatic_apply` and no public claim. A public or
fresh invocation records `public_compensation` and a separate closed transition
claim binding the immutable checkpoint identity plus the independently
validated compensation-authorization identity/digest and nonce. The claim has
its own canonical identity and digest and never changes the checkpoint identity.
Recovery rejects an ambiguous kind/claim pair and a canonically resealed foreign
claim.

Release validates a closed `RunTerminalRecord` against the independently
validated checkpoint manifest and the exact plan-action-set, captured-state,
and sealed full-record checkpoint-store-snapshot bytes. `state: succeeded`
requires one unique completed checkpoint for every complete plan action, with
durable generations increasing in canonical action order. The archive stores
all eleven exact release streams and binds all eleven byte digests; a lossy
checkpoint projection, naked checkpoint digest, and terminal-state scalar are
never release authority.

`compensation_blocked` is terminal for automatic recovery. It records an exact
compare-before-restore or ambiguous-effect mismatch, preserves the observed
external state, durably moves the run to `needs_operator`, and prevents partial
rollback from being labeled recovered. Only a separately authorized operator
disposition can supersede it; the existing checkpoint remains historical
evidence.

Recover a surviving `prepared` checkpoint through a fresh status observation:

- observed pre-state means the action did not take effect and can be retried
  only through a newly persisted invocation intent;
- `started` plus observed expected post-state means the attempted invocation
  took effect, so record completion without replay;
- `not_started` plus observed expected post-state is concurrent target-valued
  drift, not this run's effect; preserve it and stop; and
- any other observation is partial or concurrent drift, which is preserved and
  requires operator recovery.

Recover `compensating` by the inverse rule: captured pre-state means record
compensation without replay; expected post-state means retry compensation after
the restore guard passes; any other state is preserved and stops recovery.

A completed run whose live state still equals its expected state is a no-op on
rerun. A compensated run is historical evidence, not a license to replay; a new
apply requires a fresh sealed capture and authorization naming the complete
candidate implementation identity/manifest digest, catalog, lock, plan,
plan-action-set, capability-set, captured-state identity/digest, and sealed
expected-case-manifest digest tuple plus a new run identity, validity window,
and execution nonce. An already claimed nonce never authorizes the new apply.

Immediate reverse compensation after a later failure remains part of the
already invoked, claimed apply run and needs no second authority. A fresh or
public `compensate` invocation, including an ambiguous prepared-action path,
requires the separate `CompensationAuthorization` and durable compensation-
nonce claim above. It cannot start a forward action or authorize another run.

## Step-level compensation

Rollback processes completed actions in reverse topological order. The ordinal
is the sealed result of the validated dependency graph, not an independently
sorted execution rule. An ambiguous prepared or compensating action receives a
fresh status observation and classification before rollback continues.

- **Install the catalog-driven projector.** No-op when the exact implementation
  digest and control state are already present. Compensation restores captured
  projector bytes and control state, but restores a blanket projector only
  after every removed link. The guard requires the projector to still equal the
  replacement written by this run.
- **Remove one Claude skill link.** No-op when the captured entry was absent.
  Compensation recreates the exact symlink text at the same path and restores
  applicable link metadata and broken/resolved semantics without writing
  through the link. The guard requires the Claude path to remain absent and its
  canonical Agent Skills entry to equal capture.
- **Install the Matt plugin.** No-op when the reviewed route was already
  installed. Compensation may uninstall only the instance this action installed
  from confirmed captured absence. The guard covers plugin installation and
  every install-coupled surface in this action's expected post-state. This is a
  narrow inverse for the just-created instance, not general native-plugin
  removal.
- **Enable the Matt plugin.** No-op when it was already enabled or installation
  coupled the desired enablement. Compensation restores captured enablement and
  retains a pre-existing plugin. The guard requires enablement to still equal
  the state written by this run.
- **Change one MCP selection or inseparable activation group.** No-op when the
  exact desired selection is present. Compensation restores exact captured
  presence and value from private recovery material. Every owned key must still
  equal this action's expected post-state.
- **Change one plugin or component selection.** No-op when the exact desired
  selection is present. Compensation restores the captured selection or exact
  standalone suppression entry. Every owned key and affected activation group
  must still equal this action's expected post-state.

If the Matt plugin was confirmed absent initially, restore and verify every
Claude link retired after winner verification first. Then reverse enablement
when it was a separate action and uninstall the instance created by this run
only while its exact restore guard passes. If installation itself enabled the
plugin, the installation checkpoint owns both surfaces and uninstall is its one
compensation after those links are restored. If the plugin existed initially,
rollback never uninstalls it and restores its exact prior enablement. Restore
the legacy projector only after links and native winner state equal captured
pre-state. A native-rolling route never claims an exact old artifact restore. It
cannot restore a prior artifact, and it has no general removal guarantee beyond
the guarded inverse of an install that began from confirmed absence.

Canonical Agent Skills entries have no compensation because they have no
authorized mutation. Their mismatch is a hard stop, not an invitation to repair
or replace them.

## Failure-injection contract

The acceptance matrix must exercise these boundaries against disposable homes
and deterministic fake adapters. Every case proves processing stops, checkpoint
state is durable, retry begins with a fresh status observation, external changes
survive, and eventual forward completion or compensation is idempotent.

- **Full-plan rejection:** Inject an invalid final action, stale lock, missing
  compensation, or operator-owned automated mutation. Reject before the first
  action checkpoint with zero harness mutation.
- **Capture persistence:** Fail the captured-state or private recovery write.
  Create no action checkpoint and perform zero harness mutation.
- **Prepared persistence:** Fail its write or fsync. Never call the adapter.
- **After prepared:** Stop before comparison or adapter call. Recovery observes
  pre-state and may retry once.
- **Compare-before-mutate:** Inject an external change on every surface in
  separate cases. Preserve it, skip the adapter, and stop forward processing.
- **Adapter before mutation:** Fail the call before mutation. Leave the
  checkpoint prepared; a fresh status observation reports pre-state.
- **Adapter ambiguous failure:** Return failure after a partial or complete
  mutation. A fresh status observation classifies pre-state, expected post-state,
  or other drift before retry.
- **After mutation:** Stop before verification. Recovery avoids blind replay;
  expected post-state becomes completed without a second mutation.
- **Verification failure:** Reverse-compensate earlier completed actions and an
  observed-and-classified completed current action.
- **Completed persistence:** Fail its write or fsync. Observe the surviving
  prepared state through `status` and record expected post-state completed
  without replay.
- **After projector replacement:** Restore every captured surface and restore
  the projector last.
- **After each individual Claude-link removal:** Restore that link and every
  earlier link exactly before disabling or uninstalling the winner; restore the
  projector last. Canonical Agent Skills entries never change.
- **After plugin installation:** Uninstall only when initially absent; retain a
  pre-existing installation.
- **After plugin enablement:** Restore prior enablement without uninstalling a
  pre-existing plugin.
- **After each MCP reconciliation:** Restore all changed selection keys exactly
  and preserve unrelated keys.
- **After each plugin/component selection:** Restore changed selections and
  suppressions exactly, including their activation groups.
- **Compensating persistence:** Fail its write or fsync. Never call the restore
  adapter.
- **Compare-before-restore:** Inject an external change separately on the
  projector, each link, plugin installation, enablement, every MCP selection,
  and every plugin selection. Preserve it and stop compensation durably.
- **Compensation ambiguous failure:** Fail before, during, and after restoration.
  A fresh status observation classifies captured pre-state, expected post-state,
  or other drift before retry.
- **Compensated persistence:** Fail its write or fsync. A fresh status observation
  recognizes restored pre-state and records compensation without destructive
  replay.

Run the mutation-boundary cases once for every planned action, not once per
adapter kind. Include resolved and broken Claude symlinks, regular-file and
directory canonical entries, applicable metadata changes, install commands that
couple enablement, native-rolling version drift, selective and inseparable
component controls, and secret-bearing selection values. Scan every observable
output for seeded secret values.

## Operator failure and recovery

1. Stop new applies and retain the exclusive lease. Do not rerun native manager
   commands, chezmoi projection hooks, or ad hoc link repair.
2. Locate the newest nonterminal run and verify its candidate implementation
   identity/manifest digest, catalog, lock, plan, plan-action-set, capture-
   observation-authority-set identity/digest, prepared-action-authority-set
   identity/digest, capability-set, captured-state identity/digest, and sealed
   expected-case-manifest digest plus every route capability binding against the
   authorized `ApplyAuthorization`. Revalidate both exact authority-set artifacts
   against those apply-bound tuples. Require its canonical digest to equal the original
   `trusted_apply_authorization_digest`, its execution domain to equal
   `trusted_execution_domain_identity`, and its ledger claim in that domain to
   name this exact run and nonce. A mismatch requires a new read-only
   investigation, not checkpoint editing.
3. Obtain a fresh status observation for every `prepared` and `compensating`
   checkpoint from supported surfaces. Record whether each surface equals
   captured pre-state, the action's expected post-state, or neither.
4. Resume forward only when the exact authorized plan remains valid, every
   ambiguous action is classified, all next-action compare guards pass, and the
   authorization remains within its expiry. After expiry, create no new action
   checkpoint or invocation; compensation and classification of already invoked
   work remain available under the historical ledger claim. Otherwise
   compensate completed actions in reverse topological order.
   Classification that would begin compensation from an ambiguous `prepared`
   record, or any separately invoked public `compensate` command, additionally
   requires a valid `CompensationAuthorization` and a one-time CAS claim of its
   `compensation_nonce` in that same execution domain before checkpoint change
   or adapter invocation.
5. At a compare-before-restore mismatch, preserve the external state and stop.
   Report the exact surface, expected secret-free state, observation source,
   and checkpoint. Obtain an explicit decision to retain the external change
   in a new plan or have its owner restore the expected migration state before
   compensation resumes.
6. At a native compensation failure, obtain a fresh status observation before
   retry. If a plugin absent at capture now differs from the installation written
   by this run, do not uninstall it. If a plugin existed at capture, never
   uninstall it; restore only enablement or selections that still pass their
   guards.
7. After compensation, verify every mutable surface equals captured state and
   every canonical Agent Skills entry remains unchanged. Mark the run
   `compensated` only when all restorations are durable. Otherwise mark it
   `needs_operator` and retain every checkpoint and recovery blob.
8. Release the lease only after a terminal `succeeded` or `compensated` state,
   or after recording a deliberate operator handoff for `needs_operator`.
   Archive checkpoints according to retention policy; never delete evidence to
   clear an error.

Successful recovery restores every captured mutable surface unless a concurrent
change makes restoration unsafe. In that case, preserving the external change
and stopping is the stronger invariant; completion waits for a separately
authorized replan.

## Postconditions

After success:

- the Claude projector is catalog-driven and cannot recreate the retired Matt
  projections;
- only catalog-identified Matt links are absent from `~/.claude/skills`;
- every `~/.agents/skills` entry remains in its captured type and state;
- the reviewed official Matt plugin route is installed and enabled;
- MCPs, plugins, component controls, and standalone suppressions match complete
  provider selections without undocumented duplication; and
- a repeated `status` invocation proposes no mutation.

After compensation, every mutable surface equals captured state and the legacy
projector is restored only after its projections. A concurrent-change stop is
neither success nor completed rollback; it is durable `needs_operator` state.
