if (( ${+parameters[TEST_PROCESS_FIXTURE_HELPER_LOADED]} )); then
  return 0
fi

typeset -gr TEST_PROCESS_FIXTURE_HELPER_LOADED=1
typeset -g TEST_PROCESS_FIXTURE_ROOT=
typeset -gA TEST_PROCESS_FIXTURE_PIDS=()
typeset -gA TEST_PROCESS_FIXTURE_PID_FILES=()
typeset -gA TEST_PROCESS_FIXTURE_PID_LIST_FILES=()
typeset -gA TEST_PROCESS_FIXTURE_STOPPING_PIDS=()

test_process_fixture_init() {
  emulate -L zsh

  local root=${1-}
  (( $# == 1 )) && [[ $root == /* && $root != / ]] || return 64
  [[ -z $TEST_PROCESS_FIXTURE_ROOT || $TEST_PROCESS_FIXTURE_ROOT == $root ]] ||
    return 64

  TEST_PROCESS_FIXTURE_ROOT=$root
  TEST_PROCESS_FIXTURE_PIDS=()
  TEST_PROCESS_FIXTURE_PID_FILES=()
  TEST_PROCESS_FIXTURE_PID_LIST_FILES=()
  TEST_PROCESS_FIXTURE_STOPPING_PIDS=()
}

test_process_fixture_track_pid() {
  emulate -L zsh

  local pid=${1-}
  (( $# == 1 )) && [[ $pid == <-> ]] && (( pid > 1 )) || return 64
  TEST_PROCESS_FIXTURE_PIDS[$pid]=1
}

test_process_fixture_untrack_pid() {
  emulate -L zsh

  (( $# == 1 )) || return 64
  unset "TEST_PROCESS_FIXTURE_PIDS[$1]"
}

test_process_fixture_track_pid_file() {
  emulate -L zsh

  local pid_file=${1-}
  (( $# == 1 )) && [[ $pid_file == /* ]] || return 64
  TEST_PROCESS_FIXTURE_PID_FILES[$pid_file]=1
}

test_process_fixture_untrack_pid_file() {
  emulate -L zsh

  (( $# == 1 )) || return 64
  unset "TEST_PROCESS_FIXTURE_PID_FILES[$1]"
}

test_process_fixture_track_pid_list_file() {
  emulate -L zsh

  local pid_file=${1-}
  (( $# == 1 )) && [[ $pid_file == /* ]] || return 64
  TEST_PROCESS_FIXTURE_PID_LIST_FILES[$pid_file]=1
}

test_process_fixture_wait_for_pid_exit() {
  emulate -L zsh

  local pid=${1-}
  integer polls=${2:-50}
  [[ $pid == <-> ]] && (( pid > 1 && polls >= 0 )) || return 64

  zmodload zsh/zselect || return 1
  while (( polls-- > 0 )) && kill -0 $pid 2>/dev/null; do
    zselect -t 1 2>/dev/null || true
  done
  ! kill -0 $pid 2>/dev/null
}

test_process_fixture_stop_all() {
  emulate -L zsh
  unsetopt err_exit

  zmodload zsh/system 2>/dev/null || return 0
  zmodload zsh/zselect 2>/dev/null || return 0

  local -A targets=()
  local -a consumed_pid_list_files=()
  local pid_file pid
  integer own_pid=$sysparams[pid]
  for pid in ${(k)TEST_PROCESS_FIXTURE_STOPPING_PIDS}; do
    [[ $pid == <-> && $pid -gt 1 && $pid -ne own_pid ]] && targets[$pid]=1
  done
  for pid in ${(k)TEST_PROCESS_FIXTURE_PIDS}; do
    [[ $pid == <-> && $pid -gt 1 && $pid -ne own_pid ]] && targets[$pid]=1
  done
  for pid_file in ${(k)TEST_PROCESS_FIXTURE_PID_FILES}; do
    [[ -s $pid_file ]] || continue
    pid=$(<"$pid_file")
    [[ $pid == <-> && $pid -gt 1 && $pid -ne own_pid ]] && targets[$pid]=1
  done
  for pid_file in ${(k)TEST_PROCESS_FIXTURE_PID_LIST_FILES}; do
    [[ -s $pid_file ]] || continue
    while IFS= read -r pid; do
      [[ $pid == <-> && $pid -gt 1 && $pid -ne own_pid ]] && targets[$pid]=1
    done <"$pid_file"
    consumed_pid_list_files+=("$pid_file")
  done
  for pid in ${(k)targets}; do
    TEST_PROCESS_FIXTURE_STOPPING_PIDS[$pid]=1
  done
  TEST_PROCESS_FIXTURE_PIDS=()
  TEST_PROCESS_FIXTURE_PID_FILES=()
  integer consumption_failed=0
  for pid_file in $consumed_pid_list_files; do
    if ! : >"$pid_file"; then
      print -u2 -r -- "process fixture: could not consume PID list $pid_file"
      consumption_failed=1
    fi
  done

  for pid in ${(k)targets}; do
    kill -TERM $pid 2>/dev/null || true
  done
  integer polls=5
  while (( polls-- > 0 )); do
    integer live=0
    for pid in ${(k)targets}; do
      kill -0 $pid 2>/dev/null && live=1
    done
    (( live )) || break
    zselect -t 1 2>/dev/null || true
  done
  for pid in ${(k)targets}; do
    kill -0 $pid 2>/dev/null && kill -KILL $pid 2>/dev/null || true
  done
  for pid in ${(k)targets}; do
    wait $pid 2>/dev/null || true
  done
  polls=10
  while (( polls-- > 0 )); do
    integer live=0
    for pid in ${(k)targets}; do
      kill -0 $pid 2>/dev/null && live=1
    done
    (( live )) || break
    zselect -t 1 2>/dev/null || true
  done
  for pid in ${(k)targets}; do
    kill -0 $pid 2>/dev/null || unset "TEST_PROCESS_FIXTURE_STOPPING_PIDS[$pid]"
  done
  (( ! consumption_failed ))
}

test_process_fixture_cleanup() {
  integer cleanup_status=$?
  emulate -L zsh
  unsetopt err_exit
  local fixture_root=$TEST_PROCESS_FIXTURE_ROOT

  trap - EXIT HUP INT TERM
  test_process_fixture_stop_all || true
  TEST_PROCESS_FIXTURE_PID_LIST_FILES=()
  TEST_PROCESS_FIXTURE_STOPPING_PIDS=()
  TEST_PROCESS_FIXTURE_ROOT=
  if [[ $fixture_root == /* && $fixture_root != / ]]; then
    /bin/rm -rf -- "$fixture_root"
  fi
  return $cleanup_status
}

test_process_fixture_run_signal_probe_mode() {
  emulate -L zsh

  local pid_file=${TEST_PROCESS_FIXTURE_SIGNAL_PROBE_PID_FILE-}
  local ready_file=${TEST_PROCESS_FIXTURE_SIGNAL_PROBE_READY_FILE-}
  [[ -n $pid_file ]] || return 0
  [[ $pid_file == /* && $ready_file == /* ]] || return 64

  zmodload zsh/zselect || return 1
  /bin/zsh -f -c '
    zmodload zsh/system
    zmodload zsh/zselect
    trap "" HUP INT TERM
    print -r -- "$sysparams[pid]" >"$1"
    while true; do
      zselect -t 10 2>/dev/null || true
    done
  ' -- "$pid_file" &
  integer child_pid=$!
  test_process_fixture_track_pid $child_pid

  integer polls=100
  while [[ ! -s $pid_file && polls -gt 0 ]]; do
    (( --polls ))
    zselect -t 1 2>/dev/null || true
  done
  [[ -s $pid_file ]] || return 1
  : >"$ready_file"
  while true; do
    zselect -t 10 2>/dev/null || true
  done
}

test_process_fixture_assert_signal_cleanup() {
  emulate -L zsh
  unsetopt err_exit

  local script_path=${1-}
  local signal_name=${2-}
  integer expected_status=${3:-0}
  local output_prefix=${4-}
  (( $# == 4 )) || return 64
  [[ $script_path == /* && $output_prefix == /* ]] || return 64
  [[ $signal_name == HUP || $signal_name == INT || $signal_name == TERM ]] ||
    return 64

  local pid_file=$output_prefix-child.pid
  local ready_file=$output_prefix.ready
  local stdout_file=$output_prefix.out
  local stderr_file=$output_prefix.err
  test_process_fixture_track_pid_file "$pid_file" || return

  TEST_PROCESS_FIXTURE_SIGNAL_PROBE_PID_FILE=$pid_file \
    TEST_PROCESS_FIXTURE_SIGNAL_PROBE_READY_FILE=$ready_file \
    /bin/zsh -f "$script_path" >"$stdout_file" 2>"$stderr_file" &
  integer runner_pid=$!
  test_process_fixture_track_pid $runner_pid || return

  zmodload zsh/zselect || return 1
  integer polls=100
  while [[ ! -e $ready_file && polls -gt 0 ]]; do
    (( --polls ))
    zselect -t 1 2>/dev/null || true
  done
  if [[ ! -e $ready_file ]]; then
    print -u2 -r -- "$signal_name cleanup signal probe did not start"
    return 1
  fi

  kill -"$signal_name" $runner_pid 2>/dev/null || return 1
  integer runner_status
  if wait $runner_pid; then
    runner_status=0
  else
    runner_status=$?
  fi
  test_process_fixture_untrack_pid $runner_pid

  if [[ ! -s $pid_file ]]; then
    print -u2 -r -- "$signal_name cleanup signal probe did not record its child"
    return 1
  fi
  integer child_pid=$(<"$pid_file")
  if ! test_process_fixture_wait_for_pid_exit $child_pid 20; then
    print -u2 -r -- "the EXIT trap did not reap the $signal_name-resistant fixture child"
    return 1
  fi
  test_process_fixture_untrack_pid_file "$pid_file"

  if (( runner_status != expected_status )); then
    print -u2 -r -- \
      "the $signal_name trap returned $runner_status instead of $expected_status"
    return 1
  fi
}
