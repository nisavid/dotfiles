# Global agent equipment acceptance contract

This is the release gate defined by Issue #60. It specifies the evidence the
production reconciler and the separately authorized runtime migration must
produce. Passing the design-schema tests or the disposable prototype alone does
not satisfy the production gate.

## Evidence record

Each release candidate writes a secret-free evidence bundle with:

- the exact candidate implementation identity and complete installed-
  implementation manifest digest, catalog digest, lock digest, plan digest,
  plan-action-set digest, capability-set digest, sealed captured-state identity
  and digest, each route's closed capability and manager-version evidence
  binding, harness and manager versions, and fixture version;
- one result for every requirement ID below: `pass`, `fail`, `blocked`, or
  `not_run`, plus an artifact reference and execution timestamp;
- before and after runtime observation digests for mutating fixtures;
- the ordered checkpoint and compensation trace for failure fixtures; and
- an explicit human sign-off for each live-only check.

Only `pass` closes a requirement. `blocked` and `not_run` are visible release
failures, not waivers. Artifacts contain secret-reference names but never
resolved values. The gate fails if a requirement is absent, duplicated, or
recorded against a different candidate, action set, captured state, or
catalog-lock binding.

The fixture runner creates a disposable home and isolated XDG directories for
every automated scenario. It replaces native CLIs with stateful fakes unless a
scenario is explicitly marked live. A fixture may read only its own sandbox;
it must prove no path outside that sandbox changed.

## Catalog, coverage, and planning fixtures

| ID | Required fixture and assertion | Evidence |
| --- | --- | --- |
| `CAT-01` | Accept a catalog containing every equipment kind in the first slice (`skill`, `plugin`, and `mcp`) and one modeled deferred plugin component. | Automated schema and semantic-validator result |
| `CAT-02` | Accept each exact coverage outcome with its canonical shape: provider outcomes carry one complete provider selection; omission outcomes carry exact `no_provider`. | Automated parameterized validator result |
| `CAT-03` | Reject a bare outcome, a single-route shorthand, a provider outcome with `no_provider`, and an omission with a provider selection. | One negative fixture per malformed shape |
| `CAT-04` | Expand every selected identity across exactly `claude`, `codex`, and `cursor`; reject a missing, duplicate, or unknown harness record. | Expanded-matrix comparison |
| `CAT-05` | Apply whole-record template precedence deterministically and reject partial, null, recursive, or unresolved inheritance. | Golden expanded records and negative fixtures |
| `CAT-06` | Accept one preferred route and explicit supplementary routes only when one matching `allow_overlap` exception names the complete route set and rationale. Reject every unlisted or mismatched overlap. | Positive and negative overlap fixtures |
| `CAT-07` | Require every active route to have exactly one route control owner, exact provider-and-distribution-bound provenance owner, restore class, activation group, native-update state, and disposition for every required operation. | Field-deletion, wrong-binding, and conflicting-field mutation fixtures |
| `CAT-08` | Accept `managed_provider` only when all routes are `reconciler_owned`; accept `manually_managed_provider` only when at least one route is `operator_owned`. | Positive and negative ownership fixtures |
| `CAT-09` | Reject every automated mutating disposition on an operator-owned route while allowing automated `inspect`. | Operation-by-operation matrix fixture |
| `CAT-10` | Reject an automated mutating operation without `restore_captured_pre_state` compensation or without matching adapter capability. Put the invalid entry last and prove the returned mutation plan is empty. | Full-plan fail-closed trace with zero checkpoints |
| `CAT-11` | Accept immutable restore only with an immutable selector, reproducible artifact reference, verified content digest, and `not_applicable` native-update state. Reject a tag, channel, or observed version as immutable evidence. | Digest verification and negative selector fixtures |
| `CAT-12` | Accept native-rolling restore only with channel, reviewed observed-version baseline, observation source, and update-control state; never describe it as exact restore. | Golden route and diagnostic assertions |
| `CAT-13` | Compute canonical catalog and lock digests independent of formatting and object-key order; reject a semantically stale catalog-lock pair before opening the checkpoint store. | Digest vectors and checkpoint-open spy |
| `CAT-14` | Reject literal secret material or secret-bearing fields. Accept only environment-variable names or opaque secret references. | Public canary scan and schema negatives |

## Resolution and command-boundary fixtures

