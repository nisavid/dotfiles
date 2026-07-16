#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
cd "$repo_root"

fail() {
  print -u2 -r -- "$1"
  return 1
}

command -v rg >/dev/null || fail 'rg is required to validate the client boundary'

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
chmod +x "$rendered"

seed=$test_dir/seed.toml
baseline=$test_dir/baseline.toml
input=$test_dir/input.toml
output=$test_dir/output.toml
print -r -- 'unrelated = "preserved"' > "$seed"
"$rendered" < "$seed" > "$baseline"
{
  print -r -- 'model = "mlx-community/Qwen3.6-35B-A3B-OptiQ-4bit"'
  print -r -- 'model_provider = "mlx-optiq"'
  print -r -- 'model_context_window = 131072'
  print -r -- 'model_catalog_json = "/tmp/mlxctl-owned-model-catalog.json"'
  cat "$baseline"
  print -r -- '[model_providers.mlx-optiq]'
  print -r -- 'name = "Local mlxctl gateway"'
  print -r -- 'base_url = "http://127.0.0.1:8766/v1"'
  print -r -- 'wire_api = "responses"'
} > "$input"
"$rendered" < "$input" > "$output"
cmp -s "$input" "$output" || \
  fail 'Codex modifier must pass through configured mlxctl clients exactly'

! rg -n -i \
  'MLX_OPTIQ|mlx-optiq|HINDSIGHT_API_LLM|127\.0\.0\.1:8766|model_context_window|model_catalog_json' \
  "$rendered" home/dot_codex/modify_private_config.toml.tmpl \
  home/run_after_install-mlxctl.sh.tmpl >/dev/null || \
  fail 'dotfiles must not configure mlxctl clients'

print -r -- 'mlxctl client ownership checks passed'
