#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
startup_source=$repo_root/home/private_dot_local/bin/executable_proton-pass-startup
# The fixture adapter writes status through the helper's real writer, so the
# format startup reads cannot drift from the one the helper writes.
export FAKE_STARTUP_HELPER_SOURCE=$repo_root/home/private_dot_local/bin/executable_proton-pass-ensure-ready

fail() {
  print -u2 -r -- "$1"
  return 1
}

process_fixture_helper=$repo_root/tests/helpers/process-fixture.zsh
[[ -r $process_fixture_helper ]] ||
  fail 'the shared process-fixture helper is required'
source "$process_fixture_helper"

process_survives_grace() {
  emulate -L zsh

  local pid=$1
  integer poll
  zmodload zsh/zselect || return 0
  for (( poll = 0; poll < 20; ++poll )); do
    kill -0 $pid 2>/dev/null || return 1
    zselect -t 5 2>/dev/null || true
  done
  return 0
}

run_with_test_deadline() {
  emulate -L zsh

  local output_file=$1
  local timeout_seconds=$2
  shift 2
  zmodload zsh/datetime || fail 'zsh/datetime is required for deadline tests'
  zmodload zsh/zselect || fail 'zsh/zselect is required for deadline tests'

  "$@" >"$output_file" 2>&1 &
  integer command_pid=$!
  test_process_fixture_track_pid $command_pid
  local -F deadline=$(( EPOCHREALTIME + timeout_seconds ))
  while kill -0 $command_pid 2>/dev/null; do
    if (( EPOCHREALTIME >= deadline )); then
      kill -TERM $command_pid 2>/dev/null || true
      zselect -t 10 2>/dev/null || true
      kill -0 $command_pid 2>/dev/null &&
        kill -KILL $command_pid 2>/dev/null || true
      wait $command_pid 2>/dev/null || true
      test_process_fixture_untrack_pid $command_pid
      return 124
    fi
    zselect -t 5 2>/dev/null || true
  done

  integer command_status
  if wait $command_pid; then
    command_status=0
  else
    command_status=$?
  fi
  test_process_fixture_untrack_pid $command_pid
  return $command_status
}

reset_fixture() {
  emulate -L zsh

  : >"$FAKE_STARTUP_ATTEMPTS"
  : >"$FAKE_STARTUP_ADAPTER_PIDS"
  : >"$FAKE_STARTUP_DESCENDANT_PIDS"
  rm -f -- \
    "$FAKE_STARTUP_PATH_INTERPRETER_REACHED" \
    "$FAKE_STARTUP_PATH_SLEEP_REACHED" \
    "$FAKE_STARTUP_ZDOTDIR_REACHED"
}

test_dir=$(mktemp -d "${TMPDIR:-/tmp}/proton-pass-startup.XXXXXX")
startup_home=$test_dir/startup-home
mkdir -p -- "$startup_home/.config/zsh"
cat >"$startup_home/.config/zsh/startup.zsh" <<'EOF'
[[ $1 == launcher && $2 == darwin ]] || return 97
path=( /usr/bin /bin /usr/sbin /sbin )
EOF
export HOME=$startup_home
# Startup reads the readiness status on failure; never the operator's.
export XDG_STATE_HOME=$test_dir/state
test_process_fixture_init "$test_dir" || fail 'could not initialize process-fixture cleanup'
trap test_process_fixture_cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
test_process_fixture_run_signal_probe_mode

