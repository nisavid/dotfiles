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
optiq_log=$test_dir/optiq.log
hindsight_log=$test_dir/hindsight.log
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
  print -r -- 'case "$*" in'
  print -r -- '  "tool install --force $MLXD_TEST_SOURCE_DIR")'
  print -r -- '    mkdir -p -- "$MLXD_TEST_BIN_DIR"'
  print -r -- '    : > "$MLXD_TEST_BIN_DIR/mlxctl"'
  print -r -- '    : > "$MLXD_TEST_BIN_DIR/mlxd"'
  print -r -- '    chmod +x "$MLXD_TEST_BIN_DIR/mlxctl" "$MLXD_TEST_BIN_DIR/mlxd"'
  print -r -- '    ;;'
  print -r -- '  "tool install --force mlx-optiq==0.2.18")'
  print -r -- '    {'
  print -r -- "      print -r -- '#!/usr/bin/env zsh'"
  print -r -- "      print -r -- 'print -r -- \"\$*\" >> \"\$MLXD_TEST_OPTIQ_LOG\"'"
  print -r -- "      print -r -- '[[ \"\$*\" == \"serve --help\" ]] || exit 64'"
  print -r -- "      print -r -- 'print -r -- \"--kv-config\"'"
  print -r -- "      print -r -- 'if [[ \"\${MLXD_TEST_OPTIQ_NEAR_MATCH:-0}\" == 1 ]]; then'"
  print -r -- "      print -r -- '  print -r -- \"--max-contextual\"'"
  print -r -- "      print -r -- '  print -r -- \"--mtp-mode\"'"
  print -r -- "      print -r -- 'else'"
  print -r -- "      print -r -- '  print -r -- \"--max-context\"'"
  print -r -- "      print -r -- '  print -r -- \"--mtp\"'"
  print -r -- "      print -r -- 'fi'"
  print -r -- '    } > "$MLXD_TEST_BIN_DIR/optiq"'
  print -r -- '    chmod +x "$MLXD_TEST_BIN_DIR/optiq"'
  print -r -- '    ;;'
  print -r -- '  "tool run --from huggingface-hub==1.22.0 hf download mlx-community/Qwen3.6-35B-A3B-OptiQ-4bit --revision 70a3aa32c7feef511182bf16aa332f37e8d82014 --local-dir $MLXD_TEST_MODEL_DIR")'
  print -r -- '    mkdir -p -- "$MLXD_TEST_MODEL_DIR"'
  print -r -- '    print -r -- test-kv > "$MLXD_TEST_MODEL_DIR/kv_config.json"'
  print -r -- '    ;;'
  print -r -- '  *) exit 64 ;;'
  print -r -- 'esac'
} > "$fake_uv"
chmod +x "$fake_uv"
fake_hindsight=$fixture_home/.local/bin/hindsight-embed
mkdir -p -- "${fake_hindsight:h}"
{
  print -r -- '#!/usr/bin/env zsh'
  print -r -- 'set -eu'
  print -r -- 'print -r -- "$*" >> "$MLXD_TEST_HINDSIGHT_LOG"'
} > "$fake_hindsight"
chmod +x "$fake_hindsight"