| ID | Required fixture and assertion | Evidence |
| --- | --- | --- |
| `RES-01` | Resolve identical inputs repeatedly to byte-identical diagnostics, matrices, overlays, lock proposals, and plan order. | Repeated-run golden digests |
| `RES-02` | Apply stable selective component controls before forming activation groups. Prove individually controllable losing components disappear while an inseparable group remains atomic. | Component-control trace and activation-group golden |
| `RES-03` | Resolve Matt's 25 Claude skills to one official-plugin activation group while keeping standalone routes for Codex and Cursor; propose only positively identified Claude projection retirements. | Matt prototype fixture |
| `RES-04` | Resolve Context7, Firecrawl, GitHub, Greptile, and Chrome DevTools direct/plugin candidates without unexplained duplicates; preserve each explicit allowed overlap. | MCP prototype selections and conflict diagnostics |
| `RES-05` | Generate overlays and lock diffs containing owned fields and secret references only. | Golden files plus recursive secret-canary scan |
| `CMD-01` | `audit` reads runtime state and writes neither authored nor runtime state. | Filesystem and fake-manager before/after digest equality |
| `CMD-02` | `import` discovers unmanaged state and emits a proposal without claiming ownership or changing runtime state. | Proposal golden plus runtime digest equality |
| `CMD-03` | `adopt` requires an exact imported observation and changes only a reviewable authored proposal. Runtime state remains byte-identical until later apply. | Catalog diff plus runtime digest equality |
| `CMD-04` | `update` expands source-wide selection, advances immutable targets or reviewed rolling baselines, and emits a lock proposal without changing runtime state. | Lock diff plus runtime digest equality |
| `CMD-05` | `apply` rejects a stale or incomplete plan, then reconciles every accepted catalog entry in deterministic order when the complete plan is valid. | Rejection trace and complete ordered plan trace |
| `CMD-06` | Apply reports `operator_action` and `unavailable` operations with supported verification evidence but never automates them. | Adapter call spy and operator report |

## Convergence, drift, and retirement fixtures

| ID | Required fixture and assertion | Evidence |
| --- | --- | --- |
| `CON-01` | Converge an empty disposable home from catalog and lock, including canonical standalone skills, projections, plugins, component selections, and direct MCP overlays. | Fresh-home tree and native-state golden |
| `CON-02` | Reapply to the converged fixture with no mutations, checkpoint writes, manager installs, or authored diffs. | Zero-call spies and identical digests |
| `CON-03` | Repair each missing catalog-owned item independently without changing unrelated managed or unmanaged state. | Parameterized deletion-and-repair results |
| `CON-04` | Restore immutable content only after digest verification; reject corrupt or mismatched content before replacing runtime state. | Valid/corrupt artifact fixtures |
| `CON-05` | Switch a preferred provider route and retire only catalog-owned losing projections after the winner verifies. | Ordered switch trace and retained-unmanaged assertion |
| `CON-06` | Detect an unselected duplicate and fail closed; accept a supplementary route only through the exact overlap exception. | Duplicate and overlap fixtures |
| `CON-07` | Preserve unknown and imported-but-unadopted state. Retirement of unmanaged state is a report only and performs no delete. | Adapter delete spy remains zero |
| `CON-08` | Retire adopted catalog-owned state only through apply, preserving unrelated keys and runtime objects. | Narrow-diff assertion |
| `CON-09` | Detect manager-driven native-rolling version drift. Ordinary apply does not advance the baseline; reviewed update proposes it. | Drift diagnostic and lock proposal |
| `CON-10` | For a regular file, directory tree, symlink, and broken symlink under the standalone root, preserve type, bytes or tree digest, applicable metadata, link text, resolved target, and broken state. Never follow an existing symlink for a write. | Parameterized lstat/tree fixtures and outside-target canary |
| `CON-11` | Preserve unmanaged drift encountered between audit and apply; compare-before-mutate stops rather than overwriting it. | Concurrent-change injection for every adapter surface |

## Adapter contract fixtures

| ID | Required fixture and assertion | Evidence |
| --- | --- | --- |
| `ADP-01` | Accept only the closed adapter record envelopes and CapabilityDiscovery all-success or all-error result. An individual record never grants mutation authority. | Schema fixtures plus standalone-record authority negative |
| `ADP-02` | Bind the selected capability, provider family, harness, manager-version evidence, route, and operation. Reject missing, duplicate, unavailable, operator-only, or substituted capability authority. | Plural discovery and provider/operation counterexamples |
| `ADP-03` | Recompute canonical capability, route, action, desired-state, normalized-state, and receipt bindings. Reject any coordinated echo, digest, action identity, or precondition mismatch. | Field-mutation and canonical-digest matrix |
| `ADP-04` | Derive exact readable and writable surfaces from the capability rule and active-plus-controlled membership. Reject broadened scopes, duplicate controls, unsupported states, and omitted route controls. | Surface-rule and component-control matrix |
| `ADP-05` | Keep desired target fragments distinct from complete normalized pre/post state. Require exact capture, immediate guard, post-verification, and compensation restore digests. | Partial-as-full, noncanonical capture, post-state, and compensation negatives |
| `ADP-06` | Authorize mutation only through one closed `ApplySequence` bound to `command: apply`, an independently trusted current candidate identity and installed-manifest digest, the exact phase, durable checkpoint reference, action, receipt, and verification records. | Foreign-candidate and coordinated authority counterexample matrix |
| `ADP-07` | Require successful receipt evidence, equal compare guards, exact surface evidence, and phase-correct compensation; native-rolling plugin removal remains nonautomated. | Apply/compensate receipt and native-removal negatives |
| `ADP-08` | Require distinct observation request identities and UTC chronology `pre observation <= invocation start <= invocation finish <= post observation`. | Apply and compensation chronology matrix |

