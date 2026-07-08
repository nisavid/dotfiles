# Shared lifecycle helpers for the local Hindsight embed stack.

if (( ! ${+HINDSIGHT_EMBED_LAST_START_EPOCH} )); then
  typeset -gA HINDSIGHT_EMBED_LAST_START_EPOCH
fi

hindsight_stack_load_config() {
  emulate -L zsh
  setopt no_unset

  typeset -g HINDSIGHT_EMBED_UVX="${HINDSIGHT_EMBED_UVX:-$HOME/.local/bin/uvx}"
  typeset -g HINDSIGHT_EMBED_CONTROL_PORT="${HINDSIGHT_EMBED_CONTROL_PORT:-7878}"
  typeset -g HINDSIGHT_EMBED_PROFILE="${HINDSIGHT_EMBED_PROFILE:-systalyze}"
  typeset -g HINDSIGHT_EMBED_API_PORT="${HINDSIGHT_EMBED_API_PORT:-7979}"
  typeset -g HINDSIGHT_EMBED_UI_PORT="${HINDSIGHT_EMBED_UI_PORT:-17979}"
  typeset -g HINDSIGHT_EMBED_UI_HOSTNAME="${HINDSIGHT_EMBED_UI_HOSTNAME:-127.0.0.1}"
  typeset -g HINDSIGHT_EMBED_PYTHON="${HINDSIGHT_EMBED_PYTHON:-$HOME/.local/share/uv/tools/hindsight-embed/bin/python}"
  typeset -g HINDSIGHT_EMBED_STOP_HELPER="${HINDSIGHT_EMBED_STOP_HELPER:-$HOME/.local/libexec/hindsight-embed-stop-profile-services.py}"
  typeset -g HINDSIGHT_EMBED_AUTOSTART_DAEMON="${HINDSIGHT_EMBED_AUTOSTART_DAEMON:-1}"
  typeset -g HINDSIGHT_EMBED_AUTOSTART_UI="${HINDSIGHT_EMBED_AUTOSTART_UI:-1}"
  typeset -g HINDSIGHT_EMBED_CONTROL_WAIT_SECONDS="${HINDSIGHT_EMBED_CONTROL_WAIT_SECONDS:-30}"
  typeset -g HINDSIGHT_EMBED_DAEMON_WAIT_SECONDS="${HINDSIGHT_EMBED_DAEMON_WAIT_SECONDS:-120}"
  typeset -g HINDSIGHT_EMBED_UI_WAIT_SECONDS="${HINDSIGHT_EMBED_UI_WAIT_SECONDS:-60}"
  typeset -g HINDSIGHT_EMBED_STOP_WAIT_SECONDS="${HINDSIGHT_EMBED_STOP_WAIT_SECONDS:-30}"
  typeset -g HINDSIGHT_EMBED_START_COOLDOWN_SECONDS="${HINDSIGHT_EMBED_START_COOLDOWN_SECONDS:-20}"
}

hindsight_stack_timestamp() {
  emulate -L zsh
  /bin/date -u "+%Y-%m-%dT%H:%M:%SZ"
}

hindsight_stack_log() {
  emulate -L zsh
  print -r -- "$(hindsight_stack_timestamp) $*"
}

hindsight_stack_require_current_user() {
  emulate -L zsh
  if (( EUID == 0 || UID == 0 )); then
    print -ru2 -- "hindsight-embed-stack: refusing to run as root"
    return 1
  fi
}

hindsight_stack_require_tools() {
  emulate -L zsh
  hindsight_stack_load_config

  if [[ ! -x "$HINDSIGHT_EMBED_UVX" ]]; then
    print -ru2 -- "hindsight-embed-stack: uvx is not executable at ${HINDSIGHT_EMBED_UVX}"
    return 1
  fi
  if ! command -v /usr/bin/curl >/dev/null 2>&1; then
    print -ru2 -- "hindsight-embed-stack: missing /usr/bin/curl"
    return 1
  fi
}

hindsight_stack_enabled() {
  emulate -L zsh
  local value="${1:-}"

  case "$value" in
    1|true|TRUE|yes|YES|on|ON)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

