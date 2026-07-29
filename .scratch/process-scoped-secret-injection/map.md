# Wayfinder: Process-Scoped Secret Injection

## Destination

Produce a reviewer-ready, decision-complete architecture, acceptance
specification, and sequenced implementation handoff for reliable macOS and
Linux process-scoped credential injection using one Proton Pass host agent per
managed host. The map ends before implementation; execution then resumes under
the existing reliability-repair handoff.

## Notes

- This map is planning-only.
- Use `grilling` and `domain-modeling` for unresolved decisions.
- Use official Proton and operating-system sources for research.
- Apply an appropriate `codex-security` review after the architecture is
  decision-complete.
- Never expose a credential value in commands, output, source, logs, tests,
  tickets, pull requests, or handoffs.
- Keep this effort independent from Hindsight control-plane extraction.
- Preserve current behavior only when it remains simpler, more reliable,
  maintainable, and consistent with the acceptance specification.

## Decisions so far

- [Bound the Wayfinder destination](./issues/01-bound-the-destination.md) —
  produce the architecture, acceptance specification, and implementation
  sequence before resuming execution.
- [Map Proton agents to managed hosts](./issues/02-map-agents-to-hosts.md) —
  use one viewer-only Proton host agent per managed host.
- [Recover provider sessions at startup and on demand](./issues/03-recover-sessions-at-startup-and-on-demand.md) —
  combine proactive readiness with lazy self-healing.
- [Separate the control plane from the data plane](./issues/04-separate-control-and-data-planes.md) —
  make `secretctl` the operator surface and keep `secret-exec` minimal.
- [Split desired state across three stores](./issues/05-split-state-across-three-stores.md) —
  separate Proton values and grants, host bootstrap tokens, and value-free
  chezmoi mappings.
- [Define declared consumer coverage](./issues/06-define-declared-consumer-coverage.md) —
  cover verified PATH shims and explicit application bindings.
- [Fail closed and notify on provider failure](./issues/07-fail-closed-and-notify.md) —
  preserve bindings, reject the launch, and surface actionable host-native
  diagnostics.
- [Ship a CLI with human and JSON output](./issues/08-ship-cli-and-json.md) —
  defer a TUI while making every operator workflow scriptable.
- [Plan mutations before applying them](./issues/09-plan-before-applying.md) —
  reconcile multi-store changes through credential-free plans and explicit
  approval.
- [Warn before host-agent rotation](./issues/10-warn-before-agent-rotation.md) —
  monitor expiry and rotate through one operator-approved command.
- [Support macOS and Linux now](./issues/11-support-macos-and-linux.md) —
  leave Windows as a later expansion.
- [Resolve bootstrap tokens in the session layer](./issues/12-resolve-bootstrap-in-session-layer.md) —
  keep host-agent PATs out of consumer profiles and `secret-exec`.
- [Trust the logged-in OS user](./issues/13-trust-the-os-user.md) —
  prevent ambient and accidental exposure without claiming hostile
  same-user isolation.
- [Use a generic injected-secret rotation workflow](./issues/14-use-generic-secret-rotation.md) —
  stage, validate, and confirm external revocation without provider-specific
  automation.
- [Split Proton administration between the app and CLI](./issues/15-split-proton-administration.md) —
  keep privileged agent and grant choices in Proton while `secretctl` owns
  host-local lifecycle.
- [Determine the Proton agent lifecycle](./issues/16-research-proton-agent-lifecycle.md) —
  use a distinct replacement agent for overlap because agents cannot administer
  themselves; validate persisted-session invalidation fail-closed.
- [Determine native host lifecycle constraints](./issues/17-research-native-host-lifecycle.md) —
  use compiled Keychain and libsecret adapters with platform-native startup and
  diagnostics; Linux readiness begins after persistent Secret Service unlock.

## Not yet specified

- Exact command names, output contracts, and interaction design within
  `secretctl` after the operator-workflow prototype.
- Exact non-secret operation-journal contents after reconciliation failure
  modes are known.
- Exact implementation phases after platform, Proton, catalog, and security
  decisions converge.

## Out of scope

- Windows support in the first implementation; add it as a later platform
  expansion.
- A first-release TUI; the CLI and JSON contracts must settle first.
- Provider-specific credential issuance and revocation adapters.
- Protocol-specific degraded placeholders such as diagnostic-only MCP servers.
- Hard isolation from malicious processes running as the logged-in OS user.
- A generic secret-provider plugin framework.
