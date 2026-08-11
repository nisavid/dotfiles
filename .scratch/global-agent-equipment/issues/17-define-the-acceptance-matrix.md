# Define the acceptance matrix

Type: grilling
Status: open
Blocked by: 13, 14, 15, 16

## Question

Which automated fixtures and live checks prove fresh-home convergence,
steady-state no-op behavior, missing-item repair, immutable restore, explicit
update, provider-route switching, selective component disabling, duplicate
detection, refusal to claim unmanaged state before explicit adoption, runtime
state unchanged before and after both import and adopt, ownership transfer only
in authored state until apply, unmanaged-drift preservation, manager-driven
version drift and reviewed baseline advancement,
reproducible-versus-native-rolling restore claims, standalone entry type,
metadata, symlink-text, resolved-target, broken-symlink-state, and content
preservation, retirement, non-automated-state reporting, secret non-disclosure,
and rollback?

How does the coverage matrix prove exactly one harness coverage outcome for
every equipment identity × harness, including the provider selection or
explicit no-provider value? For every active provider route × operation, how
does a separate operation matrix prove exactly one `automated`,
`operator_action`, or `unavailable` disposition with outcome-specific evidence?
Which fixtures reject missing or conflicting provenance owners and verify
exactly one owner and its restore evidence per active provider route? Which
fixtures reject an unlisted overlap or incomplete supplementary route?
Which fixtures prove `managed_provider` has only reconciler-owned routes,
`manually_managed_provider` has at least one operator-owned route, and every
operator-owned route rejects automated mutating dispositions before any runtime
checkpoint while still allowing automated read-only verification?

Which fixtures prove immutable content-digest verification, stale catalog-lock
rejection before mutation, and zero mutation when an invalid entry appears last
in the resolved plan? Which fixtures prove unmanaged retirement cannot delete
runtime state and generated prototype artifacts never disclose secret values?

How do partial-apply fixtures inject an adapter failure after each checkpoint,
verify that processing stops, confirm compensation occurs only where declared,
and prove that audit-before-retry converges idempotently? How do they also cover
mutation followed by failure before checkpoint persistence, checkpoint-write
failure, and compensation failure without duplicate or destructive replay? How
do migration fixtures inject failure after legacy-projector replacement, each Claude-link
removal, plugin installation and enablement, MCP reconciliation, and plugin
selection, then verify restoration of every captured state item? Which
concurrent-change fixtures exercise compare-before-mutate and
compare-before-restore on every affected surface and prove external changes are
preserved?