hindsight_stack_http_ok() {
  emulate -L zsh
  local url="$1"

  /usr/bin/curl -fsS --max-time 2 "$url" >/dev/null 2>&1
}

hindsight_stack_run_stop_helper() {
  emulate -L zsh
  hindsight_stack_load_config

  [[ -x "$HINDSIGHT_EMBED_PYTHON" ]] || {
    print -ru2 -- "hindsight-embed-stack: missing executable Hindsight embed Python at ${HINDSIGHT_EMBED_PYTHON}"
    return 1
  }
  [[ -r "$HINDSIGHT_EMBED_STOP_HELPER" ]] || {
    print -ru2 -- "hindsight-embed-stack: missing stop helper at ${HINDSIGHT_EMBED_STOP_HELPER}"
    return 1
  }

  "$HINDSIGHT_EMBED_PYTHON" "$HINDSIGHT_EMBED_STOP_HELPER" \
    "$@"
}

hindsight_stack_stop_legacy_profile_ports() {
  emulate -L zsh
  hindsight_stack_load_config

  hindsight_stack_run_stop_helper \
    --mode normalize \
    --profile "$HINDSIGHT_EMBED_PROFILE" \
    --desired-api-port "$HINDSIGHT_EMBED_API_PORT" \
    --desired-ui-port "$HINDSIGHT_EMBED_UI_PORT" \
    --require-profile
}

hindsight_stack_stop_profile_services() {
  emulate -L zsh
  hindsight_stack_load_config
  local profile="$1"

  hindsight_stack_run_stop_helper \
    --mode stop \
    --profile "$profile" \
    --desired-api-port "$HINDSIGHT_EMBED_API_PORT" \
    --desired-ui-port "$HINDSIGHT_EMBED_UI_PORT"
}

hindsight_stack_write_profile_ports() {
  emulate -L zsh
  hindsight_stack_load_config

  "$HINDSIGHT_EMBED_UVX" hindsight-embed profile set-env \
    "$HINDSIGHT_EMBED_PROFILE" HINDSIGHT_API_PORT "$HINDSIGHT_EMBED_API_PORT" >/dev/null 2>&1 &&
    "$HINDSIGHT_EMBED_UVX" hindsight-embed profile set-env \
      "$HINDSIGHT_EMBED_PROFILE" HINDSIGHT_EMBED_CP_PORT "$HINDSIGHT_EMBED_UI_PORT" >/dev/null 2>&1
}

hindsight_stack_ensure_profile_ports() {
  emulate -L zsh
  hindsight_stack_load_config

  hindsight_stack_stop_legacy_profile_ports || return 1
  hindsight_stack_write_profile_ports
}

