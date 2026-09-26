#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
launcher_source=$repo_root/home/private_dot_local/bin/executable_secret-exec
readiness_source=$repo_root/home/private_dot_local/bin/executable_proton-pass-ensure-ready
dispatcher_source=$repo_root/home/private_dot_local/lib/secret-exec/executable_secret-exec-command

# exit, not return: errexit inside a function skips zsh's EXIT trap.
fail() {
  print -u2 -r -- "$1"
  exit 1
}

test_dir=$(mktemp -d "${TMPDIR:-/tmp}/secret-command-shims.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT

# zsh skips EXIT traps when errexit fires inside a function.
TRAPZERR() {
  if [[ -o errexit ]] && (( ZSH_SUBSHELL == 0 && ${#funcstack} > 1 )); then
    rm -rf -- "$test_dir"
  fi
}

fixture_home=$test_dir/home
shim_dir=$fixture_home/.local/lib/secret-exec/bin
real_bin=$test_dir/real-bin
backend_bin=$test_dir/backend-bin
runtime_bin=$test_dir/runtime-bin
cwd_target=$test_dir/cwd-target
profile_dir=$fixture_home/.config/secret-exec/profiles
config_dir=$fixture_home/.config/secret-exec
mkdir -p -- "$shim_dir" "$real_bin" "$backend_bin" "$runtime_bin" \
  "$cwd_target" "$profile_dir" "$fixture_home/.local/bin"
chmod 700 "$config_dir" "$profile_dir"

cp "$launcher_source" "$fixture_home/.local/bin/secret-exec"
cp "$readiness_source" "$fixture_home/.local/bin/proton-pass-ensure-ready"
cp "$dispatcher_source" "$fixture_home/.local/lib/secret-exec/secret-exec-command"
chmod +x "$fixture_home/.local/bin/secret-exec" \
  "$fixture_home/.local/bin/proton-pass-ensure-ready" \
  "$fixture_home/.local/lib/secret-exec/secret-exec-command"
ln -s ../secret-exec-command "$shim_dir/tool-a"
ln -s ../secret-exec-command "$shim_dir/tool-b"

cat > "$config_dir/commands.env" <<'EOF'
tool-a=member
tool-b=member
EOF
cat > "$profile_dir/member.env" <<'EOF'
MEMBER_TOKEN=pass://fixture-store/member/token
!UNRELATED_SECRET
EOF
cat > "$profile_dir/other.env" <<'EOF'
OTHER_TOKEN=pass://fixture-store/other/token
EOF
chmod 600 "$config_dir/commands.env" "$profile_dir/member.env" \
  "$profile_dir/other.env"

cat > "$fixture_home/.local/bin/pass-cli" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

print -r -- "$1" >> "$FAKE_PASS_LOG"
case $1 in
  info)
    (( $# == 1 )) || exit 64
    [[ ${PROTON_PASS_NO_UPDATE_CHECK:-} == 1 ]] || exit 65
    ;;
  item)
    [[ $2 == view && $3 == --output && $4 == human && $# == 5 ]] || exit 66
    if [[ -n ${FAKE_PASS_ITEM_FAIL:-} ]]; then
      print -u2 -r -- "provider-output-canary $5"
      exit 1
    fi
    case $5 in
      pass://fixture-store/member/token) fixture_value=member-canary ;;
      pass://fixture-store/other/token) fixture_value=other-canary ;;
      *) exit 67 ;;
    esac
    [[ ${PROTON_PASS_AGENT_REASON:-} == 'secret-exec credential resolution' ]] || exit 68
    [[ ${PROTON_PASS_NO_UPDATE_CHECK:-} == 1 ]] || exit 69
    case $(/usr/bin/uname -s) in
      Linux) [[ ${PROTON_PASS_LINUX_KEYRING:-} == dbus ]] || exit 71 ;;
      Darwin) [[ -z ${PROTON_PASS_LINUX_KEYRING:-} ]] || exit 71 ;;
    esac
    print -r -- "$fixture_value"
    ;;
  *)
    exit 72
    ;;
esac
EOF
chmod +x "$fixture_home/.local/bin/pass-cli"

for command_name in tool-a tool-b; do
  cat > "$real_bin/$command_name" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

[[ ${MEMBER_TOKEN:-} == member-canary ]] || exit 70
[[ -z ${UNRELATED_SECRET:-} ]] || exit 71
[[ $1 == 'argument with spaces' ]] || exit 72
print -r -- "${0:t}-ok"
EOF
  chmod +x "$real_bin/$command_name"
done

cat > "$cwd_target/tool-a" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

[[ ${MEMBER_TOKEN:-} == member-canary ]] || exit 70
print -r -- 'cwd-ok'
EOF
chmod +x "$cwd_target/tool-a"

cat > "$real_bin/exit-37" <<'EOF'
#!/usr/bin/env zsh
exit 37
EOF
chmod +x "$real_bin/exit-37"

cat > "$real_bin/exit-0" <<'EOF'
#!/usr/bin/env zsh
exit 0
EOF
chmod +x "$real_bin/exit-0"

for notifier_name in notify-send osascript; do
  cat > "$backend_bin/$notifier_name" <<'EOF'
#!/usr/bin/env zsh
print -rl -- "${0:t}" "$@" >> "$FAKE_NOTIFY_LOG"
if [[ -n ${FAKE_NOTIFY_PID:-} ]]; then
  print -r -- $$ > "$FAKE_NOTIFY_PID"
  exec /bin/sleep 30
fi
EOF
  chmod +x "$backend_bin/$notifier_name"
done

# The notifier runs detached; wait for the whole record instead of racing it.
wait_for_notification() {
  local expected=$1
  integer polls=500
  zmodload zsh/zselect
  while (( polls-- > 0 )); do
    [[ -s $FAKE_NOTIFY_LOG && $(<"$FAKE_NOTIFY_LOG") == "$expected" ]] && return 0
    zselect -t 1 2>/dev/null || true
  done
  return 1
}

expected_notification() {
  local platform=$1 command_name=$2 profile=$3
  local title='Credentials unavailable'
  local body="$command_name started without its $profile credentials. Restart it once the credential provider is available."
  case $platform in
    linux*)
      print -rl -- notify-send '--app-name=Secret-backed tools' "$title" "$body"
      ;;
    darwin*)
      print -rl -- osascript -e 'on run argv' \
        -e 'display notification (item 1 of argv) with title (item 2 of argv)' \
        -e 'end run' "$body" "$title"
      ;;
  esac
}

