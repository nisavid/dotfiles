# Preview-server port selection

Repository: `example/widgets`

Pull request: `#42`, draft, exact pushed base/head already resolved.

The required collapsed Diff disclosure is already valid and must remain first.

Change:

- `widgets preview --port 0` now asks the operating system for an available
  loopback port and prints the final `http://127.0.0.1:<port>` URL after bind.
- Explicit nonzero ports keep their current behavior.
- The server still binds loopback only. No remote-listen option is added.
- Four implementation/test files changed, with 86 authored additions and 19
  deletions.

Reason:

- Parallel local and CI preview jobs currently race on a fixed default port.
- Callers need the bound URL only after the operating system selects the port.

Observed at the pushed head, in no intended presentation order:

- `go test ./cmd/preview ./internal/preview` passed 27 tests covering port zero,
  explicit ports, and bind failure.
- `widgets preview --port 0 ./demo` printed one loopback URL after binding.
- `curl --fail "$printed_url/healthz"` returned `ok`.
- Ctrl-C stopped that server; the same port could then be bound immediately.
- Two concurrent `widgets preview --port 0 ./demo` processes printed different
  URLs, and both health checks passed.
- No installation into the author's real user-global configuration was run.

There are no rollout steps or follow-up tickets.