hindsight_stack_port_listening() {
  emulate -L zsh
  local port="$1"

  [[ -x /usr/sbin/lsof ]] || return 1
  /usr/sbin/lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

hindsight_stack_stop_owned_control_listener() {
  emulate -L zsh
  hindsight_stack_load_config

  [[ -x /usr/sbin/lsof ]] || return 1
  [[ -x /bin/ps ]] || return 1
  [[ -x /bin/kill ]] || return 1

  local -a pids
  local pid command lsof_output pid_file
  pid_file="${HOME}/.hindsight/control.pid"
  lsof_output="$(/usr/sbin/lsof -tiTCP:"$HINDSIGHT_EMBED_CONTROL_PORT" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "$lsof_output" ]]; then
    /bin/rm -f "$pid_file" 2>/dev/null || true
    return 0
  fi
  pids=("${(@f)lsof_output}")

  for pid in "${pids[@]}"; do
    command="$(/bin/ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ "$command" == *hindsight_embed.control_center.server* ]] &&
      [[ "$command" == *"--port ${HINDSIGHT_EMBED_CONTROL_PORT}"* || "$command" == *"--port=${HINDSIGHT_EMBED_CONTROL_PORT}"* ]]; then
      /bin/kill "$pid" 2>/dev/null || return 1
    else
      print -ru2 -- "hindsight-embed-stack: refusing to stop unverified listener on control port ${HINDSIGHT_EMBED_CONTROL_PORT} (pid ${pid})"
      return 1
    fi
  done

  integer i
  for (( i = 0; i < HINDSIGHT_EMBED_STOP_WAIT_SECONDS; i++ )); do
    if ! hindsight_stack_port_listening "$HINDSIGHT_EMBED_CONTROL_PORT"; then
      /bin/rm -f "$pid_file" 2>/dev/null || true
      return 0
    fi
    sleep 1
  done
  return 1
}

hindsight_stack_control_status() {
  emulate -L zsh
  hindsight_stack_load_config

  "$HINDSIGHT_EMBED_UVX" hindsight-embed control status \
    --port "$HINDSIGHT_EMBED_CONTROL_PORT" >/dev/null 2>&1
}

hindsight_stack_control_running() {
  emulate -L zsh
  hindsight_stack_load_config

  hindsight_stack_control_status ||
    hindsight_stack_http_ok "http://127.0.0.1:${HINDSIGHT_EMBED_CONTROL_PORT}" ||
    hindsight_stack_port_listening "$HINDSIGHT_EMBED_CONTROL_PORT"
}

hindsight_stack_daemon_status() {
  emulate -L zsh
  hindsight_stack_load_config

  "$HINDSIGHT_EMBED_UVX" hindsight-embed --profile "$HINDSIGHT_EMBED_PROFILE" daemon status >/dev/null 2>&1 &&
    hindsight_stack_http_ok "http://127.0.0.1:${HINDSIGHT_EMBED_API_PORT}/health"
}

hindsight_stack_daemon_running() {
  emulate -L zsh
  hindsight_stack_load_config

  "$HINDSIGHT_EMBED_UVX" hindsight-embed --profile "$HINDSIGHT_EMBED_PROFILE" daemon status >/dev/null 2>&1 ||
    hindsight_stack_http_ok "http://127.0.0.1:${HINDSIGHT_EMBED_API_PORT}/health" ||
    hindsight_stack_port_listening "$HINDSIGHT_EMBED_API_PORT"
}

hindsight_stack_ui_status() {
  emulate -L zsh
  hindsight_stack_load_config

  "$HINDSIGHT_EMBED_UVX" hindsight-embed --profile "$HINDSIGHT_EMBED_PROFILE" ui status \
    --port "$HINDSIGHT_EMBED_UI_PORT" >/dev/null 2>&1 &&
    hindsight_stack_http_ok "http://127.0.0.1:${HINDSIGHT_EMBED_UI_PORT}"
}

hindsight_stack_ui_running() {
  emulate -L zsh
  hindsight_stack_load_config

  "$HINDSIGHT_EMBED_UVX" hindsight-embed --profile "$HINDSIGHT_EMBED_PROFILE" ui status \
    --port "$HINDSIGHT_EMBED_UI_PORT" >/dev/null 2>&1 ||
    hindsight_stack_http_ok "http://127.0.0.1:${HINDSIGHT_EMBED_UI_PORT}" ||
    hindsight_stack_port_listening "$HINDSIGHT_EMBED_UI_PORT"
}

hindsight_stack_control_start() {
  emulate -L zsh
  hindsight_stack_load_config

  "$HINDSIGHT_EMBED_UVX" hindsight-embed control start --no-open \
    --port "$HINDSIGHT_EMBED_CONTROL_PORT" >/dev/null 2>&1
}

hindsight_stack_daemon_start() {
  emulate -L zsh
  hindsight_stack_load_config

  hindsight_stack_ensure_profile_ports || return 1
  "$HINDSIGHT_EMBED_UVX" hindsight-embed --profile "$HINDSIGHT_EMBED_PROFILE" daemon start >/dev/null 2>&1
}

hindsight_stack_ui_start() {
  emulate -L zsh
  hindsight_stack_load_config

  hindsight_stack_ensure_profile_ports || return 1
  "$HINDSIGHT_EMBED_UVX" hindsight-embed --profile "$HINDSIGHT_EMBED_PROFILE" ui start \
    --port "$HINDSIGHT_EMBED_UI_PORT" \
    --hostname "$HINDSIGHT_EMBED_UI_HOSTNAME" >/dev/null 2>&1
}

hindsight_stack_control_stop() {
  emulate -L zsh
  hindsight_stack_load_config

  hindsight_stack_stop_owned_control_listener
}

hindsight_stack_daemon_stop() {
  emulate -L zsh
  hindsight_stack_load_config

  hindsight_stack_run_stop_helper \
    --mode stop-api \
    --profile "$HINDSIGHT_EMBED_PROFILE" \
    --desired-api-port "$HINDSIGHT_EMBED_API_PORT"
}

hindsight_stack_ui_stop() {
  emulate -L zsh
  hindsight_stack_load_config

  hindsight_stack_run_stop_helper \
    --mode stop-ui \
    --profile "$HINDSIGHT_EMBED_PROFILE" \
    --desired-ui-port "$HINDSIGHT_EMBED_UI_PORT"
}

hindsight_stack_can_start() {
  emulate -L zsh
  hindsight_stack_load_config

  local component="$1"
  integer now last
  now="$(/bin/date +%s)"
  last="${HINDSIGHT_EMBED_LAST_START_EPOCH[$component]:-0}"

  (( now - last >= HINDSIGHT_EMBED_START_COOLDOWN_SECONDS ))
}

hindsight_stack_mark_start() {
  emulate -L zsh
  local component="$1"

  HINDSIGHT_EMBED_LAST_START_EPOCH[$component]="$(/bin/date +%s)"
}

hindsight_stack_wait_for() {
  emulate -L zsh
  setopt no_unset

  local component="$1"
  integer timeout_seconds="$2"
  integer deadline
  deadline=$(( $(/bin/date +%s) + timeout_seconds ))

  while (( $(/bin/date +%s) <= deadline )); do
    case "$component" in
      control)
        hindsight_stack_control_status && return 0
        ;;
      daemon)
        hindsight_stack_daemon_status && return 0
        ;;
      ui)
        hindsight_stack_ui_status && return 0
        ;;
      *)
        print -ru2 -- "hindsight-embed-stack: unknown component: ${component}"
        return 2
        ;;
    esac
    sleep 2
  done

  return 1
}

