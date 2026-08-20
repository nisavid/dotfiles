#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
startup_source=$repo_root/home/private_dot_local/bin/executable_proton-pass-startup

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
chmod +x -- "$fixture_bin/proton-pass-startup"

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
[[ -z ${PROVIDER_COMPLETION_MARKER:-} ]] ||
  print -r -- provider-completed >>"$PROVIDER_COMPLETION_MARKER"
EOF
chmod +x -- \
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
chmod +x -- "$fixture_bin/proton-pass-ensure-ready"

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
chmod +x -- "$hostile_bin/zsh" "$hostile_bin/sleep"
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
    "$test_dir/deadline-output" 68 \
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
(( deadline_elapsed >= 56.0 && deadline_elapsed < 66.0 )) ||
  fail 'the real startup deadline must bound whole-entrypoint failure'
(( adapter_survived == 0 )) ||
  fail 'startup must terminate and reap both timed-out readiness adapters'
(( descendant_survived == 0 )) ||
  fail 'startup must terminate both timed-out readiness adapter descendants'
[[ $(<"$test_dir/deadline-output") ==
  'proton-pass-startup: credential provider remains unavailable; unlock the native credential store and retry' ]] ||
  fail 'exhausted startup must report one fixed actionable error'
[[ ! -s $FAKE_STARTUP_BOOTSTRAP_LEAK_LOG ]] ||
  fail 'startup must scrub an inherited bootstrap token before readiness children'

print -r -- 'Proton Pass startup behavior checks passed'
