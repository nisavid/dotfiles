#!/usr/bin/env zsh
set -euo pipefail

repo_dir="${0:A:h:h}"
tmp_dir="$(mktemp -d)"
trap 'rm -rf -- "$tmp_dir"' EXIT

rendered_stack_lib="$tmp_dir/hindsight-embed-stack.zsh"
(
  cd "$repo_dir"
  chezmoi execute-template < home/private_dot_local/lib/hindsight-embed-stack.zsh.tmpl > "$rendered_stack_lib"
)

service_lib="$tmp_dir/hindsight-embed-service.zsh"
/usr/bin/sed '/^main "\$@"$/d' \
  "$repo_dir/home/private_dot_local/bin/executable_hindsight-embed-service" > "$service_lib"

test_home="$tmp_dir/home"
mkdir -p "$test_home/.hindsight/profiles"

(
  export HOME="$test_home"
  export HINDSIGHT_EMBED_PROFILE="missing-profile"
  source "$rendered_stack_lib"
  if hindsight_stack_profile_exists; then
    print -ru2 -- "missing profile unexpectedly exists"
    exit 1
  fi
)

touch "$test_home/.hindsight/profiles/present-profile.env"
(
  export HOME="$test_home"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  source "$rendered_stack_lib"
  hindsight_stack_profile_exists
)

rg -F -q 'uvx hindsight-embed configure --profile "$profile" --port "$api_port"' "$repo_dir/docs/HINDSIGHT.md" || {
  print -ru2 -- "setup guide must use interactive configure"
  exit 1
}

if rg -A1 '^uvx hindsight-embed configure' "$repo_dir/docs/HINDSIGHT.md" | rg -q -- '--env'; then
  print -ru2 -- "interactive configure must not receive --env"
  exit 1
fi

rg -F -q 'hindsight-embed profile set-env "$profile" HINDSIGHT_BANK_ID "$bank_id"' "$repo_dir/docs/HINDSIGHT.md" || {
  print -ru2 -- "setup guide must set the bank after interactive configuration"
  exit 1
}

if rg -n 'systalyze|engineering' "$repo_dir/docs/HINDSIGHT.md" >/dev/null; then
  print -ru2 -- "setup guide must use generic profile and bank placeholders"
  exit 1
fi

rg -F -q '[Hindsight local stack](docs/HINDSIGHT.md)' "$repo_dir/README.md" || {
  print -ru2 -- "README must link to the Hindsight setup guide"
  exit 1
}

status_output="$tmp_dir/status.out"
if HOME="$test_home" \
  HINDSIGHT_EMBED_STACK_LIB="$rendered_stack_lib" \
  HINDSIGHT_EMBED_PROFILE="missing-profile" \
  zsh "$repo_dir/home/private_dot_local/bin/executable_hindsight-embed-service" status \
  >"$status_output" 2>&1; then
  print -ru2 -- "status unexpectedly succeeded for a missing profile"
  exit 1
fi

rg -F -q 'configured profile: missing (missing-profile)' "$status_output" || {
  print -ru2 -- "status did not report the missing profile"
  exit 1
}

mkdir -p "$test_home/Library/LaunchAgents" "$test_home/.local/bin"
(
  cd "$repo_dir"
  chezmoi execute-template < home/Library/LaunchAgents/com.hindsight.embed.stack.plist.tmpl \
    > "$test_home/Library/LaunchAgents/com.hindsight.embed.stack.plist"
)
touch "$test_home/.local/bin/hindsight-embed-supervisor"
chmod 700 "$test_home/.local/bin/hindsight-embed-supervisor"
runtime_helper="$tmp_dir/hindsight-embed-stop-profile-services.py"
touch "$runtime_helper"

(
  export HOME="$test_home"
  export HINDSIGHT_EMBED_AUTOSTART_UI=0
  export HINDSIGHT_EMBED_UVX="/usr/bin/true"
  export HINDSIGHT_EMBED_PYTHON="/usr/bin/true"
  export HINDSIGHT_EMBED_STOP_HELPER="$runtime_helper"
  export HINDSIGHT_EMBED_NPX="$tmp_dir/missing-npx"
  export HINDSIGHT_EMBED_UI_COMPAT_HELPER="$tmp_dir/missing-ui-compat-helper"
  source "$rendered_stack_lib"
  hindsight_stack_require_tools
  hindsight_stack_require_runtime_helpers
) || {
  print -ru2 -- "control/daemon-only stack unexpectedly required UI tooling"
  exit 1
}