## Captured-state and plan-action-set fixtures

| ID | Required fixture and assertion | Evidence |
| --- | --- | --- |
| `CAP-01` | Reject schema-invalid, duplicate-member, NaN, Infinity, malformed, or traversal-bearing action-set and capture inputs before semantic authorization. | Schema, public API, and CLI negatives |
| `CAP-02` | Recompute the closed plan-action-set, action, identity, desired-state, expected-post-state, and set digests; bind the distinct candidate identity and installed-implementation manifest digest; require exact independently supplied current-candidate trust and authoritative action membership. | Canonical projection, foreign-candidate, coordinated substitution, and forged-membership matrix |
| `CAP-03` | Represent every provider payload with the catalog's secret-safe typed grammar, including profile references and hardened static credential-free HTTPS URLs. Network-destination policy is a separate executor capability and may allow reviewed private endpoints. | Valid stdio/HTTP and hostile provider fixtures |
| `CAP-04` | Bind every authoritative logical write target bijectively to one exact captured mutable physical target, route, equipment identity, provider, and ownership policy. Reject duplicates, relabeling, or orphan surfaces. | Write-scope, selection-relabel, and physical-target matrix |
| `CAP-05` | Bind every verification-only canonical dependency exactly once to its projected write and forbid mutation of canonical Agent Skills. | Canonical dependency bijection and ownership negatives |
| `CAP-06` | Permit native inverse removal only for captured absence, an authoritative forward install that owns the same exact target, and the complete expected forward-post guard. | Presence/recovery/action-target coherence matrix |
| `CAP-07` | Keep diagnostics secret-free and identifier-redacted; malformed inputs return deterministic diagnostics rather than crashes. | API/CLI canary and malformed-structure matrix |

## Checkpoint, failure, and compensation fixtures

Run `CHK-02` through `CHK-09` once for every automated mutating adapter
operation. Run them again for every migration boundary named in `MIGRATION.md`.

| ID | Required fixture and assertion | Evidence |
| --- | --- | --- |
| `CHK-01` | Validate the complete plan before the first checkpoint; an invalid final action yields zero runtime and checkpoint mutation. | Last-action invalid fixture |
| `CHK-02` | Fail the atomic prepared-checkpoint write. No runtime mutation occurs and retry creates one valid prepared record. | Write-fault trace |
| `CHK-03` | Persist `prepared` with invocation intent `not_started`, fail its atomic transition to `started`, prove no adapter call occurred, then audit and retry once without destructive replay. | Recovery classification, intent-write fault, and call counts |
| `CHK-04` | Persist `prepared` with invocation intent `started`, complete the mutation, and fail before completion persistence. Retry audits the expected post-state and records completion without replay. A `not_started` record at the same target is concurrent drift, never this run's effect. | Mutation receipt, state digest, and call counts |
| `CHK-05` | Fail the atomic completion-checkpoint write. Recovery neither duplicates the mutation nor loses the prepared record. | Journal and call-count trace |
| `CHK-06` | Inject a later action failure. Compensate every earlier completed mutation in reverse topological order from captured pre-state, with durable `compensating` and `compensated` phases. | Full ordered trace and restored digest |
| `CHK-07` | Change a completed surface externally before compensation. Compare-before-restore preserves the external value and stops. | Drift diagnostic and unchanged external digest |
| `CHK-08` | Fail compensation and preserve a durable recoverable record. Audit-before-retry classifies state and never issues duplicate or destructive replay. | Fault and retry trace |
| `CHK-09` | Inject a concurrent change immediately before every adapter mutation. Compare-before-mutate preserves it and stops before the native manager call. | Parameterized adapter call spies |
| `CHK-10` | Bind each checkpoint to run, candidate identity, installed-implementation manifest digest, catalog, lock, plan, sealed captured-state identity and digest, capability-set, the route's closed capability and manager-evidence binding, action identity and ordinal, route, operation, pre-state, and expected-post-state digests; reject replay under any changed binding. | Field-mutation and set-membership negatives |

