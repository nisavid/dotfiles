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
| Apply checkpoints | reconciler runtime state directory | Recovery evidence for one immutable plan |

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
10. Derive the selected command's report, proposal, or mutation plan.
11. Validate the complete result before returning any executable plan.
12. Sort by equipment identity, harness, route identity, and operation ordinal.

Every diagnostic has a stable code, equipment identity when applicable,
harness and route when applicable, a secret-free message, and evidence source.
An unresolved identity, incomplete route, invalid overlap, coverage-control
mismatch, stale lock, unknown capability needed by an automated operation,
operator-owned automated mutation, or missing compensation is fatal for apply.
Fatal validation yields no mutation plan.

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
- Every active route has one provenance owner and one restore class.
- Every active route carries the exact selected component controls as unique
  equipment identity plus `enabled` or `disabled` state. Conflicting controls
  are invalid; an empty array states that no selective control applies.
- Every active route has exactly one disposition for every operation in the
  operation matrix.
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
| `update` | Yes | Allowed for source resolution | Proposed resolved lock | None |
| `adopt` | Yes | No by default | Proposed catalog ownership transfer | None |
| `apply` | Yes | Allowed only for locked restore | Checkpoint ledger only | Automated operations on reconciler-owned routes |

`import` does not claim ownership. `adopt` requires the exact imported
observation identity and changes authored ownership only; a later apply performs
any runtime reconciliation. `update` advances immutable revisions and reviewed
native-rolling baselines without installing them. Apply never advances a lock.

## Adapter interface

Each production adapter should satisfy one internal seam:

```text
capabilities() -> capability records
observe(request) -> runtime observation
apply(action, expected_pre_state) -> mutation receipt
verify(action) -> runtime observation
compensate(action, expected_post_state, captured_pre_state) -> mutation receipt
```

Requests carry only resolved route data and secret references. The runner
resolves secret references inside the child process boundary; adapters, logs,
diagnostics, lock diffs, and receipts never receive the resolved value.

Selected `component_controls` are desired route state, while adapter capability
records say whether the harness can realize each control. The resolver rejects
a selected control without an exact supported capability before it returns an
executable plan. Adapters do not silently broaden a control to a whole plugin.

Adapters may mutate only the surface named by an automated action. They preserve
unrelated keys and native state, compare the current observation with the
expected observation immediately before mutation, and return observed evidence
rather than changing the provider selection.

### Initial capability table

| Surface | Observation | Automated mutation | Required ownership note |
| --- | --- | --- | --- |
| Standalone `~/.agents/skills` entry | File type, metadata, symlink text/target, or directory tree digest | Pinned install/repair only after catalog adoption | Canonical entries are shared; never follow an existing symlink for a write |
| Claude skill projection | Directory entry and symlink text/target | Create/remove exact catalog-owned link | Replace the blanket projector before selective removal |
| Claude plugin | Native plugin list/details | Install, enable, disable, uninstall through native CLI | Native rolling unless exact artifact restore is proven |
| Claude direct MCP | Narrow `.claude.json` overlay | Configure/remove owned server fields | Preserve unrelated runtime fields |
| Codex plugin and plugin MCP controls | Native plugin list plus supported config | Supported plugin and component controls | Exact plugin restore remains capability-dependent |
| Codex standalone skill suppression | `skills.config` path entries | Add/remove exact catalog-owned disable entry | Never disable by inferred name |
| Codex direct MCP | Narrow TOML overlay | Configure/remove owned server fields | Preserve unrelated keys and plugin-provided effective servers |
| Cursor direct MCP | Stable `~/.cursor/mcp.json` input | Configure/remove owned server fields | Preserve unrelated servers and secret references |
| Cursor plugin | Supported UI/CLI observation when available | Operator action until a stable install contract exists | Opaque application databases are never edited |

## Apply and recovery interface

The executor should expose one deep interface:

```text
execute(validated_plan, adapters, checkpoint_store) -> apply_report
```

The executor refuses an unvalidated or digest-mismatched plan. It does not
promise global atomicity. For every action it:

1. Audits and captures the exact pre-state.
2. Derives the expected post-state and compensation from adapter capabilities.
3. Atomically persists and fsyncs a `prepared` checkpoint before mutation.
4. Compares current state with the captured pre-state.
5. Executes the action.
6. Verifies the expected post-state.
7. Atomically persists and fsyncs `completed`.

On a later failure, completed actions compensate in reverse order. Before each
restore, current state must equal the post-state written by that action. The
executor persists `compensating` before restore and `compensated` afterward. A
mismatch preserves the external change and stops.

A surviving `prepared` checkpoint is audited before retry:

- observed pre-state: the mutation did not take effect and may be retried;
- observed expected post-state: record completion without replay;
- any other state: preserve it, report concurrent or partial drift, and stop.

A completion-checkpoint write failure therefore cannot cause duplicate replay.
A compensation failure remains durable and requires the same audit before a
retry. Checkpoint identities bind the canonical catalog digest, lock digest,
plan digest, route, operation, pre-state, expected post-state, and adapter
capability digest.

## Generated outputs

Generated overlays are proposals until apply. They contain owned fields only,
with provenance back to the route and catalog digest. Diagnostics and diffs
redact values by construction because the resolver accepts secret references,
not secret values.

The acceptance matrix in `ACCEPTANCE.md` is the release gate for production
implementation. The sequenced work and exact retained/retired source map are in
`IMPLEMENTATION_HANDOFF.md`.

The checked-in `initial-catalog.proposed.json` and
`initial-lock.proposed.json` exercise this serialized contract with 44 accepted
identities, 132 complete coverage records, nine resolved distributions, and 23
owned losing surfaces. Their `.proposed.json` suffix is normative: neither
artifact is installed under the production source path or consumed by chezmoi
apply.

## Schema evolution

Catalog, lock, captured-state, and evidence formats use independent explicit
major versions. Adding an optional field with unchanged meaning may remain in
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
