# Global agent equipment acceptance contract

This is the release gate defined by Issue #60. It specifies the evidence the
production reconciler and the separately authorized runtime migration must
produce. Passing the design-schema tests or the disposable prototype alone does
not satisfy the production gate.

## Evidence record

Each release candidate writes a secret-free evidence bundle with:

- the candidate commit, catalog digest, lock digest, plan digest, adapter
  capability digests, harness and manager versions, and fixture version;
- one result for every requirement ID below: `pass`, `fail`, `blocked`, or
  `not_run`, plus an artifact reference and execution timestamp;
- before and after runtime observation digests for mutating fixtures;
- the ordered checkpoint and compensation trace for failure fixtures; and
- an explicit human sign-off for each live-only check.

Only `pass` closes a requirement. `blocked` and `not_run` are visible release
failures, not waivers. Artifacts contain secret-reference names but never
resolved values. The gate fails if a requirement is absent, duplicated, or
recorded against a different candidate or catalog-lock binding.

The fixture runner creates a disposable home and isolated XDG directories for
every automated scenario. It replaces native CLIs with stateful fakes unless a
scenario is explicitly marked live. A fixture may read only its own sandbox;
it must prove no path outside that sandbox changed.

## Catalog, coverage, and planning fixtures

| ID | Required fixture and assertion | Evidence |
| --- | --- | --- |
| `CAT-01` | Accept a catalog containing every equipment kind in the first slice (`skill`, `plugin`, and `mcp`) and one modeled deferred plugin component. | Automated schema and semantic-validator result |
| `CAT-02` | Accept each exact coverage outcome with its canonical shape: provider outcomes carry one complete provider selection; omission outcomes carry exact `no_provider`. | Automated parameterized validator result |
| `CAT-03` | Reject a bare outcome, a single-route shorthand, a provider outcome with `no_provider`, and an omission with a provider selection. | One negative fixture per malformed shape |
| `CAT-04` | Expand every selected identity across exactly `claude`, `codex`, and `cursor`; reject a missing, duplicate, or unknown harness record. | Expanded-matrix comparison |
| `CAT-05` | Apply whole-record template precedence deterministically and reject partial, null, recursive, or unresolved inheritance. | Golden expanded records and negative fixtures |
| `CAT-06` | Accept one preferred route and explicit supplementary routes only when one matching `allow_overlap` exception names the complete route set and rationale. Reject every unlisted or mismatched overlap. | Positive and negative overlap fixtures |
| `CAT-07` | Require every active route to have exactly one route control owner, provenance owner, restore class, activation group, native-update state, and disposition for every required operation. | Field-deletion and conflicting-field mutation fixtures |
| `CAT-08` | Accept `managed_provider` only when all routes are `reconciler_owned`; accept `manually_managed_provider` only when at least one route is `operator_owned`. | Positive and negative ownership fixtures |
| `CAT-09` | Reject every automated mutating disposition on an operator-owned route while allowing automated `inspect`. | Operation-by-operation matrix fixture |
| `CAT-10` | Reject an automated mutating operation without `restore_captured_pre_state` compensation or without matching adapter capability. Put the invalid entry last and prove the returned mutation plan is empty. | Full-plan fail-closed trace with zero checkpoints |
| `CAT-11` | Accept immutable restore only with an immutable selector, reproducible artifact reference, verified content digest, and `not_applicable` native-update state. Reject a tag, channel, or observed version as immutable evidence. | Digest verification and negative selector fixtures |
| `CAT-12` | Accept native-rolling restore only with channel, reviewed observed-version baseline, observation source, and update-control state; never describe it as exact restore. | Golden route and diagnostic assertions |
| `CAT-13` | Compute canonical catalog and lock digests independent of formatting and object-key order; reject a semantically stale catalog-lock pair before opening the checkpoint store. | Digest vectors and checkpoint-open spy |
| `CAT-14` | Reject literal secret material or secret-bearing fields. Accept only environment-variable names or opaque secret references. | Public canary scan and schema negatives |

## Resolution and command-boundary fixtures

