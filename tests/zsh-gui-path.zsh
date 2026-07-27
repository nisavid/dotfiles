#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/zsh-gui-path.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT
fixture_home=${test_dir:A}/home
fake_bin=$test_dir/bin
state_dir=$test_dir/state
mkdir -p -- "$fixture_home/.config/zsh" "$fake_bin" "$state_dir"

fail() {
  print -ru2 -- "$1"
  return 1
}

adapter_template=$repo_root/home/private_dot_local/libexec/nisavid/executable_zsh-gui-path.tmpl
agent_template=$repo_root/home/private_Library/private_LaunchAgents/io.nisavid.zsh-gui-path.plist.tmpl
activation_template=$repo_root/home/run_after_activate-zsh-gui-path.zsh.tmpl

[[ -f $adapter_template ]] || fail 'the GUI PATH adapter template must exist'
[[ -f $agent_template ]] || fail 'the GUI PATH LaunchAgent template must exist'
[[ -f $activation_template ]] || fail 'the GUI PATH activation hook must exist'

adapter=$fixture_home/.local/libexec/nisavid/zsh-gui-path
agent=$fixture_home/Library/LaunchAgents/io.nisavid.zsh-gui-path.plist
activation=$test_dir/activate-zsh-gui-path
mkdir -p -- "${adapter:h}" "${agent:h}"
override='{"chezmoi":{"homeDir":"'"$fixture_home"'","os":"darwin"}}'
chezmoi -S "$repo_root/home" execute-template --override-data "$override" \
  < "$adapter_template" > "$adapter"
chezmoi -S "$repo_root/home" execute-template --override-data "$override" \
  < "$agent_template" > "$agent"
chezmoi -S "$repo_root/home" execute-template --override-data "$override" \
  < "$activation_template" > "$activation"
chmod +x "$adapter" "$activation"

grep -q '<string>io.nisavid.zsh-gui-path</string>' "$agent" ||
  fail 'the LaunchAgent must use the managed label'
grep -q '<key>LimitLoadToSessionType</key>' "$agent" ||
  fail 'the LaunchAgent must be limited to a session type'
grep -q '<string>Aqua</string>' "$agent" ||
  fail 'the LaunchAgent must be limited to Aqua'
grep -Fq "$fixture_home/.local/libexec/nisavid/zsh-gui-path" "$agent" ||
  fail 'the LaunchAgent must invoke the rendered per-user adapter'
linux_ignore=$(
  chezmoi -S "$repo_root/home" execute-template \
    --override-data '{"chezmoi":{"os":"linux"}}' \
    < "$repo_root/home/.chezmoiignore"
)
[[ $linux_ignore == *'Library/LaunchAgents/io.nisavid.zsh-gui-path.plist'* ]] ||
  fail 'non-macOS hosts must ignore the macOS LaunchAgent'
[[ $linux_ignore == *'.local/libexec/nisavid'* ]] ||
  fail 'non-macOS hosts must ignore the macOS GUI adapter directory'
darwin_ignore=$(
  chezmoi -S "$repo_root/home" execute-template \
    --override-data '{"chezmoi":{"os":"darwin"}}' \
    < "$repo_root/home/.chezmoiignore"
)
[[ $darwin_ignore != *'io.nisavid.zsh-gui-path'* ]] ||
  fail 'macOS hosts must manage the GUI adapter and LaunchAgent'
linux_activation=$(
  chezmoi -S "$repo_root/home" execute-template \
    --override-data '{"chezmoi":{"os":"linux"}}' \
    < "$activation_template"
)
[[ $linux_activation == $'#!/bin/sh\nexit 0' ]] ||
  fail 'the activation hook must be inert outside macOS'

startup=$fixture_home/.config/zsh/startup.zsh
cat > "$startup" <<'EOF'
function {
  emulate -L zsh
  [[ ${1:-} == launcher && ${2:-} == darwin* ]] || return 71
  path=(
    "$HOME/.local/lib/secret-exec/bin"
    "$HOME/.local/bin"
    "$HOME/.orbstack/bin"
    "${path[@]}"
  )
} "$@"
EOF

