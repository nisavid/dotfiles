#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
cd "$repo_root"

fail() {
  print -u2 -r -- "$1"
  return 1
}

command -v plutil >/dev/null || fail 'plutil is required to validate the LaunchAgent'
[[ -x /usr/libexec/PlistBuddy ]] || fail 'PlistBuddy is required to inspect the LaunchAgent'

test_dir=$(mktemp -d "${TMPDIR:-/tmp}/mlxd-deployment.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT

fixture_home=$test_dir/home
mkdir -p -- "$fixture_home"
fixture_home=${fixture_home:A}
plist=$fixture_home/Library/LaunchAgents/io.nisavid.mlxd.plist
config=$fixture_home/.config/mlxd/config.toml
mkdir -p -- "${plist:h}" "${config:h}"

fake_launchctl=$test_dir/launchctl
launchctl_state=$test_dir/launchctl.state
launchctl_log=$test_dir/launchctl.log
fake_bin=$test_dir/bin
fake_uv=$fake_bin/uv
uv_log=$test_dir/uv.log
source_dir=$fixture_home/src/nisavid/systools/tools/mlxctl
mkdir -p -- "$fake_bin" "$source_dir"
print -r -- '[project]' > "$source_dir/pyproject.toml"
{
  print -r -- '#!/usr/bin/env zsh'
  print -r -- 'set -eu'
  print -r -- 'case $1 in'
  print -r -- 'print)'
  print -r -- '  [[ -f "$MLXD_TEST_LAUNCHCTL_STATE" ]] || exit 113'
  print -r -- '  state=$(<"$MLXD_TEST_LAUNCHCTL_STATE")'
  print -r -- '  [[ -n "$state" ]] || state=waiting'
  print -r -- '  print -r -- "state = $state"'
  print -r -- '  ;;'
  print -r -- 'bootstrap)'
  print -r -- '  print -r -- "$*" >> "$MLXD_TEST_LAUNCHCTL_LOG"'
  print -r -- '  print -r -- waiting > "$MLXD_TEST_LAUNCHCTL_STATE"'
  print -r -- '  ;;'
  print -r -- 'bootout)'
  print -r -- '  print -r -- "$*" >> "$MLXD_TEST_LAUNCHCTL_LOG"'
  print -r -- '  rm -f -- "$MLXD_TEST_LAUNCHCTL_STATE"'
  print -r -- '  ;;'
  print -r -- '*) exit 64 ;;'
  print -r -- 'esac'
} > "$fake_launchctl"
chmod +x "$fake_launchctl"

{
  print -r -- '#!/usr/bin/env zsh'
  print -r -- 'set -eu'
  print -r -- 'print -r -- "$*" >> "$MLXD_TEST_UV_LOG"'
  print -r -- '[[ $UV_TOOL_BIN_DIR == "$MLXD_TEST_BIN_DIR" ]] || exit 65'
  print -r -- '[[ $* == "tool install --force $MLXD_TEST_SOURCE_DIR" ]] || exit 64'
  print -r -- 'mkdir -p -- "$MLXD_TEST_BIN_DIR"'
  print -r -- ': > "$MLXD_TEST_BIN_DIR/mlxctl"'
  print -r -- ': > "$MLXD_TEST_BIN_DIR/mlxd"'
  print -r -- 'chmod +x "$MLXD_TEST_BIN_DIR/mlxctl" "$MLXD_TEST_BIN_DIR/mlxd"'
} > "$fake_uv"
chmod +x "$fake_uv"

darwin_data='{"chezmoi":{"os":"darwin","homeDir":"'${fixture_home}'","username":"ivan"},"mlxd":{"launchctlBin":"'${fake_launchctl}'"}}'
linux_data='{"chezmoi":{"os":"linux","homeDir":"'${fixture_home}'","username":"ivan"}}'
xml_data='{"chezmoi":{"os":"darwin","homeDir":"/Users/tester/A&B","username":"ivan"},"mlxd":{"label":"io.nisavid.mlxd&test","launchctlBin":"'${fake_launchctl}'"}}'
extended_data='{"mlxd":{"config":{"models":{"future":{"reference":"example/future"}},"servers":{"future":{"type":"mlx_lm","model":"future","port":9999}}}}}'
hook=$test_dir/install-mlxctl.zsh
linux_plist=$test_dir/linux.plist
linux_hook=$test_dir/linux-hook.zsh
linux_config=$test_dir/linux-config.toml
xml_plist=$test_dir/xml-escaped.plist
extended_config=$test_dir/extended-config.toml

chezmoi execute-template --override-data "$darwin_data" \
  < home/Library/LaunchAgents/io.nisavid.mlxd.plist.tmpl > "$plist"
chezmoi execute-template --override-data "$darwin_data" \
  < home/run_after_install-mlxctl.sh.tmpl > "$hook"
chezmoi execute-template --override-data "$darwin_data" \
  < home/dot_config/private_mlxd/private_config.toml.tmpl > "$config"
chezmoi execute-template --override-data "$linux_data" \
  < home/Library/LaunchAgents/io.nisavid.mlxd.plist.tmpl > "$linux_plist"
chezmoi execute-template --override-data "$linux_data" \
  < home/run_after_install-mlxctl.sh.tmpl > "$linux_hook"
chezmoi execute-template --override-data "$linux_data" \
  < home/dot_config/private_mlxd/private_config.toml.tmpl > "$linux_config"
chezmoi execute-template --override-data "$xml_data" \
  < home/Library/LaunchAgents/io.nisavid.mlxd.plist.tmpl > "$xml_plist"
chezmoi execute-template --override-data "$extended_data" \
  < home/dot_config/private_mlxd/private_config.toml.tmpl > "$extended_config"

plutil -lint "$plist" >/dev/null
plutil -lint "$xml_plist" >/dev/null
zsh -n "$hook"
chmod +x "$hook"
[[ $(head -c 2 "$hook") == '#!' ]] || fail 'install hook shebang must start at byte zero'
[[ $(/usr/libexec/PlistBuddy -c 'Print :Label' "$xml_plist") == 'io.nisavid.mlxd&test' ]] || \
  fail 'LaunchAgent label must be XML escaped'
[[ $(/usr/libexec/PlistBuddy -c 'Print :WorkingDirectory' "$xml_plist") == '/Users/tester/A&B' ]] || \
  fail 'LaunchAgent paths must be XML escaped'
[[ ! -s "$linux_plist" ]] || fail 'LaunchAgent must render empty outside macOS'
[[ ! -s "$linux_hook" ]] || fail 'install hook must render empty outside macOS'
[[ ! -s "$linux_config" ]] || fail 'config must render empty outside macOS'

command -v yq >/dev/null || fail 'yq is required to validate the rendered TOML'
command -v jq >/dev/null || fail 'jq is required to validate the rendered TOML'
yq -p=toml -o=json "$config" | jq -e '
  . == {
    "schema_version": 1,
    "metrics": {"retention_days": 7},
    "models": {
      "llama-3b": {"reference": "mlx-community/Llama-3.2-3B-Instruct-4bit"},
      "qwen-7b": {"reference": "mlx-community/Qwen2.5-7B-Instruct-4bit"}
    },
    "servers": {
      "mlx": {"type": "mlx_lm", "model": "llama-3b", "port": 8765}
    }
  }
' >/dev/null || fail 'rendered config does not match the approved personal values'
yq -p=toml -o=json "$extended_config" | jq -e '
  .models.future.reference == "example/future" and
  .servers.future == {"type": "mlx_lm", "model": "future", "port": 9999}
' >/dev/null || fail 'rendered config must include future registry entries from chezmoidata'

plist_value() {
  /usr/libexec/PlistBuddy -c "Print :$1" "$plist"
}

[[ $(plist_value Label) == io.nisavid.mlxd ]] || fail 'wrong LaunchAgent label'
[[ $(plist_value ProgramArguments:0) == "$fixture_home/.local/bin/mlxd" ]] || \
  fail 'LaunchAgent must invoke mlxd'
[[ $(plist_value RunAtLoad) == false ]] || fail 'RunAtLoad must be false'
[[ $(plist_value KeepAlive) == false ]] || fail 'KeepAlive must be false'
[[ $(plist_value EnvironmentVariables:PATH) == "$fixture_home/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" ]] || \
  fail 'PATH does not include the managed tool directory'
[[ $(plist_value EnvironmentVariables:MLXD_CONFIG_DIR) == "$fixture_home/.config/mlxd" ]] || \
  fail 'wrong MLXD_CONFIG_DIR'
[[ $(plist_value EnvironmentVariables:MLXD_STATE_DIR) == "$fixture_home/.local/state/mlxd" ]] || \
  fail 'wrong MLXD_STATE_DIR'
[[ $(plist_value EnvironmentVariables:MLXD_LOG_DIR) == "$fixture_home/Library/Logs/mlxd" ]] || \
  fail 'wrong MLXD_LOG_DIR'
[[ $(plist_value StandardOutPath) == "$fixture_home/Library/Logs/mlxd/mlxd.log" ]] || \
  fail 'wrong supervisor stdout path'
[[ $(plist_value StandardErrorPath) == "$fixture_home/Library/Logs/mlxd/mlxd.log" ]] || \
  fail 'wrong supervisor stderr path'
! grep -q '<key>MLXD_LOG_LEVEL</key>' "$plist" || fail 'v1 must not set MLXD_LOG_LEVEL'

mkdir -p -- "$fixture_home/.local/state/mlxd" "$fixture_home/Library/Logs/mlxd"
chmod 755 "$fixture_home/.config/mlxd" "$fixture_home/.local/state/mlxd" "$fixture_home/Library/Logs/mlxd"

if ! PATH="$fake_bin:$PATH" \
  ZDOTDIR=$test_dir \
  MLXD_TEST_BIN_DIR=$fixture_home/.local/bin \
  MLXD_TEST_SOURCE_DIR=$source_dir \
  MLXD_TEST_UV_LOG=$uv_log \
  MLXD_TEST_LAUNCHCTL_STATE=$launchctl_state \
  MLXD_TEST_LAUNCHCTL_LOG=$launchctl_log \
    "$hook" > "$test_dir/hook.stdout" 2> "$test_dir/hook.stderr"; then
  fail "install hook failed: $(<"$test_dir/hook.stderr")"
fi
[[ -d "$fixture_home/.config/mlxd" ]] || fail 'install hook did not create config dir'
[[ -d "$fixture_home/.local/state/mlxd" ]] || fail 'install hook did not create state dir'
[[ -d "$fixture_home/Library/Logs/mlxd" ]] || fail 'install hook did not create log dir'
[[ $(stat -f '%Lp' "$fixture_home/.config/mlxd") == 700 ]] || fail 'config dir must be private'
[[ $(stat -f '%Lp' "$fixture_home/.local/state/mlxd") == 700 ]] || fail 'state dir must be private'
[[ $(stat -f '%Lp' "$fixture_home/Library/Logs/mlxd") == 700 ]] || fail 'log dir must be private'
[[ $(<"$uv_log") == "tool install --force $source_dir" ]] || \
  fail 'install hook used the wrong uv command'
[[ -f "$launchctl_state" ]] || fail 'install hook did not register the LaunchAgent'
[[ $(<"$launchctl_log") == "bootstrap gui/$EUID $plist" ]] || \
  fail 'install hook used the wrong bootstrap target'
! grep -q kickstart "$launchctl_log" || fail 'install hook must not start the service'
grep -q 'installing from' "$test_dir/hook.stdout" || fail 'source install result must be explicit'

uv_before=$(<"$uv_log")
launchctl_before=$(<"$launchctl_log")
print -r -- running > "$launchctl_state"
if PATH="$fake_bin:$PATH" \
  ZDOTDIR=$test_dir \
  MLXD_TEST_BIN_DIR=$fixture_home/.local/bin \
  MLXD_TEST_SOURCE_DIR=$source_dir \
  MLXD_TEST_UV_LOG=$uv_log \
  MLXD_TEST_LAUNCHCTL_STATE=$launchctl_state \
  MLXD_TEST_LAUNCHCTL_LOG=$launchctl_log \
    "$hook" > "$test_dir/hook-running.stdout" 2> "$test_dir/hook-running.stderr"; then
  fail 'install hook must refuse to update a running service'
fi
[[ $(<"$uv_log") == "$uv_before" ]] || fail 'running-service refusal must precede uv install'
[[ $(<"$launchctl_log") == "$launchctl_before" ]] || \
  fail 'running-service refusal must not change LaunchAgent registration'
grep -q 'is running' "$test_dir/hook-running.stderr" || \
  fail 'running-service refusal must be explicit'
print -r -- waiting > "$launchctl_state"

if ! PATH="$fake_bin:$PATH" \
  ZDOTDIR=$test_dir \
  MLXD_TEST_BIN_DIR=$fixture_home/.local/bin \
  MLXD_TEST_SOURCE_DIR=$source_dir \
  MLXD_TEST_UV_LOG=$uv_log \
  MLXD_TEST_LAUNCHCTL_STATE=$launchctl_state \
  MLXD_TEST_LAUNCHCTL_LOG=$launchctl_log \
    "$hook" > "$test_dir/hook-second.stdout" 2> "$test_dir/hook-second.stderr"; then
  fail "idempotent hook failed: $(<"$test_dir/hook-second.stderr")"
fi
bootstrap_count=$(grep -c '^bootstrap ' "$launchctl_log" || true)
[[ $bootstrap_count == 2 ]] || \
  fail "registered job was bootstrapped $bootstrap_count times"
grep -qx "bootout gui/$EUID/io.nisavid.mlxd" "$launchctl_log" || \
  fail 'registered job was not unloaded before reloading the managed plist'
grep -q 'reloaded .* without starting it' "$test_dir/hook-second.stdout" || \
  fail 'idempotent reload result must be explicit'

rm -rf -- "$source_dir"
if ! PATH="$fake_bin:$PATH" \
  ZDOTDIR=$test_dir \
  MLXD_TEST_BIN_DIR=$fixture_home/.local/bin \
  MLXD_TEST_SOURCE_DIR=$source_dir \
  MLXD_TEST_UV_LOG=$uv_log \
  MLXD_TEST_LAUNCHCTL_STATE=$launchctl_state \
  MLXD_TEST_LAUNCHCTL_LOG=$launchctl_log \
    "$hook" > "$test_dir/hook-third.stdout" 2> "$test_dir/hook-third.stderr"; then
  fail "missing-source hook failed: $(<"$test_dir/hook-third.stderr")"
fi
bootstrap_count=$(grep -c '^bootstrap ' "$launchctl_log" || true)
[[ $bootstrap_count == 2 ]] || \
  fail "missing source changed bootstrap count to $bootstrap_count"
bootout_count=$(grep -c '^bootout ' "$launchctl_log" || true)
[[ $bootout_count == 2 ]] || fail "missing source produced $bootout_count bootouts"
[[ ! -f "$launchctl_state" ]] || fail 'missing source left stale LaunchAgent registered'
grep -q 'source checkout not found' "$test_dir/hook-third.stderr" || \
  fail 'missing-source result must be explicit'

data=$(chezmoi execute-template '{{ .mlxd.label }}|{{ .mlxd.sourceDir }}|{{ .mlxd.configDir }}|{{ .mlxd.stateDir }}|{{ .mlxd.logDir }}|{{ .mlxd.launchctlBin }}|{{ .mlxd.config.schemaVersion }}')
[[ $data == 'io.nisavid.mlxd|src/nisavid/systools/tools/mlxctl|.config/mlxd|.local/state/mlxd|Library/Logs/mlxd|/bin/launchctl|1' ]] || \
  fail 'chezmoidata does not match deployment contract v1'

[[ -f home/dot_config/private_mlxd/private_config.toml.tmpl ]] || \
  fail 'config must share the existing dot_config source topology'
[[ ! -e home/private_dot_config ]] || \
  fail 'a second source root for .config creates an inconsistent chezmoi state'
[[ ! -e home/dot_config/private_mlxd/private_servers.toml.tmpl ]] || \
  fail 'server config schema is outside deployment contract v1'

print -r -- 'mlxd deployment checks passed'
