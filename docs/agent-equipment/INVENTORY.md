# Initial global agent-equipment inventory

This is the read-only classification for Issue #58. The machine-readable
snapshot is [`initial-inventory.json`](initial-inventory.json). It records names,
booleans, versions, source identities, and secret-reference labels only. It
contains no credential values, environment values, machine-local absolute
paths, or opaque application-database content.

Nothing in this inventory authorizes a runtime mutation. In particular, an
unmanaged observation cannot be deleted until an explicit `adopt` proposal is
accepted and a later validated `apply` owns that exact projection or route.

This JSON is a runtime observation and classification artifact, not the
authored catalog or resolved lock. Its desired-state inputs are resolved in the
schema-valid [`initial-catalog.proposed.json`](initial-catalog.proposed.json)
and catalog-digest-bound
[`initial-lock.proposed.json`](initial-lock.proposed.json). Those files are a
review proposal, not live adoption or migration authorization.

## Snapshot

Observed on 2026-08-12 through supported files and read-only CLI surfaces.

| Surface | Observation |
| --- | --- |
| Canonical Agent Skills | 122 entries: 119 directories and 3 symlinks |
| Claude standalone skills | 112 symlinks into the canonical root, 3 separate same-name directories, and 7 absent projections |
| Claude plugins | 47 installed: 38 enabled and 9 disabled |
| Codex plugins | 59 configured entries: 29 reported installed and enabled, and 30 config-only observations |
| Cursor plugins | Installation state is opaque through the installed CLI; no cache or database was inspected |
| Normalized plugin records | 107 observed records: 47 Claude, 59 Codex, and one opaque Cursor wildcard; plus one reviewed, not-installed Matt distribution |
| Direct MCPs | Claude 5, Codex 8, Cursor 4 |
| Plugin-provided MCP components | Claude 16 and Codex 5; Cursor is not enumerable, so zero is not claimed |

The 122 canonical skills are classified once each: 25 in the proposed managed
slice, 33 duplicate or semantic-overlap candidates, and 64 explicitly retained
unmanaged observations. The JSON groups every name by classification, source
evidence, entry kind, Claude visibility, and overlap evidence.

Provenance is observable for 87 skills through the global `skills` lock. The
repository also names 32 canonical skills, with `graphite` appearing in both
sets. Four live skills have neither source: `applying-diataxis`, `impeccable`,
`publishing-systalyze-sites`, and `working-in-systalyze-worktrees`; they remain
retained observations rather than inferred adoptions. The three canonical
Hindsight symlinks additionally identify the Hindsight control plane as their
active-release source.

## Normalized plugin components

`plugin_component_inventory` records every observed Claude, Codex, and Cursor
plugin entry independently of the provider decisions below. Each record has a
distribution-local component identity when a name is known, a component kind,
and either an evidenced selective state, an inseparable activation group, or
an explicit `unknown` control state. A distribution-local identity does not by
itself assert that a same-name component from another provider is the same
logical equipment identity.

The inventory distinguishes three evidence cases:

- `known` names a positively observed component.
- `counted_but_unnamed` preserves an observed count while leaving the component
  identity null. It does not manufacture names from plugin titles or skill
  overlaps.
- `confirmed_absent_kinds` means a supported list or reviewed manifest proved
  zero components of that kind. `unknown_kinds` means neither presence nor
  absence was established; an empty `known` array never means zero.

This representation has 82 named component observations and 206
counted-but-unnamed observations across the 107 runtime plugin records. The
counts are observations, not 288 logical capabilities: identity reconciliation
and provider precedence happen later.

| Distribution evidence | Positively known components | Control and completeness |
| --- | --- | --- |
| Reviewed Matt `1.2.3` candidate | All 25 named skills; no MCP, hook, agent, command, LSP, app, or other equipment | Complete upstream manifest; the 25 skills form one inseparable Claude activation group |
| Claude Chrome DevTools `1.7.0` | MCP `chrome-devtools` and six named skills | Whole-plugin control; the seven components are inseparable; hooks, agents, and commands are confirmed absent while uninspected kinds remain unknown |
| Claude Firecrawl `1.0.9` | Ten named skills including `firecrawl-cli`; no MCP | Whole-plugin control; other component kinds remain unknown |
| Claude GitHub | One HTTP MCP; no skills, hooks, or commands | Whole-plugin control; uninspected kinds remain unknown |
| Codex GitHub curated baseline `11c74d6b` | App/connector, HTTP MCP, and four named skills | Observed selective state keeps the app, MCP, and three skills enabled and `yeet` disabled; the live adapter must still prove those controls |
| Codex GitHub remote `0.1.8` comparison | No MCP | This is a different channel payload and cannot substitute for the observed curated baseline |
| Cursor wildcard | Nothing enumerable through the supported CLI | Every component kind and control remains unknown; no absence is claimed |

