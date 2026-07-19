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
touch "$test_home/.hindsight/profiles/present-profile.env"

desired_state_dir="$tmp_dir/desired-state"
actual_startup_id="$({ source "$rendered_stack_lib"; hindsight_stack_startup_id; })"
[[ "$actual_startup_id" == asid:<-> ]] || {
  print -ru2 -- "stack did not derive the current GUI login identity: ${actual_startup_id}"
  exit 1
}
outside_desired_state="$tmp_dir/outside-desired-state"
mkdir -p "$outside_desired_state"
ln -s "$outside_desired_state" "$tmp_dir/linked-desired-state"
if (
  export HOME="$test_home"
  export HINDSIGHT_EMBED_STATE_DIR="$tmp_dir/linked-state-parent"
  export HINDSIGHT_EMBED_DESIRED_STATE_DIR="$tmp_dir/linked-desired-state"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  source "$rendered_stack_lib"
  hindsight_stack_set_desired_state daemon stopped
) >/dev/null 2>&1; then
  print -ru2 -- "stack accepted a symlinked desired-state root"
  exit 1
fi
[[ ! -e "$outside_desired_state/profiles" ]] || {
  print -ru2 -- "stack followed a symlinked desired-state root before rejecting it"
  exit 1
}

(
  export HOME="$test_home"
  export HINDSIGHT_EMBED_STATE_DIR="$desired_state_dir"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  export HINDSIGHT_EMBED_FLEET_PROFILES="present-profile"
  export HINDSIGHT_EMBED_API_PORT=7979
  export HINDSIGHT_EMBED_UI_PORT=17979
  export HINDSIGHT_EMBED_AUTOSTART_DAEMON=1
  export HINDSIGHT_EMBED_AUTOSTART_UI=1
  source "$rendered_stack_lib"
  (( $+functions[hindsight_stack_initialize_desired_state] )) || {
    print -ru2 -- "stack does not implement desired-state initialization"
    exit 1
  }

  (( $+functions[hindsight_stack_startup_id] )) || {
    print -ru2 -- "stack does not implement login-scoped startup identity"
    exit 1
  }
  hindsight_stack_startup_id() { print -r -- login-one }
  hindsight_stack_initialize_desired_state
  [[ "$(hindsight_stack_desired_state daemon)" == running ]] || exit 1
  [[ "$(hindsight_stack_desired_state ui)" == running ]] || exit 1

  hindsight_stack_set_desired_state daemon stopped
  hindsight_stack_set_desired_state ui stopped
  hindsight_stack_initialize_desired_state
  [[ "$(hindsight_stack_desired_state daemon)" == stopped ]] || {
    print -ru2 -- "same-boot initialization discarded the intentional daemon stop"
    exit 1
  }
  [[ "$(hindsight_stack_desired_state ui)" == stopped ]] || {
    print -ru2 -- "same-boot initialization discarded the intentional UI stop"
    exit 1
  }

  hindsight_stack_startup_id() { print -r -- login-two }
  hindsight_stack_initialize_desired_state
  [[ "$(hindsight_stack_desired_state daemon)" == running ]] || {
    print -ru2 -- "new-login initialization did not restore daemon autostart"
    exit 1
  }
  [[ "$(hindsight_stack_desired_state ui)" == running ]] || {
    print -ru2 -- "new-login initialization did not restore UI autostart"
    exit 1
  }
)

reconcile_start_marker="$tmp_dir/reconcile-started"
(
  export HOME="$test_home"
  export HINDSIGHT_EMBED_STATE_DIR="$desired_state_dir"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  export HINDSIGHT_EMBED_FLEET_PROFILES="present-profile"
  export HINDSIGHT_EMBED_API_PORT=7979
  export HINDSIGHT_EMBED_UI_PORT=17979
  export HINDSIGHT_EMBED_START_COOLDOWN_SECONDS=0
  export HINDSIGHT_TEST_RECONCILE_START_MARKER="$reconcile_start_marker"
  source "$rendered_stack_lib"
  (( $+functions[hindsight_stack_set_desired_state] )) || {
    print -ru2 -- "stack does not implement component desired state"
    exit 1
  }
  hindsight_stack_daemon_status() { return 1 }
  hindsight_stack_daemon_start() { print -r -- daemon >> "$HINDSIGHT_TEST_RECONCILE_START_MARKER" }
  hindsight_stack_wait_daemon() { return 0 }
  hindsight_stack_ui_status() { return 1 }
  hindsight_stack_ui_start() { print -r -- ui >> "$HINDSIGHT_TEST_RECONCILE_START_MARKER" }
  hindsight_stack_wait_ui() { return 0 }

  hindsight_stack_set_desired_state daemon running
  hindsight_stack_set_desired_state ui running
  hindsight_stack_reconcile_daemon
  hindsight_stack_reconcile_ui
  [[ "$(paste -sd, "$HINDSIGHT_TEST_RECONCILE_START_MARKER")" == daemon,ui ]] || {
    print -ru2 -- "desired-running components were not reconciled after failure"
    exit 1
  }

  : > "$HINDSIGHT_TEST_RECONCILE_START_MARKER"
  hindsight_stack_set_desired_state daemon stopped
  hindsight_stack_set_desired_state ui stopped
  hindsight_stack_reconcile_daemon
  hindsight_stack_reconcile_ui
  [[ ! -s "$HINDSIGHT_TEST_RECONCILE_START_MARKER" ]] || {
    print -ru2 -- "intentionally stopped components were restarted"
    exit 1
  }
)