zsh_path=${commands[zsh]}
ln -s "$zsh_path" "$runtime_bin/zsh"

export HOME=$fixture_home
export XDG_CONFIG_HOME=$fixture_home/.config
export XDG_STATE_HOME=$test_dir/state
export PATH=$shim_dir:$real_bin:$backend_bin:$fixture_home/.local/bin:/usr/bin:/bin
export FAKE_PASS_LOG=$test_dir/pass.log
export FAKE_NOTIFY_LOG=$test_dir/notify.log
export MEMBER_TOKEN=inherited-member
export UNRELATED_SECRET=inherited-unrelated

output=$(tool-a 'argument with spaces')
[[ $output == tool-a-ok ]] || fail 'the first shim must launch the real executable'
[[ $(<"$FAKE_PASS_LOG") == $'info\nitem' ]] ||
  fail 'a pass-backed shim must validate readiness before resolving its value'

output=$(tool-b 'argument with spaces')
[[ $output == tool-b-ok ]] || fail 'the second shim must launch the real executable'

original_directory=$PWD
cd "$cwd_target"
PATH=$shim_dir::$real_bin:$backend_bin:$fixture_home/.local/bin:/usr/bin:/bin
output=$(tool-a 'argument with spaces')
PATH=$shim_dir:$real_bin:$backend_bin:$fixture_home/.local/bin:/usr/bin:/bin
cd "$original_directory"
[[ $output == cwd-ok ]] || fail 'an empty PATH component must resolve the current directory'

trace_output=$(zsh -x "$shim_dir/tool-a" 'argument with spaces' 2>&1)
[[ $trace_output != *member-canary* ]] || fail 'xtrace must not expose a retrieved value'

cp "$real_bin/exit-37" "$real_bin/tool-a"
set +e
tool-a
exit_code=$?
set -e
(( exit_code == 37 )) || fail 'the shim must preserve the real executable exit status'

