#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
launcher_source=$repo_root/home/private_dot_local/bin/executable_secret-exec
readiness_source=$repo_root/home/private_dot_local/bin/executable_proton-pass-ensure-ready

fail() {
  print -u2 -r -- "$1"
  return 1
}

classify_login_outcome() {
  emulate -L zsh

  local outcome_file=$1
  local aggregate=unrecorded outcome=
  if [[ -s $outcome_file ]]; then
    while IFS= read -r outcome || [[ -n $outcome ]]; do
      case $outcome in
        completed)
          aggregate=completed
          ;;
        argv-failed|bootstrap-failed)
          [[ $aggregate == completed ]] || aggregate=$outcome
          ;;
        started)
          [[ $aggregate == unrecorded ]] && aggregate=started
          ;;
      esac
    done < "$outcome_file"
  fi
  print -r -- "$aggregate"
}

classify_latest_readiness_status() {
  emulate -L zsh

  local readiness_file=$1
  local readiness_reason=unrecorded
  local waiter_stage=unrecorded
  local readiness_status_line
  if [[ -r $readiness_file ]]; then
    while IFS= read -r readiness_status_line || [[ -n $readiness_status_line ]]; do
      case $readiness_status_line in
        reason=existing-session|reason=concurrent-repair|reason=repaired|\
        reason=unsafe-lock|reason=lock-timeout|reason=concurrent-repair-failed|\
        reason=native-store-timeout|\
        reason=native-store-unavailable|reason=invalid-bootstrap-value|\
        reason=login-timeout|reason=login-failed|reason=verify-timeout|\
        reason=verify-failed)
          readiness_reason=${readiness_status_line#reason=}
          ;;
        waiter-stage=record|waiter-stage=identity|\
        waiter-stage=liveness-retry|waiter-stage=child-status|\
        waiter-stage=retirement|waiter-stage=unrecorded)
          waiter_stage=${readiness_status_line#waiter-stage=}
          ;;
      esac
    done < "$readiness_file"
  fi
  print -r -- "$readiness_reason"
  print -r -- "$waiter_stage"
}

process_fixture_helper=$repo_root/tests/helpers/process-fixture.zsh
[[ -r $process_fixture_helper ]] ||
  fail 'the shared process-fixture helper is required'
source "$process_fixture_helper"

assert_invalid_profiles() {
  local label=$1
  rm -f -- "$TARGET_MARKER"
  set +e
  zsh "$launcher" context7 -- mark-target > /dev/null 2>&1
  local exit_code=$?
  set -e
  (( exit_code != 0 )) || fail "$label must fail closed"
  [[ ! -e $TARGET_MARKER ]] || fail "$label must never run the target"
}

test_dir=$(mktemp -d "${TMPDIR:-/tmp}/secret-exec.XXXXXX")
test_process_fixture_init "$test_dir" || fail 'could not initialize process-fixture cleanup'
trap test_process_fixture_cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
latest_readiness_probe=$test_dir/latest-shared-readiness.status
for latest_ready_reason in existing-session concurrent-repair repaired; do
  print -rl -- state=ready "reason=$latest_ready_reason" \
    waiter-stage=unrecorded updated_at=0 > "$latest_readiness_probe"
  typeset -a latest_readiness_classification=(
    "${(@f)$(classify_latest_readiness_status "$latest_readiness_probe")}"
  )
  [[ ${latest_readiness_classification[1]:-} == $latest_ready_reason &&
    ${latest_readiness_classification[2]:-} == unrecorded ]] ||
    fail "the latest shared ready status must preserve $latest_ready_reason"
