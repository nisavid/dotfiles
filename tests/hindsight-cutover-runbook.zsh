#!/usr/bin/env zsh
set -euo pipefail

repo_dir="${0:A:h:h}"
agents_root="${HINDSIGHT_AGENTS_ROOT:-$HOME/src/nisavid/agents}"
tmp_dir="$(/usr/bin/mktemp -d "$HOME/.cache/hindsight-cutover-test.XXXXXX")"
/bin/chmod 700 "$tmp_dir"
trap '/bin/rm -rf -- "$tmp_dir"' EXIT

[[ -f "$agents_root/tooling/hindsight/bin/hindsight-memory" ]]

write_fixture() {
  local path="$1" line
  shift
  print -r -- '#!/bin/zsh' >"$path"
  for line in "$@"; do
    print -r -- "$line" >>"$path"
  done
  /bin/chmod 700 "$path"
}

prepare_case() {
  local name="$1"
  case_root="$tmp_dir/$name"
  fake_home="$case_root/home"
  helpers="$case_root/helpers"
  events="$case_root/events"
  /bin/mkdir -p \
    "$fake_home/.cache" \
    "$fake_home/.config/hindsight-control-plane" \
    "$fake_home/.local/share/uv/python/cpython-3.13.14-macos-aarch64-none/bin" \
    "$helpers"
  /bin/chmod 700 \
    "$case_root" \
    "$fake_home" \
    "$fake_home/.cache" \
    "$fake_home/.config" \
    "$fake_home/.config/hindsight-control-plane" \
    "$fake_home/.local" \
    "$fake_home/.local/share" \
    "$fake_home/.local/share/uv" \
    "$fake_home/.local/share/uv/python" \
    "$fake_home/.local/share/uv/python/cpython-3.13.14-macos-aarch64-none" \
    "$fake_home/.local/share/uv/python/cpython-3.13.14-macos-aarch64-none/bin" \
    "$helpers"
  print -r -- '{}' \
    >"$fake_home/.config/hindsight-control-plane/installation.json"
  /bin/chmod 600 \
    "$fake_home/.config/hindsight-control-plane/installation.json"

  write_fixture "$helpers/rollback" \
    'print -r -- "rollback:$*" >>"$HINDSIGHT_TEST_EVENTS"' \
    'exit 0'
  write_fixture "$helpers/stop" \
    'print -r -- stop >>"$HINDSIGHT_TEST_EVENTS"' \
    'if [[ "${HINDSIGHT_TEST_REPLACE_ACCEPT:-false}" == true ]]; then' \
    '  print -r -- "#!/bin/zsh" >"$HINDSIGHT_TEST_ACCEPT_PATH"' \
    '  print -r -- "exit 0" >>"$HINDSIGHT_TEST_ACCEPT_PATH"' \
    '  /bin/chmod 700 "$HINDSIGHT_TEST_ACCEPT_PATH"' \
    'fi' \
    'exit "${HINDSIGHT_TEST_STOP_RC:-0}"'
  write_fixture "$helpers/accept" \
    'print -r -- accept >>"$HINDSIGHT_TEST_EVENTS"' \
    'exit "${HINDSIGHT_TEST_ACCEPT_RC:-0}"'
  write_fixture \
    "$fake_home/.local/share/uv/python/cpython-3.13.14-macos-aarch64-none/bin/python3.13" \
    '[[ "$2" == install ]]' \
    'print -r -- install >>"$HINDSIGHT_TEST_EVENTS"' \
    'installed="$HOME/.local/opt/hindsight-control-plane/bin/hindsight-memory"' \
    '/bin/mkdir -p "${installed:h}"' \
    'print -r -- "#!/bin/zsh" >"$installed"' \
    'print -r -- '\''print -r -- "installed:$*" >>"$HINDSIGHT_TEST_EVENTS"'\'' >>"$installed"' \
    'print -r -- "exit 0" >>"$installed"' \
    '/bin/chmod 700 "$installed"'
}

