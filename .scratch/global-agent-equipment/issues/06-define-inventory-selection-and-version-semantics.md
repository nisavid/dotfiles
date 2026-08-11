# Define inventory selection and version semantics

Type: grilling
Status: resolved

## Question

How should source-wide selection, explicit selection, versions, ordinary apply,
and updates behave?

## Answer

The catalog supports both source-wide `all` selection and explicit component
selection. Both resolve to a reviewed lock snapshot that enumerates the exact
equipment and each provider's restore class. An `immutable` provider records a
source revision or package version plus a reproducible artifact route; ordinary
apply converges to that target and may use the network only to restore the
pinned artifact. A `native_rolling` provider records its channel and observed
version but cannot claim deterministic restoration of that version. A separate
explicit update operation refreshes immutable sources, expands `all`, and
produces a reviewable lock diff without silently changing ordinary apply's
immutable targets. An adapter must suppress native background updates when
supported; otherwise it detects and classifies manager-driven drift, reports
the observed version and remediation, and treats immutable restore through
that provider as manual or unsupported.
