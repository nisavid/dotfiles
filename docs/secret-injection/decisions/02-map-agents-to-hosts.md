# Map Proton agents to managed hosts

Status: accepted

## Context

How should Proton Pass agent identities map to machines and consumers?

## Decision

Use one viewer-only host agent per managed host in steady state, scoped to the
injection vault. Rotation may overlap one replacement agent, for a maximum of
two, only until its grants, provider session, and bound consumers verify. Then
delete the retired agent and confirm its access grants are gone before reporting
convergence. Keep per-consumer credential minimization in local credential
profiles.
