# Produce the implementation handoff

Type: task
Status: open
Blocked by: 16, 17

## Question

What final architecture, catalog and lock schema, adapter contract, initial
inventory classification, migration sequence, rollback path, acceptance
matrix, retained-and-retired file map, checkpoint sequence, and publication
plan should ordinary implementation follow? How does it preserve the canonical
harness coverage record from catalog through resolved lock, inventory,
validation, and adapters without accepting a bare outcome or single-route
shorthand? How does it enforce the command
boundaries: audit and import are read-only discovery; update proposes
reviewable lock changes; adopt changes authored ownership only for existing
unmanaged state; and apply alone reconciles runtime state for every accepted
catalog entry? Apply may execute only `automated` operation dispositions on
reconciler-owned active provider routes. Operator-owned routes are
verify-and-report-only, and their mutating dispositions must be
`operator_action` or `unavailable`. `operator_action` and `unavailable` remain
operation dispositions on selected active routes; apply reports them and does
not automate that operation. Only `intentional_omission` and `unsupported`
coverage outcomes select `no_provider` and perform no mutation. Unresolved
identities, incomplete route metadata, unlisted or invalid provider overlap,
coverage-control mismatch, and automated
mutating dispositions on operator-owned routes fail closed during complete plan
validation before the first runtime checkpoint. So does every automated
mutation without declared compensation that restores its captured pre-state.
