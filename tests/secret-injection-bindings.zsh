#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
cd "$repo_root"

fail() {
  print -u2 -r -- "$1"
  return 1
}

test_dir=$(mktemp -d "${TMPDIR:-/tmp}/secret-injection-bindings.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT
fixture_home=$test_dir/home
mkdir -p -- "$fixture_home"
fixture_home=${fixture_home:A}
darwin_data='{"chezmoi":{"os":"darwin","homeDir":"'${fixture_home}'","hostname":"test-host"}}'

render_modifier() {
  local source=$1
  local target=$2
  chezmoi execute-template --override-data "$darwin_data" < "$source" > "$target"
  chmod +x "$target"
}

codex_modifier=$test_dir/modify-codex
render_modifier home/dot_codex/modify_private_config.toml.tmpl "$codex_modifier"
cat > "$test_dir/codex-input.toml" <<'EOF'
unrelated = "preserved"

[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"

[mcp_servers.context7.http_headers]
CONTEXT7_API_KEY = "ambient-canary"

[mcp_servers.firecrawl]
command = "npx"
args = ["mcp-remote", "https://mcp.firecrawl.dev/firecrawl-canary/v2/mcp"]
env_vars = ["FIRECRAWL_API_KEY"]

[mcp_servers.github]
url = "https://api.githubcopilot.com/mcp/"
bearer_token_env_var = "GITHUB_PERSONAL_ACCESS_TOKEN"
EOF
"$codex_modifier" < "$test_dir/codex-input.toml" > "$test_dir/codex-output.toml"

uv run --quiet --with tomlkit python3 - "$test_dir/codex-output.toml" "$fixture_home" <<'PYEOF'
import sys, tomlkit

path, home = sys.argv[1:]
doc = tomlkit.load(open(path))
assert doc["unrelated"] == "preserved"
expected = {
    "context7": ["context7", "--", "npx", "-y", "@upstash/context7-mcp"],
    "firecrawl": ["firecrawl", "--", "npx", "-y", "firecrawl-mcp"],
    "github": [
        "github", "--", "npx", "-y", "mcp-remote",
        "https://api.githubcopilot.com/mcp/", "--header",
        "Authorization:Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}",
    ],
}
for name, args in expected.items():
    server = doc["mcp_servers"][name]
    assert server["command"] == f"{home}/.local/bin/secret-exec"
    assert list(server["args"]) == args
    assert not ({"url", "http_headers", "bearer_token_env_var", "env_vars", "env"} & set(server))
PYEOF

claude_modifier=$test_dir/modify-claude
render_modifier home/modify_private_dot_claude.json.tmpl "$claude_modifier"
cat > "$test_dir/claude-input.json" <<'EOF'
{
  "unrelated": "preserved",
  "mcpServers": {
    "context7": {"type": "http", "url": "https://mcp.context7.com/mcp"},
    "firecrawl": {"type": "http", "url": "https://mcp.firecrawl.dev/firecrawl-canary/v2/mcp"}
  }
}
EOF
"$claude_modifier" < "$test_dir/claude-input.json" > "$test_dir/claude-output.json"
jq -e --arg command "$fixture_home/.local/bin/secret-exec" '
  .unrelated == "preserved" and
  .mcpServers.context7 == {command: $command, args: ["context7", "--", "npx", "-y", "@upstash/context7-mcp"]} and
  .mcpServers.firecrawl == {command: $command, args: ["firecrawl", "--", "npx", "-y", "firecrawl-mcp"]} and
  .mcpServers.github == {command: $command, args: ["github", "--", "npx", "-y", "mcp-remote", "https://api.githubcopilot.com/mcp/", "--header", "Authorization:Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}"]} and
  .mcpServers.greptile == {command: $command, args: ["greptile", "--", "npx", "-y", "mcp-remote", "https://api.greptile.com/mcp", "--header", "Authorization:Bearer ${GREPTILE_API_KEY}"]}
' "$test_dir/claude-output.json" > /dev/null || fail 'Claude MCP bindings must use process-scoped launch profiles'
! rg -n 'firecrawl-canary|ambient-canary' "$test_dir/claude-output.json" >/dev/null || \
  fail 'Claude output must retire credential-bearing MCP URLs'

settings_modifier=$test_dir/modify-claude-settings
render_modifier home/dot_claude/modify_private_settings.json.tmpl "$settings_modifier"
cat > "$test_dir/settings-input.json" <<'EOF'
{
  "unrelated": "preserved",
  "enabledPlugins": {
    "context7@claude-plugins-official": true,
    "firecrawl@claude-plugins-official": true,
    "github@claude-plugins-official": true,
    "greptile@claude-plugins-official": true
  }
}
EOF
"$settings_modifier" < "$test_dir/settings-input.json" > "$test_dir/settings-output.json"
jq -e '
  .unrelated == "preserved" and
  .enabledPlugins["context7@claude-plugins-official"] == false and
  .enabledPlugins["firecrawl@claude-plugins-official"] == true and
  .enabledPlugins["github@claude-plugins-official"] == false and
  .enabledPlugins["greptile@claude-plugins-official"] == false
' "$test_dir/settings-output.json" > /dev/null || fail 'credential-dependent plugin MCPs must be replaced without disabling Firecrawl skills'

mcp_config_modifier=$test_dir/modify-mcp-config
render_modifier home/dot_config/modify_private_mcp-config.json.tmpl "$mcp_config_modifier"
cat > "$test_dir/mcp-config-input.json" <<'EOF'
{
  "unrelated": "preserved",
  "mcpServers": {
    "firecrawl": {
      "type": "http",
      "command": "npx",
      "args": ["mcp-remote", "https://mcp.firecrawl.dev/firecrawl-canary/v2/mcp"],
      "env": {"FIRECRAWL_API_KEY": "environment-canary"},
      "headers": {"Authorization": "Bearer header-canary"},
      "http_headers": {"X-API-Key": "http-header-canary"},
      "bearer_token_env_var": "FIRECRAWL_API_KEY",
      "tools": ["scrape"],
      "url": "https://mcp.firecrawl.dev/firecrawl-canary/v2/mcp"
    }
  }
}
EOF
"$mcp_config_modifier" < "$test_dir/mcp-config-input.json" > "$test_dir/mcp-config-output.json"
jq -e --arg command "$fixture_home/.local/bin/secret-exec" '
  .unrelated == "preserved" and
  .mcpServers.firecrawl == {
    type: "stdio",
    command: $command,
    args: ["firecrawl", "--", "npx", "-y", "firecrawl-mcp"],
    tools: ["scrape"]
  }
' "$test_dir/mcp-config-output.json" > /dev/null || fail 'generic MCP config must preserve metadata while retiring the Firecrawl URL'
! rg -n 'firecrawl-canary|environment-canary|header-canary|FIRECRAWL_API_KEY' \
  "$test_dir/mcp-config-output.json" >/dev/null || fail 'generic MCP output must not retain legacy authentication data'

aws_modifier=$test_dir/modify-aws-config
render_modifier home/private_dot_aws/modify_private_config.tmpl "$aws_modifier"
cat > "$test_dir/aws-input" <<'EOF'
[default]
region = us-east-1
login_session = personal
credential_process = old-helper
aws_session_token = session-canary

[profile unrelated]
region = us-west-2
EOF
"$aws_modifier" < "$test_dir/aws-input" > "$test_dir/aws-output"
rg -Fx "credential_process = $fixture_home/.local/bin/secret-exec aws-credential-process aws" \
  "$test_dir/aws-output" >/dev/null || fail 'AWS must resolve credentials through secret-exec'
! rg -e 'login_session|aws_session_token' "$test_dir/aws-output" >/dev/null || \
  fail 'the default AWS profile must not retain higher-precedence or partial credentials'
rg -Fx '[profile unrelated]' "$test_dir/aws-output" >/dev/null || fail 'unrelated AWS profiles must be preserved'

profiles=home/dot_config/secret-exec/profiles
[[ $(<"$profiles/context7.env") == 'CONTEXT7_API_KEY=pass://cli-secrets/context7/password' ]] || fail 'Context7 profile mismatch'
[[ $(<"$profiles/firecrawl.env") == 'FIRECRAWL_API_KEY=pass://cli-secrets/firecrawl/password' ]] || fail 'Firecrawl profile mismatch'
[[ $(<"$profiles/github.env") == 'GITHUB_PERSONAL_ACCESS_TOKEN=pass://cli-secrets/github-mcp/password' ]] || fail 'GitHub profile mismatch'
[[ $(<"$profiles/greptile.env") == 'GREPTILE_API_KEY=pass://cli-secrets/greptile/password' ]] || fail 'Greptile profile mismatch'
[[ $(<"$profiles/aws.env") == $'AWS_ACCESS_KEY_ID=pass://cli-secrets/aws/username\nAWS_SECRET_ACCESS_KEY=pass://cli-secrets/aws/password' ]] || fail 'AWS profile mismatch'

print -r -- 'secret injection binding checks passed'