| ID | Required fixture and assertion | Evidence |
| --- | --- | --- |
| `RES-01` | Resolve identical inputs repeatedly to byte-identical diagnostics, matrices, overlays, lock proposals, and plan order. | Repeated-run golden digests |
| `RES-02` | Apply stable selective component controls before forming activation groups. Prove individually controllable losing components disappear while an inseparable group remains atomic. | Component-control trace and activation-group golden |
| `RES-03` | Resolve Matt's 25 Claude skills to one official-plugin activation group while keeping standalone routes for Codex and Cursor; propose only positively identified Claude projection retirements. | Matt prototype fixture |
| `RES-04` | Resolve Context7, Firecrawl, GitHub, Greptile, and Chrome DevTools direct/plugin candidates without unexplained duplicates; preserve each explicit allowed overlap. | MCP prototype selections and conflict diagnostics |
| `RES-05` | Generate overlays and lock diffs containing owned fields and secret references only. | Golden files plus recursive secret-canary scan |
| `CMD-01` | `audit` reads runtime state and writes neither authored nor runtime state. | Filesystem and fake-manager before/after digest equality |
| `CMD-02` | `import` discovers unmanaged state and emits a proposal without claiming ownership or changing runtime state. | Proposal golden plus runtime digest equality |
| `CMD-03` | `adopt` requires an exact imported observation and changes only a reviewable authored proposal. Runtime state remains byte-identical until later apply. | Catalog diff plus runtime digest equality |
| `CMD-04` | `update` expands source-wide selection, advances immutable targets or reviewed rolling baselines, and emits a lock proposal without changing runtime state. | Lock diff plus runtime digest equality |
| `CMD-05` | `apply` rejects a stale or incomplete plan, then reconciles every accepted catalog entry in deterministic order when the complete plan is valid. | Rejection trace and complete ordered plan trace |
| `CMD-06` | Apply reports `operator_action` and `unavailable` operations with supported verification evidence but never automates them. | Adapter call spy and operator report |

## Convergence, drift, and retirement fixtures

| ID | Required fixture and assertion | Evidence |
| --- | --- | --- |
| `CON-01` | Converge an empty disposable home from catalog and lock, including canonical standalone skills, projections, plugins, component selections, and direct MCP overlays. | Fresh-home tree and native-state golden |
| `CON-02` | Reapply to the converged fixture with no mutations, checkpoint writes, manager installs, or authored diffs. | Zero-call spies and identical digests |
| `CON-03` | Repair each missing catalog-owned item independently without changing unrelated managed or unmanaged state. | Parameterized deletion-and-repair results |
| `CON-04` | Restore immutable content only after digest verification; reject corrupt or mismatched content before replacing runtime state. | Valid/corrupt artifact fixtures |
| `CON-05` | Switch a preferred provider route and retire only catalog-owned losing projections after the winner verifies. | Ordered switch trace and retained-unmanaged assertion |
| `CON-06` | Detect an unselected duplicate and fail closed; accept a supplementary route only through the exact overlap exception. | Duplicate and overlap fixtures |
| `CON-07` | Preserve unknown and imported-but-unadopted state. Retirement of unmanaged state is a report only and performs no delete. | Adapter delete spy remains zero |
| `CON-08` | Retire adopted catalog-owned state only through apply, preserving unrelated keys and runtime objects. | Narrow-diff assertion |
| `CON-09` | Detect manager-driven native-rolling version drift. Ordinary apply does not advance the baseline; reviewed update proposes it. | Drift diagnostic and lock proposal |
| `CON-10` | For a regular file, directory tree, symlink, and broken symlink under the standalone root, preserve type, bytes or tree digest, applicable metadata, link text, resolved target, and broken state. Never follow an existing symlink for a write. | Parameterized lstat/tree fixtures and outside-target canary |
| `CON-11` | Preserve unmanaged drift encountered between audit and apply; compare-before-mutate stops rather than overwriting it. | Concurrent-change injection for every adapter surface |

## Checkpoint, failure, and compensation fixtures

Run `CHK-02` through `CHK-09` once for every automated mutating adapter
operation. Run them again for every migration boundary named in `MIGRATION.md`.