## Migration and rollback fixtures

| ID | Required fixture and assertion | Evidence |
| --- | --- | --- |
| `MIG-01` | Replace the blanket Claude projector with catalog-driven projection before activating the winner or removing any selective link. | Ordered checkpoint trace |
| `MIG-02` | Install the official Matt plugin only when absent, enable it, and verify its complete active activation group before removing any losing projection. Inject failure after install, enable, and winner verification; restore prior installation and enablement, uninstalling only if initially absent. | Fake-Claude state transitions and dependency trace |
| `MIG-03` | Remove each catalog-identified Matt Claude symlink one at a time only after the winner verifies, without reading through or mutating its standalone target. Inject failure after every removal and restore exact link text and broken/resolved state before disabling or uninstalling the winner; restore the legacy projector last. | Per-link fault matrix, target digest equality, and reverse-topological trace |
| `MIG-04` | Reconcile each MCP and plugin/component selection after provider verification. Inject failure after every owned overlay or selection change and restore captured values only when compare-before-restore matches. | Per-surface fault matrix |
| `MIG-05` | Verify desired equipment coverage and absence of unapproved duplicates before retaining changes. A verification failure compensates every earlier mutation. | Coverage report and reverse compensation trace |
| `MIG-06` | Inject an external change before every untouched migration surface and before every restore. Preserve it, stop, and require a new plan. | Concurrent-change matrix |
| `MIG-07` | Prove a successful migration retains desired provider selections and removes only owned losing projections; prove rollback restores every captured link before winner disablement or uninstall, restores every other captured plugin, enablement, MCP, and selection field, and restores the projector last. | Complete before/after/rollback snapshots |

`MIG-01`, `MIG-02`, and `MIG-05` use plan-bound read-only verification nodes,
not `PlannedAction` records. Their canonical node definitions and dependency
edges contribute to `plan_digest`; successful predicate evidence is journaled
without an action checkpoint. A converged winner still requires a fresh bound
observation, and reverse compensation skips verification nodes.

## Live checks

These checks use disposable or operator-approved accounts and directories. They
are never inferred from populated caches and are rerun immediately before
authorizing runtime migration.

| ID | Check | Required observation |
| --- | --- | --- |
| `LIVE-01` | Fresh Claude user-scope install of `mattpocock-skills` from the official marketplace. | Native list reports one installed and enabled plugin exporting exactly the reviewed 25-skill activation group. |
| `LIVE-02` | Claude marketplace update controls and reinstall behavior. | Record whether background update can be suppressed for this route and confirm it remains `native_rolling` unless an exact fetched artifact and digest are proven. |
| `LIVE-03` | Fresh Codex plugin and plugin-MCP installation plus component controls. | Record supported install, enable, MCP enablement/tool-policy, version, and restore operations without assuming cache restoration. |
| `LIVE-04` | Cursor user plugin and skill discovery behavior. | Record the supported user installation surface, whether realpath-identical Claude and Agent Skills entries deduplicate, and whether any stable per-path exclusion exists. Opaque database editing is forbidden. |
| `LIVE-05` | Direct MCP startup for every selected harness route using secret references. | Server starts and authenticates while logs, diagnostics, diffs, and evidence contain no resolved secret values. |
| `LIVE-06` | Native manager drift. | Change or observe a rolling provider version and prove audit reports drift while update alone proposes the reviewed baseline advancement. |

## Current executable design evidence

The following tests are executable design fixtures. They establish the named
semantics without inspecting or mutating a real harness. They do not mark a
release requirement `pass`; the production candidate must rerun the same
contract through its real adapters and evidence writer.

