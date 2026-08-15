# Agent equipment resolver prototype findings

Issue #57 asked whether the Matt Pocock and repeated-MCP provider choices are
understandable before production resolver design. The disposable logic
prototype is preserved on branch
[`t3code/agent-equipment-resolver-prototype`](https://github.com/nisavid/dotfiles/tree/t3code/agent-equipment-resolver-prototype/docs/agent-equipment)
at commit
[`7bac9cce697b8344f08ad874f90dfb426a91bd1f`](https://github.com/nisavid/dotfiles/blob/7bac9cce697b8344f08ad874f90dfb426a91bd1f/docs/agent-equipment/prototype-resolver.html).
It is a single self-contained HTML file with no runtime integration and is not
merged into the production branch.

## Question and scenarios

The prototype exercises a small pure reducer through free play and five guided
walkthroughs:

1. Select the official Claude Matt plugin for Claude while keeping verified
   standalone providers for Codex and Cursor.
2. Apply selective component controls before choosing direct or plugin routes
   for Chrome DevTools, Context7, Firecrawl, GitHub, and Greptile MCPs.
3. Reject an exact-restore claim for a native marketplace channel, then recover
   by recording `native_rolling` and a non-automated restore disposition.
4. Add an unexplained losing provider last and prove complete validation emits
   no overlay or lock diff.
5. Accept environment-variable names but reject a resolved-value canary before
   generating any artifact.

The page renders the full observations, component controls, route records,
restore classes, operation summaries, diagnostics, generated proposals, and
decision trace after every action. Every action is preview-only; runtime writes
remain zero.

## Findings absorbed into the design

### Component controls precede activation groups

Provider resolution is clearest as two explicit stages. First apply every
supported per-component control. Then form activation groups only from the
components that remain inseparable. Treating a plugin as atomic at the start
conceals useful Codex MCP controls and incorrectly implies that every Claude
plugin supplies the same component classes.

The current Matt Claude plugin is a genuine atomic case after that first stage:
it exports the same 25 logical skills as the standalone source, no other plugin
equipment, and no supported per-skill suppression. One activation-group record
is therefore more honest than 25 independent Claude mutation plans.

### Coverage and operations remain separate

A provider choice becomes understandable when each row says both what supplies
the equipment and what the route can do. The prototype therefore keeps the
complete harness coverage record separate from operation dispositions.
`native_rolling` does not change a route into an omission or a manual coverage
outcome; it makes exact restore `operator_action` or `unavailable` while other
supported operations can remain automated.

### Native manager channels must not borrow immutable language

The ordinary official Claude install command cannot select an earlier Matt
marketplace entry. A reviewed current marketplace commit and plugin version are
useful baseline evidence, but they do not make reinstall deterministic. The
resolver must reject `immutable` unless it has an independently fetched
artifact, an immutable selector, and a verified content digest.

The same correction applies to the standalone `skills` route. Version 1.5.22
cannot install a Git commit through its GitHub `#ref` path because it passes the
commit to `git clone --branch`. A future immutable standalone adapter must own
fetching or retaining the exact artifact and verify its digest; the global
native lock remains provenance evidence.

### The repeated MCP set needs per-harness choices

One global winner per MCP is too coarse. The useful proposed fixture choices
are:

| MCP | Claude | Codex | Cursor | Important qualification |
| --- | --- | --- | --- | --- |
| Chrome DevTools | Plugin MCP | Direct overlay | Direct overlay | The reviewed plugin set is one MCP plus six skills; the proposed catalog records the skills and explicit temporary Codex/Cursor omissions. |
| Context7 | Direct overlay | Direct overlay | Direct overlay | Disable an overlapping plugin component only through a supported control. |
| Firecrawl | Direct overlay | Direct overlay | Direct overlay | The currently installed Claude Firecrawl plugin reports skills, not an MCP; its skill overlap is a separate decision. |
| GitHub | Direct overlay | Plugin MCP | Direct overlay | Claude keeps process-scoped secret injection; Codex preserves the app and three enabled skills, disables `yeet`, and retires its direct duplicate only after live component verification. |
| Greptile | Direct overlay | `no_provider` pending evidence | `no_provider` pending evidence | Do not invent a provider from name similarity or opaque state. |

These selections are resolved in
`docs/agent-equipment/initial-catalog.proposed.json` and its bound
`docs/agent-equipment/initial-lock.proposed.json`, but remain proposals rather
than runtime adoption. Fresh inventory and live capability checks may revise
them before a production lock or migration plan is authorized.

### Fail-closed output is easier to inspect

Keeping generated overlays and lock diffs empty until the entire provider and
operation matrix validates makes the invalid-last-entry case visible without
simulating a partial apply. This behavior belongs in the pure resolver. The
executor should never receive a partly valid action list.

### Secret references should be the resolver's only secret-shaped input

The simplest non-disclosure contract is structural: the resolver receives
environment-variable names or opaque secret references, never their resolved
values. It can then generate narrow overlays, diagnostics, and lock diffs
without a redaction algorithm. Secret resolution stays inside the existing
`secret-exec` child-process boundary.

## Prototype verification

- The file was served locally and returned its complete HTML document.
- Its inline JavaScript passed `node --check`.
- The built-in collaborative preview loaded the page and reported the expected
  title, but its snapshot and evaluation operations timed out; visual and
  interaction evidence therefore remains exploratory rather than a production
  acceptance receipt.
- A recursive text review found only deliberate secret-reference names and the
  secret-boundary canary labels; no credential value appears in the artifact.
- The prototype branch contains only the single throwaway HTML commit and
  performs no harness, manager, symlink, configuration, or GitHub Issue
  mutation.

Production evidence remains governed by `ACCEPTANCE.md`. In particular, the
prototype does not satisfy fresh-home, adapter failure-injection, rollback, or
live harness checks.