launchctl_log=$state_dir/launchctl.log
launchctl_path=$state_dir/path
manager_name=$state_dir/manager-name
manager_uid=$state_dir/manager-uid
print -r -- Aqua > "$manager_name"
print -r -- "$EUID" > "$manager_uid"

fake_launchctl=$fake_bin/launchctl
cat > "$fake_launchctl" <<'EOF'
#!/bin/zsh -f
set -euo pipefail
print -r -- "$*" >> "$ZSH_GUI_PATH_TEST_LOG"
case $1 in
  managername)
    cat "$ZSH_GUI_PATH_TEST_MANAGER_NAME"
    ;;
  manageruid)
    cat "$ZSH_GUI_PATH_TEST_MANAGER_UID"
    ;;
  setenv)
    [[ $2 == PATH ]]
    print -nr -- "$3" > "$ZSH_GUI_PATH_TEST_PATH"
    ;;
  getenv)
    [[ $2 == PATH ]]
    [[ -f $ZSH_GUI_PATH_TEST_PATH ]] && cat "$ZSH_GUI_PATH_TEST_PATH"
    ;;
  print)
    [[ -f "$ZSH_GUI_PATH_TEST_REGISTERED" ]]
    ;;
  bootout)
    rm -f -- "$ZSH_GUI_PATH_TEST_REGISTERED"
    ;;
  bootstrap)
    [[ ! -e "$ZSH_GUI_PATH_TEST_BOOTSTRAP_FAILURE" ]] || return 73
    : > "$ZSH_GUI_PATH_TEST_REGISTERED"
    ;;
  *)
    return 72
    ;;
esac
EOF
chmod +x "$fake_launchctl"

export ZSH_GUI_PATH_LAUNCHCTL_BIN=$fake_launchctl
export ZSH_GUI_PATH_STARTUP_FILE=$startup
export ZSH_GUI_PATH_TEST_LOG=$launchctl_log
export ZSH_GUI_PATH_TEST_PATH=$launchctl_path
export ZSH_GUI_PATH_TEST_MANAGER_NAME=$manager_name
export ZSH_GUI_PATH_TEST_MANAGER_UID=$manager_uid
export ZSH_GUI_PATH_TEST_REGISTERED=$state_dir/registered
export ZSH_GUI_PATH_TEST_BOOTSTRAP_FAILURE=$state_dir/bootstrap-failure
export HOME=$fixture_home

"$adapter"
expected_path="$fixture_home/.local/lib/secret-exec/bin:$fixture_home/.local/bin:$fixture_home/.orbstack/bin:/usr/bin:/bin:/usr/sbin:/sbin"
[[ $(<"$launchctl_path") == "$expected_path" ]] ||
  fail 'the adapter must install the core launcher PATH into the Aqua session'
grep -Fqx "setenv PATH $expected_path" "$launchctl_log" ||
  fail 'the adapter must set PATH through launchctl'
grep -Fqx 'getenv PATH' "$launchctl_log" ||
  fail 'the adapter must verify the stored launchd PATH'

: > "$launchctl_log"
print -r -- Background > "$manager_name"
rm -f -- "$launchctl_path"
non_aqua_output=$("$adapter" 2>&1)
[[ ! -e $launchctl_path ]] ||
  fail 'a non-Aqua adapter invocation must not mutate launchd PATH'
[[ $(<"$launchctl_log") == managername ]] ||
  fail 'a non-Aqua adapter invocation must stop after session classification'
[[ $non_aqua_output == *'deferring until GUI login'* ]] ||
  fail 'a non-Aqua adapter invocation must explain its deferral'

