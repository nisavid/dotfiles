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

How does the coverage matrix prove exactly one canonical harness coverage record
for every equipment identity × harness, including exactly one outcome and its
complete provider selection and active-route records or exact `no_provider`?
For every active provider route × operation, how
does a separate operation matrix prove exactly one `automated`,
`operator_action`, or `unavailable` disposition with outcome-specific evidence?
Which fixtures reject missing or conflicting provenance owners and verify
exactly one owner and its restore evidence per active provider route? Which
fixtures reject a bare coverage outcome, single-route shorthand, unlisted
overlap, or incomplete preferred or supplementary active-route record?
Which fixtures prove `managed_provider` has only reconciler-owned routes,
`manually_managed_provider` has at least one operator-owned route, and every
operator-owned route rejects automated mutating dispositions before any runtime
checkpoint while still allowing automated read-only verification?

Which fixtures prove immutable content-digest verification, stale catalog-lock
rejection before mutation, and zero mutation when an invalid entry appears last
in the resolved plan? Which fixtures prove unmanaged retirement cannot delete
runtime state and generated prototype artifacts never disclose secret values?

How do partial-apply fixtures inject an adapter failure after each checkpoint,
verify that processing stops, and prove that audit-before-retry converges
idempotently? Which full-plan fixture places an automated mutation without
declared pre-state-restoring compensation last and proves rejection with zero
mutation? For accepted plans, how do fixtures confirm every applied mutation is
compensated from its durable checkpoint? How do they also cover mutation followed
by failure before checkpoint persistence, checkpoint-write failure, and
compensation failure without duplicate or destructive replay? How
do migration fixtures inject failure after legacy-projector replacement, each Claude-link
removal, plugin installation and enablement, MCP reconciliation, and plugin
selection, then verify restoration of every captured state item? Which
concurrent-change fixtures exercise compare-before-mutate and
compare-before-restore on every affected surface and prove external changes are
preserved?