darwin_data='{"chezmoi":{"os":"darwin","homeDir":"'${fixture_home}'","username":"ivan","hostname":"hatchery"},"mlxd":{"launchctlBin":"'${fake_launchctl}'","optiq":{"targetHostname":"hatchery","runtimePackage":"mlx-optiq==0.2.18","huggingFacePackage":"huggingface-hub==1.22.0","modelRepository":"mlx-community/Qwen3.6-35B-A3B-OptiQ-4bit","modelRevision":"70a3aa32c7feef511182bf16aa332f37e8d82014","modelDir":".local/share/mlxd/models/qwen36-optiq","kvConfig":"kv_config.json","kvSha256":"547d2156462f21d250fb7edba17880c43e1cfa006a17b16f9495a630fab2c8fa","clients":{"baseUrl":"http://127.0.0.1:8766/v1","contextWindow":32768,"codexProvider":"mlx-optiq","hindsightProvider":"lmstudio","hindsightProfile":"systalyze"}},"config":{"models":{"qwen36-optiq":{"localDir":".local/share/mlxd/models/qwen36-optiq","targetHostname":"hatchery"}},"servers":{"optiq":{"type":"optiq","model":"qwen36-optiq","port":8766,"targetHostname":"hatchery","options":{"kv_config":"kv_config.json","max_context":32768,"mtp":true,"temp":0.0}}}}}}'
non_target_data=${darwin_data//\"hostname\":\"hatchery\"/\"hostname\":\"stlz-ivan-mbp\"}
linux_data='{"chezmoi":{"os":"linux","homeDir":"'${fixture_home}'","username":"ivan"}}'
xml_data='{"chezmoi":{"os":"darwin","homeDir":"/Users/tester/A&B","username":"ivan"},"mlxd":{"label":"io.nisavid.mlxd&test","launchctlBin":"'${fake_launchctl}'"}}'
extended_data='{"mlxd":{"config":{"models":{"future":{"reference":"example/future"}},"servers":{"future":{"type":"mlx_lm","model":"future","port":9999}}}}}'
hook=$test_dir/install-mlxctl.zsh
linux_plist=$test_dir/linux.plist
linux_hook=$test_dir/linux-hook.zsh
linux_config=$test_dir/linux-config.toml
xml_plist=$test_dir/xml-escaped.plist
extended_config=$test_dir/extended-config.toml
non_target_config=$test_dir/non-target-config.toml
non_target_hook=$test_dir/non-target-hook.zsh

chezmoi execute-template --override-data "$darwin_data" \
  < home/private_Library/private_LaunchAgents/io.nisavid.mlxd.plist.tmpl > "$plist"
chezmoi execute-template --override-data "$darwin_data" \
  < home/run_after_install-mlxctl.sh.tmpl > "$hook"
chezmoi execute-template --override-data "$darwin_data" \
  < home/dot_config/private_mlxd/private_config.toml.tmpl > "$config"
chezmoi execute-template --override-data "$linux_data" \
  < home/private_Library/private_LaunchAgents/io.nisavid.mlxd.plist.tmpl > "$linux_plist"
chezmoi execute-template --override-data "$linux_data" \
  < home/run_after_install-mlxctl.sh.tmpl > "$linux_hook"
chezmoi execute-template --override-data "$linux_data" \
  < home/dot_config/private_mlxd/private_config.toml.tmpl > "$linux_config"
chezmoi execute-template --override-data "$xml_data" \
  < home/private_Library/private_LaunchAgents/io.nisavid.mlxd.plist.tmpl > "$xml_plist"
chezmoi execute-template --override-data "$extended_data" \
  < home/dot_config/private_mlxd/private_config.toml.tmpl > "$extended_config"
chezmoi execute-template --override-data "$non_target_data" \
  < home/dot_config/private_mlxd/private_config.toml.tmpl > "$non_target_config"
chezmoi execute-template --override-data "$non_target_data" \
  < home/run_after_install-mlxctl.sh.tmpl > "$non_target_hook"

plutil -lint "$plist" >/dev/null
plutil -lint "$xml_plist" >/dev/null
zsh -n "$hook"
zsh -n "$non_target_hook"
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
      "qwen-7b": {"reference": "mlx-community/Qwen2.5-7B-Instruct-4bit"},
      "qwen36-optiq": {"reference": "'"$fixture_home"'/.local/share/mlxd/models/qwen36-optiq"}
    },
    "servers": {
      "mlx": {"type": "mlx_lm", "model": "llama-3b", "port": 8765},
      "optiq": {
        "type": "optiq",
        "model": "qwen36-optiq",
        "port": 8766,
        "options": {
          "kv_config": "'"$fixture_home"'/.local/share/mlxd/models/qwen36-optiq/kv_config.json",
          "max_context": 32768,
          "mtp": true,
          "temp": 0.0
        }
      }
    }
  }
