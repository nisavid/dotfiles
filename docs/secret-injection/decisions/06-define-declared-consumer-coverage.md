# Define declared consumer coverage

Status: accepted

## Context

What does coverage of terminal and application launches guarantee?

## Decision

Verified PATH shims cover name-based launches. Explicit application
configuration binds integrations that do not rely on PATH. Absolute binary
paths are an intentional escape hatch, and diagnostics report unsupported or
bypassing bindings.
