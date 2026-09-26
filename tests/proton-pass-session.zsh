#!/usr/bin/env zsh
set -euo pipefail
# The readiness helper rejects group- or world-writable commands, so fixtures
# must not inherit a permissive caller umask such as a user-private-group 002.
umask 022

repo_root=${0:A:h:h}
ensure_ready_source=${PROTON_PASS_ENSURE_READY_SOURCE:-$repo_root/home/private_dot_local/bin/executable_proton-pass-ensure-ready}
session_compatibility_source=$repo_root/home/private_dot_local/bin/executable_proton-pass-session
native_store_adapter_source=$repo_root/home/private_dot_local/bin/executable_secret-exec-native-store
proton_bootstrap_field=PROTON_PASS_PERSONAL_ACCESS
proton_bootstrap_field+=_TOKEN

# exit, not return: errexit inside a function skips zsh's EXIT trap.
fail() {
  print -u2 -r -- "$1"
  exit 1
}

process_fixture_helper=$repo_root/tests/helpers/process-fixture.zsh
[[ -r $process_fixture_helper ]] ||
  fail 'the shared process-fixture helper is required'
source "$process_fixture_helper"
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/proton-pass-session.XXXXXX")
test_process_fixture_init "$test_dir" || fail 'could not initialize process-fixture cleanup'
trap test_process_fixture_cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
# Build both roots here: the checkout itself may live under TMPDIR, as it does
# on Buildkite's GitHub Actions runner.
containment_dir=$test_dir/containment
mkdir -p -- "$containment_dir/temporary-root" "$containment_dir/outside"
if TMPDIR=$containment_dir/temporary-root /bin/zsh -f -c '
  source "$1"
  test_process_fixture_init "$2"
' -- "$process_fixture_helper" "$containment_dir/outside"; then
  fail 'the process-fixture helper must reject recursive cleanup outside the temporary root'
fi
cleanup_diagnostic=$test_dir/cleanup-diagnostic
: > "$cleanup_diagnostic"
set +e
/bin/zsh -f -c '
  source_text=$(<"$1")
  source_text=${source_text%$'"'"'\nmain "$@"'"'"'}
  eval "$source_text"
  trap - EXIT HUP INT TERM
  PROTON_PASS_DIAGNOSTIC_FILE=$2
  terminate_active_child() { exit 93 }
  cleanup_readiness_process
' -- "$ensure_ready_source" "$cleanup_diagnostic"
cleanup_diagnostic_status=$?
set -e
(( cleanup_diagnostic_status == 93 )) ||
  fail 'the cleanup-order fixture must stop inside child teardown'
[[ ! -e $cleanup_diagnostic ]] ||
  fail 'readiness cleanup must remove captured diagnostics before child teardown'

escape_diagnostic=$test_dir/escape-diagnostic
: > "$escape_diagnostic"
set +e
/bin/zsh -f -c '
  source_text=$(<"$1")
  source_text=${source_text%$'"'"'\nmain "$@"'"'"'}
  eval "$source_text"
  trap - EXIT HUP INT TERM
  PROTON_PASS_DIAGNOSTIC_FILE=$2
  escape_unmanageable_child fixture
' -- "$ensure_ready_source" "$escape_diagnostic" >/dev/null 2>&1
escape_diagnostic_status=$?
set -e
(( escape_diagnostic_status == 1 )) ||
  fail 'the escape-order fixture must use its non-returning failure path'
[[ ! -e $escape_diagnostic ]] ||
  fail 'every non-returning child escape must remove captured diagnostics first'

status_allowlist_state=$test_dir/status-allowlist-state
status_allowlist_log=$test_dir/status-allowlist.log
mkdir -p -- "$status_allowlist_state"
/bin/zsh -f -c '
  source_text=$(<"$1")
  source_text=${source_text%$'"'"'\nmain "$@"'"'"'}
  eval "$source_text"
  trap - EXIT HUP INT TERM
  XDG_STATE_HOME=$2
  status_file=$XDG_STATE_HOME/secret-exec/proton-pass-readiness.status
  for reason in \
    existing-session concurrent-repair repaired \
    unsafe-lock lock-timeout concurrent-repair-failed \
    session-probe-timeout session-state-unknown \
    native-store-timeout native-store-unavailable invalid-bootstrap-value \
    logout-timeout logout-failed login-timeout login-failed \
    login-already-authenticated login-token-rejected \
    login-token-malformed login-session-refused \
    verify-timeout verify-failed login-marker-failed \
    bogus-reason $'"'"'login-failed\nreason=repaired'"'"'; do
    write_status unavailable "$reason" unrecorded
    while IFS= read -r status_line; do
      [[ $status_line != reason=* ]] || print -r -- "${status_line#reason=}"
    done < "$status_file"
  done
  write_status bogus-state repaired unrecorded
  while IFS= read -r status_line; do
    [[ $status_line != state=* ]] || print -r -- "${status_line#state=}"
  done < "$status_file"
' -- "$ensure_ready_source" "$status_allowlist_state" >"$status_allowlist_log"
[[ $(<"$status_allowlist_log") == $'existing-session\nconcurrent-repair\nrepaired\nunsafe-lock\nlock-timeout\nconcurrent-repair-failed\nsession-probe-timeout\nsession-state-unknown\nnative-store-timeout\nnative-store-unavailable\ninvalid-bootstrap-value\nlogout-timeout\nlogout-failed\nlogin-timeout\nlogin-failed\nlogin-already-authenticated\nlogin-token-rejected\nlogin-token-malformed\nlogin-session-refused\nverify-timeout\nverify-failed\nlogin-marker-failed\nunrecorded\nunrecorded\nunavailable' ]] ||
  fail "readiness status must admit only enumerated states and reasons: $(<"$status_allowlist_log")"

# A specific failure stays visible after later generic outcomes and ready
# writes; only enumerated values carry over from the previous file.
last_failure_state=$test_dir/last-failure-state
last_failure_log=$test_dir/last-failure.log
mkdir -p -- "$last_failure_state"
/bin/zsh -f -c '
  source_text=$(<"$1")
  source_text=${source_text%$'"'"'\nmain "$@"'"'"'}
  eval "$source_text"
  trap - EXIT HUP INT TERM
  XDG_STATE_HOME=$2
  status_file=$XDG_STATE_HOME/secret-exec/proton-pass-readiness.status
  record_last_failure() {
    local line reason=none at=none
    while IFS= read -r line; do
      case $line in
        last-failure-reason=*) reason=${line#*=} ;;
        last-failure-at=*) at=${line#*=} ;;
      esac
    done < "$status_file"
    [[ $at == none || $at == <-> ]] || at=invalid
    [[ $at == none || $at == invalid ]] || at=digits
    print -r -- "$1 $reason $at"
  }
  write_status unavailable session-probe-timeout unrecorded
  record_last_failure generic-first
  write_status unavailable login-token-rejected child-status
  record_last_failure specific
  first_at=$(grep "^last-failure-at=" "$status_file")
  write_status unavailable session-probe-timeout unrecorded
  record_last_failure generic-after
  write_status ready repaired unrecorded
  record_last_failure ready-after
  [[ $(grep "^last-failure-at=" "$status_file") == "$first_at" ]] ||
    print -r -- "timestamp-changed"
  write_status unavailable logout-failed child-status
  record_last_failure replaced
  write_status unavailable lock-timeout unrecorded
  record_last_failure lock-timeout-after
  print -rl -- state=unavailable reason=lock-timeout \
    last-failure-reason=bogus-reason last-failure-at=12 >"$status_file"
  write_status unavailable session-state-unknown unrecorded
  record_last_failure bogus-reason-dropped
  print -rl -- state=unavailable reason=lock-timeout \
    last-failure-reason=login-failed "last-failure-at=12 34" >"$status_file"
  write_status unavailable session-state-unknown unrecorded
  record_last_failure bogus-time-dropped
' -- "$ensure_ready_source" "$last_failure_state" >"$last_failure_log"
[[ $(<"$last_failure_log") == $'generic-first none none\nspecific login-token-rejected digits\ngeneric-after login-token-rejected digits\nready-after login-token-rejected digits\nreplaced logout-failed digits\nlock-timeout-after logout-failed digits\nbogus-reason-dropped none none\nbogus-time-dropped none none' ]] ||
  fail "readiness status must keep the latest specific failure: $(<"$last_failure_log")"

survivor_probe_root=$test_dir/survivor-probe
survivor_probe_error=$test_dir/survivor-probe.err
mkdir -p -- "$survivor_probe_root"
if /bin/zsh -f -c '
  source "$1"
  test_process_fixture_init "$2" || exit
  kill() { return 0 }
  zselect() { return 0 }
  test_process_fixture_track_pid 2147483646 || exit
  trap test_process_fixture_cleanup EXIT
  exit 0
' -- "$process_fixture_helper" "$survivor_probe_root" 2>"$survivor_probe_error"; then
  fail 'EXIT cleanup must fail when a tracked process survives'
fi
[[ $(<"$survivor_probe_error") ==
  'process fixture: tracked PID 2147483646 survived cleanup' ]] ||
  fail 'the process-fixture helper must identify each surviving tracked process'
cleanup_temp_root=$test_dir/cleanup-temp
cleanup_registered_root=$cleanup_temp_root/registered
cleanup_outside_root=$test_dir/cleanup-outside
cleanup_outside_canary=$cleanup_outside_root/canary
cleanup_recheck_error=$test_dir/cleanup-recheck.err
mkdir -p -- "$cleanup_registered_root" "$cleanup_outside_root"
: > "$cleanup_outside_canary"
if TMPDIR=$cleanup_temp_root /bin/zsh -f -c '
  source "$1"
  test_process_fixture_init "$2"
' -- "$process_fixture_helper" "$cleanup_outside_root"; then
  fail 'the process-fixture helper must reject recursive cleanup outside the temporary root'
fi
set +e
TMPDIR=$cleanup_temp_root /bin/zsh -f -c '
  source "$1"
  test_process_fixture_init "$2" || exit
  TEST_PROCESS_FIXTURE_ROOT=$3
  test_process_fixture_cleanup
' -- "$process_fixture_helper" "$cleanup_registered_root" \
  "$cleanup_outside_root" 2>"$cleanup_recheck_error"
cleanup_recheck_status=$?
set -e
(( cleanup_recheck_status == 1 )) ||
  fail 'EXIT cleanup must fail when its registered root leaves the temporary root'
[[ -e $cleanup_outside_canary ]] ||
  fail 'EXIT cleanup must preserve data outside the temporary root'
[[ $(<"$cleanup_recheck_error") ==
  'process fixture: refusing recursive cleanup outside the temporary root' ]] ||
  fail 'EXIT cleanup must report a refused recursive deletion'
test_process_fixture_run_signal_probe_mode
kill_audit_library=
kill_audit_log=$test_dir/negative-pgid-kill-audit.log
status_fragment_library=
status_fragment_log=$test_dir/zpty-status-fragment.log
status_fragment_delay_log=$test_dir/zpty-status-fragment-delay.log
status_fragment_deadline_log=$test_dir/zpty-status-fragment-deadline.log
transient_liveness_log=$test_dir/zpty-transient-liveness.log
identity_loss_log=$test_dir/zpty-identity-loss.log
if [[ $OSTYPE == linux* ]]; then
  [[ -x /usr/bin/cc ]] || fail 'the Linux cleanup-identity test requires /usr/bin/cc'
  kill_audit_library=$test_dir/negative-pgid-kill-audit.so
  /usr/bin/cc -shared -fPIC -O2 -Wall -Wextra -Werror \
    -o "$kill_audit_library" \
    "$repo_root/tests/fixtures/negative-pgid-kill-audit.c" -ldl
  set +e
  NEGATIVE_PGID_KILL_AUDIT_LOG=$test_dir/missing/audit.log \
    LD_PRELOAD=$kill_audit_library \
    /bin/zsh -f -c '
      kill -0 -- -2147483647 2>/dev/null || true
      kill -TERM -- -2147483647 2>/dev/null || true
    '
  kill_audit_failure_status=$?
  set -e
  (( kill_audit_failure_status == 125 )) ||
    fail 'the stale-identity audit must fail closed when its log cannot be opened'
  status_fragment_library=$test_dir/zpty-status-fragment.so
  /usr/bin/cc -shared -fPIC -O2 -Wall -Wextra -Werror \
    -o "$status_fragment_library" \
    "$repo_root/tests/fixtures/zpty-status-fragment.c" -ldl
fi

test_process_fixture_assert_signal_cleanup \
  "${0:A}" TERM 143 "$test_dir/cleanup-term" ||
  fail 'the TERM cleanup contract must terminate fixtures and preserve status'
fake_bin=$test_dir/bin
fixture_home=$test_dir/home
state_home=$test_dir/state
fixture_local_bin=$fixture_home/.local/bin
mkdir -p -- "$fake_bin" "$fixture_local_bin" "$state_home"

ensure_ready=$fixture_local_bin/proton-pass-ensure-ready
session_compatibility=$fixture_local_bin/proton-pass-session
native_store_adapter=$fixture_local_bin/secret-exec-native-store
production_native_store_adapter=$test_dir/secret-exec-native-store
cp "$ensure_ready_source" "$ensure_ready"
cp "$session_compatibility_source" "$session_compatibility"
cp "$native_store_adapter_source" "$production_native_store_adapter"
chmod +x "$ensure_ready" "$session_compatibility" \
  "$production_native_store_adapter"

path_backend_home=$test_dir/path-backend-home
path_backend_state=$test_dir/path-backend-state
homebrew_prefix=$test_dir/homebrew
homebrew_cellar_bin=$homebrew_prefix/Cellar/proton-pass-cli/2.3.2/bin
path_backend_log=$test_dir/path-backend.log
mkdir -p -- "$path_backend_home" "$path_backend_state" \
  "$homebrew_prefix/bin" "$homebrew_cellar_bin"
cat >"$homebrew_cellar_bin/pass-cli" <<'EOF'
#!/bin/zsh -f
set -euo pipefail

[[ $* == info ]] || exit 64
[[ ${PROTON_PASS_NO_UPDATE_CHECK:-} == 1 ]] || exit 65
print -r -- info >>"$PROTON_PASS_PATH_BACKEND_LOG"
EOF
chmod 755 "$homebrew_cellar_bin/pass-cli"
ln -s ../Cellar/proton-pass-cli/2.3.2/bin/pass-cli \
  "$homebrew_prefix/bin/pass-cli"
PROTON_PASS_PATH_BACKEND_LOG=$path_backend_log \
  PATH=$homebrew_cellar_bin:/usr/bin:/bin \
  HOME=$path_backend_home XDG_STATE_HOME=$path_backend_state \
  zsh "$ensure_ready"
[[ $(<"$path_backend_log") == info ]] ||
  fail 'readiness must invoke the regular pass-cli selected through PATH'
: >"$path_backend_log"
PROTON_PASS_PATH_BACKEND_LOG=$path_backend_log \
  PATH=$homebrew_prefix/bin:/usr/bin:/bin \
  HOME=$path_backend_home XDG_STATE_HOME=$path_backend_state \
  zsh "$ensure_ready"
[[ $(<"$path_backend_log") == info ]] ||
  fail 'readiness must invoke the Homebrew-style symlink selected through PATH'

: >"$path_backend_log"
(
  cd "$path_backend_home"
  PROTON_PASS_PATH_BACKEND_LOG=$path_backend_log \
    PATH=:$homebrew_prefix/bin:/usr/bin:/bin \
    HOME=$path_backend_home XDG_STATE_HOME=$path_backend_state \
    "$ensure_ready"
)
[[ $(<"$path_backend_log") == info ]] ||
  fail 'an empty PATH component without pass-cli must preserve later ordinary lookup'

relative_path_cwd=$test_dir/relative-pass-cli-cwd
relative_path_bin=$relative_path_cwd/relative-bin
mkdir -p -- "$relative_path_cwd" "$relative_path_bin"
cp -- "$homebrew_cellar_bin/pass-cli" "$relative_path_cwd/pass-cli"
cp -- "$homebrew_cellar_bin/pass-cli" "$relative_path_bin/pass-cli"
: >"$path_backend_log"
for relative_path_prefix in '' . relative-bin; do
  (
    cd "$relative_path_cwd"
    PROTON_PASS_PATH_BACKEND_LOG=$path_backend_log \
      PATH=$relative_path_prefix:/usr/bin:/bin \
      HOME=$path_backend_home XDG_STATE_HOME=$path_backend_state \
      "$ensure_ready"
  )
done
[[ $(grep -Fxc info "$path_backend_log") == 3 ]] ||
  fail 'readiness must preserve ordinary relative pass-cli PATH selections'

fast_exit=
for fast_exit_candidate in /usr/bin/true /bin/true; do
  if [[ -x $fast_exit_candidate ]]; then
    fast_exit=$fast_exit_candidate
    break
  fi
done
[[ -n $fast_exit ]] || fail 'a fixed true executable is required'
fast_backend_home=$test_dir/fast-backend-home
fast_backend_state=$test_dir/fast-backend-state
mkdir -p -- "$fast_backend_home/.local/bin" "$fast_backend_state"
cat >"$fast_backend_home/.local/bin/pass-cli" <<'EOF'
#!/bin/zsh -f
set -euo pipefail
[[ -z ${PROVIDER_START_MARKER:-} ]] ||
  print -r -- provider-started >>"$PROVIDER_START_MARKER"
[[ -z ${PROVIDER_COMPLETION_DELAY:-} ]] || /bin/sleep 0.2
[[ -z ${PROVIDER_COMPLETION_MARKER:-} ]] ||
  print -r -- provider-completed >>"$PROVIDER_COMPLETION_MARKER"