hindsight_stack_wait_control() {
  emulate -L zsh
  hindsight_stack_load_config
  hindsight_stack_wait_for control "$HINDSIGHT_EMBED_CONTROL_WAIT_SECONDS"
}

hindsight_stack_wait_daemon() {
  emulate -L zsh
  hindsight_stack_load_config
  hindsight_stack_wait_for daemon "$HINDSIGHT_EMBED_DAEMON_WAIT_SECONDS"
}

hindsight_stack_wait_ui() {
  emulate -L zsh
  hindsight_stack_load_config
  hindsight_stack_wait_for ui "$HINDSIGHT_EMBED_UI_WAIT_SECONDS"
}

hindsight_stack_wait_stopped_for() {
  emulate -L zsh
  setopt no_unset

  local component="$1"
  integer timeout_seconds="$2"
  integer deadline
  deadline=$(( $(/bin/date +%s) + timeout_seconds ))

  while (( $(/bin/date +%s) <= deadline )); do
    case "$component" in
      control)
        hindsight_stack_control_running || return 0
        ;;
      daemon)
        hindsight_stack_daemon_running || return 0
        ;;
      ui)
        hindsight_stack_ui_running || return 0
        ;;
      *)
        print -ru2 -- "hindsight-embed-stack: unknown component: ${component}"
        return 2
        ;;
    esac
    sleep 2
  done

  return 1
}

hindsight_stack_reconcile_control() {
  emulate -L zsh

  if hindsight_stack_control_status; then
    return 0
  fi

  if ! hindsight_stack_can_start control; then
    return 1
  fi

  hindsight_stack_mark_start control
  hindsight_stack_log "control is not healthy; starting"
  if ! hindsight_stack_control_start; then
    hindsight_stack_log "control start command failed"
    return 1
  fi
  hindsight_stack_wait_control
}

hindsight_stack_reconcile_daemon() {
  emulate -L zsh

  hindsight_stack_ensure_profile_ports || return 1
  if hindsight_stack_daemon_status; then
    return 0
  fi

  if ! hindsight_stack_can_start daemon; then
    return 1
  fi

  hindsight_stack_mark_start daemon
  hindsight_stack_log "daemon is not healthy; starting ${HINDSIGHT_EMBED_PROFILE}"
  if ! hindsight_stack_daemon_start; then
    hindsight_stack_log "daemon start command failed"
    return 1
  fi
  hindsight_stack_wait_daemon
}

