# Choose the reconciliation architecture

Type: grilling
Status: resolved

## Question

Which architecture should implement the catalog, deduplication policy, restore,
and harness-specific behavior?

## Answer

Use one authored catalog, one resolver and generated resolved lock, and native
manager and harness adapters. Chezmoi remains the deployment entrypoint and
owns portable source data and narrow overlays. The resolver exposes distinct
audit, apply, update, import, and adopt operations rather than turning runtime
caches or native manager state into additional authorities. Import is
read-only discovery. Adopt records ownership of existing unmanaged runtime
state through a reviewable authored change. Apply reconciles every accepted
catalog entry, whether newly authored or adopted, and is the only operation
that mutates runtime state. Apply is not globally atomic across adapters: it
uses deterministic ordering and durable per-operation checkpoints, stops on
failure, compensates only changes declared reversible, and retries by auditing
observed state before idempotent convergence.