| ID | Required fixture and assertion | Evidence |
| --- | --- | --- |
| `CHK-01` | Validate the complete plan before the first checkpoint; an invalid final action yields zero runtime and checkpoint mutation. | Last-action invalid fixture |
| `CHK-02` | Fail the atomic prepared-checkpoint write. No runtime mutation occurs and retry creates one valid prepared record. | Write-fault trace |
| `CHK-03` | Persist `prepared`, fail before the adapter mutation, then audit and retry once without destructive replay. | Recovery classification and call counts |
| `CHK-04` | Persist `prepared`, complete the mutation, and fail before completion persistence. Retry audits the expected post-state and records completion without replay. | Mutation receipt, state digest, and call counts |
| `CHK-05` | Fail the atomic completion-checkpoint write. Recovery neither duplicates the mutation nor loses the prepared record. | Journal and call-count trace |
| `CHK-06` | Inject a later action failure. Compensate every earlier completed mutation in reverse order from captured pre-state, with durable `compensating` and `compensated` phases. | Full ordered trace and restored digest |
| `CHK-07` | Change a completed surface externally before compensation. Compare-before-restore preserves the external value and stops. | Drift diagnostic and unchanged external digest |
| `CHK-08` | Fail compensation and preserve a durable recoverable record. Audit-before-retry classifies state and never issues duplicate or destructive replay. | Fault and retry trace |
| `CHK-09` | Inject a concurrent change immediately before every adapter mutation. Compare-before-mutate preserves it and stops before the native manager call. | Parameterized adapter call spies |
| `CHK-10` | Bind each checkpoint to candidate, catalog, lock, plan, capability, route, operation, pre-state, and expected-post-state digests; reject replay under any changed binding. | Field-mutation negatives |

## Migration and rollback fixtures

| ID | Required fixture and assertion | Evidence |
| --- | --- | --- |
| `MIG-01` | Replace the blanket Claude projector with catalog-driven projection before removing any selective link. | Ordered checkpoint trace |
| `MIG-02` | Remove each catalog-identified Matt Claude symlink one at a time without reading through or mutating its standalone target. Inject failure after every removal and restore exact link text and broken/resolved state. | Per-link fault matrix and target digest equality |
| `MIG-03` | Install the official Matt plugin only when absent, then enable it. Inject failure after install and after enable; restore prior installation and enablement, uninstalling only if initially absent. | Fake-Claude state transitions |
| `MIG-04` | Reconcile each MCP and plugin/component selection after provider verification. Inject failure after every owned overlay or selection change and restore captured values only when compare-before-restore matches. | Per-surface fault matrix |
| `MIG-05` | Verify desired equipment coverage and absence of unapproved duplicates before retaining changes. A verification failure compensates every earlier mutation. | Coverage report and reverse compensation trace |
| `MIG-06` | Inject an external change before every untouched migration surface and before every restore. Preserve it, stop, and require a new plan. | Concurrent-change matrix |
| `MIG-07` | Prove a successful migration retains desired provider selections and removes only owned losing projections; prove rollback restores every captured projector, link, plugin, enablement, MCP, and selection field. | Complete before/after/rollback snapshots |

## Live checks

These checks use disposable or operator-approved accounts and directories. They
are never inferred from populated caches and are rerun immediately before
authorizing runtime migration.

| ID | Check | Required observation |
| --- | --- | --- |
| `LIVE-01` | Fresh Claude user-scope install of `mattpocock-skills` from the official marketplace. | Native list reports one installed and enabled plugin exporting exactly the reviewed 25-skill activation group. |
| `LIVE-02` | Claude marketplace update controls and reinstall behavior. | Record whether background update can be suppressed for this route and confirm it remains `native_rolling` unless an exact fetched artifact and digest are proven. |
| `LIVE-03` | Fresh Codex plugin and plugin-MCP installation plus component controls. | Record supported install, enable, MCP enablement/tool-policy, version, and restore operations without assuming cache restoration. |
| `LIVE-04` | Cursor user plugin and skill discovery behavior. | Record the supported user installation surface, whether realpath-identical Claude and Agent Skills entries deduplicate, and whether any stable per-path exclusion exists. Opaque database editing is forbidden. |
| `LIVE-05` | Direct MCP startup for every selected harness route using secret references. | Server starts and authenticates while logs, diagnostics, diffs, and evidence contain no resolved secret values. |
| `LIVE-06` | Native manager drift. | Change or observe a rolling provider version and prove audit reports drift while update alone proposes the reviewed baseline advancement. |

## Current design-slice evidence

The repository's schema fixtures and design validator satisfy only the
`CAT-*` shape and cross-field assertions they explicitly exercise. The
disposable prototype supplies exploratory evidence for `RES-02` through
`RES-05`; it is not a production resolver and is not merged into the production
branch. The inventory is a read-only observation. No `CON-*`, `CHK-*`,
`MIG-*`, or `LIVE-*` result may be marked passed until the production candidate
and separately authorized migration exist.

The future production release command must fail unless the evidence bundle has
one passing result for every ID in this document and no extra unknown result.
