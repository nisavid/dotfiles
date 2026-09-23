#!/usr/bin/env zsh
# Exercise the ninja shim against fake systemd-run, systemctl, choom, and ninja
# binaries.
emulate -L zsh
setopt errexit nounset pipefail

repo_root=${0:A:h:h}
shim_source=$repo_root/home/private_dot_local/bin/executable_ninja
test_root=$(mktemp -d "${TMPDIR:-/tmp}/build-memory-guards.XXXXXX")
trap 'rm -rf -- "$test_root"' EXIT HUP INT TERM

fail() {
  print -u2 -r -- "FAIL: $*"
  return 1
}

sh -n "$shim_source" || fail 'ninja shim has a syntax error'

bin=$test_root/bin
runtime=$test_root/runtime
log=$test_root/log
err=$test_root/err
cgroup=$test_root/cgroup
oom=$test_root/oom_score_adj
shim=$test_root/ninja
mkdir -m 700 -p "$bin" "$runtime/systemd"

sed \
  -e "s#^ninja=/usr/bin/ninja\$#ninja=$bin/ninja#" \
  -e "s#^systemd_run=/usr/bin/systemd-run\$#systemd_run=$bin/systemd-run#" \
  -e "s#^systemctl=/usr/bin/systemctl\$#systemctl=$bin/systemctl#" \
  -e "s#^choom=/usr/bin/choom\$#choom=$bin/choom#" \
  -e "s#^self_cgroup=/proc/self/cgroup\$#self_cgroup=$cgroup#" \
  -e "s#^self_oom_score_adj=/proc/self/oom_score_adj\$#self_oom_score_adj=$oom#" \
  "$shim_source" >"$shim"
for fixture in "$bin/ninja" "$bin/systemd-run" "$bin/systemctl" "$bin/choom" "$cgroup" "$oom"; do
  grep -Fq -- "=$fixture" "$shim" || fail "shim fixture path was not substituted: $fixture"
done
chmod 700 "$shim"

cat >"$bin/ninja" <<'EOF'
#!/bin/sh
{
  printf 'ninja'
  printf ' [%s]' "$@"
  printf '\n'
  if [ -n "${LD_PRELOAD+set}" ]; then
    printf 'ninja LD_PRELOAD=[%s]\n' "$LD_PRELOAD"
  else
    printf 'ninja LD_PRELOAD unset\n'
  fi
  printf 'ninja MARKER=[%s]\n' "${MARKER-}"
} >>"$FAKE_LOG"
exit "${FAKE_NINJA_STATUS:-0}"
EOF
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
# Answers the shim's FragmentPath query like the user manager, or fails like
# systemctl does when the manager refuses the caller.
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
chmod 700 "$bin/ninja" "$bin/systemd-run" "$bin/systemctl" "$bin/choom"

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
ninja_args=(-C 'dir with space' 'target$HOME' '${MARKER}' '$$' '%h')
bracketed_args='[-C] [dir with space] [target$HOME] [${MARKER}] [$$] [%h]'

# Run the shim with a minimal environment. Callers pass extra NAME=value pairs.
run_shim() {
  local rc=0
  : >"$log"
  env -i PATH=/usr/bin:/bin FAKE_LOG="$log" MARKER=kept "$@" \
    "$shim" "${ninja_args[@]}" 2>"$err" || rc=$?
  return $rc
}

expect_log() {
  local expected=$1 description=$2
  [[ $(<"$log") == "$expected" ]] || {
    print -u2 -rl -- "--- expected ($description)" "$expected" '--- actual' "$(<"$log")"
    fail "$description"
  }
}

# The shim asks the user manager for the slice's unit file without LD_PRELOAD.
probe_log() {
  print -r -- 'systemctl [--user] [show] [-P] [FragmentPath] [builds.slice]'
  print -r -- 'systemctl LD_PRELOAD unset'
}

# Expected log of a scoped run. A second argument is the caller's LD_PRELOAD.
scoped_log() {
  local adj=$1 restore='' ninja_preload='ninja LD_PRELOAD unset'
  if (( $# > 1 )); then
    restore="[/usr/bin/env] [LD_PRELOAD=$2] "
    ninja_preload="ninja LD_PRELOAD=[$2]"
  fi
  probe_log
  print -r -- \
    "systemd-run [--user] [--scope] [--quiet] [--collect] [--expand-environment=no] [--slice=builds.slice] [--] ${restore}[$bin/choom] [-n] [$adj] [--] [$bin/ninja] $bracketed_args"
  print -r -- 'systemd-run LD_PRELOAD unset'
  print -r -- "choom [-n] [$adj] [--] [$bin/ninja] $bracketed_args"
  print -r -- "ninja $bracketed_args"
  print -r -- "$ninja_preload"
  print -r -- 'ninja MARKER=[kept]'
}

# Expected log of Ninja run directly. An argument is the caller's LD_PRELOAD.
direct_log() {
  print -r -- "ninja $bracketed_args"
  if (( $# )); then
    print -r -- "ninja LD_PRELOAD=[$1]"
  else
    print -r -- 'ninja LD_PRELOAD unset'
  fi
  print -r -- 'ninja MARKER=[kept]'
}

# Scoped run: exact argv, literal "$" and "%", environment, and status.
print -r -- "$outside_slice" >"$cgroup"
print -r -- 200 >"$oom"
run_shim XDG_RUNTIME_DIR="$runtime" || fail 'scoped run failed'
expect_log "$(scoped_log 500)" 'scoped run passes exact arguments through systemd-run and choom'
[[ ! -s $err ]] || fail "scoped run wrote to stderr: $(<"$err")"

rc=0
run_shim XDG_RUNTIME_DIR="$runtime" FAKE_NINJA_STATUS=3 || rc=$?
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
print -r -- "$outside_slice" >"$cgroup"

# Fallbacks warn exactly once, run Ninja directly, and keep its status. The
# third argument is the expected log.
expect_fallback() {
  local description=$1 reason=$2 expected=$3
  shift 3
  local rc=0
  run_shim FAKE_NINJA_STATUS=5 "$@" || rc=$?
  (( rc == 5 )) || fail "$description returned $rc instead of Ninja's 5"
  expect_log "$expected" "$description runs Ninja directly"
  [[ $(wc -l <"$err") -eq 1 ]] || fail "$description did not warn exactly once: $(<"$err")"
  grep -Fq -- "ninja: warning: $reason; running $bin/ninja without the builds.slice memory cap" "$err" ||
    fail "$description warning is wrong: $(<"$err")"
}

unreachable='the systemd user manager is unreachable'
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

print -r -- 'build memory guards: PASS'
