#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
cd "$repo_root"

fail() {
  print -u2 -r -- "$1"
  return 1
}

command -v yq >/dev/null || fail 'yq is required to validate Codex TOML'
command -v jq >/dev/null || fail 'jq is required to inspect Codex TOML'

test_dir=$(mktemp -d "${TMPDIR:-/tmp}/mlx-optiq-clients.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT
fixture_home=$test_dir/home
mkdir -p -- "$fixture_home"
fixture_home=${fixture_home:A}
rendered=$test_dir/modify-codex-config
output=$test_dir/config.toml

optiq_data='{"targetHostname":"hatchery","modelDir":".local/share/mlxd/models/qwen36-optiq","clients":{"baseUrl":"http://127.0.0.1:8766/v1","contextWindow":32768,"codexProvider":"mlx-optiq"}}'
hatchery_data='{"chezmoi":{"os":"darwin","homeDir":"'${fixture_home}'","hostname":"hatchery"},"mlxd":{"optiq":'${optiq_data}'}}'

chezmoi execute-template --override-data "$hatchery_data" \
  < home/dot_codex/modify_private_config.toml.tmpl > "$rendered"
chmod +x "$rendered"
print -r -- 'model = "existing-model"
model_provider = "existing"
[model_providers.existing]
name = "Existing provider"
base_url = "https://example.invalid/v1"
wire_api = "responses"' | "$rendered" > "$output"

yq -p=toml -o=json "$output" | jq -e --arg model "$fixture_home/.local/share/mlxd/models/qwen36-optiq" '
  .model == $model and
  .model_provider == "mlx-optiq" and
  .model_context_window == 32768 and
  .model_providers["mlx-optiq"] == {
    "name": "Local mlxctl OptiQ",
    "base_url": "http://127.0.0.1:8766/v1",
    "wire_api": "responses"
  } and
  .model_providers.existing.name == "Existing provider"
' >/dev/null || fail 'hatchery Codex config does not select the managed mlxctl Client Endpoint'

print -r -- 'mlx-optiq client checks passed'
