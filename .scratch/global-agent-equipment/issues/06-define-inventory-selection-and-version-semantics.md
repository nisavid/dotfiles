# Define inventory selection and version semantics

Type: grilling
Status: resolved

## Question

How should source-wide selection, explicit selection, versions, ordinary apply,
and updates behave?

## Answer

The catalog supports both source-wide `all` selection and explicit component
selection. Both resolve to a reviewed lock snapshot that enumerates the exact
equipment and immutable source revisions or package versions. Ordinary apply
converges to that lock and may use the network only to restore missing pinned
artifacts. A separate explicit update operation refreshes sources, expands
`all`, produces a reviewable lock diff, and never silently changes ordinary
apply's target.
