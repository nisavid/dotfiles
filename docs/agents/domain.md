# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT-MAP.md`** at the repo root: it names each context in this repo and points at that context's `CONTEXT.md`. Read each one relevant to the topic.
- **`docs/adr/`**: read ADRs that touch the area you're about to work in.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

Multi-context repo. Contexts live under `docs/<context>/` rather than `src/<context>/`, because the deployable payload is chezmoi source state under `home/`:

```text
/
├── CONTEXT-MAP.md                     ← names each context, links its glossary
├── docs/
│   ├── adr/                           ← system-wide decisions (created lazily)
│   ├── agent-equipment/CONTEXT.md     ← context glossary
│   └── secret-injection/CONTEXT.md    ← context glossary
└── home/                              ← chezmoi source state
```

The map lists only contexts in this repository. Related external repositories may appear in the map's Relationships prose, but never as context entries, and their `CONTEXT.md` files are not linked from here.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in the relevant context's `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_
