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
read-only discovery; adopt produces a reviewable authored ownership change;
apply alone reconciles adopted runtime state.
