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
  typeset -g HINDSIGHT_EMBED_AUTOSTART_DAEMON="${HINDSIGHT_EMBED_AUTOSTART_DAEMON:-1}"
  typeset -g HINDSIGHT_EMBED_AUTOSTART_UI="${HINDSIGHT_EMBED_AUTOSTART_UI:-1}"
  typeset -g HINDSIGHT_EMBED_CONTROL_WAIT_SECONDS="${HINDSIGHT_EMBED_CONTROL_WAIT_SECONDS:-30}"
  typeset -g HINDSIGHT_EMBED_DAEMON_WAIT_SECONDS="${HINDSIGHT_EMBED_DAEMON_WAIT_SECONDS:-120}"
  typeset -g HINDSIGHT_EMBED_UI_WAIT_SECONDS="${HINDSIGHT_EMBED_UI_WAIT_SECONDS:-60}"
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

hindsight_stack_control_status() {
  emulate -L zsh
  hindsight_stack_load_config

  "$HINDSIGHT_EMBED_UVX" hindsight-embed control status \
    --port "$HINDSIGHT_EMBED_CONTROL_PORT" >/dev/null 2>&1
}

hindsight_stack_daemon_status() {
  emulate -L zsh
  hindsight_stack_load_config

  "$HINDSIGHT_EMBED_UVX" hindsight-embed --profile "$HINDSIGHT_EMBED_PROFILE" daemon status >/dev/null 2>&1 &&
    hindsight_stack_http_ok "http://127.0.0.1:${HINDSIGHT_EMBED_API_PORT}/health"
}

hindsight_stack_ui_status() {
  emulate -L zsh
  hindsight_stack_load_config

  "$HINDSIGHT_EMBED_UVX" hindsight-embed --profile "$HINDSIGHT_EMBED_PROFILE" ui status >/dev/null 2>&1 &&
    hindsight_stack_http_ok "http://127.0.0.1:${HINDSIGHT_EMBED_UI_PORT}"
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

  "$HINDSIGHT_EMBED_UVX" hindsight-embed --profile "$HINDSIGHT_EMBED_PROFILE" daemon start --ui >/dev/null 2>&1
}

hindsight_stack_ui_start() {
  emulate -L zsh
  hindsight_stack_load_config

  "$HINDSIGHT_EMBED_UVX" hindsight-embed --profile "$HINDSIGHT_EMBED_PROFILE" ui start >/dev/null 2>&1
}

hindsight_stack_control_stop() {
  emulate -L zsh
  hindsight_stack_load_config

  "$HINDSIGHT_EMBED_UVX" hindsight-embed control stop --port "$HINDSIGHT_EMBED_CONTROL_PORT" >/dev/null 2>&1
}

hindsight_stack_daemon_stop() {
  emulate -L zsh
  hindsight_stack_load_config

  "$HINDSIGHT_EMBED_UVX" hindsight-embed --profile "$HINDSIGHT_EMBED_PROFILE" daemon stop >/dev/null 2>&1
}

hindsight_stack_ui_stop() {
  emulate -L zsh
  hindsight_stack_load_config

  "$HINDSIGHT_EMBED_UVX" hindsight-embed --profile "$HINDSIGHT_EMBED_PROFILE" ui stop >/dev/null 2>&1
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
  hindsight_stack_require_current_user
  hindsight_stack_require_tools

  hindsight_stack_control_status || hindsight_stack_control_start
  hindsight_stack_wait_control || return 1

  if hindsight_stack_enabled "$HINDSIGHT_EMBED_AUTOSTART_DAEMON"; then
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

  hindsight_stack_ui_stop || true
  hindsight_stack_daemon_stop || true
  hindsight_stack_control_stop || true
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