EOF
chmod 700 "$fast_backend_home/.local/bin/pass-cli"
fast_backend_path=$fast_backend_home/.local/bin:/usr/bin:/bin
if [[ -n $status_fragment_library ]]; then
  typeset identity_loss_output identity_listing identity_controller
  integer identity_loss_status
  identity_loss_gate=$test_dir/zpty-initial-identity-loss.gate
  identity_loss_output_file=$test_dir/zpty-initial-identity-loss.out
  rm -f -- "$identity_loss_log" "$identity_loss_gate" "$identity_loss_output_file" "$kill_audit_log"
  /usr/bin/env \
    LD_PRELOAD="$status_fragment_library:$kill_audit_library" \
    ZPTY_IDENTITY_LOSS_AUDIT_LOG=$identity_loss_log \
    ZPTY_INITIAL_IDENTITY_LOSS_GATE=$identity_loss_gate \
    NEGATIVE_PGID_KILL_AUDIT_LOG=$kill_audit_log \
    PATH=$fast_backend_path HOME=$fast_backend_home XDG_STATE_HOME=$fast_backend_state \
    ZPTY_INITIAL_IDENTITY_LOSS=1 \
    "$ensure_ready" >"$identity_loss_output_file" 2>&1 &
  identity_wrapper_pid=$!
  test_process_fixture_track_pid $identity_wrapper_pid
  integer identity_marker_polls=100
  while (( identity_marker_polls-- > 0 )) && [[ ! -s $identity_loss_log ]]; do
    zselect -t 1 2>/dev/null || true
  done
  [[ -s $identity_loss_log ]] || fail 'initial readiness identity fixture must publish its controller'
  identity_loss_record=$(<"$identity_loss_log")
  typeset -a identity_lines=( "${(@f)identity_loss_record}" )
  identity_controller=${identity_lines[1]#controller:}
  [[ $identity_controller == <-> && $identity_controller -gt 1 ]] ||
    fail 'initial readiness identity fixture must publish a numeric controller'
  identity_listing=$(/bin/ps -o pid=,ppid=,pgid=,sid= -p $identity_controller)
  typeset -a identity_fields=( ${=identity_listing} )
  (( ${#identity_fields} == 4 && identity_fields[1] == identity_controller &&
    identity_fields[2] == identity_wrapper_pid && identity_fields[3] == identity_controller &&
    identity_fields[4] == identity_controller )) ||
    fail 'initial readiness controller must be the wrapper child and its session leader'
  kill -KILL -- -$identity_controller
  : >"$identity_loss_gate"
  set +e
  wait $identity_wrapper_pid
  identity_loss_status=$?
  set -e
  test_process_fixture_untrack_pid $identity_wrapper_pid
  ! kill -0 -- -$identity_controller 2>/dev/null || fail 'initial readiness controller group must become absent'
  identity_loss_output=$(<"$identity_loss_output_file")
  (( identity_loss_status == 1 )) || fail 'initial identity loss must fail readiness closed'
  [[ $identity_loss_output == 'proton-pass-ensure-ready: cannot identify bounded credential process group' ]] ||
    fail 'initial identity loss must preserve its fixed readiness diagnostic'
  [[ $(<"$identity_loss_log") == $'controller:'$identity_controller$'\ninitial-identity-loss' ]] ||
    fail 'initial readiness identity fixture must prove pre-publication controller loss'
  [[ ! -s $kill_audit_log ]] || fail 'initial readiness identity loss must not signal an absent process group'

  rm -f -- "$identity_loss_log" "$kill_audit_log"
  set +e
  identity_loss_output=$(/usr/bin/env LD_PRELOAD="$status_fragment_library:$kill_audit_library" \
    ZPTY_IDENTITY_LOSS_AUDIT_LOG=$identity_loss_log NEGATIVE_PGID_KILL_AUDIT_LOG=$kill_audit_log \
    PATH=$fast_backend_path HOME=$fast_backend_home XDG_STATE_HOME=$fast_backend_state ZPTY_POST_ACTIVE_IDENTITY_LOSS=1 \
    "$ensure_ready" 2>&1)
  identity_loss_status=$?
  set -e
  (( identity_loss_status == 1 )) || fail 'post-active identity loss must fail readiness closed'
  [[ $identity_loss_output == 'proton-pass-ensure-ready: bounded credential child became unmanageable' ]] ||
    fail 'post-active identity loss must produce one fixed readiness diagnostic'
  [[ $(<"$identity_loss_log") == post-active-identity-loss ]] || fail 'post-active identity fixture must prove controller loss'
  [[ ! -s $kill_audit_log ]] || fail 'post-active readiness identity loss must not signal an absent process group'

  provider_start_marker=$test_dir/transient-ready-provider-started
  provider_completion_marker=$test_dir/transient-ready-provider-completed
  rm -f -- "$transient_liveness_log" "$provider_start_marker" \
    "$provider_completion_marker" "$kill_audit_log"
  set +e
  LD_PRELOAD="$status_fragment_library:$kill_audit_library" \
    ZPTY_TRANSIENT_LIVENESS_PROBE=1 \
    ZPTY_TRANSIENT_LIVENESS_AUDIT_LOG=$transient_liveness_log \
    NEGATIVE_PGID_KILL_AUDIT_LOG=$kill_audit_log \
    PROVIDER_START_MARKER=$provider_start_marker \
    PROVIDER_COMPLETION_MARKER=$provider_completion_marker \
    PROVIDER_COMPLETION_DELAY=1 \
    PATH=$fast_backend_path HOME=$fast_backend_home XDG_STATE_HOME=$fast_backend_state \
    "$ensure_ready" >/dev/null 2>"$test_dir/transient-ready.err"
  transient_ready_status=$?
  set -e
  (( transient_ready_status == 0 )) ||
    fail "readiness must retry one transient live-group probe: status=$transient_ready_status error=$(<"$test_dir/transient-ready.err")"
  [[ $(<"$transient_liveness_log") == \
    $'start-gate\nlive-before-esrch\ninjected-esrch\nrecovered-live' ]] ||
    fail 'the readiness liveness fixture must prove one live ESRCH and recovery'
  [[ $(<"$provider_start_marker") == provider-started &&
    $(<"$provider_completion_marker") == provider-completed ]] ||
    fail 'readiness must complete exactly one provider after the transient probe'
  [[ ! -s $kill_audit_log ]] ||
    fail 'readiness transient-probe recovery must not signal a stale group'

  provider_completion_marker=$test_dir/fragmented-ready-provider-completed
  rm -f -- "$status_fragment_log" "$status_fragment_delay_log" \
    "$provider_completion_marker"
  set +e
  LD_PRELOAD=$status_fragment_library \
    ZPTY_STATUS_FRAGMENT_AUDIT_LOG=$status_fragment_log \
    ZPTY_STATUS_FRAGMENT_DELAY_TAIL=1 \
    ZPTY_STATUS_FRAGMENT_DELAY_AUDIT_LOG=$status_fragment_delay_log \
    PROVIDER_COMPLETION_MARKER=$provider_completion_marker \
    PATH=$fast_backend_path HOME=$fast_backend_home XDG_STATE_HOME=$fast_backend_state \
    "$ensure_ready" >/dev/null 2>"$test_dir/fragmented-ready.err"
  fragmented_ready_status=$?
  set -e
  (( fragmented_ready_status == 0 )) ||
    fail "readiness must accept a fragmented successful child-status record: status=$fragmented_ready_status error=$(<"$test_dir/fragmented-ready.err")"
  [[ $(<"$status_fragment_log") == fragmented-status ]] ||
    fail 'the PTY status-read fixture must prove that it fragmented a record'
  [[ $(<"$provider_completion_marker") == provider-completed ]] ||
    fail 'the fragmented readiness fixture must prove one provider completion'
  [[ $(<"$status_fragment_delay_log") == \
    $'delay-armed\nforced-yields-complete\ndelayed-tail' ]] ||
    fail 'the readiness PTY fixture must prove the forced-yield and 160 ms status-tail delay'

  rm -f -- "$status_fragment_log" "$status_fragment_deadline_log"
  set +e
  LD_PRELOAD=$status_fragment_library \
    ZPTY_STATUS_FRAGMENT_AUDIT_LOG=$status_fragment_log \
    ZPTY_STATUS_FRAGMENT_EXPIRE_DEADLINE=1 \
    ZPTY_STATUS_FRAGMENT_DEADLINE_AUDIT_LOG=$status_fragment_deadline_log \
    PATH=$fast_backend_path HOME=$fast_backend_home XDG_STATE_HOME=$fast_backend_state \
    "$ensure_ready" >/dev/null 2>"$test_dir/deadline-ready.err"
  deadline_ready_status=$?
  set -e
  (( deadline_ready_status == 0 )) ||
    fail "readiness must recover after rejecting a post-deadline status tail: status=$deadline_ready_status error=$(<"$test_dir/deadline-ready.err")"
  [[ $(<"$status_fragment_log") == fragmented-status ]] ||
    fail 'the readiness deadline fixture must prove status fragmentation'
  [[ $(<"$status_fragment_deadline_log") == \
    $'deadline-armed\ndeadline-expired' ]] ||
    fail 'readiness must not read a fragmented status tail after its deadline'

  rm -f -- "$status_fragment_log" "$kill_audit_log"
  zmodload zsh/zselect || fail 'the signal fixture requires zsh/zselect'
  set +e
  LD_PRELOAD="$status_fragment_library:$kill_audit_library" \
    ZPTY_STATUS_FRAGMENT_AUDIT_LOG=$status_fragment_log \
    ZPTY_STATUS_FRAGMENT_PAUSE=1 \
    NEGATIVE_PGID_KILL_AUDIT_LOG=$kill_audit_log \
    PATH=$fast_backend_path HOME=$fast_backend_home XDG_STATE_HOME=$fast_backend_state \
    "$ensure_ready" >"$test_dir/fragment-signal.out" \
      2>"$test_dir/fragment-signal.err" &
  fragmented_readiness_pid=$!
  test_process_fixture_track_pid $fragmented_readiness_pid
  integer fragment_marker_polls=100
  while (( fragment_marker_polls-- > 0 )) && [[ ! -s $status_fragment_log ]]; do
    zselect -t 1 2>/dev/null || true
  done
  if [[ ! -s $status_fragment_log ]]; then
    kill -KILL $fragmented_readiness_pid 2>/dev/null || true
    wait $fragmented_readiness_pid 2>/dev/null || true
    test_process_fixture_untrack_pid $fragmented_readiness_pid
    set -e
    fail 'readiness must reach the fragmented post-exit status window'
  fi
  kill -TERM $fragmented_readiness_pid 2>/dev/null || true
  wait $fragmented_readiness_pid
  fragmented_signal_status=$?
  test_process_fixture_untrack_pid $fragmented_readiness_pid
  set -e
  (( fragmented_signal_status == 143 )) ||
    fail 'TERM during fragmented post-exit status parsing must retain status 143'
  [[ $(<"$status_fragment_log") == fragmented-status ]] ||
    fail 'the signal fixture must prove that it reached a fragmented status record'
  [[ ! -s $kill_audit_log ]] ||
    fail 'post-exit status parsing must not signal an absent process group'
fi

integer fast_backend_run
for (( fast_backend_run = 1; fast_backend_run <= 32; ++fast_backend_run )); do
  PATH=$fast_backend_path HOME=$fast_backend_home XDG_STATE_HOME=$fast_backend_state \
    "$ensure_ready" >/dev/null 2>&1 ||
    fail 'readiness must accept an immediately successful provider backend'
done

hostile_shell_dir=$test_dir/hostile-shell
hostile_zdotdir=$test_dir/hostile-zdotdir
hostile_shell_marker=$test_dir/hostile-shell-ran
hostile_zdotdir_marker=$test_dir/hostile-zdotdir-ran
mkdir -p -- "$hostile_shell_dir" "$hostile_zdotdir"
cat > "$hostile_shell_dir/zsh" <<'EOF'
#!/bin/sh
: > "$HOSTILE_SHELL_MARKER"
exit 90
EOF
chmod +x "$hostile_shell_dir/zsh"
cat > "$hostile_zdotdir/.zshenv" <<'EOF'
: > "$HOSTILE_ZDOTDIR_MARKER"
EOF
export HOSTILE_SHELL_MARKER=$hostile_shell_marker
export HOSTILE_ZDOTDIR_MARKER=$hostile_zdotdir_marker

set +e
direct_output=$(PATH=$hostile_shell_dir:/usr/bin:/bin \
  ZDOTDIR=$test_dir/empty-zdotdir "$ensure_ready" unexpected 2>&1)
direct_status=$?
set -e
(( direct_status == 1 )) ||
  fail 'direct readiness execution must use the fixed system zsh'
[[ $direct_output ==
  'proton-pass-ensure-ready: this operation takes no arguments' ]] ||
  fail 'direct readiness execution must preserve its argument error'
[[ ! -e $hostile_shell_marker ]] ||
  fail 'direct readiness execution must ignore a PATH-selected zsh'

set +e
direct_output=$(PATH=/usr/bin:/bin ZDOTDIR=$hostile_zdotdir \
  "$ensure_ready" unexpected 2>&1)
direct_status=$?
set -e
(( direct_status == 1 )) ||
  fail 'direct readiness execution must disable zsh startup files'
[[ $direct_output ==
  'proton-pass-ensure-ready: this operation takes no arguments' ]] ||
  fail 'direct readiness execution must preserve its argument error'
[[ ! -e $hostile_zdotdir_marker ]] ||
  fail 'direct readiness execution must ignore a hostile ZDOTDIR'

rm -f -- "$hostile_shell_marker" "$hostile_zdotdir_marker"
set +e
direct_output=$(PATH=$hostile_shell_dir:/usr/bin:/bin \
  ZDOTDIR=$test_dir/empty-zdotdir "$session_compatibility" unexpected 2>&1)
direct_status=$?
set -e
(( direct_status == 1 )) ||
  fail 'direct compatibility execution must use the fixed system zsh'
[[ $direct_output ==
  'proton-pass-ensure-ready: this operation takes no arguments' ]] ||
  fail 'direct compatibility execution must preserve the readiness argument error'
[[ ! -e $hostile_shell_marker ]] ||
  fail 'direct compatibility execution must ignore a PATH-selected zsh'

set +e
direct_output=$(PATH=/usr/bin:/bin ZDOTDIR=$hostile_zdotdir \
  "$session_compatibility" unexpected 2>&1)
direct_status=$?
set -e
(( direct_status == 1 )) ||
  fail 'direct compatibility execution must disable zsh startup files'
[[ $direct_output ==
  'proton-pass-ensure-ready: this operation takes no arguments' ]] ||
  fail 'direct compatibility execution must preserve the readiness argument error'
[[ ! -e $hostile_zdotdir_marker ]] ||
  fail 'direct compatibility execution must ignore a hostile ZDOTDIR'

rm -f -- "$hostile_shell_marker" "$hostile_zdotdir_marker"
set +e
direct_output=$(PATH=$hostile_shell_dir:/usr/bin:/bin \
  ZDOTDIR=$test_dir/empty-zdotdir \
  "$production_native_store_adapter" unexpected 2>&1)
direct_status=$?
set -e
(( direct_status == 1 )) ||
  fail 'direct native-store adapter execution must use the fixed system zsh'
[[ $direct_output ==
  'secret-exec-native-store: usage: secret-exec-native-store proton-bootstrap | lookup <profile> <name>' ]] ||
  fail 'direct native-store adapter execution must preserve its usage error'
[[ ! -e $hostile_shell_marker ]] ||
  fail 'direct native-store adapter execution must ignore a PATH-selected zsh'

set +e
direct_output=$(PATH=/usr/bin:/bin ZDOTDIR=$hostile_zdotdir \
  "$production_native_store_adapter" unexpected 2>&1)
direct_status=$?
set -e
(( direct_status == 1 )) ||
  fail 'direct native-store adapter execution must disable zsh startup files'
[[ $direct_output ==
  'secret-exec-native-store: usage: secret-exec-native-store proton-bootstrap | lookup <profile> <name>' ]] ||
  fail 'direct native-store adapter execution with hostile ZDOTDIR must preserve its usage error'
[[ ! -e $hostile_zdotdir_marker ]] ||
  fail 'direct native-store adapter execution must ignore a hostile ZDOTDIR'

cat > "$fixture_local_bin/pass-cli" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

(( ! ${+PROTON_PASS_LAST_WAITER_STAGE} )) || exit 72
(( ! ${+PROTON_PASS_DIAGNOSTIC_TEXT} && ! ${+PROTON_PASS_DIAGNOSTIC_FILE} &&
  ! ${+PROTON_PASS_DIAGNOSTIC_WRITE_FD} && ! ${+PROTON_PASS_DIAGNOSTIC_READ_FD} )) ||
  exit 72
print -r -- "$*" >> "$FAKE_PASS_LOG"
fixture_token=pst_
fixture_token+='fixture-token'
fixture_token+='::fixture-key'
bootstrap_field=PROTON_PASS_PERSONAL_ACCESS
bootstrap_field+=_TOKEN
hang_forever() {
  print -r -- $$ > "$FAKE_HANGING_CHILD_PID"
  [[ -z ${FAKE_HANGING_CHILD_PIDS:-} ]] ||
    print -r -- $$ >> "$FAKE_HANGING_CHILD_PIDS"
  zmodload zsh/zselect
  trap 'exit 143' TERM
  while true; do
    zselect -t 10 || true
  done
}
spawn_resistant_descendant() {
  (
    zmodload zsh/system
    zmodload zsh/zselect
    trap '' HUP TERM
    if [[ -n ${FAKE_DESCENDANT_TOKEN_MARKER:-} &&
      ${${(P)bootstrap_field}:-} == $fixture_token ]]; then
      : > "$FAKE_DESCENDANT_TOKEN_MARKER"
    fi
    print -r -- "$sysparams[pid]" > "$FAKE_DESCENDANT_PID"
    while true; do
      zselect -t 10 || true
    done
  ) &!
  zmodload zsh/zselect
  while [[ ! -s $FAKE_DESCENDANT_PID ]]; do
    zselect -t 1 || true
  done
}
plain_main_record() {
  print -r -- "$1 ERROR pass-cli/src/main.rs:$2: $3"
}
ansi_main_record() {
  local timestamp=$1
  local line_number=$2
  local message=$3
  local record=$'\e[2m'"$timestamp"$'\e[0m '
  record+=$'\e[31mERROR\e[0m '
  record+=$'\e[2mpass-cli/src/main.rs\e[0m'
  record+=$'\e[2m:\e[0m\e[2m'"${line_number}:"$'\e[0m '"$message"
  print -r -- "$record"
}
ansi_split_line_colon_record() {
  local line_number=$2
  local record=$(ansi_main_record "$@")
  record=${record/"${line_number}:"$'\e[0m '/"$line_number"$'\e[0m: '}
  print -r -- "$record"
}
print_nul_terminated_record() {
  print -u2 -nr -- "$1"$'\0\n'
}
fixture_timestamp='2026-08-25T07:13:16.037584Z'
alternate_timestamp='2026-08-25T07:13:16.037585Z'
absent_message='Command is not logout there is no session'
alternate_absent_message='Session is some but is not logged in'
invalidated_message='Session invalidated'
absent_diagnostic='Error: This operation requires an authenticated client'
invalidated_diagnostic='Your session has been invalidated and you have been logged out automatically.'
invalidated_guidance='Please log in again with: pass login'
plain_absent_record=$(plain_main_record "$fixture_timestamp" 332 "$absent_message")
plain_alternate_absent_record=$(
  plain_main_record "$alternate_timestamp" 333 "$alternate_absent_message"
)
plain_invalidated_record=$(plain_main_record "$fixture_timestamp" 231 "$invalidated_message")
plain_second_invalidated_record=$(
  plain_main_record "$alternate_timestamp" 232 "$invalidated_message"
)
ansi_absent_record=$(ansi_main_record "$fixture_timestamp" 332 "$absent_message")
ansi_alternate_absent_record=$(
  ansi_main_record "$alternate_timestamp" 333 "$alternate_absent_message"
)
ansi_invalidated_record=$(ansi_main_record "$fixture_timestamp" 231 "$invalidated_message")
ansi_second_invalidated_record=$(
  ansi_main_record "$alternate_timestamp" 232 "$invalidated_message"
)
orphaned_cause_lines=(
  'Caused by:'
  '    0: Error sending request'
  '    1: failed to authenticate: non-existent session'
  '    2: non-existent session'
)
orphaned_diagnostic_lines=(
  'Error: Error getting personal access token name'
  ''
  "${orphaned_cause_lines[@]}"
)
case $1 in
  info)
    (( $# == 1 )) || exit 64
    [[ ${PROTON_PASS_NO_UPDATE_CHECK:-} == 1 ]] || exit 69
    [[ -z ${${(P)bootstrap_field}:-} ]] || exit 70
    [[ ${PROTON_PASS_DISABLE_TELEMETRY:-} == 1 ]] || exit 80
    if [[ -n ${FAKE_PASS_INFO_EXIT_LOG:-} ]]; then
      zmodload zsh/datetime
      trap 'print -r -- "$EPOCHREALTIME" >> "$FAKE_PASS_INFO_EXIT_LOG"' EXIT
    fi
    # These holds end by wall-clock time, not a poll count: a loaded runner
    # can stretch every short sleep, and a counted hold could then outlast the
    # helper's deadline for this check.
    # Hold this check, well inside its three-second deadline, until a second
    # check also runs, and record whether one did.
    if [[ -n ${FAKE_PASS_INFO_BARRIER:-} ]]; then
      zmodload zsh/datetime
      zmodload zsh/zselect
      : > "$FAKE_PASS_INFO_BARRIER/$$"
      typeset -F barrier_deadline=$(( EPOCHREALTIME + 2 ))
      barrier_arrivals=( "$FAKE_PASS_INFO_BARRIER"/<->(N) )
      while (( EPOCHREALTIME < barrier_deadline && ${#barrier_arrivals} < 2 )); do
        zselect -t 1 || true
        barrier_arrivals=( "$FAKE_PASS_INFO_BARRIER"/<->(N) )
      done
      if (( ${#barrier_arrivals} >= 2 )); then
        print -r -- met >> "$FAKE_PASS_INFO_BARRIER.log"
      else
        print -r -- alone >> "$FAKE_PASS_INFO_BARRIER.log"
      fi
    fi
    # Hold this caller's first check, well inside its three-second deadline,
    # until a concurrent login stores a session, and record whether it did.
    # A check that saw one and has FAKE_PASS_INFO_HOLD_WHILE then waits until
    # that path is gone and reports the session ready, as a check that read
    # it before a repair's cleanup would.
    if [[ -n ${FAKE_PASS_INFO_AWAIT_SESSION_ONCE:-} &&
      ! -e $FAKE_PASS_INFO_AWAIT_SESSION_ONCE ]]; then
      zmodload zsh/datetime
      zmodload zsh/zselect
      typeset -F await_session_deadline=$(( EPOCHREALTIME + 1.5 ))
      while (( EPOCHREALTIME < await_session_deadline )) &&
        [[ ! -e $FAKE_PASS_LOCAL_SESSION || ! -e $FAKE_PASS_REMOTE_SESSION ]]; do
        zselect -t 1 || true
      done
      if [[ -e $FAKE_PASS_LOCAL_SESSION && -e $FAKE_PASS_REMOTE_SESSION ]]; then
        print -r -- seen > "$FAKE_PASS_INFO_AWAIT_SESSION_ONCE"
        if [[ -n ${FAKE_PASS_INFO_HOLD_WHILE:-} ]]; then
          typeset -F hold_deadline=$(( EPOCHREALTIME + 1 ))
          while (( EPOCHREALTIME < hold_deadline )) &&
            [[ -e $FAKE_PASS_INFO_HOLD_WHILE ]]; do
            zselect -t 1 || true
          done
          print -r -- 'account-metadata-canary'
          exit 0
        fi
      else
        print -r -- missed > "$FAKE_PASS_INFO_AWAIT_SESSION_ONCE"
      fi
    fi
    [[ -z ${FAKE_PASS_INFO_DELAY_SECONDS:-} ]] ||
      /bin/sleep "$FAKE_PASS_INFO_DELAY_SECONDS"
    if [[ -e $FAKE_PASS_VERIFY_HANG && -e $FAKE_PASS_REMOTE_SESSION ]]; then
      hang_forever
    fi
    if [[ -e $FAKE_PASS_INFO_HANG && ! -e $FAKE_PASS_REMOTE_SESSION ]]; then
      hang_forever
    fi
    if [[ -e $FAKE_PASS_INFO_TRANSIENT ]]; then
      print -u2 -rl -- \
        '2026-08-25T07:13:16.037584Z ERROR pass-cli/src/features/keyring.rs:203: Keyring unavailable' \
        'Error: This operation requires an authenticated client'
      exit 76
    fi
    if [[ -e $FAKE_PASS_INFO_MALFORMED_FRAMING ]]; then
      case $(<"$FAKE_PASS_INFO_MALFORMED_FRAMING") in
        blank-absent)
          print -u2 -rl -- '' "$absent_diagnostic"
          ;;
        embedded-absent)
          print -u2 -rl -- "$plain_absent_record" '' "$absent_diagnostic"
          ;;
        trailing-absent)
          print -u2 -rl -- "$absent_diagnostic" ''
          ;;
        styled-terminal-absent)
          print -u2 -rl -- \
            "$plain_absent_record" \
            $'\e[31m'"$absent_diagnostic"$'\e[0m'
          ;;
        unsupported-sgr-absent)
          print -u2 -rl -- \
            $'\e[1m'"$plain_absent_record"$'\e[0m' \
            "$absent_diagnostic"
          ;;
        non-sgr-csi-absent)
          print -u2 -rl -- \
            $'\e[31K'"$plain_absent_record" \
            "$absent_diagnostic"
          ;;
        ansi-only-absent)
          print -u2 -rl -- $'\e[2m\e[0m' "$absent_diagnostic"
          ;;
        misplaced-sgr-absent)
          misplaced_absent_record=$(ansi_main_record \
            "$fixture_timestamp" 332 \
            $'Command is not logout there is no \e[2msession\e[0m')
          print -u2 -rl -- \
            "$misplaced_absent_record" "$absent_diagnostic"
          ;;
        trailing-sgr-absent)
          print -u2 -rl -- \
            "$ansi_absent_record"$'\e[0m' "$absent_diagnostic"
          ;;
        split-line-colon-sgr-absent)
          print -u2 -rl -- \
            "$(ansi_split_line_colon_record \
              "$fixture_timestamp" 332 "$absent_message")" \
            "$absent_diagnostic"
          ;;
        mixed-absent)
          print -u2 -rl -- \
            "$plain_absent_record" "$ansi_alternate_absent_record" \
            "$absent_diagnostic"
          ;;
        nul-plain-absent)
          print_nul_terminated_record "$plain_absent_record"
          print -u2 -r -- "$absent_diagnostic"
          ;;
        nul-ansi-absent)
          print_nul_terminated_record "$ansi_absent_record"
          print -u2 -r -- "$absent_diagnostic"
          ;;
        blank-invalidated)
          print -u2 -rl -- '' "$invalidated_diagnostic" "$invalidated_guidance"
          ;;
        embedded-invalidated)
          print -u2 -rl -- \
            "$plain_invalidated_record" '' \
            "$invalidated_diagnostic" "$invalidated_guidance"
          ;;
        trailing-invalidated)
          print -u2 -rl -- \
            "$invalidated_diagnostic" "$invalidated_guidance" ''
          ;;
        styled-terminal-invalidated)
          print -u2 -rl -- \
            "$plain_invalidated_record" \
            $'\e[31m'"$invalidated_diagnostic"$'\e[0m' \
            "$invalidated_guidance"
          ;;
        unsupported-sgr-invalidated)
          print -u2 -rl -- \
            $'\e[1m'"$plain_invalidated_record"$'\e[0m' \
            "$invalidated_diagnostic" "$invalidated_guidance"
          ;;
        non-sgr-csi-invalidated)
          print -u2 -rl -- \
            $'\e[31K'"$plain_invalidated_record" \
            "$invalidated_diagnostic" "$invalidated_guidance"
          ;;
        ansi-only-invalidated)
          print -u2 -rl -- \
            $'\e[2m\e[0m' \
            "$invalidated_diagnostic" "$invalidated_guidance"
          ;;
        misplaced-sgr-invalidated)
          misplaced_invalidated_record=$(ansi_main_record \
            "$fixture_timestamp" 231 $'Session \e[2minvalidated\e[0m')
          print -u2 -rl -- \
            "$misplaced_invalidated_record" \
            "$invalidated_diagnostic" "$invalidated_guidance"
          ;;
        trailing-sgr-invalidated)
          print -u2 -rl -- \
            "$ansi_invalidated_record"$'\e[0m' \
            "$invalidated_diagnostic" "$invalidated_guidance"
          ;;
        split-line-colon-sgr-invalidated)
          print -u2 -rl -- \
            "$(ansi_split_line_colon_record \
              "$fixture_timestamp" 231 "$invalidated_message")" \
            "$invalidated_diagnostic" "$invalidated_guidance"
          ;;
        mixed-invalidated)
          print -u2 -rl -- \
            "$plain_invalidated_record" "$ansi_second_invalidated_record" \
            "$invalidated_diagnostic" "$invalidated_guidance"
          ;;
        nul-plain-invalidated)
          print_nul_terminated_record "$plain_invalidated_record"
          print -u2 -rl -- "$invalidated_diagnostic" "$invalidated_guidance"
          ;;
        nul-ansi-invalidated)
          print_nul_terminated_record "$ansi_invalidated_record"
          print -u2 -rl -- "$invalidated_diagnostic" "$invalidated_guidance"
          ;;
        plain-framed-orphaned)
          print -u2 -rl -- "$plain_absent_record" "${orphaned_diagnostic_lines[@]}"
          ;;
        ansi-framed-orphaned)
          print -u2 -rl -- "$ansi_absent_record" "${orphaned_diagnostic_lines[@]}"
          ;;
        trailing-orphaned)
          print -u2 -rl -- "${orphaned_diagnostic_lines[@]}" ''
          ;;
        user-info-orphaned)
          print -u2 -rl -- \
            'Error: Error getting user info' '' "${orphaned_cause_lines[@]}"
          ;;
        no-active-session)
          print -u2 -rl -- \
            'Error: Error getting personal access token name' '' \
            'Caused by:' '    No active session'
          ;;
        refresh-failed)
          print -u2 -rl -- \
            'Error: Error getting personal access token name' '' \
            'Caused by:' \
            '    0: Error sending request' \
            '    1: failed to authenticate: refresh failed' \
            '    2: refresh failed'
          ;;
        *) exit 64 ;;
      esac
      exit 78
    fi
    # Captured from pass-cli 2.3.3 opening its database under another local key.
    if [[ -e $FAKE_PASS_INFO_UNDECRYPTABLE ]]; then
      store_detail='Failed to open encrypted database: file is not a database. '
      store_detail+='The encryption key may not match or the database may be corrupted. '
      store_detail+="Try running 'pass-cli logout --force' to reset local state."
      core_records=(
        '2026-09-24 16:12:00.774: ERROR CORE sqlcipher_page_cipher: hmac check failed for pgno=1'
        '2026-09-24 16:12:00.774: ERROR CORE sqlite3Codec: error decrypting page 1 data: 1'
        '2026-09-24 16:12:00.774: ERROR CORE sqlcipher_codec_ctx_set_error 1'
      )
      undecryptable_lines=(
        'Error: Error creating client features'
        ''
        'Caused by:'
        '    0: Failed to initialize database'
        '    1: Failed to get database connection'
        "    2: Error occurred while creating a new object: $store_detail"
        "    3: $store_detail"
        '    4: Error code 0: not an error'
      )
      case $(<"$FAKE_PASS_INFO_UNDECRYPTABLE") in
        framed)
          print -u2 -rl -- "${core_records[@]}" "${undecryptable_lines[@]}"
          ;;
        unframed)
          print -u2 -rl -- "${undecryptable_lines[@]}"
          ;;
        main-record-framed)
          print -u2 -rl -- "$plain_absent_record" "${undecryptable_lines[@]}"
          ;;
        styled-core-framed)
          print -u2 -rl -- $'\e[31m'"${core_records[1]}"$'\e[0m' \
            "${undecryptable_lines[@]}"
          ;;
        blank-framed)
          print -u2 -rl -- "${core_records[1]}" '' "${undecryptable_lines[@]}"
          ;;
        trailing-blank)
          print -u2 -rl -- "${core_records[@]}" "${undecryptable_lines[@]}" ''
          ;;
        truncated)
          print -u2 -rl -- "${core_records[@]}" "${(@)undecryptable_lines[1,-2]}"
          ;;
        *) exit 64 ;;
      esac
      exit 1
    fi
    if [[ -e $FAKE_PASS_INFO_MULTI_RECORD && ! -e $FAKE_PASS_REMOTE_SESSION ]]; then
      case $(<"$FAKE_PASS_INFO_MULTI_RECORD") in
        absent)
          print -u2 -rl -- \
            "$ansi_absent_record" "$ansi_alternate_absent_record" \
            "$absent_diagnostic"
          exit 78
          ;;
        invalidated)
          print -u2 -rl -- \
            "$plain_invalidated_record" "$plain_second_invalidated_record" \
            "$invalidated_diagnostic" "$invalidated_guidance"
          exit 77
          ;;
        *) exit 64 ;;
      esac
    fi
    if [[ -e $FAKE_PASS_LOCAL_SESSION && -e $FAKE_PASS_REMOTE_SESSION ]]; then
      print -r -- 'account-metadata-canary'
      exit 0
    fi
    if [[ -e $FAKE_PASS_INFO_ORPHANED && -e $FAKE_PASS_LOCAL_SESSION ]]; then
      print -u2 -rl -- "${orphaned_diagnostic_lines[@]}"
      exit 1
    fi
    if [[ -e $FAKE_PASS_INFO_INVALIDATED ]]; then
      print -u2 -rl -- \
        "$ansi_invalidated_record" \
        "$invalidated_diagnostic" "$invalidated_guidance"
      exit 77
    fi
    if [[ -e $FAKE_PASS_INFO_ALTERNATE_ABSENT ]]; then
      print -u2 -rl -- \
        "$(plain_main_record \
          "$fixture_timestamp" 332 "$alternate_absent_message")" \
        "$absent_diagnostic"
      exit 78
    fi
    print -u2 -rl -- \
      "$ansi_absent_record" "$absent_diagnostic"
    exit 78
    ;;
  login)
    if [[ -n ${FAKE_PASS_LOGIN_STDERR_LOG:-} ]]; then
      zmodload zsh/stat
      typeset -A login_stderr_metadata
      login_stderr_record=unknown
      # Redirecting this zstat's own stderr would replace the audited descriptor.
      if zstat -H login_stderr_metadata -f 2; then
        login_stderr_record=other
        (( (login_stderr_metadata[mode] & 8#170000) == 8#100000 )) &&
          login_stderr_record=regular
        login_stderr_record+=:$(printf '%o' $(( login_stderr_metadata[mode] & 8#7777 )))
        login_stderr_record+=:links=$login_stderr_metadata[nlink]
      fi
      login_stderr_record+=:
      [[ $OSTYPE != linux* ]] ||
        login_stderr_record+=$(/usr/bin/readlink "/proc/$$/fd/2" 2>/dev/null || true)
      print -r -- "$login_stderr_record" >> "$FAKE_PASS_LOGIN_STDERR_LOG"
    fi
    (( $# == 1 )) || exit 65
    [[ ${${(P)bootstrap_field}:-} == $fixture_token ]] || exit 66
    if [[ $OSTYPE == darwin* ]]; then
      [[ -z ${PROTON_PASS_LINUX_KEYRING:-} ]] || exit 67
    else
      [[ ${PROTON_PASS_LINUX_KEYRING:-} == dbus ]] || exit 67
    fi
    # pass-cli refuses login while local authentication remains stored.
    if [[ -e $FAKE_PASS_REQUIRE_LOGOUT && -e $FAKE_PASS_LOCAL_SESSION ]]; then
      print -r -- 'Client is already authenticated. Log out if you want to log in again'
      print -u2 -r -- 'Error: Already authenticated'
      exit 1
    fi
    # pass-cli writes local authentication before its private token key, so
    # an interrupted login passes info while every item read fails.
    if [[ -e $FAKE_PASS_LOGIN_PARTIAL_HANG ]]; then
      : > "$FAKE_PASS_LOCAL_SESSION"
      : > "$FAKE_PASS_REMOTE_SESSION"
      hang_forever
    fi
    # The same partial session from a login that then fails, once
    # FAKE_PASS_LOGIN_PARTIAL_GATE, when set, records an observation.
    if [[ -e $FAKE_PASS_LOGIN_PARTIAL_FAIL ]]; then
      : > "$FAKE_PASS_LOCAL_SESSION"
      : > "$FAKE_PASS_REMOTE_SESSION"
      if [[ -n ${FAKE_PASS_LOGIN_PARTIAL_GATE:-} ]]; then
        zmodload zsh/datetime
        zmodload zsh/zselect
        typeset -F partial_gate_deadline=$(( EPOCHREALTIME + 3 ))
        while (( EPOCHREALTIME < partial_gate_deadline )) &&
          [[ ! -s $FAKE_PASS_LOGIN_PARTIAL_GATE ]]; do
          zselect -t 1 || true
        done
      fi
      exit 71
    fi
    if [[ -e $FAKE_PASS_LOGIN_DIAGNOSTIC ]]; then
      login_flow_lines=(
        'Error: Error in personal access token login flow'
        ''
        'Caused by:'
      )
      parse_failure_line='    0: Failed to parse personal access token token'
      session_failure_line='    0: Error creating personal access token session'
      case $(<"$FAKE_PASS_LOGIN_DIAGNOSTIC") in
        token-rejected)
          print -u2 -rl -- "${login_flow_lines[@]}" "$session_failure_line" \
            '    1: This personal access token is invalid, expired or has been deleted.'
          ;;
        malformed-format)
          print -u2 -rl -- "${login_flow_lines[@]}" "$parse_failure_line" \
            '    1: Invalid personal access token token format. Expected format: pst_<token>::<key>'
          ;;
        malformed-prefix)
          print -u2 -rl -- "${login_flow_lines[@]}" "$parse_failure_line" \
            "    1: Personal access token token must start with 'pst_'"
          ;;
        malformed-length)
          print -u2 -rl -- "${login_flow_lines[@]}" "$parse_failure_line" \
            "    1: Personal access token token must have exactly 64 characters after 'pst_' prefix"
          ;;
        malformed-key)
          print -u2 -rl -- "${login_flow_lines[@]}" "$parse_failure_line" \
            '    1: Failed to decode personal access token key. Must be base64-urlsafe encoded' \
            '    2: Invalid symbol 45, offset 3.'
          ;;
        session-refused)
          print -u2 -rl -- "${login_flow_lines[@]}" "$session_failure_line" \
            '    1: Error requesting personal access token session' \
            '    2: failed to authenticate: non-existent session' \
            '    3: non-existent session'
          ;;
        bad-response)
          print -u2 -rl -- "${login_flow_lines[@]}" "$session_failure_line" \
            '    1: Bad response when creating Personal Access Token session: 429'
          ;;
        already-authenticated-trailing-space)
          print -u2 -r -- 'Error: Already authenticated '
          ;;
        already-authenticated-blank-line)
          print -u2 -rl -- 'Error: Already authenticated' ''
          ;;
        already-authenticated-crlf)
          print -u2 -r -- $'Error: Already authenticated\r'
          ;;
        already-authenticated-traced)
          print -u2 -rl -- \
            "$(plain_main_record "$fixture_timestamp" 300 'Login refused')" \
            'Error: Already authenticated'
          ;;
        already-authenticated-backtrace)
          print -u2 -rl -- 'Error: Already authenticated' '' \
            'Stack backtrace:' '   0: std::backtrace::Backtrace::create'
          ;;
        already-authenticated-oversized)
          print -u2 -r -- ${(l:4067::x:)}
          print -u2 -r -- 'Error: Already authenticated'
          ;;
        already-authenticated-hang)
          print -u2 -r -- 'Error: Already authenticated'
          hang_forever
          ;;
        token-echo)
          print -u2 -r -- "Error: rejected $fixture_token"
          ;;
        *) exit 64 ;;
      esac
      exit 1
    fi
    [[ -z ${PROVIDER_PID_FILE:-} ]] || print -r -- $$ > "$PROVIDER_PID_FILE"
    [[ -z ${PROVIDER_START_MARKER:-} ]] ||
      print -r -- provider-started >> "$PROVIDER_START_MARKER"
    [[ -z ${PROVIDER_COMPLETION_DELAY:-} ]] || /bin/sleep 0.2
    if [[ -e $FAKE_PASS_LOGIN_DESCENDANT ]]; then
      spawn_resistant_descendant
      : > "$FAKE_PASS_LOCAL_SESSION"
      : > "$FAKE_PASS_REMOTE_SESSION"
      exit 0
    fi
    [[ ! -e $FAKE_PASS_LOGIN_HANG ]] || hang_forever
    [[ ! -e $FAKE_PASS_LOGIN_DELAY ]] ||
      /bin/sleep "${FAKE_PASS_LOGIN_DELAY_SECONDS:-0.2}"
    [[ ! -e $FAKE_PASS_LOGIN_EXIT_124 ]] || exit 124
    [[ ! -e $FAKE_PASS_LOGIN_FAIL ]] || exit 71
    : > "$FAKE_PASS_LOCAL_SESSION"
    [[ -e $FAKE_PASS_SKIP_REMOTE_SESSION ]] || : > "$FAKE_PASS_REMOTE_SESSION"
    [[ -z ${PROVIDER_COMPLETION_MARKER:-} ]] ||
      print -r -- provider-completed >> "$PROVIDER_COMPLETION_MARKER"
    ;;
  logout)
    (( $# == 1 )) || [[ $# == 2 && $2 == --force ]] || exit 74
    [[ -z ${${(P)bootstrap_field}:-} ]] || exit 75
    [[ ! -e $FAKE_PASS_LOGOUT_HANG ]] || hang_forever
    [[ -z ${FAKE_PASS_LOGOUT_DELAY_SECONDS:-} ]] ||
      /bin/sleep "$FAKE_PASS_LOGOUT_DELAY_SECONDS"
    [[ ! -e $FAKE_PASS_LOGOUT_FAIL ]] || exit 79
    # Forced logout also removes the local database that could not be opened.
    /bin/rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION" \
      "$FAKE_PASS_INFO_UNDECRYPTABLE"
    ;;
  *)
    exit 68
    ;;
esac
EOF
chmod +x "$fixture_local_bin/pass-cli"

cat > "$native_store_adapter" <<'EOF'
#!/bin/zsh -f
set -euo pipefail

print -r -- "$*" >> "$FAKE_SECRET_TOOL_LOG"
bootstrap_field=PROTON_PASS_PERSONAL_ACCESS
bootstrap_field+=_TOKEN
unset "$bootstrap_field" 2>/dev/null || true
[[ $* == proton-bootstrap ]] || exit 64
[[ ! -e $FAKE_NATIVE_STORE_LOCKED ]] || exit 69
[[ -z ${FAKE_NATIVE_STORE_DELAY_SECONDS:-} ]] ||
  /bin/sleep "$FAKE_NATIVE_STORE_DELAY_SECONDS"
fixture_token=pst_
fixture_token+='fixture-token'
fixture_token+='::fixture-key'
if [[ -e $FAKE_NATIVE_STORE_DESCENDANT ]]; then
  print -r -- "$fixture_token"
  (
    zmodload zsh/system
    zmodload zsh/zselect
    trap '' HUP TERM
    print -r -- "$sysparams[pid]" > "$FAKE_DESCENDANT_PID"
    while true; do
      zselect -t 10 || true
    done
  ) &!
  zmodload zsh/zselect
  while [[ ! -s $FAKE_DESCENDANT_PID ]]; do
    zselect -t 1 || true
  done
  exit 0
fi
if [[ -e $FAKE_NATIVE_STORE_HANG ]]; then
  print -r -- $$ > "$FAKE_HANGING_CHILD_PID"
  zmodload zsh/zselect
  trap 'exit 143' TERM
  while true; do
    zselect -t 10 || true
  done
fi
if [[ -e $FAKE_NATIVE_STORE_BAD_VALUE ]]; then
  print -r -- 'invalid'
  print -r -- 'bootstrap'
  exit 0
fi
print -r -- "$fixture_token"
EOF
chmod +x "$native_store_adapter"

cat > "$fake_bin/uname" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

[[ ${1:-} == -s && $# == 1 ]] || exit 64
if [[ -e $FAKE_UNAME_HANG ]]; then
  print -r -- $$ > "$FAKE_UNAME_CHILD_PID"
  : > "$FAKE_UNAME_MARKER"
  integer original_parent=$PPID
  zmodload zsh/zselect
  trap 'exit 143' TERM
  while kill -0 $original_parent 2>/dev/null; do
    zselect -t 1 || true
  done
  exit 143
fi
print -r -- "${FAKE_UNAME_SYSTEM:-Linux}"
EOF
chmod +x "$fake_bin/uname"

cat > "$fake_bin/flock" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

: > "$FAKE_EXTERNAL_FLOCK_MARKER"
exit 90
EOF
chmod +x "$fake_bin/flock"

for utility in mkdir chmod mktemp rm mv; do
  cat > "$fake_bin/$utility" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

utility=${0:t}
if [[ -e $FAKE_UTILITY_TRACE ]]; then
  : > "$FAKE_UTILITY_MARKER_DIR/$utility"
fi
case $utility in
  mkdir) exec /bin/mkdir "$@" ;;
  chmod) exec /bin/chmod "$@" ;;
  mktemp) exec /usr/bin/mktemp "$@" ;;
  rm) exec /bin/rm "$@" ;;
  mv) exec /bin/mv "$@" ;;
  *) exit 90 ;;
