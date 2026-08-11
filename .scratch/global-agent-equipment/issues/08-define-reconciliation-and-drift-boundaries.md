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
only a later apply may reconcile it. A `manual` outcome has a supported provider
route but requires operator action. An `unsupported` outcome has no supported
provider for the operation and selects an explicit no-provider value. For
example, Cursor's supported UI route may be manual, while editing its opaque
user-plugin database is unsupported. Both are verified through supported
observable surfaces where possible and reported with remediation instructions
instead of editing caches or databases.
