# Use a generic injected-secret rotation workflow

Status: accepted

## Context

How far should `secretctl` automate rotation of injected credentials?

## Decision

Use a provider-neutral staged workflow: issue the replacement externally,
ingest it securely into Proton Pass, validate every affected host and consumer,
then require confirmation that the old provider credential was revoked.
Provider-specific issuance and revocation adapters are deferred.