For every other plugin, the JSON carries only the names and counts present in
the snapshot evidence. Config-only Codex entries and opaque Cursor state have
no inferred payload. This is what makes the plugin-versus-standalone policy
case-specific: a plugin may replace standalone equipment only after its entire
positive and unknown component surface is qualified, and selective controls
may split that decision only when their live capability is proved.

## Matt Pocock correction and proposal

The current machine has all 25 reviewed Matt skills in the canonical Agent
Skills root. Twenty-one are symlinked into Claude. These four are not:
`to-questionnaire`, `wait-what`, `wizard`, and `writing-for-agents`. No
`mattpocock-skills` Claude plugin is installed.

The reviewed official plugin is version `1.2.3` at upstream commit
`84fdeffd12f2ee307994d1eb6feb48173b6e0502`. Its complete equipment set is the
same 25 skills and it has no plugin-level hooks, MCPs, agents, commands, LSPs,
monitors, or executables. That makes the proposed provider split complete:

- Claude prefers the official `mattpocock-skills` plugin as one inseparable
  25-skill activation group.
- Codex and Cursor use the individually selected canonical standalone skills.
- A later migration may adopt and remove only the 21 positively identified
  Claude symlinks after the plugin is installed and its complete activation
  group is verified. The 25 canonical targets stay untouched.

The official Claude route is `native_rolling`: the install command selects a
marketplace channel, not an old exact artifact. The proposed standalone route
is `immutable` only when the reconciler fetches the reviewed commit and
verifies the recorded archive digest. The proposal's digest is the SHA-256 of
`git archive --format=tar` over `skills/engineering` and
`skills/productivity` at the reviewed commit. The installed `skills` CLI cannot clone
an arbitrary commit through its native `--branch` selector, and
`experimental_install` does not restore the global lock.

## First MCP slice

These are the provider choices in the proposed catalog, not production
adoption. Each selected route has complete ownership, provenance, restore,
component-control, operation, and compensation data. No supplementary route is
selected, so the desired slice contains no accepted overlap exception.

| Equipment | Claude | Codex | Cursor | Disposition |
| --- | --- | --- | --- | --- |
| Chrome DevTools | Native plugin | Direct MCP | Direct MCP | Reviewed proposal: Claude keeps the atomic MCP-plus-six-skill plugin; each bundled skill has an explicit temporary Codex/Cursor omission |
| Context7 | Direct MCP | Direct MCP | Direct MCP | Recommended: the installed Claude plugin is disabled and contributes only the overlapping MCP |
| Firecrawl | Direct MCP | Direct MCP | Direct MCP | Recommended: the enabled Claude Firecrawl plugin contributes ten skills and **no MCP server** |
| GitHub | Direct MCP | Native plugin | Direct MCP | Reviewed proposal: Claude retains process-scoped `secret-exec`; Codex keeps its app, MCP, and three skills while `yeet` is disabled; Cursor gains the direct route |
| Greptile | Direct MCP | Intentional omission | Intentional omission | Recommended with explicit omissions: only the Claude route is currently observed |

The current duplicate candidates are preserved until their winning routes are
adopted. The proposed retirement set owns only the observed direct Claude
Chrome DevTools route, the observed direct Codex GitHub route, and the 21 Matt
Claude projections. Disabled Claude Context7, GitHub, and Greptile plugins
remain unmanaged observations. None of those unmanaged observations is a
deletion instruction.

## Selective-component limits

- Claude exposes whole-plugin enable and disable for the observed plugins. The
  Matt plugin cannot disable one of its 25 skills, and the Chrome DevTools
  plugin cannot select its MCP independently of its six skills.