' >/dev/null || fail 'rendered config does not match the approved personal values'
yq -p=toml -o=json "$extended_config" | jq -e '
  .models.future.reference == "example/future" and
  .servers.future == {"type": "mlx_lm", "model": "future", "port": 9999}
' >/dev/null || fail 'rendered config must include future registry entries from chezmoidata'
yq -p=toml -o=json "$non_target_config" | jq -e '
  (.models | has("qwen36-optiq") | not) and (.servers | has("optiq") | not)
' >/dev/null || fail 'OptiQ model and Server Definition must remain hatchery-only'
grep -q '^  local optiq_target=0$' "$non_target_hook" || \
  fail 'non-target install hook must disable OptiQ deployment'

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
  MLXD_TEST_MODEL_DIR=$fixture_home/.local/share/mlxd/models/qwen36-optiq \
  MLXD_TEST_UV_LOG=$uv_log \
  MLXD_TEST_OPTIQ_LOG=$optiq_log \
  MLXD_TEST_HINDSIGHT_LOG=$hindsight_log \
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
expected_uv_log="tool install --force $source_dir
tool install --force mlx-optiq==0.2.18
tool run --from huggingface-hub==1.22.0 hf download mlx-community/Qwen3.6-35B-A3B-OptiQ-4bit --revision 70a3aa32c7feef511182bf16aa332f37e8d82014 --local-dir $fixture_home/.local/share/mlxd/models/qwen36-optiq"
[[ $(<"$uv_log") == "$expected_uv_log" ]] || \
  fail 'install hook used the wrong uv command'
[[ -x "$fixture_home/.local/bin/optiq" ]] || fail 'install hook did not install optiq'
[[ $(<"$optiq_log") == 'serve --help' ]] || \
  fail 'install hook did not validate the installed OptiQ serve capabilities'
[[ -f "$fixture_home/.local/share/mlxd/models/qwen36-optiq/kv_config.json" ]] || \
  fail 'install hook did not download the pinned model snapshot'
[[ $(wc -l < "$hindsight_log" | tr -d ' ') == 8 ]] || \
  fail 'install hook did not configure all Hindsight sampling settings'
grep -qx "profile set-env systalyze HINDSIGHT_API_LLM_PROVIDER lmstudio" "$hindsight_log" || \
  fail 'install hook used the wrong Hindsight provider'
grep -qx "profile set-env systalyze HINDSIGHT_API_LLM_BASE_URL http://127.0.0.1:8766/v1" "$hindsight_log" || \
  fail 'install hook used the wrong Hindsight Client Endpoint'
grep -qx "profile set-env systalyze HINDSIGHT_API_LLM_TEMPERATURE_REFLECT 0.9" "$hindsight_log" || \
  fail 'install hook used the wrong Hindsight reflection temperature'
[[ -f "$launchctl_state" ]] || fail 'install hook did not register the LaunchAgent'
[[ $(<"$launchctl_log") == "bootstrap gui/$EUID $plist" ]] || \
  fail 'install hook used the wrong bootstrap target'
! grep -q kickstart "$launchctl_log" || fail 'install hook must not start the service'
grep -q 'installing from' "$test_dir/hook.stdout" || fail 'source install result must be explicit'

