#!/usr/bin/env zsh
set -euo pipefail

repo_dir="${0:A:h:h}"
agents_root="${HINDSIGHT_AGENTS_ROOT:-$HOME/src/nisavid/agents}"
tmp_dir="$(mktemp -d)"
trap '/bin/rm -rf -- "$tmp_dir"' EXIT

for relative in \
  tooling/hindsight/bin/hindsight-embed-service \
  tooling/hindsight/bin/hindsight-embed-single-bank-cleanup \
  tooling/hindsight/bin/hindsight-embed-supervisor \
  tooling/hindsight/bin/hindsight-memory \
  tooling/hindsight/lib/hindsight-embed-stack.zsh \
  tooling/hindsight/libexec/hindsight-embed-control-server.py \
  tooling/hindsight/libexec/hindsight-embed-single-bank-migrate.py \
  tooling/hindsight/libexec/hindsight-embed-stop-profile-services.py \
  tooling/hindsight/skills/hindsight-memory-import/SKILL.md \
  tooling/hindsight/skills/hindsight-memory-onboarding/SKILL.md; do
  [[ -f "$agents_root/$relative" ]] || {
    print -ru2 -- "missing reusable Hindsight asset: $agents_root/$relative"
    exit 1
  }
done

render() {
  local source="$1" target="$2"
  chezmoi -S "$repo_dir/home" \
    --override-data-file "$repo_dir/home/.chezmoidata/hindsight.toml" \
    execute-template < "$repo_dir/$source" > "$target"
}

render home/private_dot_local/lib/hindsight-embed-stack.zsh.tmpl \
  "$tmp_dir/hindsight-embed-stack.zsh"
render home/private_dot_local/bin/executable_hindsight-embed-service.tmpl \
  "$tmp_dir/hindsight-embed-service"
render home/private_dot_local/bin/executable_hindsight-embed-supervisor.tmpl \
  "$tmp_dir/hindsight-embed-supervisor"
render home/private_dot_local/bin/executable_hindsight-memory.tmpl \
  "$tmp_dir/hindsight-memory"
render home/private_dot_local/bin/executable_hindsight-embed-single-bank-cleanup.tmpl \
  "$tmp_dir/hindsight-embed-single-bank-cleanup"
render home/private_Library/private_LaunchAgents/com.hindsight.embed.stack.plist.tmpl \
  "$tmp_dir/com.hindsight.embed.stack.plist"
render home/dot_agents/skills/symlink_hindsight-memory-import.tmpl \
  "$tmp_dir/hindsight-memory-import.link"
render home/dot_agents/skills/symlink_hindsight-memory-onboarding.tmpl \
  "$tmp_dir/hindsight-memory-onboarding.link"
/bin/chmod 700 "$tmp_dir"/hindsight-*

[[ "$(<"$tmp_dir/hindsight-memory-import.link")" == \
  "$HOME/src/nisavid/agents/tooling/hindsight/skills/hindsight-memory-import" ]]
[[ "$(<"$tmp_dir/hindsight-memory-onboarding.link")" == \
  "$HOME/src/nisavid/agents/tooling/hindsight/skills/hindsight-memory-onboarding" ]]
grep -F "$HOME/.pg0/instances/hindsight-embed-systalyze" \
  "$tmp_dir/hindsight-embed-single-bank-cleanup" >/dev/null
! grep -F "hindsight-embed-/systalyze" \
  "$tmp_dir/hindsight-embed-single-bank-cleanup" >/dev/null

HINDSIGHT_AGENTS_ROOT="$agents_root" zsh -f -c '
  source "$1"
  hindsight_stack_load_config || exit 1
  (( $+functions[hindsight_stack_validate_fleet] )) || exit 1
  /usr/bin/python3 -I - "$2" <<"PY"
import os
import plistlib
import sys

required = {
    "HINDSIGHT_EMBED_STACK_LIB", "HINDSIGHT_EMBED_UVX",
    "HINDSIGHT_EMBED_CONTROL_PORT", "HINDSIGHT_EMBED_CONTROL_HOSTNAME",
    "HINDSIGHT_EMBED_PRIMARY_PROFILE", "HINDSIGHT_EMBED_FLEET_PROFILES",
    "HINDSIGHT_EMBED_API_BASE_PORT", "HINDSIGHT_EMBED_UI_BASE_PORT",
    "HINDSIGHT_EMBED_UI_HOSTNAME", "HINDSIGHT_EMBED_PYTHON",
    "HINDSIGHT_EMBED_STOP_HELPER", "HINDSIGHT_MEMORY_CLI",
    "HINDSIGHT_MEMORY_STATE_DIR", "HINDSIGHT_MEMORY_BROKER_SOCKET",
    "HINDSIGHT_EMBED_STATE_DIR", "HINDSIGHT_EMBED_AUTOSTART_DAEMON",
    "HINDSIGHT_EMBED_AUTOSTART_UI",
}
with open(sys.argv[1], "rb") as handle:
    environment = plistlib.load(handle).get("EnvironmentVariables", {})
missing = sorted(
    key for key in required
    if not isinstance(environment.get(key), str)
    or not environment[key]
    or not os.environ.get(key)
)
if missing:
    raise SystemExit("missing lifecycle bindings: " + ", ".join(missing))
mismatched = sorted(key for key in required if environment.get(key) != os.environ.get(key))
if mismatched:
    raise SystemExit("manifest lifecycle bindings differ: " + ", ".join(mismatched))
PY
' zsh "$tmp_dir/hindsight-embed-stack.zsh" "$tmp_dir/com.hindsight.embed.stack.plist"
HINDSIGHT_AGENTS_ROOT="$agents_root" "$tmp_dir/hindsight-embed-service" --help >/dev/null
HINDSIGHT_AGENTS_ROOT="$agents_root" "$tmp_dir/hindsight-memory" --help >/dev/null
HINDSIGHT_AGENTS_ROOT="$agents_root" "$tmp_dir/hindsight-embed-single-bank-cleanup" --help >/dev/null
/usr/bin/plutil -lint "$tmp_dir/com.hindsight.embed.stack.plist" >/dev/null
[[ "$(/usr/libexec/PlistBuddy -c \
  'Print :EnvironmentVariables:HINDSIGHT_EMBED_AUTOSTART_DAEMON' \
  "$tmp_dir/com.hindsight.embed.stack.plist")" == true ]]
[[ "$(/usr/libexec/PlistBuddy -c \
  'Print :EnvironmentVariables:HINDSIGHT_EMBED_AUTOSTART_UI' \
  "$tmp_dir/com.hindsight.embed.stack.plist")" == true ]]
[[ "$(/usr/libexec/PlistBuddy -c \
  'Print :EnvironmentVariables:HINDSIGHT_MEMORY_CLI' \
  "$tmp_dir/com.hindsight.embed.stack.plist")" == \
  "$agents_root/tooling/hindsight/bin/hindsight-memory" ]]

for retired_dir in \
  home/private_dot_local/lib/hindsight_memory_control_plane \
  home/dot_agents/skills/hindsight-memory-import \
  home/dot_agents/skills/hindsight-memory-onboarding \
  home/dot_config/private_hindsight-memory; do
  [[ ! -d "$repo_dir/$retired_dir" ]] ||
    [[ -z "$(find "$repo_dir/$retired_dir" -type f -print -quit)" ]] || {
      print -ru2 -- "reusable Hindsight files remain in dotfiles: $retired_dir"
      exit 1
    }
done

print -r -- "hindsight agents bindings: PASS"
