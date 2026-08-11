# Global agent equipment: primary-source findings

Research dates: 2026-08-08; refreshed 2026-08-11

This note separates public contracts from observations of the currently installed CLIs and this repository. It covers Claude Code, Codex, Cursor, chezmoi, the `skills` CLI, and Matt Pocock's skills. No real user or repository plugin, skill, or runtime configuration was installed, removed, or changed. The isolated disposable restore probe temporarily created `probe-skill` and rewrote its project `skills-lock.json`, then was removed.

## Executive findings

1. Matt Pocock's current Claude distribution is an official-marketplace plugin. The exact documented shell command is `claude plugins install mattpocock-skills`; no marketplace-add step is needed. The corresponding fully qualified plugin ID is `mattpocock-skills@claude-plugins-official`. [Matt Pocock's README](https://github.com/mattpocock/skills#1-get-the-skills) and the [official marketplace entry](https://raw.githubusercontent.com/anthropics/claude-plugins-official/main/.claude-plugin/marketplace.json) agree on this.
2. The official Claude marketplace currently pins Matt's repository at commit `84fdeffd12f2ee307994d1eb6feb48173b6e0502`; that commit's plugin manifest is version `1.2.3` and exports 25 skills. The plugin is therefore the official marketplace's accepted snapshot, not necessarily an unreviewed checkout of the tip of Matt's `main` branch. [Official marketplace entry](https://raw.githubusercontent.com/anthropics/claude-plugins-official/main/.claude-plugin/marketplace.json) and [pinned plugin manifest](https://raw.githubusercontent.com/mattpocock/skills/84fdeffd12f2ee307994d1eb6feb48173b6e0502/.claude-plugin/plugin.json).
3. Claude plugin skills are namespaced, so the plugin's `ask-matt` is invoked as `/mattpocock-skills:ask-matt`, while a user skill remains `/ask-matt`. This avoids an identifier collision but does not avoid duplicate capability or duplicate discovery. Claude's standalone `skillOverrides` do not affect plugin skills. [Claude plugin discovery](https://code.claude.com/docs/en/discover-plugins) and [Claude skills settings](https://code.claude.com/docs/en/skills).
4. Codex intentionally does not merge same-name standalone and plugin skills; both can appear. Its supported deduplication mechanism is a `[[skills.config]]` entry with `enabled = false`. A path selector is safer than a name selector because it can disable only the standalone `SKILL.md` while leaving the preferred plugin copy enabled. [Codex skills documentation](https://developers.openai.com/codex/skills/) and [Codex configuration schema](https://developers.openai.com/codex/config-schema.json).
5. Cursor automatically scans both `~/.agents/skills` and `~/.cursor/skills`, plus Claude and Codex compatibility roots. Its public documentation does not define same-name precedence or a path-specific skill-disable setting. `disable-model-invocation: true` only prevents automatic invocation; the skill remains manually invocable. Therefore the proposed rule "keep the standalone copy for Codex but disable it in Cursor when a Cursor plugin wins" is not currently supported by a documented file-backed Cursor contract. [Cursor skills](https://cursor.com/docs/skills) and [Cursor plugins](https://cursor.com/docs/plugins).
6. Cursor's documented user-scope plugin installation is UI-managed through Customize. The installed Cursor Agent CLI can manage marketplace registrations, but it has no non-interactive plugin-install subcommand. No primary source found a stable local manifest that chezmoi can restore to reproduce user-scope plugin installations. This remains a research result, not an invitation to manage Cursor's cache or database internals.
7. Chezmoi has the right low-level primitives—templated symlinks, modify overlays, externals, removals, and idempotent scripts—but none is a complete equipment package manager. A small checked-in equipment manifest plus harness-specific reconciliation is the least surprising shape. `.chezmoiexternal` is useful for referenced source trees, while `modify_` overlays preserve harness-owned runtime fields. `run_onchange_` reacts to rendered script-content changes, not to an upstream repository changing on its own. [Chezmoi externals](https://www.chezmoi.io/user-guide/include-files-from-elsewhere/), [source-state attributes](https://www.chezmoi.io/reference/source-state-attributes/), and [target types](https://www.chezmoi.io/reference/target-types/).

## Matt Pocock skills

### Official Claude install and update model

Matt's current README gives this Claude Code flow:

```sh
claude plugins install mattpocock-skills
```

It says the plugin is in Claude Code's official marketplace, so no marketplace registration is required, and updates arrive automatically. Claude Code accepts both `plugin` and `plugins` as the command group in the installed `2.1.226` CLI. [Matt Pocock's README](https://github.com/mattpocock/skills#1-get-the-skills).

Claude's official docs say the official marketplace is registered automatically and that official marketplaces have auto-update enabled by default. Marketplace and plugin updates happen in the background after session start; a running session keeps its already loaded version until `/reload-plugins` or the next launch. [Discover and install plugins](https://code.claude.com/docs/en/discover-plugins).

The official marketplace identifies the plugin as `mattpocock-skills`, sourced from Matt's Git repository at pinned SHA `84fdeffd12f2ee307994d1eb6feb48173b6e0502`. The manifest at that SHA declares version `1.2.3`. [Official marketplace](https://raw.githubusercontent.com/anthropics/claude-plugins-official/main/.claude-plugin/marketplace.json) and [plugin manifest at the pinned SHA](https://raw.githubusercontent.com/mattpocock/skills/84fdeffd12f2ee307994d1eb6feb48173b6e0502/.claude-plugin/plugin.json).

Claude copies marketplace plugins to its versioned local cache rather than loading them from the marketplace checkout. The documented cache root is `~/.claude/plugins/cache`. Combining that contract with the current marketplace ID, plugin name, and version implies an expected install directory of:

```text
~/.claude/plugins/cache/claude-plugins-official/mattpocock-skills/1.2.3
```

That exact leaf is an inference until installation; verify it afterward with `claude plugin list --json` rather than treating the cache path as desired state. Cache contents are implementation-managed and should not be chezmoi-owned. [Claude plugins reference](https://code.claude.com/docs/en/plugins-reference).

### Current official inventory

The `1.2.3` plugin manifest exports these 25 skills: [manifest](https://raw.githubusercontent.com/mattpocock/skills/84fdeffd12f2ee307994d1eb6feb48173b6e0502/.claude-plugin/plugin.json).

| Engineering | Productivity |
| --- | --- |
| `ask-matt` | `grill-me` |
| `diagnosing-bugs` | `grilling` |
| `grill-with-docs` | `handoff` |
| `triage` | `teach` |
| `improve-codebase-architecture` | `to-questionnaire` |
| `setup-matt-pocock-skills` | `wait-what` |
| `tdd` | `writing-for-agents` |
| `to-spec` |  |
| `to-tickets` |  |
| `wayfinder` |  |
| `implement` |  |
| `prototype` |  |
| `research` |  |
| `domain-modeling` |  |
| `codebase-design` |  |
| `code-review` |  |
| `resolving-merge-conflicts` |  |
| `wizard` |  |

The local `skills` lock also contains exactly these 25 entries from `mattpocock/skills`, including source URL, source-relative `SKILL.md` path, and per-skill tree hash. This is an observation of the current installation, not a separate authoritative inventory.

### Standalone install and update model

For Codex and other Agent Skills consumers, Matt documents:

```sh
npx skills@latest add mattpocock/skills
```

The installer lets the user select skills and target agents. Matt describes this mode as ordinary editable files that do not update behind the user's back; `npx skills update` refreshes installed skills. [Matt Pocock's README](https://github.com/mattpocock/skills#1-get-the-skills).

The `skills` project documents `-g` for user-level installation, agent selection with `--agent`, skill selection with `--skill`, and symlinks as its recommended multi-agent installation method. It documents `skills update -g` for global updates. [Vercel `skills` README](https://github.com/vercel-labs/skills/blob/main/README.md).

Installed `skills` CLI `1.5.22` observations:

- Its global lock is `~/.local/state/skills/.skill-lock.json`, schema version 3 in this environment.
- The lock records 87 skills and includes all 25 Matt entries.
- The CLI exposes `experimental_install` as "Restore skills from skills-lock.json". The `experimental_` name is a clear stability caveat: tracking this lock is useful for provenance and recovery experiments, but it is not yet a settled, stable declarative-install contract.
- The public update documentation describes updating installed skills. It does not promise that `update` discovers brand-new skills later added to a previously installed source. A "latest complete Matt inventory" reconciler should therefore compare the current upstream manifest or re-run an explicit all/selected-skills add, not assume `update` expands the set.

## Claude Code

### Scopes and declarative settings

Claude's user scope is `~/.claude/`; plugin user settings live in `~/.claude/settings.json`. User-scoped plugins apply across projects. [Claude settings](https://code.claude.com/docs/en/settings).

`enabledPlugins` is the supported settings map:

```json
{
  "enabledPlugins": {
    "mattpocock-skills@claude-plugins-official": true
  }
}
```

Keys are fully qualified `plugin@marketplace` IDs and values are booleans. A project setting can override a user setting; a local setting can override both. [Claude plugin settings](https://code.claude.com/docs/en/settings#plugin-settings).

This setting records desired enablement but should not be confused with a complete package restore. Claude's docs say external plugins still require installation and trust before they run. For this official plugin, a chezmoi `modify_` overlay can safely own the single `enabledPlugins` key while an idempotent installation reconciler checks `claude plugin list --json` and invokes the documented install command only when missing. [Claude plugin settings](https://code.claude.com/docs/en/settings#plugin-settings) and [plugin CLI reference](https://code.claude.com/docs/en/plugins-reference).

`extraKnownMarketplaces` is the declarative registry for additional marketplace sources, with optional `autoUpdate`. It is unnecessary for Matt because `claude-plugins-official` is built in. For non-official marketplaces it registers or prompts for a marketplace; each plugin still needs a separate `enabledPlugins` entry and, where required, installation consent. [Claude `extraKnownMarketplaces`](https://code.claude.com/docs/en/settings#extraknownmarketplaces).

### Skill collision and disable behavior

- Marketplace plugin skills are namespaced with the plugin name, for example `/mattpocock-skills:ask-matt`. [Plugin discovery](https://code.claude.com/docs/en/discover-plugins).
- Standalone skills are invoked by their unqualified name, for example `/ask-matt`. [Claude skills](https://code.claude.com/docs/en/skills).
- Same-name standalone skills at multiple standalone scopes override by scope, but plugin skills are namespaced to avoid that collision. [Claude feature layering](https://code.claude.com/docs/en/features-overview#understand-how-features-layer).
- `skillOverrides` supports `on`, `name-only`, `user-invocable-only`, and `off` for standalone skills. It explicitly does not affect plugin skills; plugin enablement is managed through `/plugin` or `enabledPlugins`. [Claude skills](https://code.claude.com/docs/en/skills#override-skill-visibility-from-settings).

For Matt, removing the 25 Claude symlinks is the clean deduplication action. Turning the standalone names `off` would hide every standalone source with that name and leave unnecessary filesystem entries; it is also less transparent than not projecting those skills into Claude in the first place.

## Codex

### Public contract

Codex standalone user skills live at `$HOME/.agents/skills`. Directory symlinks are supported. Plugin skills are another distribution mechanism. If multiple skills share a name, Codex does not merge them and may present both. [Codex skills](https://developers.openai.com/codex/skills/).

Codex supports per-skill disable entries:

```toml
[[skills.config]]
path = "/absolute/path/to/.agents/skills/example/SKILL.md"
enabled = false
```

The configuration schema allows either a `name` or `path` selector plus `enabled`. For deduplication, path is the important selector: a name selector risks disabling the preferred plugin copy too, whereas the standalone path identifies the losing source. [Codex skills](https://developers.openai.com/codex/skills/) and [configuration schema](https://developers.openai.com/codex/config-schema.json).

Codex plugin desired state is represented under the user-level plugin map:

```toml
[plugins."plugin@marketplace"]
enabled = true
```

Marketplace entries represent Git or local sources and may contain a ref and sparse paths. They also contain runtime fields such as the last revision and update time, so the whole config should not be replaced wholesale. [Codex configuration schema](https://developers.openai.com/codex/config-schema.json).

### Installed CLI observation

The installed CLI is `codex-cli 0.147.0`. Its read-only help exposes:

- `codex plugin add`, `list`, `marketplace`, and `remove`;
- marketplace `add` for local paths, `owner/repo[@ref]`, and Git URLs, with `--ref` and sparse paths; and
- marketplace `upgrade` to refresh configured Git snapshots.

This is evidence for the current executable, not a timeless public contract. The official plugin UI documentation describes install/uninstall and enable/disable interaction through `/plugins`; plugin capabilities apply to new sessions. [Codex plugins](https://developers.openai.com/codex/plugins/).

No primary source established that restoring plugin-map entries into an empty cache automatically rehydrates a plugin. A safe implementation should validate fresh-machine convergence before relying on config alone; an idempotent CLI `add` step may still be needed.

### Existing repository direction

`home/dot_codex/modify_private_config.toml.tmpl` already uses the correct overlay approach: it preserves Codex-owned fields and appends exact path-based disables. It currently hard-codes a retired-skill set and also searches versioned plugin cache paths. The general policy should replace that isolated name set with manifest data while retaining path-specific disables and runtime-field preservation.

## Cursor

### Skill discovery

Cursor automatically discovers skills from all of these documented roots: [Cursor skills](https://cursor.com/docs/skills).

| Root | Scope |
| --- | --- |
| `.agents/skills/` | Project |
| `.cursor/skills/` | Project |
| `~/.agents/skills/` | User |
| `~/.cursor/skills/` | User |

For compatibility it also loads project and user skills from `.claude/skills`, `.codex/skills`, `~/.claude/skills`, and `~/.codex/skills`. It recursively discovers nested `SKILL.md` files. [Cursor skills](https://cursor.com/docs/skills).

Two consequences matter for the proposed policy:

1. Cursor already sees canonical skills in `~/.agents/skills`; no separate `~/.cursor/skills` symlink is needed for parity.
2. Symlinking the same skills into `~/.claude/skills` makes them visible through two Cursor discovery roots. Cursor's public docs do not say whether it canonicalizes symlinks, deduplicates identical realpaths, or which same-name copy wins. The policy must not assume that Claude symlinks are free of Cursor-side duplication.

`disable-model-invocation: true` prevents the model from automatically applying a skill, but the user can still invoke it manually. It is not a full disable and requires modifying the skill itself, so it cannot express "hide the standalone source in Cursor, leave the same file enabled for Codex." [Cursor skills](https://cursor.com/docs/skills#disabling-automatic-invocation).

No documented Cursor configuration key provides Codex-like `path + enabled = false` behavior. This creates a real cross-harness constraint: when Codex needs a standalone skill under `~/.agents/skills` but Cursor has a preferred plugin copy of the same capability, Cursor will still discover the standalone copy.

### Plugin installation and management

Cursor plugins can bundle skills, rules, subagents, MCP servers, hooks, and commands. The documented installation flow is Customize → select a plugin → Install → choose project or user scope. Installed components are managed in Customize and work across IDE and CLI. [Cursor plugins](https://cursor.com/docs/plugins).

The installed Cursor Agent CLI is version `2026.07.23-e383d2b`. Its plugin CLI has only marketplace management:

```text
agent plugin marketplace add|list|remove|update
```

It does not expose plugin `install`, `list`, `enable`, or `disable` subcommands. Public docs do not document a stable file-backed user plugin manifest. User-scope plugin state appears to be product-managed, so chezmoi should track only documented file inputs and reconciliation helpers—not plugin cache or opaque application state—until Cursor publishes a declarative contract or CLI.

### Unresolved Cursor decisions

The literal desired behavior is impossible with the currently documented controls. Choose one policy deliberately:

- Prefer standalone `~/.agents/skills` copies in Cursor whenever another harness still needs them, and do not install overlapping Cursor plugin skills.
- Accept duplicate Cursor discovery when a Cursor plugin is materially preferable, then validate actual collision behavior with a controlled prototype.
- Move canonical standalone packages out of `~/.agents/skills` into a neutral source store and project only filtered symlinks into harness roots. This enables filtering but gives up the requested convention that individually installed global skills live canonically in `~/.agents/skills`.
- Defer Cursor plugin preference until Cursor exposes a documented per-path disable or discovery-root allowlist.

This choice should be grilled; it is not a fact that further web research can resolve today.

## Chezmoi primitives and their limits

### Symlinks and removals

Chezmoi represents a target symlink with a regular source file named `symlink_*`; that file's contents are the link target. A `.tmpl` suffix makes the target templated. This is the right primitive for a finite, explicitly selected projection. [Source-state attributes](https://www.chezmoi.io/reference/source-state-attributes/) and [target types](https://www.chezmoi.io/reference/target-types/).

`.chezmoiremove` and `remove_` targets declare removals. They are appropriate for retiring known legacy links, but a growing exclusion policy is easier to reason about in one equipment manifest than as a permanent accumulation of unrelated removal lines. [`.chezmoiremove`](https://www.chezmoi.io/reference/special-files/chezmoiremove/) and [target types](https://www.chezmoi.io/reference/target-types/).

### Externals

`.chezmoiexternal` can bring an archive or Git repository into target state by reference. Archives can be exact and refreshed periodically; `--refresh-externals` forces a refresh. `git-repo` externals clone/pull but delegate directory ownership to Git; their contents are not manifested in `chezmoi diff` or `dump` and appear unmanaged. [Include files from elsewhere](https://www.chezmoi.io/user-guide/include-files-from-elsewhere/) and [`.chezmoiexternal` reference](https://www.chezmoi.io/reference/special-files/chezmoiexternal-format/).

Implications:

- Do not use one `exact = true` external directly on all of `~/.agents/skills`; it would make one upstream archive authoritative over custom, private, and separately managed skills.
- A referenced source tree can live under a neutral vendor/source directory, with a separately managed projection manifest deciding which skill directories appear in each harness.
- A `git-repo` external is convenient for "follow this ref" but deliberately weak in chezmoi diff visibility. A pinned archive gives stronger reproducibility and file-level target state.
- Following a moving branch and requiring "latest" is operational convergence, not reproducibility. Record whether each source follows a channel/ref or pins an immutable revision.

### Scripts

Chezmoi runs ordinary `run_` scripts on every apply, `run_once_` scripts once per content, and `run_onchange_` scripts when their rendered content changes. [Target types](https://www.chezmoi.io/reference/target-types/).

Consequences:

- `run_onchange_` is ideal when the checked-in manifest or pinned version changes and that data is rendered into the script.
- A remote branch moving does not change the rendered script. `run_onchange_` alone cannot implement "always follow latest" unless a refreshed external or another input changes its content hash.
- An idempotent `run_after_` reconciler can inspect current CLI state every apply and repair missing projections or installations, but it should make no changes when desired state already holds and should never own opaque caches.
- `run_once_` is a poor repair primitive for equipment because deleting an installed plugin later does not change the script content or reset chezmoi's persistent success record.

### Modify overlays

`modify_` scripts receive the live target and emit an updated version, making them suitable for harness-owned config files that accumulate runtime state. [Chezmoi target types](https://www.chezmoi.io/reference/target-types/).

The repository already uses this pattern correctly for Claude and Codex. A unified policy should keep narrow overlays:

- Claude: own selected `enabledPlugins` booleans and any explicitly managed marketplace references; preserve usage, timestamps, credentials, and other runtime fields.
- Codex: own selected plugin enablement, marketplace source/ref fields, and exact standalone skill disables; preserve last-revision/update and unrelated config.
- Cursor: do not invent a local overlay until a supported file-backed contract exists.

## Repository observations

These are live local observations, not upstream contracts:

- `home/run_after_sync-global-agent-skills-to-claude.zsh` creates a Claude symlink for every immediate directory under `~/.agents/skills` if the Claude target is absent. It has no plugin-preference or exclusion manifest.
- That script will recreate manually removed Matt links on a later `chezmoi apply`. Removing the live links without changing the policy is not durable.
- `home/dot_claude/skills/` contains 28 explicit symlink sources, while the blanket synchronizer independently covers the larger live `~/.agents/skills` inventory. These are two ownership paths for the same projection.
- `home/.chezmoiremove` separately retires a small list of old Claude duplicates.
- `home/dot_codex/modify_private_config.toml.tmpl` contains another hard-coded list for retired skills.
- `home/dot_claude/modify_private_settings.json.tmpl` already uses a narrow `jq` overlay for selected plugin enablement.
- All 25 Matt skills remain present under `~/.agents/skills`. Twenty-one currently have `~/.claude/skills` symlinks; `to-questionnaire`, `wait-what`, `wizard`, and `writing-for-agents` arrived in the latest standalone refresh but have not yet been linked. The blanket sync would link those four on its next successful run.
- `claude plugin list` confirms the Matt plugin is not installed yet.

## A workable policy shape to grill

The source of truth should describe desired equipment, not caches or entire harness configs. A compact manifest could represent:

```toml
[[packages]]
id = "mattpocock-skills"
source = "mattpocock/skills"
channel = "claude-official"

[packages.harnesses.claude]
provider = "plugin"
plugin = "mattpocock-skills@claude-plugins-official"

[packages.harnesses.codex]
provider = "standalone"

[packages.harnesses.cursor]
provider = "standalone" # until path-specific exclusion exists
```

The reconciler can then derive:

- which referenced sources or `skills`-managed installs must exist;
- which standalone skills are projected into Claude;
- which exact standalone paths Codex disables because a plugin wins;
- which Claude and Codex plugins are enabled;
- which legacy links are removed; and
- which exceptions are documented at the package/harness edge instead of scattered through scripts.

Before a selective Claude projection removes any losing link, the migration must retire `home/run_after_sync-global-agent-skills-to-claude.zsh` or make it consume the authoritative catalog. Otherwise a later `chezmoi apply` recreates the removed links and leaves two owners for the same projection.

Recommended invariants:

1. Each active provider route for an equipment identity and harness has exactly one artifact and provenance owner: `skills`, a dedicated helper, a checked-in custom skill, a referenced external, or a harness plugin. One logical package may therefore use distinct Claude, Codex, and Cursor provider routes with separate restore evidence.
2. The coverage matrix stores one canonical harness coverage record for every equipment identity and harness: one outcome plus either a provider selection—one preferred route and any supplementary routes named by an explicit overlap exception, each with its complete active-route record—for `managed_provider` and `manually_managed_provider`, or exact `no_provider` for `intentional_omission` and `unsupported`. Every active route declares `reconciler_owned` or `operator_owned` runtime control. `managed_provider` requires only reconciler-owned routes; `manually_managed_provider` requires at least one operator-owned route. A separate operation matrix records `automated`, `operator_action`, or `unavailable` for every active provider route and operation without changing the coverage outcome. Operator-owned routes are verify-and-report-only: their mutating operations cannot be `automated`. Plugin installation is not assumed to activate an indivisible bundle: the resolver first applies every documented harness control that can selectively enable or disable a plugin component, then treats only the remaining inseparable activation groups as atomic. For example, Codex exposes per-plugin-MCP enablement and tool policy, while Claude plugin MCP servers start with the enabled plugin and plugin hooks cannot be individually disabled. [Codex configuration schema](https://developers.openai.com/codex/config-schema.json), [Claude MCP documentation](https://code.claude.com/docs/en/mcp), and [Claude hooks reference](https://code.claude.com/docs/en/hooks).
3. Generated projections are fully derivable from the manifest and never become a second authority.
4. Harness-owned caches, credentials, timestamps, and usage databases are never chezmoi-owned.
5. Fresh-machine install, steady-state no-op, missing-item repair, upstream update, plugin/standalone preference switch, and uninstall/retirement each have a testable convergence case.

## Decisions resolved after research

The accepted decisions are recorded in the [Wayfinder map](../../.scratch/global-agent-equipment/map.md), its [domain language](../../.scratch/global-agent-equipment/CONTEXT.md), and resolved GitHub Issues [#44–#54](https://github.com/nisavid/dotfiles/issues?q=is%3Aissue+label%3Aagent-equipment+is%3Aclosed). The authored catalog supports both source-wide and explicit component selection; a reviewed lock records exact inventory and each provider route's restore class. Ordinary apply restores pinned targets where a reproducible artifact reference exists, while native-rolling routes remain explicit and cannot claim deterministic version restore. A separate update operation produces reviewable lock changes for immutable targets and reviewed observed-version baseline changes for native-rolling routes. The global `skills` lock remains useful import evidence, but it is neither the desired-state authority nor a sufficient fresh-home restore mechanism. The coverage matrix preserves explicit `managed_provider`, `manually_managed_provider`, `intentional_omission`, and `unsupported` harness outcomes, while route control ownership constrains who may mutate runtime state and the operation matrix records operation dispositions separately.

## Remaining validation

1. **Claude projection and Cursor compatibility scan.** Determine whether Cursor deduplicates realpath-identical entries discovered through both `~/.agents/skills` and `~/.claude/skills`; the public docs do not specify this behavior.
2. **Plugin installation restore.** Validate fresh-home behavior for Claude and Codex rather than inferring it from populated caches: determine when the reconciler must call a native plugin-install command.
3. **Live inventory classification.** Import and classify the current skills, helpers, plugins, plugin components, and direct MCPs before claiming ownership or removing unmanaged state.
4. **Native rolling channels.** [Issue #57](https://github.com/nisavid/dotfiles/issues/57) must test whether representative providers can suppress background updates and restore exact artifacts. Where they cannot, require an explicit native-rolling restore class and `operator_action` or `unavailable` operation disposition plus manager-driven-drift reporting instead of claiming immutable convergence.

## Wayfinder status

The cross-session [Wayfinder map](../../.scratch/global-agent-equipment/map.md) now charts the policy, schema, adapters, migration, MCP coverage, and acceptance work. It is a planning artifact rather than runtime configuration. Its current implementation frontier is [Issue #55](https://github.com/nisavid/dotfiles/issues/55); the Matt migration follows the resolver, inventory, and test-design dependencies recorded in the map and Issues.

## `skills` global lock versus `experimental_install`

This follow-up tested the installed `skills` CLI `1.5.22` on 2026-08-11. Its bundled implementation matches the upstream first-party source described below.

### What the global lock contains

With `XDG_STATE_HOME=~/.local/state`, the installed CLI uses `~/.local/state/skills/.skill-lock.json`; without `XDG_STATE_HOME`, it falls back to `~/.agents/.skill-lock.json`. The global schema is version 3. Its top-level fields are `version`, a flat `skills` map keyed only by skill name, optional `dismissed` prompt state, and optional `lastSelectedAgents` UI state. Each skill entry can record `source`, `sourceType`, `sourceUrl`, `ref`, `skillPath`, `skillFolderHash`, installation/update timestamps, and optional plugin or well-known-source metadata. [Global lock source and schema](https://github.com/vercel-labs/skills/blob/main/src/skill-lock.ts).

The current global lock has 87 entries, all with `sourceType: "github"`, from 11 independently installed sources:

| Source | Skills |
| --- | ---: |
| `firecrawl/cli` | 10 |
| `firecrawl/firecrawl-workflows` | 16 |
| `firecrawl/skills` | 5 |
| `heredotnow/skill` | 1 |
| `heygen-com/hyperframes` | 8 |
| `mattpocock/skills` | 25 |
| `obra/superpowers` | 14 |
| `obra/the-elements-of-style` | 1 |
| `vectorize-io/hindsight` | 5 |
| `vercel-labs/skills` | 1 |
| `withgraphite/agent-skills` | 1 |

All 87 entries have source identity/URL, source-relative skill path, folder hash, and timestamps. Fifty-five also have `pluginName` (`mattpocock-skills`, `firecrawl`, `firecrawl-workflows`, or `core-skills`). The top level records `findSkillsPrompt` as dismissed and 13 last-selected agents. It does **not** record a per-skill set of harness projections or whether a particular harness copy was a symlink or copy.

Calling this a lock that “mixes unrelated packages” is descriptive, not by itself a defect: it is a whole-user-install inventory. That is appropriate if chezmoi intends to own the complete `skills`-managed global set. Its practical limitations are that independent packages cannot be restored separately from the file, entries share one skill-name namespace, and harness placement is absent.

### What `experimental_install` actually reads

`experimental_install` does not read the global lock. It reads only `skills-lock.json` in the current working directory. That is a separate version-1 project schema intended for version control, with timestamp-free entries and content hashes. [Project lock source and schema](https://github.com/vercel-labs/skills/blob/main/src/local-lock.ts).

For each non-`node_modules` source, the command calls the ordinary add path with the locked skill names, `yes: true`, and the CLI's complete set of “universal” agents. It deliberately omits the global option, so the canonical destination is `<cwd>/.agents/skills`. It never recreates agent-specific paths such as `.claude/skills` or `.cursor/skills`. [Restore implementation](https://github.com/vercel-labs/skills/blob/main/src/install.ts) and [agent path definitions](https://github.com/vercel-labs/skills/blob/main/src/agents.ts).

There are no documented or implemented restore-specific scope or agent flags. Arguments are ignored for ordinary local/remote entries. They are parsed only when a lock contains `node_modules` entries, and even then the restore implementation overrides the parsed agent selection with all universal agents. Consequently, `--global`, `--agent`, and `--copy` cannot turn this command into a global, harness-specific restore. The generic CLI help lists `experimental_install` under “Project” and exposes no options for it. [CLI dispatch and help](https://github.com/vercel-labs/skills/blob/main/src/cli.ts).

### Isolated restore probe

The probe used a disposable HOME, XDG state directory, project, and local one-skill source. No real agent directory or lock was changed. First, the temporary XDG state contained a valid global version-3 `.skill-lock.json`, while the project contained no `skills-lock.json`:

```sh
env \
  HOME="$probe/home" \
  XDG_CONFIG_HOME="$probe/config" \
  XDG_STATE_HOME="$probe/state" \
  CLAUDE_CONFIG_DIR="$probe/home/.claude" \
  CODEX_HOME="$probe/home/.codex" \
  CI=1 NO_TELEMETRY=1 \
  skills experimental_install --global --agent claude-code --copy
```

The command reported:

```text
No project skills found in skills-lock.json
Add project-level skills with npx skills add <package> (without -g)
```

After adding a project-format `skills-lock.json` pointing at the disposable local source, the exact same command restored the skill only to:

```text
<cwd>/.agents/skills/probe-skill/SKILL.md
```

The temporary HOME remained empty, the temporary global lock remained unchanged, and neither a Claude nor Cursor projection was created. The command rewrote the project lock with a newly computed content hash and normalized source path, so it is a converging project install operation rather than a read-only replay of the supplied lock.

### Verdict for chezmoi restore

`experimental_install` is not a reliable direct fresh-home restore mechanism for the current global lock or cross-harness projection state:

- it ignores the actual global lock path and schema authority;
- it always restores project-scoped canonical skills relative to its working directory;
- it discards per-harness placement because the global lock never records it and the restore path targets only universal agents;
- stored global `skillFolderHash` values are update-detection metadata, not integrity pins enforced during restore; and
- entries without an immutable `ref` are fetched from their moving upstream source, so the current lock is provenance rather than a reproducible content lock.

A wrapper could generate a project-format lock and run the command with the home directory as its working directory, incidentally placing files in `~/.agents/skills`. That would still be a workaround: it mutates the generated project lock, does not restore Claude/Cursor projections, and does not prove that fetched content matches the global lock's recorded hashes. Therefore the global lock remains useful chezmoi-tracked inventory and import evidence, but a separate reconciler or explicit `skills add ... -g` operations are still required for fresh-home global convergence and harness-specific projections.
