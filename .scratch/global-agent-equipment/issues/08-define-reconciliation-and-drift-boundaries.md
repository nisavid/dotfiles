# Define reconciliation and drift boundaries

Type: grilling
Status: resolved

## Question

How should apply treat managed state, unmanaged state, native managers, manual
steps, and exceptions?

## Answer

The resolver computes desired state once and native manager and harness
adapters implement it. Apply may create, update, disable, or retire only state
owned by the catalog. It preserves and reports unmanaged or unknown state;
adoption is explicit. `import` discovers unmanaged state and proposes catalog
entries without claiming ownership or mutating runtime state. A separate
`adopt` operation records a reviewable ownership transfer in authored state;
only a later apply may reconcile it. An active provider route declares one
operation disposition per operation: `automated`, `operator_action`, or
`unavailable`. For example, a Cursor UI install route can have
`operator_action` installation while direct opaque-database editing remains an
`unavailable` operation; neither changes the route's harness coverage outcome.
Non-automated dispositions are verified through supported observable surfaces
where possible and reported with remediation instructions instead of editing
caches or databases.
