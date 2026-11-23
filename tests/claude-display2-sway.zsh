#!/usr/bin/env zsh
# Check the headless sway display for Claude Desktop computer use: the user
# unit's contract, the link helper's guard, and the script that enables the
# unit. The helper and the script run against scratch directories and a fake
# systemctl, so this test runs on every platform and touches no real unit.
set -euo pipefail

repo_root=${0:A:h:h}
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/claude-display2-sway.XXXXXX")
test_dir=${test_dir:A}
trap 'rm -rf -- "$test_dir"' EXIT HUP INT TERM

# zsh skips EXIT traps when errexit fires inside a function.
TRAPZERR() {
  if [[ -o errexit ]] && (( ZSH_SUBSHELL == 0 && ${#funcstack} > 1 )); then
    rm -rf -- "$test_dir"
  fi
}

# exit, not return: errexit inside a function skips zsh's EXIT trap.
fail() {
  print -ru2 -- "FAIL: $*"
  exit 1
}

assert_line() {
  local line=$1 file=$2
  grep -Fqx -- "$line" "$file" || fail "missing line in ${file:t}: $line"
}

unit_source=$repo_root/home/dot_config/systemd/user/claude-display2-sway.service
sway_config=$repo_root/home/dot_config/claude-display2-sway/config
helper=$repo_root/home/private_dot_local/bin/executable_claude-display2-link
enable_template=$repo_root/home/run_onchange_after_enable-claude-display2-sway.sh.tmpl

# The unit.
[[ -f $unit_source ]] || fail 'the claude-display2-sway user unit must be managed'
for line in \
  'After=graphical-session.target' \
  'PartOf=graphical-session.target' \
  'WantedBy=graphical-session.target' \
  'Restart=on-failure' \
  'RuntimeDirectory=claude-display2' \
  'RuntimeDirectoryMode=0700' \
  'Environment=XDG_RUNTIME_DIR=%t/claude-display2' \
  'Environment=WLR_BACKENDS=headless' \
  'Environment=WLR_RENDERER=pixman' \
  'Environment=WLR_LIBINPUT_NO_DEVICES=1' \
  'UnsetEnvironment=WAYLAND_DISPLAY DISPLAY' \
  'ExecStart=sway --config %h/.config/claude-display2-sway/config' \
  'ExecStartPost=%h/.local/bin/claude-display2-link link %t/claude-display2 %t/wayland-2' \
  'ExecStopPost=%h/.local/bin/claude-display2-link unlink %t/claude-display2 %t/wayland-2'
do
  assert_line "$line" "$unit_source"
done
# A unit-level WAYLAND_DISPLAY or DISPLAY would point sway at the session
# compositor instead of the headless backend.
if grep -Eq '^Environment=(.*[[:space:]])?(WAYLAND_DISPLAY|DISPLAY)=' "$unit_source"; then
  fail 'the unit must not set WAYLAND_DISPLAY or DISPLAY'
fi

# The sway config. sway's default config includes /etc/sway/config.d, whose
# systemd snippet exports this sway's display and XDG_CURRENT_DESKTOP into the
# session's user manager and D-Bus activation environment, and starts a bar.
# The dedicated config may hold only the directives the headless display
# needs, so nothing in it can include files or start programs. Comments and
# blank lines aside, its lines, with whitespace normalized, must be exactly
# these.
[[ -f $sway_config ]] || fail 'the claude-display2-sway sway config must be managed'
expected_config_directives=$(
  printf '%s\n' 'output * resolution 1600x900' 'xwayland disable' | LC_ALL=C sort
)
config_directives=$(
  awk '
    { sub(/^[[:space:]]+/, ""); sub(/[[:space:]]+$/, ""); gsub(/[[:space:]]+/, " ") }
    /^#/ || $0 == "" { next }
    { print }
  ' "$sway_config" | LC_ALL=C sort
)
[[ $config_directives == "$expected_config_directives" ]] ||
  fail "the sway config may only hold the directives 'xwayland disable' and 'output * resolution 1600x900', and must not include files or start programs; it holds:"$'\n'"$config_directives"

# The link helper. Each case gets its own shared runtime directory, with the
# private directory sway would use inside it, as the unit lays them out.
helper_status=0
run_helper() {
  emulate -L zsh
  helper_status=0
  CLAUDE_DISPLAY2_SOCKET_TIMEOUT=${socket_timeout:-1} \
    /bin/sh "$helper" "$@" >"$test_dir/helper.out" 2>"$test_dir/helper.err" ||
    helper_status=$?
}

# Bind a Unix socket at a path. The socket file outlives the process, which is
# all the helper checks. Binding a relative name keeps the path inside the
# platform's socket path limit.
make_socket() {
  emulate -L zsh
  python3 -c '
import os, socket, sys
os.chdir(sys.argv[1])
socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).bind(sys.argv[2])
' "${1:h}" "${1:t}"
}

integer case_number=0
new_case() {
  emulate -L zsh
  (( case_number += 1 ))
  runtime=$test_dir/case-$case_number
  private=$runtime/claude-display2
  link=$runtime/wayland-2
  mkdir -p -m 0700 -- "$private"
  make_socket "$private/wayland-1"
  # Lock files and other names beside the socket must not be taken for it.
  : >"$private/wayland-1.lock"
  : >"$private/wayland-9"
}

# Absent: the helper creates the link.
new_case
run_helper link "$private" "$link"
(( helper_status == 0 )) || fail "link with the path absent failed: $(<"$test_dir/helper.err")"
[[ -L $link && $(readlink -- "$link") == "$private/wayland-1" ]] ||
  fail 'link with the path absent did not point wayland-2 at the private socket'
run_helper unlink "$private" "$link"
(( helper_status == 0 )) || fail 'unlink of an own link failed'
[[ ! -e $link && ! -L $link ]] || fail 'unlink did not remove an own link'
run_helper unlink "$private" "$link"
(( helper_status == 0 )) || fail 'unlink with the path absent failed'

# Absent at the check, present when ln runs: a stub ln plants a regular file at
# the link path just before running the real ln, and link must leave it.
race_bin=$test_dir/race-bin
mkdir -p -- "$race_bin"
print -r -- '#!/bin/sh
for last; do :; done
printf "%s\n" raced >"$last"
exec '"${commands[ln]}"' "$@"' >"$race_bin/ln"
chmod 700 "$race_bin/ln"
new_case
PATH="$race_bin:$PATH" run_helper link "$private" "$link"
(( helper_status != 0 )) || fail 'link replaced a file that appeared after its check'
[[ -f $link && ! -L $link && $(<"$link") == raced ]] ||
  fail 'link disturbed a file that appeared after its check'
grep -Fq "could not create $link" "$test_dir/helper.err" ||
  fail 'link did not explain refusing a file that appeared after its check'

# Own link: a stale link from an earlier run is replaced and later removed.
new_case
ln -s -- "$private/wayland-7" "$link"
run_helper link "$private" "$link"
(( helper_status == 0 )) || fail "link over an own link failed: $(<"$test_dir/helper.err")"
[[ -L $link && $(readlink -- "$link") == "$private/wayland-1" ]] ||
  fail 'link did not replace an own stale link'
[[ $(<"$test_dir/helper.err") != *foreign* ]] ||
  fail 'link reported an own link as foreign'
run_helper unlink "$private" "$link"
[[ ! -e $link && ! -L $link ]] || fail 'unlink did not remove an own link'

# Foreign link: start replaces it, because it is a symlink, and says so; stop
# leaves a foreign link alone, because it is not ours.
new_case
foreign_target=$runtime/elsewhere/wayland-0
ln -s -- "$foreign_target" "$link"
run_helper link "$private" "$link"
(( helper_status == 0 )) || fail "link over a foreign link failed: $(<"$test_dir/helper.err")"
[[ -L $link && $(readlink -- "$link") == "$private/wayland-1" ]] ||
  fail 'link did not replace a foreign symlink'
grep -Fq "replacing the foreign symlink $link -> $foreign_target" "$test_dir/helper.err" ||
  fail 'link did not report the foreign symlink it replaced'
rm -- "$link"
for foreign_target in \
  "$runtime/elsewhere/wayland-0" \
  "${private}-other/wayland-1" \
  "$private/nested/wayland-1" \
  "$private"; do
  ln -s -- "$foreign_target" "$link"
  run_helper unlink "$private" "$link"
  (( helper_status == 0 )) || fail "unlink of a foreign link failed: $foreign_target"
  [[ -L $link && $(readlink -- "$link") == "$foreign_target" ]] ||
    fail "unlink removed a foreign link: $foreign_target"
  grep -Fq 'leaving' "$test_dir/helper.err" ||
    fail "unlink did not report leaving a foreign link: $foreign_target"
  rm -- "$link"
done

# Real socket, and real file: link refuses loudly and leaves them untouched;
# unlink leaves them too.
new_case
make_socket "$link"
run_helper link "$private" "$link"
(( helper_status != 0 )) || fail 'link replaced a real socket'
[[ -S $link && ! -L $link ]] || fail 'link disturbed a real socket'
grep -Fq "$link exists and is not a symlink" "$test_dir/helper.err" ||
  fail 'link did not explain refusing a real socket'
run_helper unlink "$private" "$link"
(( helper_status == 0 )) || fail 'unlink with a real socket failed'
[[ -S $link && ! -L $link ]] || fail 'unlink removed a real socket'
rm -- "$link"
print -r -- sentinel >"$link"
run_helper link "$private" "$link"
(( helper_status != 0 )) || fail 'link replaced a regular file'
[[ -f $link && ! -L $link && $(<"$link") == sentinel ]] ||
  fail 'link disturbed a regular file'
mkdir -- "$runtime/directory-link"
run_helper link "$private" "$runtime/directory-link"
(( helper_status != 0 )) || fail 'link accepted a directory'
[[ -z $(ls -A -- "$runtime/directory-link") ]] ||
  fail 'link wrote into a directory'

# The wait is bounded, waits for a socket that appears late, and refuses to
# guess between two sockets.
new_case
rm -- "$private/wayland-1"
socket_timeout=0 run_helper link "$private" "$link"
(( helper_status != 0 )) || fail 'link succeeded with no socket'
grep -Fq 'no Wayland socket appeared' "$test_dir/helper.err" ||
  fail 'link did not report a missing socket'
[[ ! -e $link && ! -L $link ]] || fail 'link created a link with no socket'
( sleep 0.5; make_socket "$private/wayland-3" ) &
late_socket=$!
socket_timeout=10 run_helper link "$private" "$link"
wait $late_socket
(( helper_status == 0 )) || fail "link did not wait for a late socket: $(<"$test_dir/helper.err")"
[[ $(readlink -- "$link") == "$private/wayland-3" ]] ||
  fail 'link did not link the late socket'
make_socket "$private/wayland-4"
rm -- "$link"
run_helper link "$private" "$link"
(( helper_status != 0 )) || fail 'link chose between two sockets'
grep -Fq 'more than one Wayland socket' "$test_dir/helper.err" ||
  fail 'link did not report two sockets'
grep -Fq 'no Wayland socket appeared' "$test_dir/helper.err" &&
  fail 'link waited out its bound instead of stopping at two sockets'
socket_timeout=x run_helper link "$private" "$link"
(( helper_status != 0 )) || fail 'link accepted a malformed timeout'
run_helper link relative "$link"
(( helper_status != 0 )) || fail 'link accepted a relative private directory'

# A trailing slash on the private directory changes neither the link target
# nor what unlink counts as ours. A relative link path is refused.
new_case
(cd -- "$runtime" && run_helper link "$private" wayland-2 &&
  print -r -- "$helper_status" >"$test_dir/relative-status")
[[ $(<"$test_dir/relative-status") != 0 ]] || fail 'link accepted a relative link path'
[[ ! -e $link && ! -L $link ]] || fail 'link created a relative link'
run_helper link "$private/" "$link"
(( helper_status == 0 )) || fail "link with a trailing slash failed: $(<"$test_dir/helper.err")"
[[ $(readlink -- "$link") == "$private/wayland-1" ]] ||
  fail 'link with a trailing slash did not point at the private socket'
run_helper unlink "$private/" "$link"
[[ ! -e $link && ! -L $link ]] ||
  fail 'unlink with a trailing slash did not remove an own link'
run_helper sideways "$private" "$link"
(( helper_status == 64 )) || fail 'an unknown command must exit 64'

# The enabling script.
render_enable() {
  emulate -L zsh
  chezmoi -S "$repo_root/home" execute-template \
    --override-data "{\"chezmoi\":{\"os\":\"$1\"}}" <"$enable_template"
}
[[ $(render_enable darwin) == $'#!/bin/sh\nexit 0' ]] ||
  fail 'the enabling script must be inert outside Linux'

# Fake systemctl and sway on PATH, both at template time (lookPath) and at run
# time. The fake records each call and fails show-environment on request.
fake_bin=$test_dir/fake-bin
mkdir -p -- "$fake_bin" "$test_dir/empty-bin"
print -r -- '#!/bin/sh
printf "%s\n" "$*" >>"$SYSTEMCTL_LOG"
case "$*" in
  "--user show-environment") [ -z "${MANAGER_DOWN:-}" ] ;;
esac' >"$fake_bin/systemctl"
print -r -- '#!/bin/sh' >"$fake_bin/sway"
chmod 700 "$fake_bin/systemctl" "$fake_bin/sway"
chezmoi_bin=${commands[chezmoi]}
enable_script=$test_dir/enable-claude-display2-sway.sh
PATH="$fake_bin:$PATH" XDG_RUNTIME_DIR= "$chezmoi_bin" -S "$repo_root/home" execute-template \
  --override-data '{"chezmoi":{"os":"linux"}}' <"$enable_template" >"$enable_script"
for source_path in \
  dot_config/systemd/user/claude-display2-sway.service \
  dot_config/claude-display2-sway/config \
  private_dot_local/bin/executable_claude-display2-link; do
  digest=$(chezmoi -S "$repo_root/home" execute-template \
    "{{ include \"$source_path\" | sha256sum }}")
  grep -Fq -- "$digest" "$enable_script" ||
    fail "the enabling script must rerun when $source_path changes"
done
grep -Fqx -- "# systemctl: ${fake_bin:A}/systemctl" "$enable_script" ||
  fail 'the enabling script must rerun when systemctl appears'
grep -Fqx -- '# user manager: unreachable' "$enable_script" ||
  fail 'the enabling script must record an unreachable user manager'
manager_runtime=$test_dir/manager-runtime
mkdir -p -- "$manager_runtime/systemd"
: >"$manager_runtime/systemd/private"
reachable_script=$test_dir/enable-reachable.sh
PATH="$fake_bin:$PATH" XDG_RUNTIME_DIR=$manager_runtime "$chezmoi_bin" -S "$repo_root/home" \
  execute-template --override-data '{"chezmoi":{"os":"linux"}}' <"$enable_template" \
  >"$reachable_script"
grep -Fqx -- '# user manager: reachable' "$reachable_script" ||
  fail 'the enabling script must rerun when the user manager becomes reachable'
/bin/sh -n "$enable_script" || fail 'the rendered enabling script does not parse'
/bin/sh -n "$reachable_script" || fail 'the rendered enabling script does not parse'

SYSTEMCTL_LOG=$test_dir/systemctl.log PATH="$fake_bin:/usr/bin:/bin" \
  /bin/sh "$enable_script"
[[ $(<"$test_dir/systemctl.log") == $'--user show-environment\n--user daemon-reload\n--user enable --now claude-display2-sway.service' ]] ||
  fail "the enabling script did not reload and enable the unit: $(<"$test_dir/systemctl.log")"

: >"$test_dir/systemctl.log"
MANAGER_DOWN=1 SYSTEMCTL_LOG=$test_dir/systemctl.log PATH="$fake_bin:/usr/bin:/bin" \
  /bin/sh "$enable_script" 2>"$test_dir/enable.err" ||
  fail 'the enabling script failed with the user manager unreachable'
[[ $(<"$test_dir/systemctl.log") == '--user show-environment' ]] ||
  fail 'the enabling script acted with the user manager unreachable'
grep -Fq 'the user service manager is unreachable' "$test_dir/enable.err" ||
  fail 'the enabling script did not report an unreachable user manager'

# A manager that was reachable as the apply began but does not answer now must
# fail the run, so chezmoi retries it, rather than skip and record it as done.
: >"$test_dir/systemctl.log"
reachable_status=0
MANAGER_DOWN=1 SYSTEMCTL_LOG=$test_dir/systemctl.log PATH="$fake_bin:/usr/bin:/bin" \
  /bin/sh "$reachable_script" 2>"$test_dir/enable.err" || reachable_status=$?
(( reachable_status != 0 )) ||
  fail 'the enabling script skipped when the expected user manager did not answer'
[[ $(<"$test_dir/systemctl.log") == '--user show-environment' ]] ||
  fail 'the enabling script acted when the expected user manager did not answer'
grep -Fq 'the next apply will retry' "$test_dir/enable.err" ||
  fail 'the enabling script did not explain failing on a silent user manager'
: >"$test_dir/systemctl.log"
SYSTEMCTL_LOG=$test_dir/systemctl.log PATH="$fake_bin:/usr/bin:/bin" \
  /bin/sh "$reachable_script"
[[ $(<"$test_dir/systemctl.log") == $'--user show-environment\n--user daemon-reload\n--user enable --now claude-display2-sway.service' ]] ||
  fail "the enabling script did not reload and enable the unit: $(<"$test_dir/systemctl.log")"

for missing in systemctl sway; do
  partial_bin=$test_dir/without-$missing
  mkdir -p -- "$partial_bin"
  for tool in systemctl sway; do
    [[ $tool == $missing ]] || ln -s -- "$fake_bin/$tool" "$partial_bin/$tool"
  done
  for tool in sh printf; do
    ln -s -- "${commands[$tool]}" "$partial_bin/$tool"
  done
  : >"$test_dir/systemctl.log"
  SYSTEMCTL_LOG=$test_dir/systemctl.log PATH=$partial_bin \
    /bin/sh "$enable_script" 2>"$test_dir/enable.err" ||
    fail "the enabling script failed without $missing"
  [[ ! -s $test_dir/systemctl.log ]] ||
    fail "the enabling script called systemctl without $missing"
  grep -Fq "$missing is unavailable on PATH" "$test_dir/enable.err" ||
    fail "the enabling script did not report a missing $missing"
done

print -r -- 'claude-display2-sway checks passed'