esac
EOF
  chmod +x "$fake_bin/$utility"
done

export PATH=$fixture_local_bin:$fake_bin:/usr/bin:/bin
export HOME=$fixture_home
export XDG_STATE_HOME=$state_home
export FAKE_PASS_LOG=$test_dir/pass.log
export FAKE_PASS_LOGIN_DELAY=$test_dir/login-delay
export FAKE_PASS_LOGIN_FAIL=$test_dir/login-fail
export FAKE_PASS_REQUIRE_LOGOUT=$test_dir/require-logout
export FAKE_PASS_LOGOUT_FAIL=$test_dir/logout-fail
export FAKE_PASS_LOGOUT_HANG=$test_dir/logout-hang
export FAKE_PASS_LOGIN_EXIT_124=$test_dir/login-exit-124
export FAKE_PASS_LOGIN_HANG=$test_dir/login-hang
export FAKE_PASS_LOGIN_PARTIAL_HANG=$test_dir/login-partial-hang
export FAKE_PASS_LOGIN_PARTIAL_FAIL=$test_dir/login-partial-fail
export FAKE_PASS_LOGIN_DESCENDANT=$test_dir/login-descendant
export FAKE_PASS_LOCAL_SESSION=$test_dir/local-session
export FAKE_PASS_REMOTE_SESSION=$test_dir/remote-session
export FAKE_PASS_SKIP_REMOTE_SESSION=$test_dir/skip-remote-session
export FAKE_PASS_VERIFY_HANG=$test_dir/verify-hang
export FAKE_PASS_INFO_HANG=$test_dir/info-hang
export FAKE_PASS_INFO_TRANSIENT=$test_dir/info-transient
export FAKE_PASS_INFO_MALFORMED_FRAMING=$test_dir/info-malformed-framing
export FAKE_PASS_INFO_MULTI_RECORD=$test_dir/info-multi-record
export FAKE_PASS_INFO_INVALIDATED=$test_dir/info-invalidated
export FAKE_PASS_INFO_ORPHANED=$test_dir/info-orphaned
export FAKE_PASS_INFO_UNDECRYPTABLE=$test_dir/info-undecryptable
export FAKE_PASS_LOGIN_DIAGNOSTIC=$test_dir/login-diagnostic
export FAKE_PASS_LOGIN_STDERR_LOG=$test_dir/login-stderr.log
export FAKE_PASS_INFO_ALTERNATE_ABSENT=$test_dir/info-alternate-absent
export FAKE_SECRET_TOOL_LOG=$test_dir/secret-tool.log
export FAKE_NATIVE_STORE_LOCKED=$test_dir/native-store-locked
export FAKE_NATIVE_STORE_HANG=$test_dir/native-store-hang
export FAKE_NATIVE_STORE_DESCENDANT=$test_dir/native-store-descendant
export FAKE_HANGING_CHILD_PID=$test_dir/hanging-child.pid
# Set only by tests that expect more than one hanging child in a call.
export FAKE_HANGING_CHILD_PIDS=
export FAKE_DESCENDANT_PID=$test_dir/descendant.pid
export FAKE_DESCENDANT_TOKEN_MARKER=$test_dir/descendant-inherited-bootstrap
export FAKE_NATIVE_STORE_BAD_VALUE=$test_dir/native-store-bad-value
export FAKE_EXTERNAL_FLOCK_MARKER=$test_dir/external-flock-ran
export FAKE_UNAME_HANG=$test_dir/uname-hang
export FAKE_UNAME_MARKER=$test_dir/uname-ran
export FAKE_UNAME_CHILD_PID=$test_dir/uname-child.pid
export FAKE_UTILITY_TRACE=$test_dir/trace-ambient-utilities
export FAKE_UTILITY_MARKER_DIR=$test_dir/ambient-utility-markers
if [[ ${PROTON_PASS_WAITER_STAGE_RED_PROOF:-0} == 1 ]]; then
  unset PROTON_PASS_LAST_WAITER_STAGE 2>/dev/null || true
