#!/usr/bin/env zsh
emulate -L zsh
setopt errexit nounset pipefail

repo_root=${0:A:h:h}
fixture=$repo_root/tests/fixtures/hindsight-public.toml
test_root=$(mktemp -d "${TMPDIR:-/tmp}/hindsight-bindings.XXXXXX")
trap 'rm -rf -- "$test_root"' EXIT HUP INT TERM

fail() {
  print -u2 -r -- "FAIL: $*"
  return 1
}

render() {
  local source=$1
  local target=$2
  chezmoi -S "$repo_root/home" \
    --override-data-file "$fixture" \
    execute-template <"$repo_root/$source" >"$target"
}

typeset -a json_templates=(
  home/dot_config/private_hindsight-control-plane/private_inventory.json.tmpl
  home/dot_config/private_hindsight-control-plane/private_installation.json.tmpl
  home/dot_config/private_hindsight-control-plane/private_provider-runtime-policy.json.tmpl
  home/dot_config/private_hindsight-control-plane/private_harnesses/private_claude-code-destination.json.tmpl
  home/dot_config/private_hindsight-control-plane/private_harnesses/private_codex-destination.json.tmpl
  home/dot_config/private_hindsight-control-plane/private_harnesses/private_cursor-destination.json.tmpl
)
typeset -a executable_templates=(
  home/private_dot_local/bin/executable_hindsight-memory.tmpl
  home/private_dot_local/bin/executable_hindsight-embed-supervisor.tmpl
  home/private_dot_local/bin/executable_hindsight-harness-session.tmpl
)
typeset -a skill_templates=(
  home/dot_agents/skills/symlink_hindsight-memory-import.tmpl
  home/dot_agents/skills/symlink_hindsight-memory-onboarding.tmpl
  home/dot_agents/skills/symlink_hindsight-memory-runtime.tmpl
)

typeset source target
for source in $json_templates; do
  target=$test_root/${source:t:r}
  render "$source" "$target"
  jq -e . "$target" >/dev/null || fail "invalid rendered JSON: ${source:t}"
done

for source in $executable_templates; do
  target=$test_root/${source:t:r}
  render "$source" "$target"
  case "$(<"$target")" in
    '#!/usr/bin/env zsh'*)
      zsh -n "$target"
      ;;
    *)
      python3 -B -c \
        'import pathlib, sys; p = pathlib.Path(sys.argv[1]); compile(p.read_text(), str(p), "exec")' \
        "$target"
      ;;
  esac
done

target=$test_root/sitecustomize.py
render home/private_dot_local/lib/hindsight-runtime/sitecustomize.py.tmpl "$target"
python3 -B -c \
  'import pathlib, sys; p = pathlib.Path(sys.argv[1]); compile(p.read_text(), str(p), "exec")' \
  "$target"

for source in $skill_templates; do
  target=$test_root/${source:t:r}
  render "$source" "$target"
  [[ "$(<"$target")" == "$HOME/.fixture/install/active/skills/"* ]] ||
    fail "unexpected rendered skill target: ${source:t}"
done

python3 - "$test_root" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
inventory = json.loads((root / "private_inventory.json").read_text())
installation = json.loads((root / "private_installation.json").read_text())
policy = json.loads((root / "private_provider-runtime-policy.json").read_text())

assert inventory["machine"]["id"] == "fixture-consumer"
assert inventory["banks"][0]["id"] == "fixture-bank"
assert installation["consumer_id"] == "fixture-consumer"
assert installation["services"][0]["label"].startswith("io.example.fixture.")
assert policy["failover_order"] == ["member-a", "member-b", "member-local"]
assert all("fixture" in member["id"] or member["id"].startswith("member-") for member in policy["members"])
PY

[[ "$(sed -n 's/^releaseCommit = //p' "$repo_root/home/.chezmoidata/hindsight.toml" | wc -l | tr -d ' ')" == 1 ]]
[[ "$(sed -n 's/^releaseVersion = //p' "$repo_root/home/.chezmoidata/hindsight.toml" | wc -l | tr -d ' ')" == 1 ]]
if rg -v '^([[:space:]]*|\[hindsight\]|releaseCommit[[:space:]]*=.*|releaseVersion[[:space:]]*=.*)$' \
  "$repo_root/home/.chezmoidata/hindsight.toml" >/dev/null; then
  fail 'public Hindsight data contains a machine-specific binding'
fi

print -r -- 'hindsight public consumer bindings: PASS'