hindsight_stack_reconcile_ui() {
  emulate -L zsh

  if hindsight_stack_ui_status; then
    return 0
  fi

  if ! hindsight_stack_can_start ui; then
    return 1
  fi

  hindsight_stack_mark_start ui
  hindsight_stack_log "ui is not healthy; starting ${HINDSIGHT_EMBED_PROFILE}"
  if ! hindsight_stack_ui_start; then
    hindsight_stack_log "ui start command failed"
    return 1
  fi
  hindsight_stack_wait_ui
}

hindsight_stack_reconcile_once() {
  emulate -L zsh
  hindsight_stack_load_config

  local ok=0

  if ! hindsight_stack_reconcile_control; then
    ok=1
  fi

  if hindsight_stack_enabled "$HINDSIGHT_EMBED_AUTOSTART_DAEMON"; then
    if ! hindsight_stack_reconcile_daemon; then
      ok=1
    fi
  fi

  if hindsight_stack_enabled "$HINDSIGHT_EMBED_AUTOSTART_UI" && hindsight_stack_daemon_status; then
    if ! hindsight_stack_reconcile_ui; then
      ok=1
    fi
  fi

  return "$ok"
}

hindsight_stack_start_all() {
  emulate -L zsh
  hindsight_stack_require_current_user || return 1
  hindsight_stack_require_tools || return 1

  hindsight_stack_control_status || hindsight_stack_control_start
  hindsight_stack_wait_control || return 1

  if hindsight_stack_enabled "$HINDSIGHT_EMBED_AUTOSTART_DAEMON"; then
    hindsight_stack_ensure_profile_ports || return 1
    hindsight_stack_daemon_status || hindsight_stack_daemon_start
    hindsight_stack_wait_daemon || return 1
  fi

  if hindsight_stack_enabled "$HINDSIGHT_EMBED_AUTOSTART_UI"; then
    hindsight_stack_ui_status || hindsight_stack_ui_start
    hindsight_stack_wait_ui || return 1
  fi
}

hindsight_stack_stop_all() {
  emulate -L zsh
  hindsight_stack_load_config

  local ok=0
  hindsight_stack_stop_profile_services "$HINDSIGHT_EMBED_PROFILE" || ok=1
  hindsight_stack_wait_stopped_for ui "$HINDSIGHT_EMBED_STOP_WAIT_SECONDS" || ok=1
  hindsight_stack_wait_stopped_for daemon "$HINDSIGHT_EMBED_STOP_WAIT_SECONDS" || ok=1
  hindsight_stack_control_stop || true
  hindsight_stack_wait_stopped_for control "$HINDSIGHT_EMBED_STOP_WAIT_SECONDS" || ok=1
  return "$ok"
}

hindsight_stack_status_word() {
  emulate -L zsh
  local component="$1"

  case "$component" in
    control)
      hindsight_stack_control_status && print -r -- "healthy" || print -r -- "down"
      ;;
    daemon)
      hindsight_stack_daemon_status && print -r -- "healthy" || print -r -- "down"
      ;;
    ui)
      hindsight_stack_ui_status && print -r -- "healthy" || print -r -- "down"
      ;;
    *)
      print -r -- "unknown"
      return 2
      ;;
  esac
}

hindsight_stack_status_report() {
  emulate -L zsh
  hindsight_stack_load_config

  print -r -- "control: $(hindsight_stack_status_word control) (http://localhost:${HINDSIGHT_EMBED_CONTROL_PORT})"
  print -r -- "daemon: $(hindsight_stack_status_word daemon) (${HINDSIGHT_EMBED_PROFILE}, http://127.0.0.1:${HINDSIGHT_EMBED_API_PORT})"
  print -r -- "ui: $(hindsight_stack_status_word ui) (${HINDSIGHT_EMBED_PROFILE}, http://127.0.0.1:${HINDSIGHT_EMBED_UI_PORT})"
}
