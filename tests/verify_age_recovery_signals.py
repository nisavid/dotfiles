import sys
import unittest

from tests.test_age_admission_recovery_preimage import RecoveryPreimageTests

NAMES = (
    "test_caught_signal_records_interruption_and_leaves_no_ready_file",
    "test_signal_during_process_spawn_is_honored_after_registration",
    "test_repeated_signals_keep_first_status_and_do_not_extend_retirement",
    "test_oversized_github_capture_is_bounded_and_leaves_no_ready_file",
    "test_uncertain_group_retirement_is_a_retained_failure",
    "test_transient_group_eperm_does_not_abort_verified_retirement",
    "test_normal_leader_exit_with_resistant_descendant_fails_after_retirement",
)
for iteration in range(1, 21):
    print(f"Darwin retirement verification {iteration}/20", flush=True)
    suite = unittest.TestSuite(RecoveryPreimageTests(name) for name in NAMES)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped:
        sys.exit(1)
print("All 140 Darwin retirement cases passed; none skipped.", flush=True)