multicall_bin=$test_dir/multicall-bin
mkdir -- "$multicall_bin"
cat > "$multicall_bin/multicall" <<'EOF'
#!/usr/bin/env zsh
print -r -- "${0:t}"
EOF
chmod +x "$multicall_bin/multicall"
rm -- "$real_bin/tool-a"
ln -s ../multicall-bin/multicall "$real_bin/tool-a"
output=$(tool-a)
[[ $output == tool-a ]] ||
  fail 'the shim must preserve the invoked name of a symlinked multi-call executable'
rm -- "$real_bin/tool-a"

# A PATH entry that leaves a symlink through `..` must exec the file the
# dispatcher checked, not the one a lexical `..` removal names.
dotdot_dir=$test_dir/dotdot
mkdir -p -- "$dotdot_dir/real/nested"
ln -s real/nested "$dotdot_dir/link"
print -r -- $'#!/bin/sh\necho checked' > "$dotdot_dir/real/tool-a"
print -r -- $'#!/bin/sh\necho lexical' > "$dotdot_dir/tool-a"
chmod +x "$dotdot_dir/real/tool-a" "$dotdot_dir/tool-a"
cd "$dotdot_dir"
for dotdot_entry in "$dotdot_dir/link/.." link/..; do
  PATH=$shim_dir:$dotdot_entry:$real_bin:$backend_bin:$fixture_home/.local/bin:/usr/bin:/bin
  output=$(tool-a)
  [[ $output == checked ]] ||
    fail "a symlink-then-.. PATH entry must exec the checked file ($dotdot_entry): $output"
done

# The same entry form can reach the shim directory itself; the dispatcher must
# skip it like the shim directory, not re-dispatch to its own shim in a loop.
zmodload zsh/zselect
mkdir -- "$shim_dir/nested"
ln -s "$shim_dir/nested" "$dotdot_dir/shim-link"
PATH=$shim_dir:$dotdot_dir/shim-link/..:$dotdot_dir/link/..:$real_bin:$backend_bin:$fixture_home/.local/bin:/usr/bin:/bin
tool-a > "$test_dir/shim-loop.out" 2>&1 &
shim_loop_pid=$!
integer shim_loop_polls=500
while (( shim_loop_polls-- > 0 )) && kill -0 $shim_loop_pid 2>/dev/null; do
  zselect -t 1 2>/dev/null || true
done
if kill -0 $shim_loop_pid 2>/dev/null; then
  kill -KILL $shim_loop_pid 2>/dev/null || true
  fail 'a symlink-then-.. PATH entry into the shim directory must not re-dispatch the shim'
fi
wait $shim_loop_pid ||
  fail "a symlink-then-.. PATH entry into the shim directory must be skipped: status $?"
[[ $(<"$test_dir/shim-loop.out") == checked ]] ||
  fail "a symlink-then-.. PATH entry into the shim directory must be skipped: $(<"$test_dir/shim-loop.out")"
rm -- "$dotdot_dir/shim-link"
rmdir -- "$shim_dir/nested"
PATH=$shim_dir:$real_bin:$backend_bin:$fixture_home/.local/bin:/usr/bin:/bin
cd "$original_directory"

# Provenance marker: an already-injected profile skips the provider lookup, but
# the launcher still scrubs every other managed name.
launcher=$fixture_home/.local/bin/secret-exec
counted_launcher=$fixture_home/.local/bin/secret-exec-counted
launcher_log=$test_dir/launcher-calls.log
cp "$launcher" "$counted_launcher"
mv "$launcher" "$test_dir/secret-exec"
cat > "$launcher" <<'EOF'
#!/usr/bin/env zsh
print -r -- "$1" >> "$LAUNCHER_LOG"
exec "${0:h}/secret-exec-counted" "$@"
EOF
chmod +x "$launcher"
export LAUNCHER_LOG=$launcher_log
cat > "$real_bin/tool-a" <<'EOF'
#!/usr/bin/env zsh
print -r -- "marker=${SECRET_EXEC_INJECTED_PROFILES-unset}" \
  "member=${MEMBER_TOKEN-unset} other=${OTHER_TOKEN-unset}" \
  "unrelated=${UNRELATED_SECRET-unset}"
EOF
chmod +x "$real_bin/tool-a"
injected_output='marker=member member=inherited-member other=unset unrelated=unset'
resolved_output='marker=member member=member-canary other=unset unrelated=unset'