near_match_uv_before=$(<"$uv_log")
near_match_hindsight_before=$(<"$hindsight_log")
near_match_launchctl_before=$(<"$launchctl_log")
if PATH="$fake_bin:$PATH" \
  ZDOTDIR=$test_dir \
  MLXD_TEST_BIN_DIR=$fixture_home/.local/bin \
  MLXD_TEST_SOURCE_DIR=$source_dir \
  MLXD_TEST_MODEL_DIR=$fixture_home/.local/share/mlxd/models/qwen36-optiq \
  MLXD_TEST_UV_LOG=$uv_log \
  MLXD_TEST_OPTIQ_LOG=$optiq_log \
  MLXD_TEST_OPTIQ_NEAR_MATCH=1 \
  MLXD_TEST_HINDSIGHT_LOG=$hindsight_log \
  MLXD_TEST_LAUNCHCTL_STATE=$launchctl_state \
  MLXD_TEST_LAUNCHCTL_LOG=$launchctl_log \
    "$hook" > "$test_dir/hook-near-match.stdout" 2> "$test_dir/hook-near-match.stderr"; then
  fail 'install hook accepted a near-match for a required OptiQ serve option'
fi
expected_near_match_uv_log="$near_match_uv_before
tool install --force $source_dir
tool install --force mlx-optiq==0.2.18"
[[ $(<"$uv_log") == "$expected_near_match_uv_log" ]] || \
  fail 'OptiQ capability refusal must precede the pinned model download'
[[ $(<"$hindsight_log") == "$near_match_hindsight_before" ]] || \
  fail 'OptiQ capability refusal must precede Hindsight configuration'
expected_near_match_launchctl_log="$near_match_launchctl_before
bootout gui/$EUID/io.nisavid.mlxd"
[[ $(<"$launchctl_log") == "$expected_near_match_launchctl_log" ]] || \
  fail 'OptiQ capability refusal must unload the stale LaunchAgent registration'
[[ ! -f "$launchctl_state" ]] || \
  fail 'OptiQ capability refusal left the stale LaunchAgent registered'
grep -q 'does not support required serve options: --max-context, --mtp' \
  "$test_dir/hook-near-match.stderr" || \
  fail 'OptiQ capability refusal must identify the unsupported option'

uv_before=$(<"$uv_log")
launchctl_before=$(<"$launchctl_log")
print -r -- running > "$launchctl_state"
if PATH="$fake_bin:$PATH" \
  ZDOTDIR=$test_dir \
  MLXD_TEST_BIN_DIR=$fixture_home/.local/bin \
  MLXD_TEST_SOURCE_DIR=$source_dir \
  MLXD_TEST_MODEL_DIR=$fixture_home/.local/share/mlxd/models/qwen36-optiq \
  MLXD_TEST_UV_LOG=$uv_log \
  MLXD_TEST_OPTIQ_LOG=$optiq_log \
  MLXD_TEST_HINDSIGHT_LOG=$hindsight_log \
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
  MLXD_TEST_MODEL_DIR=$fixture_home/.local/share/mlxd/models/qwen36-optiq \
  MLXD_TEST_UV_LOG=$uv_log \
  MLXD_TEST_OPTIQ_LOG=$optiq_log \
  MLXD_TEST_HINDSIGHT_LOG=$hindsight_log \
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
  MLXD_TEST_MODEL_DIR=$fixture_home/.local/share/mlxd/models/qwen36-optiq \
  MLXD_TEST_UV_LOG=$uv_log \
  MLXD_TEST_OPTIQ_LOG=$optiq_log \
  MLXD_TEST_HINDSIGHT_LOG=$hindsight_log \
  MLXD_TEST_LAUNCHCTL_STATE=$launchctl_state \
  MLXD_TEST_LAUNCHCTL_LOG=$launchctl_log \
    "$hook" > "$test_dir/hook-third.stdout" 2> "$test_dir/hook-third.stderr"; then
  fail "missing-source hook failed: $(<"$test_dir/hook-third.stderr")"
fi
bootstrap_count=$(grep -c '^bootstrap ' "$launchctl_log" || true)
[[ $bootstrap_count == 2 ]] || \
  fail "missing source changed bootstrap count to $bootstrap_count"
bootout_count=$(grep -c '^bootout ' "$launchctl_log" || true)
[[ $bootout_count == 3 ]] || fail "missing source produced $bootout_count bootouts"
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
