# Research current harness and manager behavior

Type: research
Status: resolved

## Question

What documented and observed constraints must the architecture respect for
Claude Code, Codex, Cursor, chezmoi, Matt Pocock's distributions, and the
`skills` CLI?

## Answer

Use the evidence and conclusions in
[Global agent equipment: primary-source findings](../../../docs/research/GLOBAL_AGENT_EQUIPMENT_PRIMARY_SOURCES.md).
The decisive constraints include Claude plugin namespacing and whole-plugin
controls for some components, Codex path-specific skill disabling and
per-plugin-MCP policy, Cursor's incomplete portable plugin and skill-exclusion
interfaces, chezmoi's low-level but composable primitives, the native global
`skills` lock's projection and restore limitations, and the official Claude
marketplace's pinned Matt Pocock plugin snapshot.
