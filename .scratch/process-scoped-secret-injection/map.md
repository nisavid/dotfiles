# Wayfinder: Process-Scoped Secret Injection

## Destination

Produce a reviewer-ready, decision-complete architecture, acceptance
specification, and sequenced implementation handoff for reliable macOS and
Linux process-scoped credential injection using one Proton Pass host agent per
managed host. The map ends before implementation; execution then resumes from
the sequenced handoff produced by
[issue 27](./issues/27-produce-the-implementation-handoff.md).

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

- [Bound the Wayfinder destination][decision-01] —
  produce the architecture, acceptance specification, and implementation
  sequence before resuming execution.
- [Map Proton agents to managed hosts][decision-02] —
  use one viewer-only Proton host agent in steady state; permit one verified
  replacement during rotation, then remove the retired agent and grants.
- [Recover provider sessions at startup and on demand][decision-03] —
  combine proactive readiness with lazy self-healing.
- [Separate the control plane from the data plane][decision-04] —
  make `secretctl` the operator surface and keep `secret-exec` minimal.
- [Split desired state across three stores][decision-05] —
  separate Proton values and grants, host bootstrap tokens, and value-free
  chezmoi mappings; treat Proton's native-store session key as provider-managed
  runtime state.
- [Define declared consumer coverage][decision-06] —
  cover verified PATH shims and explicit application bindings.
- [Fail closed and notify on provider failure][decision-07] —
  preserve bindings, reject the launch, and keep durable status authoritative
  while host-native notification remains best-effort.
- [Ship a CLI with human and JSON output][decision-08] —
  defer a TUI while making every operator workflow scriptable.
- [Plan mutations before applying them][decision-09] —
  bind approval to a credential-free plan, journal before mutation, and verify
  every step before reporting convergence.
- [Warn before host-agent rotation][decision-10] —
  monitor expiry and rotate through one operator-approved command.
- [Support macOS and Linux now][decision-11] —
  leave Windows as a later expansion.
- [Resolve bootstrap tokens in the session layer][decision-12] —
  keep host-agent PATs out of consumer profiles and `secret-exec`.
- [Trust the logged-in OS user][decision-13] —
  prevent ambient and accidental exposure without claiming hostile
  same-user isolation.
- [Use a generic injected-secret rotation workflow][decision-14] —
  stage, validate, and confirm external revocation without provider-specific
  automation.
- [Split Proton administration between the app and CLI][decision-15] —
  keep privileged agent and grant choices in the Proton Pass web app while
  `secretctl` owns host-local lifecycle.
- [Determine the Proton agent lifecycle][decision-16] —
  use a distinct replacement agent for overlap because agents cannot administer
  themselves; validate persisted-session invalidation fail-closed.
- [Determine native host lifecycle constraints][decision-17] —
  make the native-host adapter require a persistent, unlocked Secret Service
  provider and the Proton session layer set `PROTON_PASS_LINUX_KEYRING=dbus`;
  both are required for Linux reboot persistence.

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

[decision-01]: ./issues/01-bound-the-destination.md
[decision-02]: ./issues/02-map-agents-to-hosts.md
[decision-03]: ./issues/03-recover-sessions-at-startup-and-on-demand.md
[decision-04]: ./issues/04-separate-control-and-data-planes.md
[decision-05]: ./issues/05-split-state-across-three-stores.md
[decision-06]: ./issues/06-define-declared-consumer-coverage.md
[decision-07]: ./issues/07-fail-closed-and-notify.md
[decision-08]: ./issues/08-ship-cli-and-json.md
[decision-09]: ./issues/09-plan-before-applying.md
[decision-10]: ./issues/10-warn-before-agent-rotation.md
[decision-11]: ./issues/11-support-macos-and-linux.md
[decision-12]: ./issues/12-resolve-bootstrap-in-session-layer.md
[decision-13]: ./issues/13-trust-the-os-user.md
[decision-14]: ./issues/14-use-generic-secret-rotation.md
[decision-15]: ./issues/15-split-proton-administration.md
[decision-16]: ./issues/16-research-proton-agent-lifecycle.md
[decision-17]: ./issues/17-research-native-host-lifecycle.md
