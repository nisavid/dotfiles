# Fail closed and notify on provider failure

Status: accepted

## Context

What happens when provider readiness fails before or during a managed launch?

## Decision

Keep consumer bindings configured, fail the credential-dependent launch with
one actionable error, and emit a best-effort host-native startup notification.
Persistent non-secret status and `secretctl ensure-ready` are the authoritative
readiness and retry surfaces; notification delivery is not readiness evidence.
