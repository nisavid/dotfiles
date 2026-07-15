#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
cd "$repo_root"

fail() {
  print -u2 -r -- "$1"
  return 1
}

command -v rg >/dev/null || fail 'rg is required to validate the install boundary'

test_dir=$(mktemp -d "${TMPDIR:-/tmp}/mlxctl-install.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT

fixture_home=$test_dir/home
fixture_home=${fixture_home:A}
source_dir=$fixture_home/src/nisavid/systools/tools/mlxctl
fake_bin=$test_dir/bin
empty_bin=$test_dir/empty-bin
fake_uv=$fake_bin/uv
fake_launchctl=$fake_bin/launchctl
uv_log=$test_dir/uv.log
launchctl_log=$test_dir/launchctl.log
hook=$test_dir/install-mlxctl.zsh
linux_hook=$test_dir/linux-hook.zsh

mkdir -p -- "$empty_bin" "$fake_bin" "$source_dir"
print -r -- '[project]' > "$source_dir/pyproject.toml"

{
  print -r -- '#!/usr/bin/env zsh'
  print -r -- 'set -eu'
  print -r -- 'print -r -- "$*" >> "$MLXCTL_TEST_UV_LOG"'
  print -r -- '[[ $UV_TOOL_BIN_DIR == "$MLXCTL_TEST_BIN_DIR" ]] || exit 65'
  print -r -- '[[ "$*" == "tool install --force $MLXCTL_TEST_SOURCE_DIR" ]] || exit 64'
  print -r -- '[[ ${MLXCTL_TEST_UV_SKIP_BINARY:-0} == 1 ]] && exit 0'
  print -r -- 'mkdir -p -- "$MLXCTL_TEST_BIN_DIR"'
  print -r -- ': > "$MLXCTL_TEST_BIN_DIR/mlxctl"'
  print -r -- 'chmod +x "$MLXCTL_TEST_BIN_DIR/mlxctl"'
} > "$fake_uv"
chmod +x "$fake_uv"

{
  print -r -- '#!/usr/bin/env zsh'
  print -r -- 'set -eu'
  print -r -- 'print -r -- "$*" >> "$MLXCTL_TEST_LAUNCHCTL_LOG"'
  print -r -- '[[ $1 == print && $2 == gui/$EUID/io.nisavid.mlxd ]] || exit 64'
  print -r -- 'case ${MLXCTL_TEST_LAUNCHCTL_STATE:-inactive} in'
  print -r -- '  unregistered) exit 113 ;;'
  print -r -- '  running) print -r -- $'"'"'\tstate = running'"'"' ;;'
  print -r -- '  inactive) print -r -- $'"'"'\tstate = waiting\n\tstatus = state = running\n\tstate = running-later'"'"' ;;'
  print -r -- '  *) exit 65 ;;'
  print -r -- 'esac'
} > "$fake_launchctl"
chmod +x "$fake_launchctl"
export MLXCTL_TEST_LAUNCHCTL_BIN=$fake_launchctl
export MLXCTL_TEST_LAUNCHCTL_LOG=$launchctl_log
export MLXCTL_TEST_LAUNCHCTL_STATE=inactive

darwin_data='{"chezmoi":{"os":"darwin","homeDir":"'${fixture_home}'"},"mlxctl":{"sourceDir":"src/nisavid/systools/tools/mlxctl","binDir":".local/bin"}}'
linux_data='{"chezmoi":{"os":"linux","homeDir":"'${fixture_home}'"},"mlxctl":{"sourceDir":"src/nisavid/systools/tools/mlxctl","binDir":".local/bin"}}'

chezmoi execute-template --override-data "$darwin_data" \
  < home/run_after_install-mlxctl.sh.tmpl > "$hook"
chezmoi execute-template --override-data "$linux_data" \
  < home/run_after_install-mlxctl.sh.tmpl > "$linux_hook"

zsh -n "$hook"
chmod +x "$hook"
[[ $(head -c 2 "$hook") == '#!' ]] || fail 'install hook shebang must start at byte zero'
[[ ! -s "$linux_hook" ]] || fail 'install hook must render empty outside macOS'

legacy_plist=$fixture_home/Library/LaunchAgents/io.nisavid.mlxd.plist
legacy_config=$fixture_home/.config/mlxd/config.toml
legacy_state=$fixture_home/.local/state/mlxd/state.db
legacy_log=$fixture_home/Library/Logs/mlxd/mlxd.log
legacy_model=$fixture_home/.local/share/mlxd/models/qwen36-optiq/kv_config.json
mkdir -p -- "${legacy_plist:h}" "${legacy_config:h}" "${legacy_state:h}" \
  "${legacy_log:h}" "${legacy_model:h}"
print -r -- 'legacy plist' > "$legacy_plist"
print -r -- 'legacy config' > "$legacy_config"
print -r -- 'legacy state' > "$legacy_state"
print -r -- 'legacy log' > "$legacy_log"
print -r -- 'legacy model' > "$legacy_model"

if ! PATH="$fake_bin:$PATH" \
  ZDOTDIR=$test_dir \
  MLXCTL_TEST_BIN_DIR=$fixture_home/.local/bin \
  MLXCTL_TEST_SOURCE_DIR=$source_dir \
  MLXCTL_TEST_UV_LOG=$uv_log \
    "$hook" > "$test_dir/hook.stdout" 2> "$test_dir/hook.stderr"; then
  fail "install hook failed: $(<"$test_dir/hook.stderr")"
fi

[[ $(<"$uv_log") == "tool install --force $source_dir" ]] || \
  fail 'install hook must run only the local mlxctl tool installation'
[[ -x "$fixture_home/.local/bin/mlxctl" ]] || fail 'install hook did not install mlxctl'
grep -q 'installed .*mlxctl' "$test_dir/hook.stdout" || fail 'install result must be explicit'

[[ $(<"$legacy_plist") == 'legacy plist' ]] || fail 'install changed the legacy LaunchAgent'
[[ $(<"$legacy_config") == 'legacy config' ]] || fail 'install changed legacy config'
[[ $(<"$legacy_state") == 'legacy state' ]] || fail 'install changed legacy state'
[[ $(<"$legacy_log") == 'legacy log' ]] || fail 'install changed legacy logs'
[[ $(<"$legacy_model") == 'legacy model' ]] || fail 'install changed legacy model data'

uv_before=$(<"$uv_log")
running_status=0
MLXCTL_TEST_LAUNCHCTL_STATE=running \
  PATH="$fake_bin:$PATH" \
  ZDOTDIR=$test_dir \
  MLXCTL_TEST_BIN_DIR=$fixture_home/.local/bin \
  MLXCTL_TEST_SOURCE_DIR=$source_dir \
  MLXCTL_TEST_UV_LOG=$uv_log \
    "$hook" > "$test_dir/running.stdout" 2> "$test_dir/running.stderr" || \
  running_status=$?
[[ $running_status == 1 ]] || \
  fail "running legacy daemon hook exited $running_status instead of 1"
[[ $(<"$uv_log") == "$uv_before" ]] || \
  fail 'running legacy daemon refusal must precede uv'
grep -q 'legacy LaunchAgent .* is running; stop it before updating mlxctl' \
  "$test_dir/running.stderr" || \
  fail 'running legacy daemon refusal must explain the migration prerequisite'
[[ $(<"$legacy_plist") == 'legacy plist' ]] || fail 'running refusal changed the legacy LaunchAgent'
[[ $(<"$legacy_config") == 'legacy config' ]] || fail 'running refusal changed legacy config'
[[ $(<"$legacy_state") == 'legacy state' ]] || fail 'running refusal changed legacy state'
[[ $(<"$legacy_log") == 'legacy log' ]] || fail 'running refusal changed legacy logs'
[[ $(<"$legacy_model") == 'legacy model' ]] || fail 'running refusal changed legacy model data'

rm -rf -- "$source_dir"
uv_before=$(<"$uv_log")
if ! PATH="$fake_bin:$PATH" \
  ZDOTDIR=$test_dir \
  MLXCTL_TEST_BIN_DIR=$fixture_home/.local/bin \
  MLXCTL_TEST_SOURCE_DIR=$source_dir \
  MLXCTL_TEST_UV_LOG=$uv_log \
    "$hook" > "$test_dir/missing.stdout" 2> "$test_dir/missing.stderr"; then
  fail "missing-source hook failed: $(<"$test_dir/missing.stderr")"
fi
[[ $(<"$uv_log") == "$uv_before" ]] || fail 'missing source must not run uv'
grep -q 'source checkout not found' "$test_dir/missing.stderr" || \
  fail 'missing-source result must be explicit'
[[ $(<"$legacy_plist") == 'legacy plist' ]] || fail 'missing source changed the legacy LaunchAgent'

rm -f -- "$fixture_home/.local/bin/mlxctl"
mkdir -p -- "$source_dir"
uv_before=$(<"$uv_log")
if ! PATH="$fake_bin:$PATH" \
  ZDOTDIR=$test_dir \
  MLXCTL_TEST_BIN_DIR=$fixture_home/.local/bin \
  MLXCTL_TEST_SOURCE_DIR=$source_dir \
  MLXCTL_TEST_UV_LOG=$uv_log \
    "$hook" > "$test_dir/missing-project.stdout" 2> "$test_dir/missing-project.stderr"; then
  fail "missing-project hook failed: $(<"$test_dir/missing-project.stderr")"
fi
[[ $(<"$uv_log") == "$uv_before" ]] || fail 'missing project must not run uv'
grep -q 'installable project not found' "$test_dir/missing-project.stderr" || \
  fail 'missing-project result must be explicit'
[[ ! -e "$fixture_home/.local/bin/mlxctl" ]] || \
  fail 'missing-project scenario unexpectedly installed mlxctl'

print -r -- '[project]' > "$source_dir/pyproject.toml"
missing_uv_status=0
PATH="$empty_bin" \
  ZDOTDIR=$test_dir \
  MLXCTL_TEST_BIN_DIR=$fixture_home/.local/bin \
  MLXCTL_TEST_SOURCE_DIR=$source_dir \
  MLXCTL_TEST_UV_LOG=$uv_log \
    /bin/zsh "$hook" > "$test_dir/missing-uv.stdout" 2> "$test_dir/missing-uv.stderr" || \
  missing_uv_status=$?
[[ $missing_uv_status == 1 ]] || \
  fail "missing-uv hook exited $missing_uv_status instead of 1"
grep -q 'uv is required' "$test_dir/missing-uv.stderr" || \
  fail 'missing-uv result must be explicit'
[[ $(<"$uv_log") == "$uv_before" ]] || fail 'missing uv must not run an installer'
[[ ! -e "$fixture_home/.local/bin/mlxctl" ]] || \
  fail 'missing-uv scenario unexpectedly installed mlxctl'

missing_binary_status=0
MLXCTL_TEST_LAUNCHCTL_STATE=unregistered \
  PATH="$fake_bin:$PATH" \
  ZDOTDIR=$test_dir \
  MLXCTL_TEST_BIN_DIR=$fixture_home/.local/bin \
  MLXCTL_TEST_SOURCE_DIR=$source_dir \
  MLXCTL_TEST_UV_LOG=$uv_log \
  MLXCTL_TEST_UV_SKIP_BINARY=1 \
    "$hook" > "$test_dir/missing-binary.stdout" 2> "$test_dir/missing-binary.stderr" || \
  missing_binary_status=$?
[[ $missing_binary_status == 1 ]] || \
  fail "missing-binary hook exited $missing_binary_status instead of 1"
grep -q 'installation did not create' "$test_dir/missing-binary.stderr" || \
  fail 'missing-binary result must be explicit'
[[ ! -e "$fixture_home/.local/bin/mlxctl" ]] || \
  fail 'missing-binary scenario unexpectedly installed mlxctl'

[[ $(<"$legacy_plist") == 'legacy plist' ]] || fail 'failure cases changed the legacy LaunchAgent'
[[ $(<"$legacy_config") == 'legacy config' ]] || fail 'failure cases changed legacy config'
[[ $(<"$legacy_state") == 'legacy state' ]] || fail 'failure cases changed legacy state'
[[ $(<"$legacy_log") == 'legacy log' ]] || fail 'failure cases changed legacy logs'
[[ $(<"$legacy_model") == 'legacy model' ]] || fail 'failure cases changed legacy model data'

data=$(chezmoi execute-template '{{ .mlxctl.sourceDir }}|{{ .mlxctl.binDir }}')
[[ $data == 'src/nisavid/systools/tools/mlxctl|.local/bin' ]] || \
  fail 'chezmoidata does not match the mlxctl installation boundary'

[[ ! -e home/private_Library/private_LaunchAgents/io.nisavid.mlxd.plist.tmpl ]] || \
  fail 'dotfiles must not manage the legacy LaunchAgent'
[[ ! -e home/dot_config/private_mlxd/private_config.toml.tmpl ]] || \
  fail 'dotfiles must not manage legacy mlxd configuration'
[[ ! -e home/.chezmoidata/mlxd.toml ]] || \
  fail 'obsolete mlxd deployment data must be removed'
! rg -n -i 'mlx-optiq|huggingface|hf download|hindsight|\.config/mlxd|\.local/state/mlxd|Library/Logs/mlxd' \
  home/run_after_install-mlxctl.sh.tmpl home/.chezmoidata/mlxctl.toml >/dev/null || \
  fail 'mlxctl installation sources exceed the tool-install boundary'
! rg -n -i '\b(bootstrap|bootout|kickstart|kill|enable|disable)\b' \
  home/run_after_install-mlxctl.sh.tmpl >/dev/null || \
  fail 'mlxctl install hook must not mutate the legacy LaunchAgent'
[[ $(grep -c '^print gui/.*/io\.nisavid\.mlxd$' "$launchctl_log" || true) -eq \
  $(wc -l < "$launchctl_log" | tr -d ' ') ]] || \
  fail 'mlxctl install hook used launchctl for more than read-only legacy inspection'

print -r -- 'mlxctl installation checks passed'
