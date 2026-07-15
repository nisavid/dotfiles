#!/usr/bin/env zsh
set -euo pipefail
unsetopt BG_NICE

repo_dir="${0:A:h:h}"
tmp_dir="$(mktemp -d)"
broker_pid=""
supervisor_pid=""
trap '
  for pid in "$broker_pid" "$supervisor_pid"; do
    [[ -z "$pid" ]] && continue
    kill -TERM "$pid" >/dev/null 2>&1 || true
    for _ in {1..20}; do
      kill -0 "$pid" >/dev/null 2>&1 || break
      sleep 0.05
    done
    kill -KILL "$pid" >/dev/null 2>&1 || true
    wait "$pid" >/dev/null 2>&1 || true
  done
  rm -rf -- "$tmp_dir"
' EXIT

fail() {
  print -ru2 -- "hindsight-memory-controller: $*"
  exit 1
}

rendered_stack_lib="$tmp_dir/hindsight-embed-stack.zsh"
rendered_plist="$tmp_dir/com.hindsight.embed.stack.plist"
(
  cd "$repo_dir"
  chezmoi --source "$repo_dir/home" execute-template < home/private_dot_local/lib/hindsight-embed-stack.zsh.tmpl > "$rendered_stack_lib"
  chezmoi --source "$repo_dir/home" execute-template < home/private_Library/private_LaunchAgents/com.hindsight.embed.stack.plist.tmpl > "$rendered_plist"
)

help_output="$(zsh "$repo_dir/home/private_dot_local/bin/executable_hindsight-embed-service" --help)"
for command in install start stop status logs; do
  print -r -- "$help_output" | rg -q "^[[:space:]]+${command}[[:space:]]" ||
    fail "service help lost the ${command} command"
done
if print -r -- "$help_output" | rg -v '^(Usage:|$|Commands:|[[:space:]]+(install|start|stop|status|logs)[[:space:]])' | rg -q .; then
  fail "service help gained an unreviewed operator command"
fi

python3 - "$rendered_plist" "$repo_dir/home/.chezmoidata/hindsight.toml" <<'PY'
import plistlib
import re
import sys
from pathlib import Path

plist = plistlib.loads(Path(sys.argv[1]).read_bytes())
environment = plist["EnvironmentVariables"]
required = {
    "HINDSIGHT_EMBED_CONTROL_HOSTNAME": "127.0.0.1",
    "HINDSIGHT_EMBED_UI_HOSTNAME": "127.0.0.1",
    "HINDSIGHT_MEMORY_BROKER_SOCKET": str(Path.home() / ".local/state/hindsight-memory/broker.sock"),
    "HINDSIGHT_EMBED_FLEET_PROFILES": environment["HINDSIGHT_EMBED_PROFILE"],
    "HINDSIGHT_MEMORY_BROKER_WAIT_SECONDS": "30",
}
for key, expected in required.items():
    if environment.get(key) != expected:
        raise SystemExit(f"LaunchAgent {key} is not bound to the expected private value")
serialized = Path(sys.argv[1]).read_text() + Path(sys.argv[2]).read_text()
if re.search(r"(?i)(authorization|bearer|credential|password|secret|token)", serialized):
    raise SystemExit("managed service configuration contains a credential carrier")
PY

apply_source="$tmp_dir/apply-source"
apply_home="$tmp_dir/apply-home"
mkdir -p "$apply_source/private_dot_hindsight" "$apply_home"
cp -R "$repo_dir/home/.chezmoidata" "$apply_source/.chezmoidata"
for template in codex claude-code cursor; do
  cp "$repo_dir/home/private_dot_hindsight/${template}.json.tmpl" \
    "$apply_source/private_dot_hindsight/${template}.json.tmpl"
done
chezmoi --source "$apply_source" --destination "$apply_home" \
  --persistent-state "$tmp_dir/apply-state.boltdb" apply --force

for template in codex claude-code cursor; do
  applied="$apply_home/.hindsight/${template}.json"
  python3 - "$applied" "$template" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text())
expected_adapters = {
    "codex": "hindsight-codex",
    "claude-code": "claude-code",
    "cursor": "cursor",
}
if value.get("active") is not False:
    raise SystemExit("managed harness rendered active")
if value.get("broker", {}).get("transport") != "unix":
    raise SystemExit("managed harness lost its private broker transport")
if value.get("adapter") != expected_adapters[sys.argv[2]]:
    raise SystemExit("managed harness lost its registered adapter identity")
for forbidden in ("url", "token", "credential", "bank_id"):
    if forbidden in json.dumps(value).lower():
        raise SystemExit(f"managed harness contains {forbidden}")
PY
done