typeset cleanup_probe_spec cleanup_probe_signal cleanup_probe_suffix
integer cleanup_probe_expected_status
for cleanup_probe_spec in HUP:129 INT:130 TERM:143; do
  cleanup_probe_signal=${cleanup_probe_spec%%:*}
  cleanup_probe_suffix=${(L)cleanup_probe_signal}
  cleanup_probe_expected_status=${cleanup_probe_spec#*:}
  test_process_fixture_assert_signal_cleanup \
    "${0:A}" "$cleanup_probe_signal" "$cleanup_probe_expected_status" \
    "$test_dir/cleanup-$cleanup_probe_suffix" ||
    fail "$cleanup_probe_signal cleanup must terminate fixtures and preserve status"
done

fixture_bin=$test_dir/bin
mkdir -p -- "$fixture_bin"
cp -- "$startup_source" "$fixture_bin/proton-pass-startup"
chmod -- +x "$fixture_bin/proton-pass-startup"

fast_exit=
for fast_exit_candidate in /usr/bin/true /bin/true; do
  if [[ -x $fast_exit_candidate ]]; then
    fast_exit=$fast_exit_candidate
    break
  fi
done
[[ -n $fast_exit ]] || fail 'a fixed true executable is required'
fast_child_bin=$test_dir/fast-child-bin
mkdir -p -- "$fast_child_bin"
cp -- "$startup_source" "$fast_child_bin/proton-pass-startup"
cat >"$fast_child_bin/proton-pass-ensure-ready" <<'EOF'
#!/bin/zsh -f
set -euo pipefail
[[ -z ${PROVIDER_START_MARKER:-} ]] ||
  print -r -- provider-started >>"$PROVIDER_START_MARKER"
[[ -z ${PROVIDER_COMPLETION_DELAY:-} ]] || /bin/sleep 0.2
[[ -z ${PROVIDER_COMPLETION_MARKER:-} ]] ||
  print -r -- provider-completed >>"$PROVIDER_COMPLETION_MARKER"
EOF
chmod -- +x \
  "$fast_child_bin/proton-pass-startup" \
  "$fast_child_bin/proton-pass-ensure-ready"
integer fast_child_run
for (( fast_child_run = 1; fast_child_run <= 32; ++fast_child_run )); do
  "$fast_child_bin/proton-pass-startup" >/dev/null 2>&1 ||
    fail 'startup must accept an immediately ready provider child'
done

negative_pgid_audit_library=
positive_pid_audit_log=$test_dir/positive-pid-kill-audit.log
status_fragment_library=
status_fragment_log=$test_dir/zpty-status-fragment.log
status_fragment_delay_log=$test_dir/zpty-status-fragment-delay.log
status_fragment_deadline_log=$test_dir/zpty-status-fragment-deadline.log
transient_liveness_log=$test_dir/zpty-transient-liveness.log
identity_loss_log=$test_dir/zpty-identity-loss.log
if [[ $OSTYPE == linux* ]]; then
  [[ -x /usr/bin/cc ]] ||
    fail 'Linux requires /usr/bin/cc for process-group identity tracing'
  negative_pgid_audit_source=$repo_root/tests/fixtures/negative-pgid-kill-audit.c
  [[ -r $negative_pgid_audit_source ]] ||
    fail 'the negative-PGID syscall audit fixture is required'
  negative_pgid_audit_library=$test_dir/negative-pgid-kill-audit.so
  /usr/bin/cc -shared -fPIC -O2 -Wall -Wextra -Werror \
    -o "$negative_pgid_audit_library" "$negative_pgid_audit_source" -ldl
  status_fragment_library=$test_dir/zpty-status-fragment.so
  /usr/bin/cc -shared -fPIC -O2 -Wall -Wextra -Werror \
    -o "$status_fragment_library" \
    "$repo_root/tests/fixtures/zpty-status-fragment.c" -ldl
  negative_pgid_audit_log=$test_dir/negative-pgid-kill-audit.log
  : >"$negative_pgid_audit_log"
  NEGATIVE_PGID_KILL_AUDIT_LOG=$negative_pgid_audit_log \
    LD_PRELOAD=$negative_pgid_audit_library \
    /bin/zsh -f -c '
      kill -0 -- -2147483647 2>/dev/null || true
      kill -TERM -- -2147483647 2>/dev/null || true
    '
  [[ -s $negative_pgid_audit_log ]] ||
    fail 'the negative-PGID syscall audit must detect a stale signal'
  : >"$negative_pgid_audit_log"

  : >"$positive_pid_audit_log"
  POSITIVE_PID_KILL_AUDIT_LOG=$positive_pid_audit_log \
    LD_PRELOAD=$negative_pgid_audit_library \
    /bin/zsh -f -c '
      kill -0 2147483647 2>/dev/null || true
      kill -TERM 2147483647 2>/dev/null || true
    '
  [[ -s $positive_pid_audit_log ]] ||
    fail 'the positive-PID syscall audit must detect a reused identity signal'
  : >"$positive_pid_audit_log"

  typeset identity_loss_output identity_listing identity_controller
  integer identity_loss_status
  identity_loss_gate=$test_dir/zpty-initial-identity-loss.gate
  identity_loss_output_file=$test_dir/zpty-initial-identity-loss.out
  rm -f -- "$identity_loss_log" "$identity_loss_gate" "$identity_loss_output_file" "$negative_pgid_audit_log"
  /usr/bin/env LD_PRELOAD="$status_fragment_library:$negative_pgid_audit_library" \
    ZPTY_IDENTITY_LOSS_AUDIT_LOG=$identity_loss_log \
    ZPTY_INITIAL_IDENTITY_LOSS_GATE=$identity_loss_gate \
    NEGATIVE_PGID_KILL_AUDIT_LOG=$negative_pgid_audit_log \
    ZPTY_INITIAL_IDENTITY_LOSS=1 "$fast_child_bin/proton-pass-startup" \
    >"$identity_loss_output_file" 2>&1 &
  identity_wrapper_pid=$!
  test_process_fixture_track_pid $identity_wrapper_pid
  integer identity_marker_polls=100
  while (( identity_marker_polls-- > 0 )) && [[ ! -s $identity_loss_log ]]; do
    zselect -t 1 2>/dev/null || true
  done
  [[ -s $identity_loss_log ]] || fail 'initial startup identity fixture must publish its controller'
  identity_loss_record=$(<"$identity_loss_log")
  typeset -a identity_lines=( "${(@f)identity_loss_record}" )
  identity_controller=${identity_lines[1]#controller:}
  [[ $identity_controller == <-> && $identity_controller -gt 1 ]] || fail 'initial startup identity fixture must publish a numeric controller'
  identity_listing=$(/bin/ps -o pid=,ppid=,pgid=,sid= -p $identity_controller)
  typeset -a identity_fields=( ${=identity_listing} )
  (( ${#identity_fields} == 4 && identity_fields[1] == identity_controller &&
    identity_fields[2] == identity_wrapper_pid && identity_fields[3] == identity_controller &&
    identity_fields[4] == identity_controller )) || fail 'initial startup controller must be the wrapper child and its session leader'
  kill -KILL -- -$identity_controller
  : >"$identity_loss_gate"
  set +e
  wait $identity_wrapper_pid
  identity_loss_status=$?
  set -e
  test_process_fixture_untrack_pid $identity_wrapper_pid
  ! kill -0 -- -$identity_controller 2>/dev/null || fail 'initial startup controller group must become absent'
  identity_loss_output=$(<"$identity_loss_output_file")
  (( identity_loss_status == 1 )) || fail 'initial identity loss must fail startup closed'
  [[ $identity_loss_output == 'proton-pass-startup: cannot identify bounded startup process group' ]] || fail 'initial identity loss must preserve its fixed startup diagnostic'
  [[ $(<"$identity_loss_log") == $'controller:'$identity_controller$'\ninitial-identity-loss' ]] || fail 'initial startup identity fixture must prove pre-publication controller loss'
  [[ ! -s $negative_pgid_audit_log ]] || fail 'initial startup identity loss must not signal an absent process group'

  rm -f -- "$identity_loss_log" "$negative_pgid_audit_log"
  set +e
  identity_loss_output=$(/usr/bin/env LD_PRELOAD="$status_fragment_library:$negative_pgid_audit_library" \
    ZPTY_IDENTITY_LOSS_AUDIT_LOG=$identity_loss_log NEGATIVE_PGID_KILL_AUDIT_LOG=$negative_pgid_audit_log \
    ZPTY_POST_ACTIVE_IDENTITY_LOSS=1 "$fast_child_bin/proton-pass-startup" 2>&1)
  identity_loss_status=$?
  set -e
  (( identity_loss_status == 1 )) || fail 'post-active identity loss must fail startup closed'
  [[ $identity_loss_output == 'proton-pass-startup: bounded startup child became unmanageable' ]] || fail 'post-active identity loss must produce one fixed startup diagnostic'
  [[ $(<"$identity_loss_log") == post-active-identity-loss ]] || fail 'post-active startup identity fixture must prove controller loss'
  [[ ! -s $negative_pgid_audit_log ]] || fail 'post-active startup identity loss must not signal an absent process group'

  provider_start_marker=$test_dir/transient-startup-provider-started
  provider_completion_marker=$test_dir/transient-startup-provider-completed
  rm -f -- "$transient_liveness_log" "$provider_start_marker" \
    "$provider_completion_marker" "$negative_pgid_audit_log"
  set +e
  LD_PRELOAD="$status_fragment_library:$negative_pgid_audit_library" \
    ZPTY_TRANSIENT_LIVENESS_PROBE=1 \
    ZPTY_TRANSIENT_LIVENESS_AUDIT_LOG=$transient_liveness_log \
    NEGATIVE_PGID_KILL_AUDIT_LOG=$negative_pgid_audit_log \
    PROVIDER_START_MARKER=$provider_start_marker \
    PROVIDER_COMPLETION_MARKER=$provider_completion_marker \
    PROVIDER_COMPLETION_DELAY=1 \
    "$fast_child_bin/proton-pass-startup" \
      >/dev/null 2>"$test_dir/transient-startup.err"
  transient_startup_status=$?
  set -e
  (( transient_startup_status == 0 )) ||
    fail "startup must retry one transient live-group probe: status=$transient_startup_status error=$(<"$test_dir/transient-startup.err")"
  [[ $(<"$transient_liveness_log") == \
    $'start-gate\nlive-before-esrch\ninjected-esrch\nrecovered-live' ]] ||
    fail 'the startup liveness fixture must prove one live ESRCH and recovery'
  [[ $(<"$provider_start_marker") == provider-started &&
    $(<"$provider_completion_marker") == provider-completed ]] ||
    fail 'startup must complete exactly one provider after the transient probe'
  [[ ! -s $negative_pgid_audit_log ]] ||
    fail 'startup transient-probe recovery must not signal a stale group'

  provider_completion_marker=$test_dir/fragmented-startup-provider-completed
  rm -f -- "$status_fragment_log" "$status_fragment_delay_log" \
    "$provider_completion_marker" "$negative_pgid_audit_log"
  set +e
  LD_PRELOAD=$status_fragment_library \
    ZPTY_STATUS_FRAGMENT_AUDIT_LOG=$status_fragment_log \
    ZPTY_STATUS_FRAGMENT_DELAY_TAIL=1 \
    ZPTY_STATUS_FRAGMENT_DELAY_AUDIT_LOG=$status_fragment_delay_log \
    PROVIDER_COMPLETION_MARKER=$provider_completion_marker \
    "$fast_child_bin/proton-pass-startup" \
      >/dev/null 2>"$test_dir/fragmented-startup.err"
  fragmented_startup_status=$?
  set -e
  (( fragmented_startup_status == 0 )) ||
    fail "startup must accept a fragmented successful child-status record: status=$fragmented_startup_status error=$(<"$test_dir/fragmented-startup.err")"
  [[ $(<"$status_fragment_log") == fragmented-status ]] ||
    fail 'the startup PTY fixture must prove that it fragmented a record'
  [[ $(<"$provider_completion_marker") == provider-completed ]] ||
    fail 'the fragmented startup fixture must prove one provider completion'
  [[ $(<"$status_fragment_delay_log") == \
    $'delay-armed\nforced-yields-complete\ndelayed-tail' ]] ||
    fail 'the startup PTY fixture must prove the forced-yield and 160 ms status-tail delay'

  rm -f -- "$status_fragment_log" "$status_fragment_deadline_log"
  set +e
  LD_PRELOAD=$status_fragment_library \
    ZPTY_STATUS_FRAGMENT_AUDIT_LOG=$status_fragment_log \
    ZPTY_STATUS_FRAGMENT_EXPIRE_DEADLINE=1 \
    ZPTY_STATUS_FRAGMENT_DEADLINE_AUDIT_LOG=$status_fragment_deadline_log \
    "$fast_child_bin/proton-pass-startup" \
      >/dev/null 2>"$test_dir/deadline-startup.err"
  deadline_startup_status=$?
  set -e
  (( deadline_startup_status == 0 )) ||
    fail "startup must recover after rejecting a post-deadline status tail: status=$deadline_startup_status error=$(<"$test_dir/deadline-startup.err")"
  [[ $(<"$status_fragment_log") == fragmented-status ]] ||
    fail 'the startup deadline fixture must prove status fragmentation'
  [[ $(<"$status_fragment_deadline_log") == \
    $'deadline-armed\ndeadline-expired' ]] ||
    fail 'startup must not read a fragmented status tail after its deadline'

  rm -f -- "$status_fragment_log" "$negative_pgid_audit_log"
  zmodload zsh/zselect || fail 'the startup signal fixture requires zsh/zselect'
  set +e
  LD_PRELOAD="$status_fragment_library:$negative_pgid_audit_library" \
    ZPTY_STATUS_FRAGMENT_AUDIT_LOG=$status_fragment_log \
    ZPTY_STATUS_FRAGMENT_PAUSE=1 \
    NEGATIVE_PGID_KILL_AUDIT_LOG=$negative_pgid_audit_log \
    "$fast_child_bin/proton-pass-startup" \
      >"$test_dir/fragment-signal.out" \
      2>"$test_dir/fragment-signal.err" &
  fragmented_startup_pid=$!
  test_process_fixture_track_pid $fragmented_startup_pid
  integer fragment_marker_polls=100
  while (( fragment_marker_polls-- > 0 )) && [[ ! -s $status_fragment_log ]]; do
    zselect -t 1 2>/dev/null || true
  done
  if [[ ! -s $status_fragment_log ]]; then
    kill -KILL $fragmented_startup_pid 2>/dev/null || true
    wait $fragmented_startup_pid 2>/dev/null || true
    test_process_fixture_untrack_pid $fragmented_startup_pid
    set -e
    fail 'startup must reach the fragmented post-exit status window'
  fi
  kill -TERM $fragmented_startup_pid 2>/dev/null || true
  wait $fragmented_startup_pid
  fragmented_signal_status=$?
  test_process_fixture_untrack_pid $fragmented_startup_pid
  set -e
  (( fragmented_signal_status == 143 )) ||
    fail 'TERM during startup status parsing must retain status 143'
  [[ $(<"$status_fragment_log") == fragmented-status ]] ||
    fail 'the startup signal fixture must prove that it fragmented a record'
  [[ ! -s $negative_pgid_audit_log ]] ||
    fail 'startup status parsing must not signal an absent process group'
fi

run_pid_list_consumption_probe() {
  emulate -L zsh
  unsetopt err_exit

  local mode=$1
  local probe_root=$2
  /bin/mkdir -p -- "$probe_root"

  (
    if [[ -n $negative_pgid_audit_library ]]; then
      export POSITIVE_PID_KILL_AUDIT_LOG=$positive_pid_audit_log
      export LD_PRELOAD=$negative_pgid_audit_library
    fi
    /bin/zsh -f -c '
      set -euo pipefail
      source "$1"
      probe_root=$2
      mode=$3
      test_process_fixture_init "$probe_root"
      trap test_process_fixture_cleanup EXIT
      pid_list=$probe_root/children.pids
      ready_file=$probe_root/child.ready
      test_process_fixture_track_pid_list_file "$pid_list"
      /bin/zsh -f -c '\''
        trap "exit 0" TERM
        : >"$1"
        zmodload zsh/zselect
        while true; do
          zselect -t 10 2>/dev/null || true
        done
      '\'' -- "$ready_file" &
      child_pid=$!
      print -r -- "$child_pid" >"$pid_list"
      zmodload zsh/zselect
      integer polls=100
      while [[ ! -e $ready_file && polls -gt 0 ]]; do
        (( --polls ))
        zselect -t 1 2>/dev/null || true
      done
      [[ -e $ready_file ]]
      test_process_fixture_stop_all
      integer consumed=0
      [[ ! -s $pid_list ]] && consumed=1
      if [[ $mode == explicit ]]; then
        test_process_fixture_stop_all
        (( consumed )) || exit 80
        trap - EXIT
        /bin/rm -rf -- "$probe_root"
      else
        (( consumed ))
      fi
    ' -- "$process_fixture_helper" "$probe_root" "$mode"
  )
}

integer pid_list_probe_failed=0
for pid_list_probe_mode in explicit exit; do
  run_pid_list_consumption_probe \
    "$pid_list_probe_mode" "$test_dir/pid-list-$pid_list_probe_mode" ||
    pid_list_probe_failed=1
done
[[ ! -s $positive_pid_audit_log ]] ||
  fail "PID-list cleanup must not signal a reused numeric identity: $(<"$positive_pid_audit_log")"
(( ! pid_list_probe_failed )) ||
  fail 'PID-list cleanup must consume collected identities before a later cleanup pass'

interrupted_probe_root=$test_dir/pid-list-interrupted
interrupted_probe_ready=$test_dir/pid-list-interrupted.ready
interrupted_child_pid_file=$test_dir/pid-list-interrupted-child.pid
/bin/mkdir -p -- "$interrupted_probe_root"
test_process_fixture_track_pid_file "$interrupted_child_pid_file"
/bin/zsh -f -c '
  set -euo pipefail
  source "$1"
  probe_root=$2
  ready_file=$3
  observed_child_pid_file=$4
  test_process_fixture_init "$probe_root"
  trap test_process_fixture_cleanup EXIT
  trap "exit 143" TERM
  pid_list=$probe_root/children.pids
  child_ready=$probe_root/child.ready
  test_process_fixture_track_pid_list_file "$pid_list"
  /bin/zsh -f -c '\''
    trap "" HUP INT TERM
    : >"$1"
    zmodload zsh/zselect
    while true; do
      zselect -t 10 2>/dev/null || true
    done
  '\'' -- "$child_ready" &
  child_pid=$!
  print -r -- "$child_pid" >"$pid_list"
  print -r -- "$child_pid" >"$observed_child_pid_file"
  zmodload zsh/zselect
  integer polls=100
  while [[ ! -e $child_ready && polls -gt 0 ]]; do
    (( --polls ))
    zselect -t 1 2>/dev/null || true
  done
  [[ -e $child_ready ]]
  : >"$ready_file"
  test_process_fixture_stop_all
  while true; do
    zselect -t 10 2>/dev/null || true
  done
' -- "$process_fixture_helper" "$interrupted_probe_root" \
  "$interrupted_probe_ready" "$interrupted_child_pid_file" \
  >"$test_dir/pid-list-interrupted.out" \
  2>"$test_dir/pid-list-interrupted.err" &
interrupted_probe_pid=$!
test_process_fixture_track_pid $interrupted_probe_pid
zmodload zsh/datetime
zmodload zsh/zselect
typeset -F interrupted_probe_start_deadline=$(( EPOCHREALTIME + 1.0 ))
while [[ ! -e $interrupted_probe_ready ]] &&
  (( EPOCHREALTIME < interrupted_probe_start_deadline )); do
  zselect -t 1 2>/dev/null || true
done
[[ -e $interrupted_probe_ready ]] ||
  fail 'the interrupted PID-list cleanup probe did not start'
interrupted_pid_list=$interrupted_probe_root/children.pids
typeset -F interrupted_handoff_deadline=$(( EPOCHREALTIME + 1.0 ))
while [[ -s $interrupted_pid_list ]] &&
  (( EPOCHREALTIME < interrupted_handoff_deadline )); do
  :
done
interrupted_child_pid=$(<"$interrupted_child_pid_file")
[[ ! -s $interrupted_pid_list ]] ||
  fail 'PID-list cleanup did not consume its identity before the interrupt'
kill -0 $interrupted_child_pid 2>/dev/null ||
  fail 'the interruption probe missed the in-flight cleanup window'
kill -TERM $interrupted_probe_pid
if wait $interrupted_probe_pid; then
  interrupted_probe_status=0
else
  interrupted_probe_status=$?
fi
test_process_fixture_untrack_pid $interrupted_probe_pid
test_process_fixture_wait_for_pid_exit $interrupted_child_pid 100 ||
  fail 'EXIT cleanup must finish an interrupted PID-list cleanup pass'
test_process_fixture_untrack_pid_file "$interrupted_child_pid_file"
(( interrupted_probe_status == 143 )) ||
  fail 'interrupted PID-list cleanup must preserve TERM status'

cat >"$fixture_bin/proton-pass-ensure-ready" <<'EOF'
#!/bin/zsh -f
set -euo pipefail

bootstrap_field=PROTON_PASS_PERSONAL_ACCESS
bootstrap_field+=_TOKEN
(( ${+parameters[$bootstrap_field]} == 0 )) ||
  print -r -- readiness >>"$FAKE_STARTUP_BOOTSTRAP_LEAK_LOG"

integer attempt=0
[[ ! -s $FAKE_STARTUP_ATTEMPTS ]] ||
  attempt=${${(f)"$(<"$FAKE_STARTUP_ATTEMPTS")"}[-1]}
(( ++attempt ))
print -r -- "$attempt" >>"$FAKE_STARTUP_ATTEMPTS"

case $FAKE_STARTUP_SCENARIO in
  ready)
    return 0
    ;;
  retry)
    (( attempt >= 2 ))
    ;;
  fail-status)
    # Records the reason through the readiness helper's own status writer,
    # then fails.
    if [[ -n ${FAKE_STARTUP_STATUS_REASON:-} ]]; then
      /bin/zsh -f -c '
        source_text=$(<"$1")
        source_text=${source_text%$'"'"'\nmain "$@"'"'"'}
        eval "$source_text"
        trap - EXIT HUP INT TERM
        write_status unavailable "$2" unrecorded
      ' -- "$FAKE_STARTUP_HELPER_SOURCE" "$FAKE_STARTUP_STATUS_REASON"
    fi
    return 1
    ;;
  hang)
    /bin/zsh -f -c '
      trap "" HUP INT TERM
      zmodload zsh/zselect
      while true; do
        zselect -t 100 2>/dev/null || true
      done
    ' proton-pass-startup-descendant &
    print -r -- $! >>"$FAKE_STARTUP_DESCENDANT_PIDS"
    print -r -- $$ >>"$FAKE_STARTUP_ADAPTER_PIDS"
    trap '' HUP INT TERM
    zmodload zsh/zselect
    while true; do
      zselect -t 100 2>/dev/null || true
    done
    ;;
  *)
    return 64
    ;;
