#!/usr/bin/env zsh
set -euo pipefail
setopt extended_glob

repo_root=${0:A:h:h}
cd "$repo_root"

fail() {
  print -u2 -r -- "$1"
  return 1
}

test_dir=$(mktemp -d "${TMPDIR:-/tmp}/secret-injection-bindings.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT
export UV_CACHE_DIR=$test_dir/uv-cache
fixture_home=$test_dir/home
mkdir -p -- "$fixture_home"
fixture_home=${fixture_home:A}
darwin_data='{"chezmoi":{"os":"darwin","homeDir":"'${fixture_home}'","hostname":"test-host"},"gitIdentity":{"publicFixture":true,"selection":{"default":"personal","byHostname":{}},"identities":{"personal":{"email":"ivan@nisavid.io","editorTarget":"cursor","branchPrefix":"nisavid/","noTracking":false}}}}'

render_modifier() {
  local source=$1
  local target=$2
  chezmoi -S "$repo_root/home" execute-template --override-data "$darwin_data" < "$source" > "$target"
  chmod +x "$target"
}

codex_modifier=$test_dir/modify-codex
render_modifier home/dot_codex/modify_private_config.toml.tmpl "$codex_modifier"
cat > "$test_dir/codex-input.toml" <<'EOF'
unrelated = "preserved"

[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"
startup_timeout_sec = 30

[mcp_servers.context7.http_headers]
CONTEXT7_API_KEY = "ambient-canary"

[mcp_servers.firecrawl]
command = "npx"
args = ["mcp-remote", "https://mcp.firecrawl.dev/firecrawl-canary/v2/mcp"]
env_vars = ["FIRECRAWL_API_KEY"]
cwd = "/tmp/firecrawl"

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
    "context7": ["context7", "--", "npx", "-y", "@upstash/context7-mcp@3.2.4"],
    "firecrawl": ["firecrawl", "--", "npx", "-y", "firecrawl-mcp@3.22.3"],
    "github": [
        "github", "--", "npx", "-y", "mcp-remote@0.1.38",
        "https://api.githubcopilot.com/mcp/", "--header",
        "Authorization:Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}",
    ],
}
for name, args in expected.items():
    server = doc["mcp_servers"][name]
    assert server["command"] == f"{home}/.local/bin/secret-exec"
    assert list(server["args"]) == args
    assert not ({"type", "url", "headers", "http_headers", "bearer_token_env_var", "env_vars", "env"} & set(server))
assert doc["mcp_servers"]["context7"]["startup_timeout_sec"] == 30
assert doc["mcp_servers"]["firecrawl"]["cwd"] == "/tmp/firecrawl"
PYEOF

claude_modifier=$test_dir/modify-claude
render_modifier home/modify_private_dot_claude.json.tmpl "$claude_modifier"
cat > "$test_dir/claude-input.json" <<'EOF'
{
  "unrelated": "preserved",
  "pluginUsage": {
    "context7@inline": {"usageCount": 7},
    "serena@claude-plugins-official": {"usageCount": 3},
    "serena@inline": {"usageCount": 2}
  },
  "mcpServers": {
    "context7": {"type": "http", "url": "https://mcp.context7.com/mcp", "headers": {"CONTEXT7_API_KEY": "context7-canary"}, "timeout": 60000},
    "firecrawl": {"type": "http", "url": "https://mcp.firecrawl.dev/firecrawl-canary/v2/mcp", "tools": ["scrape"]},
    "github": {"type": "http", "url": "https://github.example.invalid", "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "github-canary"}, "disabled": true},
    "greptile": {"type": "http", "url": "https://greptile.example.invalid", "http_headers": {"Authorization": "greptile-canary"}, "timeout": 30000},
    "serena": {"command": "serena", "args": ["start-mcp-server"]}
  }
}
EOF
"$claude_modifier" < "$test_dir/claude-input.json" > "$test_dir/claude-output.json"
jq -e --arg command "$fixture_home/.local/bin/secret-exec" '
  .unrelated == "preserved" and
  .pluginUsage["context7@inline"] == {usageCount: 7} and
  .mcpServers.context7 == {command: $command, args: ["context7", "--", "npx", "-y", "@upstash/context7-mcp@3.2.4"], timeout: 60000} and
  .mcpServers.firecrawl == {command: $command, args: ["firecrawl", "--", "npx", "-y", "firecrawl-mcp@3.22.3"], tools: ["scrape"]} and
  .mcpServers.github == {command: $command, args: ["github", "--", "npx", "-y", "mcp-remote@0.1.38", "https://api.githubcopilot.com/mcp/", "--header", "Authorization:Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}"], disabled: true} and
  .mcpServers.greptile == {command: $command, args: ["greptile", "--", "npx", "-y", "mcp-remote@0.1.38", "https://api.greptile.com/mcp", "--header", "Authorization:Bearer ${GREPTILE_API_KEY}"], timeout: 30000} and
  (.mcpServers | has("serena") | not) and
  (.pluginUsage | has("serena@claude-plugins-official") | not) and
  (.pluginUsage | has("serena@inline") | not) and
  ([.mcpServers.context7, .mcpServers.firecrawl, .mcpServers.github, .mcpServers.greptile] |
    all(. as $server | ["type", "url", "env", "env_vars", "headers", "http_headers", "bearer_token_env_var"] |
      all(. as $field | ($server | has($field) | not))))
' "$test_dir/claude-output.json" > /dev/null || fail 'Claude MCP bindings must use process-scoped launch profiles'
! rg -n 'context7-canary|firecrawl-canary|github-canary|greptile-canary|ambient-canary' "$test_dir/claude-output.json" >/dev/null || \
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
    "greptile@claude-plugins-official": true,
    "serena@claude-plugins-official": true
  }
}
EOF
"$settings_modifier" < "$test_dir/settings-input.json" > "$test_dir/settings-output.json"
jq -e '
  .unrelated == "preserved" and
  .enabledPlugins["context7@claude-plugins-official"] == false and
  .enabledPlugins["firecrawl@claude-plugins-official"] == true and
  .enabledPlugins["github@claude-plugins-official"] == false and
  .enabledPlugins["greptile@claude-plugins-official"] == false and
  (.enabledPlugins | has("serena@claude-plugins-official") | not)
