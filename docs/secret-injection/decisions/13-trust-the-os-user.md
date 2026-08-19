# Trust the logged-in OS user

Status: accepted

## Context

Is a malicious process running as the logged-in OS user inside the isolation
threat model?

## Decision

No. Treat the OS account and provider session as trusted. Enforce declared
bindings as fail-closed misuse protection, while claiming containment only
against ambient inheritance, accidental misbinding, logs, and unrelated child
processes.