esac
EOF
chmod -- +x "$fixture_bin/proton-pass-ensure-ready"

hostile_bin=$test_dir/hostile-bin
hostile_zdotdir=$test_dir/hostile-zdotdir
mkdir -p -- "$hostile_bin" "$hostile_zdotdir"
cat >"$hostile_bin/zsh" <<'EOF'
#!/bin/sh
set -eu
: >"$FAKE_STARTUP_PATH_INTERPRETER_REACHED"
exit 97
EOF
cat >"$hostile_bin/sleep" <<'EOF'
#!/bin/sh
set -eu
: >"$FAKE_STARTUP_PATH_SLEEP_REACHED"
exit 0
EOF
chmod -- +x "$hostile_bin/zsh" "$hostile_bin/sleep"
cat >"$hostile_zdotdir/.zshenv" <<'EOF'
: >"$FAKE_STARTUP_ZDOTDIR_REACHED"
EOF

export FAKE_STARTUP_ATTEMPTS=$test_dir/attempts
export FAKE_STARTUP_ADAPTER_PIDS=$test_dir/adapter-pids
export FAKE_STARTUP_DESCENDANT_PIDS=$test_dir/descendant-pids
test_process_fixture_track_pid_list_file "$FAKE_STARTUP_ADAPTER_PIDS"
test_process_fixture_track_pid_list_file "$FAKE_STARTUP_DESCENDANT_PIDS"
export FAKE_STARTUP_BOOTSTRAP_LEAK_LOG=$test_dir/bootstrap-leaks
export FAKE_STARTUP_PATH_INTERPRETER_REACHED=$test_dir/path-interpreter-reached
export FAKE_STARTUP_PATH_SLEEP_REACHED=$test_dir/path-sleep-reached
export FAKE_STARTUP_ZDOTDIR_REACHED=$test_dir/zdotdir-reached
bootstrap_field=PROTON_PASS_PERSONAL_ACCESS
bootstrap_field+=_TOKEN
typeset -gx "$bootstrap_field=synthetic-bootstrap-marker"

