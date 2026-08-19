# Recover provider sessions at startup and on demand

Status: accepted

## Context

When should a managed host establish or repair its Proton provider session?

## Decision

Check proactively at user-session startup for early visibility and recover
lazily in the provider path before a consumer resolves credentials.