done
rm -f -- "$latest_readiness_probe"
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
  [[ -x /usr/bin/setsid ]] ||
    fail 'the Linux fragmented-signal test requires /usr/bin/setsid'
  kill_audit_library=$test_dir/negative-pgid-kill-audit.so
  /usr/bin/cc -shared -fPIC -O2 -Wall -Wextra -Werror \
    -o "$kill_audit_library" \
    "$repo_root/tests/fixtures/negative-pgid-kill-audit.c" -ldl
  status_fragment_library=$test_dir/zpty-status-fragment.so
  /usr/bin/cc -shared -fPIC -O2 -Wall -Wextra -Werror \
    -o "$status_fragment_library" \
    "$repo_root/tests/fixtures/zpty-status-fragment.c" -ldl

  zmodload zsh/zselect || fail 'the setsid identity probe requires zsh/zselect'
  /usr/bin/setsid /bin/sleep 10 &
  setsid_probe_pid=$!
  test_process_fixture_track_pid $setsid_probe_pid
  integer setsid_probe_polls=100
  typeset setsid_probe_listing=
  typeset -a setsid_probe_fields
  while (( setsid_probe_polls-- > 0 )); do
    setsid_probe_listing=$(
      /bin/ps -o pid=,pgid=,sid= -p $setsid_probe_pid 2>/dev/null
    ) || true
    setsid_probe_fields=( ${=setsid_probe_listing} )
    if (( ${#setsid_probe_fields} == 3 &&
      setsid_probe_fields[1] == setsid_probe_pid &&
      setsid_probe_fields[2] == setsid_probe_pid &&
      setsid_probe_fields[3] == setsid_probe_pid )); then
      break
    fi
    zselect -t 1 2>/dev/null || true
  done
  if (( ${#setsid_probe_fields} != 3 ||
    setsid_probe_fields[1] != setsid_probe_pid ||
    setsid_probe_fields[2] != setsid_probe_pid ||
    setsid_probe_fields[3] != setsid_probe_pid )); then
    kill -TERM $setsid_probe_pid 2>/dev/null || true
    wait $setsid_probe_pid 2>/dev/null || true
    test_process_fixture_untrack_pid $setsid_probe_pid
    fail 'background setsid must preserve its PID as the session leader'
  fi
  kill -TERM -- -$setsid_probe_pid 2>/dev/null || true
  wait $setsid_probe_pid 2>/dev/null || true
  test_process_fixture_untrack_pid $setsid_probe_pid
fi

test_process_fixture_assert_signal_cleanup \
  "${0:A}" TERM 143 "$test_dir/cleanup-term" ||
  fail 'the TERM cleanup contract must terminate fixtures and preserve status'

fixture_home=$test_dir/home
profile_dir=$fixture_home/.config/secret-exec/profiles
fake_bin=$test_dir/bin
fixture_local_bin=$fixture_home/.local/bin
mkdir -p -- "$profile_dir" "$fake_bin" "$fixture_local_bin"
chmod 700 "$fixture_home/.config/secret-exec" "$profile_dir"

launcher=$fixture_local_bin/secret-exec
readiness=$fixture_local_bin/proton-pass-ensure-ready
native_store_adapter=$fixture_local_bin/secret-exec-native-store
proton_bootstrap_field=PROTON_PASS_PERSONAL_ACCESS
proton_bootstrap_field+=_TOKEN
cp "$launcher_source" "$launcher"
cp "$readiness_source" "$readiness"
chmod +x "$launcher" "$readiness"

hostile_shell_dir=$test_dir/hostile-shell
hostile_zdotdir=$test_dir/hostile-zdotdir
empty_zdotdir=$test_dir/empty-zdotdir
hostile_shell_marker=$test_dir/hostile-shell-ran
hostile_zdotdir_marker=$test_dir/hostile-zdotdir-ran
mkdir -p -- "$hostile_shell_dir" "$hostile_zdotdir" "$empty_zdotdir"
cat > "$hostile_shell_dir/zsh" <<'EOF'
#!/bin/sh
: > "$HOSTILE_SHELL_MARKER"
exit 90
EOF
cat > "$hostile_zdotdir/.zshenv" <<'EOF'
: > "$HOSTILE_ZDOTDIR_MARKER"
EOF
chmod +x "$hostile_shell_dir/zsh"

set +e
direct_output=$(PATH="$hostile_shell_dir:/usr/bin:/bin" \
  ZDOTDIR="$empty_zdotdir" \
  HOSTILE_SHELL_MARKER="$hostile_shell_marker" \
  "$launcher" 2>&1)
direct_status=$?
set -e
(( direct_status == 1 )) || fail 'direct launcher execution must use the fixed system zsh'
[[ $direct_output == 'secret-exec: usage: secret-exec <profile> -- <command> [args...] | secret-exec aws-credential-process <profile>' ]] || \
  fail 'direct launcher execution must preserve the usage failure'
[[ ! -e $hostile_shell_marker ]] || fail 'direct launcher execution must ignore PATH-selected zsh'

set +e
direct_output=$(PATH="/usr/bin:/bin" \
  ZDOTDIR="$hostile_zdotdir" \
  HOSTILE_ZDOTDIR_MARKER="$hostile_zdotdir_marker" \
  "$launcher" 2>&1)
direct_status=$?
set -e
(( direct_status == 1 )) || fail 'direct launcher execution must disable zsh startup files'
[[ $direct_output == 'secret-exec: usage: secret-exec <profile> -- <command> [args...] | secret-exec aws-credential-process <profile>' ]] || \
  fail 'direct launcher execution with hostile ZDOTDIR must preserve the usage failure'
[[ ! -e $hostile_zdotdir_marker ]] || fail 'direct launcher execution must ignore ZDOTDIR'

fast_exit=
for fast_exit_candidate in /usr/bin/true /bin/true; do
  if [[ -x $fast_exit_candidate ]]; then
    fast_exit=$fast_exit_candidate
    break
  fi
done
[[ -n $fast_exit ]] || fail 'a fixed true executable is required'
fast_home=$test_dir/fast-home
fast_profile_dir=$fast_home/.config/secret-exec/profiles
fast_local_bin=$fast_home/.local/bin
fast_target_bin=$test_dir/fast-target-bin
mkdir -p -- "$fast_profile_dir" "$fast_local_bin" "$fast_target_bin"
chmod 700 "$fast_home/.config/secret-exec" "$fast_profile_dir"
cp -- "$launcher_source" "$fast_local_bin/secret-exec"
cp -- "$fast_exit" "$fast_local_bin/proton-pass-ensure-ready"
cat > "$fast_local_bin/readiness-fd-audit" <<'EOF'
#!/bin/zsh -f
if [[ -n ${FD_AUDIT_TARGET:-} ]]; then
  integer matching_fds=0
  for descriptor in /proc/$$/fd/<->(N); do
    [[ $(/usr/bin/readlink -- $descriptor) == $FD_AUDIT_TARGET ]] &&
      (( ++matching_fds ))
  done
  print -r -- "readiness:$matching_fds" >>$FD_AUDIT_LOG
  (( matching_fds == 0 )) || exit 96
fi
EOF
cat > "$fast_local_bin/pass-cli" <<'EOF'
#!/bin/zsh -f
set -euo pipefail
[[ -z ${PROVIDER_START_MARKER:-} ]] ||
  print -r -- provider-started >>"$PROVIDER_START_MARKER"
[[ -z ${PROVIDER_COMPLETION_DELAY:-} ]] || /bin/sleep 0.2
if [[ -n ${FD_AUDIT_TARGET:-} ]]; then
  integer matching_fds=0
  for descriptor in /proc/$$/fd/<->(N); do
    [[ $(/usr/bin/readlink -- $descriptor) == $FD_AUDIT_TARGET ]] &&
      (( ++matching_fds ))
  done
  print -r -- "provider:$matching_fds" >>$FD_AUDIT_LOG
  # stderr and the bounded wrapper's diagnostics descriptor are intentional.
  (( matching_fds == 2 )) || exit 97
fi
print -r -- 'fast-provider-canary'
[[ -z ${PROVIDER_COMPLETION_MARKER:-} ]] ||
  print -r -- provider-completed >>"$PROVIDER_COMPLETION_MARKER"
EOF
cat > "$fast_target_bin/check-fast-provider" <<'EOF'
#!/bin/zsh -f
if [[ -n ${FD_AUDIT_TARGET:-} ]]; then
  integer matching_fds=0
  for descriptor in /proc/$$/fd/<->(N); do
    [[ $(/usr/bin/readlink -- $descriptor) == $FD_AUDIT_TARGET ]] &&
      (( ++matching_fds ))
  done
  print -r -- "consumer:$matching_fds" >>$FD_AUDIT_LOG
  (( matching_fds == 1 )) || exit 98
fi
[[ ${FAST_PROVIDER_VALUE:-} == fast-provider-canary ]]
EOF
chmod 700 \
  "$fast_local_bin/secret-exec" \
  "$fast_local_bin/readiness-fd-audit" \
  "$fast_local_bin/proton-pass-ensure-ready" \
  "$fast_local_bin/pass-cli" \
  "$fast_target_bin/check-fast-provider"
print -r -- \
  'FAST_PROVIDER_VALUE=pass://cli-secrets/fast-provider/password' > \
  "$fast_profile_dir/fast-provider.env"
chmod 600 "$fast_profile_dir/fast-provider.env"
fd_audit_target=$test_dir/escape-fd-audit.err
fd_audit_log=$test_dir/escape-fd-audit.log
typeset -a fd_audit_environment=(
  HOME=$fast_home
  XDG_CONFIG_HOME=$fast_home/.config
  PATH=$fast_local_bin:$fast_target_bin:/usr/bin:/bin
)
integer fd_audit_enabled=0
if [[ $OSTYPE == linux* && -d /proc/$$/fd ]]; then
  fd_audit_enabled=1
  cp -- "$fast_local_bin/readiness-fd-audit" \
    "$fast_local_bin/proton-pass-ensure-ready"
  fd_audit_environment+=(
    FD_AUDIT_TARGET=$fd_audit_target
    FD_AUDIT_LOG=$fd_audit_log
  )
fi
set +e
/usr/bin/env "${fd_audit_environment[@]}" \
  "$fast_local_bin/secret-exec" fast-provider -- check-fast-provider \
  2>"$fd_audit_target"
fd_audit_status=$?
set -e
(( fd_audit_status == 0 )) ||
  fail "provider and final consumer scenario must succeed: status=$fd_audit_status error=$(<"$fd_audit_target")"
if (( fd_audit_enabled )); then
  [[ $(<"$fd_audit_log") == $'readiness:0\nprovider:2\nconsumer:1' ]] ||
    fail 'provider and final consumer must not inherit the escape diagnostic descriptor'
  cp -- "$fast_exit" "$fast_local_bin/proton-pass-ensure-ready"
fi

empty_path_output=$(
  cd "$test_dir"
  HOME=$fast_home XDG_CONFIG_HOME=$fast_home/.config \
    PATH=:$fast_local_bin:$fast_target_bin:/usr/bin:/bin \
    "$fast_local_bin/secret-exec" fast-provider -- check-fast-provider
)
[[ -z $empty_path_output ]] ||
  fail 'an empty PATH component without pass-cli must preserve later provider lookup'

relative_pass_cwd=$test_dir/relative-pass-cli-cwd
relative_pass_bin=$relative_pass_cwd/relative-bin
mkdir -p -- "$relative_pass_cwd" "$relative_pass_bin"
cp -- "$fast_local_bin/pass-cli" "$relative_pass_cwd/pass-cli"
cp -- "$fast_local_bin/pass-cli" "$relative_pass_bin/pass-cli"
for relative_pass_prefix in '' . relative-bin; do
  relative_pass_output=$(
    cd "$relative_pass_cwd"
    HOME=$fast_home XDG_CONFIG_HOME=$fast_home/.config \
      PATH=$relative_pass_prefix:$fast_target_bin:/usr/bin:/bin \
      "$fast_local_bin/secret-exec" fast-provider -- check-fast-provider
  )
  [[ -z $relative_pass_output ]] ||
    fail 'secret-exec must preserve ordinary relative pass-cli PATH selections'
done

if [[ -n $status_fragment_library ]]; then
  typeset identity_loss_output identity_listing identity_controller
  integer identity_loss_status
  identity_loss_gate=$test_dir/zpty-initial-identity-loss.gate
  identity_loss_output_file=$test_dir/zpty-initial-identity-loss.out
  rm -f -- "$identity_loss_log" "$identity_loss_gate" "$identity_loss_output_file" "$kill_audit_log"
  /usr/bin/env LD_PRELOAD="$status_fragment_library:$kill_audit_library" \
    ZPTY_IDENTITY_LOSS_AUDIT_LOG=$identity_loss_log ZPTY_INITIAL_IDENTITY_LOSS_GATE=$identity_loss_gate \
    NEGATIVE_PGID_KILL_AUDIT_LOG=$kill_audit_log HOME=$fast_home \
    XDG_CONFIG_HOME=$fast_home/.config PATH=$fast_local_bin:$fast_target_bin:/usr/bin:/bin \
    ZPTY_INITIAL_IDENTITY_LOSS=1 "$fast_local_bin/secret-exec" \
    fast-provider -- check-fast-provider >"$identity_loss_output_file" 2>&1 &
  identity_wrapper_pid=$!
  test_process_fixture_track_pid $identity_wrapper_pid
  integer identity_marker_polls=100
  while (( identity_marker_polls-- > 0 )) && [[ ! -s $identity_loss_log ]]; do zselect -t 1 2>/dev/null || true; done
  [[ -s $identity_loss_log ]] || fail 'initial secret identity fixture must publish its controller'
  identity_loss_record=$(<"$identity_loss_log")
  typeset -a identity_lines=( "${(@f)identity_loss_record}" )
  identity_controller=${identity_lines[1]#controller:}
  [[ $identity_controller == <-> && $identity_controller -gt 1 ]] || fail 'initial secret identity fixture must publish a numeric controller'
  identity_listing=$(/bin/ps -o pid=,ppid=,pgid=,sid= -p $identity_controller)
  typeset -a identity_fields=( ${=identity_listing} )
  identity_ancestor=${identity_fields[2]}
  integer identity_ancestor_hops=8
  while (( identity_ancestor_hops-- > 0 )) &&
    [[ $identity_ancestor != $identity_wrapper_pid ]]; do
    identity_ancestor=$(/bin/ps -o ppid= -p $identity_ancestor)
    identity_ancestor=${identity_ancestor//[[:space:]]/}
    [[ $identity_ancestor == <-> && $identity_ancestor -gt 1 ]] || break
  done
  (( ${#identity_fields} == 4 && identity_fields[1] == identity_controller &&
    identity_ancestor == identity_wrapper_pid && identity_fields[3] == identity_controller &&
    identity_fields[4] == identity_controller )) || fail 'initial secret controller must belong to the wrapper lineage and lead its session'
  kill -KILL -- -$identity_controller
  : >"$identity_loss_gate"
  set +e
  wait $identity_wrapper_pid
  identity_loss_status=$?
  set -e
  test_process_fixture_untrack_pid $identity_wrapper_pid
  ! kill -0 -- -$identity_controller 2>/dev/null || fail 'initial secret controller group must become absent'
  identity_loss_output=$(<"$identity_loss_output_file")
  (( identity_loss_status == 1 )) || fail 'initial identity loss must fail secret resolution closed'
  [[ $identity_loss_output == $'secret-exec: cannot identify credential-resolution process group\nsecret-exec: failed to resolve FAST_PROVIDER_VALUE' ]] || fail 'initial identity loss must preserve its fixed resolution diagnostics'
  [[ $(<"$identity_loss_log") == $'controller:'$identity_controller$'\ninitial-identity-loss' ]] || fail 'initial secret identity fixture must prove pre-publication controller loss'
  [[ ! -s $kill_audit_log ]] || fail 'initial secret identity loss must not signal an absent process group'

  rm -f -- "$identity_loss_log" "$kill_audit_log"
  set +e
  identity_loss_output=$(/usr/bin/env LD_PRELOAD="$status_fragment_library:$kill_audit_library" \
    ZPTY_IDENTITY_LOSS_AUDIT_LOG=$identity_loss_log NEGATIVE_PGID_KILL_AUDIT_LOG=$kill_audit_log \
    HOME=$fast_home XDG_CONFIG_HOME=$fast_home/.config PATH=$fast_local_bin:$fast_target_bin:/usr/bin:/bin \
    ZPTY_POST_ACTIVE_IDENTITY_LOSS=1 "$fast_local_bin/secret-exec" fast-provider -- check-fast-provider 2>&1)
  identity_loss_status=$?
  set -e
  (( identity_loss_status == 1 )) || fail 'post-active identity loss must fail secret resolution closed'
  [[ $identity_loss_output == $'secret-exec: bounded credential resolution became unmanageable\nsecret-exec: failed to resolve FAST_PROVIDER_VALUE' ]] || fail 'post-active identity loss must preserve its fixed resolution diagnostics'
  [[ $(<"$identity_loss_log") == post-active-identity-loss ]] || fail 'post-active secret identity fixture must prove controller loss'
  [[ ! -s $kill_audit_log ]] || fail 'post-active secret identity loss must not signal an absent process group'

  provider_start_marker=$test_dir/transient-secret-provider-started
  provider_completion_marker=$test_dir/transient-secret-provider-completed
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
    HOME=$fast_home XDG_CONFIG_HOME=$fast_home/.config \
    PATH=$fast_local_bin:$fast_target_bin:/usr/bin:/bin \
    /usr/bin/setsid "$fast_local_bin/secret-exec" \
      fast-provider -- check-fast-provider \
      >/dev/null 2>"$test_dir/transient-secret-exec.err"
  transient_secret_exec_status=$?
  set -e
  (( transient_secret_exec_status == 0 )) ||
    fail "secret-exec must retry one transient live-group probe: status=$transient_secret_exec_status error=$(<"$test_dir/transient-secret-exec.err")"
  [[ $(<"$transient_liveness_log") == \
    $'start-gate\nlive-before-esrch\ninjected-esrch\nrecovered-live' ]] ||
    fail 'the secret-exec liveness fixture must prove one live ESRCH and recovery'
  [[ $(<"$provider_start_marker") == provider-started &&
    $(<"$provider_completion_marker") == provider-completed ]] ||
    fail 'secret-exec must complete exactly one provider after the transient probe'
  [[ ! -s $kill_audit_log ]] ||
    fail 'secret-exec transient-probe recovery must not signal a stale group'

  provider_completion_marker=$test_dir/fragmented-secret-provider-completed
  rm -f -- "$status_fragment_log" "$status_fragment_delay_log" \
    "$provider_completion_marker"
  set +e
  LD_PRELOAD=$status_fragment_library \
    ZPTY_STATUS_FRAGMENT_AUDIT_LOG=$status_fragment_log \
    ZPTY_STATUS_FRAGMENT_DELAY_TAIL=1 \
    ZPTY_STATUS_FRAGMENT_DELAY_AUDIT_LOG=$status_fragment_delay_log \
    PROVIDER_COMPLETION_MARKER=$provider_completion_marker \
    HOME=$fast_home XDG_CONFIG_HOME=$fast_home/.config \
    PATH=$fast_local_bin:$fast_target_bin:/usr/bin:/bin \
    /usr/bin/setsid "$fast_local_bin/secret-exec" \
      fast-provider -- check-fast-provider \
      >/dev/null 2>"$test_dir/fragmented-secret-exec.err"
  fragmented_secret_exec_status=$?
  set -e
  (( fragmented_secret_exec_status == 0 )) ||
    fail "secret-exec must accept a fragmented successful child-status record: status=$fragmented_secret_exec_status error=$(<"$test_dir/fragmented-secret-exec.err")"
  [[ $(<"$status_fragment_log") == fragmented-status ]] ||
    fail 'the secret-exec PTY fixture must prove that it fragmented a record'
  [[ $(<"$provider_completion_marker") == provider-completed ]] ||
    fail 'the fragmented secret-exec fixture must prove one provider completion'
  [[ $(<"$status_fragment_delay_log") == \
    $'delay-armed\nforced-yields-complete\ndelayed-tail' ]] ||
    fail 'the secret-exec PTY fixture must prove the forced-yield and 160 ms status-tail delay'

  rm -f -- "$status_fragment_log" "$status_fragment_deadline_log"
  set +e
  deadline_output=$(
    LD_PRELOAD=$status_fragment_library \
      ZPTY_STATUS_FRAGMENT_AUDIT_LOG=$status_fragment_log \
      ZPTY_STATUS_FRAGMENT_EXPIRE_DEADLINE=1 \
      ZPTY_STATUS_FRAGMENT_DEADLINE_AUDIT_LOG=$status_fragment_deadline_log \
      HOME=$fast_home XDG_CONFIG_HOME=$fast_home/.config \
      PATH=$fast_local_bin:$fast_target_bin:/usr/bin:/bin \
      "$fast_local_bin/secret-exec" fast-provider -- check-fast-provider 2>&1
  )
  deadline_status=$?
  set -e
  (( deadline_status == 1 )) ||
    fail "a fragmented tail must not extend credential resolution beyond its deadline: status=$deadline_status audit=$(<"$status_fragment_deadline_log")"
  [[ $deadline_output == \
    'secret-exec: timed out resolving FAST_PROVIDER_VALUE' ]] ||
    fail 'an expired fragmented status must preserve the value-free timeout error'
  [[ $(<"$status_fragment_log") == fragmented-status ]] ||
    fail 'the deadline fixture must prove that it fragmented a status record'
  [[ $(<"$status_fragment_deadline_log") == \
    $'deadline-armed\ndeadline-expired' ]] ||
    fail 'the fragmented status tail must not be read after the operation deadline'

  rm -f -- "$status_fragment_log" "$kill_audit_log"
  zmodload zsh/zselect || fail 'the secret-exec signal fixture requires zsh/zselect'
  set +e
  LD_PRELOAD="$status_fragment_library:$kill_audit_library" \
    ZPTY_STATUS_FRAGMENT_AUDIT_LOG=$status_fragment_log \
    ZPTY_STATUS_FRAGMENT_PAUSE=1 \
    NEGATIVE_PGID_KILL_AUDIT_LOG=$kill_audit_log \
    HOME=$fast_home XDG_CONFIG_HOME=$fast_home/.config \
    PATH=$fast_local_bin:$fast_target_bin:/usr/bin:/bin \
    /usr/bin/setsid "$fast_local_bin/secret-exec" \
      fast-provider -- check-fast-provider \
      >"$test_dir/fragment-signal.out" \
      2>"$test_dir/fragment-signal.err" &
  fragmented_secret_exec_pid=$!
  test_process_fixture_track_pid $fragmented_secret_exec_pid
  integer fragment_marker_polls=100
  while (( fragment_marker_polls-- > 0 )) && [[ ! -s $status_fragment_log ]]; do
    zselect -t 1 2>/dev/null || true
  done
  if [[ ! -s $status_fragment_log ]]; then
    kill -KILL -- -$fragmented_secret_exec_pid 2>/dev/null || true
    wait $fragmented_secret_exec_pid 2>/dev/null || true
    test_process_fixture_untrack_pid $fragmented_secret_exec_pid
    set -e
    fail 'secret-exec must reach the fragmented post-exit status window'
  fi
  kill -TERM -- -$fragmented_secret_exec_pid 2>/dev/null || true
  wait $fragmented_secret_exec_pid
  fragmented_signal_status=$?
  test_process_fixture_untrack_pid $fragmented_secret_exec_pid
  set -e
  (( fragmented_signal_status == 143 )) ||
    fail 'TERM during secret-exec status parsing must retain status 143'
  [[ $(<"$status_fragment_log") == fragmented-status ]] ||
    fail 'the secret-exec signal fixture must prove that it fragmented a record'
  [[ ! -s $kill_audit_log ]] ||
    fail 'secret-exec status parsing must not signal an absent process group'
fi

integer fast_provider_run
for (( fast_provider_run = 1; fast_provider_run <= 32; ++fast_provider_run )); do
  HOME=$fast_home XDG_CONFIG_HOME=$fast_home/.config \
    PATH=$fast_local_bin:$fast_target_bin:/usr/bin:/bin \
    "$fast_local_bin/secret-exec" fast-provider -- check-fast-provider ||
    fail 'the launcher must accept an immediately successful provider child'
done

context7_field=CONTEXT7
context7_field+=_API_KEY
firecrawl_field=FIRECRAWL
firecrawl_field+=_API_KEY
aws_access_field=AWS_ACCESS_KEY
aws_access_field+=_ID
aws_secret_field=AWS_SECRET_ACCESS
aws_secret_field+=_KEY
aws_session_field=AWS_SESSION
aws_session_field+=_TOKEN
github_field=GITHUB_PERSONAL_ACCESS
github_field+=_TOKEN
greptile_field=GREPTILE
greptile_field+=_API_KEY

cat > "$profile_dir/context7.env" <<'EOF'
CONTEXT7_API_KEY=pass://cli-secrets/context7/password
EOF
cat > "$profile_dir/firecrawl.env" <<'EOF'
FIRECRAWL_API_KEY=pass://cli-secrets/firecrawl/password
EOF
cat > "$profile_dir/github.env" <<'EOF'
GITHUB_PERSONAL_ACCESS_TOKEN=pass://cli-secrets/github-mcp/password
EOF
cat > "$profile_dir/greptile.env" <<'EOF'
GREPTILE_API_KEY=pass://cli-secrets/greptile/password
EOF
cat > "$profile_dir/aws.env" <<'EOF'
AWS_ACCESS_KEY_ID=pass://cli-secrets/aws/username
AWS_SECRET_ACCESS_KEY=pass://cli-secrets/aws/password
!AWS_SESSION_TOKEN
EOF
print -r -- "$proton_bootstrap_field=secret-service://" > \
  "$profile_dir/proton-session.env"
chmod 600 "$profile_dir"/*.env

homebrew_prefix=$test_dir/homebrew
homebrew_cellar_bin=$homebrew_prefix/Cellar/proton-pass-cli/2.3.2/bin
mkdir -p -- "$homebrew_prefix/bin" "$homebrew_cellar_bin"
cat > "$homebrew_cellar_bin/pass-cli" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

fixture_token=pst_
fixture_token+='fixture-token'
fixture_token+='::fixture-key'
bootstrap_field=PROTON_PASS_PERSONAL_ACCESS
bootstrap_field+=_TOKEN
record_stage() {
  print -r -- "$1" > "$FAKE_PASS_DIAGNOSTIC_LOG"
}
fail_stage() {
  record_stage "${1}:exit=${2}"
  exit "$2"
}
case $1 in
  info)
    record_stage 'info:start'
    (( $# == 1 )) || fail_stage info-argv 64
    [[ ${PROTON_PASS_NO_UPDATE_CHECK:-} == 1 ]] || fail_stage info-update-check 65
    [[ -z ${${(P)bootstrap_field}:-} ]] || fail_stage info-bootstrap-scrub 72
    print -r -- info >> "$FAKE_PASS_SESSION_LOG"
    print -r -- 'account-metadata-canary'
    if [[ -e $FAKE_PASS_SESSION ]]; then
      record_stage 'info:ready'
    else
      print -u2 -r -- 'Error: This operation requires an authenticated client'
      fail_stage info-session 1
    fi
    ;;
  login)
    record_stage 'login:start'
    print -r -- started >> "$FAKE_PASS_LOGIN_OUTCOME_LOG"
    if (( $# != 1 )); then
      print -r -- argv-failed >> "$FAKE_PASS_LOGIN_OUTCOME_LOG"
      fail_stage login-argv 66
    fi
    if [[ ${${(P)bootstrap_field}:-} != $fixture_token ]]; then
      print -r -- bootstrap-failed >> "$FAKE_PASS_LOGIN_OUTCOME_LOG"
      fail_stage login-bootstrap 67
    fi
    print -r -- login >> "$FAKE_PASS_SESSION_LOG"
    [[ ! -e $FAKE_PASS_LOGIN_DELAY ]] || /bin/sleep 0.2
    : > "$FAKE_PASS_SESSION"
    record_stage 'login:ready'
    print -r -- completed >> "$FAKE_PASS_LOGIN_OUTCOME_LOG"
    ;;
  item)
    record_stage 'item:start'
    [[ $2 == view && $3 == --output && $4 == human && $# == 5 ]] || fail_stage item-argv 68
    [[ -e $FAKE_PASS_SESSION ]] || fail_stage item-session 69
    [[ -z ${${(P)bootstrap_field}:-} ]] || fail_stage item-bootstrap-scrub 72
    [[ ${PROTON_PASS_AGENT_REASON:-} == 'secret-exec credential resolution' ]] || fail_stage item-reason 73
    [[ ${PROTON_PASS_NO_UPDATE_CHECK:-} == 1 ]] || fail_stage item-update-check 74
    case $(/usr/bin/uname -s) in
      Linux) [[ ${PROTON_PASS_LINUX_KEYRING:-} == dbus ]] || fail_stage item-keyring 75 ;;
      Darwin) [[ -z ${PROTON_PASS_LINUX_KEYRING:-} ]] || fail_stage item-keyring 75 ;;
      *) fail_stage item-platform 76 ;;
    esac
    record_stage 'item:ready'
    print -r -- "$5" >> "$FAKE_PASS_LOG"
    [[ ! -e $FAKE_PASS_ITEM_EXIT_124 ]] || exit 124
    if [[ -e $FAKE_PASS_ITEM_DESCENDANT ]]; then
      print -r -- 'context7-canary'
      (
        zmodload zsh/system
        zmodload zsh/zselect
        trap '' HUP TERM
        print -r -- "$sysparams[pid]" > "$FAKE_RESOLUTION_CHILD_PID"
        while true; do
          zselect -t 10 || true
        done
      ) &!
      zmodload zsh/zselect
      while [[ ! -s $FAKE_RESOLUTION_CHILD_PID ]]; do
        zselect -t 1 || true
      done
      exit 0
    fi
    case $5 in
      pass://cli-secrets/context7/password) print -r -- 'context7-canary' ;;
      pass://cli-secrets/firecrawl/password) print -r -- 'firecrawl-canary' ;;
      pass://cli-secrets/github-mcp/password) print -r -- 'github-canary' ;;
      pass://cli-secrets/greptile/password) print -r -- 'greptile-canary' ;;
      pass://cli-secrets/aws/username) print -r -- "${FAKE_AWS_ACCESS_KEY_ID:-AKIACANARY123}" ;;
      pass://cli-secrets/aws/password) print -r -- "${FAKE_AWS_SECRET_ACCESS_KEY:-AwsSecretCanary123+/=}" ;;
      *) exit 70 ;;
    esac
    ;;
  *)
    fail_stage command 71
    ;;
esac
EOF
chmod +x "$homebrew_cellar_bin/pass-cli"
ln -s ../Cellar/proton-pass-cli/2.3.2/bin/pass-cli \
  "$homebrew_prefix/bin/pass-cli"

cat > "$native_store_adapter" <<'EOF'
#!/bin/zsh -f
set -euo pipefail

print -r -- "$*" >> "$FAKE_SECRET_TOOL_LOG"
bootstrap_field=PROTON_PASS_PERSONAL_ACCESS
bootstrap_field+=_TOKEN
unset "$bootstrap_field" 2>/dev/null || true
case $* in
  proton-bootstrap)
    [[ ! -e $FAKE_NATIVE_STORE_LOCKED ]] || exit 69
    fixture_token=pst_
    fixture_token+='fixture-token'
    fixture_token+='::fixture-key'
    print -r -- "$fixture_token"
    ;;
  'lookup member-local SITE_PASSWORD')
    if [[ -e $FAKE_SECRET_LOOKUP_HANG ]]; then
      zmodload zsh/system
      zmodload zsh/zselect
      trap '' HUP TERM
      print -r -- "$sysparams[pid]" > "$FAKE_RESOLUTION_CHILD_PID"
      while true; do
        zselect -t 10 || true
      done
    fi
    print -r -- 'site-canary'
    ;;
  *)
    exit 66
    ;;
esac
EOF
chmod +x "$native_store_adapter"

cat > "$fake_bin/check-context" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

[[ ${CONTEXT7_API_KEY:-} == context7-canary ]] || exit 70
[[ -z ${FIRECRAWL_API_KEY:-} ]] || exit 71
[[ -z ${AWS_ACCESS_KEY_ID:-} ]] || exit 72
[[ -z ${AWS_SECRET_ACCESS_KEY:-} ]] || exit 75
[[ -z ${AWS_SESSION_TOKEN:-} ]] || exit 76
[[ -z ${GITHUB_PERSONAL_ACCESS_TOKEN:-} ]] || exit 77
[[ -z ${GREPTILE_API_KEY:-} ]] || exit 78
bootstrap_field=PROTON_PASS_PERSONAL_ACCESS
bootstrap_field+=_TOKEN
[[ -z ${${(P)bootstrap_field}:-} ]] || exit 79
[[ ${ORDINARY_SETTING:-} == preserved ]] || exit 73
[[ $1 == 'argument with spaces' ]] || exit 74
print -r -- 'target-ok'
EOF
chmod +x "$fake_bin/check-context"

cat > "$fake_bin/check-selected" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

case $1 in
  context7)
    [[ $CONTEXT7_API_KEY == context7-canary && -z ${FIRECRAWL_API_KEY:-} &&
      -z ${GITHUB_PERSONAL_ACCESS_TOKEN:-} && -z ${GREPTILE_API_KEY:-} &&
      -z ${AWS_ACCESS_KEY_ID:-} && -z ${AWS_SECRET_ACCESS_KEY:-} && -z ${AWS_SESSION_TOKEN:-} ]]
    ;;
  firecrawl)
    [[ $FIRECRAWL_API_KEY == firecrawl-canary && -z ${CONTEXT7_API_KEY:-} &&
      -z ${GITHUB_PERSONAL_ACCESS_TOKEN:-} && -z ${GREPTILE_API_KEY:-} &&
      -z ${AWS_ACCESS_KEY_ID:-} && -z ${AWS_SECRET_ACCESS_KEY:-} && -z ${AWS_SESSION_TOKEN:-} ]]
    ;;
  github)
    [[ $GITHUB_PERSONAL_ACCESS_TOKEN == github-canary && -z ${CONTEXT7_API_KEY:-} &&
      -z ${FIRECRAWL_API_KEY:-} && -z ${GREPTILE_API_KEY:-} &&
      -z ${AWS_ACCESS_KEY_ID:-} && -z ${AWS_SECRET_ACCESS_KEY:-} && -z ${AWS_SESSION_TOKEN:-} ]]
    ;;
  greptile)
    [[ $GREPTILE_API_KEY == greptile-canary && -z ${CONTEXT7_API_KEY:-} &&
      -z ${FIRECRAWL_API_KEY:-} && -z ${GITHUB_PERSONAL_ACCESS_TOKEN:-} &&
      -z ${AWS_ACCESS_KEY_ID:-} && -z ${AWS_SECRET_ACCESS_KEY:-} && -z ${AWS_SESSION_TOKEN:-} ]]
    ;;
  aws)
    [[ $AWS_ACCESS_KEY_ID == AKIACANARY123 && $AWS_SECRET_ACCESS_KEY == AwsSecretCanary123+/= &&
      -z ${AWS_SESSION_TOKEN:-} && -z ${CONTEXT7_API_KEY:-} && -z ${FIRECRAWL_API_KEY:-} &&
      -z ${GITHUB_PERSONAL_ACCESS_TOKEN:-} && -z ${GREPTILE_API_KEY:-} ]]
    ;;
  *) exit 79 ;;
esac
EOF
chmod +x "$fake_bin/check-selected"

cat > "$fake_bin/exit-37" <<'EOF'
#!/usr/bin/env zsh
exit 37
EOF
chmod +x "$fake_bin/exit-37"

cat > "$fake_bin/mark-target" <<'EOF'
#!/usr/bin/env zsh
: > "$TARGET_MARKER"
EOF
chmod +x "$fake_bin/mark-target"

export HOME=$fixture_home
export XDG_CONFIG_HOME=$fixture_home/.config
export XDG_STATE_HOME=$test_dir/state
export PATH=$homebrew_prefix/bin:$fake_bin:/usr/bin:/bin
export FAKE_PASS_LOG=$test_dir/pass-requests.log
export FAKE_PASS_SESSION=$test_dir/provider-session
export FAKE_PASS_SESSION_LOG=$test_dir/provider-session.log
export FAKE_PASS_DIAGNOSTIC_LOG=$test_dir/provider-diagnostics.log
export FAKE_PASS_LOGIN_OUTCOME_LOG=$test_dir/provider-login-outcomes.log
export FAKE_PASS_LOGIN_DELAY=$test_dir/provider-login-delay
export FAKE_SECRET_TOOL_LOG=$test_dir/secret-tool-requests.log
export FAKE_NATIVE_STORE_LOCKED=$test_dir/native-store-locked
export FAKE_PASS_ITEM_DESCENDANT=$test_dir/pass-item-descendant
export FAKE_PASS_ITEM_EXIT_124=$test_dir/pass-item-exit-124
export FAKE_SECRET_LOOKUP_HANG=$test_dir/secret-lookup-hang
export FAKE_RESOLUTION_CHILD_PID=$test_dir/resolution-child.pid
export HOSTILE_UNAME_MARKER=$test_dir/hostile-uname-ran
export ORDINARY_SETTING=preserved
login_outcome_precedence_probe=$test_dir/provider-login-outcome-precedence.log
print -r -- completed > "$login_outcome_precedence_probe"
print -r -- started >> "$login_outcome_precedence_probe"
[[ $(classify_login_outcome "$login_outcome_precedence_probe") == completed ]] ||
  fail 'a later login start must not mask an earlier completed login'
rm -f -- "$login_outcome_precedence_probe"
export "$context7_field=inherited-context7-canary"
export "$firecrawl_field=inherited-firecrawl-canary"
export "$aws_access_field=INHERITEDACCESS"
export "$aws_secret_field=InheritedSecret"
export "$aws_session_field=InheritedSession"
export "$github_field=inherited-github-canary"
export "$greptile_field=inherited-greptile-canary"
export "$proton_bootstrap_field=inherited-proton-bootstrap-canary"
: > "$FAKE_PASS_SESSION"

cat > "$fake_bin/uname" <<'EOF'
#!/usr/bin/env zsh
: > "$HOSTILE_UNAME_MARKER"
exit 90
EOF
chmod +x "$fake_bin/uname"
set +e
output=$(zsh "$launcher" context7 -- check-context 'argument with spaces' 2>&1)
launcher_status=$?
set -e
if (( launcher_status != 0 )); then
  launcher_output_marker=unexpected
  case $output in
    '') launcher_output_marker=empty ;;
    *'provider session is unavailable'*) launcher_output_marker=provider-unavailable ;;
    *'failed to resolve '*) launcher_output_marker=resolution-failed ;;
    *'timed out resolving '*) launcher_output_marker=resolution-timeout ;;
  esac
  provider_diagnostic=none
  if [[ -s $FAKE_PASS_DIAGNOSTIC_LOG ]]; then
    provider_diagnostic=$(<"$FAKE_PASS_DIAGNOSTIC_LOG")
    case $provider_diagnostic in
      info:start|info:ready|info-argv:exit=64|info-update-check:exit=65|\
      info-bootstrap-scrub:exit=72|info-session:exit=1|login:start|login:ready|\
      login-argv:exit=66|login-bootstrap:exit=67|item:start|item:ready|\
      item-argv:exit=68|item-session:exit=69|item-bootstrap-scrub:exit=72|\
      item-reason:exit=73|item-update-check:exit=74|item-keyring:exit=75|\
      item-platform:exit=76|command:exit=71)
        ;;
      *) provider_diagnostic=invalid ;;
    esac
  fi
  fail "launcher failed before the PATH-selected platform probe check: status=$launcher_status output=$launcher_output_marker provider=$provider_diagnostic"
fi
[[ ! -e $HOSTILE_UNAME_MARKER ]] ||
  fail 'the launcher must ignore a PATH-selected platform probe'
[[ $output == target-ok ]] || fail 'selected profile must reach the target with argv preserved'
[[ $(<"$FAKE_PASS_LOG") == pass://cli-secrets/context7/password ]] || \
  fail 'the launcher must retrieve only the selected profile'

export TARGET_MARKER=$test_dir/target-ran
rm -f -- "$TARGET_MARKER"
: > "$FAKE_PASS_ITEM_EXIT_124"
set +e
item_exit_124_output=$(zsh "$launcher" context7 -- mark-target 2>&1)
item_exit_124_status=$?
set -e
rm -f -- "$FAKE_PASS_ITEM_EXIT_124"
(( item_exit_124_status != 0 )) ||
  fail 'a provider-reported status 124 must fail resolution'
[[ $item_exit_124_output == 'secret-exec: failed to resolve CONTEXT7_API_KEY' ]] ||
  fail 'a provider-reported status 124 must not be mislabeled as a timeout'
[[ ! -e $TARGET_MARKER ]] ||
  fail 'a provider-reported status 124 must not start the consumer'

rm -f -- "$TARGET_MARKER" "$FAKE_RESOLUTION_CHILD_PID"
: > "$FAKE_PASS_ITEM_DESCENDANT"
test_process_fixture_track_pid_file "$FAKE_RESOLUTION_CHILD_PID"
zmodload zsh/datetime
zmodload zsh/zselect
typeset -F item_started=$EPOCHREALTIME
if [[ -n $kill_audit_library ]]; then
  LD_PRELOAD=$kill_audit_library \
    NEGATIVE_PGID_KILL_AUDIT_LOG=$kill_audit_log \
    "$launcher" context7 -- mark-target >"$test_dir/item-timeout.out" \
      2>"$test_dir/item-timeout.err" &
else
  "$launcher" context7 -- mark-target >"$test_dir/item-timeout.out" \
    2>"$test_dir/item-timeout.err" &
fi
item_launcher_pid=$!
test_process_fixture_track_pid $item_launcher_pid
typeset -F item_harness_deadline=$(( item_started + 4.0 ))
integer item_harness_expired=0
while kill -0 $item_launcher_pid 2>/dev/null; do
  if (( EPOCHREALTIME >= item_harness_deadline )); then
    item_harness_expired=1
    kill -TERM $item_launcher_pid 2>/dev/null || true
    zselect -t 10 || true
    kill -0 $item_launcher_pid 2>/dev/null && \
      kill -KILL $item_launcher_pid 2>/dev/null || true
    break
  fi
  zselect -t 1 || true
done
if wait $item_launcher_pid; then
  item_status=0
else
  item_status=$?
fi
test_process_fixture_untrack_pid $item_launcher_pid
typeset -F item_elapsed=$(( EPOCHREALTIME - item_started ))
item_output=$(<"$test_dir/item-timeout.err")
item_descendant_pid=$(<"$FAKE_RESOLUTION_CHILD_PID")
integer item_descendant_survived=0
if ! test_process_fixture_wait_for_pid_exit $item_descendant_pid; then
  item_descendant_survived=1
  kill -KILL $item_descendant_pid 2>/dev/null || true
  test_process_fixture_wait_for_pid_exit $item_descendant_pid 100 || true
fi
test_process_fixture_untrack_pid_file "$FAKE_RESOLUTION_CHILD_PID"
rm -f -- "$FAKE_PASS_ITEM_DESCENDANT"
(( ! item_harness_expired && item_status != 0 && item_elapsed < 4.0 )) ||
  fail 'pass item resolution must fail within its production deadline'
[[ $item_output == 'secret-exec: timed out resolving CONTEXT7_API_KEY' ]] ||
  fail 'a pass item timeout must produce one value-free error'
[[ ! -e $TARGET_MARKER ]] ||
  fail 'a timed-out pass item resolution must not start the consumer'
(( ! item_descendant_survived )) ||
  fail 'a timed-out pass item process group must leave no surviving descendant'
[[ ! -s $kill_audit_log ]] ||
  fail "secret resolution cleanup must never signal a numeric process group after observing it absent: $(<$kill_audit_log)"

mv "$profile_dir/proton-session.env" "$test_dir/proton-session.env"
output=$(zsh "$launcher" context7 -- check-context 'argument with spaces')
[[ $output == target-ok ]] ||
  fail 'a missing proton-session profile must not preserve an inherited bootstrap token'
mv "$test_dir/proton-session.env" "$profile_dir/proton-session.env"

for profile in context7 firecrawl github greptile aws; do
  zsh "$launcher" "$profile" -- check-selected "$profile"
done

rm -f -- "$FAKE_PASS_SESSION"
: > "$FAKE_PASS_SESSION_LOG"
: > "$FAKE_PASS_LOGIN_OUTCOME_LOG"
: > "$FAKE_SECRET_TOOL_LOG"
status_file=$XDG_STATE_HOME/secret-exec/proton-pass-readiness.status
set +e
output=$(zsh "$launcher" context7 -- check-context 'argument with spaces')
lazy_repair_status=$?
set -e
if (( lazy_repair_status != 0 )); then
  repair_stage=lock
  repair_reason=unrecorded
  if [[ -s $FAKE_SECRET_TOOL_LOG &&
    $(<"$FAKE_SECRET_TOOL_LOG") == proton-bootstrap ]]; then
    repair_stage=native-store
  fi
  if [[ -s $FAKE_PASS_DIAGNOSTIC_LOG ]]; then
    case $(<"$FAKE_PASS_DIAGNOSTIC_LOG") in
      login:*) repair_stage=login ;;
      info:ready) repair_stage=verify ;;
    esac
  fi
  if [[ -r $status_file ]]; then
    while IFS= read -r readiness_status_line || [[ -n $readiness_status_line ]]; do
      case $readiness_status_line in
        reason=unsafe-lock|reason=lock-timeout|reason=concurrent-repair-failed|\
        reason=native-store-timeout|\
        reason=native-store-unavailable|reason=invalid-bootstrap-value|\
        reason=login-timeout|reason=login-failed|reason=verify-timeout|\
        reason=verify-failed)
          repair_reason=${readiness_status_line#reason=}
          ;;
      esac
    done < "$status_file"
  fi
  case $repair_reason in
    unsafe-lock|lock-timeout|concurrent-repair-failed) repair_stage=lock ;;
    native-store-*|invalid-bootstrap-value) repair_stage=native-store ;;
    login-*) repair_stage=login ;;
    verify-*) repair_stage=verify ;;
  esac
  fail "lazy provider repair failed: status=$lazy_repair_status stage=$repair_stage reason=$repair_reason"
fi
[[ $output == target-ok ]] ||
  fail 'the first pass-backed consumer after session loss must recover and run'
[[ $(grep -Fxc login "$FAKE_PASS_SESSION_LOG") == 1 ]] ||
  fail 'lazy consumer recovery must perform one argument-free login'
grep -Fqx 'proton-bootstrap' "$FAKE_SECRET_TOOL_LOG" ||
  fail 'lazy recovery must use the fixed native bootstrap item'

export TARGET_MARKER=$test_dir/target-ran
rm -f -- "$FAKE_PASS_SESSION" "$TARGET_MARKER"
: > "$FAKE_NATIVE_STORE_LOCKED"
set +e
locked_output=$(zsh "$launcher" context7 -- mark-target 2>&1)
locked_status=$?
set -e
(( locked_status != 0 )) ||
  fail 'a pass-backed consumer must fail when the native store is locked'
[[ ! -e $TARGET_MARKER ]] ||
  fail 'a locked native store must not start the selected consumer'
[[ $locked_output ==
  'secret-exec: the Proton Pass provider session is unavailable; unlock the native credential store and retry' ]] ||
  fail 'a locked native store must produce one fixed actionable consumer error'
grep -Fqx 'state=unavailable' "$status_file" ||
  fail 'a locked native store must leave value-free unavailable status'
grep -Fqx 'reason=native-store-unavailable' "$status_file" ||
  fail 'a locked native store must record its value-free reason'
rm -f -- "$FAKE_NATIVE_STORE_LOCKED"

: > "$FAKE_PASS_SESSION_LOG"
: > "$FAKE_PASS_LOGIN_OUTCOME_LOG"
: > "$FAKE_PASS_LOGIN_DELAY"
typeset -a consumer_pids
typeset -A consumer_profiles
for profile in context7 firecrawl github greptile aws; do
  zsh "$launcher" "$profile" -- check-selected "$profile" \
    >"$test_dir/concurrent-$profile.out" \
    2>"$test_dir/concurrent-$profile.err" &
  consumer_pid=$!
  consumer_pids+=($consumer_pid)
  consumer_profiles[$consumer_pid]=$profile
  test_process_fixture_track_pid $consumer_pid
done
for consumer_pid in $consumer_pids; do
  if wait $consumer_pid; then
    test_process_fixture_untrack_pid $consumer_pid
  else
    test_process_fixture_untrack_pid $consumer_pid
    concurrent_profile=${consumer_profiles[$consumer_pid]:-unknown}
    case $concurrent_profile in
      context7|firecrawl|github|greptile|aws) ;;
      *) concurrent_profile=unknown ;;
    esac
    concurrent_error_file=$test_dir/concurrent-$concurrent_profile.err
    concurrent_error_marker=empty
    if [[ -s $concurrent_error_file ]]; then
      concurrent_error_marker=unexpected
      case $(<"$concurrent_error_file") in
        'secret-exec: the Proton Pass provider session is unavailable; unlock the native credential store and retry')
          concurrent_error_marker=provider-unavailable
          ;;
        'secret-exec: timed out resolving CONTEXT7_API_KEY'|\
        'secret-exec: timed out resolving FIRECRAWL_API_KEY'|\
        'secret-exec: timed out resolving GITHUB_PERSONAL_ACCESS_TOKEN'|\
        'secret-exec: timed out resolving GREPTILE_API_KEY'|\
        'secret-exec: timed out resolving AWS_ACCESS_KEY_ID'|\
        'secret-exec: timed out resolving AWS_SECRET_ACCESS_KEY')
          concurrent_error_marker=resolution-timeout
          ;;
      esac
    fi
    typeset -a concurrent_readiness_classification=(
      "${(@f)$(classify_latest_readiness_status "$status_file")}"
    )
    concurrent_readiness_reason=${concurrent_readiness_classification[1]:-unrecorded}
    concurrent_waiter_stage=${concurrent_readiness_classification[2]:-unrecorded}
    concurrent_login_outcome=$(
      classify_login_outcome "$FAKE_PASS_LOGIN_OUTCOME_LOG"
    )
    fail "concurrent pass-backed consumer launch failed: profile=$concurrent_profile stderr=$concurrent_error_marker latest-readiness=$concurrent_readiness_reason login=$concurrent_login_outcome latest-waiter-stage=$concurrent_waiter_stage"
  fi
done
rm -f -- "$FAKE_PASS_LOGIN_DELAY"
[[ $(grep -Fxc login "$FAKE_PASS_SESSION_LOG") == 1 ]] ||
  fail 'concurrent pass-backed consumers must perform one serialized repair login'
! grep -F 'account-metadata-canary' "$test_dir"/*.out "$test_dir"/*.err >/dev/null ||
  fail 'consumer recovery must suppress provider account metadata'

cat > "$profile_dir/member-local.env" <<'EOF'
SITE_PASSWORD=secret-service://
EOF
chmod 600 "$profile_dir"/*.env
cat > "$fake_bin/check-secret-service" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

[[ ${SITE_PASSWORD:-} == site-canary ]] || exit 80
[[ -z ${CONTEXT7_API_KEY:-} ]] || exit 81
[[ -z ${FIRECRAWL_API_KEY:-} ]] || exit 82
[[ -z ${GITHUB_PERSONAL_ACCESS_TOKEN:-} ]] || exit 83
[[ -z ${GREPTILE_API_KEY:-} ]] || exit 84
[[ -z ${AWS_ACCESS_KEY_ID:-} ]] || exit 85
[[ -z ${AWS_SECRET_ACCESS_KEY:-} ]] || exit 86
print -r -- 'secret-service-ok'
EOF
chmod +x "$fake_bin/check-secret-service"

: > "$FAKE_SECRET_TOOL_LOG"
hostile_dir=$test_dir/hostile-cwd
mkdir -p -- "$hostile_dir"
original_directory=$PWD
hostile_secret_marker=$test_dir/hostile-secret-tool-ran
cat > "$hostile_dir/secret-tool" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

: > "$HOSTILE_SECRET_TOOL_MARKER"
exit 90
EOF
chmod +x "$hostile_dir/secret-tool"
export HOSTILE_SECRET_TOOL_MARKER=$hostile_secret_marker
cd "$hostile_dir"
output=$(PATH=:$fake_bin:/usr/bin:/bin zsh "$launcher" member-local -- \
  check-secret-service)
cd "$original_directory"
[[ $output == secret-service-ok ]] || fail 'Secret Service profile must reach the target'
[[ ! -e $hostile_secret_marker ]] ||
  fail 'the launcher must ignore a current-directory secret-tool selected by PATH'
[[ $(<"$FAKE_SECRET_TOOL_LOG") == \
  'lookup member-local SITE_PASSWORD' ]] || \
  fail 'Secret Service lookup must use the selected profile and variable attributes'

rm -f -- "$TARGET_MARKER" "$FAKE_RESOLUTION_CHILD_PID"
: > "$FAKE_SECRET_LOOKUP_HANG"
test_process_fixture_track_pid_file "$FAKE_RESOLUTION_CHILD_PID"
typeset -F lookup_started=$EPOCHREALTIME
"$launcher" member-local -- mark-target >"$test_dir/lookup-timeout.out" \
  2>"$test_dir/lookup-timeout.err" &
lookup_launcher_pid=$!
test_process_fixture_track_pid $lookup_launcher_pid
typeset -F lookup_harness_deadline=$(( lookup_started + 4.0 ))
integer lookup_harness_expired=0
while kill -0 $lookup_launcher_pid 2>/dev/null; do
  if (( EPOCHREALTIME >= lookup_harness_deadline )); then
    lookup_harness_expired=1
    kill -TERM $lookup_launcher_pid 2>/dev/null || true
    zselect -t 10 || true
    kill -0 $lookup_launcher_pid 2>/dev/null && \
      kill -KILL $lookup_launcher_pid 2>/dev/null || true
    break
  fi
  zselect -t 1 || true
done
if wait $lookup_launcher_pid; then
  lookup_status=0
else
  lookup_status=$?
fi
test_process_fixture_untrack_pid $lookup_launcher_pid
typeset -F lookup_elapsed=$(( EPOCHREALTIME - lookup_started ))
lookup_output=$(<"$test_dir/lookup-timeout.err")
lookup_child_pid=$(<"$FAKE_RESOLUTION_CHILD_PID")
integer lookup_child_survived=0
if ! test_process_fixture_wait_for_pid_exit $lookup_child_pid; then
  lookup_child_survived=1
  kill -KILL $lookup_child_pid 2>/dev/null || true
  test_process_fixture_wait_for_pid_exit $lookup_child_pid 100 || true
fi
test_process_fixture_untrack_pid_file "$FAKE_RESOLUTION_CHILD_PID"
rm -f -- "$FAKE_SECRET_LOOKUP_HANG"
(( ! lookup_harness_expired && lookup_status != 0 && lookup_elapsed < 4.0 )) ||
  fail 'Secret Service resolution must fail within its production deadline'
[[ $lookup_output == 'secret-exec: timed out resolving SITE_PASSWORD' ]] ||
  fail 'a Secret Service timeout must produce one value-free error'
[[ ! -e $TARGET_MARKER ]] ||
  fail 'a timed-out Secret Service lookup must not start the consumer'
(( ! lookup_child_survived )) ||
  fail 'a timed-out Secret Service process group must leave no surviving child'

mv "$native_store_adapter" "$test_dir/native-store-adapter.real"
ln -s "$test_dir/native-store-adapter.real" "$native_store_adapter"
set +e
unsafe_adapter_output=$(zsh "$launcher" member-local -- mark-target 2>&1)
unsafe_adapter_status=$?
set -e
(( unsafe_adapter_status != 0 )) ||
  fail 'a symbolic-link native-store adapter must fail closed'
[[ $unsafe_adapter_output ==
  'secret-exec: a trusted native-store adapter is required' ]] ||
  fail 'a rejected native-store adapter must produce one value-free error'
rm -- "$native_store_adapter"
mv "$test_dir/native-store-adapter.real" "$native_store_adapter"

rm -f -- "$TARGET_MARKER"
set +e
zsh "$launcher" '*' -- mark-target > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'profile selection must treat glob characters literally'
[[ ! -e $TARGET_MARKER ]] || fail 'a glob-like profile must never run the target'

set +e
zsh "$launcher" context7 -- exit-37
exit_code=$?
set -e
(( exit_code == 37 )) || fail 'the launcher must preserve the target exit status'

mv "$profile_dir/context7.env" "$test_dir/context7.env"
export TARGET_MARKER=$test_dir/target-ran
assert_invalid_profiles 'a missing selected profile'
mv "$test_dir/context7.env" "$profile_dir/context7.env"

mv "$profile_dir/context7.env" "$test_dir/context7.env"
ln -s "$test_dir/context7.env" "$profile_dir/context7.env"
assert_invalid_profiles 'a symlinked canonical profile'
rm -- "$profile_dir/context7.env"
mv "$test_dir/context7.env" "$profile_dir/context7.env"

cp "$profile_dir/context7.env" "$test_dir/context7.env"
print -r -- 'CONTEXT7_API_KEY=pass://cli-secrets/context7/password' >> \
  "$profile_dir/context7.env"
assert_invalid_profiles 'a duplicate profile mapping'
mv "$test_dir/context7.env" "$profile_dir/context7.env"

cp "$profile_dir/context7.env" "$test_dir/context7.env"
print -r -- "$context7_field=file:///tmp/not-a-provider" > \
  "$profile_dir/context7.env"
assert_invalid_profiles 'an unsupported secret provider'
mv "$test_dir/context7.env" "$profile_dir/context7.env"

chmod 644 "$profile_dir/context7.env"
assert_invalid_profiles 'a group-readable profile'
chmod 600 "$profile_dir/context7.env"

trace_output=$(zsh -x "$launcher" context7 -- check-context 'argument with spaces' 2>&1)
[[ $trace_output != *context7-canary* ]] || fail 'xtrace must not expose a retrieved canary'

aws_json=$(zsh "$launcher" aws-credential-process aws)
aws_output_access_field=AccessKey
aws_output_access_field+=Id
aws_output_secret_field=SecretAccess
aws_output_secret_field+=Key
expected_aws_json='{"Version":1,"'${aws_output_access_field}'":"AKIACANARY123","'${aws_output_secret_field}'":"AwsSecretCanary123+/="}'
[[ $aws_json == "$expected_aws_json" ]] || \
  fail 'AWS credential-process output must match the external AWS contract'

export FAKE_AWS_ACCESS_KEY_ID='AKIA"bad'
set +e
malformed_output=$(zsh "$launcher" aws-credential-process aws 2>/dev/null)
exit_code=$?
set -e
unset FAKE_AWS_ACCESS_KEY_ID
(( exit_code != 0 )) || fail 'quote-bearing AWS access keys must fail closed'
[[ -z $malformed_output ]] || fail 'invalid AWS access keys must not emit credential JSON'

export FAKE_AWS_SECRET_ACCESS_KEY='AwsSecret"bad'
set +e
malformed_output=$(zsh "$launcher" aws-credential-process aws 2>/dev/null)
exit_code=$?
set -e
unset FAKE_AWS_SECRET_ACCESS_KEY
(( exit_code != 0 )) || fail 'quote-bearing AWS secret keys must fail closed'
[[ -z $malformed_output ]] || fail 'invalid AWS secret keys must not emit credential JSON'

python3 - "$launcher" <<'PYEOF'
import os
import pty
import sys

pid, fd = pty.fork()
if pid == 0:
    os.execv("/bin/zsh", ["zsh", sys.argv[1], "aws-credential-process", "aws"])
output = bytearray()
while True:
    try:
        chunk = os.read(fd, 4096)
    except OSError:
        break
    if not chunk:
        break
    output.extend(chunk)
_, status = os.waitpid(pid, 0)
assert not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0
assert b"AKIACANARY123" not in output
assert b"AwsSecretCanary123+/=" not in output
PYEOF

cp "$profile_dir/firecrawl.env" "$test_dir/firecrawl.env.bak"
cat > "$profile_dir/firecrawl.env" <<'EOF'
NOT AN ASSIGNMENT
EOF
set +e
zsh "$launcher" context7 -- check-context 'argument with spaces' > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'malformed profile mappings must fail closed'
mv "$test_dir/firecrawl.env.bak" "$profile_dir/firecrawl.env"

print -r -- 'secret-exec behavior checks passed'
