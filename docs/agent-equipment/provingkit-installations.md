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
| `clients` | Per-client artifact target, route, scope, and a map of selected member names to `{ "enabled": true }` or `false`. Only these members are reconciled. |
| `retirements` | Empty. Retirement is an operator-owned step; this command has no retirement actuator. |

Targets and controls are fixed:

| Client | Artifact target | Route | Scope |
| --- | --- | --- | --- |
| Codex | `agent-plugins` | `native_marketplace` | `implicit_user` |
| Claude | `claude` | `native_marketplace` | `user` |
| Cursor | `cursor` | `user_local_directory` | `user` |

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
   use durable HTTPS URLs; the tests use public synthetic `file:` fixtures.
   Keep the complete artifact slate separate from each client's selected members.
   The archive root name records the producer's single root; chezmoi strips one
   component and the reconciler verifies the extracted tree.
3. Select the profile through the default or a hostname override. Review the
   projected JSON and chezmoi diff, then apply within the intended host scope.
4. Read the command result and run `provingkit-installations status`. Verify
   native scope, enablement, and installed bytes separately. Complete the
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

The stable native marketplace roots are
`~/.local/share/provingkit/marketplaces/<target>/`. They contain complete copies
of verified clean artifacts. Replacement requires either matching desired
content or matching the previous observed projection. Previous directories are
retained below `~/.local/state/provingkit/backups/`; unrecognized modifications
stop replacement. Immutable input directories and prior external sources are
retained for recovery.

`~/.local/state/provingkit/installations.json` records the selected source and
artifacts, observed directories, native additions, client results, and source
transitions with the prior source and unselected cache identities. It is an
observation receipt, not another desired-state declaration. `status` reads
current bytes and native state; it never substitutes the stored receipt for a
fresh observation.

## Native reconciliation

Codex and Claude use supported native commands. The reconciler does not write
native plugin caches or application settings directly. It honors `CODEX_HOME`
and `CLAUDE_CONFIG_DIR` when supplied. Keep native configuration changes serial
with reconciliation and inspect an interrupted run before changing its selection.

For steady-state changes, replace the owned stable marketplace copy, refresh
Claude's directory marketplace, and compare each selected installed subtree.
A changed, registered member is removed and reinstalled through native commands;
Claude removal always uses `--scope user --keep-data`. A missing cache is
installed again. Unchanged members receive no install action. Claude's declared
enabled state is restored with its scoped native enable/disable commands.
Codex's persistent disable control is unavailable through the measured CLI.

An initial source rebind differs by client:

- Codex rejects a same-name source replacement. Removal is allowed only when
  every registered member affected by that marketplace belongs to the selection
  and its state is recognized. The reconciler removes those selected plugins,
  rebinds the source, and reinstalls them. An unselected member blocks this route.
- Claude supports `plugin marketplace add NEW_DIRECTORY --scope user` for a
  same-name rebind. The destination clean catalog must retain every installed
  unselected member. A three-entry catalog makes the other three installations
  report `plugin-not-found`, even though their cache bytes remain. Use the
  complete catalog and replace only the selected installations.

Before native mutations, capture unselected registrations and cache bytes/modes.
Check them again after each native mutation and at the end. Existing member
errors, ambiguous scopes, unknown cache layouts, or unrecognized files stop
reconciliation. An explicitly enabled Claude `autoUpdate` setting also blocks
reconciliation when unselected members are installed. Its observed setting is reported;
`unspecified` does not mean disabled. No tested command changed unselected cache
bytes, but a later interactive client's update behavior still needs observation.

Native command success is insufficient. Claude can report a successful
same-version install while retaining old bytes. Codex's installed list reports a
cache version but omits its path: use the native install result when available,
otherwise a bounded version component within the observed cache layout. Both
`local` and versioned directories are supported. The native-generated Codex
`.codex-plugin/plugin.json` is recorded separately from artifact-defined files;
unknown extra files and drift in a previously observed adapter are rejected.

Compatibility is based on required command/JSON shapes and observed state, with
the native version included in the report. A different compatible patch version
does not automatically disable the route. A changed control, output schema, or
layout produces `unavailable` and requires a new mechanism probe. The native
mechanism evidence here used Codex 0.155.0 and Claude Code 2.1.273.

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
