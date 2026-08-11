# Define inventory selection and version semantics

Type: grilling
Status: resolved

## Question

How should source-wide selection, explicit selection, versions, ordinary apply,
and updates behave?

## Answer

The catalog supports both source-wide `all` selection and explicit component
selection. Both resolve to a reviewed lock snapshot that enumerates the exact
equipment and each provider route's restore class. An `immutable` route records
a source revision or package version plus a reproducible artifact reference;
ordinary apply converges to that target and may use the network only to restore
the pinned artifact. A `native_rolling` route records its channel and observed
version but cannot claim deterministic restoration of that version. A separate
explicit update operation refreshes immutable sources, expands `all`, samples
native-rolling channels, and produces a reviewable lock diff without silently
changing ordinary apply's target. An adapter must suppress native background
updates when supported; otherwise it detects and classifies manager-driven
drift and reports the observed version. The operator closes that drift only by
reviewing an update that advances the observed-version baseline or changes the
provider route or restore class. Immutable restore through an unsuppressible
rolling route has an `operator_action` or `unavailable` disposition; this
does not change the route's harness coverage outcome.