print -r -- Aqua > "$manager_name"
print -r -- "$(( EUID + 1 ))" > "$manager_uid"
: > "$launchctl_log"
set +e
"$adapter" >/dev/null 2>&1
mismatched_uid_status=$?
set -e
(( mismatched_uid_status != 0 )) ||
  fail 'the adapter must reject another user session'
[[ ! -e $launchctl_path ]] ||
  fail 'a mismatched session user must not receive a PATH'
[[ $(<"$launchctl_log") == $'managername\nmanageruid' ]] ||
  fail 'the adapter must stop before mutation after a session-user mismatch'

print -r -- "$EUID" > "$manager_uid"
mv "$startup" "$startup.missing"
set +e
"$adapter" >/dev/null 2>&1
missing_status=$?
set -e
(( missing_status != 0 )) ||
  fail 'the adapter must fail when the shared startup policy is unavailable'
mv "$startup.missing" "$startup"

: > "$launchctl_log"
rm -f -- "$ZSH_GUI_PATH_TEST_REGISTERED"
: > "$ZSH_GUI_PATH_TEST_BOOTSTRAP_FAILURE"
set +e
"$activation" >/dev/null 2>&1
bootstrap_failure_status=$?
set -e
(( bootstrap_failure_status != 0 )) ||
  fail 'an initial LaunchAgent bootstrap failure must fail the apply'
[[ ! -e $ZSH_GUI_PATH_TEST_REGISTERED ]] ||
  fail 'a failed initial bootstrap must not claim a registered LaunchAgent'
rm -f -- "$ZSH_GUI_PATH_TEST_BOOTSTRAP_FAILURE"
: > "$launchctl_log"
"$activation"
grep -Fqx "bootstrap gui/$EUID $fixture_home/Library/LaunchAgents/io.nisavid.zsh-gui-path.plist" "$launchctl_log" ||
  fail 'the activation hook must bootstrap only the current user GUI domain'
[[ -e $ZSH_GUI_PATH_TEST_REGISTERED ]] ||
  fail 'the activation hook must leave the LaunchAgent registered'
[[ $(<"$launchctl_path") == "$expected_path" ]] ||
  fail 'the activation hook must install the current GUI-session PATH'

: > "$launchctl_log"
cat > "$startup" <<'EOF'
function {
  emulate -L zsh
  [[ ${1:-} == launcher && ${2:-} == darwin* ]] || return 71
  path=(
    "$HOME/.local/lib/secret-exec/bin"
    "$HOME/.local/bin"
    "$HOME/.new-core/bin"
    "$HOME/.orbstack/bin"
    "${path[@]}"
  )
} "$@"
EOF
: > "$ZSH_GUI_PATH_TEST_BOOTSTRAP_FAILURE"
"$activation"
[[ -e $ZSH_GUI_PATH_TEST_REGISTERED ]] ||
  fail 'the next apply must preserve an existing LaunchAgent registration'
if grep -Fq 'bootout ' "$launchctl_log" ||
  grep -Fq 'bootstrap ' "$launchctl_log"; then
  fail 'the next apply must not replace a working LaunchAgent registration'
fi
expected_refreshed_path="$fixture_home/.local/lib/secret-exec/bin:$fixture_home/.local/bin:$fixture_home/.new-core/bin:$fixture_home/.orbstack/bin:/usr/bin:/bin:/usr/sbin:/sbin"
[[ $(<"$launchctl_path") == "$expected_refreshed_path" ]] ||
  fail 'the next apply must refresh launchd PATH from the current external startup policy'
rm -f -- "$ZSH_GUI_PATH_TEST_BOOTSTRAP_FAILURE"

print -r -- Background > "$manager_name"
: > "$launchctl_log"
non_aqua_activation_output=$("$activation" 2>&1)
[[ $(<"$launchctl_log") == managername ]] ||
  fail 'a non-Aqua apply must defer activation without touching a launchd domain'
[[ $non_aqua_activation_output == *'next GUI login'* ]] ||
  fail 'a non-Aqua apply must explain when registration resumes'

print -r -- 'zsh GUI PATH checks passed'
