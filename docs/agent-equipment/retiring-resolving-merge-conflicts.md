# Retire the standalone resolving-merge-conflicts skill

Use this procedure to retire the native Skills-managed standalone route from
Codex, Cursor, and Claude after accepting its Versionkeeping replacement in
those clients. First adopt the reviewed source selections and Claude alias
exclusions that prevent recreation. Preserve the separately managed Claude
plugin and retained custom skills. Record results in the
[owning adoption record](https://github.com/nisavid/provingkit/issues/112).

## Bind the installed command and state

The inspected example is [Skills](https://github.com/vercel-labs/skills) 1.7.0
with Node 24.21.0. Resolve the installed `skills` launcher through its package
manager's selector to the actual Node executable (`skills_node`) and installed
`bin/cli.mjs` (`skills_entrypoint`). Record resolved paths, versions, and digests
for those files, package metadata, `dist/cli.mjs`, and any selector. Re-scout the
removal implementation when these bindings drift; a version string alone does
not establish compatible behavior. Do not download or update the manager as
part of retirement.

The inspected `dist/cli.mjs` SHA-256 is
`fde68534019765fb69510a0038ca7df2810a6ffed4c26fef9beabdcf6cc6701c`.

Capture `HOME`, `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, and `XDG_STATE_HOME`, including
unset states, and retain them for preflight and execution. Check `--version`
and `remove --help` through the selected Node and entrypoint with the telemetry
and cache overrides below. The command inherits the captured environment; it
does not select a home or lock for the operator.

Inspect the exact `resolving-merge-conflicts` object under each root below with
`lstat` and, for links, `readlink`. Record absent objects explicitly. Codex and
Claude overrides are trimmed before use.

| Object | Skills 1.7.0 path rule |
| --- | --- |
| Shared canonical skill | `$HOME/.agents/skills/resolving-merge-conflicts` |
| Codex standalone skill | `$CODEX_HOME/skills/resolving-merge-conflicts`; default `$HOME/.codex/skills/resolving-merge-conflicts` when the trimmed variable is empty or unset. |
| Cursor standalone skill | `$HOME/.cursor/skills/resolving-merge-conflicts` |
| Claude standalone skill | `$CLAUDE_CONFIG_DIR/skills/resolving-merge-conflicts`; default `$HOME/.claude/skills/resolving-merge-conflicts` when the trimmed variable is empty or unset. |
| Global lock | `$XDG_STATE_HOME/skills/.skill-lock.json` when the variable is nonempty; otherwise `$HOME/.agents/.skill-lock.json`. |

Keep the observed state-home binding: the manager does not infer
`$HOME/.local/state` when `XDG_STATE_HOME` is unset. Require a readable, valid
version-3 lock and bind its exact `skills.resolving-merge-conflicts` record,
including the source URL and skill path, to the accepted retirement inventory.
Confirm the CLI's normalized name lookup selects that identity. The command can
remove a lock-only entry; an absent canonical directory is not a blocker.

The remover does not check ownership or a symlink's destination. If a named
object is retained custom content, stop this command and return that mismatch
to the adoption owner. There is no conditional-target or lock-only removal mode.
Back up the complete lock bytes and metadata and every addressed object,
including dangling symlinks as links, with their restoration steps. Capture the
unrelated lock entries and retained skill/plugin state needed for comparison.
Recheck the bound inputs immediately before execution and keep other skill
manager writes serial with this operation.

## Remove and verify

Run the one named request through the bound installation:

```sh
DISABLE_TELEMETRY=1 DO_NOT_TRACK=1 NODE_DISABLE_COMPILE_CACHE=1 \
  "$skills_node" "$skills_entrypoint" remove resolving-merge-conflicts \
  --global --agent codex cursor claude-code --yes
```

Keep the skill name before `--agent`: that option consumes subsequent
non-option tokens. Omitting the agent list targets every known agent. Do not
substitute `--all` or a wildcard. There is no `--dry-run`; unknown options are
ignored, so adding that flag still permits removal. Agent detection can bypass
confirmation, and the prompt is not a path preview. The native command scans
supported global skill directories even with this explicit selection.

Record the invocation, exit status, output, and warnings. Verify that the three
accepted standalone paths are absent. Full retirement also requires the shared
canonical path and target lock key to be absent. Compare every other lock entry
and top-level field semantically with the backup: the manager reserializes the
complete lock. Verify the retained skills and separate Claude plugin state are
unchanged. Per-path failures can be warnings followed by success text; neither
that text nor the exit status replaces these checks. Retain recovery inputs.

If an unselected detected agent still has its same-name installation path, the
manager deliberately retains the canonical object and global lock key. Record
that partial result and identify the remaining consumer before proceeding.
Return an owned retiring copy for a reviewed scope extension, or preserve a
retained custom consumer and report that the CLI cannot forget the key while
keeping it. Do not widen removal unattended, delete paths by hand, or hand-edit
the lock as a fallback. Investigate warnings or other mismatches as well.

Record the procedure revision and observed postconditions in the adoption
record. The inspected source establishes these controls; successful cutover and
recovery remain separate observations. Continue to keep `retirements` empty in
the [Provingkit selection](provingkit-installations.md#source-and-selection).
