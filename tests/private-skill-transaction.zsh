#!/usr/bin/env zsh
emulate -L zsh
setopt errexit nounset pipefail
unsetopt bg_nice

repo_root=${0:A:h:h}
cli=$repo_root/scripts/private-skill-transaction
typeset -a fixtures
trap 'cleanup_fixtures' EXIT

test_dir=${0:A:h}/private-skill-transaction.d
source $test_dir/support.zsh
source $test_dir/locking.zsh
source $test_dir/restore.zsh
source $test_dir/apply.zsh
source $test_dir/apply-targets.zsh

case ${1:-all} in
  lock) test_lock_contention_release_and_descendant_lifetime ;;
  lock-path) test_lock_path_validation_and_parent_mode_preservation ;;
  token) test_bogus_participant_token ;;
  phase-cleanup) test_all_validated_phase_names_are_cleaned ;;
  restore) test_successful_two_skill_restore ;;
  validation) test_validation_failures_have_no_partial_update ;;
  controls) test_control_character_targets_are_rejected ;;
  restore-boundaries) test_restore_prepublication_crash_boundaries ;;
  orphan-cleanup) test_all_public_acquisitions_clean_orphan_prepublication_phases ;;
  recovery) test_catchable_and_killed_recovery_with_type_transitions ;;
  restore-signals) test_restore_signals_roll_back_immediately ;;
  restore-ancestors) test_private_skill_ancestor_containment ;;
  apply) test_outer_apply_protects_persistent_state_and_rolls_back_restore ;;
  apply-post-success-failures) test_outer_apply_post_success_catchable_failures_roll_back_immediately ;;
  apply-signals) test_outer_apply_signals_roll_back_immediately ;;
  apply-target-set) test_outer_apply_protects_every_explicit_target ;;
  git-publication) test_git_publication_activation_target_set ;;
  unsupported-type) test_unsupported_apply_target_type_is_rejected ;;
  projected-modes) test_projected_apply_file_modes_are_preserved ;;
  apply-prepublish-failures) test_apply_projection_catchable_failures_cleanup ;;
  apply-flags) test_apply_rejects_uncontained_flags ;;
  apply-db-conflict) test_apply_preserves_concurrent_live_database_edit ;;
  apply-boundaries) test_apply_pre_pointer_crash_boundaries ;;
  committed) test_committed_crash_cleanup_and_manifest_binding ;;
  conflict) test_visible_conflict_and_absent_symlink_transitions ;;
  metadata-conflict) test_directory_metadata_only_conflict ;;
  final-check) test_final_desired_state_check_retains_conflict ;;
  recovery-teardown) test_recovery_tears_down_plaintext_before_encrypted_state ;;
  outer-capability) test_outer_capability_binds_nested_finalization ;;
  snapshot-trees) test_directory_snapshot_tree_contract ;;
  all)
    test_lock_contention_release_and_descendant_lifetime
    test_lock_path_validation_and_parent_mode_preservation
    test_bogus_participant_token
    test_all_validated_phase_names_are_cleaned
    test_successful_two_skill_restore
    test_validation_failures_have_no_partial_update
    test_control_character_targets_are_rejected
    test_restore_prepublication_crash_boundaries
    test_all_public_acquisitions_clean_orphan_prepublication_phases
    test_catchable_and_killed_recovery_with_type_transitions
    test_restore_signals_roll_back_immediately
    test_private_skill_ancestor_containment
    test_apply_pre_pointer_crash_boundaries
    test_outer_apply_protects_persistent_state_and_rolls_back_restore
    test_outer_apply_post_success_catchable_failures_roll_back_immediately
    test_outer_apply_signals_roll_back_immediately
    test_outer_apply_protects_every_explicit_target
    test_git_publication_activation_target_set
    test_unsupported_apply_target_type_is_rejected
    test_projected_apply_file_modes_are_preserved
    test_apply_projection_catchable_failures_cleanup
    test_apply_rejects_uncontained_flags
    test_apply_preserves_concurrent_live_database_edit
    test_committed_crash_cleanup_and_manifest_binding
    test_visible_conflict_and_absent_symlink_transitions
    test_directory_metadata_only_conflict
    test_final_desired_state_check_retains_conflict
    test_recovery_tears_down_plaintext_before_encrypted_state
    test_outer_capability_binds_nested_finalization
    test_directory_snapshot_tree_contract
    ;;
  *) fail "unknown test: $1" ;;
esac
