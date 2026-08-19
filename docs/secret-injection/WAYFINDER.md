# Wayfinder: Process-Scoped Secret Injection

## Destination

Produce a reviewer-ready, decision-complete architecture, acceptance
specification, and sequenced implementation handoff for reliable macOS and
Linux process-scoped credential injection using one Proton Pass host agent per
managed host. The map ends before implementation; execution then resumes from
the sequenced handoff produced by
[GitHub Issue #96](https://github.com/nisavid/dotfiles/issues/96).

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

## Open work

- [#87: Classify the current system](https://github.com/nisavid/dotfiles/issues/87) —
  current planning frontier.
- [#88: Prototype `secretctl` workflows](https://github.com/nisavid/dotfiles/issues/88) —
  depends on #87 and the accepted lifecycle research.
- [#89: Choose the implementation substrate](https://github.com/nisavid/dotfiles/issues/89) —
  depends on #87, #88, and the native-host lifecycle research.
- [#90: Define reconciliation and recovery](https://github.com/nisavid/dotfiles/issues/90) —
  depends on #88, #89, and the accepted lifecycle research.
- [#91: Define startup readiness](https://github.com/nisavid/dotfiles/issues/91) —
  depends on #89, #90, and the native-host lifecycle research.
- [#92: Define host enrollment and rotation](https://github.com/nisavid/dotfiles/issues/92) —
  depends on #88–#90 and the accepted lifecycle research.
- [#93: Define the injection catalog](https://github.com/nisavid/dotfiles/issues/93) —
  depends on #87–#90.
- [#94: Review the security architecture](https://github.com/nisavid/dotfiles/issues/94) —
  depends on #91–#93.
- [#95: Specify the acceptance matrix](https://github.com/nisavid/dotfiles/issues/95) —
  depends on #87 and #91–#94.
- [#96: Produce the implementation handoff](https://github.com/nisavid/dotfiles/issues/96) —
  depends on #95 and completes the planning map.

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

[decision-01]: ./decisions/01-bound-the-destination.md
[decision-02]: ./decisions/02-map-agents-to-hosts.md
[decision-03]: ./decisions/03-recover-sessions-at-startup-and-on-demand.md
[decision-04]: ./decisions/04-separate-control-and-data-planes.md
[decision-05]: ./decisions/05-split-state-across-three-stores.md
[decision-06]: ./decisions/06-define-declared-consumer-coverage.md
[decision-07]: ./decisions/07-fail-closed-and-notify.md
[decision-08]: ./decisions/08-ship-cli-and-json.md
[decision-09]: ./decisions/09-plan-before-applying.md
[decision-10]: ./decisions/10-warn-before-agent-rotation.md
[decision-11]: ./decisions/11-support-macos-and-linux.md
[decision-12]: ./decisions/12-resolve-bootstrap-in-session-layer.md
[decision-13]: ./decisions/13-trust-the-os-user.md
[decision-14]: ./decisions/14-use-generic-secret-rotation.md
[decision-15]: ./decisions/15-split-proton-administration.md
[decision-16]: ./decisions/16-research-proton-agent-lifecycle.md
[decision-17]: ./decisions/17-research-native-host-lifecycle.md