run_cutover() {
  local stop_rc="${1:-0}" accept_rc="${2:-0}" replace_accept="${3:-false}"
  local cutover_script="${4:-$repo_dir/scripts/hindsight-control-plane-cutover.zsh}"
  set +e
  HOME="$fake_home" \
  HINDSIGHT_TEST_EVENTS="$events" \
  HINDSIGHT_TEST_STOP_RC="$stop_rc" \
  HINDSIGHT_TEST_ACCEPT_RC="$accept_rc" \
  HINDSIGHT_TEST_REPLACE_ACCEPT="$replace_accept" \
  HINDSIGHT_TEST_ACCEPT_PATH="$helpers/accept" \
  HINDSIGHT_AGENTS_CHECKOUT="$agents_root" \
  stop_legacy="$helpers/stop" \
  rollback_preflight="$helpers/rollback" \
  activation_acceptance="$helpers/accept" \
    /bin/zsh "$cutover_script"
  cutover_status=$?
  set -e
}

assert_events() {
  local expected="$1"
  [[ "$(<"$events")" == "$expected" ]] || {
    print -ru2 -- "unexpected events for ${case_root:t}"
    /bin/cat "$events" >&2
    return 1
  }
}

prepare_case stop-failure
run_cutover 19 0
[[ "$cutover_status" == 19 ]]
assert_events $'rollback:--verify-only\nstop\nrollback:--restore-and-reload'

prepare_case acceptance-failure
run_cutover 0 23
[[ "$cutover_status" == 23 ]]
assert_events $'rollback:--verify-only\nstop\ninstall\ninstalled:verify --config '"$fake_home"$'/.config/hindsight-control-plane/installation.json\naccept\nrollback:--restore-and-reload'

prepare_case success
run_cutover 0 0
[[ "$cutover_status" == 0 ]]
assert_events $'rollback:--verify-only\nstop\ninstall\ninstalled:verify --config '"$fake_home"$'/.config/hindsight-control-plane/installation.json\naccept'

prepare_case replaced-helper
run_cutover 0 0 true
[[ "$cutover_status" != 0 ]]
assert_events $'rollback:--verify-only\nstop\ninstall\ninstalled:verify --config '"$fake_home"$'/.config/hindsight-control-plane/installation.json\nrollback:--restore-and-reload'

prepare_case unsafe-helper
/bin/mv "$helpers/stop" "$helpers/stop-real"
/bin/ln -s "$helpers/stop-real" "$helpers/stop"
run_cutover 0 0
[[ "$cutover_status" != 0 ]]
[[ ! -e "$events" ]]

prepare_case acl-helper
/bin/chmod +a "everyone allow read,write" "$helpers/stop"
run_cutover 0 0
[[ "$cutover_status" != 0 ]]
[[ ! -e "$events" ]]

prepare_case prerequisite-failure
/bin/rm "$fake_home/.config/hindsight-control-plane/installation.json"
run_cutover 0 0
[[ "$cutover_status" != 0 ]]
[[ ! -e "$events" ]]

prepare_case version-mismatch
mismatch_root="$case_root/dotfiles"
/bin/mkdir -p "$mismatch_root/scripts" "$mismatch_root/home/.chezmoidata"
/bin/chmod 700 \
  "$mismatch_root" \
  "$mismatch_root/scripts" \
  "$mismatch_root/home" \
  "$mismatch_root/home/.chezmoidata"
/bin/cp \
  "$repo_dir/scripts/hindsight-control-plane-cutover.zsh" \
  "$mismatch_root/scripts/hindsight-control-plane-cutover.zsh"
while IFS= read -r line; do
  if [[ "$line" == 'releaseVersion = '* ]]; then
    print -r -- 'releaseVersion = "2026.07.23+0000000"'
  else
    print -r -- "$line"
  fi
done <"$repo_dir/home/.chezmoidata/hindsight.toml" \
  >"$mismatch_root/home/.chezmoidata/hindsight.toml"
run_cutover \
  0 \
  0 \
  false \
  "$mismatch_root/scripts/hindsight-control-plane-cutover.zsh"
[[ "$cutover_status" != 0 ]]
[[ ! -e "$events" ]]

print -r -- "hindsight cutover rollback: PASS"