| Requirements | Exact executable evidence |
| --- | --- |
| `CAT-01` | `AgentEquipmentDesignTest.test_every_declared_equipment_kind_has_valid_and_invalid_examples` |
| `CAT-02`, `CAT-03` | `AgentEquipmentDesignTest.test_valid_provider_and_no_provider_outcomes_resolve`; `AgentEquipmentDesignTest.test_bare_outcome_and_single_route_shorthand_are_rejected` |
| `CAT-04`, `CAT-05` | `AgentEquipmentDesignTest.test_missing_harness_coverage_fails_closed`; `AgentEquipmentDesignTest.test_duplicate_or_incomplete_lock_coverage_is_rejected`; `AgentEquipmentDesignTest.test_template_reference_must_match_target_harness` |
| `CAT-06` | `AgentEquipmentDesignTest.test_supplementary_route_requires_exact_allow_overlap` |
| `CAT-07` | `AgentEquipmentDesignTest.test_operation_matrix_is_exact_and_complete`; `AgentEquipmentDesignTest.test_provenance_has_exactly_one_owner`; `AgentEquipmentDesignTest.test_provenance_owner_matches_provider_and_harness`; `AgentEquipmentDesignTest.test_standalone_provenance_owner_matches_selected_distribution`; `AgentEquipmentDesignTest.test_native_plugin_provenance_owner_matches_exact_plugin`; the immutable and native-rolling restore tests named below |
| `CAT-08`, `CAT-09` | `AgentEquipmentDesignTest.test_provider_outcome_must_match_route_control_owners`; `AgentEquipmentDesignTest.test_operator_owned_route_rejects_automated_mutation` |
| Partial `CAT-10` | `AgentEquipmentDesignTest.test_automated_mutation_requires_pre_state_compensation` and `AgentEquipmentDesignTest.test_an_invalid_final_entry_yields_no_plan` prove catalog-level compensation and full-design fail-closed behavior. Matching live adapter capability is checked at the adapter action boundary, but a resolver-level unsupported final action with zero plan and unopened checkpoint store remains a production-candidate fixture. |
| `CAT-11`, `CAT-12` | `AgentEquipmentDesignTest.test_immutable_restore_requires_revision_reference_digest_and_update_control`; `AgentEquipmentDesignTest.test_native_rolling_restore_requires_reviewed_update_state` |
| `CAT-13`, `CAT-14` | `AgentEquipmentDesignTest.test_canonical_digest_is_utf8_compact_and_key_sorted`; `AgentEquipmentDesignTest.test_stale_catalog_lock_digest_is_rejected`; `AgentEquipmentDesignTest.test_provider_configuration_is_typed_and_secret_safe`; `AgentEquipmentDesignTest.test_literal_secret_material_fails_closed_without_echoing_it`; `AgentEquipmentDesignTest.test_secret_references_accept_environment_variables_and_opaque_profiles` |
| `ADP-01` | `AdapterContractSchemaTests.test_schema_is_valid_draft_2020_12`; `AdapterContractSchemaTests.test_valid_records_satisfy_the_closed_contract`; `AdapterContractSchemaTests.test_invalid_records_fail_closed`; `AdapterContractSchemaTests.test_individual_record_does_not_grant_mutation_authority` |
| `ADP-02` | `AdapterContractSchemaTests.test_capability_provider_harness_and_manager_evidence_are_bound`; `AdapterContractSchemaTests.test_sequence_selects_the_request_bound_capability_from_plural_discovery`; `AdapterContractSchemaTests.test_sequence_rejects_missing_or_duplicate_request_bound_capability`; `AdapterContractSchemaTests.test_sequence_requires_automated_route_and_capability_operation` |
| `ADP-03` | `AdapterContractSchemaTests.test_valid_sequence_has_canonical_embedded_payload_digests_and_exact_bindings`; `AdapterContractSchemaTests.test_apply_sequence_recomputes_action_identity_coordinates`; `AdapterContractSchemaTests.test_sequence_rejects_each_request_observation_echo_mismatch`; `AdapterContractSchemaTests.test_sequence_rejects_each_request_action_and_action_receipt_echo_mismatch` |
| `ADP-04` | `AdapterContractSchemaTests.test_sequence_rejects_coordinated_surface_scope_outside_capability_rule`; `AdapterContractSchemaTests.test_sequence_accepts_each_surface_identity_rule`; `AdapterContractSchemaTests.test_sequence_rejects_unsupported_or_broadened_component_controls`; `AdapterContractSchemaTests.test_sequence_rejects_route_control_omitted_from_desired_state`; `AdapterContractSchemaTests.test_codex_github_no_provider_skill_is_controlled_but_not_active` |
| `ADP-05` | `AdapterContractSchemaTests.test_apply_sequence_rejects_desired_fragment_digest_as_full_state_digest`; `AdapterContractSchemaTests.test_apply_sequence_rejects_noncanonical_pre_capture_state_digest`; `AdapterContractSchemaTests.test_sequence_rejects_ok_state_and_compensation_restore_mismatches`; `AdapterContractSchemaTests.test_sequence_accepts_compensation_restored_to_captured_pre_state` |
| `ADP-06`, `ADP-07` | `AdapterContractSchemaTests.test_valid_apply_sequence_satisfies_the_closed_contract`; `AdapterContractSchemaTests.test_apply_sequence_rejects_coordinated_authority_counterexamples`; `AdapterContractSchemaTests.test_apply_sequence_rejects_verification_of_a_different_route`; `AdapterContractSchemaTests.test_sequence_rejects_native_rolling_plugin_remove`; `AdapterContractSchemaTests.test_cross_field_safety_invariants_fail_closed` |
| `ADP-08` | `AdapterContractSchemaTests.test_apply_sequence_uses_distinct_observation_request_identities`; `AdapterContractSchemaTests.test_apply_sequence_rejects_receipt_finished_before_started`; `AdapterContractSchemaTests.test_apply_and_compensation_sequences_bind_observation_chronology` |
| `CAP-01` | `CapturedStateValidationTest.test_schema_and_fixture_are_valid`; `CapturedStateValidationTest.test_plan_action_set_schema_is_closed`; `CapturedStateValidationTest.test_public_and_cli_gates_reject_schema_invalid_locators`; `CapturedStateValidationTest.test_cli_rejects_ambiguous_or_nonstandard_json` |
| `CAP-02` | `CapturedStateValidationTest.test_plan_action_digest_covers_the_closed_canonical_payload`; `CapturedStateValidationTest.test_full_plan_projection_binds_all_automated_action_authority`; `CapturedStateValidationTest.test_forward_install_requires_separate_authoritative_plan_membership` |
| `CAP-03` | `CapturedStateValidationTest.test_plan_action_projection_represents_secret_safe_mcp_providers` |
| `CAP-04`, `CAP-05` | `CapturedStateValidationTest.test_action_write_scope_and_canonical_dependencies_are_bijective`; `CapturedStateValidationTest.test_schema_rejects_skill_root_and_ownership_conflation`; `CapturedStateValidationTest.test_full_plan_projection_binds_all_automated_action_authority` |
| `CAP-06` | `CapturedStateValidationTest.test_native_installation_capture_accepts_only_coherent_route_evidence`; `CapturedStateValidationTest.test_forward_install_requires_separate_authoritative_plan_membership` |
| `CAP-07` | `CapturedStateValidationTest.test_manifest_semantics_fail_closed`; `CapturedStateValidationTest.test_malformed_manifest_returns_a_diagnostic_instead_of_crashing`; `CapturedStateValidationTest.test_diagnostics_never_echo_captured_identifiers`; `CapturedStateValidationTest.test_cli_exits_nonzero_for_a_semantic_error` |
| `RES-01` | `AgentEquipmentDesignTest.test_resolution_is_deterministic_under_input_ordering` |
| `RES-02` | `AgentEquipmentDesignTest.test_component_controls_have_one_exact_non_conflicting_shape`; `AgentEquipmentDesignTest.test_shared_activation_group_produces_one_action_per_route_operation`; `AgentEquipmentAcceptanceTest.test_route_switch_controls_components_and_retires_only_owned_duplicates` |
| `RES-03`, `RES-04` | `AgentEquipmentDesignTest.test_proposed_initial_catalog_and_lock_are_complete_and_valid`; `AgentEquipmentDesignTest.test_initial_inventory_counts_and_classifications_are_complete` |
| `RES-05` | `AgentEquipmentDesignTest.test_provider_configuration_is_typed_and_secret_safe`; `AgentEquipmentAcceptanceTest.test_durable_artifacts_contain_secret_references_but_no_secret_values` |
| `CMD-01`, `CMD-02`, `CMD-03` | `AgentEquipmentAcceptanceTest.test_audit_import_and_adopt_commands_are_runtime_read_only`; `AgentEquipmentAcceptanceTest.test_adoption_requires_an_exact_import_and_never_mutates_runtime`; `AgentEquipmentAcceptanceTest.test_adoption_rejects_incoherent_imported_value_and_digest`; `AgentEquipmentAcceptanceTest.test_adoption_requires_a_minted_import_identity_and_exact_bindings`; `AgentEquipmentAcceptanceTest.test_adoption_distinguishes_present_null_from_absence` |
| `CMD-04` | `AgentEquipmentAcceptanceTest.test_update_is_an_explicit_proposal_until_apply`; `AgentEquipmentAcceptanceTest.test_native_rolling_drift_requires_reviewed_baseline_update` |
| `CMD-05` | `AgentEquipmentAcceptanceTest.test_invalid_final_action_fails_before_the_checkpoint_store_changes`; `AgentEquipmentAcceptanceTest.test_fresh_home_converges_to_the_complete_desired_state` |
| `CMD-06` | `AgentEquipmentAcceptanceTest.test_nonautomated_operations_are_reported_without_adapter_mutation` |
| `CON-01`, `CON-02`, `CON-03` | `AgentEquipmentAcceptanceTest.test_fresh_home_converges_to_the_complete_desired_state`; `AgentEquipmentAcceptanceTest.test_reapply_is_a_steady_state_no_op`; `AgentEquipmentAcceptanceTest.test_each_missing_owned_item_is_repaired_without_touching_other_state` |
| `CON-04` | `AgentEquipmentAcceptanceTest.test_immutable_content_is_verified_before_explicit_update_mutates` |
| `CON-05`, `CON-06`, `CON-07` | `AgentEquipmentAcceptanceTest.test_route_switch_controls_components_and_retires_only_owned_duplicates`; `AgentEquipmentAcceptanceTest.test_duplicate_routes_fail_closed_unless_the_exact_overlap_is_declared`; `AgentEquipmentAcceptanceTest.test_adoption_requires_an_exact_import_and_never_mutates_runtime` |
| `CON-08`, `CON-09` | `AgentEquipmentAcceptanceTest.test_retirement_mutates_only_exact_adopted_owned_state_through_apply`; `AgentEquipmentAcceptanceTest.test_retirement_reports_drift_when_adopted_state_disappears`; `AgentEquipmentAcceptanceTest.test_native_rolling_drift_requires_reviewed_baseline_update` |
| Partial `CON-10`; `CON-11` | `AgentEquipmentAcceptanceTest.test_standalone_capture_restores_files_trees_and_links_without_following` and `AgentEquipmentAcceptanceTest.test_standalone_restore_recreates_deleted_and_replaced_symlink_entries` cover type, content, mode, link text, target, broken state, and no-follow restore behavior; `AgentEquipmentAcceptanceTest.test_standalone_lexical_traversal_cannot_capture_or_restore_outside`, `AgentEquipmentAcceptanceTest.test_standalone_restore_rejects_nested_traversal_before_removal`, `AgentEquipmentAcceptanceTest.test_standalone_restore_rejects_tampered_digests_before_removal`, and `AgentEquipmentAcceptanceTest.test_standalone_restore_rejects_changed_symlink_target_state` cover containment and snapshot integrity; `AgentEquipmentAcceptanceTest.test_compare_before_mutate_preserves_concurrent_changes_on_every_surface` covers the `CON-11` state-machine seam. |
| `CHK-01`, `CHK-02`, `CHK-03` | `AgentEquipmentAcceptanceTest.test_invalid_final_action_fails_before_the_checkpoint_store_changes`; `AgentEquipmentAcceptanceTest.test_duplicate_surface_final_action_fails_before_any_effect`; `AgentEquipmentAcceptanceTest.test_invalid_plan_bindings_fail_before_checkpoint_store_changes`; `AgentEquipmentAcceptanceTest.test_plan_rejects_non_string_and_empty_identities_before_any_effect`; `AgentEquipmentAcceptanceTest.test_plan_rejects_non_json_state_before_any_effect`; `AgentEquipmentAcceptanceTest.test_absence_sentinel_cannot_collide_with_valid_json_state`; `AgentEquipmentAcceptanceTest.test_state_equality_distinguishes_booleans_from_numbers`; `AgentEquipmentAcceptanceTest.test_plan_rejects_forged_no_op_action_before_any_effect`; `AgentEquipmentAcceptanceTest.test_stale_plan_digest_fails_before_checkpoint_or_runtime_mutation`; `AgentEquipmentAcceptanceTest.test_prepared_write_failure_has_no_runtime_effect_and_retry_is_valid`; `AgentEquipmentAcceptanceTest.test_prepared_failure_before_mutation_audits_then_retries_once` |
| `CHK-04`, `CHK-05` | `AgentEquipmentAcceptanceTest.test_mutated_but_uncompleted_step_is_audited_without_replay` |
| `CHK-06`, `CHK-07`, `CHK-08` | `AgentEquipmentAcceptanceTest.test_later_failure_compensates_completed_steps_in_reverse_order`; `AgentEquipmentAcceptanceTest.test_compare_before_restore_preserves_an_external_change`; `AgentEquipmentAcceptanceTest.test_failed_compensation_is_durable_and_recovery_audits_before_retry`; `AgentEquipmentAcceptanceTest.test_explicit_compensation_can_resume_after_first_intent_write_fails`; `AgentEquipmentAcceptanceTest.test_compensation_recovery_finishes_the_complete_reverse_prefix`; `AgentEquipmentAcceptanceTest.test_blocked_compensation_cannot_report_recovered` |
| `CHK-09`, `CHK-10` | `AgentEquipmentAcceptanceTest.test_compare_before_mutate_preserves_concurrent_changes_on_every_surface`; `AgentEquipmentAcceptanceTest.test_fresh_action_rejects_target_valued_concurrent_change`; `AgentEquipmentAcceptanceTest.test_auto_compensation_preserves_target_valued_external_change`; `AgentEquipmentAcceptanceTest.test_invocation_intent_write_failure_occurs_before_adapter_call`; `AgentEquipmentAcceptanceTest.test_plan_rejects_foreign_candidate_authority_before_checkpoint`; `AgentEquipmentAcceptanceTest.test_plan_rejects_ambiguous_capability_identity_before_checkpoint`; `AgentEquipmentAcceptanceTest.test_invalid_capability_binding_digests_fail_before_checkpoint`; `AgentEquipmentAcceptanceTest.test_checkpoint_replay_rejects_every_changed_binding`; `AgentEquipmentAcceptanceTest.test_checkpoint_replay_rejects_forged_embedded_step_identity`; `AgentEquipmentAcceptanceTest.test_checkpoint_preflight_rejects_malformed_durable_record`; `AgentEquipmentAcceptanceTest.test_checkpoint_preflight_rejects_duplicate_json_members`; `AgentEquipmentAcceptanceTest.test_checkpoint_binding_is_type_exact_for_json_values`; `AgentEquipmentAcceptanceTest.test_checkpoint_replay_binds_capability_set_and_route_evidence`; `AgentEquipmentAcceptanceTest.test_retry_preflights_every_checkpoint_binding_before_any_write`; `AgentEquipmentAcceptanceTest.test_compensation_recovery_rejects_changed_bindings_before_restore`; `AgentEquipmentAcceptanceTest.test_completed_checkpoint_preserves_reverted_external_state`; `AgentEquipmentAcceptanceTest.test_completed_checkpoint_reverted_to_pre_state_blocks_all_compensation`; `AgentEquipmentAcceptanceTest.test_compensated_checkpoint_cannot_replay_forward_plan` |
| `CHK-04` through `CHK-06` state-machine examples, all automated mutating operations | `AgentEquipmentAcceptanceTest.test_forward_recovery_and_reverse_compensation_cover_every_mutating_operation` repeats post-mutation audit, completion-persistence recovery, and reverse compensation for every modeled mutating operation, including native-update suppression. It is not the complete `CHK-02` through `CHK-09` production matrix. |
| Partial migration state-machine seam; no `MIG-*` requirement closes | `AgentEquipmentAcceptanceTest.test_migration_activates_winner_before_retiring_loser`, `AgentEquipmentAcceptanceTest.test_failed_winner_verification_never_retires_loser`, and `AgentEquipmentAcceptanceTest.test_migration_rollback_restores_loser_before_retiring_winner` prove the representative forward and reverse migration order. `AgentEquipmentAcceptanceTest.test_every_migration_boundary_compensates_to_the_exact_initial_state` and `AgentEquipmentAcceptanceTest.test_every_migration_surface_preserves_changes_before_mutate_and_restore` exercise generic ordered checkpoints, reverse compensation, and compare guards. `AgentEquipmentAcceptanceTest.test_successful_migration_retains_winners_and_removes_only_owned_losers` checks the representative state map. These do not prove the production dependency graph, typed projector, per-link `lstat`/unlink, conditional native-plugin, coupled-surface, MCP-overlay, component-control, or coverage-verification behavior required by `MIG-01` through `MIG-07`. |

