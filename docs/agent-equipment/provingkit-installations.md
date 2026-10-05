# Recreate selected Provingkit installations

`provingkit-installations` recreates selected plugins from pinned, clean
Provingkit artifacts through chezmoi. Use this procedure when preparing a new
machine, changing selected plugin bytes, repairing a missing installation, or
moving an ad hoc selection to a later preview or release.

The producer establishes artifact materialization and observed native
configuration. Interactive discovery, skill behavior, preview qualification,
publication, live activation, and source retirement have separate acceptance
steps. The generic protected `agent-equipment apply` route remains unavailable.

## Source and selection

| Source | Responsibility |
| --- | --- |
| `home/.chezmoidata/provingkit.json` | The only authored profile selection and pins. |
| `home/.chezmoitemplates/provingkit-selection.tmpl` | Resolve `selection.default` and an optional `selection.byHostname` override. |
| `home/.chezmoiexternals/provingkit.toml.tmpl` | Derive checksum-pinned archive, receipt, and mode-manifest downloads. |
| `home/dot_config/provingkit/selection-v1.json.tmpl` | Project the resolved profile into `~/.config/provingkit/selection-v1.json`. |
| `home/private_dot_local/bin/executable_provingkit-installations` | Validate, observe, and reconcile the selected installation. |
| `home/run_after_sync-provingkit-installations.sh.tmpl` | Reconcile after every apply, including an unchanged declaration with a missing cache. |

The default is inactive and contains no artifact pins. Add a reviewed profile
before selecting it. A default profile applies to another matching Linux
machine without requiring its hostname in the source. A hostname override can
select another complete profile or the empty string to opt out. A platform
mismatch produces `unsupported_platform` and no artifact downloads or client
operations. The command also checks the actual operating system and architecture.

A profile uses `provingkit-installation-selection-v1` and these fields:

| Field | Meaning |
| --- | --- |
| `platform` | `os` and chezmoi `arch`, such as `linux` and `amd64`. |
| `adoption` | `stage` (`ad_hoc`, `preview`, or `release`), a named `identity`, and a public `record` URL identifying the reviewed selection. These are selection metadata. |
| `source` | Repository `https://github.com/nisavid/provingkit` and its full immutable `commit`. |
| `artifact_slate` | Ordered complete catalog membership emitted by the projector. This is distinct from the installation selection. |
| `artifacts` | Each selected target's archive URL, archive SHA-256 and root name, artifact tree SHA-256, separate receipt URL/SHA-256, mode-manifest URL/SHA-256, and catalog path. |
| `clients` | Per-client artifact target, route, scope, optional `marketplace`, and a map of selected member names to `{ "enabled": true }` or `{ "enabled": false }`. Only these members are reconciled. |
| `retirements` | Empty. Retirement is an operator-owned step; this command has no retirement actuator. |

Targets and controls are fixed:

| Client | Artifact target | Route | Scope |
| --- | --- | --- | --- |
| Codex | `agent-plugins` | `native_marketplace` | `implicit_user` |
| Claude | `claude` | `native_marketplace` | `user` |
| Cursor | `cursor` | `user_local_directory` | `user` |

The marketplace defaults to `provingkit`. Codex also supports the explicit
`provingkit-local` identity when an installation must remain distinct from a
repository's `provingkit` catalog. Other names are unavailable. Claude retains
`provingkit`; Cursor uses its local directory route.
Changing an identity already recorded by this producer requires a separately
reviewed migration. The command checks this before processing any client;
it does not install duplicate aliases or rename the existing marketplace.

Use a complete clean catalog from one source snapshot when an existing shared
marketplace contains additional installed members. For example, the artifact
slate can contain all six plugins while each client's selected member map
contains only Proseweaving, Versionkeeping, and Mergecraft. Catalog availability
does not authorize installing or updating the other members. Do not combine
members from different snapshots into a newly authored marketplace.

## Prepare and apply a profile

