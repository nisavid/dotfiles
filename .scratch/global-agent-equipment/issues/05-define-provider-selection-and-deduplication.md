# Define provider selection and deduplication

Type: grilling
Status: resolved

## Question

How should provider selection, plugin coverage, selective component controls,
and unavoidable overlap interact?

## Answer

For a `managed_provider` or `manually_managed_provider` harness coverage outcome,
each equipment identity and harness has a provider selection: one preferred
route plus zero or more supplementary routes named by an `allow_overlap`
exception with a rationale. Every member is an active provider route and must
carry its own operation dispositions, provenance owner, restore evidence, and
acceptance coverage. It also declares one route control owner:
`reconciler_owned` or `operator_owned`. `managed_provider` requires every active
route to be `reconciler_owned`; `manually_managed_provider` requires at least one
`operator_owned` active route and may include supplementary reconciler-owned
routes. Together, the outcome, selection, and complete active-route records form
the canonical harness coverage record. `intentional_omission` and `unsupported`
coverage outcomes select the exact `no_provider` value instead. Operation
dispositions and control owners on active routes do not erase or replace that
harness-level selection. The
resolver inventories a distribution's complete coverage, applies every stable
harness control that can selectively enable or disable a component, and then
treats only the remaining inseparable activation groups as atomic. It omits or
disables losing standalone projections where the harness supports that.
Unselected duplicate active routes are invalid. A plugin that supplies unique
hooks or other equipment therefore triggers a coverage-based, case-specific
choice among the plugin, standalone routes, or an explicit provider selection
that includes both.
