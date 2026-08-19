# Resolve bootstrap tokens in the session layer

Status: accepted

## Context

Where should the host-agent PAT be resolved from the native credential store?

## Decision

Resolve it inside an internal session layer used by `secretctl` and lazy
recovery. Do not represent the bootstrap token as a consumer profile or expose
native credential-store locators in `secret-exec`.
