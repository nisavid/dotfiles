#!/usr/bin/env zsh
set -euo pipefail

repo_dir="${0:A:h:h}"
tmp_dir="$(mktemp -d)"
trap 'rm -rf -- "$tmp_dir"' EXIT

rendered_stack_lib="$tmp_dir/hindsight-embed-stack.zsh"
(
  cd "$repo_dir"
  chezmoi -S "$repo_dir/home" \
    --override-data-file "$repo_dir/home/.chezmoidata/hindsight.toml" \
    execute-template < home/private_dot_local/lib/hindsight-embed-stack.zsh.tmpl > "$rendered_stack_lib"
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

touch "$test_home/.hindsight/profiles/second-profile.env"
mkdir -p "$test_home/.hindsight/profiles/present-profile.sidecars/reranker"
sidecar_test_port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
export HINDSIGHT_TEST_SIDECAR_PORT="$sidecar_test_port"
print -r -- "$sidecar_test_port" > "$test_home/.hindsight/profiles/present-profile.sidecars/reranker/port-base"
print -r -- "/healthz" > "$test_home/.hindsight/profiles/present-profile.sidecars/reranker/health-path"

fleet_state="$tmp_dir/fleet-state"
(
  export HOME="$test_home"
  export HINDSIGHT_EMBED_STATE_DIR="$fleet_state"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  export HINDSIGHT_EMBED_FLEET_PROFILES="present-profile,second-profile"
  export HINDSIGHT_EMBED_API_PORT=7979
  export HINDSIGHT_EMBED_UI_PORT=17979
  source "$rendered_stack_lib"

  profiles="$(hindsight_stack_enabled_profiles | paste -sd, -)"
  [[ "$profiles" == "present-profile,second-profile" ]] || {
    print -ru2 -- "fleet did not retain enabled profile order: ${profiles}"
    exit 1
  }
  hindsight_stack_require_fleet_profiles
  hindsight_stack_validate_fleet

  hindsight_stack_select_profile present-profile
  [[ "$HINDSIGHT_EMBED_PROFILE_SLOT" == 0 ]] || exit 1
  [[ "$HINDSIGHT_EMBED_API_PORT" == 7979 ]] || exit 1
  [[ "$HINDSIGHT_EMBED_UI_PORT" == 17979 ]] || exit 1
  [[ "$(hindsight_stack_sidecar_port reranker)" == "$HINDSIGHT_TEST_SIDECAR_PORT" ]] || exit 1
  [[ "$(hindsight_stack_sidecar_health_url reranker)" == "http://127.0.0.1:${HINDSIGHT_TEST_SIDECAR_PORT}/healthz" ]] || exit 1
  sidecar_probe="$tmp_dir/sidecar-probe"
  hindsight_stack_http_ok() {
    print -r -- "$1" > "$sidecar_probe"
    return 0
  }
  hindsight_stack_sidecars_status
  [[ "$(<"$sidecar_probe")" == "http://127.0.0.1:${HINDSIGHT_TEST_SIDECAR_PORT}/healthz" ]] || {
    print -ru2 -- "sidecar readiness did not probe the slot-derived endpoint"
    exit 1
  }

  hindsight_stack_select_profile second-profile
  [[ "$HINDSIGHT_EMBED_PROFILE_SLOT" == 1 ]] || exit 1
  [[ "$HINDSIGHT_EMBED_API_PORT" == 7980 ]] || exit 1
  [[ "$HINDSIGHT_EMBED_UI_PORT" == 17980 ]] || exit 1
  export HINDSIGHT_EMBED_PROFILE_SECOND_PROFILE_API_PORT=7979
  if hindsight_stack_validate_fleet >/dev/null 2>&1; then
    print -ru2 -- "fleet collision unexpectedly validated"
    exit 1
  fi
  unset HINDSIGHT_EMBED_PROFILE_SECOND_PROFILE_API_PORT
  [[ "$HINDSIGHT_EMBED_PROFILE" == second-profile ]] || {
    print -ru2 -- "failed fleet traversal leaked the selected profile"
    exit 1
  }
  [[ "$HINDSIGHT_EMBED_PROFILE_SLOT" == 1 && "$HINDSIGHT_EMBED_API_PORT" == 7980 && "$HINDSIGHT_EMBED_UI_PORT" == 17980 ]] || {
    print -ru2 -- "failed fleet traversal leaked derived profile state"
    exit 1
  }
)

unsafe_lock_state="$tmp_dir/unsafe-lock-state"
dangling_lock_target="$tmp_dir/dangling-lock-target"
mkdir -p "$unsafe_lock_state/profile-slots"
ln -s "$dangling_lock_target" "$unsafe_lock_state/profile-slots/.allocation.lock"
if (
  export HOME="$test_home"
  export HINDSIGHT_EMBED_STATE_DIR="$unsafe_lock_state"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  export HINDSIGHT_EMBED_FLEET_PROFILES="present-profile,second-profile"
  source "$rendered_stack_lib"
  hindsight_stack_profile_slot present-profile
) >/dev/null 2>&1; then
  print -ru2 -- "profile slot allocation accepted a dangling lock symlink"
  exit 1
fi
[[ ! -e "$dangling_lock_target" ]] || {
  print -ru2 -- "profile slot allocation followed a dangling lock symlink"
  exit 1
}

filtered_status="$tmp_dir/filtered-status.out"
(
  export HOME="$test_home"
  export HINDSIGHT_EMBED_STATE_DIR="$fleet_state"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  export HINDSIGHT_EMBED_FLEET_PROFILES="present-profile,missing-profile"
  source "$rendered_stack_lib"
  hindsight_stack_broker_status() { return 0 }
  hindsight_stack_control_status() { return 0 }
  hindsight_stack_daemon_status() { return 0 }
  hindsight_stack_ui_status() { return 0 }
  hindsight_stack_sidecar_names() { return 0 }
  hindsight_stack_status_report present-profile > "$filtered_status"
)
rg -F -q 'fleet: healthy (1 enabled profile)' "$filtered_status" || {
  print -ru2 -- "filtered status was degraded by an unrelated unselectable profile"
  exit 1
}

(
  export HOME="$test_home"
  export HINDSIGHT_EMBED_STATE_DIR="$fleet_state"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  export HINDSIGHT_EMBED_FLEET_PROFILES="second-profile,present-profile"
  export HINDSIGHT_EMBED_API_PORT=7979
  export HINDSIGHT_EMBED_UI_PORT=17979
  source "$rendered_stack_lib"
  hindsight_stack_select_profile present-profile
  [[ "$HINDSIGHT_EMBED_PROFILE_SLOT" == 0 ]] || {
    print -ru2 -- "persisted profile slot changed after fleet reorder"
    exit 1
  }
  hindsight_stack_select_profile second-profile
  [[ "$HINDSIGHT_EMBED_PROFILE_SLOT" == 1 ]] || exit 1
)

[[ "$(stat -f '%Lp' "$fleet_state/profile-slots/present-profile.slot")" == 600 ]] || {
  print -ru2 -- "persisted profile slot is not mode 0600"
  exit 1
}

sidecar_dir="$test_home/.hindsight/profiles/present-profile.sidecars/reranker"
cat > "$sidecar_dir/status" <<'ZSH'
#!/usr/bin/env zsh
[[ -e "$HINDSIGHT_TEST_SIDECAR_MARKER" ]]
ZSH
cat > "$sidecar_dir/start" <<'ZSH'
#!/usr/bin/env zsh
print -r -- "${HINDSIGHT_EMBED_PROFILE}:${HINDSIGHT_EMBED_PROFILE_SLOT}:${HINDSIGHT_EMBED_SIDECAR_NAME}:${HINDSIGHT_EMBED_SIDECAR_PORT}" > "$HINDSIGHT_TEST_SIDECAR_START"
touch "$HINDSIGHT_TEST_SIDECAR_MARKER"
ZSH
cat > "$sidecar_dir/stop" <<'ZSH'
#!/usr/bin/env zsh
rm -f "$HINDSIGHT_TEST_SIDECAR_MARKER"
ZSH
chmod 700 "$sidecar_dir/status" "$sidecar_dir/start" "$sidecar_dir/stop"
sidecar_marker="$tmp_dir/sidecar-running"
sidecar_start="$tmp_dir/sidecar-start"
(
  export HOME="$test_home"
  export HINDSIGHT_EMBED_STATE_DIR="$fleet_state"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  export HINDSIGHT_EMBED_FLEET_PROFILES="present-profile,second-profile"
  export HINDSIGHT_EMBED_API_PORT=7979
  export HINDSIGHT_EMBED_UI_PORT=17979
  export HINDSIGHT_EMBED_START_COOLDOWN_SECONDS=0
  export HINDSIGHT_TEST_SIDECAR_MARKER="$sidecar_marker"
  export HINDSIGHT_TEST_SIDECAR_START="$sidecar_start"
  source "$rendered_stack_lib"
  hindsight_stack_select_profile present-profile
  hindsight_stack_reconcile_sidecars >/dev/null
  [[ "$(<"$sidecar_start")" == "present-profile:0:reranker:${HINDSIGHT_TEST_SIDECAR_PORT}" ]] || exit 1
  hindsight_stack_sidecars_status
  hindsight_stack_stop_sidecars
  hindsight_stack_wait_sidecars_stopped
  [[ ! -e "$sidecar_marker" ]]
)

reconcile_events="$tmp_dir/reconcile-events"
(
  export HOME="$test_home"
  export HINDSIGHT_EMBED_STATE_DIR="$fleet_state"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  export HINDSIGHT_EMBED_FLEET_PROFILES="present-profile,second-profile"
  export HINDSIGHT_EMBED_API_PORT=7979
  export HINDSIGHT_EMBED_UI_PORT=17979
  export HINDSIGHT_EMBED_AUTOSTART_DAEMON=1
  export HINDSIGHT_EMBED_AUTOSTART_UI=1
  source "$rendered_stack_lib"
  hindsight_stack_reconcile_broker() { print -r -- broker >> "$reconcile_events" }
  hindsight_stack_reconcile_control() { print -r -- control >> "$reconcile_events" }
  hindsight_stack_reconcile_sidecars() { print -r -- "sidecars:${HINDSIGHT_EMBED_PROFILE}" >> "$reconcile_events" }
  hindsight_stack_reconcile_daemon() { print -r -- "daemon:${HINDSIGHT_EMBED_PROFILE}:${HINDSIGHT_EMBED_API_PORT}" >> "$reconcile_events" }
  hindsight_stack_daemon_status() { return 0 }
  hindsight_stack_daemon_present() { return 0 }
  hindsight_stack_reconcile_ui() { print -r -- "ui:${HINDSIGHT_EMBED_PROFILE}:${HINDSIGHT_EMBED_UI_PORT}" >> "$reconcile_events" }
  hindsight_stack_reconcile_once
)
for expected in \
  broker control \
  sidecars:present-profile daemon:present-profile:7979 ui:present-profile:17979 \
  sidecars:second-profile daemon:second-profile:7980 ui:second-profile:17980; do
  rg -F -x -q "$expected" "$reconcile_events" || {
    print -ru2 -- "fleet reconcile omitted ${expected}"
    exit 1
  }
done

collision_output="$tmp_dir/collision.out"
if (
  export HOME="$test_home"
  export HINDSIGHT_EMBED_STATE_DIR="$fleet_state"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  export HINDSIGHT_EMBED_FLEET_PROFILES="present-profile,second-profile"
  export HINDSIGHT_EMBED_API_PORT=7979
  export HINDSIGHT_EMBED_UI_PORT=17979
  export HINDSIGHT_EMBED_PROFILE_SECOND_PROFILE_API_PORT=7979
  source "$rendered_stack_lib"
  hindsight_stack_validate_fleet
) >"$collision_output" 2>&1; then
  print -ru2 -- "fleet validation accepted colliding profile endpoints"
  exit 1
fi
rg -F -q 'endpoint collision on port 7979' "$collision_output" || {
  print -ru2 -- "fleet validation did not identify the colliding port"
  exit 1
}

fake_memory_cli="$tmp_dir/fake-hindsight-memory"
cat > "$fake_memory_cli" <<'ZSH'
#!/usr/bin/env zsh
print -r -- "$@" > "$HINDSIGHT_TEST_BROKER_ARGS"
print -ru2 -- "broker output must be detached"
ZSH
chmod 700 "$fake_memory_cli"
broker_args="$tmp_dir/broker-args"
broker_output="$tmp_dir/broker-output"
(
  unsetopt BG_NICE
  export HOME="$test_home"
  export HINDSIGHT_EMBED_STATE_DIR="$fleet_state"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  export HINDSIGHT_EMBED_FLEET_PROFILES="present-profile,second-profile"
  export HINDSIGHT_MEMORY_CLI="$fake_memory_cli"
  export HINDSIGHT_TEST_BROKER_ARGS="$broker_args"
  source "$rendered_stack_lib"
  hindsight_stack_broker_start >"$broker_output" 2>&1
  wait
)
[[ ! -s "$broker_output" ]] || {
  print -ru2 -- "broker start inherited caller output descriptors"
  exit 1
}
broker_command="$(<"$broker_args")"
[[ "$broker_command" == *'broker serve'* &&
  "$broker_command" == *'--profile present-profile --profile second-profile'* ]] || {
  print -ru2 -- "broker did not receive the complete enabled-profile fleet: ${broker_command}"
  exit 1
}

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

configured_profile="$(chezmoi --override-data-file "$repo_dir/home/.chezmoidata/hindsight.toml" execute-template '{{ .hindsight.profile }}')"
configured_bank="$(chezmoi --override-data-file "$repo_dir/home/.chezmoidata/hindsight.toml" execute-template '{{ .hindsight.bank }}')"
fenced_setup_commands="$(awk '
  /^```/ { in_fence = !in_fence; next }
  in_fence { print }
' "$repo_dir/docs/HINDSIGHT.md")"
if print -r -- "$fenced_setup_commands" | rg -F -n -e "$configured_profile" -e "$configured_bank" >/dev/null; then
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
  chezmoi -S "$repo_dir/home" \
    --override-data-file "$repo_dir/home/.chezmoidata/hindsight.toml" \
    execute-template < home/private_Library/private_LaunchAgents/com.hindsight.embed.stack.plist.tmpl \
    > "$test_home/Library/LaunchAgents/com.hindsight.embed.stack.plist"
)
touch "$test_home/.local/bin/hindsight-embed-supervisor"
chmod 700 "$test_home/.local/bin/hindsight-embed-supervisor"
runtime_helper="$tmp_dir/hindsight-embed-stop-profile-services.py"
touch "$runtime_helper"
control_server="$tmp_dir/hindsight-embed-control-server.py"
touch "$control_server"

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
    export HINDSIGHT_EMBED_CONTROL_SERVER="$control_server"

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

(
  source "$service_lib"
  is_loaded() { return 1 }
  service_name() { print -r -- "$1" }
  has_disabled_override() { return 1 }
  show_installed_file_checks() { return 0 }
  hindsight_stack_status_report() { return 23 }
  typeset -g HINDSIGHT_EMBED_STACK_LIB_LOADED=1
  if show_status >/dev/null 2>&1; then
    print -ru2 -- "status ignored a stack status-report failure"
    exit 1
  fi
)

help_output="$(zsh "$repo_dir/home/private_dot_local/bin/executable_hindsight-embed-service" --help)"
print -r -- "$help_output" | rg -F -q 'status [--profile <name>]' || {
  print -ru2 -- "service help does not expose additive profile selection"
  exit 1
}

selected_profile_file="$tmp_dir/selected-profile"
(
  export HINDSIGHT_TEST_SELECTED_PROFILE_FILE="$selected_profile_file"
  source "$service_lib"
  show_status() { print -r -- "$1" > "$HINDSIGHT_TEST_SELECTED_PROFILE_FILE" }
  main status --profile second-profile
)
[[ "$(<"$selected_profile_file")" == second-profile ]] || {
  print -ru2 -- "status --profile did not select the requested enabled profile"
  exit 1
}
