# Define provider selection and deduplication

Type: grilling
Status: resolved

## Question

How should provider preference, plugin coverage, selective component controls,
and unavoidable overlap interact?

## Answer

For a managed or manual outcome, each equipment identity selects one preferred
provider per harness. Intentional omission and unsupported outcomes select an
explicit no-provider value instead. The resolver inventories a distribution's
complete coverage, applies every stable harness control that can selectively
enable or disable a component, and then treats only the remaining inseparable
activation groups as atomic. It omits or disables losing standalone
projections where the harness supports that. Remaining duplicate active
providers are invalid unless an explicit `allow_overlap` exception records the
rationale. A plugin that supplies unique hooks or other equipment therefore
triggers a coverage-based, case-specific choice among the plugin, standalone
providers, or an intentional combination.
