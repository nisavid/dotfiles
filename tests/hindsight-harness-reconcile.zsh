#!/usr/bin/env zsh
set -euo pipefail

repo_dir="${0:A:h:h}"
tmp_dir="$(mktemp -d)"
trap '/bin/rm -rf -- "$tmp_dir"' EXIT
managed_python_relative="$(
  chezmoi -S "$repo_dir/home" \
    --override-data-file "$repo_dir/home/.chezmoidata/hindsight.toml" \
    execute-template '{{ .hindsight.managedPython }}'
)"
managed_python="$HOME/$managed_python_relative"
wrapper_home="$tmp_dir/home"
wrapper_python="$wrapper_home/$managed_python_relative"
wrapper_controller="$wrapper_home/.local/opt/hindsight-control-plane/bin/hindsight-memory-hook-authority"
wrapper_config="$wrapper_home/.local/state/hindsight-control-plane/harness-reconciliation.json"
wrapper_log="$tmp_dir/controller.log"
wrapper="$tmp_dir/hindsight-harness-reconcile"

mkdir -p \
  "${wrapper_python:h}" \
  "${wrapper_controller:h}" \
  "${wrapper_config:h}"
ln -s "$managed_python" "$wrapper_python"
HOME="$wrapper_home" \
  chezmoi -S "$repo_dir/home" \
    --override-data-file "$repo_dir/home/.chezmoidata/hindsight.toml" \
    execute-template \
    < "$repo_dir/home/private_dot_local/bin/executable_hindsight-harness-reconcile.tmpl" \
    > "$wrapper"
chmod 700 "$wrapper"
cat > "$wrapper_controller" <<'ZSH'
#!/usr/bin/env zsh
set -euo pipefail
print -r -- "$*" >>"$HINDSIGHT_TEST_CONTROLLER_LOG"
if [[ "$*" == *"harness-config disable"* ]]; then
  exit 0
fi
phase=""
for (( index = 1; index <= $#; index++ )); do
  if [[ "${@[index]}" == "--phase" ]]; then
    phase="${@[index + 1]}"
  fi
done
case "${HINDSIGHT_TEST_RECONCILE_MODE:-healthy}" in
  healthy)
    if [[ "$phase" == pre-start ]]; then
      print -r -- \
        '{"hook_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","phase":"pre-start","schema_version":1,"status":"healthy"}'
    else
      print -r -- \
        '{"hook_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","phase":"post-start","schema_version":1,"server_generation":"generation-1","status":"healthy"}'
    fi
    ;;
  unexpected)
    print -r -- \
      '{"extra":true,"hook_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","phase":"pre-start","schema_version":1,"status":"healthy"}'
    ;;
  nonzero)
    print -r -- '{"schema_version":1,"status":"degraded"}'
    exit 23
    ;;
esac
ZSH
chmod 700 "$wrapper_controller"

run_failure_case() {
  local label="$1" mode="$2" phase
  for phase in pre-start post-start; do
    : >"$wrapper_log"
    if HINDSIGHT_TEST_CONTROLLER_LOG="$wrapper_log" \
      HINDSIGHT_TEST_RECONCILE_MODE="$mode" \
      "$wrapper" "$phase" "$wrapper_config" >/dev/null 2>&1; then
      print -ru2 -- "harness reconciler accepted $label during $phase"
      exit 1
    fi
    [[ "$(grep -c 'harness-config disable' "$wrapper_log")" == 3 ]] || {
      print -ru2 -- \
        "harness reconciler did not disable every harness for $label during $phase"
      exit 1
    }
  done
}

/bin/rm -f -- "$wrapper_config"
for phase in pre-start post-start; do
  : >"$wrapper_log"
  HINDSIGHT_TEST_CONTROLLER_LOG="$wrapper_log" \
    HINDSIGHT_TEST_RECONCILE_MODE=healthy \
    "$wrapper" "$phase" "$wrapper_config" >/dev/null
  [[ "$(grep -c 'harness-config disable' "$wrapper_log")" == 3 ]] || {
    print -ru2 -- \
      "harness reconciler did not disable every harness for missing config during $phase"
    exit 1
  }
  if grep -F 'harness-config reconcile' "$wrapper_log" >/dev/null; then
    print -ru2 -- \
      "harness reconciler attempted activation for missing config during $phase"
    exit 1
  fi
done
print -r -- '{malformed' >"$wrapper_config"
chmod 600 "$wrapper_config"
run_failure_case "malformed config" healthy
print -r -- '{}' >"$tmp_dir/unsafe-config-target.json"
ln -sf "$tmp_dir/unsafe-config-target.json" "$wrapper_config"
run_failure_case "symlinked config" healthy
/bin/rm -f -- "$wrapper_config"
print -r -- '{}' >"$wrapper_config"
chmod 644 "$wrapper_config"
run_failure_case "unsafe config mode" healthy
chmod 600 "$wrapper_config"
run_failure_case "unexpected aggregate" unexpected
run_failure_case "nonzero reconcile" nonzero

wrapper_config_digest="$(
  "$managed_python" -c \
    'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' \
    "$wrapper_config"
)"
for phase in pre-start post-start; do
  : >"$wrapper_log"
  HINDSIGHT_TEST_CONTROLLER_LOG="$wrapper_log" \
    HINDSIGHT_TEST_RECONCILE_MODE=healthy \
    "$wrapper" "$phase" "$wrapper_config" >/dev/null
  grep -F \
    "harness-config reconcile --config $wrapper_config --config-digest $wrapper_config_digest --phase $phase" \
    "$wrapper_log" >/dev/null
  [[ "$(grep -c 'harness-config disable' "$wrapper_log")" == 0 ]]
done

: >"$wrapper_log"
HINDSIGHT_TEST_CONTROLLER_LOG="$wrapper_log" \
  "$wrapper" disable "$wrapper_config" >/dev/null
[[ "$(grep -c 'harness-config disable' "$wrapper_log")" == 3 ]] || {
  print -ru2 -- "explicit fail-closed phase did not disable every harness"
  exit 1
}
if grep -F 'harness-config reconcile' "$wrapper_log" >/dev/null; then
  print -ru2 -- "explicit fail-closed phase attempted runtime reconciliation"
  exit 1
fi

override_controller="$tmp_dir/candidate-hindsight-memory"
cp "$wrapper_controller" "$override_controller"
chmod 700 "$override_controller"
/bin/mv "$wrapper_controller" "$wrapper_controller.unavailable"
: >"$wrapper_log"
HINDSIGHT_HOOK_AUTHORITY_CONTROLLER="$override_controller" \
  HINDSIGHT_TEST_CONTROLLER_LOG="$wrapper_log" \
  "$wrapper" disable "$wrapper_config" >/dev/null
[[ "$(grep -c 'harness-config disable' "$wrapper_log")" == 3 ]] || {
  print -ru2 -- "candidate-anchored fail-closed override was not honored"
  exit 1
}

print -r -- "hindsight harness reconcile wrapper: PASS"
