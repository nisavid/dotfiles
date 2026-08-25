#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
ensure_ready_source=${PROTON_PASS_ENSURE_READY_SOURCE:-$repo_root/home/private_dot_local/bin/executable_proton-pass-ensure-ready}
session_compatibility_source=$repo_root/home/private_dot_local/bin/executable_proton-pass-session
native_store_adapter_source=$repo_root/home/private_dot_local/bin/executable_secret-exec-native-store
proton_bootstrap_field=PROTON_PASS_PERSONAL_ACCESS
proton_bootstrap_field+=_TOKEN

fail() {
  print -u2 -r -- "$1"
  return 1
}

process_fixture_helper=$repo_root/tests/helpers/process-fixture.zsh
[[ -r $process_fixture_helper ]] ||
  fail 'the shared process-fixture helper is required'
source "$process_fixture_helper"
if /bin/zsh -f -c '
  source "$1"
  test_process_fixture_init "$2"
' -- "$process_fixture_helper" "$repo_root"; then
  fail 'the process-fixture helper must reject recursive cleanup outside the temporary root'
fi
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/proton-pass-session.XXXXXX")
test_process_fixture_init "$test_dir" || fail 'could not initialize process-fixture cleanup'
trap test_process_fixture_cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
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
print -r -- "$*" >> "$FAKE_PASS_LOG"
fixture_token=pst_
fixture_token+='fixture-token'
fixture_token+='::fixture-key'
bootstrap_field=PROTON_PASS_PERSONAL_ACCESS
bootstrap_field+=_TOKEN
hang_forever() {
  print -r -- $$ > "$FAKE_HANGING_CHILD_PID"
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
case $1 in
  info)
    (( $# == 1 )) || exit 64
    [[ ${PROTON_PASS_NO_UPDATE_CHECK:-} == 1 ]] || exit 69
    [[ -z ${${(P)bootstrap_field}:-} ]] || exit 70
    if [[ -e $FAKE_PASS_VERIFY_HANG && -e $FAKE_PASS_REMOTE_SESSION ]]; then
      hang_forever
    fi
    if [[ -e $FAKE_PASS_INFO_HANG && ! -e $FAKE_PASS_REMOTE_SESSION ]]; then
      hang_forever
    fi
    if [[ -e $FAKE_PASS_INFO_TRANSIENT ]]; then
      print -u2 -r -- \
        'Error: temporary provider failure while reporting "Error: This operation requires an authenticated client"'
      exit 76
    fi
    if [[ -e $FAKE_PASS_LOCAL_SESSION && -e $FAKE_PASS_REMOTE_SESSION ]]; then
      print -r -- 'account-metadata-canary'
      exit 0
    fi
    if [[ -e $FAKE_PASS_INFO_INVALIDATED ]]; then
      print -u2 -rl -- \
        '2026-08-25T07:13:16.037584Z ERROR pass-cli/src/main.rs:231: Session invalidated' \
        'Your session has been invalidated and you have been logged out automatically.' \
        'Please log in again with: pass login'
      exit 77
    fi
    print -u2 -rl -- \
      '2026-08-25T07:13:16.037584Z ERROR pass-cli/src/main.rs:332: Command is not logout there is no session' \
      'Error: This operation requires an authenticated client'
    exit 78
    ;;
  login)
    (( $# == 1 )) || exit 65
    [[ ${${(P)bootstrap_field}:-} == $fixture_token ]] || exit 66
    if [[ $OSTYPE == darwin* ]]; then
      [[ -z ${PROTON_PASS_LINUX_KEYRING:-} ]] || exit 67
    else
      [[ ${PROTON_PASS_LINUX_KEYRING:-} == dbus ]] || exit 67
    fi
    [[ ! -e $FAKE_PASS_REQUIRE_LOGOUT || ! -e $FAKE_PASS_LOCAL_SESSION ]] ||
      exit 73
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
    [[ ! -e $FAKE_PASS_LOGOUT_FAIL ]] || exit 79
    /bin/rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
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
export FAKE_PASS_LOGIN_DESCENDANT=$test_dir/login-descendant
export FAKE_PASS_LOCAL_SESSION=$test_dir/local-session
export FAKE_PASS_REMOTE_SESSION=$test_dir/remote-session
export FAKE_PASS_SKIP_REMOTE_SESSION=$test_dir/skip-remote-session
export FAKE_PASS_VERIFY_HANG=$test_dir/verify-hang
export FAKE_PASS_INFO_HANG=$test_dir/info-hang
export FAKE_PASS_INFO_TRANSIENT=$test_dir/info-transient
export FAKE_PASS_INFO_INVALIDATED=$test_dir/info-invalidated
export FAKE_SECRET_TOOL_LOG=$test_dir/secret-tool.log
export FAKE_NATIVE_STORE_LOCKED=$test_dir/native-store-locked
export FAKE_NATIVE_STORE_HANG=$test_dir/native-store-hang
export FAKE_NATIVE_STORE_DESCENDANT=$test_dir/native-store-descendant
export FAKE_HANGING_CHILD_PID=$test_dir/hanging-child.pid
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
/bin/mkdir -p -- "$FAKE_UTILITY_MARKER_DIR"
fixture_token=pst_
fixture_token+='fixture-token'
fixture_token+='::fixture-key'

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
  [[ $(<"$FAKE_PASS_LOG") == $'info\ninfo\nlogin' ]] ||
    fail "the $mode waiter-stage fixture must target the direct login waiter"
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
typeset -F info_hang_deadline=$(( info_hang_started + 7.5 ))
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
(( ! info_hang_timed_out && info_hang_status == 1 && info_hang_elapsed < 7.5 )) ||
  fail 'the whole readiness entrypoint must bound initial and locked session probes'
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

zsh "$ensure_ready"
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

: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
zsh "$ensure_ready"
[[ $(<"$FAKE_PASS_LOG") == 'info' ]] ||
  fail 'an existing provider session must not trigger another login'
[[ ! -s $FAKE_SECRET_TOOL_LOG ]] ||
  fail 'an existing provider session must not read the bootstrap item'
grep -Fqx 'reason=existing-session' "$status_file" ||
  fail 'an existing session must record its value-free reason'

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
probe_artifacts=( "$state_home/secret-exec"/.proton-pass-session-probe.*(N) )
(( ! ${#probe_artifacts} )) ||
  fail 'a classified readiness check must remove its private diagnostic file'

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
hanging_child_pid=$(<"$FAKE_HANGING_CHILD_PID")
! kill -0 $hanging_child_pid 2>/dev/null ||
  fail 'a timed-out stale-session cleanup child must be terminated and reaped'
test_process_fixture_untrack_pid_file "$FAKE_HANGING_CHILD_PID"

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

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION"
: > "$FAKE_PASS_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
: > "$FAKE_PASS_LOGIN_DELAY"
slow_repair_started=$test_dir/slow-repair-started
/usr/bin/env \
  FAKE_PASS_LOGIN_DELAY_SECONDS=6 \
  PROVIDER_START_MARKER="$slow_repair_started" \
  zsh "$ensure_ready" >"$test_dir/slow-repair-owner.out" \
  2>"$test_dir/slow-repair-owner.err" &
slow_repair_owner_pid=$!
test_process_fixture_track_pid $slow_repair_owner_pid
integer slow_repair_start_polls=200
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
/usr/bin/env \
  FAKE_PASS_LOGIN_DELAY_SECONDS=6 \
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
(( login_timeout_elapsed < 9.0 )) ||
  fail 'a provider-login process group must fail within the production deadline'
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
rm -f -- "$FAKE_PASS_SKIP_REMOTE_SESSION"

rm -f -- "$FAKE_PASS_LOCAL_SESSION" "$FAKE_PASS_REMOTE_SESSION" \
  "$FAKE_HANGING_CHILD_PID"
: > "$FAKE_PASS_LOG"
: > "$FAKE_PASS_VERIFY_HANG"
test_process_fixture_track_pid_file "$FAKE_HANGING_CHILD_PID"
set +e
verify_timeout_output=$(zsh "$ensure_ready" 2>&1)
verify_timeout_status=$?
set -e
(( verify_timeout_status != 0 )) ||
  fail 'a hanging repaired-session verification must fail readiness'
[[ $verify_timeout_output ==
  'proton-pass-ensure-ready: repaired provider-session verification timed out' ]] ||
  fail 'a provider-verification timeout must report one value-free error'
grep -Fqx 'reason=verify-timeout' "$status_file" ||
  fail 'a provider-verification timeout must record its value-free reason'
hanging_child_pid=$(<"$FAKE_HANGING_CHILD_PID")
! kill -0 $hanging_child_pid 2>/dev/null ||
  fail 'a timed-out provider-verification child must be terminated and reaped'
test_process_fixture_untrack_pid_file "$FAKE_HANGING_CHILD_PID"
rm -f -- "$FAKE_PASS_VERIFY_HANG"

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
  zselect -t 1850 || true
' -- "$lock_file" "$lock_ready" &
lock_holder_pid=$!
test_process_fixture_track_pid $lock_holder_pid
zmodload zsh/zselect
while [[ ! -e $lock_ready ]]; do
  zselect -t 1 || true
done
set +e
lock_output=$(zsh "$ensure_ready" 2>&1)
lock_status=$?
set -e
wait $lock_holder_pid
test_process_fixture_untrack_pid $lock_holder_pid
(( lock_status != 0 )) || fail 'a repair lock timeout must fail readiness'
[[ $lock_output ==
  'proton-pass-ensure-ready: timed out waiting for provider-session repair' ]] ||
  fail 'a lock timeout must report one value-free error'
grep -Fqx 'reason=lock-timeout' "$status_file" ||
  fail 'a lock timeout must record its value-free reason'
! /usr/bin/grep -Fqx login "$FAKE_PASS_LOG" ||
  fail 'a lock timeout must not attempt provider login'

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
