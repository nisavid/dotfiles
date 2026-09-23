#!/usr/bin/env zsh
# Exercise the build-tool shims against fake systemd-run, systemctl, choom, and
# build-tool binaries.
emulate -L zsh
setopt errexit nounset pipefail

repo_root=${0:A:h:h}
source_home=$repo_root/home/private_dot_local
dispatcher_source=$source_home/lib/builds-slice/executable_builds-slice-command
test_root=$(mktemp -d "${TMPDIR:-/tmp}/build-memory-guards.XXXXXX")
trap 'rm -rf -- "$test_root"' EXIT HUP INT TERM

# exit, not return: zsh skips the EXIT trap when errexit fires on a function's
# status, and the temporary directory would stay behind.
fail() {
  print -u2 -r -- "FAIL: $*"
  exit 1
}

sh -n "$dispatcher_source" || fail 'build-tool dispatcher has a syntax error'

bin=$test_root/bin
runtime=$test_root/runtime
log=$test_root/log
err=$test_root/err
cgroup=$test_root/cgroup
oom=$test_root/oom_score_adj
# Mirror ~/.local so the symlinks resolve through their deployed relative targets.
shims=$test_root/local/bin
dispatcher=$test_root/local/lib/builds-slice/builds-slice-command
mkdir -m 700 -p "$bin" "$runtime/systemd" "$shims" "${dispatcher:h}"

sed \
  -e "s#^usr_bin=/usr/bin\$#usr_bin=$bin#" \
  -e "s#^self_cgroup=/proc/self/cgroup\$#self_cgroup=$cgroup#" \
  -e "s#^self_oom_score_adj=/proc/self/oom_score_adj\$#self_oom_score_adj=$oom#" \
  "$dispatcher_source" >"$dispatcher"
for line in "usr_bin=$bin" "self_cgroup=$cgroup" "self_oom_score_adj=$oom"; do
  grep -Fqx -- "$line" "$dispatcher" ||
    fail "dispatcher fixture path was not substituted: $line"
done
chmod 700 "$dispatcher"

typeset -a tool_names=(cmake makepkg ninja)
for tool_name in $tool_names; do
  ln -s -- "$(<"$source_home/bin/symlink_$tool_name")" "$shims/$tool_name"
  [[ $shims/$tool_name -ef $dispatcher ]] ||
    fail "the $tool_name symlink does not resolve to the dispatcher"
done