for injected_marker in member 'other member' 'member other'; do
  : > "$launcher_log"
  : > "$FAKE_PASS_LOG"
  output=$(OTHER_TOKEN=inherited-other \
    SECRET_EXEC_INJECTED_PROFILES=$injected_marker tool-a)
  [[ $output == "$injected_output" ]] ||
    fail "an injected profile must keep its value and scrub the rest ('$injected_marker'): $output"
  [[ $(<"$launcher_log") == member && ! -s $FAKE_PASS_LOG ]] ||
    fail "an injected profile must pass through the launcher without a provider call ('$injected_marker')"
done

for spoofed_value in unset empty multiline; do
  : > "$launcher_log"
  : > "$FAKE_PASS_LOG"
  case $spoofed_value in
    unset) output=$(unset MEMBER_TOKEN; SECRET_EXEC_INJECTED_PROFILES=member tool-a) ;;
    empty) output=$(MEMBER_TOKEN= SECRET_EXEC_INJECTED_PROFILES=member tool-a) ;;
    multiline)
      output=$(MEMBER_TOKEN=$'first\nsecond' SECRET_EXEC_INJECTED_PROFILES=member tool-a)
      ;;
  esac
  [[ $output == "$resolved_output" && $(<"$FAKE_PASS_LOG") == $'info\nitem' ]] ||
    fail "a marker without a usable value must resolve through the provider ($spoofed_value): $output"
done

for spoof_marker in member-extra xmember mem member.x 'other member-extra' ''; do
  : > "$launcher_log"
  : > "$FAKE_PASS_LOG"
  output=$(SECRET_EXEC_INJECTED_PROFILES=$spoof_marker tool-a)
  [[ $output == "$resolved_output" && $(<"$FAKE_PASS_LOG") == $'info\nitem' ]] ||
    fail "a non-matching marker must resolve through the provider: '$spoof_marker'"
  [[ $(<"$launcher_log") == member ]] ||
    fail "a non-matching marker must invoke the launcher once: '$spoof_marker'"
done

: > "$launcher_log"
output=$(unset SECRET_EXEC_INJECTED_PROFILES; tool-a)
[[ $output == "$resolved_output" && $(<"$launcher_log") == member ]] ||
  fail 'an absent marker must inject through the launcher'

: > "$launcher_log"
output=$(OTHER_TOKEN=inherited-other "$launcher" other -- tool-a)
[[ $output == "$resolved_output" ]] ||
  fail 'a shim inside another profile must replace the marker and scrub its values'
[[ $(<"$launcher_log") == $'other\nmember' ]] ||
  fail 'a shim inside another profile must invoke the launcher again'

output=$("$launcher" member -- "$launcher" other -- "$real_bin/tool-a")
[[ $output == 'marker=other member=unset other=other-canary unrelated=unset' ]] ||
  fail 'a nested launcher must name exactly the profile whose values are present'

rm -- "$launcher" "$counted_launcher" "$real_bin/tool-a"
mv "$test_dir/secret-exec" "$launcher"
unset LAUNCHER_LOG

# Best-effort mappings: provider or readiness failure runs the target without
# injection; ordinary mappings and launch-contract failures still fail closed.
zmodload zsh/zselect
cat > "$real_bin/tool-a" <<'EOF'
#!/usr/bin/env zsh
print -r -- "marker=${SECRET_EXEC_INJECTED_PROFILES-unset}" \
  "member=${MEMBER_TOKEN-unset} unrelated=${UNRELATED_SECRET-unset}" \
  "reason=${PROTON_PASS_AGENT_REASON-unset}"
exit ${TOOL_EXIT:-0}
EOF
chmod +x "$real_bin/tool-a"
fallback_output='marker=unset member=unset unrelated=unset reason=unset'
fallback_notification=$(expected_notification "$OSTYPE" tool-a member)

print -r -- $'tool-a=member?\ntool-b=member' > "$config_dir/commands.env"
: > "$FAKE_NOTIFY_LOG"
output=$(tool-a)
[[ $output == 'marker=member member=member-canary unrelated=unset reason=unset' ]] ||
  fail "a best-effort mapping must inject when the provider is available: $output"
