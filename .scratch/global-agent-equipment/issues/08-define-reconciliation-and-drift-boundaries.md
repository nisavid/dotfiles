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
Every active route also declares `reconciler_owned` or `operator_owned` runtime
control. A reconciler-owned route may execute an `automated` mutating operation.
An operator-owned route is verify-and-report-only for the reconciler, so each of
its mutating operations must be `operator_action` or `unavailable`; full-plan
validation rejects any operator-owned route with an automated mutating
disposition. `managed_provider` means all selected routes are reconciler-owned.
`manually_managed_provider` means at least one selected route is operator-owned.
Non-automated dispositions are verified through supported observable surfaces
where possible and reported with remediation instructions instead of editing
caches or databases.