gui_home=$test_dir/gui-home
gui_startup_bin=$test_dir/gui-startup-bin
gui_cellar_bin=$test_dir/gui-homebrew/Cellar/proton-pass-cli/2.3.2/bin
gui_path_bin=$test_dir/gui-homebrew/bin
mkdir -p -- \
  "$gui_home/.config/zsh" \
  "$gui_startup_bin" \
  "$gui_cellar_bin" \
  "$gui_path_bin"
cp -- "$startup_source" "$gui_startup_bin/proton-pass-startup"
ln -s -- "$gui_cellar_bin/pass-cli" "$gui_path_bin/pass-cli"

cat >"$gui_home/.config/zsh/startup.zsh" <<'EOF'
[[ $1 == launcher && $2 == darwin ]] || return 97
bootstrap_field=PROTON_PASS_PERSONAL_ACCESS
bootstrap_field+=_TOKEN
(( ${+parameters[$bootstrap_field]} == 0 )) ||
  print -r -- startup-policy >>"$FAKE_GUI_BOOTSTRAP_LEAK_LOG"
case $FAKE_GUI_STARTUP_POLICY_SCENARIO in
  ready)
    path=( "$FAKE_GUI_PATH_BIN" /usr/bin /bin /usr/sbin /sbin )
    print -r -- loaded >"$FAKE_GUI_STARTUP_POLICY_LOG"
    ;;
  fail)
    return 91
    ;;
  hang)
    (
      zmodload zsh/system
      zmodload zsh/zselect
      trap '' HUP TERM
      print -r -- "$sysparams[pid]" >"$FAKE_GUI_POLICY_DESCENDANT_PID"
      while true; do
        zselect -t 100 2>/dev/null || true
      done
    ) &
    wait
    ;;
  *)
    return 92
    ;;
esac
EOF
cat >"$gui_cellar_bin/pass-cli" <<'EOF'
#!/bin/zsh -f
set -euo pipefail
[[ $1 == info ]] || exit 64
print -r -- info >>"$FAKE_GUI_PASS_LOG"
EOF
cat >"$gui_startup_bin/proton-pass-ensure-ready" <<'EOF'
#!/bin/zsh -f
set -euo pipefail
bootstrap_field=PROTON_PASS_PERSONAL_ACCESS
bootstrap_field+=_TOKEN
(( ${+parameters[$bootstrap_field]} == 0 )) ||
  print -r -- readiness >>"$FAKE_GUI_BOOTSTRAP_LEAK_LOG"
[[ $(command -v pass-cli) == "$FAKE_GUI_PATH_BIN/pass-cli" ]] || exit 75
pass-cli info >/dev/null 2>&1
EOF
chmod -- +x \
  "$gui_startup_bin/proton-pass-startup" \
  "$gui_startup_bin/proton-pass-ensure-ready" \
  "$gui_cellar_bin/pass-cli"

fake_gui_startup_policy_log=$test_dir/gui-startup-policy.log
fake_gui_pass_log=$test_dir/gui-pass.log
fake_gui_bootstrap_leak_log=$test_dir/gui-bootstrap-leaks.log
fake_gui_output=$test_dir/gui-startup.out
fake_gui_policy_descendant_pid=$test_dir/gui-policy-descendant.pid
set +e
HOME=$gui_home \
  PATH=/usr/bin:/bin:/usr/sbin:/sbin \
  FAKE_GUI_STARTUP_POLICY_SCENARIO=ready \
  FAKE_GUI_PATH_BIN=$gui_path_bin \
  FAKE_GUI_STARTUP_POLICY_LOG=$fake_gui_startup_policy_log \
  FAKE_GUI_PASS_LOG=$fake_gui_pass_log \
  FAKE_GUI_BOOTSTRAP_LEAK_LOG=$fake_gui_bootstrap_leak_log \
  FAKE_GUI_POLICY_DESCENDANT_PID=$fake_gui_policy_descendant_pid \
  /bin/zsh -f -c '
    function run_darwin_startup {
      local OSTYPE=darwin23.0
      local startup_path=$1
      set --
      source "$startup_path"
    }
    run_darwin_startup "$1"
  ' proton-pass-startup "$gui_startup_bin/proton-pass-startup" \
    >"$fake_gui_output" 2>&1