output=$(SECRET_EXEC_INJECTED_PROFILES=member FAKE_PASS_ITEM_FAIL=1 tool-a 2>/dev/null)
[[ $output == 'marker=member member=inherited-member unrelated=unset reason=unset' ]] ||
  fail "a best-effort mapping must reuse an injected value without the provider: $output"

: > "$FAKE_PASS_LOG"
set +e
output=$(FAKE_PASS_ITEM_FAIL=1 tool-a 2>"$test_dir/best-effort.err")
exit_code=$?
set -e
(( exit_code == 0 )) && [[ $output == "$fallback_output" ]] ||
  fail "a best-effort resolution failure must run the target without injection: status=$exit_code output=$output"
[[ $(<"$test_dir/best-effort.err") == *'secret-exec: failed to resolve MEMBER_TOKEN'* &&
  $(<"$test_dir/best-effort.err") == *'secret-exec: starting tool-a without member credentials'* ]] ||
  fail 'a best-effort fallback must report its value-free reason on stderr'
wait_for_notification "$fallback_notification" ||
  fail "a best-effort fallback must emit one notification: $(<"$FAKE_NOTIFY_LOG")"
[[ $(<"$FAKE_NOTIFY_LOG") != *(canary|pass://)* ]] ||
  fail 'a best-effort notification must not contain values, locators, or provider output'

: > "$FAKE_NOTIFY_LOG"
set +e
FAKE_PASS_ITEM_FAIL=1 TOOL_EXIT=37 tool-a > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code == 37 )) || fail 'a best-effort fallback must preserve the target exit status'
wait_for_notification "$fallback_notification" ||
  fail 'a best-effort fallback with a failing target must still notify'

: > "$FAKE_NOTIFY_LOG"
set +e
output=$(FAKE_PASS_ITEM_FAIL=1 tool-b 2>/dev/null)
exit_code=$?
set -e
(( exit_code == 1 )) && [[ -z $output ]] ||
  fail 'an ordinary mapping must still fail closed when the provider fails'
zselect -t 50 2>/dev/null || true
[[ ! -s $FAKE_NOTIFY_LOG ]] || fail 'a fail-closed mapping must not notify'

readiness=$fixture_home/.local/bin/proton-pass-ensure-ready
mv "$readiness" "$test_dir/proton-pass-ensure-ready"
print -r -- $'#!/bin/sh\nexit 1' > "$readiness"
chmod +x "$readiness"
: > "$FAKE_NOTIFY_LOG"
: > "$FAKE_PASS_LOG"
output=$(tool-a 2>/dev/null)
[[ $output == "$fallback_output" && ! -s $FAKE_PASS_LOG ]] ||
  fail "a best-effort readiness failure must run the target without resolving: $output"
wait_for_notification "$fallback_notification" ||
  fail 'a best-effort readiness failure must notify'
rm -- "$readiness"
mv "$test_dir/proton-pass-ensure-ready" "$readiness"

: > "$FAKE_NOTIFY_LOG"
notify_pid_file=$test_dir/notify.pid
zmodload zsh/datetime
typeset -F launch_started=$EPOCHREALTIME
output=$(FAKE_PASS_ITEM_FAIL=1 FAKE_NOTIFY_PID=$notify_pid_file tool-a 2>/dev/null)
typeset -F launch_elapsed=$(( EPOCHREALTIME - launch_started ))
[[ $output == "$fallback_output" ]] && (( launch_elapsed < 1.5 )) ||
  fail "a hanging notifier must not delay the target: elapsed=$launch_elapsed"
integer notify_polls=500
while (( notify_polls-- > 0 )) && [[ ! -s $notify_pid_file ]]; do
  zselect -t 1 2>/dev/null || true
done
[[ -s $notify_pid_file ]] || fail 'the hanging notifier fixture must start'
notify_pid=$(<"$notify_pid_file")
notify_polls=400
while (( notify_polls-- > 0 )) && kill -0 $notify_pid 2>/dev/null; do
  zselect -t 1 2>/dev/null || true
done
if kill -0 $notify_pid 2>/dev/null; then
  kill -KILL $notify_pid 2>/dev/null || true
  fail 'a hanging notifier must be terminated within its bound'
fi

: > "$FAKE_NOTIFY_LOG"
set +e
# Source at top level: the launcher's readonly globals must not become locals.
output=$(FAKE_PASS_ITEM_FAIL=1 /bin/zsh -f -c '
  OSTYPE=darwin23.0
  source "$@"
' secret-exec "$launcher" --best-effort member -- "$real_bin/tool-a" \
  2>"$test_dir/darwin.err")
exit_code=$?
set -e
(( exit_code == 0 )) && [[ $output == "$fallback_output" ]] ||
  fail "a macOS best-effort fallback must run the target without injection: status=$exit_code output=$output error=$(<"$test_dir/darwin.err")"
wait_for_notification "$(expected_notification darwin tool-a member)" ||
  fail "a macOS best-effort fallback must notify through osascript: $(<"$FAKE_NOTIFY_LOG")"

: > "$FAKE_NOTIFY_LOG"
print -r -- 'tool-a=unknown?' > "$config_dir/commands.env"
set +e
output=$(tool-a 2>/dev/null)
exit_code=$?
set -e
(( exit_code == 1 )) && [[ -z $output ]] ||
  fail 'a best-effort mapping to an unknown profile must fail closed'
cp "$profile_dir/member.env" "$test_dir/member.env"
print -r -- 'MEMBER_TOKEN = pass://fixture-store/member/token' > "$profile_dir/member.env"
print -r -- 'tool-a=member?' > "$config_dir/commands.env"
set +e
output=$(tool-a 2>/dev/null)
exit_code=$?
set -e
cp "$test_dir/member.env" "$profile_dir/member.env"
(( exit_code == 1 )) && [[ -z $output ]] ||
  fail 'a best-effort mapping to a malformed profile must fail closed'
zselect -t 50 2>/dev/null || true
[[ ! -s $FAKE_NOTIFY_LOG ]] || fail 'a launch-contract failure must not notify'
rm -- "$real_bin/tool-a"

cp "$real_bin/exit-0" "$real_bin/tool-a"
mv "$launcher" "$test_dir/secret-exec"
mkdir "$launcher"
chmod +x "$launcher"
set +e
tool-a > /dev/null 2>&1
exit_code=$?
MEMBER_TOKEN=member-canary SECRET_EXEC_INJECTED_PROFILES=member \
  tool-a > /dev/null 2>&1
injected_exit_code=$?
set -e
rmdir "$launcher"
mv "$test_dir/secret-exec" "$launcher"
(( exit_code == 1 )) || fail 'the dispatcher must reject an executable launcher directory'
(( injected_exit_code == 1 )) ||
  fail 'the dispatcher must reject a launcher directory inside an injected process tree'

print -r -- 'tool-a=unknown' > "$config_dir/commands.env"
set +e
tool-a > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code == 1 )) || fail 'an unknown profile mapping must fail closed'