1. Consume Provingkit's [clean artifact projection procedure](https://github.com/nisavid/provingkit/blob/147e1ddfc969b5119001488ce1556627d3b2449b/docs/release-artifact-projection.md)
   and its [install/source-transition procedure](https://github.com/nisavid/provingkit/blob/147e1ddfc969b5119001488ce1556627d3b2449b/docs/preview/install-and-update.md).
   Obtain retrievable artifacts, exact receipt bytes, and the mode inventory for
   the chosen source commit. The installer never builds from a working checkout
   or resolves a moving branch. Publishing those inputs is a separate step.
2. Record the reviewed URLs and digests in one profile. Production selections
   require durable HTTPS URLs. The command and acquisition template reject
   local URLs unless `PROVINGKIT_TEST_LOCAL_ARTIFACTS=1` explicitly enables
   disposable synthetic fixtures; never enable that mode for a host deployment.
   Keep the complete artifact slate separate from each client's selected members.
   The archive root name records the producer's single root; chezmoi strips one
   component and the reconciler verifies the extracted tree.
3. Select the profile through the default or a hostname override. Review the
   projected JSON and chezmoi diff, then apply within the intended host scope.
4. Read the command result and run `provingkit-installations status`. Verify
   native scope, enablement, effective payload, and cache separately. Complete the
   client-specific discovery checks before calling the client adopted.

```sh
chezmoi diff
chezmoi apply
provingkit-installations validate
provingkit-installations status
```

`--selection PATH` supplies a projected selection explicitly. All commands emit
JSON; `--json` makes that choice explicit. `validate` checks the declaration,
`status` reads current artifacts and client state, and `reconcile` performs the
supported operations and observes the result again.

## Artifact and installation observations

Chezmoi retains immutable inputs below
`~/.local/share/provingkit/artifacts/<target>/<artifact_sha256>/` and
`~/.local/share/provingkit/evidence/<target>/<artifact_sha256>/`. Archive,
receipt, and mode-manifest downloads each have a SHA-256 pin. A new artifact
gets a new identity and URL; native version strings do not select its bytes.

The reconciler follows `provingkit-artifact-receipt-v1`: exact receipt field set,
builder/source commit, repository, target, ordered slate, file inventory, and
`provingkit-tree-v1` framing. It checks the extracted receipt against its separate
pinned copy. It verifies file modes against the separate mode manifest because
the artifact tree digest covers paths and bytes, not modes. Links and special
files are outside this clean artifact format.

For Codex's `provingkit-local` selection, verify the ordinary artifact first,
then derive a fixed installation view. Change only the catalog name and replace
the view's root receipt with `provingkit-local-marketplace-projection-v1`, binding
the exact ordinary receipt digest, source commit, complete slate, and name
change. Preserve every plugin file and mode. The acquired canonical artifact
stays unchanged; the derived receipt is never accepted as an ordinary artifact
receipt. This route requires the projector's compact catalog encoding.

The stable native marketplace roots are
`~/.local/share/provingkit/marketplaces/<target>/`. They contain complete copies
of verified clean artifacts. Replacement requires either matching desired
content or matching the previous observed projection. Previous directories are
retained below `~/.local/state/provingkit/backups/`; unrecognized modifications
stop replacement. Immutable input directories and prior external sources are
retained for recovery.
Codex's alias uses `agent-plugins-local` as its owned directory name.

`~/.local/state/provingkit/installations.json` records the selected source and
artifacts, observed directories, native additions, client results, and source
transitions with the prior source, the captured unselected state, and its expected
post-state. It is an observation receipt, not another desired-state declaration.
`status` reads current bytes and native state; it never substitutes the stored
receipt for a fresh observation.

Native observations distinguish the effective plugin payload from its cache:

| Field | Meaning |
| --- | --- |
| `path` and `cache_content` | Native cache location and its comparison with the selected clean artifact. Recovery copies use this location. |
| `load_path` and `content` | Effective load location and its payload comparison with the selected clean artifact. |
| `native_files` | Previously verified cache file and mode inventory, retained in the observation receipt. |
| `native_loaded_files` | Previously verified effective payload file and mode inventory, retained separately in the observation receipt. |

Both content comparisons must be `match`, with the requested source binding,
registration, and enablement, for native reconciliation to converge. These are
file and configuration observations; `runtime_acceptance` remains `not_observed`.

## Native reconciliation

Codex and Claude use supported native commands. The reconciler does not write
native plugin caches or application settings directly. It honors `CODEX_HOME`
and `CLAUDE_CONFIG_DIR` when supplied. Keep native configuration changes serial
with reconciliation and inspect an interrupted run before changing its selection.

Claude's [plugin loading documentation](https://code.claude.com/docs/en/plugins/loading)
describes relative plugin sources in a local directory marketplace as loading
in place. When a native registration reports `readFromFolder`, the reconciler
requires an existing, real member directory at the registered directory
marketplace's `plugins/<member>` path. A malformed, missing, or differently bound
load folder makes observation unavailable; a matching cache cannot substitute
for that folder. Registrations without `readFromFolder` retain the supported
cache-loading path.

Before replacing the stable marketplace copy, check each selected cache or
effective payload that differs from the desired artifact against its separate
previously verified file and mode inventory. An unexplained change stops
reconciliation before projection or native commands. After projection, refresh
Claude's directory marketplace and reinstall a changed cache through native
commands. Before removal, retain and verify a complete recovery copy under
`~/.local/state/provingkit/backups/`, including native-generated files. Record
the copy and its original path in `native_backups` in the observation receipt;
Claude removal always uses `--scope user --keep-data`. A missing cache is
installed again; a missing declared in-place source remains unavailable.
Unchanged caches receive no install action. Claude's declared enabled state is
restored with its scoped native enable/disable commands.
Codex's persistent disable control is unavailable through the measured CLI.

For first adoption, declare an artifact that matches the installed content and
reconcile that baseline before selecting newer bytes. A missing inventory or
unexplained local edit stops replacement before native changes. Keep the
installed files intact and resolve their identity with the adoption owner;
do not edit the observation receipt to make an unknown installation appear
recognized. Cache replacement requires a matching `native_files` inventory.
When a member has no `native_loaded_files` record, its legacy `native_files`
inventory can establish the effective payload baseline. A present effective
inventory must be a dictionary; null or a non-dictionary inventory makes the
receipt unavailable and cannot fall back to legacy evidence.

An existing Codex `provingkit-local` source can be adopted in place when its
complete files and modes match the verified installation view and every selected
installation already has the requested content, registration, and enabled state.
Record its actual source and complete file/mode baseline without rebinding the
marketplace or changing caches. This observation-only adoption also works with
unselected members.
Missing selected caches can subsequently be repaired from that same verified
source without rebinding it; unexplained cache edits still stop replacement.
Retain the original source directory unchanged. Every later run that selects
Codex checks its recorded baseline and registered source path before processing
any client. A changed or missing retained source, or registration to another
path (including the owned marketplace root), stops both status and reconciliation
until the discrepancy is resolved with its owner, even when the files match the
requested artifact. Selecting a new artifact while
the retained source remains unchanged follows the client's rebind rules below;
adoption does not make a commit-addressed directory mutable or establish a
selected-only Codex rebind.

An initial source rebind differs by client:

- Codex rejects a same-name source replacement. Removal is allowed only when
  every registered member affected by that marketplace belongs to the selection
  and its state is recognized. The reconciler removes those selected plugins,
  rebinds the source, and reinstalls them. An unselected member blocks this route.
- Claude supports `plugin marketplace add NEW_DIRECTORY --scope user` for a
  same-name rebind. The destination clean catalog must retain every installed
  unselected member. A three-entry catalog makes the other three installations
  report `plugin-not-found`, even though their cache bytes remain. For each
  unselected member loaded in place, verify before projection that its current
  effective payload files and modes equal the new clean artifact's member.
  Changed unselected content blocks the operation. During this declared rebind,
  the only permitted registration change is `readFromFolder` moving to the
  owned destination's `plugins/<member>` path. Preserve its cache, identity,
  scope, enablement, and every other registration field. Use the complete
  catalog and replace only the selected installations.

Before projection or native mutations, capture unselected registrations,
effective payloads, and cache bytes/modes, excluding Claude's validated volatile
process markers. Claude members loaded in place must match their destination
artifact's files and modes for steady-state changes as well as rebinds. For a
rebind, retain the raw capture in the source transition's `unselected` record and
its expected post-state in `expected_unselected`, changing only the permitted
load-folder path. Compare fresh observations with that complete expected state
and the unchanged unselected member set after each native mutation and at the
end, including when no unselected members were installed. Existing member errors,
ambiguous scopes, unknown cache layouts, or unrecognized files stop reconciliation.
An explicitly enabled Claude `autoUpdate` setting also blocks reconciliation when
unselected members are installed. Its observed setting is reported;
`unspecified` does not mean disabled. Interactive client updates and session
loading require their separate acceptance checks.

Native command success is insufficient. Claude can report a successful
same-version install while retaining old bytes. Codex's installed list reports a
cache version but omits its path: use the native install result when available,
otherwise a bounded version component within the observed cache layout. Both
`local` and versioned directories are supported. The native-generated Codex
`.codex-plugin/plugin.json` is recorded separately from artifact-defined files;
unknown extra files and drift in a previously observed adapter are rejected.

Claude's root `.in_use` directory contains volatile native process markers.
Accept only direct regular files named by a positive decimal PID, containing
at most 4096 bytes of JSON with a matching integer `pid` and optional decimal
string `procStart`. Duplicate keys, incomplete writes, unknown fields, nested
entries, and links make observation unavailable; preserve them for inspection.
Validated cache markers are reported separately from plugin payloads and
excluded from retained payload identity. Markers in effective load folders are
also validated and excluded from payload identity, but are not reported in
`native_additions`. Keep cache markers in complete recovery copies. Their
presence does not prove that a process is active or that a live update is safe.
This format is grounded in Claude Code 2.1.284's installed marker writer and
reader; tests construct marker fixtures and do not claim fresh session loading.

Compatibility is based on required command/JSON shapes and observed state, with
the native version included in the report. A different compatible patch version
does not automatically disable the route. A changed control, output schema, or
layout produces `unavailable` and requires a new mechanism probe. Native lifecycle
checks were verified in disposable Linux homes with Codex 0.160.0 and Claude Code
2.1.289, including effective-source observations and full-catalog rebinds. Recorded
mechanism fixtures retain earlier client versions. Constructed CLI fault tests
establish refusal behavior, not real-client outcomes or session loading.

## Cursor materialization and acceptance

The supported source route copies selected clean plugin subtrees into real
`~/.cursor/plugins/local/<member>` directories. It uses neither an external
symlink nor an account marketplace operation. Missing directories are recreated;
changed owned directories are replaced with their previous tree retained.
Unselected local directories are untouched. Persistent disable is unavailable
through this route, so a disabled declaration is rejected before copying.

[Cursor's local plugin documentation](https://cursor.com/docs/plugins#test-plugins-locally)
and inspected Agent `2026.09.10-fd3934a` and IDE `3.15.19` source establish the
directory discovery route. This work verifies its files and modes. It has not
observed fresh CLI, TUI, or IDE discovery, effective local-import policy,
enablement, or same-name marketplace precedence. Pro subscription status does
not establish those behaviors.

A successful copy reports `materialization: verified`, `enabled: unknown`, and
`runtime_acceptance: pending`. The after-apply hook succeeds for that bounded
materialization result. It does not claim runtime readiness. The adoption
consumer must check fresh CLI discovery, `/plugins` in the TUI, and Settings /
Customize after IDE reload independently, including same-name marketplace
precedence and the supported enablement control.

## Outcomes, updates, and retirement

| Exit | Result |
| --- | --- |
| `0` | Valid declaration, inactive/unsupported no-action, verified materialization, or converged supported native configuration. Read `outcome` and each client's runtime acceptance separately. |
| `1` | Extracted artifact, receipt, or mode verification failed. No client operation ran. |
| `2` | Incomplete or unavailable client state, or an unusable observation receipt. The hook fails for these conditions. |
| `64` | Invalid selection. |

A later ad hoc revision or preview changes the source, artifact pins, slate,
selected member map, and adoption record together. The same reconciliation seam
applies; it does not wait for full preview qualification to support ordinary
selected installations. Setting the profile inactive stops reconciliation and
leaves installations in place.

Retirement follows verified replacement and its separate operator decision.
Inventory the old installation, global skill source, Claude aliases, config
reintroduction points, and retained recovery inputs before removing anything.
This producer does not delete source skills, thin global instructions, prune
old artifacts/backups, or retire another provider. Record the retirement result
in the owning adoption record; keep `retirements` empty here.

For the native Skills-managed standalone `resolving-merge-conflicts` route,
use [the focused retirement procedure](retiring-resolving-merge-conflicts.md)
after accepting its Versionkeeping replacement in the affected clients.

## Verification and downstream use

Run the public fixtures and isolated chezmoi deployment checks:

```sh
python3 -m unittest tests.test_provingkit_installations tests.test_provingkit_deployment
zsh tests/platform-portability.zsh
```

Native tests are explicitly opt-in and use only disposable synthetic homes:

```sh
PROVINGKIT_TEST_CODEX="$reviewed_codex_executable" \
PROVINGKIT_TEST_CLAUDE="$reviewed_claude_executable" \
python3 -m unittest tests.test_provingkit_installations
```

The default test run skips native probes when those paths are absent. The
fixture [README](../../tests/fixtures/provingkit-installations/README.md) identifies
producer and native evidence, its normalization, and its limits. A stubbed
schema test is parser evidence; it is not a native lifecycle result.

The [adoption consumer](https://github.com/nisavid/provingkit/issues/112) must load
this procedure from the reviewed dotfiles revision before choosing real pins or
running a live apply. Record that revision, selected profile, observed client
versions/results, and remaining interactive checks in its acceptance record.
Publication, real artifact selection, initial live host scope, and retirement
remain with that consumer and its operator.