gui_startup_status=$?
set -e
(( gui_startup_status == 0 )) ||
  fail "macOS startup must establish the shared GUI PATH before provider readiness: $(<"$fake_gui_output")"
[[ $(<"$fake_gui_startup_policy_log") == loaded ]] ||
  fail 'macOS startup must invoke the shared launcher PATH policy'
[[ $(<"$fake_gui_pass_log") == info ]] ||
  fail 'macOS startup readiness must use the PATH-selected provider executable'
[[ ! -e $fake_gui_bootstrap_leak_log ]] ||
  fail 'macOS startup must scrub the bootstrap token before shared PATH policy'

set +e
HOME=$gui_home \
  PATH=/usr/bin:/bin:/usr/sbin:/sbin \
  FAKE_GUI_STARTUP_POLICY_SCENARIO=fail \
  FAKE_GUI_PATH_BIN=$gui_path_bin \
  FAKE_GUI_STARTUP_POLICY_LOG=$fake_gui_startup_policy_log \
  FAKE_GUI_PASS_LOG=$fake_gui_pass_log \
  FAKE_GUI_BOOTSTRAP_LEAK_LOG=$fake_gui_bootstrap_leak_log \
  FAKE_GUI_POLICY_DESCENDANT_PID=$fake_gui_policy_descendant_pid \
  /bin/zsh -f -c '
    function run_darwin_startup {
      local OSTYPE=darwin23.0
      local startup_path=$1
      set --
      source "$startup_path"
    }
    run_darwin_startup "$1"
  ' proton-pass-startup "$gui_startup_bin/proton-pass-startup" \
    >"$fake_gui_output" 2>&1
gui_policy_failure_status=$?
set -e
(( gui_policy_failure_status == 1 )) ||
  fail 'a failed macOS PATH policy must fail startup closed'
[[ $(<"$fake_gui_output") ==
  'proton-pass-startup: the shared GUI PATH policy failed' ]] ||
  fail 'a failed macOS PATH policy must report one fixed diagnostic'

rm -f -- "$fake_gui_policy_descendant_pid"
test_process_fixture_track_pid_file "$fake_gui_policy_descendant_pid"
typeset -F gui_policy_hang_started=$EPOCHREALTIME
set +e
run_with_test_deadline \
  "$fake_gui_output" 8 \
  /usr/bin/env \
    HOME="$gui_home" \
    PATH=/usr/bin:/bin:/usr/sbin:/sbin \
    FAKE_GUI_STARTUP_POLICY_SCENARIO=hang \
    FAKE_GUI_PATH_BIN="$gui_path_bin" \
    FAKE_GUI_STARTUP_POLICY_LOG="$fake_gui_startup_policy_log" \
    FAKE_GUI_PASS_LOG="$fake_gui_pass_log" \
    FAKE_GUI_BOOTSTRAP_LEAK_LOG="$fake_gui_bootstrap_leak_log" \
    FAKE_GUI_POLICY_DESCENDANT_PID="$fake_gui_policy_descendant_pid" \
    /bin/zsh -f -c '
      function run_darwin_startup {
        local OSTYPE=darwin23.0
        local startup_path=$1
        set --
        source "$startup_path"
      }
      run_darwin_startup "$1"
    ' proton-pass-startup "$gui_startup_bin/proton-pass-startup"
gui_policy_hang_status=$?
set -e
typeset -F gui_policy_hang_elapsed=$(( EPOCHREALTIME - gui_policy_hang_started ))
(( gui_policy_hang_status == 1 &&
  gui_policy_hang_elapsed >= 2.5 && gui_policy_hang_elapsed < 6.0 )) ||
  fail 'a hanging macOS PATH policy must exhaust within its production deadline'
[[ $(<"$fake_gui_output") ==
  'proton-pass-startup: the shared GUI PATH policy failed' ]] ||
  fail 'a timed-out macOS PATH policy must report one fixed diagnostic'
gui_policy_descendant_pid=$(<"$fake_gui_policy_descendant_pid")
! kill -0 $gui_policy_descendant_pid 2>/dev/null ||
  fail 'a timed-out macOS PATH policy descendant must be terminated and reaped'
test_process_fixture_untrack_pid_file "$fake_gui_policy_descendant_pid"

reset_fixture
export FAKE_STARTUP_SCENARIO=ready
set +e
(
  unset ZDOTDIR
  export PATH=$hostile_bin:/usr/bin:/bin
  run_with_test_deadline \
    "$test_dir/hostile-path-output" 5 \
    "$fixture_bin/proton-pass-startup"
)
hostile_path_status=$?
set -e
(( hostile_path_status == 0 )) ||
  fail "the installed startup shape must execute successfully under hostile PATH: $(<"$test_dir/hostile-path-output")"
[[ $(<"$FAKE_STARTUP_ATTEMPTS") == 1 ]] ||
  fail 'a ready provider must require one readiness attempt'
[[ ! -e $FAKE_STARTUP_PATH_INTERPRETER_REACHED ]] ||
  fail 'the installed startup shape must ignore a PATH-selected zsh interpreter'

reset_fixture
set +e
(
  export PATH=/usr/bin:/bin
  export ZDOTDIR=$hostile_zdotdir
  run_with_test_deadline \
    "$test_dir/hostile-zdotdir-output" 5 \
    "$fixture_bin/proton-pass-startup"
)
hostile_zdotdir_status=$?
set -e
(( hostile_zdotdir_status == 0 )) ||
  fail 'the installed startup shape must execute successfully under hostile ZDOTDIR'
[[ $(<"$FAKE_STARTUP_ATTEMPTS") == 1 ]] ||
  fail 'a ready provider must stay ready under hostile ZDOTDIR'
[[ ! -e $FAKE_STARTUP_ZDOTDIR_REACHED ]] ||
  fail 'the installed startup shape must disable inherited ZDOTDIR startup files'

reset_fixture
export FAKE_STARTUP_SCENARIO=retry
zmodload zsh/datetime
typeset -F retry_started=$EPOCHREALTIME
set +e
(
  export PATH=$hostile_bin:/usr/bin:/bin
  run_with_test_deadline \
    "$test_dir/retry-output" 10 \
    "$fixture_bin/proton-pass-startup"
)
retry_status=$?
set -e
typeset -F retry_elapsed=$(( EPOCHREALTIME - retry_started ))
(( retry_status == 0 )) || fail 'startup must recover on its second readiness attempt'
[[ $(<"$FAKE_STARTUP_ATTEMPTS") == $'1\n2' ]] ||
  fail 'startup must make exactly two attempts before retry recovery'
(( retry_elapsed >= 4.5 && retry_elapsed < 8.0 )) ||
  fail 'startup must apply one real bounded backoff before its second attempt'
[[ ! -e $FAKE_STARTUP_PATH_SLEEP_REACHED ]] ||
  fail 'startup backoff must not invoke a PATH-selected sleep child'