else
  export PROTON_PASS_LAST_WAITER_STAGE=waiter-stage-canary
fi
# Inherited private diagnostic state must never reach provider children.
export PROTON_PASS_DIAGNOSTIC_TEXT=diagnostic-text-canary
export PROTON_PASS_DIAGNOSTIC_FILE=$test_dir/inherited-diagnostic-file
export PROTON_PASS_DIAGNOSTIC_WRITE_FD=1 PROTON_PASS_DIAGNOSTIC_READ_FD=0
: > "$PROTON_PASS_DIAGNOSTIC_FILE"
/bin/mkdir -p -- "$FAKE_UTILITY_MARKER_DIR"
fixture_token=pst_
fixture_token+='fixture-token'
fixture_token+='::fixture-key'

assert_no_private_diagnostics() {
  local -a leftovers=(
    "$state_home/secret-exec"/.proton-pass-{session-probe,login-diagnostic}.*(N)
  )
  (( ! ${#leftovers} )) ||
    fail "$1 must remove its private provider diagnostic files"
}

run_waiter_stage_mapping() {
  emulate -L zsh
  setopt local_options err_return no_unset pipe_fail

  local mode=$1
  local expected_audit=$2
  local completion_expectation=$3
  local completion_delay=$4
  local audit_log=$test_dir/waiter-$mode.audit
  local identity_gate=$test_dir/waiter-$mode.identity-gate
  local retirement_release=$test_dir/waiter-$mode.retirement-release
  local controller_pid_file=$test_dir/waiter-$mode.controller-pid
  local provider_start=$test_dir/waiter-$mode.provider-start
  local provider_pid_file=$test_dir/waiter-$mode.provider-pid
  local provider_completion=$test_dir/waiter-$mode.provider-completion
  local output_file=$test_dir/waiter-$mode.output
  integer waiter_status
  local waiter_output
  local -a value_free_artifacts

  rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION" \
    "$audit_log" "$identity_gate" "$provider_start" "$provider_pid_file" \
    "$provider_completion" "$retirement_release" "$controller_pid_file" \
    "$output_file" "$kill_audit_log"
  : > "$FAKE_PASS_LOG"
  : > "$FAKE_SECRET_TOOL_LOG"
  test_process_fixture_track_pid_file "$provider_pid_file"
  test_process_fixture_track_pid_file "$controller_pid_file"
  if /usr/bin/env \
    LD_PRELOAD="$status_fragment_library:$kill_audit_library" \
    ZPTY_WAITER_STAGE_MODE=$mode \
    ZPTY_WAITER_STAGE_AUDIT_LOG=$audit_log \
    ZPTY_WAITER_STAGE_IDENTITY_GATE=$identity_gate \
    ZPTY_WAITER_STAGE_RETIREMENT_RELEASE=$retirement_release \
    ZPTY_WAITER_STAGE_CONTROLLER_PID_FILE=$controller_pid_file \
    NEGATIVE_PGID_KILL_AUDIT_LOG=$kill_audit_log \
    PROVIDER_START_MARKER=$provider_start \
    PROVIDER_PID_FILE=$provider_pid_file \
    PROVIDER_COMPLETION_MARKER=$provider_completion \
    PROVIDER_COMPLETION_DELAY=$completion_delay \
    HOME=$fixture_home XDG_STATE_HOME=$state_home \
    "$ensure_ready" >"$output_file" 2>&1; then
    waiter_status=0
  else
    waiter_status=$?
  fi

  [[ -s $controller_pid_file ]] ||
    fail "the $mode waiter-stage fixture must publish its controller PID"
  local controller_pid=$(<"$controller_pid_file")
  [[ $controller_pid == <-> && $controller_pid -gt 1 ]] ||
    fail "the $mode waiter-stage fixture must publish a numeric controller PID"
  test_process_fixture_track_pid $controller_pid
  if [[ $mode == retirement ]]; then
    : > "$retirement_release"
  fi
  test_process_fixture_wait_for_pid_exit $controller_pid 100 ||
    fail "the $mode waiter-stage fixture must leave no controller process"
  integer controller_group_polls=100
  while (( controller_group_polls-- > 0 )) &&
    kill -0 -- -$controller_pid 2>/dev/null; do
    zselect -t 1 2>/dev/null || true
  done
  ! kill -0 -- -$controller_pid 2>/dev/null ||
    fail "the $mode waiter-stage fixture must leave no controller process group"
  test_process_fixture_untrack_pid $controller_pid
  test_process_fixture_untrack_pid_file "$controller_pid_file"

  [[ -s $provider_pid_file ]] ||
    fail "the $mode waiter-stage fixture must publish its provider PID"
  local provider_pid=$(<"$provider_pid_file")
  [[ $provider_pid == <-> && $provider_pid -gt 1 ]] ||
    fail "the $mode waiter-stage fixture must publish a numeric provider PID"
  test_process_fixture_wait_for_pid_exit $provider_pid 100 ||
    fail "the $mode waiter-stage fixture must leave no provider process"
  test_process_fixture_untrack_pid_file "$provider_pid_file"

  (( waiter_status == 1 )) ||
    fail "the $mode waiter-stage fixture must fail readiness with status 1"
  waiter_output=$(<"$output_file")
  [[ $waiter_output ==
    'proton-pass-ensure-ready: provider-session repair failed' ]] ||
    fail "the $mode waiter-stage fixture must preserve the fixed readiness diagnostic"
  [[ $(<"$audit_log") == $expected_audit ]] ||
    fail "the $mode waiter-stage fixture must prove its exact trigger"
  [[ $(<"$provider_start") == provider-started ]] ||
    fail "the $mode waiter-stage fixture must prove provider execution"
  # The helper cannot tell how far a login got past a failed waiter, so it
  # forces out whatever local authentication that login stored.
  [[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogin\nlogout --force' ]] ||
    fail "the $mode waiter-stage fixture must target the direct login waiter and clear its local state"
  [[ ! -e $FAKE_PASS_LOCAL_SESSION ]] ||
    fail "the $mode waiter-stage fixture must not leave the failed login's local authentication"
  case $completion_expectation in
    completed)
      [[ $(<"$provider_completion") == provider-completed ]] ||
        fail "the $mode waiter-stage fixture must prove provider completion"
      ;;
    interrupted)
      [[ ! -e $provider_completion ]] ||
        fail "the $mode waiter-stage fixture must interrupt the provider before completion"
      ;;
    *) fail 'invalid waiter-stage completion expectation' ;;
  esac
  grep -Fqx 'state=unavailable' "$status_file" ||
    fail "the $mode waiter-stage failure must record unavailable status"
  grep -Fqx 'reason=login-failed' "$status_file" ||
    fail "the $mode waiter-stage failure must keep login-failed stable"
  grep -Fqx "waiter-stage=$mode" "$status_file" ||
    fail "the $mode waiter-stage failure must record its exact stage"
  [[ ! -s $kill_audit_log ]] ||
    fail "the $mode waiter-stage fixture must not signal a stale process group"

  value_free_artifacts=(
    "$output_file"
    "$audit_log"
    "$status_file"
    "$FAKE_PASS_LOG"
    "$FAKE_SECRET_TOOL_LOG"
    "$provider_pid_file"
  )
  [[ ! -e $controller_pid_file ]] || value_free_artifacts+=("$controller_pid_file")
  [[ ! -e $provider_start ]] || value_free_artifacts+=("$provider_start")
  [[ ! -e $provider_completion ]] || value_free_artifacts+=("$provider_completion")
  ! /usr/bin/grep -F "$fixture_token" "${value_free_artifacts[@]}" >/dev/null ||
    fail "the $mode waiter-stage fixture must not expose the bootstrap value"
  ! /usr/bin/grep -F 'account-metadata-canary' "${value_free_artifacts[@]}" >/dev/null ||
    fail "the $mode waiter-stage fixture must not expose provider output"
  ! /usr/bin/grep -F 'waiter-stage-canary' "${value_free_artifacts[@]}" >/dev/null ||
    fail "the $mode waiter-stage fixture must not expose inherited diagnostic input"
}

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION" \
  "$FAKE_UNAME_MARKER" "$FAKE_UNAME_CHILD_PID"
: > "$FAKE_PASS_LOCAL_SESSION"
: > "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_UNAME_HANG"
test_process_fixture_track_pid_file "$FAKE_UNAME_CHILD_PID"
zmodload zsh/datetime
zmodload zsh/zselect
typeset -F entrypoint_started=$EPOCHREALTIME
"$ensure_ready" >"$test_dir/entrypoint.out" \
  2>"$test_dir/entrypoint.err" &
entrypoint_pid=$!
test_process_fixture_track_pid $entrypoint_pid
typeset -F entrypoint_deadline=$(( entrypoint_started + 1.5 ))
integer entrypoint_timed_out=0
while kill -0 $entrypoint_pid 2>/dev/null; do
  if (( EPOCHREALTIME >= entrypoint_deadline )); then
    entrypoint_timed_out=1
    kill -TERM $entrypoint_pid 2>/dev/null || true
    zselect -t 10 || true
    kill -0 $entrypoint_pid 2>/dev/null && \
      kill -KILL $entrypoint_pid 2>/dev/null || true
    break
  fi
  zselect -t 1 || true
done
if wait $entrypoint_pid; then
  entrypoint_status=0
else
  entrypoint_status=$?
fi
test_process_fixture_untrack_pid $entrypoint_pid
typeset -F entrypoint_elapsed=$(( EPOCHREALTIME - entrypoint_started ))
if [[ -e $FAKE_UNAME_CHILD_PID ]]; then
  hostile_uname_pid=$(<"$FAKE_UNAME_CHILD_PID")
  kill -TERM $hostile_uname_pid 2>/dev/null || true
  test_process_fixture_wait_for_pid_exit $hostile_uname_pid 20 || true
fi
test_process_fixture_untrack_pid_file "$FAKE_UNAME_CHILD_PID"
rm -f -- "$FAKE_UNAME_HANG"
(( ! entrypoint_timed_out && entrypoint_status == 0 && entrypoint_elapsed < 1.5 )) ||
  fail 'the whole readiness entrypoint must remain bounded before credential-child deadlines'
[[ ! -e $FAKE_UNAME_MARKER ]] ||
  fail 'readiness must not invoke a PATH-selected platform probe'
rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"

: > "$FAKE_UTILITY_TRACE"
"$ensure_ready"
/bin/rm -f -- "$FAKE_UTILITY_TRACE"
ambient_utility_markers=("$FAKE_UTILITY_MARKER_DIR"/*(N))
(( ! ${#ambient_utility_markers} )) ||
  fail 'readiness must not invoke PATH-selected housekeeping utilities'
/bin/rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION" \
  "$FAKE_HANGING_CHILD_PID"
: > "$FAKE_PASS_INFO_HANG"
test_process_fixture_track_pid_file "$FAKE_HANGING_CHILD_PID"
typeset -F info_hang_started=$EPOCHREALTIME
"$ensure_ready" >"$test_dir/info-hang.out" 2>"$test_dir/info-hang.err" &
info_hang_entrypoint_pid=$!
test_process_fixture_track_pid $info_hang_entrypoint_pid
typeset -F info_hang_deadline=$(( info_hang_started + 9.5 ))
integer info_hang_timed_out=0
while kill -0 $info_hang_entrypoint_pid 2>/dev/null; do
  if (( EPOCHREALTIME >= info_hang_deadline )); then
    info_hang_timed_out=1
    kill -TERM $info_hang_entrypoint_pid 2>/dev/null || true
    zselect -t 10 || true
    kill -0 $info_hang_entrypoint_pid 2>/dev/null && \
      kill -KILL $info_hang_entrypoint_pid 2>/dev/null || true
    break
  fi
  zselect -t 1 || true
done
if wait $info_hang_entrypoint_pid; then
  info_hang_status=0
else
  info_hang_status=$?
fi
test_process_fixture_untrack_pid $info_hang_entrypoint_pid
typeset -F info_hang_elapsed=$(( EPOCHREALTIME - info_hang_started ))
rm -f -- "$FAKE_PASS_INFO_HANG"
(( ! info_hang_timed_out && info_hang_status == 1 && info_hang_elapsed < 9.5 )) ||
  fail 'the whole readiness entrypoint must bound initial and locked session probes'
(( info_hang_elapsed >= 7.8 )) ||
  fail "the locked session probe must allow its full classification deadline: elapsed=$info_hang_elapsed"
[[ $(<"$test_dir/info-hang.err") ==
  'proton-pass-ensure-ready: provider-session readiness check timed out' ]] ||
  fail 'a timed-out locked session probe must report one fixed diagnostic'
grep -Fqx 'reason=session-probe-timeout' \
  "$state_home/secret-exec/proton-pass-readiness.status" ||
  fail 'a timed-out locked session probe must record its value-free reason'
hanging_child_pid=$(<"$FAKE_HANGING_CHILD_PID")
if kill -0 $hanging_child_pid 2>/dev/null; then
  kill -TERM $hanging_child_pid 2>/dev/null || true
  fail 'timed-out session probes must be terminated and reaped'
fi
test_process_fixture_untrack_pid_file "$FAKE_HANGING_CHILD_PID"
rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
: > "$FAKE_PASS_LOGIN_STDERR_LOG"

zsh "$ensure_ready"
login_stderr_record=$(<"$FAKE_PASS_LOGIN_STDERR_LOG")
[[ $login_stderr_record == regular:600:links=0:* ]] ||
  fail "provider login diagnostics must go to a private unlinked regular file: $login_stderr_record"
if [[ $OSTYPE == linux* ]]; then
  [[ ${login_stderr_record#regular:600:links=0:} ==
    "$state_home/secret-exec/.proton-pass-login-diagnostic."??????' (deleted)' ]] ||
    fail "provider login diagnostics must stay in the private state directory: $login_stderr_record"
fi
assert_no_private_diagnostics 'a successful repair'
[[ ! -e $FAKE_EXTERNAL_FLOCK_MARKER ]] ||
  fail 'readiness locking must not invoke an external flock executable'
[[ -e $FAKE_PASS_REMOTE_SESSION ]] ||
  fail 'ensure-ready must establish a remotely authenticated provider session'
[[ $(/usr/bin/grep -Fxc login "$FAKE_PASS_LOG") == 1 ]] ||
  fail 'ensure-ready must perform one argument-free login when repair is needed'
[[ $(<"$FAKE_SECRET_TOOL_LOG") ==
  'proton-bootstrap' ]] ||
  fail 'ensure-ready must resolve the fixed native bootstrap item'
status_file=$state_home/secret-exec/proton-pass-readiness.status
login_marker=$state_home/secret-exec/proton-pass-login.pending
[[ ! -e $login_marker ]] ||
  fail 'a verified repair must clear its login marker'
if [[ -n $status_fragment_library ]]; then
  run_waiter_stage_mapping record \
    $'login-controller-targeted\nrecord-corrupted' completed ''
  run_waiter_stage_mapping identity \
    $'login-controller-targeted\nstart-gate\nlive-before-esrch\ninjected-esrch\nidentity-listing-invalidated\ncleanup-live' \
    interrupted 1
  run_waiter_stage_mapping liveness-retry \
    $'login-controller-targeted\nstart-gate\nlive-before-esrch-1\ninjected-esrch-1\nlive-before-esrch-2\ninjected-esrch-2\ncleanup-live' \
    interrupted 1
  run_waiter_stage_mapping retirement \
    $'login-controller-targeted\ncontroller-release-blocked\ncontroller-released' \
    completed ''
  rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
  : > "$FAKE_PASS_LOG"
  : > "$FAKE_SECRET_TOOL_LOG"
  zsh "$ensure_ready"
fi
grep -Fqx 'state=ready' "$status_file" || fail 'a repaired session must record ready status'
grep -Fqx 'reason=repaired' "$status_file" || fail 'a repaired session must record its value-free reason'
grep -Fqx 'waiter-stage=unrecorded' "$status_file" ||
  fail 'a successful repair must record an unrecorded waiter stage'
[[ $(grep -Ec '^waiter-stage=(record|identity|liveness-retry|child-status|retirement|unrecorded)$' "$status_file") == 1 ]] ||
  fail 'readiness status must contain one allowlisted waiter stage'

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_INFO_ALTERNATE_ABSENT"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
zsh "$ensure_ready"
rm -f -- "$FAKE_PASS_INFO_ALTERNATE_ABSENT"
[[ -e $FAKE_PASS_REMOTE_SESSION ]] ||
  fail 'the alternate recognized absent diagnostic must establish readiness'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogin\ninfo' ]] ||
  fail 'the alternate recognized absent diagnostic must perform one bounded repair'
[[ $(<"$FAKE_SECRET_TOOL_LOG") == proton-bootstrap ]] ||
  fail 'the alternate recognized absent diagnostic must use the fixed bootstrap item'

: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
zsh "$ensure_ready"
[[ $(<"$FAKE_PASS_LOG") == 'info' ]] ||
  fail 'an existing provider session must not trigger another login'
[[ ! -s $FAKE_SECRET_TOOL_LOG ]] ||
  fail 'an existing provider session must not read the bootstrap item'
grep -Fqx 'reason=existing-session' "$status_file" ||
  fail 'an existing session must record its value-free reason'

for malformed_framing in \
  blank-absent embedded-absent trailing-absent \
  styled-terminal-absent unsupported-sgr-absent non-sgr-csi-absent \
  ansi-only-absent misplaced-sgr-absent trailing-sgr-absent \
  split-line-colon-sgr-absent mixed-absent \
  nul-plain-absent nul-ansi-absent \
  blank-invalidated embedded-invalidated trailing-invalidated \
  styled-terminal-invalidated unsupported-sgr-invalidated \
  non-sgr-csi-invalidated ansi-only-invalidated \
  misplaced-sgr-invalidated trailing-sgr-invalidated \
  split-line-colon-sgr-invalidated mixed-invalidated \
  nul-plain-invalidated nul-ansi-invalidated \
  plain-framed-orphaned ansi-framed-orphaned trailing-orphaned \
  user-info-orphaned no-active-session refresh-failed; do
  print -r -- "$malformed_framing" >"$FAKE_PASS_INFO_MALFORMED_FRAMING"
  : >"$FAKE_PASS_LOG"
  : >"$FAKE_SECRET_TOOL_LOG"
  set +e
  malformed_framing_output=$(zsh "$ensure_ready" 2>&1)
  malformed_framing_status=$?
  set -e
  (( malformed_framing_status != 0 )) ||
    fail "the $malformed_framing diagnostic must remain unclassified"
  [[ $malformed_framing_output ==
    'proton-pass-ensure-ready: provider-session readiness could not be classified' ]] ||
    fail "the $malformed_framing diagnostic must report one fixed error"
  [[ -e $FAKE_PASS_LOCAL_SESSION && -e $FAKE_PASS_REMOTE_SESSION ]] ||
    fail "the $malformed_framing diagnostic must preserve the existing session"
  [[ $(<"$FAKE_PASS_LOG") == $'info\ninfo' ]] ||
    fail "the $malformed_framing diagnostic must not mutate provider authentication"
  [[ ! -s $FAKE_SECRET_TOOL_LOG ]] ||
    fail "the $malformed_framing diagnostic must not read the bootstrap item"
  grep -Fqx 'reason=session-state-unknown' "$status_file" ||
    fail "the $malformed_framing diagnostic must record the unknown state"
done
rm -f -- "$FAKE_PASS_INFO_MALFORMED_FRAMING"

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
print -r -- absent >"$FAKE_PASS_INFO_MULTI_RECORD"
: >"$FAKE_PASS_LOG"
: >"$FAKE_SECRET_TOOL_LOG"
zsh "$ensure_ready"
rm -f -- "$FAKE_PASS_INFO_MULTI_RECORD"
[[ -e $FAKE_PASS_REMOTE_SESSION ]] ||
  fail 'multiple recognized absent records must establish readiness'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogin\ninfo' ]] ||
  fail 'multiple recognized absent records must perform one bounded repair'
[[ $(<"$FAKE_SECRET_TOOL_LOG") == proton-bootstrap ]] ||
  fail 'multiple recognized absent records must use the fixed bootstrap item'

touch -- "$FAKE_PASS_INFO_TRANSIENT"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
set +e
transient_output=$(zsh "$ensure_ready" 2>&1)
transient_status=$?
set -e
rm -f -- "$FAKE_PASS_INFO_TRANSIENT"
(( transient_status != 0 )) ||
  fail 'an unclassified readiness failure must not replace an existing session'
[[ $transient_output ==
  'proton-pass-ensure-ready: provider-session readiness could not be classified' ]] ||
  fail 'an unclassified readiness failure must report one fixed diagnostic'
[[ -e $FAKE_PASS_LOCAL_SESSION && -e $FAKE_PASS_REMOTE_SESSION ]] ||
  fail 'an unclassified readiness failure must preserve the existing session'
! /usr/bin/grep -Eq '^(logout|login)' "$FAKE_PASS_LOG" ||
  fail 'an unclassified readiness failure must not mutate provider authentication'
[[ ! -s $FAKE_SECRET_TOOL_LOG ]] ||
  fail 'an unclassified readiness failure must not read the bootstrap item'
assert_no_private_diagnostics 'a classified readiness check'

rm -f -- "$FAKE_PASS_REMOTE_SESSION"
: >"$FAKE_PASS_REQUIRE_LOGOUT"
print -r -- invalidated >"$FAKE_PASS_INFO_MULTI_RECORD"
: >"$FAKE_PASS_LOG"
: >"$FAKE_SECRET_TOOL_LOG"
zsh "$ensure_ready"
rm -f -- "$FAKE_PASS_INFO_MULTI_RECORD"
[[ -e $FAKE_PASS_REMOTE_SESSION ]] ||
  fail 'multiple recognized invalidated records must establish readiness'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogout --force\nlogin\ninfo' ]] ||
  fail 'multiple recognized invalidated records must perform cleanup and repair'
[[ $(<"$FAKE_SECRET_TOOL_LOG") == proton-bootstrap ]] ||
  fail 'multiple recognized invalidated records must use the fixed bootstrap item'

rm -f -- "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_REQUIRE_LOGOUT"
: > "$FAKE_PASS_INFO_INVALIDATED"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
zsh "$ensure_ready"
[[ -e $FAKE_PASS_REMOTE_SESSION ]] ||
  fail 'a stale local session marker must not satisfy remote readiness'
[[ $(/usr/bin/grep -Fxc login "$FAKE_PASS_LOG") == 1 ]] ||
  fail 'a stale local session marker must trigger one repair login'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogout --force\nlogin\ninfo' ]] ||
  fail 'a stale local session must be logged out before repair login'
rm -f -- "$FAKE_PASS_INFO_INVALIDATED"

rm -f -- "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_REQUIRE_LOGOUT"
: > "$FAKE_PASS_INFO_INVALIDATED"
: > "$FAKE_PASS_LOGOUT_FAIL"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
set +e
logout_failure_output=$(zsh "$ensure_ready" 2>&1)
logout_failure_status=$?
set -e
rm -f -- \
  "$FAKE_PASS_REQUIRE_LOGOUT" \
  "$FAKE_PASS_INFO_INVALIDATED" \
  "$FAKE_PASS_LOGOUT_FAIL"
(( logout_failure_status != 0 )) ||
  fail 'a failed stale-session cleanup must fail readiness'
[[ $logout_failure_output ==
  'proton-pass-ensure-ready: provider-session cleanup failed' ]] ||
  fail 'a failed stale-session cleanup must report one fixed diagnostic'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogout --force' ]] ||
  fail 'a failed stale-session cleanup must not attempt provider login'
grep -Fqx 'reason=logout-failed' "$status_file" ||
  fail 'a failed stale-session cleanup must record its value-free reason'
# The marker covers the forced logout too, so a failed one leaves it behind.
[[ -f $login_marker ]] ||
  fail 'a failed stale-session cleanup must keep the login marker'
rm -f -- "$login_marker"

rm -f -- "$FAKE_PASS_REMOTE_SESSION" "$FAKE_HANGING_CHILD_PID"
: > "$FAKE_PASS_REQUIRE_LOGOUT"
: > "$FAKE_PASS_INFO_INVALIDATED"
: > "$FAKE_PASS_LOGOUT_HANG"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
test_process_fixture_track_pid_file "$FAKE_HANGING_CHILD_PID"
typeset -F logout_timeout_started=$EPOCHREALTIME
set +e
logout_timeout_output=$(zsh "$ensure_ready" 2>&1)
logout_timeout_status=$?
set -e
typeset -F logout_timeout_elapsed=$(( EPOCHREALTIME - logout_timeout_started ))
rm -f -- \
  "$FAKE_PASS_REQUIRE_LOGOUT" \
  "$FAKE_PASS_INFO_INVALIDATED" \
  "$FAKE_PASS_LOGOUT_HANG"
(( logout_timeout_status != 0 && logout_timeout_elapsed < 4.5 )) ||
  fail 'a hanging stale-session cleanup must fail within its production deadline'
[[ $logout_timeout_output ==
  'proton-pass-ensure-ready: provider-session cleanup timed out' ]] ||
  fail 'a stale-session cleanup timeout must report one fixed diagnostic'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogout --force' ]] ||
  fail 'a stale-session cleanup timeout must not attempt provider login'
grep -Fqx 'reason=logout-timeout' "$status_file" ||
  fail 'a stale-session cleanup timeout must record its value-free reason'
[[ -f $login_marker ]] ||
  fail 'a stale-session cleanup timeout must keep the login marker'
rm -f -- "$login_marker"
hanging_child_pid=$(<"$FAKE_HANGING_CHILD_PID")
! kill -0 $hanging_child_pid 2>/dev/null ||
  fail 'a timed-out stale-session cleanup child must be terminated and reaped'
test_process_fixture_untrack_pid_file "$FAKE_HANGING_CHILD_PID"

# The live pass-cli 2.3.3 incident: the provider dropped the session while local
# authentication remains, so login is refused until forced local cleanup.
rm -f -- "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOCAL_SESSION"
: > "$FAKE_PASS_REQUIRE_LOGOUT"
: > "$FAKE_PASS_INFO_ORPHANED"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
set +e
orphaned_output=$(zsh "$ensure_ready" 2>&1)
orphaned_status=$?
set -e
(( orphaned_status == 0 )) ||
  fail "an orphaned provider session must be repaired: $orphaned_output"
[[ -e $FAKE_PASS_REMOTE_SESSION ]] ||
  fail 'an orphaned provider session repair must establish remote readiness'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogout --force\nlogin\ninfo' ]] ||
  fail 'an orphaned provider session must be cleaned up before one repair login'
[[ $(<"$FAKE_SECRET_TOOL_LOG") == proton-bootstrap ]] ||
  fail 'an orphaned provider session must use the fixed bootstrap item'
grep -Fqx 'state=ready' "$status_file" &&
  grep -Fqx 'reason=repaired' "$status_file" ||
  fail 'an orphaned provider session repair must record its value-free reason'
assert_no_private_diagnostics 'an orphaned repair'

rm -f -- "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOCAL_SESSION"
: > "$FAKE_PASS_LOGOUT_FAIL"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
set +e
orphaned_logout_output=$(zsh "$ensure_ready" 2>&1)
orphaned_logout_status=$?
set -e
rm -f -- "$FAKE_PASS_LOGOUT_FAIL"
(( orphaned_logout_status != 0 )) ||
  fail 'a failed orphaned-session cleanup must fail readiness'
[[ $orphaned_logout_output ==
  'proton-pass-ensure-ready: provider-session cleanup failed' ]] ||
  fail 'a failed orphaned-session cleanup must report one fixed diagnostic'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogout --force' ]] ||
  fail 'a failed orphaned-session cleanup must not attempt provider login'
grep -Fqx 'reason=logout-failed' "$status_file" ||
  fail 'a failed orphaned-session cleanup must record its value-free reason'
# The marker covers the forced logout too, so a failed one leaves it behind.
[[ -f $login_marker ]] ||
  fail 'a failed orphaned-session cleanup must keep the login marker'
rm -f -- "$login_marker"
assert_no_private_diagnostics 'a failed orphaned-session cleanup'

rm -f -- "$FAKE_PASS_REMOTE_SESSION" "$FAKE_HANGING_CHILD_PID"
: > "$FAKE_PASS_LOCAL_SESSION"
: > "$FAKE_PASS_LOGOUT_HANG"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
test_process_fixture_track_pid_file "$FAKE_HANGING_CHILD_PID"
typeset -F orphaned_logout_timeout_started=$EPOCHREALTIME
set +e
orphaned_logout_timeout_output=$(zsh "$ensure_ready" 2>&1)
orphaned_logout_timeout_status=$?
set -e
typeset -F orphaned_logout_timeout_elapsed=$((
  EPOCHREALTIME - orphaned_logout_timeout_started ))
rm -f -- "$FAKE_PASS_LOGOUT_HANG"
(( orphaned_logout_timeout_status != 0 &&
  orphaned_logout_timeout_elapsed < 4.5 )) ||
  fail 'a hanging orphaned-session cleanup must fail within its production deadline'
[[ $orphaned_logout_timeout_output ==
  'proton-pass-ensure-ready: provider-session cleanup timed out' ]] ||
  fail 'an orphaned-session cleanup timeout must report one fixed diagnostic'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogout --force' ]] ||
  fail 'an orphaned-session cleanup timeout must not attempt provider login'
grep -Fqx 'reason=logout-timeout' "$status_file" ||
  fail 'an orphaned-session cleanup timeout must record its value-free reason'
[[ -f $login_marker ]] ||
  fail 'a timed-out orphaned-session cleanup must keep the login marker'
rm -f -- "$login_marker"
assert_no_private_diagnostics 'a timed-out orphaned-session cleanup'
hanging_child_pid=$(<"$FAKE_HANGING_CHILD_PID")
! kill -0 $hanging_child_pid 2>/dev/null ||
  fail 'a timed-out orphaned-session cleanup child must be terminated and reaped'
test_process_fixture_untrack_pid_file "$FAKE_HANGING_CHILD_PID"

rm -f -- "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOCAL_SESSION"
: > "$FAKE_NATIVE_STORE_LOCKED"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
set +e
orphaned_locked_output=$(zsh "$ensure_ready" 2>&1)
orphaned_locked_status=$?
set -e
rm -f -- "$FAKE_NATIVE_STORE_LOCKED" "$FAKE_PASS_REQUIRE_LOGOUT" \
  "$FAKE_PASS_INFO_ORPHANED"
(( orphaned_locked_status != 0 )) ||
  fail 'an orphaned session with a locked native store must fail readiness'
[[ $orphaned_locked_output ==
  'proton-pass-ensure-ready: the native bootstrap item is unavailable or locked' ]] ||
  fail 'an orphaned session with a locked native store must report the store failure'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo' ]] ||
  fail 'an orphaned session must not be cleaned up before the bootstrap item is read'
[[ -e $FAKE_PASS_LOCAL_SESSION ]] ||
  fail 'an orphaned session must keep local authentication while the native store is locked'
grep -Fqx 'reason=native-store-unavailable' "$status_file" ||
  fail 'an orphaned session with a locked native store must record its reason'

# The 2026-09-24 incident: the local database no longer matched the stored
# local key, so every info failed and nothing repaired it. The exact chain,
# optionally after the database engine's plain records, forces a local reset.
for undecryptable_variant in framed unframed; do
  rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
  print -r -- "$undecryptable_variant" >"$FAKE_PASS_INFO_UNDECRYPTABLE"
  : > "$FAKE_PASS_LOG"
  : > "$FAKE_SECRET_TOOL_LOG"
  set +e
  undecryptable_output=$(zsh "$ensure_ready" 2>&1)
  undecryptable_status=$?
  set -e
  (( undecryptable_status == 0 )) ||
    fail "an undecryptable $undecryptable_variant local store must be repaired: $undecryptable_output"
  [[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogout --force\nlogin\ninfo' ]] ||
    fail "an undecryptable $undecryptable_variant local store must be reset before one login"
  [[ $(<"$FAKE_SECRET_TOOL_LOG") == proton-bootstrap ]] ||
    fail 'an undecryptable local store repair must use the fixed bootstrap item'
  grep -Fqx 'reason=repaired' "$status_file" ||
    fail 'an undecryptable local store repair must record its value-free reason'
  assert_no_private_diagnostics "an undecryptable $undecryptable_variant local store"
done

for undecryptable_variant in main-record-framed styled-core-framed \
  blank-framed trailing-blank truncated; do
  rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
  print -r -- "$undecryptable_variant" >"$FAKE_PASS_INFO_UNDECRYPTABLE"
  : > "$FAKE_PASS_LOG"
  : > "$FAKE_SECRET_TOOL_LOG"
  set +e
  undecryptable_output=$(zsh "$ensure_ready" 2>&1)
  undecryptable_status=$?
  set -e
  rm -f -- "$FAKE_PASS_INFO_UNDECRYPTABLE"
  (( undecryptable_status != 0 )) ||
    fail "a $undecryptable_variant store diagnostic must not be classified"
  [[ $undecryptable_output ==
    'proton-pass-ensure-ready: provider-session readiness could not be classified' ]] ||
    fail "a $undecryptable_variant store diagnostic must remain unknown: $undecryptable_output"
  [[ $(<"$FAKE_PASS_LOG") == $'info\ninfo' ]] ||
    fail "a $undecryptable_variant store diagnostic must not reset local state"
  [[ ! -s $FAKE_SECRET_TOOL_LOG ]] ||
    fail "a $undecryptable_variant store diagnostic must not read the bootstrap item"
  grep -Fqx 'reason=session-state-unknown' "$status_file" ||
    fail "a $undecryptable_variant store diagnostic must record session-state-unknown"
  assert_no_private_diagnostics "a $undecryptable_variant store diagnostic"
done

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
: > "$FAKE_PASS_LOGIN_DELAY"
typeset -a readiness_pids
for attempt in {1..5}; do
  zsh "$ensure_ready" >"$test_dir/concurrent-$attempt.out" \
    2>"$test_dir/concurrent-$attempt.err" &
  readiness_pid=$!
  readiness_pids+=($readiness_pid)
  test_process_fixture_track_pid $readiness_pid
done
for readiness_pid in $readiness_pids; do
  if wait $readiness_pid; then
    test_process_fixture_untrack_pid $readiness_pid
  else
    test_process_fixture_untrack_pid $readiness_pid
    local_error_file=$test_dir/concurrent-${readiness_pids[(i)$readiness_pid]}.err
    [[ ! -s $local_error_file ]] || print -u2 -r -- "$(<$local_error_file)"
    fail 'concurrent ensure-ready invocation failed'
  fi
done
rm -f -- "$FAKE_PASS_LOGIN_DELAY"
login_count=$(/usr/bin/grep -Fxc login "$FAKE_PASS_LOG")
(( login_count == 1 )) ||
  fail 'concurrent ensure-ready invocations must perform exactly one login'

# Healthy readers share the lock: their first checks run side by side rather
# than in turn, and each reports the existing session.
reader_barrier=$test_dir/reader-barrier
rm -rf -- "$reader_barrier" "$reader_barrier.log"
mkdir -- "$reader_barrier"
: > "$FAKE_PASS_LOCAL_SESSION"
: > "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOG"
typeset -a shared_reader_pids=()
for attempt in 1 2; do
  FAKE_PASS_INFO_BARRIER=$reader_barrier zsh "$ensure_ready" \
    >"$test_dir/shared-reader-$attempt.out" 2>&1 &
  shared_reader_pids+=($!)
  test_process_fixture_track_pid $!
done
integer shared_reader_failures=0
for readiness_pid in $shared_reader_pids; do
  wait $readiness_pid || (( ++shared_reader_failures ))
  test_process_fixture_untrack_pid $readiness_pid
done
(( shared_reader_failures == 0 )) ||
  fail "concurrent healthy readers must both report ready: $(<"$test_dir/shared-reader-1.out") $(<"$test_dir/shared-reader-2.out")"
[[ $(<"$reader_barrier.log") == $'met\nmet' ]] ||
  fail "concurrent healthy readers must check side by side: $(<"$reader_barrier.log")"
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo' ]] ||
  fail "concurrent healthy readers must each take only the first check: $(<"$FAKE_PASS_LOG")"
grep -Fqx 'reason=existing-session' "$status_file" ||
  fail 'concurrent healthy readers must record the existing session'
rm -rf -- "$reader_barrier" "$reader_barrier.log"

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
: > "$FAKE_PASS_LOGIN_DELAY"
slow_repair_started=$test_dir/slow-repair-started
# From the owner's login, its login and verification outlast the waiter's
# shared wait and 6-second takeover window by about two seconds, so the waiter
# ends in the extended wait. Each delayed stage keeps about one second of
# headroom below its own deadline.
/usr/bin/env \
  FAKE_PASS_LOGIN_DELAY_SECONDS=7 \
  FAKE_PASS_INFO_DELAY_SECONDS=2 \
  PROVIDER_START_MARKER="$slow_repair_started" \
  zsh "$ensure_ready" >"$test_dir/slow-repair-owner.out" \
  2>"$test_dir/slow-repair-owner.err" &
slow_repair_owner_pid=$!
test_process_fixture_track_pid $slow_repair_owner_pid
integer slow_repair_start_polls=1000
while [[ ! -s $slow_repair_started && slow_repair_start_polls -gt 0 ]]; do
  (( --slow_repair_start_polls ))
  zselect -t 1 2>/dev/null || true
done
[[ -s $slow_repair_started ]] ||
  fail 'the slow repair owner must reach the provider login'
set +e
zsh "$ensure_ready" >"$test_dir/slow-repair-waiter.out" \
  2>"$test_dir/slow-repair-waiter.err"
slow_repair_waiter_status=$?
set -e
if wait $slow_repair_owner_pid; then
  slow_repair_owner_status=0
else
  slow_repair_owner_status=$?
fi
test_process_fixture_untrack_pid $slow_repair_owner_pid
rm -f -- "$FAKE_PASS_LOGIN_DELAY"
(( slow_repair_owner_status == 0 )) ||
  fail 'the slow repair owner must establish provider readiness'
(( slow_repair_waiter_status == 0 )) ||
  fail 'a concurrent readiness caller must wait for a valid slow repair'
[[ $(/usr/bin/grep -Fxc login "$FAKE_PASS_LOG") == 1 ]] ||
  fail 'a valid slow concurrent repair must perform exactly one login'
[[ ! -s $test_dir/slow-repair-owner.err &&
  ! -s $test_dir/slow-repair-waiter.err ]] ||
  fail 'a valid slow concurrent repair must not emit diagnostics'

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
: > "$FAKE_PASS_LOGIN_DELAY"
: > "$FAKE_PASS_LOGIN_FAIL"
failed_repair_started=$test_dir/failed-repair-started
# Same margins as the valid slow repair, with the cleanup after the failed
# login in place of verification.
/usr/bin/env \
  FAKE_PASS_LOGIN_DELAY_SECONDS=7 \
  FAKE_PASS_LOGOUT_DELAY_SECONDS=2 \
  PROVIDER_START_MARKER="$failed_repair_started" \
  zsh "$ensure_ready" >"$test_dir/failed-repair-owner.out" \
  2>"$test_dir/failed-repair-owner.err" &
failed_repair_owner_pid=$!
test_process_fixture_track_pid $failed_repair_owner_pid
integer failed_repair_start_polls=200
while [[ ! -s $failed_repair_started && failed_repair_start_polls -gt 0 ]]; do
  (( --failed_repair_start_polls ))
  zselect -t 1 2>/dev/null || true
done
[[ -s $failed_repair_started ]] ||
  fail 'the failed repair owner must reach the provider login'
set +e
zsh "$ensure_ready" >"$test_dir/failed-repair-waiter.out" \
  2>"$test_dir/failed-repair-waiter.err"
failed_repair_waiter_status=$?
set -e
if wait $failed_repair_owner_pid; then
  failed_repair_owner_status=0
else
  failed_repair_owner_status=$?
fi
test_process_fixture_untrack_pid $failed_repair_owner_pid
rm -f -- "$FAKE_PASS_LOGIN_DELAY" "$FAKE_PASS_LOGIN_FAIL"
(( failed_repair_owner_status != 0 )) ||
  fail 'the failed repair owner must report unavailable readiness'
(( failed_repair_waiter_status != 0 )) ||
  fail 'a waiter must fail when the slow repair owner does not establish readiness'
[[ $(<"$test_dir/failed-repair-owner.err") ==
  'proton-pass-ensure-ready: provider-session repair failed' ]] ||
  fail 'the failed repair owner must preserve its value-free diagnostic'
[[ $(<"$test_dir/failed-repair-waiter.err") ==
  'proton-pass-ensure-ready: the concurrent provider-session repair did not establish readiness' ]] ||
  fail 'the failed concurrent repair must preserve its value-free diagnostic'
[[ $(/usr/bin/grep -Fxc login "$FAKE_PASS_LOG") == 1 ]] ||
  fail 'a failed slow concurrent repair must not start a second login'
[[ $(<"$FAKE_SECRET_TOOL_LOG") == proton-bootstrap ]] ||
  fail 'a failed slow concurrent repair must not repeat the bootstrap lookup'
grep -Fqx 'reason=concurrent-repair-failed' "$status_file" ||
  fail 'a failed concurrent repair must record its value-free reason'

# A slow but healthy cleanup repair holds the lock longer than the old
# five-plus-thirteen-second wait; the waiter must still observe its success.
# Each delayed stage keeps one second of headroom below its own deadline.
info_call_count() {
  /usr/bin/grep -Fxc info "$FAKE_PASS_LOG" || true
}
rm -f -- "$FAKE_PASS_REMOTE_SESSION" "$test_dir/slow-cleanup-owner.exits"
: > "$FAKE_PASS_LOCAL_SESSION"
: > "$FAKE_PASS_REQUIRE_LOGOUT"
: > "$FAKE_PASS_INFO_ORPHANED"
: > "$FAKE_PASS_LOGIN_DELAY"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
/usr/bin/env \
  FAKE_PASS_INFO_DELAY_SECONDS=4.0 \
  FAKE_NATIVE_STORE_DELAY_SECONDS=2.0 \
  FAKE_PASS_LOGOUT_DELAY_SECONDS=2.0 \
  FAKE_PASS_LOGIN_DELAY_SECONDS=7.0 \
  FAKE_PASS_INFO_EXIT_LOG="$test_dir/slow-cleanup-owner.exits" \
  zsh "$ensure_ready" >"$test_dir/slow-cleanup-owner.out" \
  2>"$test_dir/slow-cleanup-owner.err" &
slow_cleanup_owner_pid=$!
test_process_fixture_track_pid $slow_cleanup_owner_pid
integer slow_cleanup_classify_polls=1000
while (( slow_cleanup_classify_polls-- > 0 &&
  $(info_call_count) < 2 )); do
  zselect -t 1 2>/dev/null || true
done
(( $(info_call_count) >= 2 )) ||
  fail 'the slow cleanup owner must reach its locked classification'
typeset -F slow_cleanup_waiter_started=$EPOCHREALTIME
set +e
zsh "$ensure_ready" >"$test_dir/slow-cleanup-waiter.out" \
  2>"$test_dir/slow-cleanup-waiter.err"
slow_cleanup_waiter_status=$?
set -e
if wait $slow_cleanup_owner_pid; then
  slow_cleanup_owner_status=0
else
  slow_cleanup_owner_status=$?
fi
test_process_fixture_untrack_pid $slow_cleanup_owner_pid
rm -f -- "$FAKE_PASS_LOGIN_DELAY" "$FAKE_PASS_REQUIRE_LOGOUT" \
  "$FAKE_PASS_INFO_ORPHANED"
(( slow_cleanup_owner_status == 0 )) ||
  fail "a slow healthy cleanup repair must establish readiness: $(<"$test_dir/slow-cleanup-owner.err")"
(( slow_cleanup_waiter_status == 0 )) ||
  fail "a waiter must outlast a slow healthy cleanup repair: $(<"$test_dir/slow-cleanup-waiter.err")"
# The waiter starts once the owner holds the lock to classify, and the owner
# holds it through its verification, so this bounds the waiter's lock wait.
slow_cleanup_owner_exits=("${(@f)$(<"$test_dir/slow-cleanup-owner.exits")}")
typeset -F slow_cleanup_lock_wait=$((
  slow_cleanup_owner_exits[-1] - slow_cleanup_waiter_started ))
(( slow_cleanup_lock_wait >= 18.5 )) ||
  fail "the slow cleanup fixture must hold the lock beyond the former wait: lock-wait=$slow_cleanup_lock_wait"
grep -Fqx 'reason=concurrent-repair' "$status_file" ||
  fail 'the waiter must record the concurrent repair it observed'
[[ $(/usr/bin/grep -Fxc login "$FAKE_PASS_LOG") == 1 &&
  $(/usr/bin/grep -Fxc 'logout --force' "$FAKE_PASS_LOG") == 1 ]] ||
  fail 'a slow healthy cleanup repair must clean up and log in exactly once'
[[ $(<"$FAKE_SECRET_TOOL_LOG") == proton-bootstrap ]] ||
  fail 'a slow healthy cleanup repair must read the bootstrap item once'
[[ ! -s $test_dir/slow-cleanup-owner.err &&
  ! -s $test_dir/slow-cleanup-waiter.err ]] ||
  fail 'a slow healthy cleanup repair must not emit diagnostics'

# A timed-out classifying probe must release the lock inside the takeover
# window of a caller that began waiting as the lock was taken, so that caller
# can still repair instead of failing as a concurrent waiter. The successor
# starts once the stalled owner holds the lock to classify, so its shared wait
# expires and it goes to the exclusive path without a first check.
takeover_values=("${(@f)$(<"$ensure_ready_source")}")
integer takeover_seconds=${${(M)takeover_values:#readonly PROTON_PASS_LOCK_TAKEOVER_SECONDS=*}#*=}
integer classify_seconds=${${(M)takeover_values:#readonly PROTON_PASS_CLASSIFY_PROBE_TIMEOUT_SECONDS=*}#*=}
(( classify_seconds > 0 && takeover_seconds >= classify_seconds + 1 )) ||
  fail "the takeover window must outlast a timed-out classifying probe: takeover=$takeover_seconds classify=$classify_seconds"
rm -f -- "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOCAL_SESSION"
: > "$FAKE_PASS_REQUIRE_LOGOUT"
: > "$FAKE_PASS_INFO_ORPHANED"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
/usr/bin/env FAKE_PASS_INFO_DELAY_SECONDS=30 \
  zsh "$ensure_ready" >"$test_dir/takeover-stalled.out" \
  2>"$test_dir/takeover-stalled.err" &
takeover_stalled_pid=$!
test_process_fixture_track_pid $takeover_stalled_pid
integer takeover_classify_polls=1000
while (( takeover_classify_polls-- > 0 &&
  $(info_call_count) < 2 )); do
  zselect -t 1 2>/dev/null || true
done
(( $(info_call_count) >= 2 )) ||
  fail 'the stalled lock owner must reach its classifying probe'
set +e
zsh "$ensure_ready" >"$test_dir/takeover-successor.out" \
  2>"$test_dir/takeover-successor.err"
takeover_successor_status=$?
set -e
if wait $takeover_stalled_pid; then
  takeover_stalled_status=0
else
  takeover_stalled_status=$?
fi
test_process_fixture_untrack_pid $takeover_stalled_pid
rm -f -- "$FAKE_PASS_REQUIRE_LOGOUT" "$FAKE_PASS_INFO_ORPHANED"
(( takeover_stalled_status != 0 )) &&
  [[ $(<"$test_dir/takeover-stalled.err") ==
    'proton-pass-ensure-ready: provider-session readiness check timed out' ]] ||
  fail 'the stalled lock owner must fail its classifying probe'
(( takeover_successor_status == 0 )) ||
  fail "a caller waiting behind a timed-out classification must take over: $(<"$test_dir/takeover-successor.err")"
[[ ! -s $test_dir/takeover-successor.err ]] ||
  fail 'a takeover repair must not emit diagnostics'
[[ $(/usr/bin/grep -Fxc login "$FAKE_PASS_LOG") == 1 &&
  $(/usr/bin/grep -Fxc 'logout --force' "$FAKE_PASS_LOG") == 1 ]] ||
  fail 'a takeover repair must clean up and log in exactly once'
# The owner's two checks, then only the successor's classification and
# verification.
[[ $(info_call_count) == 4 ]] ||
  fail "a successor whose shared wait expires must skip the first check: $(<"$FAKE_PASS_LOG")"
grep -Fqx 'reason=repaired' "$status_file" ||
  fail 'a takeover repair must record its value-free reason'
assert_no_private_diagnostics 'a takeover repair'

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
: > "$FAKE_NATIVE_STORE_LOCKED"
set +e
locked_output=$(zsh "$ensure_ready" 2>&1)
locked_status=$?
set -e
(( locked_status != 0 )) || fail 'a locked native store must fail readiness'
[[ $locked_output ==
  'proton-pass-ensure-ready: the native bootstrap item is unavailable or locked' ]] ||
  fail 'a locked native store must report one value-free error'
! /usr/bin/grep -Fqx login "$FAKE_PASS_LOG" ||
  fail 'a locked native store must not attempt provider login'
grep -Fqx 'state=unavailable' "$status_file" ||
  fail 'a locked native store must record unavailable status'
grep -Fqx 'reason=native-store-unavailable' "$status_file" ||
  fail 'a locked native store must record its value-free reason'
rm -f -- "$FAKE_NATIVE_STORE_LOCKED"

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION" \
  "$FAKE_DESCENDANT_PID" "$FAKE_DESCENDANT_TOKEN_MARKER"
: > "$FAKE_PASS_LOG"
: > "$FAKE_NATIVE_STORE_DESCENDANT"
test_process_fixture_track_pid_file "$FAKE_DESCENDANT_PID"
zmodload zsh/datetime
typeset -F hang_started=$EPOCHREALTIME
if [[ -n $kill_audit_library ]]; then
  LD_PRELOAD=$kill_audit_library \
    NEGATIVE_PGID_KILL_AUDIT_LOG=$kill_audit_log \
    zsh "$ensure_ready" >"$test_dir/native-descendant.out" \
      2>"$test_dir/native-descendant.err" &
else
  zsh "$ensure_ready" >"$test_dir/native-descendant.out" \
    2>"$test_dir/native-descendant.err" &
fi
native_entrypoint_pid=$!
test_process_fixture_track_pid $native_entrypoint_pid
typeset -F native_harness_deadline=$(( hang_started + 4.0 ))
integer native_harness_expired=0
while kill -0 $native_entrypoint_pid 2>/dev/null; do
  if (( EPOCHREALTIME >= native_harness_deadline )); then
    native_harness_expired=1
    kill -TERM $native_entrypoint_pid 2>/dev/null || true
    zselect -t 10 || true
    kill -0 $native_entrypoint_pid 2>/dev/null && \
      kill -KILL $native_entrypoint_pid 2>/dev/null || true
    break
  fi
  zselect -t 1 || true
done
if wait $native_entrypoint_pid; then
  hanging_status=0
else
  hanging_status=$?
fi
test_process_fixture_untrack_pid $native_entrypoint_pid
hanging_output=$(<"$test_dir/native-descendant.err")
typeset -F hang_elapsed=$(( EPOCHREALTIME - hang_started ))
descendant_pid=$(<"$FAKE_DESCENDANT_PID")
integer native_descendant_survived=0
if ! test_process_fixture_wait_for_pid_exit $descendant_pid; then
  native_descendant_survived=1
  kill -KILL $descendant_pid 2>/dev/null || true
  test_process_fixture_wait_for_pid_exit $descendant_pid 100 || true
fi
test_process_fixture_untrack_pid_file "$FAKE_DESCENDANT_PID"
rm -f -- "$FAKE_NATIVE_STORE_DESCENDANT"
(( ! native_harness_expired && hanging_status != 0 && hang_elapsed < 4.0 )) ||
  fail 'a forked native-store descendant must fail within the production deadline'
[[ $hanging_output ==
  'proton-pass-ensure-ready: the native bootstrap item lookup timed out' ]] ||
  fail 'a native-store timeout must report one value-free error'
grep -Fqx 'reason=native-store-timeout' "$status_file" ||
  fail 'a native-store timeout must record its value-free reason'
(( ! native_descendant_survived )) ||
  fail 'a timed-out native-store process group must leave no surviving descendant'
[[ ! -s $kill_audit_log ]] ||
  fail "readiness cleanup must never signal a numeric process group after observing it absent: $(<$kill_audit_log)"

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOG"
: > "$FAKE_NATIVE_STORE_BAD_VALUE"
set +e
invalid_output=$(zsh "$ensure_ready" 2>&1)
invalid_status=$?
set -e
(( invalid_status != 0 )) || fail 'a multiline bootstrap value must fail readiness'
[[ $invalid_output ==
  'proton-pass-ensure-ready: the native bootstrap item must contain one non-empty line' ]] ||
  fail 'an invalid bootstrap value must report one value-free error'
grep -Fqx 'reason=invalid-bootstrap-value' "$status_file" ||
  fail 'an invalid bootstrap value must record its value-free reason'
! /usr/bin/grep -Fqx login "$FAKE_PASS_LOG" ||
  fail 'an invalid bootstrap value must not attempt provider login'
rm -f -- "$FAKE_NATIVE_STORE_BAD_VALUE"

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOG"
: > "$FAKE_PASS_LOGIN_FAIL"
set +e
login_failure_output=$(zsh "$ensure_ready" 2>&1)
login_failure_status=$?
set -e
(( login_failure_status != 0 )) || fail 'a failed provider login must fail readiness'
[[ $login_failure_output ==
  'proton-pass-ensure-ready: provider-session repair failed' ]] ||
  fail 'a failed provider login must report one value-free error'
grep -Fqx 'reason=login-failed' "$status_file" ||
  fail 'a failed provider login must record its value-free reason'
grep -Fqx 'waiter-stage=child-status' "$status_file" ||
  fail 'a reported nonzero login status must record child-status'
rm -f -- "$FAKE_PASS_LOGIN_FAIL"

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOG"
: > "$FAKE_PASS_LOGIN_EXIT_124"
set +e
login_124_output=$(zsh "$ensure_ready" 2>&1)
login_124_status=$?
set -e
(( login_124_status != 0 )) ||
  fail 'a provider-reported status 124 must fail readiness'
[[ $login_124_output ==
  'proton-pass-ensure-ready: provider-session repair failed' ]] ||
  fail 'provider-reported status 124 must not be classified as a waiter timeout'
grep -Fqx 'reason=login-failed' "$status_file" ||
  fail 'provider-reported status 124 must preserve login-failed'
grep -Fqx 'waiter-stage=child-status' "$status_file" ||
  fail 'provider-reported status 124 must record child-status'
rm -f -- "$FAKE_PASS_LOGIN_EXIT_124"
assert_no_private_diagnostics 'a failed provider login'

# Classic absent info with stale local authentication: login refuses locally.
rm -f -- "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOCAL_SESSION"
: > "$FAKE_PASS_REQUIRE_LOGOUT"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
set +e
already_authenticated_output=$(zsh "$ensure_ready" 2>&1)
already_authenticated_status=$?
set -e
rm -f -- "$FAKE_PASS_REQUIRE_LOGOUT"
(( already_authenticated_status != 0 )) ||
  fail 'a login refused for stored local authentication must fail readiness'
[[ $already_authenticated_output ==
  'proton-pass-ensure-ready: provider login refused: a local provider session is still authenticated' ]] ||
  fail "a refused login must report its fixed diagnostic: $already_authenticated_output"
grep -Fqx 'reason=login-already-authenticated' "$status_file" ||
  fail 'a refused login must record its value-free reason'
grep -Fqx 'waiter-stage=child-status' "$status_file" ||
  fail 'a refused login must record child-status'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogin' ]] ||
  fail 'a classified absent session must never be logged out'
[[ -e $FAKE_PASS_LOCAL_SESSION ]] ||
  fail 'a refused login must preserve local authentication'
assert_no_private_diagnostics 'a refused login'

typeset -A login_diagnostic_reasons=(
  token-rejected login-token-rejected
  malformed-format login-token-malformed
  malformed-prefix login-token-malformed
  malformed-length login-token-malformed
  session-refused login-session-refused
  malformed-key login-failed
  bad-response login-failed
  already-authenticated-trailing-space login-failed
  already-authenticated-blank-line login-failed
  already-authenticated-crlf login-failed
  already-authenticated-traced login-failed
  already-authenticated-backtrace login-failed
  already-authenticated-oversized login-failed
  token-echo login-failed
)
typeset -A login_reason_messages=(
  login-token-rejected 'the provider rejected the bootstrap token as invalid, expired, or deleted'
  login-token-malformed 'the bootstrap token is not a well-formed personal access token'
  login-session-refused 'the provider refused to open a login session'
  login-failed 'provider-session repair failed'
)
for login_diagnostic in ${(ko)login_diagnostic_reasons}; do
  expected_login_reason=${login_diagnostic_reasons[$login_diagnostic]}
  rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
  print -r -- "$login_diagnostic" >"$FAKE_PASS_LOGIN_DIAGNOSTIC"
  : >"$FAKE_PASS_LOG"
  set +e
  login_diagnostic_output=$(zsh "$ensure_ready" 2>&1)
  login_diagnostic_status=$?
  set -e
  (( login_diagnostic_status != 0 )) ||
    fail "the $login_diagnostic login diagnostic must fail readiness"
  [[ $login_diagnostic_output ==
    "proton-pass-ensure-ready: ${login_reason_messages[$expected_login_reason]}" ]] ||
    fail "the $login_diagnostic login diagnostic must report its fixed message: $login_diagnostic_output"
  grep -Fqx "reason=$expected_login_reason" "$status_file" ||
    fail "the $login_diagnostic login diagnostic must record $expected_login_reason"
  grep -Fqx 'waiter-stage=child-status' "$status_file" ||
    fail "the $login_diagnostic login diagnostic must record child-status"
  [[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogin\nlogout --force' ]] ||
    fail "the $login_diagnostic login diagnostic must follow one absent repair and clear the failed login"
  assert_no_private_diagnostics "the $login_diagnostic login diagnostic"
  ! print -r -- "$login_diagnostic_output" |
    /usr/bin/grep -F -e "$fixture_token" -e 'Already authenticated' >/dev/null ||
    fail "the $login_diagnostic login diagnostic must not echo provider output"
done
! /usr/bin/grep -RF -e "$fixture_token" -e 'Already authenticated' \
  "$state_home" "$FAKE_PASS_LOG" >/dev/null ||
  fail 'provider login diagnostics must never persist in state or logs'

# An interrupted login leaves local authentication that passes info while item
# reads fail. The helper must force it out, or every later readiness check
# reports the unusable session as ready and repair never runs again.
rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION" \
  "$FAKE_HANGING_CHILD_PID" "$FAKE_PASS_LOGIN_DIAGNOSTIC"
: > "$FAKE_PASS_LOG"
: > "$FAKE_PASS_LOGIN_PARTIAL_HANG"
test_process_fixture_track_pid_file "$FAKE_HANGING_CHILD_PID"
set +e
partial_login_output=$(zsh "$ensure_ready" 2>&1)
partial_login_status=$?
set -e
rm -f -- "$FAKE_PASS_LOGIN_PARTIAL_HANG"
hanging_child_pid=$(<"$FAKE_HANGING_CHILD_PID")
test_process_fixture_wait_for_pid_exit $hanging_child_pid 100 ||
  fail 'a timed-out partial login child must be terminated and reaped'
test_process_fixture_untrack_pid_file "$FAKE_HANGING_CHILD_PID"
(( partial_login_status != 0 )) ||
  fail 'a timed-out partial login must fail readiness'
[[ $partial_login_output ==
  'proton-pass-ensure-ready: provider-session repair timed out' ]] ||
  fail "a timed-out partial login must report its timeout: $partial_login_output"
grep -Fqx 'reason=login-timeout' "$status_file" ||
  fail 'a timed-out partial login must record login-timeout'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogin\nlogout --force' ]] ||
  fail 'a timed-out login must force out its partial local authentication'
[[ ! -e $FAKE_PASS_LOCAL_SESSION ]] ||
  fail 'a timed-out login must not leave partial local authentication'
[[ ! -e $login_marker ]] ||
  fail 'a login whose cleanup succeeded must clear its login marker'
assert_no_private_diagnostics 'a timed-out partial login'
: > "$FAKE_PASS_LOG"
zsh "$ensure_ready" ||
  fail 'readiness must recover once a partial login has been forced out'
grep -Fqx 'reason=repaired' "$status_file" ||
  fail 'the call after a forced-out partial login must repair, not reuse it'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogin\ninfo' ]] ||
  fail 'the call after a forced-out partial login must log in again'

# When that cleanup fails, the unusable session may survive, so the cleanup
# failure is the reported reason.
rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION" \
  "$FAKE_HANGING_CHILD_PID"
: > "$FAKE_PASS_LOG"
: > "$FAKE_PASS_LOGIN_PARTIAL_HANG"
: > "$FAKE_PASS_LOGOUT_FAIL"
test_process_fixture_track_pid_file "$FAKE_HANGING_CHILD_PID"
set +e
partial_cleanup_output=$(zsh "$ensure_ready" 2>&1)
partial_cleanup_status=$?
set -e
rm -f -- "$FAKE_PASS_LOGIN_PARTIAL_HANG" "$FAKE_PASS_LOGOUT_FAIL"
hanging_child_pid=$(<"$FAKE_HANGING_CHILD_PID")
test_process_fixture_wait_for_pid_exit $hanging_child_pid 100 ||
  fail 'a partial login child must be reaped when its cleanup fails'
test_process_fixture_untrack_pid_file "$FAKE_HANGING_CHILD_PID"
(( partial_cleanup_status != 0 )) ||
  fail 'a failed partial-login cleanup must fail readiness'
[[ $partial_cleanup_output ==
  'proton-pass-ensure-ready: provider-session cleanup failed' ]] ||
  fail "a failed partial-login cleanup must report it: $partial_cleanup_output"
grep -Fqx 'reason=logout-failed' "$status_file" ||
  fail 'a failed partial-login cleanup must record logout-failed'
# The recorded stage is the cleanup's reported exit, not the login's timeout.
grep -Fqx 'waiter-stage=child-status' "$status_file" ||
  fail 'a failed partial-login cleanup must record its own waiter stage'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogin\nlogout --force' ]] ||
  fail 'a failed partial-login cleanup must run exactly once after login'
[[ -e $FAKE_PASS_LOCAL_SESSION ]] ||
  fail 'the fixture must model the unusable session surviving a failed cleanup'
[[ -f $login_marker ]] ||
  fail 'a failed partial-login cleanup must keep its login marker'
assert_no_private_diagnostics 'a failed partial-login cleanup'
# The next call forces out what the failed cleanup left, then logs in again.
: > "$FAKE_PASS_LOG"
zsh "$ensure_ready" ||
  fail 'readiness must recover behind a login marker left by a failed cleanup'
[[ $(<"$FAKE_PASS_LOG") == $'info\nlogout --force\nlogin\ninfo' ]] ||
  fail "a login marker must skip the shared first check and force a local reset: $(<"$FAKE_PASS_LOG")"
grep -Fqx 'reason=repaired' "$status_file" ||
  fail 'the call behind a login marker must record a repair'
[[ ! -e $login_marker ]] ||
  fail 'the verified repair behind a login marker must clear it'
rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"

# When login and its cleanup both hang, the cleanup timeout is reported, both
# children are reaped, and the call ends within the two production deadlines.
rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION" \
  "$FAKE_HANGING_CHILD_PID"
export FAKE_HANGING_CHILD_PIDS=$test_dir/hanging-children.pids
: > "$FAKE_HANGING_CHILD_PIDS"
: > "$FAKE_PASS_LOG"
: > "$FAKE_PASS_LOGIN_PARTIAL_HANG"
: > "$FAKE_PASS_LOGOUT_HANG"
test_process_fixture_track_pid_list_file "$FAKE_HANGING_CHILD_PIDS"
typeset -F partial_cleanup_hang_started=$EPOCHREALTIME
set +e
partial_cleanup_hang_output=$(zsh "$ensure_ready" 2>&1)
partial_cleanup_hang_status=$?
set -e
typeset -F partial_cleanup_hang_elapsed=$((
  EPOCHREALTIME - partial_cleanup_hang_started ))
rm -f -- "$FAKE_PASS_LOGIN_PARTIAL_HANG" "$FAKE_PASS_LOGOUT_HANG"
typeset -a partial_cleanup_hang_pids=(${(f)"$(<"$FAKE_HANGING_CHILD_PIDS")"})
(( ${#partial_cleanup_hang_pids} == 2 )) ||
  fail 'a hanging login and its hanging cleanup must each start one child'
for hanging_child_pid in $partial_cleanup_hang_pids; do
  test_process_fixture_wait_for_pid_exit $hanging_child_pid 100 ||
    fail 'a hanging login and its hanging cleanup must both be reaped'
done
(( partial_cleanup_hang_status != 0 )) ||
  fail 'a hanging partial-login cleanup must fail readiness'
(( partial_cleanup_hang_elapsed >= 10.5 &&
  partial_cleanup_hang_elapsed < 14.0 )) ||
  fail "a hanging login and cleanup must use both production deadlines: elapsed=$partial_cleanup_hang_elapsed"
[[ $partial_cleanup_hang_output ==
  'proton-pass-ensure-ready: provider-session cleanup timed out' ]] ||
  fail "a hanging partial-login cleanup must report it: $partial_cleanup_hang_output"
grep -Fqx 'reason=logout-timeout' "$status_file" ||
  fail 'a hanging partial-login cleanup must record logout-timeout'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogin\nlogout --force' ]] ||
  fail 'a hanging partial-login cleanup must run exactly once after login'
[[ -f $login_marker ]] ||
  fail 'a hanging partial-login cleanup must keep its login marker'
rm -f -- "$login_marker"
assert_no_private_diagnostics 'a hanging partial-login cleanup'
rm -f -- "$FAKE_HANGING_CHILD_PIDS"
export FAKE_HANGING_CHILD_PIDS=
rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"

# Stored local authentication that info already reported absent is not usable,
# so a failed login forces it out along with anything the login stored.
rm -f -- "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOCAL_SESSION"
: > "$FAKE_PASS_LOGIN_FAIL"
: > "$FAKE_PASS_LOG"
set +e
absent_stored_output=$(zsh "$ensure_ready" 2>&1)
absent_stored_status=$?
set -e
rm -f -- "$FAKE_PASS_LOGIN_FAIL"
(( absent_stored_status != 0 )) ||
  fail 'a failed login over absent stored authentication must fail readiness'
[[ $absent_stored_output ==
  'proton-pass-ensure-ready: provider-session repair failed' ]] ||
  fail "a failed login over absent stored authentication must report it: $absent_stored_output"
grep -Fqx 'reason=login-failed' "$status_file" ||
  fail 'a failed login over absent stored authentication must record login-failed'
[[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogin\nlogout --force' ]] ||
  fail 'a failed login over absent stored authentication must force it out'
[[ ! -e $FAKE_PASS_LOCAL_SESSION ]] ||
  fail 'a failed login must not leave absent stored authentication behind'
[[ ! -e $login_marker ]] ||
  fail 'a failed login whose cleanup succeeded must clear its login marker'
assert_no_private_diagnostics 'a failed login over absent stored authentication'

# A recognized refusal is not classified when the waiter times out.
rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION" \
  "$FAKE_HANGING_CHILD_PID"
print -r -- already-authenticated-hang >"$FAKE_PASS_LOGIN_DIAGNOSTIC"
: > "$FAKE_PASS_LOG"
test_process_fixture_track_pid_file "$FAKE_HANGING_CHILD_PID"
typeset -F recognized_hang_started=$EPOCHREALTIME
set +e
recognized_hang_output=$(zsh "$ensure_ready" 2>&1)
recognized_hang_status=$?
set -e
typeset -F recognized_hang_elapsed=$(( EPOCHREALTIME - recognized_hang_started ))
rm -f -- "$FAKE_PASS_LOGIN_DIAGNOSTIC"
# The login deadline; the instant forced cleanup adds well under a second.
(( recognized_hang_status != 0 && recognized_hang_elapsed < 9.5 )) ||
  fail 'a hanging login must fail within its production deadlines'
[[ $recognized_hang_output ==
  'proton-pass-ensure-ready: provider-session repair timed out' ]] ||
  fail 'a hanging login must remain a timeout despite recognized diagnostics'
grep -Fqx 'reason=login-timeout' "$status_file" ||
  fail 'a hanging login must record login-timeout'
grep -Fqx 'waiter-stage=unrecorded' "$status_file" ||
  fail 'a hanging login must not classify its captured diagnostics'
hanging_child_pid=$(<"$FAKE_HANGING_CHILD_PID")
! kill -0 $hanging_child_pid 2>/dev/null ||
  fail 'a timed-out login child must be terminated and reaped'
test_process_fixture_untrack_pid_file "$FAKE_HANGING_CHILD_PID"
assert_no_private_diagnostics 'a timed-out login'

# A signal during login releases the private diagnostic capture before
# teardown; the capture is unlinked before login starts, so no name remains.
rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION" \
  "$FAKE_HANGING_CHILD_PID"
: > "$FAKE_PASS_LOG"
: > "$FAKE_PASS_LOGIN_STDERR_LOG"
: > "$FAKE_PASS_LOGIN_HANG"
test_process_fixture_track_pid_file "$FAKE_HANGING_CHILD_PID"
zsh "$ensure_ready" >"$test_dir/login-signal.out" \
  2>"$test_dir/login-signal.err" &
login_signal_pid=$!
test_process_fixture_track_pid $login_signal_pid
integer login_signal_polls=500
while (( login_signal_polls-- > 0 )) && [[ ! -s $FAKE_HANGING_CHILD_PID ]]; do
  zselect -t 1 2>/dev/null || true
done
login_signal_artifacts=(
  "$state_home/secret-exec"/.proton-pass-login-diagnostic.*(N)
)
kill -TERM $login_signal_pid 2>/dev/null || true
if wait $login_signal_pid; then
  login_signal_status=0
else
  login_signal_status=$?
fi
test_process_fixture_untrack_pid $login_signal_pid
rm -f -- "$FAKE_PASS_LOGIN_HANG"
(( ${#login_signal_artifacts} == 0 )) ||
  fail 'a hanging login must not leave its private diagnostics under a name'
[[ $(<"$FAKE_PASS_LOGIN_STDERR_LOG") == regular:600:links=0:* ]] ||
  fail 'a hanging login must write diagnostics to one private unlinked file'
(( login_signal_status == 143 )) ||
  fail "TERM during login must preserve status 143: status=$login_signal_status"
# A signalled login may have stored a partial session, so its marker stays.
zmodload zsh/stat
typeset -A login_marker_metadata
[[ -f $login_marker && ! -L $login_marker ]] &&
  zstat -H login_marker_metadata -- "$login_marker" &&
  (( (login_marker_metadata[mode] & 8#777) == 8#600 )) ||
  fail 'a signalled login must keep one private login marker'
[[ $(<"$login_marker") == started_at=<-> ]] ||
  fail 'the login marker must hold only its value-free start time'
rm -f -- "$login_marker"
assert_no_private_diagnostics 'a signal during login'
hanging_child_pid=$(<"$FAKE_HANGING_CHILD_PID")
test_process_fixture_wait_for_pid_exit $hanging_child_pid 100 ||
  fail 'TERM during login must terminate and reap the login child'
test_process_fixture_untrack_pid_file "$FAKE_HANGING_CHILD_PID"

# An uncatchable kill during login cannot run cleanup traps, so the private
# diagnostic capture must already have no name in the state directory.
rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION" \
  "$FAKE_HANGING_CHILD_PID"
[[ ! -e $login_marker ]] ||
  fail 'the killed-login fixture must start without a login marker'
: > "$FAKE_PASS_LOG"
: > "$FAKE_PASS_LOGIN_HANG"
test_process_fixture_track_pid_file "$FAKE_HANGING_CHILD_PID"
zsh "$ensure_ready" >"$test_dir/login-kill.out" \
  2>"$test_dir/login-kill.err" &
login_kill_pid=$!
test_process_fixture_track_pid $login_kill_pid
integer login_kill_polls=500
while (( login_kill_polls-- > 0 )) && [[ ! -s $FAKE_HANGING_CHILD_PID ]]; do
  zselect -t 1 2>/dev/null || true
done
[[ -s $FAKE_HANGING_CHILD_PID ]] ||
  fail 'the killed-login fixture must reach the provider login'
kill -KILL $login_kill_pid 2>/dev/null || true
wait $login_kill_pid 2>/dev/null || true
test_process_fixture_untrack_pid $login_kill_pid
rm -f -- "$FAKE_PASS_LOGIN_HANG"
assert_no_private_diagnostics 'a killed readiness helper'
hanging_child_pid=$(<"$FAKE_HANGING_CHILD_PID")
test_process_fixture_wait_for_pid_exit $hanging_child_pid 100 ||
  fail 'a killed readiness helper must not leave its login child running'
test_process_fixture_untrack_pid_file "$FAKE_HANGING_CHILD_PID"
[[ -f $login_marker ]] ||
  fail 'a killed readiness helper must leave its login marker for the next call'

# The #316 case: the killed login stored a session that info accepts while its
# private token key is missing. The marker makes the next call reset it.
: > "$FAKE_PASS_LOCAL_SESSION"
: > "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOG"
zsh "$ensure_ready" ||
  fail 'readiness must repair a partial session left by a killed helper'
[[ $(<"$FAKE_PASS_LOG") == $'info\nlogout --force\nlogin\ninfo' ]] ||
  fail "a partial session behind a login marker must be reset, not reused: $(<"$FAKE_PASS_LOG")"
grep -Fqx 'reason=repaired' "$status_file" ||
  fail 'a partial session behind a login marker must record a repair'
[[ ! -e $login_marker ]] ||
  fail 'the repair of a partial session must clear its login marker'
: > "$FAKE_PASS_LOG"
zsh "$ensure_ready" ||
  fail 'the repaired session must stay ready'
[[ $(<"$FAKE_PASS_LOG") == info ]] ||
  fail 'without a login marker, a ready session must take the shared first check'

# An unclassified check behind a marker keeps both the session and the marker.
rm -f -- "$FAKE_PASS_REMOTE_SESSION" "$FAKE_HANGING_CHILD_PID"
print -r -- started_at=1 >"$login_marker"
: > "$FAKE_PASS_INFO_HANG"
: > "$FAKE_PASS_LOG"
test_process_fixture_track_pid_file "$FAKE_HANGING_CHILD_PID"
set +e
marker_timeout_output=$(zsh "$ensure_ready" 2>&1)
marker_timeout_status=$?
set -e
rm -f -- "$FAKE_PASS_INFO_HANG"
hanging_child_pid=$(<"$FAKE_HANGING_CHILD_PID")
test_process_fixture_wait_for_pid_exit $hanging_child_pid 100 ||
  fail 'a timed-out check behind a login marker must reap its child'
test_process_fixture_untrack_pid_file "$FAKE_HANGING_CHILD_PID"
(( marker_timeout_status != 0 )) ||
  fail 'a timed-out check behind a login marker must fail readiness'
[[ $marker_timeout_output ==
  'proton-pass-ensure-ready: provider-session readiness check timed out' ]] ||
  fail "a timed-out check behind a login marker must report the timeout: $marker_timeout_output"
[[ $(<"$FAKE_PASS_LOG") == info ]] ||
  fail 'a timed-out check behind a login marker must not reset local state'
[[ -f $login_marker && -e $FAKE_PASS_LOCAL_SESSION ]] ||
  fail 'a timed-out check must keep the login marker and the local session'
rm -f -- "$login_marker" "$FAKE_PASS_LOCAL_SESSION"

# An unusable marker is never followed or replaced, and it stops the call
# before any check or reset touches a working session.
login_marker_target=$test_dir/login-marker-target
print -r -- untouched >"$login_marker_target"
: > "$FAKE_PASS_LOCAL_SESSION"
: > "$FAKE_PASS_REMOTE_SESSION"
for marker_kind in symlink directory; do
  case $marker_kind in
    symlink) ln -s -- "$login_marker_target" "$login_marker" ;;
    directory) mkdir -- "$login_marker" ;;
  esac
  : > "$FAKE_PASS_LOG"
  : > "$FAKE_SECRET_TOOL_LOG"
  set +e
  marker_unusable_output=$(zsh "$ensure_ready" 2>&1)
  marker_unusable_status=$?
  set -e
  (( marker_unusable_status != 0 )) ||
    fail "a $marker_kind login marker must fail readiness"
  [[ $marker_unusable_output ==
    'proton-pass-ensure-ready: the login marker must be a regular file' ]] ||
    fail "a $marker_kind login marker must report it: $marker_unusable_output"
  [[ ! -s $FAKE_PASS_LOG && ! -s $FAKE_SECRET_TOOL_LOG ]] ||
    fail "a $marker_kind login marker must stop before any provider or store call"
  [[ -e $FAKE_PASS_LOCAL_SESSION && -e $FAKE_PASS_REMOTE_SESSION ]] ||
    fail "a $marker_kind login marker must leave the session untouched"
  grep -Fqx 'reason=login-marker-failed' "$status_file" &&
    grep -Fqx 'last-failure-reason=login-marker-failed' "$status_file" ||
    fail "a $marker_kind login marker must record login-marker-failed"
  case $marker_kind in
    symlink)
      [[ -L $login_marker && $(<"$login_marker_target") == untouched ]] ||
        fail 'a symbolic-link login marker must not be followed'
      rm -f -- "$login_marker"
      ;;
    directory)
      [[ -d $login_marker && -z $(print -r -- "$login_marker"/*(DN)) ]] ||
        fail 'a directory login marker must be left as found'
      rmdir -- "$login_marker"
      ;;
  esac
done
rm -f -- "$login_marker_target" "$FAKE_PASS_LOCAL_SESSION" \
  "$FAKE_PASS_REMOTE_SESSION"

# A failed repair stores a partial session, then forces it out and clears its
# marker. A fast check that runs beside it can read that session before the
# cleanup and finish after the marker is gone, so a marker check cannot catch
# it. The reader's check starts first and waits for a session; the repair's
# login stores one and fails once the reader records what it saw. The reader
# must never report that session ready.
partial_race_window=$test_dir/partial-race-window
rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION" \
  "$partial_race_window"
: > "$FAKE_PASS_LOG"
: > "$FAKE_PASS_LOGIN_PARTIAL_FAIL"
/usr/bin/env \
  FAKE_PASS_INFO_AWAIT_SESSION_ONCE="$partial_race_window" \
  FAKE_PASS_INFO_HOLD_WHILE="$login_marker" \
  zsh "$ensure_ready" >"$test_dir/partial-race-reader.out" 2>&1 &
partial_race_reader_pid=$!
test_process_fixture_track_pid $partial_race_reader_pid
zmodload zsh/zselect
integer partial_race_polls=500
# The reader's check is running once its info call is logged.
while (( partial_race_polls-- > 0 )) && [[ ! -s $FAKE_PASS_LOG ]]; do
  zselect -t 1 2>/dev/null || true
done
[[ -s $FAKE_PASS_LOG ]] || fail 'the racing reader must start its check'
set +e
/usr/bin/env FAKE_PASS_LOGIN_PARTIAL_GATE="$partial_race_window" \
  zsh "$ensure_ready" >"$test_dir/partial-race-repair.out" 2>&1
partial_race_repair_status=$?
wait $partial_race_reader_pid
partial_race_reader_status=$?
set -e
test_process_fixture_untrack_pid $partial_race_reader_pid
rm -f -- "$FAKE_PASS_LOGIN_PARTIAL_FAIL"
(( partial_race_repair_status != 0 )) ||
  fail 'the racing repair fixture must fail its login'
(( partial_race_reader_status != 0 )) &&
  ! grep -Fqx 'reason=existing-session' "$status_file" ||
  fail "a check beside a failed repair must not report its partial session ready: status=$partial_race_reader_status check=$(<"$partial_race_window") output=$(<"$test_dir/partial-race-reader.out")"
[[ $(<"$partial_race_window") == missed ]] ||
  fail 'a fast check must not overlap a repair that stores a partial session'
[[ $(<"$test_dir/partial-race-reader.out") ==
  'proton-pass-ensure-ready: provider-session repair failed' ]] ||
  fail "the reader must repair after the failed repair, not reuse it: $(<"$test_dir/partial-race-reader.out")"
[[ ! -e $FAKE_PASS_LOCAL_SESSION && ! -e $login_marker ]] ||
  fail 'failed repairs must leave neither a partial session nor a marker'

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION" \
  "$FAKE_DESCENDANT_PID" "$FAKE_DESCENDANT_TOKEN_MARKER"
: > "$FAKE_PASS_LOG"
: > "$FAKE_PASS_LOGIN_DESCENDANT"
test_process_fixture_track_pid_file "$FAKE_DESCENDANT_PID"
typeset -F login_timeout_started=$EPOCHREALTIME
set +e
login_timeout_output=$(zsh "$ensure_ready" 2>&1)
login_timeout_status=$?
set -e
typeset -F login_timeout_elapsed=$(( EPOCHREALTIME - login_timeout_started ))
descendant_pid=$(<"$FAKE_DESCENDANT_PID")
integer login_descendant_survived=0
if ! test_process_fixture_wait_for_pid_exit $descendant_pid; then
  login_descendant_survived=1
  kill -KILL $descendant_pid 2>/dev/null || true
  test_process_fixture_wait_for_pid_exit $descendant_pid 100 || true
fi
test_process_fixture_untrack_pid_file "$FAKE_DESCENDANT_PID"
rm -f -- "$FAKE_PASS_LOGIN_DESCENDANT"
(( login_timeout_status != 0 )) ||
  fail 'a provider login with a surviving descendant must fail readiness'
# The login deadline; the instant forced cleanup adds well under a second.
(( login_timeout_elapsed < 9.5 )) ||
  fail 'a provider-login process group must fail within the production deadlines'
[[ $login_timeout_output ==
  'proton-pass-ensure-ready: provider-session repair timed out' ]] ||
  fail 'a provider-login timeout must report one value-free error'
grep -Fqx 'reason=login-timeout' "$status_file" ||
  fail 'a provider-login timeout must record its value-free reason'
grep -Fqx 'waiter-stage=unrecorded' "$status_file" ||
  fail 'a true waiter timeout must not be classified as child-status'
[[ -e $FAKE_DESCENDANT_TOKEN_MARKER ]] ||
  fail 'the login descendant fixture must inherit the bootstrap field before cleanup'
(( ! login_descendant_survived )) ||
  fail 'a timed-out provider-login process group must leave no surviving descendant'

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOG"
: > "$FAKE_PASS_SKIP_REMOTE_SESSION"
set +e
verification_output=$(zsh "$ensure_ready" 2>&1)
verification_status=$?
set -e
(( verification_status != 0 )) || fail 'a remotely invalid repaired session must fail readiness'
[[ $verification_output ==
  'proton-pass-ensure-ready: the repaired provider session did not verify' ]] ||
  fail 'a failed verification must report one value-free error'
grep -Fqx 'reason=verify-failed' "$status_file" ||
  fail 'a failed verification must record its value-free reason'
[[ -f $login_marker ]] ||
  fail 'a login that fails verification must keep its login marker'
rm -f -- "$FAKE_PASS_SKIP_REMOTE_SESSION" "$login_marker"

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION" \
  "$FAKE_HANGING_CHILD_PID"
: > "$FAKE_PASS_LOG"
: > "$FAKE_PASS_VERIFY_HANG"
test_process_fixture_track_pid_file "$FAKE_HANGING_CHILD_PID"
typeset -F verify_timeout_started=$EPOCHREALTIME
set +e
verify_timeout_output=$(zsh "$ensure_ready" 2>&1)
verify_timeout_status=$?
set -e
typeset -F verify_timeout_elapsed=$(( EPOCHREALTIME - verify_timeout_started ))
(( verify_timeout_status != 0 )) ||
  fail 'a hanging repaired-session verification must fail readiness'
(( verify_timeout_elapsed >= 5.0 && verify_timeout_elapsed < 7.5 )) ||
  fail "a hanging verification must use its full production deadline: elapsed=$verify_timeout_elapsed"
[[ $verify_timeout_output ==
  'proton-pass-ensure-ready: repaired provider-session verification timed out' ]] ||
  fail 'a provider-verification timeout must report one value-free error'
grep -Fqx 'reason=verify-timeout' "$status_file" ||
  fail 'a provider-verification timeout must record its value-free reason'
[[ -f $login_marker ]] ||
  fail 'a login whose verification times out must keep its login marker'
rm -f -- "$login_marker"
hanging_child_pid=$(<"$FAKE_HANGING_CHILD_PID")
! kill -0 $hanging_child_pid 2>/dev/null ||
  fail 'a timed-out provider-verification child must be terminated and reaped'
test_process_fixture_untrack_pid_file "$FAKE_HANGING_CHILD_PID"
rm -f -- "$FAKE_PASS_VERIFY_HANG"

# A holder that keeps the lock past every wait: the first check's shared wait
# expires, then the exclusive path's takeover window and extended wait.
rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOG"
lock_file=$state_home/secret-exec/proton-pass-readiness.lock
lock_ready=$test_dir/native-lock-ready
zsh -f -c '
  set -euo pipefail
  zmodload zsh/system
  zmodload zsh/zselect
  : >> "$1"
  integer lock_fd
  zsystem flock -t 1 -f lock_fd "$1"
  : > "$2"
  zselect -t 6000 || true
' -- "$lock_file" "$lock_ready" &
lock_holder_pid=$!
test_process_fixture_track_pid $lock_holder_pid
zmodload zsh/zselect
while [[ ! -e $lock_ready ]]; do
  zselect -t 1 || true
done
typeset -F lock_timeout_started=$EPOCHREALTIME
set +e
lock_output=$(zsh "$ensure_ready" 2>&1)
lock_status=$?
set -e
typeset -F lock_timeout_elapsed=$(( EPOCHREALTIME - lock_timeout_started ))
kill $lock_holder_pid 2>/dev/null || true
wait $lock_holder_pid 2>/dev/null || true
test_process_fixture_untrack_pid $lock_holder_pid
(( lock_status != 0 )) || fail 'a repair lock timeout must fail readiness'
(( lock_timeout_elapsed >= 26.5 )) ||
  fail "a lock timeout must cover the shared wait, takeover window, and extended concurrent wait: elapsed=$lock_timeout_elapsed"
[[ $lock_output ==
  'proton-pass-ensure-ready: timed out waiting for provider-session repair' ]] ||
  fail 'a lock timeout must report one value-free error'
grep -Fqx 'reason=lock-timeout' "$status_file" ||
  fail 'a lock timeout must record its value-free reason'
[[ ! -s $FAKE_PASS_LOG ]] ||
  fail "a caller whose lock waits expire must not call the provider: $(<"$FAKE_PASS_LOG")"

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOG"
chmod 0644 "$lock_file"
set +e
unsafe_mode_output=$(zsh "$ensure_ready" 2>&1)
unsafe_mode_status=$?
set -e
(( unsafe_mode_status != 0 )) ||
  fail 'a broadly readable readiness lock must fail readiness'
[[ $unsafe_mode_output ==
  'proton-pass-ensure-ready: readiness lock must have mode 0600' ]] ||
  fail 'an unsafe readiness-lock mode must report one value-free error'
grep -Fqx 'reason=unsafe-lock' "$status_file" ||
  fail 'an unsafe readiness-lock mode must record its value-free reason'
! /usr/bin/grep -Fqx login "$FAKE_PASS_LOG" ||
  fail 'an unsafe readiness-lock mode must not attempt provider login'

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOG"
lock_trap=$test_dir/lock-trap
print -r -- 'unchanged' > "$lock_trap"
rm -f -- "$lock_file"
ln -s -- "$lock_trap" "$lock_file"
set +e
unsafe_lock_output=$(zsh "$ensure_ready" 2>&1)
unsafe_lock_status=$?
set -e
(( unsafe_lock_status != 0 )) ||
  fail 'a symbolic-link readiness lock must fail readiness'
[[ $unsafe_lock_output ==
  'proton-pass-ensure-ready: readiness lock must not be a symbolic link' ]] ||
  fail 'an unsafe readiness lock must report one value-free error'
[[ $(<"$lock_trap") == unchanged ]] ||
  fail 'readiness must not follow or alter a symbolic-link lock target'
grep -Fqx 'reason=unsafe-lock' "$status_file" ||
  fail 'an unsafe readiness lock must record its value-free reason'
rm -f -- "$lock_file"

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
mv "$ensure_ready" "$test_dir/proton-pass-ensure-ready.real"
cat > "$ensure_ready" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

bootstrap_field=PROTON_PASS_PERSONAL_ACCESS
bootstrap_field+=_TOKEN
[[ -z ${${(P)bootstrap_field}:-} ]] || exit 91
: > "$SESSION_DELEGATE_MARKER"
EOF
chmod +x "$ensure_ready"
export SESSION_DELEGATE_MARKER=$test_dir/session-delegate-ran
export "$proton_bootstrap_field=$fixture_token"
"$session_compatibility"
unset "$proton_bootstrap_field"
[[ -e $SESSION_DELEGATE_MARKER ]] ||
  fail 'the compatibility entrypoint must scrub the bootstrap token before delegation'
rm -- "$ensure_ready"
mv "$test_dir/proton-pass-ensure-ready.real" "$ensure_ready"

export "$proton_bootstrap_field=$fixture_token"
"$session_compatibility"
unset "$proton_bootstrap_field"
[[ -e $FAKE_PASS_REMOTE_SESSION ]] ||
  fail 'the legacy session helper must delegate to ensure-ready'
[[ $(/usr/bin/grep -Fxc login "$FAKE_PASS_LOG") == 1 ]] ||
  fail 'the legacy session helper must use the serialized login path'
[[ -s $FAKE_SECRET_TOOL_LOG ]] ||
  fail 'the legacy session helper must re-read the native bootstrap item'

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
mv "$native_store_adapter" "$test_dir/native-store-adapter.real"
ln -s "$test_dir/native-store-adapter.real" "$native_store_adapter"
set +e
symlink_adapter_output=$(zsh "$ensure_ready" 2>&1)
symlink_adapter_status=$?
set -e
(( symlink_adapter_status != 0 )) ||
  fail 'a symbolic-link native-store adapter must fail closed'
[[ $symlink_adapter_output ==
  'proton-pass-ensure-ready: a trusted native-store adapter is required' ]] ||
  fail 'a rejected symbolic-link native-store adapter must produce one value-free error'
rm -- "$native_store_adapter"
mv "$test_dir/native-store-adapter.real" "$native_store_adapter"

chmod 777 "$native_store_adapter"
set +e
writable_adapter_output=$(zsh "$ensure_ready" 2>&1)
writable_adapter_status=$?
set -e
(( writable_adapter_status != 0 )) ||
  fail 'a group-or-other-writable native-store adapter must fail closed'
[[ $writable_adapter_output ==
  'proton-pass-ensure-ready: a trusted native-store adapter is required' ]] ||
  fail 'a rejected writable native-store adapter must produce one value-free error'
chmod 755 "$native_store_adapter"

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
trace_output=$(FAKE_UNAME_SYSTEM=Linux zsh -x "$ensure_ready" 2>&1)
[[ -e $FAKE_PASS_REMOTE_SESSION ]] ||
  fail 'readiness under an inherited xtrace request must still repair the session'
grep -Fqx 'waiter-stage=unrecorded' "$status_file" ||
  fail 'a repair after waiter-stage failures must reset diagnostic state'

! print -r -- "$locked_output" | /usr/bin/grep -F "$fixture_token" >/dev/null ||
  fail 'readiness errors must not contain the bootstrap token'
! print -r -- "$trace_output" | /usr/bin/grep -F "$fixture_token" >/dev/null ||
  fail 'readiness must disable xtrace before resolving the bootstrap token'
! /usr/bin/grep -F "$fixture_token" "$FAKE_PASS_LOG" "$FAKE_SECRET_TOOL_LOG" \
  "$status_file" >/dev/null ||
  fail 'readiness logs and status must not contain the bootstrap token'
! /usr/bin/grep -FR "$fixture_token" "$repo_root/home" "$repo_root/tests" >/dev/null ||
  fail 'the synthetic bootstrap token must not appear in managed source or tests'
! /usr/bin/grep -F 'account-metadata-canary' "$test_dir"/*.log "$status_file" >/dev/null ||
  fail 'readiness must suppress provider account metadata'
! /usr/bin/grep -F 'waiter-stage-canary' "$test_dir"/*.log "$status_file" >/dev/null ||
  fail 'readiness must not persist an inherited waiter-stage canary'
! /usr/bin/grep -RF "$fixture_token" "$state_home" >/dev/null ||
  fail 'readiness state must not contain the bootstrap token'
! /usr/bin/grep -F 'diagnostic-text-canary' "$test_dir"/*.log "$status_file" >/dev/null ||
  fail 'readiness must not persist inherited diagnostic text'
[[ -e $PROTON_PASS_DIAGNOSTIC_FILE ]] ||
  fail 'readiness must never remove an inherited diagnostic path'
assert_no_private_diagnostics 'the readiness suite'

symlink_state_home=$test_dir/symlink-state-home
symlink_state_target=$test_dir/symlink-state-target
mkdir -p -- "$symlink_state_home" "$symlink_state_target"
ln -s -- "$symlink_state_target" "$symlink_state_home/secret-exec"
set +e
unsafe_state_output=$(XDG_STATE_HOME=$symlink_state_home zsh "$ensure_ready" 2>&1)
unsafe_state_status=$?
set -e
(( unsafe_state_status != 0 )) ||
  fail 'a symbolic-link readiness state directory must fail closed'
[[ $unsafe_state_output ==
  'proton-pass-ensure-ready: state directory must not be a symbolic link' ]] ||
  fail 'an unsafe state directory must report one value-free error'

print -r -- 'Proton Pass readiness checks passed'
