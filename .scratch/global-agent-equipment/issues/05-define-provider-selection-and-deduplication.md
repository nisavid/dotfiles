# Define provider selection and deduplication

Type: grilling
Status: resolved

## Question

How should provider preference, plugin coverage, selective component controls,
and unavoidable overlap interact?

## Answer

For a managed-provider or manually-managed-provider harness coverage outcome,
each equipment identity selects one preferred provider route for that harness.
Intentional omission and unsupported coverage outcomes select an explicit
no-provider value instead. Operation dispositions on a selected route do not
erase or replace that harness-level selection. The resolver inventories a
distribution's complete coverage, applies every stable harness control that can
selectively enable or disable a component, and then treats only the remaining
inseparable activation groups as atomic. It omits or disables losing standalone
projections where the harness supports that. Remaining duplicate active
providers are invalid unless an explicit `allow_overlap` exception records the
rationale. A plugin that supplies unique hooks or other equipment therefore
triggers a coverage-based, case-specific choice among the plugin, standalone
providers, or an intentional combination.