assert_missing_profile_blocks_mutation() {
  local command="$1"
  local mutation_marker="$tmp_dir/${command}.mutated"
  local output="$tmp_dir/${command}.out"

  if (
    export HOME="$test_home"
    export HINDSIGHT_EMBED_STACK_LIB="$rendered_stack_lib"
    export HINDSIGHT_EMBED_PROFILE="missing-profile"
    export HINDSIGHT_EMBED_UVX="/usr/bin/true"
    export HINDSIGHT_EMBED_PYTHON="/usr/bin/true"
    export HINDSIGHT_EMBED_STOP_HELPER="$runtime_helper"
    export HINDSIGHT_EMBED_UI_COMPAT_HELPER="$runtime_helper"
    export HINDSIGHT_EMBED_NPX="/usr/bin/true"
    export HINDSIGHT_EMBED_CURL="/usr/bin/true"

    source "$service_lib"
    load_stack_lib

    bootout_if_loaded() {
      touch "$mutation_marker"
    }
    load_launchd_service() {
      touch "$mutation_marker"
    }

    case "$command" in
      start)
        start_launchd_service
        ;;
      install)
        install_service
        ;;
    esac
  ) >"$output" 2>&1; then
    print -ru2 -- "${command} unexpectedly succeeded for a missing profile"
    return 1
  fi

  if [[ -e "$mutation_marker" ]]; then
    print -ru2 -- "${command} reached a launchd mutation for a missing profile"
    return 1
  fi

  rg -F -q "configured profile 'missing-profile' does not exist" "$output" || {
    print -ru2 -- "${command} did not report the missing profile preflight"
    return 1
  }
}

assert_missing_profile_blocks_mutation start
assert_missing_profile_blocks_mutation install

auth_home="$test_home/hindsight-codex"
print -r -- "CODEX_HOME=${auth_home}" >> "$test_home/.hindsight/profiles/present-profile.env"
mock_codex="$tmp_dir/codex"
cat > "$mock_codex" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail
print -r -- "${CODEX_HOME}|$*" >> "${CODEX_TEST_CALLS}"
case "$*" in
  login)
    [[ "${CODEX_TEST_LOGIN_FAIL:-0}" == 0 ]] || exit 1
    mkdir -p "$CODEX_HOME"
    print -r -- '{"auth_mode":"chatgpt","tokens":{"access_token":"test"}}' > "$CODEX_HOME/auth.json"
    ;;
  'login status')
    ;;
  *)
    exit 2
    ;;
esac
EOF
chmod 700 "$mock_codex"

auth_calls="$tmp_dir/auth-calls"
service_calls="$tmp_dir/auth-refresh-service-calls"
mock_service="$tmp_dir/hindsight-embed-service"
cat > "$mock_service" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail
print -r -- "$*" >> "$HINDSIGHT_TEST_SERVICE_CALLS"
EOF
chmod 700 "$mock_service"

HOME="$test_home" \
  HINDSIGHT_EMBED_STACK_LIB="$rendered_stack_lib" \
  HINDSIGHT_EMBED_PROFILE="present-profile" \
  HINDSIGHT_EMBED_CODEX="$mock_codex" \
  HINDSIGHT_EMBED_SERVICE="$mock_service" \
  HINDSIGHT_TEST_SERVICE_CALLS="$service_calls" \
  CODEX_TEST_CALLS="$auth_calls" \
  zsh "$repo_dir/home/private_dot_local/bin/executable_hindsight-embed-service" auth-refresh

expected_auth_call="${auth_home}|login"
rg -Fx -q "$expected_auth_call" "$auth_calls" || {
  print -ru2 -- "auth refresh did not log in with the profile CODEX_HOME"
  exit 1
}
expected_status_call="${auth_home}|login status"
rg -Fx -q "$expected_status_call" "$auth_calls" || {
  print -ru2 -- "auth refresh did not verify the refreshed Codex login"
  exit 1
}
[[ "$(<"$service_calls")" == $'stop\nstart' ]] || {
  print -ru2 -- "auth refresh did not fully stop and start the managed stack after login"
  exit 1
}