' "$test_dir/settings-output.json" > /dev/null || fail 'credential-dependent plugin MCPs must be replaced without disabling Firecrawl skills'

mcp_config_modifier=$test_dir/modify-mcp-config
render_modifier home/dot_config/modify_private_mcp-config.json.tmpl "$mcp_config_modifier"
authorization_header='Bearer '
authorization_header+='header-canary'
http_header_canary='http-header-'
http_header_canary+='canary'
cat > "$test_dir/mcp-config-input.json" <<EOF
{
  "unrelated": "preserved",
  "mcpServers": {
    "firecrawl": {
      "type": "http",
      "command": "npx",
      "args": ["mcp-remote", "https://mcp.firecrawl.dev/firecrawl-canary/v2/mcp"],
      "env": {"FIRECRAWL_API_KEY": "environment-canary"},
      "headers": {"Authorization": "$authorization_header"},
      "http_headers": {"X-API-Key": "$http_header_canary"},
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
    args: ["firecrawl", "--", "npx", "-y", "firecrawl-mcp@3.22.3"],
    tools: ["scrape"]
  }
' "$test_dir/mcp-config-output.json" > /dev/null || fail 'generic MCP config must preserve metadata while retiring the Firecrawl URL'
! rg -n 'firecrawl-canary|environment-canary|header-canary|FIRECRAWL_API_KEY' \
  "$test_dir/mcp-config-output.json" >/dev/null || fail 'generic MCP output must not retain legacy authentication data'

opencode_hook=$test_dir/update-opencode-context7
render_modifier home/run_after_update-opencode-context7.sh.tmpl "$opencode_hook"
mkdir -p -- "$fixture_home/.config/opencode"
cat > "$fixture_home/.config/opencode/opencode.json" <<EOF
{
  "unrelated": "preserved",
  "mcp": {
    "context7": {
      "type": "remote",
      "url": "https://mcp.context7.com/mcp",
      "headers": {"CONTEXT7_API_KEY": "literal-canary"},
      "env": {"CONTEXT7_API_KEY": "environment-canary"},
      "env_vars": ["CONTEXT7_API_KEY"],
      "http_headers": {"X-API-Key": "$http_header_canary"},
      "bearer_token_env_var": "CONTEXT7_API_KEY",
      "timeout": 60000
    }
  }
}
EOF
"$opencode_hook"
jq -e --arg command "$fixture_home/.local/bin/secret-exec" '
  .unrelated == "preserved" and
  .mcp.context7 == {
    type: "local",
    command: [$command, "context7", "--", "npx", "-y", "@upstash/context7-mcp@3.2.4"],
    enabled: true,
    timeout: 60000
  }
' "$fixture_home/.config/opencode/opencode.json" > /dev/null || \
  fail 'OpenCode Context7 must use the process-scoped launcher while preserving metadata'
! rg -n 'literal-canary|environment-canary|http-header-canary|CONTEXT7_API_KEY|mcp.context7.com' \
  "$fixture_home/.config/opencode/opencode.json" >/dev/null || \
  fail 'OpenCode output must not retain literal Context7 authentication data'
chmod 600 "$fixture_home/.config/opencode/opencode.json"
jq '.mcp.context7.enabled = false' "$fixture_home/.config/opencode/opencode.json" > \
  "$test_dir/opencode-disabled.json"
mv "$test_dir/opencode-disabled.json" "$fixture_home/.config/opencode/opencode.json"
"$opencode_hook"
jq -e '.mcp.context7.enabled == false' "$fixture_home/.config/opencode/opencode.json" > /dev/null || \
  fail 'OpenCode Context7 migration must preserve an explicit disabled state'

aws_modifier=$test_dir/modify-aws-config
render_modifier home/private_dot_aws/modify_private_config.tmpl "$aws_modifier"
cat > "$test_dir/aws-input" <<'EOF'
[default]
region = us-east-1
login_session = personal
credential_process = old-helper
aws_access_key_id = access-key-canary
aws_secret_access_key = secret-key-canary
aws_session_token = session-canary
credential_source = Environment
source_profile = legacy-source
role_arn = arn:aws:iam::123456789012:role/legacy
web_identity_token_file = /tmp/legacy-token
sso_session = legacy-sso
sso_account_id = 123456789012

[profile unrelated]
region = us-west-2
role_arn = arn:aws:iam::123456789012:role/preserved
EOF
"$aws_modifier" < "$test_dir/aws-input" > "$test_dir/aws-output"
rg -Fx "credential_process = $fixture_home/.local/bin/secret-exec aws-credential-process aws" \
  "$test_dir/aws-output" >/dev/null || fail 'AWS must resolve credentials through secret-exec'
! rg -F 'old-helper' "$test_dir/aws-output" >/dev/null || \
  fail 'AWS output must not retain the legacy credential-process helper'
! sed -n '/^\[default\]$/,/^\[/p' "$test_dir/aws-output" | \
  rg -e 'login_session|aws_(access_key_id|secret_access_key|session_token)|credential_source|source_profile|role_arn|web_identity_token_file|sso_' >/dev/null || \
  fail 'the default AWS profile must not retain higher-precedence or partial credentials'
rg -Fx '[profile unrelated]' "$test_dir/aws-output" >/dev/null || fail 'unrelated AWS profiles must be preserved'
rg -Fx 'role_arn = arn:aws:iam::123456789012:role/preserved' "$test_dir/aws-output" >/dev/null || \
  fail 'unrelated AWS authentication settings must be preserved'

proton_environment=home/dot_config/environment.d/98-proton-pass.conf
[[ $(<"$proton_environment") == \
  $'# Keep Proton Pass sessions available across Linux launch contexts and reboots.\nPROTON_PASS_LINUX_KEYRING=dbus' ]] || \
  fail 'Proton Pass must use the persistent Linux Secret Service provider'

[[ ! -e home/dot_config/private_secret-exec/profiles ]] || \
  fail 'plaintext profile sources must not remain in the repository'
[[ ! -e home/dot_config/private_secret-exec/commands.env ]] || \
  fail 'the plaintext command-map source must not remain in the repository'
[[ ! -e home/dot_config/secret-exec ]] || \
  fail 'the legacy secret-exec source root must not remain in the repository'

profile_templates=(home/dot_config/private_secret-exec/private_profiles/private_*.env.tmpl(N))
(( ${#profile_templates} > 0 )) || fail 'encrypted profile templates are required'
rendered_profiles=$test_dir/rendered-profiles
mkdir -m 700 -- "$rendered_profiles"
for profile_template in "${profile_templates[@]}"; do
  profile_name=${${profile_template:t}#private_}
  profile_name=${profile_name%.env.tmpl}
  rendered_profile=$rendered_profiles/$profile_name.env
  chezmoi -S home execute-template \
    --override-data-file tests/fixtures/secret-exec-public.toml \
    < "$profile_template" > "$rendered_profile"
  chmod 600 "$rendered_profile"
  [[ -s $rendered_profile ]] || fail "$profile_name fixture profile must not be empty"
  while IFS= read -r profile_line || [[ -n $profile_line ]]; do
    [[ -z $profile_line || $profile_line == \#* ||
      $profile_line == \![A-Za-z_][A-Za-z0-9_]# ||
      $profile_line == [A-Za-z_][A-Za-z0-9_]#=(pass://[^[:space:]]#|secret-service://) ]] || \
      fail "$profile_name fixture profile contains an invalid mapping"
  done < "$rendered_profile"
done

commands_template=home/dot_config/private_secret-exec/private_commands.env.tmpl
rendered_commands=$test_dir/rendered-commands.env
chezmoi -S home execute-template \
  --override-data-file tests/fixtures/secret-exec-public.toml \
  < "$commands_template" > "$rendered_commands"
while IFS= read -r command_line || [[ -n $command_line ]]; do
  [[ -z $command_line || $command_line == \#* ||
    $command_line == [A-Za-z0-9][A-Za-z0-9_.+-]#=[A-Za-z0-9][A-Za-z0-9_.-]# ]] || \
    fail 'the fixture command map contains an invalid mapping'
done < "$rendered_commands"

! rg -n '(^|[^[:alnum:]_])(pass|secret-service)://' \
  home/dot_config/private_secret-exec --glob '!*.age' >/dev/null || \
  fail 'public secret-exec sources must not expose backend locators'

print -r -- 'secret injection binding checks passed'
