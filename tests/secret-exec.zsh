#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
launcher_source=$repo_root/home/private_dot_local/bin/executable_secret-exec
readiness_source=$repo_root/home/private_dot_local/bin/executable_proton-pass-ensure-ready

fail() {
  print -u2 -r -- "$1"
  return 1
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
test_process_fixture_run_signal_probe_mode
kill_audit_library=
kill_audit_log=$test_dir/negative-pgid-kill-audit.log
if [[ $OSTYPE == linux* ]]; then
  [[ -x /usr/bin/cc ]] || fail 'the Linux cleanup-identity test requires /usr/bin/cc'
  kill_audit_library=$test_dir/negative-pgid-kill-audit.so
  /usr/bin/cc -shared -fPIC -O2 -Wall -Wextra -Werror \
    -o "$kill_audit_library" \
    "$repo_root/tests/fixtures/negative-pgid-kill-audit.c" -ldl
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
cat > "$fast_local_bin/pass-cli" <<'EOF'
#!/bin/zsh -f
print -r -- 'fast-provider-canary'
EOF
cat > "$fast_target_bin/check-fast-provider" <<'EOF'
#!/bin/zsh -f
[[ ${FAST_PROVIDER_VALUE:-} == fast-provider-canary ]]
EOF
chmod 700 \
  "$fast_local_bin/secret-exec" \
  "$fast_local_bin/proton-pass-ensure-ready" \
  "$fast_local_bin/pass-cli" \
  "$fast_target_bin/check-fast-provider"
print -r -- \
  'FAST_PROVIDER_VALUE=pass://cli-secrets/fast-provider/password' > \
  "$fast_profile_dir/fast-provider.env"
chmod 600 "$fast_profile_dir/fast-provider.env"
integer fast_provider_run
for (( fast_provider_run = 1; fast_provider_run <= 32; ++fast_provider_run )); do
  HOME=$fast_home XDG_CONFIG_HOME=$fast_home/.config \
    PATH=$fast_target_bin:/usr/bin:/bin \
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

cat > "$fixture_local_bin/pass-cli" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

fixture_token=pst_
fixture_token+='fixture-token'
fixture_token+='::fixture-key'
bootstrap_field=PROTON_PASS_PERSONAL_ACCESS
bootstrap_field+=_TOKEN
case $1 in
  info)
    (( $# == 1 )) || exit 64
    [[ ${PROTON_PASS_NO_UPDATE_CHECK:-} == 1 ]] || exit 65
    [[ -z ${${(P)bootstrap_field}:-} ]] || exit 72
    print -r -- info >> "$FAKE_PASS_SESSION_LOG"
    print -r -- 'account-metadata-canary'
    [[ -e $FAKE_PASS_SESSION ]]
    ;;
  login)
    (( $# == 1 )) || exit 66
    [[ ${${(P)bootstrap_field}:-} == $fixture_token ]] || exit 67
    print -r -- login >> "$FAKE_PASS_SESSION_LOG"
    [[ ! -e $FAKE_PASS_LOGIN_DELAY ]] || /usr/bin/sleep 0.2
    : > "$FAKE_PASS_SESSION"
    ;;
  item)
    [[ $2 == view && $3 == --output && $4 == human && $# == 5 ]] || exit 68
    [[ -e $FAKE_PASS_SESSION ]] || exit 69
    [[ -z ${${(P)bootstrap_field}:-} ]] || exit 72
    [[ ${PROTON_PASS_AGENT_REASON:-} == 'secret-exec credential resolution' ]] || exit 73
    [[ ${PROTON_PASS_NO_UPDATE_CHECK:-} == 1 ]] || exit 74
    case $(/usr/bin/uname -s) in
      Linux) [[ ${PROTON_PASS_LINUX_KEYRING:-} == dbus ]] || exit 75 ;;
      Darwin) [[ -z ${PROTON_PASS_LINUX_KEYRING:-} ]] || exit 75 ;;
    esac
    print -r -- "$5" >> "$FAKE_PASS_LOG"
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
    exit 71
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
export PATH=$fake_bin:/usr/bin:/bin
export FAKE_PASS_LOG=$test_dir/pass-requests.log
export FAKE_PASS_SESSION=$test_dir/provider-session
export FAKE_PASS_SESSION_LOG=$test_dir/provider-session.log
export FAKE_PASS_LOGIN_DELAY=$test_dir/provider-login-delay
export FAKE_SECRET_TOOL_LOG=$test_dir/secret-tool-requests.log
export FAKE_NATIVE_STORE_LOCKED=$test_dir/native-store-locked
export FAKE_PASS_ITEM_DESCENDANT=$test_dir/pass-item-descendant
export FAKE_SECRET_LOOKUP_HANG=$test_dir/secret-lookup-hang
export FAKE_RESOLUTION_CHILD_PID=$test_dir/resolution-child.pid
export HOSTILE_UNAME_MARKER=$test_dir/hostile-uname-ran
export ORDINARY_SETTING=preserved
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
(( launcher_status == 0 )) ||
  fail 'the launcher must not invoke a PATH-selected platform probe'
[[ ! -e $HOSTILE_UNAME_MARKER ]] ||
  fail 'the launcher must ignore a PATH-selected platform probe'
[[ $output == target-ok ]] || fail 'selected profile must reach the target with argv preserved'
[[ $(<"$FAKE_PASS_LOG") == pass://cli-secrets/context7/password ]] || \
  fail 'the launcher must retrieve only the selected profile'

export TARGET_MARKER=$test_dir/target-ran
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

hostile_dir=$test_dir/hostile-cwd
hostile_pass_marker=$test_dir/hostile-pass-cli-ran
mkdir -p -- "$hostile_dir"
cat > "$hostile_dir/pass-cli" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

: > "$HOSTILE_PASS_CLI_MARKER"
exit 90
EOF
chmod +x "$hostile_dir/pass-cli"
export HOSTILE_PASS_CLI_MARKER=$hostile_pass_marker
original_directory=$PWD
cd "$hostile_dir"
output=$(PATH=:$fake_bin:/usr/bin:/bin zsh "$launcher" context7 -- \
  check-context 'argument with spaces')
cd "$original_directory"
[[ $output == target-ok && ! -e $hostile_pass_marker ]] ||
  fail 'the launcher must ignore a current-directory pass-cli selected by PATH'

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
: > "$FAKE_SECRET_TOOL_LOG"
output=$(zsh "$launcher" context7 -- check-context 'argument with spaces')
[[ $output == target-ok ]] ||
  fail 'the first pass-backed consumer after session loss must recover and run'
[[ $(rg -c '^login$' "$FAKE_PASS_SESSION_LOG") == 1 ]] ||
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
status_file=$XDG_STATE_HOME/secret-exec/proton-pass-readiness.status
grep -Fqx 'state=unavailable' "$status_file" ||
  fail 'a locked native store must leave value-free unavailable status'
grep -Fqx 'reason=native-store-unavailable' "$status_file" ||
  fail 'a locked native store must record its value-free reason'
rm -f -- "$FAKE_NATIVE_STORE_LOCKED"

: > "$FAKE_PASS_SESSION_LOG"
: > "$FAKE_PASS_LOGIN_DELAY"
typeset -a consumer_pids
for profile in context7 firecrawl github greptile aws; do
  zsh "$launcher" "$profile" -- check-selected "$profile" \
    >"$test_dir/concurrent-$profile.out" \
    2>"$test_dir/concurrent-$profile.err" &
  consumer_pid=$!
  consumer_pids+=($consumer_pid)
  test_process_fixture_track_pid $consumer_pid
done
for consumer_pid in $consumer_pids; do
  if wait $consumer_pid; then
    test_process_fixture_untrack_pid $consumer_pid
  else
    test_process_fixture_untrack_pid $consumer_pid
    fail 'concurrent pass-backed consumer launch failed'
  fi
done
rm -f -- "$FAKE_PASS_LOGIN_DELAY"
[[ $(rg -c '^login$' "$FAKE_PASS_SESSION_LOG") == 1 ]] ||
  fail 'concurrent pass-backed consumers must perform one serialized repair login'
! rg -F 'account-metadata-canary' "$test_dir"/*.out "$test_dir"/*.err >/dev/null ||
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
