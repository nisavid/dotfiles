# Ship a CLI with human and JSON output

Status: accepted

## Context

What interface should the first complete secret control plane provide?

## Decision

Ship a CLI with concise human output and stable JSON for inventory, status,
diagnosis, enrollment, rotation, binding, and addition workflows. Use secure
interactive input only when a credential enters the system. Defer a TUI.