print -r -- 'other=member' > "$config_dir/commands.env"
set +e
tool-a > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code == 1 )) || fail 'a missing command mapping must fail closed'

print -r -- $'tool-a=member\ntool-a=other' > "$config_dir/commands.env"
set +e
tool-a > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code == 1 )) || fail 'a duplicate command mapping must fail closed'

print -r -- 'tool-a = member' > "$config_dir/commands.env"
set +e
tool-a > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code == 1 )) || fail 'a malformed command mapping must fail closed'

for malformed_mapping in 'tool-a=member??' 'tool-a=?' 'tool-a=member?x' \
  'tool-a?=member' 'tool-a=?member' 'tool-a=member ?' $'tool-a=member\ntool-a=member?'; do
  print -r -- "$malformed_mapping" > "$config_dir/commands.env"
  set +e
  mapping_error=$(tool-a 2>&1 >/dev/null)
  exit_code=$?
  set -e
  (( exit_code == 1 )) &&
    [[ $mapping_error == 'secret-exec-command: '(invalid|duplicate)' '* ]] ||
    fail "the dispatcher must reject a malformed best-effort mapping: '$malformed_mapping'"
done

print -r -- 'tool-a=member' > "$config_dir/commands.env"
rm -- "$real_bin/tool-a"
full_fixture_path=$PATH
PATH=$shim_dir:$real_bin:$runtime_bin
set +e
tool-a > /dev/null 2>&1
exit_code=$?
set -e
PATH=$full_fixture_path
(( exit_code != 0 )) || fail 'a missing later executable must fail closed without recursion'

print -r -- 'secret command shim checks passed'