failed_service_calls="$tmp_dir/failed-auth-refresh-service-calls"
if HOME="$test_home" \
  HINDSIGHT_EMBED_STACK_LIB="$rendered_stack_lib" \
  HINDSIGHT_EMBED_PROFILE="present-profile" \
  HINDSIGHT_EMBED_CODEX="$mock_codex" \
  HINDSIGHT_EMBED_SERVICE="$mock_service" \
  HINDSIGHT_TEST_SERVICE_CALLS="$failed_service_calls" \
  CODEX_TEST_CALLS="$auth_calls" \
  CODEX_TEST_LOGIN_FAIL=1 \
  zsh "$repo_dir/home/private_dot_local/bin/executable_hindsight-embed-service" auth-refresh \
  >/dev/null 2>&1; then
  print -ru2 -- "auth refresh unexpectedly succeeded after a failed Codex login"
  exit 1
fi
[[ ! -e "$failed_service_calls" ]] || {
  print -ru2 -- "auth refresh restarted the managed stack after a failed Codex login"
  exit 1
}

ui_health_calls="$tmp_dir/ui-health-calls"
mock_curl="$tmp_dir/curl"
cat > "$mock_curl" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail
print -r -- "$*" >> "$HINDSIGHT_TEST_CURL_CALLS"
exit "${HINDSIGHT_TEST_CURL_EXIT:-0}"
EOF
chmod 700 "$mock_curl"

mock_uvx="$tmp_dir/uvx"
cat > "$mock_uvx" <<'EOF'
#!/usr/bin/env zsh
exit 0
EOF
chmod 700 "$mock_uvx"

(
  export HOME="$test_home"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  export HINDSIGHT_EMBED_UVX="$mock_uvx"
  export HINDSIGHT_EMBED_CURL="$mock_curl"
  export HINDSIGHT_TEST_CURL_CALLS="$ui_health_calls"
  source "$rendered_stack_lib"
  hindsight_stack_ui_status
)

ui_health_args="$(<"$ui_health_calls")"
[[ "$ui_health_args" == *"--location"* && "$ui_health_args" == *"--max-redirs 8"* ]] || {
  print -ru2 -- "UI health check did not follow a bounded number of redirects"
  exit 1
}

if (
  export HOME="$test_home"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  export HINDSIGHT_EMBED_UVX="$mock_uvx"
  export HINDSIGHT_EMBED_CURL="$mock_curl"
  export HINDSIGHT_TEST_CURL_CALLS="$ui_health_calls"
  export HINDSIGHT_TEST_CURL_EXIT=47
  source "$rendered_stack_lib"
  hindsight_stack_ui_status
); then
  print -ru2 -- "UI health check accepted a redirect loop"
  exit 1
fi

reconcile_calls="$tmp_dir/reconcile-calls"
(
  export HOME="$test_home"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  source "$rendered_stack_lib"
  hindsight_stack_ui_status() { return 1 }
  hindsight_stack_can_start() { return 0 }
  hindsight_stack_mark_start() { print -r -- "mark" >> "$reconcile_calls" }
  hindsight_stack_log() { : }
  hindsight_stack_prepare_ui() { print -r -- "prepare" >> "$reconcile_calls" }
  hindsight_stack_ui_running() { return 0 }
  hindsight_stack_ui_stop() { print -r -- "stop" >> "$reconcile_calls" }
  hindsight_stack_wait_stopped_for() { print -r -- "wait-stopped" >> "$reconcile_calls" }
  hindsight_stack_ui_start_prepared() { print -r -- "start" >> "$reconcile_calls" }
  hindsight_stack_wait_ui() { print -r -- "wait-healthy" >> "$reconcile_calls" }
  hindsight_stack_reconcile_ui
)

[[ "$(<"$reconcile_calls")" == $'mark\nprepare\nstop\nwait-stopped\nstart\nwait-healthy' ]] || {
  print -ru2 -- "UI reconciliation did not replace the running unhealthy process before restart"
  exit 1
}