# Each fake build tool logs the name it was run as, its arguments, and the
# parts of its environment the shims must preserve.
cat >"$bin/fake-tool" <<'EOF'
#!/bin/sh
name=${0##*/}
{
  printf '%s' "$name"
  printf ' [%s]' "$@"
  printf '\n'
  if [ -n "${LD_PRELOAD+set}" ]; then
    printf '%s LD_PRELOAD=[%s]\n' "$name" "$LD_PRELOAD"
  else
    printf '%s LD_PRELOAD unset\n' "$name"
  fi
  printf '%s MARKER=[%s]\n' "$name" "${MARKER-}"
} >>"$FAKE_LOG"
printf '%s\n' "$PPID" >"$FAKE_LOG.ppid"
exit "${FAKE_TOOL_STATUS:-0}"
EOF
for tool_name in $tool_names; do
  cp -- "$bin/fake-tool" "$bin/$tool_name"
done
ln -s -- "${commands[env]}" "$bin/env"
cat >"$bin/systemd-run" <<'EOF'
#!/bin/sh
{
  printf 'systemd-run'
  printf ' [%s]' "$@"
  printf '\n'
  if [ -n "${LD_PRELOAD+set}" ]; then
    printf 'systemd-run LD_PRELOAD set\n'
  else
    printf 'systemd-run LD_PRELOAD unset\n'
  fi
} >>"$FAKE_LOG"
while [ "$#" -gt 0 ]; do
  if [ "$1" = -- ]; then
    shift
    exec "$@"
  fi
  shift
done
exit 99
EOF
# Answers the dispatcher's FragmentPath query like the user manager, or fails
# like systemctl does when the manager refuses the caller.
cat >"$bin/systemctl" <<'EOF'
#!/bin/sh
{
  printf 'systemctl'
  printf ' [%s]' "$@"
  printf '\n'
  if [ -n "${LD_PRELOAD+set}" ]; then
    printf 'systemctl LD_PRELOAD set\n'
  else
    printf 'systemctl LD_PRELOAD unset\n'
  fi
} >>"$FAKE_LOG"
if [ -n "${FAKE_SYSTEMCTL_STATUS-}" ]; then
  printf 'Failed to connect to user scope bus via local transport: No data available\n' >&2
  exit "$FAKE_SYSTEMCTL_STATUS"
fi
printf '%s\n' "${FAKE_FRAGMENT-/fixture/builds.slice}"
EOF
cat >"$bin/choom" <<'EOF'
#!/bin/sh
{
  printf 'choom'
  printf ' [%s]' "$@"
  printf '\n'
} >>"$FAKE_LOG"
[ "$1" = -n ] && [ "$3" = -- ] || exit 98
shift 3
exec "$@"
EOF
chmod 700 "$bin"/*(.)

# Bind relative to the directory: macOS limits socket paths to 104 bytes.
python3 -c '
import os, socket, sys
os.chdir(sys.argv[1])
socket.socket(socket.AF_UNIX).bind("private")
' "$runtime/systemd"
[[ -S $runtime/systemd/private ]] || fail 'socket fixture was not created'

outside_slice='0::/user.slice/manager/app.slice/app-fixture.scope'
inside_slice='0::/user.slice/manager/builds.slice/run-r1.scope'
near_miss='0::/user.slice/manager/app.slice/mybuilds.slice/run-r1.scope'
tool_args=(-C 'dir with space' 'target$HOME' '${MARKER}' '$$' '%h')
bracketed_args='[-C] [dir with space] [target$HOME] [${MARKER}] [$$] [%h]'

# Run the shim named by $tool_name with a minimal environment. Callers pass
# extra NAME=value pairs.
tool_name=ninja
run_shim() {
  local rc=0
  : >"$log"
  rm -f -- "$log.ppid"
  env -i PATH=/usr/bin:/bin FAKE_LOG="$log" MARKER=kept "$@" \
    "$shims/$tool_name" "${tool_args[@]}" 2>"$err" || rc=$?
  return $rc
}

expect_log() {
  local expected=$1 description=$2
  [[ $(<"$log") == "$expected" ]] || {
    print -u2 -rl -- "--- expected ($description)" "$expected" '--- actual' "$(<"$log")"
    fail "$description"
  }
  # Every hop execs, so the tool is still the test shell's own child.
  [[ $(<"$log.ppid") == $$ ]] || fail "$description: the tool is not the caller's child"
}

# The dispatcher asks the user manager for the slice's unit file without
# LD_PRELOAD.
probe_log() {
  print -r -- 'systemctl [--user] [show] [-P] [FragmentPath] [builds.slice]'
  print -r -- 'systemctl LD_PRELOAD unset'
}

# Expected log of a scoped run. A second argument is the caller's LD_PRELOAD.
scoped_log() {
  local adj=$1 restore='' tool_preload="$tool_name LD_PRELOAD unset"
  if (( $# > 1 )); then
    restore="[$bin/env] [LD_PRELOAD=$2] "
    tool_preload="$tool_name LD_PRELOAD=[$2]"
  fi
  probe_log
  print -r -- \
    "systemd-run [--user] [--scope] [--quiet] [--collect] [--expand-environment=no] [--property=OOMPolicy=continue] [--slice=builds.slice] [--] ${restore}[$bin/choom] [-n] [$adj] [--] [$bin/$tool_name] $bracketed_args"
  print -r -- 'systemd-run LD_PRELOAD unset'
  print -r -- "choom [-n] [$adj] [--] [$bin/$tool_name] $bracketed_args"
  print -r -- "$tool_name $bracketed_args"
  print -r -- "$tool_preload"
  print -r -- "$tool_name MARKER=[kept]"
}

# Expected log of the tool run directly. An argument is the caller's LD_PRELOAD.
direct_log() {
  print -r -- "$tool_name $bracketed_args"
  if (( $# )); then
    print -r -- "$tool_name LD_PRELOAD=[$1]"
  else
    print -r -- "$tool_name LD_PRELOAD unset"
  fi
  print -r -- "$tool_name MARKER=[kept]"
}

# Fallbacks warn exactly once, run the tool directly, and keep its status. The
# third argument is the expected log.
expect_fallback() {
  local description=$1 reason=$2 expected=$3
  shift 3
  local rc=0
  run_shim FAKE_TOOL_STATUS=5 "$@" || rc=$?
  (( rc == 5 )) || fail "$description returned $rc instead of the tool's 5"
  expect_log "$expected" "$description runs $tool_name directly"
  [[ $(wc -l <"$err") -eq 1 ]] || fail "$description did not warn exactly once: $(<"$err")"
  grep -Fq -- "$tool_name: warning: $reason; running $bin/$tool_name without the builds.slice memory cap" "$err" ||
    fail "$description warning is wrong: $(<"$err")"
}

# Refusals run nothing, print one line, and return the expected status.
expect_refusal() {
  local description=$1 expected_rc=$2 message=$3
  shift 3
  local rc=0
  : >"$log"
  env -i PATH=/usr/bin:/bin FAKE_LOG="$log" XDG_RUNTIME_DIR="$runtime" \
    "$@" "${tool_args[@]}" 2>"$err" || rc=$?
  (( rc == expected_rc )) || fail "$description returned $rc instead of $expected_rc"
  [[ ! -s $log ]] || fail "$description ran something: $(<"$log")"
  [[ $(<"$err") == "$message" ]] || fail "$description message is wrong: $(<"$err")"
}

unreachable='the systemd user manager is unreachable'
print -r -- "$outside_slice" >"$cgroup"
print -r -- 200 >"$oom"

# The full matrix runs through the ninja symlink.
tool_name=ninja

# Scoped run: exact argv, literal "$" and "%", environment, and status.
run_shim XDG_RUNTIME_DIR="$runtime" || fail 'scoped run failed'
expect_log "$(scoped_log 500)" 'scoped run passes exact arguments through systemd-run and choom'
[[ ! -s $err ]] || fail "scoped run wrote to stderr: $(<"$err")"

rc=0
run_shim XDG_RUNTIME_DIR="$runtime" FAKE_TOOL_STATUS=3 || rc=$?
(( rc == 3 )) || fail "scoped run returned $rc instead of Ninja's 3"

# A process under a path merely ending in "builds.slice" is not in the slice.
print -r -- "$near_miss" >"$cgroup"
run_shim XDG_RUNTIME_DIR="$runtime" || fail 'near-miss cgroup run failed'
expect_log "$(scoped_log 500)" 'near-miss cgroup path is treated as outside builds.slice'
print -r -- "$outside_slice" >"$cgroup"

# The OOM score is raised to 500, never lowered; unreadable values fall back to 500.
for current expected in 800 800 500 500 -100 500 bogus 500; do
  print -r -- "$current" >"$oom"
  run_shim XDG_RUNTIME_DIR="$runtime" || fail "OOM score $current run failed"
  expect_log "$(scoped_log $expected)" "OOM score $current becomes $expected"
done
rm -- "$oom"
run_shim XDG_RUNTIME_DIR="$runtime" || fail 'missing OOM score run failed'
expect_log "$(scoped_log 500)" 'missing OOM score becomes 500'
print -r -- 200 >"$oom"

# systemd-run runs without LD_PRELOAD; choom and Ninja get it back verbatim.
for preload in '' '$LIB/libfixture.so'; do
  run_shim XDG_RUNTIME_DIR="$runtime" LD_PRELOAD="$preload" ||
    fail "LD_PRELOAD=[$preload] run failed"
  expect_log "$(scoped_log 500 "$preload")" \
    "LD_PRELOAD=[$preload] is hidden from systemd-run and restored for Ninja"
done

# Inside builds.slice, Ninja runs directly without a nested scope.
print -r -- "$inside_slice" >"$cgroup"
run_shim XDG_RUNTIME_DIR="$runtime" || fail 'in-slice run failed'
expect_log "$(direct_log)" 'in-slice run execs Ninja directly'
[[ ! -s $err ]] || fail "in-slice run wrote to stderr: $(<"$err")"
# makepkg's package() runs under fakeroot, so the tools it starts inside the
# slice arrive with LD_PRELOAD set and must keep it.
run_shim XDG_RUNTIME_DIR="$runtime" LD_PRELOAD= || fail 'in-slice LD_PRELOAD run failed'
expect_log "$(direct_log '')" 'in-slice run keeps LD_PRELOAD for Ninja'
print -r -- "$outside_slice" >"$cgroup"

expect_fallback 'missing XDG_RUNTIME_DIR' "$unreachable" "$(direct_log)"
mkdir -m 700 "$test_root/empty-runtime"
expect_fallback 'runtime directory without a manager socket' "$unreachable" "$(direct_log)" \
  XDG_RUNTIME_DIR="$test_root/empty-runtime"
# The sockets exist but the manager refuses the caller, as in a PID namespace.
expect_fallback 'manager that does not answer' "$unreachable" "$(probe_log; direct_log)" \
  XDG_RUNTIME_DIR="$runtime" FAKE_SYSTEMCTL_STATUS=1
# The query drops LD_PRELOAD only for itself. An empty value keeps the dynamic
# loader quiet and still tells "set" from "unset".
expect_fallback 'manager that does not answer under LD_PRELOAD' "$unreachable" \
  "$(probe_log; direct_log '')" \
  XDG_RUNTIME_DIR="$runtime" FAKE_SYSTEMCTL_STATUS=1 LD_PRELOAD=
expect_fallback 'builds.slice without a unit file' 'builds.slice has no unit file' \
  "$(probe_log; direct_log)" XDG_RUNTIME_DIR="$runtime" FAKE_FRAGMENT=
for tool in systemd-run systemctl choom; do
  chmod -x "$bin/$tool"
  expect_fallback "missing $tool" "$bin/$tool is unavailable" "$(direct_log)" \
    XDG_RUNTIME_DIR="$runtime"
  chmod +x "$bin/$tool"
done

# The warning is best-effort: with stderr closed, the tool still runs.
rc=0
: >"$log"
rm -f -- "$log.ppid"
env -i PATH=/usr/bin:/bin FAKE_LOG="$log" MARKER=kept FAKE_TOOL_STATUS=5 \
  "$shims/$tool_name" "${tool_args[@]}" 2>&- || rc=$?
(( rc == 5 )) || fail "fallback with stderr closed returned $rc instead of the tool's 5"
expect_log "$(direct_log)" 'fallback with stderr closed runs Ninja directly'

# The cmake and makepkg symlinks run their own tools through the same paths.
for tool_name in cmake makepkg; do
  run_shim XDG_RUNTIME_DIR="$runtime" || fail "scoped $tool_name run failed"
  expect_log "$(scoped_log 500)" "scoped $tool_name run passes exact arguments"
  [[ ! -s $err ]] || fail "scoped $tool_name run wrote to stderr: $(<"$err")"

  print -r -- "$inside_slice" >"$cgroup"
  run_shim XDG_RUNTIME_DIR="$runtime" || fail "in-slice $tool_name run failed"
  expect_log "$(direct_log)" "in-slice $tool_name run execs the tool directly"
  run_shim XDG_RUNTIME_DIR="$runtime" LD_PRELOAD= ||
    fail "in-slice $tool_name LD_PRELOAD run failed"
  expect_log "$(direct_log '')" "in-slice $tool_name run keeps LD_PRELOAD"
  print -r -- "$outside_slice" >"$cgroup"

  expect_fallback "$tool_name with missing XDG_RUNTIME_DIR" "$unreachable" "$(direct_log)"

  # A missing tool fails like a missing command, before any systemd query.
  chmod -x "$bin/$tool_name"
  expect_refusal "$tool_name without its tool" 127 \
    "$tool_name: $bin/$tool_name is not installed" "$shims/$tool_name"
  chmod +x "$bin/$tool_name"
done

# The dispatcher refuses its own name and names it has no tool for.
ln -s -- ../lib/builds-slice/builds-slice-command "$shims/make"
expect_refusal 'a make symlink' 2 \
  'make: run this through a cmake, makepkg, or ninja symlink' "$shims/make"
expect_refusal 'the dispatcher run by its own name' 2 \
  'builds-slice-command: run this through a cmake, makepkg, or ninja symlink' \
  "$dispatcher"

# makepkg.conf runs the pacman that makepkg starts through sudo at OOM score 0.
makepkg_auth=$(
  bash -c 'source "$1" && printf "[%s]" "${PACMAN_AUTH[@]}"' _ \
    "$repo_root/home/dot_config/pacman/makepkg.conf"
)
[[ $makepkg_auth == '[sudo][-k][choom][-n][0][--]' ]] ||
  fail "makepkg.conf sets PACMAN_AUTH to $makepkg_auth"

print -r -- 'build memory guards: PASS'