intentional_status="$tmp_dir/intentional-status"
(
  export HOME="$test_home"
  export HINDSIGHT_EMBED_STATE_DIR="$desired_state_dir"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  export HINDSIGHT_EMBED_FLEET_PROFILES="present-profile"
  export HINDSIGHT_EMBED_API_PORT=7979
  export HINDSIGHT_EMBED_UI_PORT=17979
  source "$rendered_stack_lib"
  hindsight_stack_broker_status() { return 0 }
  hindsight_stack_control_status() { return 0 }
  hindsight_stack_daemon_status() { return 1 }
  hindsight_stack_ui_status() { return 1 }
  hindsight_stack_sidecar_names() { return 0 }
  hindsight_stack_set_desired_state daemon stopped
  hindsight_stack_set_desired_state ui stopped
  hindsight_stack_status_report > "$intentional_status"
)
rg -F -q 'fleet: healthy (1 enabled profile)' "$intentional_status" || {
  print -ru2 -- "intentional stops degraded fleet status"
  exit 1
}
rg -F -q 'api=stopped@7979 ui=stopped@17979' "$intentional_status" || {
  print -ru2 -- "status did not distinguish intentional stops from failures"
  exit 1
}

restart_events="$tmp_dir/restart-events"
(
  source "$service_lib"
  (( $+functions[restart_service] )) || {
    print -ru2 -- "service does not implement restart"
    exit 1
  }
  preflight_launchd_service() { print -r -- preflight >> "$restart_events" }
  bootout_if_loaded() { print -r -- bootout >> "$restart_events" }
  hindsight_stack_stop_all() { print -r -- stop >> "$restart_events" }
  hindsight_stack_reset_desired_state() { print -r -- reset >> "$restart_events" }
  load_launchd_service() { print -r -- load >> "$restart_events" }
  typeset -g HINDSIGHT_EMBED_STACK_LIB_LOADED=1
  restart_service
)
[[ "$(paste -sd, "$restart_events")" == preflight,bootout,stop,reset,load ]] || {
  print -ru2 -- "restart did not perform a validated clean stop/start: $(paste -sd, "$restart_events")"
  exit 1
}

(
  export HOME="$test_home"
  export HINDSIGHT_EMBED_STATE_DIR="$desired_state_dir"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  export HINDSIGHT_EMBED_FLEET_PROFILES="present-profile"
  source "$rendered_stack_lib"
  hindsight_stack_stop_profile_services() { return 1 }
  hindsight_stack_wait_stopped_for() { return 0 }
  hindsight_stack_stop_sidecars() { return 0 }
  hindsight_stack_wait_sidecars_stopped() { return 0 }
  hindsight_stack_stop_profile present-profile
) || {
  print -ru2 -- "profile stop treated a transient stop-command timeout as a final failure"
  exit 1
}

(
  export HOME="$test_home"
  export HINDSIGHT_EMBED_STATE_DIR="$desired_state_dir"
  export HINDSIGHT_EMBED_PROFILE="present-profile"
  export HINDSIGHT_EMBED_FLEET_PROFILES="present-profile"
  source "$rendered_stack_lib"
  hindsight_stack_require_current_user() { return 0 }
  hindsight_stack_for_each_profile() { return 0 }
  hindsight_stack_broker_running() { return 0 }
  hindsight_stack_broker_stop() { return 1 }
  hindsight_stack_wait_stopped_for() { return 0 }
  hindsight_stack_control_running() { return 1 }
  hindsight_stack_stop_all
) || {
  print -ru2 -- "stack stop treated a transient broker stop-command timeout as a final failure"
  exit 1
}

help_output="$(zsh "$repo_dir/home/private_dot_local/bin/executable_hindsight-embed-service" --help)"
print -r -- "$help_output" | rg -F -q 'restart' || {
  print -ru2 -- "service help does not expose restart"
  exit 1
}

restart_dispatch="$tmp_dir/restart-dispatch"
(
  export HINDSIGHT_TEST_RESTART_DISPATCH="$restart_dispatch"
  source "$service_lib"
  load_stack_lib() { return 0 }
  restart_service() { touch "$HINDSIGHT_TEST_RESTART_DISPATCH" }
  main restart
)
[[ -e "$restart_dispatch" ]] || {
  print -ru2 -- "service main did not dispatch restart"
  exit 1
}
