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
adoption is explicit. Unsupported portable operations, including opaque Cursor
user-plugin state, are modeled as `manual`, verified through supported
observable surfaces where possible, and reported with remediation instructions
instead of editing caches or databases.