(
  export HOME="$tmp_dir/status-home"
  export HINDSIGHT_EMBED_STATE_DIR="$tmp_dir/status-state"
  export HINDSIGHT_EMBED_PROFILE="test-profile"
  export HINDSIGHT_EMBED_FLEET_PROFILES="test-profile"
  mkdir -p "$HOME/.hindsight/profiles"
  touch "$HOME/.hindsight/profiles/test-profile.env"
  source "$rendered_stack_lib"
  for function_name in \
    hindsight_stack_broker_status \
    hindsight_stack_broker_start \
    hindsight_stack_broker_stop \
    hindsight_stack_enabled_profiles \
    hindsight_stack_select_profile \
    hindsight_stack_validate_fleet \
    hindsight_stack_wait_broker; do
    (( ${+functions[$function_name]} )) || fail "stack library is missing ${function_name}"
  done

  hindsight_stack_control_status() { return 0 }
  hindsight_stack_daemon_status() { return 0 }
  hindsight_stack_ui_status() { return 0 }
  hindsight_stack_broker_status() { return 0 }
  status_report="$(hindsight_stack_status_report)"
  print -r -- "$status_report" | rg -q '^broker: healthy .*broker\.sock' ||
    fail "status report does not add broker health"
  print -r -- "$status_report" | rg -q '^daemon: healthy ' ||
    fail "status report lost profile health"
  print -r -- "$status_report" | rg -q '^fleet: healthy \(1 enabled profile\)$' ||
    fail "status report does not add fleet health"
  print -r -- "$status_report" | rg -q '^profile .* slot=0 .*sidecars=none' ||
    fail "status report does not expose stable profile slot and sidecar readiness"
)

(
  export HOME="$tmp_dir/lifecycle-home"
  export HINDSIGHT_EMBED_STATE_DIR="$tmp_dir/lifecycle-state"
  export HINDSIGHT_EMBED_PROFILE_SLOT_DIR="$HINDSIGHT_EMBED_STATE_DIR/profile-slots"
  export HINDSIGHT_EMBED_PROFILE="crash-profile"
  export HINDSIGHT_EMBED_FLEET_PROFILES="crash-profile"
  mkdir -p "$HOME/.hindsight/profiles" "$HINDSIGHT_EMBED_PROFILE_SLOT_DIR"
  touch "$HOME/.hindsight/profiles/crash-profile.env"
  lock_file="$HINDSIGHT_EMBED_PROFILE_SLOT_DIR/.allocation.lock"
  lock_ready="$tmp_dir/profile-lock-ready"
  : >"$lock_file"
  zsh -c '
    zmodload zsh/system
    zsystem flock -f descriptor "$1"
    touch "$2"
    sleep 60
  ' -- "$lock_file" "$lock_ready" &
  lock_holder_pid=$!
  for _ in {1..100}; do
    [[ -e "$lock_ready" ]] && break
    kill -0 "$lock_holder_pid" >/dev/null 2>&1 || break
    sleep 0.01
  done
  [[ -e "$lock_ready" ]] || fail "profile lock holder did not become ready"
  kill -KILL "$lock_holder_pid"
  wait "$lock_holder_pid" >/dev/null 2>&1 || true

  source "$rendered_stack_lib"
  [[ "$(hindsight_stack_profile_slot crash-profile)" == 0 ]] ||
    fail "profile slot lock was not released after holder crash"

  sidecar_stop="$tmp_dir/sidecar-stop"
  hindsight_stack_sidecar_names() { print -r -- unhealthy-sidecar }
  hindsight_stack_sidecar_port() { print -r -- 18180 }
  hindsight_stack_sidecar_status() { return 1 }
  hindsight_stack_port_listening() { return 0 }
  hindsight_stack_sidecar_command() {
    [[ "$2" == stop ]] && print -r -- "$1" >"$sidecar_stop"
  }
  hindsight_stack_sidecar_running unhealthy-sidecar ||
    fail "sidecar liveness incorrectly followed health readiness"
  hindsight_stack_stop_sidecars
  [[ "$(<"$sidecar_stop")" == unhealthy-sidecar ]] ||
    fail "unhealthy sidecar did not receive a stop command"
)

broker_state="$tmp_dir/broker-state"
broker_socket="$broker_state/broker.sock"
broker_log="$tmp_dir/broker.log"
mkdir -m 700 "$broker_state"
print -r -- '{"pid":999999999,"start_time":"stale-process"}' >"$broker_state/broker.pid"
chmod 600 "$broker_state/broker.pid"
python3 "$repo_dir/home/private_dot_local/bin/executable_hindsight-memory" \
  --state-dir "$broker_state" broker serve \
  --socket "$broker_socket" --profile example >"$broker_log" 2>&1 &
broker_pid=$!
for _ in {1..100}; do
  [[ -S "$broker_socket" ]] && break
  kill -0 "$broker_pid" >/dev/null 2>&1 || break
  sleep 0.05
