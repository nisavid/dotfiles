---
status: accepted
---

# Inject Low-Blast-Radius Keys At Application Boundaries

`secret-exec` normally injects a profile into the one command that uses it, so
a credential lives only in that command's process tree. The `jev-axi` hooks
break that pattern. Claude Code, Claude Desktop, and Codex run them as hook
subprocesses. `jev-axi` reads its key only from `TYPESAFE_API_KEY`, a project
`.env`, or a plaintext configuration file. `jev-axi setup` owns the hook
entries and recognizes them by exact prefix, so the entries cannot be rewritten
to launch through `secret-exec`. Without the key, the hooks fall through to
local rules and add nothing.

We inject `TYPESAFE_API_KEY` at the application boundary instead. The command
map sends each hook host through its command shim with a best-effort mapping,
and the hooks inherit the key from the host. `jev-axi` keeps a strict mapping
of its own. Inside a wrapped host it reuses the injected key. In a terminal it
resolves the key through the provider and fails closed.

The cost is exposure. Every child of a wrapped host sees the key: shell tool
calls, MCP servers, and subagents, including code those hosts run on an agent's
behalf. We accept that only because the key's blast radius is small: it grants
metered access to one scoring API and to no identity, repository, or
infrastructure. The rule is therefore narrow. An application-boundary mapping
is allowed only for a key with a comparably small blast radius, never for an
identity-bearing credential such as a GitHub or AWS token. Those stay on the
individual tools that use them, and a nested `secret-exec` launch of any other
profile still removes the key.

Best-effort mappings keep an unavailable provider from stopping the
applications. A host that falls back starts without the key, notifies once, and
records the fallback in a non-secret marker. Hooks inside it then run keyless at
once, instead of waiting on the provider past their timeouts or sending another
notification. A spoofed marker can only make a launch start without
credentials. A GitHub launch ignores the marker, so it always resolves and
checks its identity.

A host reads the key once, when it starts. Rotating the key therefore requires
restarting every wrapped host. A host also inherits the key only when it starts
through its shim, so desktop entries must launch it by bare name. On Linux the
source manages the Claude Desktop login entry and the Claude Code URL handler,
which the applications otherwise write with absolute paths.

Considered and rejected:

- A plaintext `apiKey` in `jev-axi`'s configuration would put the key on disk
  outside the provider.
- Rewriting the hook entries to launch through `secret-exec` would fight
  `jev-axi setup`, which re-adds its own entries by exact prefix.
- A strict mapping on the hosts would stop Claude Code, Claude Desktop, or
  Codex from starting while the provider is unavailable.
