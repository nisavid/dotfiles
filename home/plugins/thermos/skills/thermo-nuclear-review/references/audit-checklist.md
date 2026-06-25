# Security And Correctness Checklist

Use this checklist for the audit pass after reading the diff.

## Breaking Behavior

- Changed contracts, data shapes, defaults, persistence semantics, or lifecycle behavior.
- Missing migrations or backfills.
- Compatibility breaks across callers, packages, generated clients, config, or deployment surfaces.
- Async, retry, caching, ordering, or concurrency changes with downstream effects.

## Developer Experience

- Changed secret locations, environment variable names, ports, hostnames, or network assumptions.
- New required manual setup for existing workflows.
- Scripts or services that become required for behavior that previously worked without them.
- Local build, test, or run flows that silently lose required defaults.

## Feature Leaks

- Gated or internal-only behavior exposed through UI, API, routing, permissions, logs, telemetry, defaults, or docs.
- Checks applied on one path but missing on another path that reaches the same capability.
- Feature flags removed or bypassed without a deliberately scoped rollout.

## Security

- Authentication or authorization bypass.
- Injection, unsafe deserialization, SSRF, path traversal, unsafe file/process access, secret exposure, tenancy leak, or weakened validation.
- Trust-boundary changes that make previously internal input attacker-controlled.

## Calibration

- Do not report intended breakage when the branch clearly and narrowly owns the blast radius.
- Do report intended breakage when the implications look misunderstood, underweighted, or malicious.
- Do not inflate severity for theoretical issues. Trace the path before reporting.