- The proposed Codex GitHub route records the observed app and MCP enabled,
  `gh-address-comments`, `gh-fix-ci`, and `github` enabled, and `yeet` disabled
  before forming one activation group. The production adapter must still prove
  each exact native control in the `LIVE-03` gate before apply.
- The Claude Firecrawl plugin has nine exact-name skill overlaps with canonical
  standalone skills. `firecrawl` versus the plugin's `firecrawl-cli` is a
  semantic candidate. This is a skill-provider decision, not an MCP overlap.
- `code-review` is a same-name component in Matt and CodeRabbit distributions.
  It needs an equipment-identity decision before either provider is called a
  duplicate.
- Cursor Agent exposes marketplace registration commands but no supported
  user-plugin list, install, enable, or disable surface. Stable `mcp.json` input
  is observable; user-plugin state remains opaque and operator-owned.

## Review dispositions

- `hyperframes-creative` remains a duplicate/overlap candidate everywhere in
  this inventory. Its separate Claude directory is no longer mislabeled as a
  proposed-managed observation; it has two plugin overlaps and still needs an
  identity and provider decision alongside the other Hyperframes skills.
- The disabled direct Codex `computer-use` MCP and the enabled
  MCP-plus-one-skill plugin are both duplicate/overlap candidates. There is no
  complete provider decision in the first slice, so the direct route has no
  adoption or retirement authority and `computer-use-provider-map` stays
  pending. The proposed catalog is intentionally not expanded for it.

## Classification policy

`proposed_managed_equipment_slice` means that a later catalog may adopt the
observation after review. `duplicate_overlap_candidate` records evidence but
does not choose a winner or authorize removal. `stale_unverifiable_observation`
is used for unknown-version Claude plugins and Codex config entries not
reported by the native installed-plugin list. Everything outside this slice is
`explicitly_retained_unmanaged_runtime_observation`. Cursor plugin state is
`opaque_runtime_state`.

The proposed catalog accepts 44 identities from nine distributions, expands
132 exact identity-by-harness coverage records, and names 23 losing surfaces.
It deliberately records the Chrome skill and GitHub component decisions that
remain grouped observations in `initial-inventory.json`; the proposed catalog
and bound lock are the reviewable desired-state resolution of those inputs.

The exact grouped inventory remains minimally surprising for future exceptions:
add a named observation, classify it, state ownership and retirement intent,
and either map it to a complete harness coverage record or retain it without
mutation authority.

## Read-only evidence and verification

The count and name probes used only supported directories, settings, native
lists, and plugin manifests. Representative exact commands were:

```sh
find ~/.agents/skills -mindepth 1 -maxdepth 1 -print | wc -l
find ~/.claude/skills -mindepth 1 -maxdepth 1 -type l -print | wc -l
jq '.skills | length' ~/.local/state/skills/.skill-lock.json
claude plugin list --json | jq '[.[] | {id, version, enabled, mcp_server_names: ((.mcpServers // {}) | keys | sort)}]'
codex plugin list --json | jq '{installed: [.installed[] | {id: .pluginId, version, enabled}]}'
python3 -c 'import pathlib,tomllib; d=tomllib.loads(pathlib.Path.home().joinpath(".codex/config.toml").read_text()); print(len(d.get("plugins", {})), sorted(d.get("mcp_servers", {})))'
jq '(.mcpServers // {}) | keys | sort' ~/.claude.json
jq '(.mcpServers // {}) | keys | sort' ~/.cursor/mcp.json
agent plugin --help
agent mcp list
```

`agent mcp list` returned `SecItemCopyMatching failed -50`; the stable Cursor
MCP file was therefore the supported read-only fallback. No Cursor plugin
database was opened.

The artifact checks are:

```sh
python3 -m json.tool docs/agent-equipment/initial-inventory.json >/dev/null
jq '.counts' docs/agent-equipment/initial-inventory.json
jq '.plugin_component_inventory.summary' docs/agent-equipment/initial-inventory.json
jq '[.plugin_component_inventory.observed_plugins[] | {harness, plugin_id}] | length' docs/agent-equipment/initial-inventory.json
rg -n '/Users/|ivan@|Bearer [A-Za-z0-9]|"(token|api_key|secret|password)"[[:space:]]*:' docs/agent-equipment/initial-inventory.json
python3 -m unittest tests/test_agent_equipment_design.py
```

The JSON parser succeeded. The secret/local-path scan returned no matches.