done
kill -0 "$broker_pid" >/dev/null 2>&1 || {
  sed -n '1,120p' "$broker_log" >&2
  fail "inactive broker exited during startup"
}
identity_pid="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="ascii"))["pid"])' \
  "$broker_state/broker.pid")"
identity_start="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="ascii"))["start_time"])' \
  "$broker_state/broker.pid")"
[[ "$identity_pid" == "$broker_pid" ]] || fail "broker PID identity was not rewritten"
[[ "$identity_start" != "stale-process" ]] || fail "broker start identity remained stale"
python3 "$repo_dir/home/private_dot_local/bin/executable_hindsight-memory" \
  --state-dir "$broker_state" broker status --socket "$broker_socket" >/dev/null
[[ "$(stat -f '%Lp' "$broker_socket")" == "600" ]] || fail "broker socket is not mode 0600"
python3 "$repo_dir/home/private_dot_local/bin/executable_hindsight-memory" \
  --state-dir "$broker_state" broker stop --socket "$broker_socket" >/dev/null
wait "$broker_pid"
broker_pid=""
[[ ! -e "$broker_socket" ]] || fail "broker socket remains after bounded stop"
[[ ! -e "$broker_state/broker.pid" ]] || fail "broker PID remains after bounded stop"

fake_stack="$tmp_dir/fake-stack.zsh"
cat > "$fake_stack" <<'ZSH'
hindsight_stack_load_config() {
  typeset -g HINDSIGHT_EMBED_PROFILE="test-profile"
  typeset -g HINDSIGHT_EMBED_CONTROL_PORT="7878"
  typeset -g HINDSIGHT_EMBED_API_PORT="7979"
  typeset -g HINDSIGHT_EMBED_UI_PORT="17979"
  typeset -g HINDSIGHT_EMBED_FLEET_PROFILES="test-profile,second-profile"
  typeset -g HINDSIGHT_MEMORY_BROKER_SOCKET="$HINDSIGHT_EMBED_STATE_DIR/broker.sock"
}
hindsight_stack_log() { print -r -- "$*" }
hindsight_stack_enabled_profiles() { print -r -- test-profile; print -r -- second-profile }
hindsight_stack_fleet_profiles_csv() { print -r -- test-profile,second-profile }
hindsight_stack_broker_status() { return 0 }
hindsight_stack_reconcile_once() { return 0 }
hindsight_stack_require_current_user() { return 0 }
hindsight_stack_require_runtime_helpers() { return 0 }
hindsight_stack_require_tools() { return 0 }
hindsight_stack_validate_fleet() { return 0 }
hindsight_stack_stop_all() { return 0 }
ZSH

supervisor_state="$tmp_dir/supervisor-state"
HINDSIGHT_EMBED_STACK_LIB="$fake_stack" \
HINDSIGHT_EMBED_STATE_DIR="$supervisor_state" \
HINDSIGHT_EMBED_POLL_SECONDS=1 \
HINDSIGHT_TEST_SECRET="credential-sentinel" \
HINDSIGHT_TEST_PAYLOAD="payload-sentinel" \
zsh "$repo_dir/home/private_dot_local/bin/executable_hindsight-embed-supervisor" &
supervisor_pid=$!
supervisor_log="$supervisor_state/logs/supervisor.log"
start_log=""
for _ in {1..100}; do
  if [[ -s "$supervisor_log" ]]; then
    start_log="$(rg --max-count 1 \
      "^supervisor started .*profiles=test-profile,second-profile.*broker_socket=$supervisor_state/broker.sock" \
      "$supervisor_log" || true)"
    [[ -n "$start_log" ]] && break
  fi
  sleep 0.05
done
[[ -n "$start_log" ]] || fail "supervisor startup record did not become ready"
kill -TERM "$supervisor_pid"
for _ in {1..100}; do
  kill -0 "$supervisor_pid" >/dev/null 2>&1 || break
  sleep 0.05
done
if kill -0 "$supervisor_pid" >/dev/null 2>&1; then
  kill -KILL "$supervisor_pid" >/dev/null 2>&1 || true
  wait "$supervisor_pid" >/dev/null 2>&1 || true
  supervisor_pid=""
  sed -n '1,120p' "$supervisor_log" >&2
  fail "supervisor did not stop within the bounded timeout"
fi
wait "$supervisor_pid"
supervisor_pid=""
[[ "$start_log" == *"profiles=test-profile,second-profile"* &&
  "$start_log" == *"broker_socket=$supervisor_state/broker.sock"* ]] ||
  fail "supervisor log omits content-free broker identity"
if rg -qi '(credential-sentinel|payload-sentinel|authorization:|bearer[[:space:]]|api[_-]?key)' "$supervisor_log"; then
  fail "supervisor log contains a credential or payload"
fi

print -r -- "hindsight-memory-controller: PASS"
