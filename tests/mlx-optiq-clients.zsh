#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
cd "$repo_root"

fail() {
  print -u2 -r -- "$1"
  return 1
}

test_dir=$(mktemp -d "${TMPDIR:-/tmp}/mlxctl-client-boundary.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT
rendered=$test_dir/modify-codex-config
fixture_home=$test_dir/home
mkdir -p -- "$fixture_home"
fixture_home=${fixture_home:A}

darwin_data='{"chezmoi":{"os":"darwin","homeDir":"'${fixture_home}'","hostname":"hatchery"}}'
chezmoi execute-template --override-data "$darwin_data" \
  < home/dot_codex/modify_private_config.toml.tmpl > "$rendered"
bash -n "$rendered"

! rg -n -i \
  'MLX_OPTIQ|mlx-optiq|HINDSIGHT_API_LLM|127\.0\.0\.1:8766|model_context_window' \
  "$rendered" home/dot_codex/modify_private_config.toml.tmpl \
  home/run_after_install-mlxctl.sh.tmpl >/dev/null || \
  fail 'dotfiles must not configure mlxctl clients'

rg -q 'raw = sys\.stdin\.read\(\)' "$rendered" || \
  fail 'Codex modifier must continue to pass through the live config'
! rg -n 'doc\["model"\]|doc\["model_provider"\]|model_providers' "$rendered" >/dev/null || \
  fail 'Codex modifier must not mutate model selection or provider definitions'

print -r -- 'mlxctl client ownership checks passed'