if [[ -n $negative_pgid_audit_library ]]; then
  reset_fixture
  export FAKE_STARTUP_SCENARIO=hang
  zmodload zsh/zselect
  set +e
  NEGATIVE_PGID_KILL_AUDIT_LOG=$negative_pgid_audit_log \
    LD_PRELOAD=$negative_pgid_audit_library \
    "$fixture_bin/proton-pass-startup" \
      >"$test_dir/signal-cleanup-output" 2>&1 &
  integer startup_pid=$!
  integer startup_polls=100
  while (( startup_polls-- > 0 )) && \
    [[ ! -s $FAKE_STARTUP_ADAPTER_PIDS ||
      ! -s $FAKE_STARTUP_DESCENDANT_PIDS ]]; do
    zselect -t 5 2>/dev/null || true
  done
  if [[ ! -s $FAKE_STARTUP_ADAPTER_PIDS ||
    ! -s $FAKE_STARTUP_DESCENDANT_PIDS ]]; then
    kill -KILL $startup_pid 2>/dev/null || true
    wait $startup_pid 2>/dev/null || true
    set -e
    fail 'startup must reach a managed readiness process group before signal cleanup'
  fi
  kill -TERM $startup_pid 2>/dev/null
  wait $startup_pid
  integer startup_signal_status=$?
  set -e

  typeset -a signal_descendant_pids
  signal_descendant_pids=( ${(f)"$(<"$FAKE_STARTUP_DESCENDANT_PIDS")"} )
  integer signal_descendant_survived=0
  for fixture_pid in $signal_descendant_pids; do
    process_survives_grace $fixture_pid && signal_descendant_survived=1
  done
  test_process_fixture_stop_all
  (( startup_signal_status == 143 )) ||
    fail 'startup must complete managed child cleanup on TERM'
  (( signal_descendant_survived == 0 )) ||
    fail 'startup must terminate a resistant descendant during signal cleanup'
  [[ ! -s $negative_pgid_audit_log ]] ||
    fail "startup must not signal a process-group identity after it was observed absent: $(<"$negative_pgid_audit_log")"
fi

reset_fixture
export FAKE_STARTUP_SCENARIO=hang
typeset -F deadline_started=$EPOCHREALTIME
set +e
(
  unset DISPLAY DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR
  run_with_test_deadline \
    "$test_dir/deadline-output" 88 \
    "$fixture_bin/proton-pass-startup"
)
deadline_status=$?
set -e
typeset -F deadline_elapsed=$(( EPOCHREALTIME - deadline_started ))
typeset -a adapter_pids descendant_pids
adapter_pids=( ${(f)"$(<"$FAKE_STARTUP_ADAPTER_PIDS")"} )
descendant_pids=( ${(f)"$(<"$FAKE_STARTUP_DESCENDANT_PIDS")"} )
integer adapter_survived=0 descendant_survived=0
for fixture_pid in $adapter_pids; do
  process_survives_grace $fixture_pid && adapter_survived=1
done
for fixture_pid in $descendant_pids; do
  process_survives_grace $fixture_pid && descendant_survived=1
done
test_process_fixture_stop_all
(( deadline_status != 0 && deadline_status != 124 )) ||
  fail 'startup must return after exhausting its real whole-entrypoint deadline'
[[ $(<"$FAKE_STARTUP_ATTEMPTS") == $'1\n2' ]] ||
  fail 'the real deadline must cover exactly two readiness attempts'
[[ ${#adapter_pids} == 2 && ${#descendant_pids} == 2 ]] ||
  fail 'the deadline fixture must reach both adapters and descendants'
(( deadline_elapsed >= 76.0 && deadline_elapsed < 86.0 )) ||
  fail 'the real startup deadline must bound whole-entrypoint failure'
(( adapter_survived == 0 )) ||
  fail 'startup must terminate and reap both timed-out readiness adapters'
(( descendant_survived == 0 )) ||
  fail 'startup must terminate both timed-out readiness adapter descendants'
[[ $(<"$test_dir/deadline-output") ==
  'proton-pass-startup: credential provider remains unavailable; secret-backed tools retry when used' ]] ||
  fail "exhausted startup without a recorded reason must report the generic error: $(<"$test_dir/deadline-output")"
[[ ! -s $FAKE_STARTUP_BOOTSTRAP_LEAK_LOG ]] ||
  fail 'startup must scrub an inherited bootstrap token before readiness children'

set +e
usage_output=$("$fixture_bin/proton-pass-startup" --unknown 2>&1)
usage_status=$?
set -e
(( usage_status == 1 )) &&
  [[ $usage_output ==
    'proton-pass-startup: usage: proton-pass-startup [--await-prerequisites]' ]] ||
  fail "startup must reject unknown arguments: $usage_output"

# Writes a status through the helper's own writer, as an earlier run would.
write_helper_status() {
  emulate -L zsh

  /bin/zsh -f -c '
    source_text=$(<"$1")
    source_text=${source_text%$'"'"'\nmain "$@"'"'"'}
    eval "$source_text"
    trap - EXIT HUP INT TERM
    write_status "$2" "$3" unrecorded
  ' -- "$FAKE_STARTUP_HELPER_SOURCE" "$@"
}

# Exhaustion names a reason recorded during this run: one that changed the
# status after startup read it. A status that was already there is not.
# These cases run the installed startup on the host's own platform, so the
# native-store guidance follows the host.
case $OSTYPE in
  darwin*) native_store_guidance='unlock the login keychain and retry' ;;
  *) native_store_guidance='unlock the native credential store and retry' ;;
esac
export FAKE_STARTUP_SCENARIO=fail-status
for reason_case in \
  'login-token-rejected:replace the Proton Pass bootstrap token' \
  "native-store-unavailable:$native_store_guidance" \
  'session-probe-timeout:check the network; secret-backed tools retry when used' \
  'session-state-unknown:secret-backed tools retry when used'; do
  reset_fixture
  rm -rf -- "$XDG_STATE_HOME"
  export FAKE_STARTUP_STATUS_REASON=${reason_case%%:*}
  set +e
  (
    unset DISPLAY DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR
    run_with_test_deadline "$test_dir/reason-output" 12 \
      "$fixture_bin/proton-pass-startup"
  )
  reason_status=$?
  set -e
  (( reason_status == 1 )) ||
    fail "startup must fail after two recorded $FAKE_STARTUP_STATUS_REASON attempts"
  [[ $(<"$test_dir/reason-output") ==
    "proton-pass-startup: credential provider remains unavailable ($FAKE_STARTUP_STATUS_REASON); ${reason_case#*:}" ]] ||
    fail "startup must name the recorded $FAKE_STARTUP_STATUS_REASON: $(<"$test_dir/reason-output")"
done
# An earlier specific failure, then attempts that record nothing: neither the
# old reason nor the old last failure is named.
reset_fixture
rm -rf -- "$XDG_STATE_HOME"
write_helper_status unavailable login-token-rejected
unset FAKE_STARTUP_STATUS_REASON
set +e
(
  unset DISPLAY DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR
  run_with_test_deadline "$test_dir/stale-reason-output" 12 \
    "$fixture_bin/proton-pass-startup"
)
set -e
[[ $(<"$test_dir/stale-reason-output") ==
  'proton-pass-startup: credential provider remains unavailable; secret-backed tools retry when used' ]] ||
  fail "startup must not attribute an earlier status to this run: $(<"$test_dir/stale-reason-output")"

# A resolved failure lingers as the last failure under a later ready status.
# Its timestamp must not make it this run's, even if the clock is behind.
reset_fixture
rm -rf -- "$XDG_STATE_HOME"
write_helper_status unavailable login-token-rejected
write_helper_status ready repaired
# As if that failure was recorded while the clock ran an hour ahead.
zmodload zsh/datetime
resolved_status=$XDG_STATE_HOME/secret-exec/proton-pass-readiness.status
resolved_text=$(<"$resolved_status")
[[ $resolved_text == *$'\nlast-failure-at='<->* ]] ||
  fail 'the helper must keep the resolved failure under its ready status'
print -r -- "${resolved_text/last-failure-at=<->/last-failure-at=$(( EPOCHSECONDS + 3600 ))}" \
  >"$resolved_status"
export FAKE_STARTUP_STATUS_REASON=session-probe-timeout
set +e
(
  unset DISPLAY DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR
  run_with_test_deadline "$test_dir/resolved-reason-output" 12 \
    "$fixture_bin/proton-pass-startup"
)
set -e
[[ $(<"$test_dir/resolved-reason-output") ==
  'proton-pass-startup: credential provider remains unavailable (session-probe-timeout); check the network; secret-backed tools retry when used' ]] ||
  fail "startup must not name a resolved earlier failure: $(<"$test_dir/resolved-reason-output")"

# Without the flag no prerequisite is awaited, and an inherited verdict never
# reaches a message.
reset_fixture
rm -rf -- "$XDG_STATE_HOME"
export FAKE_STARTUP_STATUS_REASON=session-state-unknown
set +e
(
  unset DISPLAY DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR
  export PROTON_PASS_UNMET_PREREQUISITE=$'inherited\nverdict'
  run_with_test_deadline "$test_dir/inherited-verdict-output" 12 \
    "$fixture_bin/proton-pass-startup"
)
set -e
[[ $(<"$test_dir/inherited-verdict-output") ==
  'proton-pass-startup: credential provider remains unavailable (session-state-unknown); secret-backed tools retry when used' ]] ||
  fail "startup must ignore an inherited prerequisite verdict: $(<"$test_dir/inherited-verdict-output")"
unset FAKE_STARTUP_STATUS_REASON
rm -rf -- "$XDG_STATE_HOME"

# Login-time prerequisites. Only the fixed busctl path and the wait bound are
# substituted; the probes, private capture, and wait loop run as shipped.
fake_busctl=$test_dir/fake-busctl
cat >"$fake_busctl" <<'EOF'
#!/bin/zsh -f
set -euo pipefail

print -r -- "$*" >>"$FAKE_BUSCTL_LOG"
# A boot clock that advances with real time from FAKE_UPTIME_ORIGIN.
if [[ -n ${FAKE_UPTIME_ORIGIN:-} ]]; then
  zmodload zsh/datetime
  printf '%.2f 50.00\n' $(( 100 + EPOCHREALTIME - FAKE_UPTIME_ORIGIN )) \
    >"$FAKE_STARTUP_UPTIME_FILE"
fi
wallet_query='--user --no-pager get-property org.freedesktop.secrets'
wallet_query+=' /org/freedesktop/secrets/aliases/default'
wallet_query+=' org.freedesktop.Secret.Collection Locked'
network_query='--system --no-pager get-property org.freedesktop.NetworkManager'
network_query+=' /org/freedesktop/NetworkManager org.freedesktop.NetworkManager State'
case $* in
  "$wallet_query")
    integer wallet_calls=0
    [[ ! -s $FAKE_BUSCTL_WALLET_CALLS ]] ||
      wallet_calls=$(<"$FAKE_BUSCTL_WALLET_CALLS")
    (( ++wallet_calls ))
    print -r -- "$wallet_calls" >"$FAKE_BUSCTL_WALLET_CALLS"
    # Advances a fake boot clock by a fixed step per wallet probe.
    if [[ -n ${FAKE_UPTIME_STEP:-} ]]; then
      IFS=' ' read -r uptime_now uptime_idle <"$FAKE_STARTUP_UPTIME_FILE"
      print -r -- "$(( ${uptime_now%.*} + FAKE_UPTIME_STEP )).00 $uptime_idle" \
        >"$FAKE_STARTUP_UPTIME_FILE"
    fi
    case $FAKE_BUSCTL_WALLET in
      unlocked) print -r -- 'b false' ;;
      locked) print -r -- 'b true' ;;
      unlocks-on-third)
        if (( wallet_calls >= 3 )); then
          print -r -- 'b false'
        else
          print -r -- 'b true'
        fi
        ;;
      unreachable) exit 1 ;;
      extra-line) print -rl -- 'b false' 'b false' ;;
      *) exit 64 ;;
    esac
    ;;
  "$network_query")
    case $FAKE_BUSCTL_NETWORK in
      global) print -r -- 'u 70' ;;
      site) print -r -- 'u 60' ;;
      absent) exit 1 ;;
      *) exit 64 ;;
    esac
    ;;
  *) exit 64 ;;
