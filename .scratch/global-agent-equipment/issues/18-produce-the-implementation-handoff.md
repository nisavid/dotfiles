# Produce the implementation handoff

Type: task
Status: open
Blocked by: 16, 17

## Question

What final architecture, catalog and lock schema, adapter contract, initial
inventory classification, migration sequence, rollback path, acceptance
matrix, retained-and-retired file map, checkpoint sequence, and publication
plan should ordinary implementation follow? How does it enforce the command
boundaries: audit and import are read-only discovery; update proposes
reviewable lock changes; adopt changes authored ownership only for existing
unmanaged state; and apply alone reconciles runtime state for every accepted
catalog entry? Apply may execute only `automated` operation dispositions on
active provider routes. `operator_action` is reported for the operator;
`unavailable`, intentional-omission, and unsupported outcomes select no
automated mutation. Unresolved identities, incomplete route metadata, and
unlisted or invalid provider overlap fail closed.