Production command parsing, sandbox enforcement, human-facing report rendering,
and the complete real-adapter operation matrix remain production-candidate
requirements. The fake migration matrix does not authorize or perform runtime
migration.

The fixture checkpoint store proves state-machine transitions, binding checks,
and audit-before-retry. It does not model distinct temporary-write, file-`fsync`,
rename, and parent-directory-`fsync` failures. Likewise, its standalone snapshot
proves type, bytes/tree digest, mode, and symlink behavior, but not UID, GID,
nanosecond timestamps, flags, ACLs, or extended attributes. The production
candidate must supply those missing `CHK-*` and `CON-10` results, plus the typed
and composed `MIG-01` through `MIG-07` fixtures, before the release gate can
pass.

If the first `compensating` checkpoint write fails, no durable record can imply
rollback intent after a crash. The fixture's `recover_compensation` seam therefore
requires a surviving `compensating` or `compensated` phase. Its separate
`compensate` seam represents a fresh, explicit rollback authorization and may
initiate the same guarded reverse walk from validated `prepared` and `completed`
records.

All `LIVE-*` checks remain live-only. They require the real native managers,
disposable or operator-approved accounts, current harness versions, secret
resolution at process boundaries, and explicit human sign-off. No schema,
prototype, or fake-manager result substitutes for those observations.

The future production release command must fail unless the evidence bundle has
one passing result for every ID in this document and no extra unknown result.
