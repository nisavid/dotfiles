# Matt Pocock skills: current distribution contract

Verified on 2026-08-12 against upstream `main` commit
[`84fdeffd12f2ee307994d1eb6feb48173b6e0502`](https://github.com/mattpocock/skills/commit/84fdeffd12f2ee307994d1eb6feb48173b6e0502),
the upstream `v1.2.3` release, Claude Code 2.1.228, and `skills` 1.5.22.
Treat these facts as a dated fixture input, not an undated catalog constant.

## Current upstream distributions

One upstream repository supplies two formats of the same promoted skill set.
Claude currently exposes that plugin format through two marketplaces:

| Distribution | Native identity | Current entry point | Current contents |
| --- | --- | --- | --- |
| Claude official plugin | `mattpocock-skills@claude-plugins-official` | `claude plugin install mattpocock-skills` | Official marketplace entry pinned to upstream commit `84fdeffd…`; one plugin whose manifest exports 25 skills |
| Claude publisher plugin | `mattpocock-skills@mattpocock` | Add marketplace `mattpocock/skills`, then install `mattpocock-skills@mattpocock` | Same plugin through Matt's own rolling marketplace |
| Standalone Agent Skills | source `mattpocock/skills` | `skills add mattpocock/skills`, selecting individual skills and target harnesses | Independently selectable copies under the Agent Skills-standard harness directories |

The requested unqualified install resolves through Claude's built-in official
marketplace. At official marketplace commit
[`e5be1026bd77be5719f4fdf07c9583c9080f2de8`](https://github.com/anthropics/claude-plugins-official/commit/e5be1026bd77be5719f4fdf07c9583c9080f2de8),
its [Matt entry](https://github.com/anthropics/claude-plugins-official/blob/e5be1026bd77be5719f4fdf07c9583c9080f2de8/.claude-plugin/marketplace.json)
uses a Git URL source with exact SHA
`84fdeffd12f2ee307994d1eb6feb48173b6e0502`. The publisher's separate
[marketplace manifest](https://github.com/mattpocock/skills/blob/84fdeffd12f2ee307994d1eb6feb48173b6e0502/.claude-plugin/marketplace.json)
contains one plugin named `mattpocock-skills`; its marketplace is named
`mattpocock`. The [plugin manifest](https://github.com/mattpocock/skills/blob/84fdeffd12f2ee307994d1eb6feb48173b6e0502/.claude-plugin/plugin.json)
declares version `1.2.3` and these 25 skills:

```text
ask-matt                       diagnosing-bugs
grill-with-docs                triage
improve-codebase-architecture  setup-matt-pocock-skills
tdd                            to-spec
to-tickets                     wayfinder
implement                      prototype
research                       domain-modeling
codebase-design                code-review
resolving-merge-conflicts      wizard
grill-me                       grilling
handoff                        teach
to-questionnaire               wait-what
writing-for-agents
```

The plugin has no plugin-level agents, hooks, MCP servers, LSP servers,
commands, monitors, or executables at this commit. Its equipment inventory is
therefore exactly those 25 skills. Some skill directories contain supporting
files, including `agents/openai.yaml`; those files are skill-package metadata,
not Claude plugin-level agent components. Claude's
[component rules](https://code.claude.com/docs/en/plugins-reference#plugin-components-reference)
distinguish manifest-selected skill directories from plugin-root component
locations.

The upstream [README](https://github.com/mattpocock/skills/blob/84fdeffd12f2ee307994d1eb6feb48173b6e0502/README.md)
describes the distributions as two different ownership models: `skills`
installs selectable, editable standalone copies, while the Claude plugin is a
managed namespaced bundle. The repository's
[distribution ADR](https://github.com/mattpocock/skills/blob/84fdeffd12f2ee307994d1eb6feb48173b6e0502/.agents/adr/0002-ship-as-a-claude-code-plugin.md)
also records that a native Codex plugin was deliberately deferred; the
standalone route remains the current Codex and cross-harness distribution.

## Version, update, and restore semantics

### Claude plugin route

Claude resolves a plugin version from the plugin manifest before the
marketplace entry or source commit. Its
[version-management contract](https://code.claude.com/docs/en/plugins-reference#version-management)
therefore makes Matt's explicit `1.2.3` the cache and update identity. New
upstream commits are invisible to installed users until Matt bumps that field.
The annotated `v1.2.3` tag dereferences to commit
[`6acc160e4e0cd062dbbbd7a1b26ae92855edf07e`](https://github.com/mattpocock/skills/commit/6acc160e4e0cd062dbbbd7a1b26ae92855edf07e);
the 25 exported skill trees and plugin manifest are byte-identical between that
commit and the verified `main` commit.

`claude plugin install` accepts a plugin identity and scope, not a version.
Selection belongs to the marketplace source: Claude documents
[branch or tag pins on marketplace add](https://code.claude.com/docs/en/plugin-marketplaces#plugin-marketplace-add)
and commit-SHA pins for marketplace plugin sources in its 2.1.14
[changelog](https://code.claude.com/docs/en/changelog). Consequently:

- the current official entry fetches an exact source commit, but the built-in
  official marketplace is an auto-updating channel controlled by its publisher;
  the install command cannot select an earlier entry or commit;
- the publisher marketplace is a managed release channel, not an exact-version
  install command;
- a catalog-owned pinned marketplace source can provide an immutable route only
  after an exact commit, fetched artifact, and content digest are verified;
- a tag or the manifest's semantic version alone is not an immutable digest;
- reinstalling from the ordinary upstream marketplace is native rolling and
  must not be reported as exact restoration.

The official marketplace automatically updates by default; Matt's third-party
marketplace does not. Claude can toggle auto-update per marketplace, and
`DISABLE_AUTOUPDATER` disables all Claude and plugin automatic updates; see the
official
[auto-update behavior](https://code.claude.com/docs/en/discover-plugins#configure-auto-updates).
For the requested official route, suppression is marketplace-wide, not
Matt-specific.
The installed CLI exposes whole-plugin enable and disable operations. It does
not expose per-skill enablement for this single 25-skill plugin, and Claude's
[`skillOverrides` contract](https://code.claude.com/docs/en/slash-commands#override-skill-visibility-from-settings)
explicitly excludes plugin skills. The 25 skills are therefore one inseparable
activation group on the native Matt plugin route.

Catalog classification:

- use `immutable` only for a catalog-owned source pinned and verified by commit
  plus content digest;
- use `native_rolling` for the official or publisher channel, record the
  reviewed marketplace commit, selected source commit, and observed plugin
  version, and make restore of a prior version an `operator_action` or
  `unavailable` disposition;
- record marketplace auto-update as a route-level control. Do not infer it from
  whether the plugin is enabled: disabled plugins remain installed artifacts.

### Standalone `skills` route

`skills` 1.5.22 supports selecting skill names and target harnesses. Its
[source parser](https://github.com/vercel-labs/skills/blob/a4d243c3d4f86cdf9385dd1b6a0733f6937e70b5/src/source-parser.ts)
records an optional branch or tag `ref`; its global lock records the source URL,
ref, skill path, and per-folder Git tree hash. The
[global updater](https://github.com/vercel-labs/skills/blob/a4d243c3d4f86cdf9385dd1b6a0733f6937e70b5/src/update.ts)
compares that tree hash and reinstalls changed skills from the recorded ref.
Updates happen only when the operator runs the CLI; there is no background
standalone updater to suppress.

The folder hash is drift and update provenance, not an install selector. A
ref-less entry follows the source's current default branch. Although the parser
accepts any text as a ref, the Git path supplies it to `git clone --branch`.
A read-only `--list` probe against upstream commit `84fdeffd…` failed with
`Remote branch ... not found`; an exact commit SHA is therefore not a working
native install selector in 1.5.22. A tag ref can hold a release channel, but
exact standalone restoration requires the controller to retain or fetch a
verified artifact by immutable commit and validate its digest; the native lock
alone does not promise that outcome.

`skills experimental_install` is not a global-lock restore path. Its
[implementation](https://github.com/vercel-labs/skills/blob/a4d243c3d4f86cdf9385dd1b6a0733f6937e70b5/src/install.ts)
reads a project `skills-lock.json` and restores into project
`.agents/skills/`. It does not consume the global XDG-state `.skill-lock.json`
or recreate the global harness projection set. The prototype must therefore
classify global restore as controller-owned reconciliation, not delegate it to
`experimental_install`.

## Current-machine reconciliation

The statement that this machine exposes only `ask-matt` and
`setup-matt-pocock-skills` is an inventory-query error, not an upstream
distribution change. Those are merely the two installed names containing
`matt` or `pocock`.

Read-only verification found:

- the global `skills` v3 lock attributes all 25 names above to
  `mattpocock/skills`, with `pluginName: mattpocock-skills`;
- all 25 canonical directories exist in the global Agent Skills directory;
- every installed directory is byte-identical to its path at upstream commit
  `84fdeffd12f2ee307994d1eb6feb48173b6e0502`, and every recorded folder tree
  hash matches that commit;
- 21 are currently symlinked into Claude; `to-questionnaire`, `wait-what`,
  `wizard`, and `writing-for-agents` are not;
- no `mattpocock-skills` Claude plugin or publisher `mattpocock` marketplace is
  currently installed; the built-in official marketplace is available.

The global lock is authoritative evidence about installer provenance, but not
desired-state authority. The directories and projections are runtime
observations until the new catalog explicitly imports or adopts them.

## Catalog and prototype implications

Use one equipment identity per logical skill. The initial proposal selects two
provider distributions:

- `standalone:mattpocock/skills`, with individually selectable skill routes;
- `claude-plugin:mattpocock-skills@claude-plugins-official`, the requested
  preferred Claude route, with one 25-skill activation group and a
  component-to-equipment mapping for every exported skill.

The publisher route `claude-plugin:mattpocock-skills@mattpocock` is a known
alternative distribution of the same activation group, but it is deferred
from the initial catalog because the official route is selected and no current
exception requires both. Add it only with an explicit provider-choice or
overlap decision.

For Claude, select the plugin route as preferred for all 25 identities and
retire only the corresponding catalog-owned standalone projections. Keep the
canonical Agent Skills directories for Codex, Cursor, and other harnesses.
Provider selection must not treat `pluginName` in the standalone lock as proof
that the Claude plugin is installed.

Fixture the following independently:

1. Upstream plugin manifest: 25 selected skill paths at commit
   `84fdeffd12f2ee307994d1eb6feb48173b6e0502`, plugin version `1.2.3`.
2. Standalone provenance: 25 lock entries with source, path, and folder hash;
   no `ref` means default-branch update semantics.
3. Current projections: 25 Agent Skills directories, 21 Claude symlinks, four
   absent Claude projections, no installed Matt plugin, and an available
   official marketplace route.
4. Conflict resolution: installing the plugin makes its 25 Claude components
   preferred as one activation group; the resolver proposes removing only the
   21 positively identified symlinks after the catalog-driven projector is in
   place.
5. Restore classes: official/publisher plugin channels are `native_rolling`.
   Ref-less or tag-only standalone observations also have rolling semantics,
   but v1 does not admit them as selected standalone routes; retain them as
   import evidence until `update` resolves a separately verified commit and
   content digest, which the controller can model as `immutable`.
6. Operation dispositions: Claude plugin install, enable, disable, update, and
   uninstall are whole-plugin operations; selective skill suppression is
   `unavailable`; global standalone restore is controller reconciliation rather
   than `experimental_install`.

Before migration, refresh the upstream manifest and live inventory. A changed
skill list, plugin version, marketplace source, symlink set, or folder hash is
manager-driven drift and requires a new plan rather than automatic adoption.