esac
EOF
chmod -- 700 "$fake_busctl"
export FAKE_BUSCTL_LOG=$test_dir/busctl.log
export FAKE_BUSCTL_WALLET_CALLS=$test_dir/busctl-wallet-calls

fake_notifier=$test_dir/fake-notifier
cat >"$fake_notifier" <<'EOF'
#!/bin/zsh -f
set -euo pipefail

print -r -- "${0:t} ${(j:|:)@}" >>"$FAKE_NOTIFY_LOG"
EOF
chmod -- 700 "$fake_notifier"
ln -s -- fake-notifier "$test_dir/notify-send"
ln -s -- fake-notifier "$test_dir/osascript"
export FAKE_NOTIFY_LOG=$test_dir/notify.log
export FAKE_STARTUP_UPTIME_FILE=

# Linux-only waits run on a boot clock that the fake busctl advances with real
# time, so no case reads the host's /proc/uptime.
linux_boot_clock=$test_dir/linux-boot-clock
start_linux_boot_clock() {
  print -r -- '100.00 50.00' >"$linux_boot_clock"
  export FAKE_STARTUP_UPTIME_FILE=$linux_boot_clock
  export FAKE_UPTIME_ORIGIN=$EPOCHREALTIME
}
stop_linux_boot_clock() {
  rm -f -- "$linux_boot_clock"
  export FAKE_STARTUP_UPTIME_FILE=
  unset FAKE_UPTIME_ORIGIN
}

# Only fixed paths and the wait bound are substituted, each at an anchor that
# must exist; the probes, capture, wait, and reporting run as shipped. An empty
# platform keeps the host's OSTYPE, so each case that expects one platform's
# behavior names it.
run_startup_functions() {
  emulate -L zsh

  local ostype=$1
  shift
  /bin/zsh -f -c '
    source_text=$(<"$1")
    source_text=${source_text%$'"'"'\nmain "$@"'"'"'}
    typeset -A substitutions=(
      "readonly PROTON_PASS_BUSCTL=/usr/bin/busctl"
        "readonly PROTON_PASS_BUSCTL=$2"
      "readonly PROTON_PASS_PREREQUISITE_WAIT_SECONDS=60"
        "readonly PROTON_PASS_PREREQUISITE_WAIT_SECONDS=3"
      "local notify_send=/usr/bin/notify-send"
        "local notify_send=$4/notify-send"
      "local osascript=/usr/bin/osascript"
        "local osascript=$4/osascript"
    )
    uptime_anchor="readonly PROTON_PASS_UPTIME_FILE=/proc/uptime"
    [[ -z $FAKE_STARTUP_UPTIME_FILE ]] ||
      substitutions[$uptime_anchor]="readonly PROTON_PASS_UPTIME_FILE=$FAKE_STARTUP_UPTIME_FILE"
    for anchor in "${(@k)substitutions}"; do
      [[ $source_text == *"$anchor"* ]] || exit 90
      source_text=${source_text/$anchor/$substitutions[$anchor]}
      [[ $source_text != *"$anchor"* ]] || exit 91
    done
    # No other use of a substituted fixed path may escape the fixtures.
    typeset -a substituted_paths=(
      /usr/bin/busctl /usr/bin/notify-send /usr/bin/osascript
    )
    [[ -z $FAKE_STARTUP_UPTIME_FILE ]] || substituted_paths+=(/proc/uptime)
    for fixed_path in $substituted_paths; do
      [[ $source_text != *"$fixed_path"* ]] || exit 92
    done
    fixture_ostype=$3
    shift 4
    eval "$source_text"
    [[ -z $fixture_ostype ]] || OSTYPE=$fixture_ostype
    eval "$@"
  ' "$fixture_bin/proton-pass-startup" "$startup_source" "$fake_busctl" \
    "$ostype" "$test_dir" "$@"
}

typeset -a prerequisite_cases=(
  'unlocked:global:linux-gnu:none:0:0'
  'unlocks-on-third:global:linux-gnu:none:1:3'
  'unlocked:site:linux-gnu:network-offline:3:5'
  'locked:global:linux-gnu:native-store-locked:3:5'
  'unreachable:global:linux-gnu:native-store-locked:3:5'
  'extra-line:global:linux-gnu:native-store-locked:3:5'
  'unlocked:absent:linux-gnu:none:0:0'
  'locked:site:darwin23.0:none:0:0'
)
for prerequisite_case in $prerequisite_cases; do
  typeset -a case_fields=( "${(@s/:/)prerequisite_case}" )
  export FAKE_BUSCTL_WALLET=$case_fields[1] FAKE_BUSCTL_NETWORK=$case_fields[2]
  : >"$FAKE_BUSCTL_LOG"
  rm -f -- "$FAKE_BUSCTL_WALLET_CALLS"
  start_linux_boot_clock
  prerequisite_output=$(
    run_startup_functions "$case_fields[3]" '
      zmodload zsh/datetime
      typeset -F started=$EPOCHREALTIME
      await_prerequisites
      integer elapsed=$(( EPOCHREALTIME - started ))
      print -r -- "${PROTON_PASS_UNMET_PREREQUISITE:-none} $elapsed"'
  ) || fail "the prerequisite wait must run for $prerequisite_case"
  unmet=${prerequisite_output%% *}
  integer elapsed=${prerequisite_output##* }
  [[ $unmet == $case_fields[4] ]] ||
    fail "prerequisites $prerequisite_case must report $case_fields[4], not $unmet"
  (( elapsed >= case_fields[5] && elapsed <= case_fields[6] )) ||
    fail "prerequisites $prerequisite_case must wait ${case_fields[5]}-${case_fields[6]} s, not $elapsed"
done
stop_linux_boot_clock
[[ ! -s $FAKE_BUSCTL_LOG ]] ||
  fail 'the prerequisite wait must not probe outside Linux'

# The deadline follows the boot clock, not the wall clock: a boot clock that
# races ahead ends the wait at once, and an unreadable one skips the wait.
fake_uptime=$test_dir/fake-uptime
print -r -- '100.00 50.00' >"$fake_uptime"
export FAKE_STARTUP_UPTIME_FILE=$fake_uptime FAKE_UPTIME_STEP=30
export FAKE_BUSCTL_WALLET=locked FAKE_BUSCTL_NETWORK=global
rm -f -- "$FAKE_BUSCTL_WALLET_CALLS"
uptime_output=$(
  run_startup_functions linux-gnu '
    zmodload zsh/datetime
    typeset -F started=$EPOCHREALTIME
    await_prerequisites
    integer elapsed=$(( EPOCHREALTIME - started ))
    print -r -- "${PROTON_PASS_UNMET_PREREQUISITE:-none} $elapsed"'
) || fail 'the boot-clock wait must run'
[[ $uptime_output == 'native-store-locked 0' &&
  $(<"$FAKE_BUSCTL_WALLET_CALLS") == 1 ]] ||
  fail "the prerequisite deadline must follow the boot clock: $uptime_output"
rm -f -- "$fake_uptime" "$FAKE_BUSCTL_WALLET_CALLS"
unset FAKE_UPTIME_STEP
uptime_output=$(
  run_startup_functions linux-gnu '
    await_prerequisites
    print -r -- "${PROTON_PASS_UNMET_PREREQUISITE:-none}"'
) || fail 'the wait must survive an unreadable boot clock'
[[ $uptime_output == none && ! -e $FAKE_BUSCTL_WALLET_CALLS ]] ||
  fail "an unreadable boot clock must skip the prerequisite wait: $uptime_output"
export FAKE_STARTUP_UPTIME_FILE=

# The flag opts in: plain startup never probes.
reset_fixture
export FAKE_STARTUP_SCENARIO=ready FAKE_BUSCTL_WALLET=locked FAKE_BUSCTL_NETWORK=site
: >"$FAKE_BUSCTL_LOG"
run_startup_functions linux-gnu main ||
  fail 'startup without the prerequisite flag must reach readiness'
[[ ! -s $FAKE_BUSCTL_LOG ]] ||
  fail 'startup without the prerequisite flag must not probe prerequisites'

# A specific failure recorded during this run wins over the prerequisite
# verdict, except that being offline replaces the helper's catch-alls. A
# locked wallet cannot, since login had already read the bootstrap item. An
# unmet prerequisite still replaces a generic recorded reason.
for precedence_case in \
  'unlocked:site:session-probe-timeout:network-offline:check the network; secret-backed tools retry when used' \
  'unlocked:site:login-failed:network-offline:check the network; secret-backed tools retry when used' \
  'unlocked:site:verify-failed:network-offline:check the network; secret-backed tools retry when used' \
  'locked:global:login-failed:login-failed:secret-backed tools retry when used' \
  'unlocked:site:login-token-rejected:login-token-rejected:replace the Proton Pass bootstrap token' \
  'locked:global:login-token-rejected:login-token-rejected:replace the Proton Pass bootstrap token'; do
  typeset -a case_fields=( "${(@s/:/)precedence_case}" )
  reset_fixture
  rm -rf -- "$XDG_STATE_HOME"
  : >"$FAKE_BUSCTL_LOG" >"$FAKE_NOTIFY_LOG"
  export FAKE_STARTUP_SCENARIO=fail-status
  export FAKE_BUSCTL_WALLET=$case_fields[1] FAKE_BUSCTL_NETWORK=$case_fields[2]
  export FAKE_STARTUP_STATUS_REASON=$case_fields[3]
  start_linux_boot_clock
  set +e
  prerequisite_failure_output=$(
    run_startup_functions linux-gnu main --await-prerequisites 2>&1
  )
  prerequisite_failure_status=$?
  set -e
  (( prerequisite_failure_status == 1 )) ||
    fail "startup must fail for $precedence_case"
  [[ $prerequisite_failure_output ==
    "proton-pass-startup: credential provider remains unavailable ($case_fields[4]); $case_fields[5]" ]] ||
    fail "startup must name $case_fields[4] for $precedence_case: $prerequisite_failure_output"
  [[ $(<"$FAKE_STARTUP_ATTEMPTS") == $'1\n2' ]] ||
    fail 'an unmet prerequisite must still leave both readiness attempts'
  [[ -s $FAKE_BUSCTL_LOG ]] ||
    fail 'the prerequisite flag must probe prerequisites'
done
stop_linux_boot_clock
unset FAKE_STARTUP_STATUS_REASON
rm -rf -- "$XDG_STATE_HOME"

# The notification carries the same verdict as the diagnostic. macOS passes
# the text to its script as arguments, never inside the script source.
typeset -a notification_cases=(
  'linux-gnu:native-store-locked::notify-send --app-name=Secret-backed tools|Credential provider unavailable|Unlock the native credential store. Secret-backed tools will retry when used.'
  'linux-gnu:network-offline::notify-send --app-name=Secret-backed tools|Credential provider unavailable|Proton Pass could not be reached. Secret-backed tools will retry when used.'
  'linux-gnu::login-token-malformed:notify-send --app-name=Secret-backed tools|Credential provider unavailable|The Proton Pass bootstrap token is invalid or was rejected. Replace it; secret-backed tools cannot recover until then.'
  'linux-gnu::session-state-unknown:notify-send --app-name=Secret-backed tools|Credential provider unavailable|Proton Pass is unavailable (session-state-unknown). Secret-backed tools will retry when used.'
  'linux-gnu:::notify-send --app-name=Secret-backed tools|Credential provider unavailable|Proton Pass is unavailable. Secret-backed tools will retry when used.'
  'darwin23.0:native-store-locked::osascript -e|on run argv|-e|display notification (item 1 of argv) with title (item 2 of argv)|-e|end run|Unlock the login keychain. Secret-backed tools will retry when used.|Credential provider unavailable'
)
for notification_case in $notification_cases; do
  typeset -a case_fields=( "${(@s/:/)notification_case}" )
  rm -rf -- "$XDG_STATE_HOME"
  : >"$FAKE_NOTIFY_LOG"
  [[ -z $case_fields[3] ]] ||
    write_helper_status unavailable "$case_fields[3]"
  # An empty before-snapshot attributes whatever status exists to this run.
  set +e
  run_startup_functions "$case_fields[1]" \
    "PROTON_PASS_UNMET_PREREQUISITE=${(q)case_fields[2]}; report_unavailable '' ''" \
    >/dev/null 2>&1
  set -e
  [[ $(<"$FAKE_NOTIFY_LOG") == "${(j.:.)case_fields[4,-1]}" ]] ||
    fail "the notification must carry the verdict for $notification_case: $(<"$FAKE_NOTIFY_LOG")"
done
rm -rf -- "$XDG_STATE_HOME"

print -r -- 'Proton Pass startup behavior checks passed'
