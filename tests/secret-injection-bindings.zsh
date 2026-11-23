#!/usr/bin/env zsh
set -euo pipefail
setopt extended_glob

repo_root=${0:A:h:h}
cd "$repo_root"

# Test assertions use stdlib tomllib (Python 3.11+); the modifier supports 3.9+.
python3 -I -S -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "secret-injection-bindings tests require Python 3.11+")'

# exit, not return: errexit inside a function skips zsh's EXIT trap.
fail() {
  print -u2 -r -- "$1"
  exit 1
}

test_dir=$(mktemp -d "${TMPDIR:-/tmp}/secret-injection-bindings.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT

# zsh skips EXIT traps when errexit fires inside a function.
TRAPZERR() {
  if [[ -o errexit ]] && (( ZSH_SUBSHELL == 0 && ${#funcstack} > 1 )); then
    rm -rf -- "$test_dir"
  fi
}
export UV_CACHE_DIR=$test_dir/uv-cache
fixture_home=$test_dir/home
mkdir -p -- "$fixture_home"
fixture_home=${fixture_home:A}
context7_field=CONTEXT7
context7_field+=_API_KEY
firecrawl_field=FIRECRAWL
firecrawl_field+=_API_KEY
github_field=GITHUB_PERSONAL_ACCESS
github_field+=_TOKEN
aws_access_setting=aws_access_key
aws_access_setting+=_id
aws_secret_setting=aws_secret_access
aws_secret_setting+=_key
aws_session_setting=aws_session
aws_session_setting+=_token
darwin_data='{"chezmoi":{"os":"darwin","homeDir":"'${fixture_home}'","hostname":"test-host"},"gitIdentity":{"publicFixture":true,"selection":{"default":"personal","byHostname":{}},"identities":{"personal":{"email":"ivan@nisavid.io","editorTarget":"cursor","branchPrefix":"nisavid/","noTracking":false}}}}'

render_modifier() {
  local source=$1
  local target=$2
  chezmoi -S "$repo_root/home" execute-template --override-data "$darwin_data" < "$source" > "$target"
  chmod +x "$target"
}

codex_modifier=$test_dir/modify-codex
render_modifier home/dot_codex/modify_private_config.toml.tmpl "$codex_modifier"
cat > "$test_dir/codex-input.toml" <<EOF
unrelated = "preserved"

[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"
startup_timeout_sec = 30

[mcp_servers.context7.http_headers]
$context7_field = "ambient-canary"

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

python3 -I -S - "$test_dir/codex-output.toml" "$fixture_home" <<'PYEOF'
import sys, tomllib

path, home = sys.argv[1:]
with open(path, "rb") as config:
    doc = tomllib.load(config)
assert doc["unrelated"] == "preserved"
expected = {
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
    assert set(server) == {"command", "args"}, server
# Context7 is remote, with its key from the header helper (dotfiles#522).
assert doc["mcp_servers"]["context7"] == {
    "url": "https://mcp.context7.com/mcp",
    "http_headers_helper": f"{home}/.local/bin/secret-exec context7 -- {home}/.local/lib/secret-exec/context7-http-headers",
    "startup_timeout_sec": 30,
}, doc["mcp_servers"]["context7"]
PYEOF
! rg -n 'ambient-canary' "$test_dir/codex-output.toml" > /dev/null ||
  fail 'Codex output must not keep a Context7 key'
"$codex_modifier" < "$test_dir/codex-output.toml" | cmp -s - "$test_dir/codex-output.toml" ||
  fail 'the Codex modifier must be idempotent'

# Every earlier form of the Codex context7 entry becomes the remote entry: the
# local launcher, keys in the environment, in a header, or named by a variable,
# and no entry at all. Other settings and other servers stay as they are.
codex_context7_forms=(
  "command = \"$fixture_home/.local/bin/secret-exec\"
args = [\"context7\", \"--\", \"npx\", \"-y\", \"@upstash/context7-mcp@3.2.4\"]
enabled = false
tool_timeout_sec = 90"
  "command = \"npx\"
args = [\"-y\", \"@upstash/context7-mcp\"]
cwd = \"/tmp/context7\"
env = { $context7_field = \"context7-canary\" }
env_vars = [\"$context7_field\"]"
  "type = \"streamable_http\"
url = \"https://mcp.context7.example.invalid/mcp\"
bearer_token_env_var = \"$context7_field\"
env_http_headers = { \"Authorization\" = \"$context7_field\" }
headers = { \"X-Key\" = \"context7-canary\" }"
  ''
)
for form in "${codex_context7_forms[@]}"; do
  {
    print -r -- '[mcp_servers.notes]'
    print -r -- 'command = "notes-mcp"'
    if [[ -n $form ]]; then
      print -r -- '[mcp_servers.context7]'
      print -r -- "$form"
    fi
  } > "$test_dir/codex-form.toml"
  "$codex_modifier" < "$test_dir/codex-form.toml" > "$test_dir/codex-form-output.toml"
  python3 -I -S - "$test_dir/codex-form.toml" "$test_dir/codex-form-output.toml" "$fixture_home" <<'PYEOF' ||
import sys, tomllib

source_path, output_path, home = sys.argv[1:]
with open(source_path, "rb") as config:
    source = tomllib.load(config)["mcp_servers"].get("context7", {})
with open(output_path, "rb") as config:
    servers = tomllib.load(config)["mcp_servers"]
assert servers["notes"] == {"command": "notes-mcp"}
kept = {key: value for key, value in source.items() if key in {"enabled", "tool_timeout_sec"}}
assert servers["context7"] == {
    **kept,
    "url": "https://mcp.context7.com/mcp",
    "http_headers_helper": f"{home}/.local/bin/secret-exec context7 -- {home}/.local/lib/secret-exec/context7-http-headers",
}, servers["context7"]
PYEOF
    fail "the Codex modifier must write the remote Context7 entry from: ${form:-no entry}"
  ! rg -n 'context7-canary|context7.example|context7-mcp|/tmp/context7' "$test_dir/codex-form-output.toml" > /dev/null ||
    fail 'Codex output must not keep an earlier Context7 field'
done

# Every managed entry drops the same fields that can carry a key, or choose the
# credential Codex sends, and every field of the transport it does not use.
for server in context7 firecrawl github; do
  print -r -- "[mcp_servers.$server]
type = \"fields-canary\"
command = \"fields-canary\"
args = [\"fields-canary\"]
cwd = \"/tmp/fields-canary\"
env = { $context7_field = \"fields-canary\" }
env_vars = [\"$context7_field\"]
url = \"https://fields-canary.example.invalid/mcp\"
headers = { X-Key = \"fields-canary\" }
http_headers = { X-Key = \"fields-canary\" }
env_http_headers = { X-Key = \"$context7_field\" }
bearer_token_env_var = \"$context7_field\"
bearer_token = \"fields-canary\"
oauth = { client_id = \"fields-canary\", client_secret = \"fields-canary\" }
oauth_resource = \"https://fields-canary.example.invalid\"
auth = \"oauth\"
enabled = true" > "$test_dir/codex-fields.toml"
  "$codex_modifier" < "$test_dir/codex-fields.toml" > "$test_dir/codex-fields-output.toml"
  python3 -I -S - "$server" "$test_dir/codex-fields-output.toml" <<'PYEOF' ||
import sys, tomllib

name, output_path = sys.argv[1:]
with open(output_path, "rb") as config:
    server = tomllib.load(config)["mcp_servers"][name]
expected = {"url", "http_headers_helper"} if name == "context7" else {"command", "args"}
assert set(server) == expected | {"enabled"}, server
PYEOF
    fail "the Codex modifier must drop every key-carrying and other-transport field from $server"
  ! rg -n "fields-canary|$context7_field" "$test_dir/codex-fields-output.toml" > /dev/null ||
    fail "Codex output must not keep a key-carrying field of $server"
done

# A managed entry split over several table headers, written with dotted keys,
# or placed after another top-level table is rewritten as one plain table, and a
# second run changes nothing.
codex_layout_expect=$test_dir/codex-layout-expect.py
cat > "$codex_layout_expect" <<'PYEOF'
import sys, tomllib

name, output_path, home = sys.argv[1:]
with open(output_path, "rb") as config:
    servers = tomllib.load(config)["mcp_servers"]
assert servers["notes"] == {"command": "notes-mcp"}, servers["notes"]
launcher = f"{home}/.local/bin/secret-exec"
expected = {
    "context7": {
        "url": "https://mcp.context7.com/mcp",
        "http_headers_helper": f"{launcher} context7 -- {home}/.local/lib/secret-exec/context7-http-headers",
    },
    "firecrawl": {
        "command": launcher,
        "args": ["firecrawl", "--", "npx", "-y", "firecrawl-mcp@3.22.3"],
    },
    "github": {
        "command": launcher,
        "args": [
            "github", "--", "npx", "-y", "mcp-remote@0.1.38",
            "https://api.githubcopilot.com/mcp/", "--header",
            "Authorization:Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}",
        ],
    },
}[name]
assert servers[name] == {**expected, "startup_timeout_sec": 20}, servers[name]
PYEOF
for server in context7 firecrawl github; do
  if [[ $server == context7 ]]; then
    key_table=env
    transport_field='command = "npx"'
  else
    key_table=http_headers
    transport_field='url = "https://mcp.example.invalid/mcp"'
  fi
  print -r -- "[mcp_servers.$server]
$transport_field
startup_timeout_sec = 20

[mcp_servers.notes]
command = \"notes-mcp\"

[mcp_servers.$server.$key_table]
$context7_field = \"layout-canary\"" > "$test_dir/codex-layout-split.toml"
  print -r -- "[mcp_servers]
notes.command = \"notes-mcp\"
$server.$transport_field
$server.$key_table.$context7_field = \"layout-canary\"
$server.startup_timeout_sec = 20" > "$test_dir/codex-layout-dotted.toml"
  print -r -- "[mcp_servers.notes]
command = \"notes-mcp\"

[tui]
theme = \"fixture\"

[mcp_servers.$server]
$transport_field
startup_timeout_sec = 20

[mcp_servers.$server.$key_table]
$context7_field = \"layout-canary\"" > "$test_dir/codex-layout-around.toml"
  for layout in split dotted around; do
    "$codex_modifier" < "$test_dir/codex-layout-$layout.toml" > "$test_dir/codex-layout-output.toml" ||
      fail "the Codex modifier must rewrite a $layout $server entry"
    python3 -I -S "$codex_layout_expect" "$server" "$test_dir/codex-layout-output.toml" "$fixture_home" ||
      fail "the Codex modifier must write the managed $server entry from a $layout layout"
    ! rg -n 'layout-canary' "$test_dir/codex-layout-output.toml" > /dev/null ||
      fail "Codex output must not keep a key from a $layout $server entry"
    "$codex_modifier" < "$test_dir/codex-layout-output.toml" | cmp -s - "$test_dir/codex-layout-output.toml" ||
      fail "a second run must not change a rewritten $layout $server entry"
  done
done
# A top-level dotted key: tomlkit renders this one so that the instruction budget
# reads back inside context7. The modifier writes the right config or fails with
# no output.
print -r -- 'model = "fixture"
mcp_servers.context7.url = "https://mcp.context7.example.invalid/mcp"' > "$test_dir/codex-layout-top-dotted.toml"
if "$codex_modifier" < "$test_dir/codex-layout-top-dotted.toml" > "$test_dir/codex-layout-output.toml" \
  2> /dev/null; then
  python3 -I -S -c '
import sys, tomllib
with open(sys.argv[1], "rb") as config:
    doc = tomllib.load(config)
assert doc["model"] == "fixture" and isinstance(doc["project_doc_max_bytes"], int), doc
assert all("project_doc_max_bytes" not in server for server in doc["mcp_servers"].values()), doc
' "$test_dir/codex-layout-output.toml" || fail 'the Codex modifier must not write a config that reads back differently'
else
  [[ ! -s $test_dir/codex-layout-output.toml ]] || fail 'a failing Codex modifier must print nothing'
fi

# The helper command survives a home path that needs shell quoting.
spaced_data=${darwin_data//${fixture_home}/$test_dir/spaced home}
[[ $spaced_data == *'spaced home'* ]] || fail 'the spaced-home fixture data must name the spaced home'
chezmoi -S "$repo_root/home" execute-template --override-data "$spaced_data" \
  < home/dot_codex/modify_private_config.toml.tmpl > "$test_dir/modify-codex-spaced"
chmod +x "$test_dir/modify-codex-spaced"
"$test_dir/modify-codex-spaced" < /dev/null | python3 -I -S -c '
import shlex, sys, tomllib
home = sys.argv[1]
command = tomllib.loads(sys.stdin.read())["mcp_servers"]["context7"]["http_headers_helper"]
assert shlex.split(command) == [
    f"{home}/.local/bin/secret-exec", "context7", "--",
    f"{home}/.local/lib/secret-exec/context7-http-headers",
], command
' "$test_dir/spaced home" || fail 'the Codex helper command must quote a home path with a space'

# The header helper, run as Codex runs it: through `sh -c`, with a cleared
# environment, under a stand-in secret-exec that supplies the key.
helper_home=$test_dir/helper-home
mkdir -p -- "$helper_home/.local/bin" "$helper_home/.local/lib/secret-exec"
cp home/private_dot_local/lib/secret-exec/executable_context7-http-headers \
  "$helper_home/.local/lib/secret-exec/context7-http-headers"
chmod 755 "$helper_home/.local/lib/secret-exec/context7-http-headers"
cat > "$helper_home/.local/bin/secret-exec" <<'EOF'
#!/bin/zsh -f
[[ $1 == context7 && $2 == -- ]] || exit 64
shift 2
if [[ -n ${STAND_IN_VALUE+set} ]]; then
  export CONTEXT7_API_KEY=$STAND_IN_VALUE
else
  unset CONTEXT7_API_KEY
fi
exec "$@"
EOF
chmod 755 "$helper_home/.local/bin/secret-exec"
helper_command="$helper_home/.local/bin/secret-exec context7 -- $helper_home/.local/lib/secret-exec/context7-http-headers"
run_helper() {
  env -i PATH=/usr/bin:/bin HOME=$helper_home "$@" sh -c "$helper_command" 2> "$test_dir/helper.err"
}
# Every bearer-token character class: letters, digits, and - . _ ~ + / =.
stand_in_value='context7-canary_1.2~3+4/5=='
helper_output=$(run_helper "STAND_IN_VALUE=$stand_in_value") ||
  fail 'the Context7 helper must succeed when the key is set'
[[ ! -s $test_dir/helper.err ]] || fail 'a successful Context7 helper must write nothing to stderr'
print -r -- "$helper_output" | jq -se --arg value "$stand_in_value" '
  length == 1 and .[0] == {Authorization: ("Bearer " + $value)}
' > /dev/null || fail 'the Context7 helper must print exactly one JSON object with the Authorization header'
[[ $helper_output == "{\"Authorization\":\"Bearer $stand_in_value\"}" ]] ||
  fail 'the Context7 helper must print one line'
for value in UNSET '' 'context7"canary' 'context7\canary' 'context7 canary' 'context7=canary'; do
  if [[ $value == UNSET ]]; then
    helper_args=()
  else
    helper_args=("STAND_IN_VALUE=$value")
  fi
  if helper_output=$(run_helper "${helper_args[@]}"); then
    fail "the Context7 helper must fail for a missing or invalid key: ${value:-empty}"
  fi
  [[ -z $helper_output ]] || fail 'a failing Context7 helper must print nothing'
  [[ $(<"$test_dir/helper.err") != *canary* ]] ||
    fail 'the Context7 helper diagnostic must not contain the value'
done

claude_modifier=$test_dir/modify-claude
render_modifier home/modify_private_dot_claude.json.tmpl "$claude_modifier"
authorization_key=Author
authorization_key+=ization
cat > "$test_dir/claude-input.json" <<EOF
{
  "unrelated": "preserved",
  "pluginUsage": {
    "context7@inline": {"usageCount": 7},
    "serena@claude-plugins-official": {"usageCount": 3},
    "serena@inline": {"usageCount": 2}
  },
  "mcpServers": {
    "context7": {"type": "http", "url": "https://mcp.context7.com/mcp", "headers": {"$context7_field": "context7-canary"}, "timeout": 60000},
    "firecrawl": {"type": "http", "url": "https://mcp.firecrawl.dev/firecrawl-canary/v2/mcp", "tools": ["scrape"]},
    "github": {"type": "http", "url": "https://github.example.invalid", "env": {"$github_field": "github-canary"}, "disabled": true},
    "greptile": {"type": "http", "url": "https://greptile.example.invalid", "http_headers": {"$authorization_key": "greptile-canary"}, "timeout": 30000},
    "serena": {"command": "serena", "args": ["start-mcp-server"]}
  }
}
EOF
"$claude_modifier" < "$test_dir/claude-input.json" > "$test_dir/claude-output.json"
jq -e --arg command "$fixture_home/.local/bin/secret-exec" '
  .unrelated == "preserved" and
  .pluginUsage["context7@inline"] == {usageCount: 7} and
  (.mcpServers | has("context7") | not) and
  .mcpServers.firecrawl == {command: $command, args: ["firecrawl", "--", "npx", "-y", "firecrawl-mcp@3.22.3"], tools: ["scrape"]} and
  .mcpServers.github == {command: $command, args: ["github", "--", "npx", "-y", "mcp-remote@0.1.38", "https://api.githubcopilot.com/mcp/", "--header", "Authorization:Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}"], disabled: true} and
  .mcpServers.greptile == {command: $command, args: ["greptile", "--", "npx", "-y", "mcp-remote@0.1.38", "https://api.greptile.com/mcp", "--header", "Authorization:Bearer ${GREPTILE_API_KEY}"], timeout: 30000} and
  (.mcpServers | has("serena") | not) and
  (.pluginUsage | has("serena@claude-plugins-official") | not) and
  (.pluginUsage | has("serena@inline") | not) and
  ([.mcpServers.firecrawl, .mcpServers.github, .mcpServers.greptile] |
    all(. as $server | ["type", "url", "env", "env_vars", "headers", "http_headers", "bearer_token_env_var"] |
      all(. as $field | ($server | has($field) | not))))
' "$test_dir/claude-output.json" > /dev/null || fail 'Claude MCP bindings must use process-scoped launch profiles'
! rg -n 'context7-canary|firecrawl-canary|github-canary|greptile-canary|ambient-canary' "$test_dir/claude-output.json" >/dev/null || \
  fail 'Claude output must retire credential-bearing MCP URLs'
[[ $(tail -c 1 "$test_dir/claude-output.json" | od -An -c | tr -d ' ') == '}' ]] ||
  fail 'Claude output must end without a final newline, as Claude Code writes ~/.claude.json'

# Claude Code takes Context7 from the official plugin (dotfiles#521): the
# modifier removes a user-scope context7 entry in every form, the secret-exec
# launcher, a remote url entry, and one with a key in env or headers, and leaves
# the other managed entries as they are.
claude_managed_output=$(jq -c '.mcpServers | {firecrawl, github, greptile}' "$test_dir/claude-output.json")
for context7_entry in \
  "{\"command\": \"$fixture_home/.local/bin/secret-exec\", \"args\": [\"context7\", \"--\", \"npx\", \"-y\", \"@upstash/context7-mcp@3.2.4\"]}" \
  '{"type": "http", "url": "https://mcp.context7.com/mcp"}' \
  "{\"command\": \"npx\", \"args\": [\"-y\", \"@upstash/context7-mcp\"], \"env\": {\"$context7_field\": \"context7-canary\"}}" \
  "{\"type\": \"http\", \"url\": \"https://mcp.context7.com/mcp\", \"headers\": {\"$context7_field\": \"context7-canary\"}}"; do
  jq --argjson entry "$context7_entry" '.mcpServers.context7 = $entry' \
    "$test_dir/claude-input.json" | "$claude_modifier" > "$test_dir/claude-context7-output.json"
  jq -e --argjson managed "$claude_managed_output" '
    (.mcpServers | has("context7") | not) and
    (.mcpServers | {firecrawl, github, greptile}) == $managed
  ' "$test_dir/claude-context7-output.json" > /dev/null ||
    fail "the Claude modifier must remove a user-scope context7 entry and keep the other managed entries: $context7_entry"
  ! rg -n 'context7-canary' "$test_dir/claude-context7-output.json" > /dev/null ||
    fail 'Claude output must not keep a Context7 key'
done
jq 'del(.mcpServers.context7)' "$test_dir/claude-input.json" | "$claude_modifier" |
  jq -e '.mcpServers | has("context7") | not' > /dev/null ||
  fail 'the Claude modifier must not add a context7 entry'
"$claude_modifier" < "$test_dir/claude-output.json" | cmp -s - "$test_dir/claude-output.json" ||
  fail 'the Claude modifier must be idempotent'

settings_modifier=$test_dir/modify-claude-settings
render_modifier home/dot_claude/modify_private_settings.json.tmpl "$settings_modifier"
cat > "$test_dir/settings-input.json" <<'EOF'
{
  "unrelated": "preserved",
  "enabledPlugins": {
    "context7@claude-plugins-official": false,
    "context7@inline": true,
    "context7@synced": true,
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
  .enabledPlugins["context7@claude-plugins-official"] == true and
  .enabledPlugins["context7@inline"] == false and
  .enabledPlugins["context7@synced"] == false and
  .enabledPlugins["firecrawl@claude-plugins-official"] == true and
  .enabledPlugins["github@claude-plugins-official"] == false and
  .enabledPlugins["greptile@claude-plugins-official"] == false and
  (.enabledPlugins | has("serena@claude-plugins-official") | not)
' "$test_dir/settings-output.json" > /dev/null || fail 'the official Context7 plugin must be on, its account copies off, and the GitHub and Greptile plugin MCPs off without disabling Firecrawl skills'
# With no context7 entries at all, the official one is written true and the
# account copies false (dotfiles#521).
jq 'del(.enabledPlugins["context7@claude-plugins-official", "context7@inline", "context7@synced"])' \
  "$test_dir/settings-input.json" | "$settings_modifier" | jq -e '
  .enabledPlugins["context7@claude-plugins-official"] == true and
  .enabledPlugins["context7@inline"] == false and
  .enabledPlugins["context7@synced"] == false and
  .enabledPlugins["github@claude-plugins-official"] == false and
  .enabledPlugins["greptile@claude-plugins-official"] == false
' > /dev/null || fail 'a missing official Context7 entry must be written true, with its account copies false'

# Plugin enablement from the explicit lists (dotfiles#479).
python3 -I -S - home/.chezmoidata/claude-plugins.toml <<'PYEOF' || fail 'accepted and explicitly-off plugin lists must hold 64 and 15 distinct, disjoint names'
import sys, tomllib
with open(sys.argv[1], "rb") as data_file:
    plugins = tomllib.load(data_file)["claudePlugins"]
accepted, off = plugins["accepted"], plugins["explicitlyOff"]
assert len(accepted) == len(set(accepted)) == 64
assert len(off) == len(set(off)) == 15
assert not set(accepted) & set(off)
assert "real-skills-leashed" in off
assert "real-skills-unleashed" in accepted
assert {"investment-banking", "pitch-agent"} <= set(off)
assert not {"investment-banking", "pitch-agent"} & set(accepted)
PYEOF
python3 -I -S - home/.chezmoidata/claude-plugins.toml <<'PYEOF' || fail 'localWins must be exactly cloudflare, skill-creator and context7, all accepted, and off exactly linear@claude-plugins-official, naming no local-wins plugin'
import sys, tomllib
with open(sys.argv[1], "rb") as data_file:
    plugins = tomllib.load(data_file)["claudePlugins"]
one_copy = plugins["oneCopyPerSkill"]
assert one_copy["localWins"] == ["cloudflare", "skill-creator", "context7"]
assert one_copy["off"] == ["linear@claude-plugins-official"]
assert set(one_copy["localWins"]) <= set(plugins["accepted"])
assert not any(entry.split("@")[0] in one_copy["localWins"] for entry in one_copy["off"])
PYEOF
# The account copies of these eleven win (dotfiles#538): no rule names them.
python3 -I -S - home/.chezmoidata/claude-plugins.toml <<'PYEOF' || fail 'the eleven account-copy plugins must be accepted and have no entry in explicitlyOff, localWins, off or on'
import sys, tomllib
with open(sys.argv[1], "rb") as data_file:
    plugins = tomllib.load(data_file)["claudePlugins"]
one_copy = plugins["oneCopyPerSkill"]
account_copies_win = {"agent-sdk-dev", "clangd-lsp", "claude-code-setup", "codex",
                      "firebase", "firecrawl", "gopls-lsp", "lua-lsp", "mcp-apps",
                      "rust-analyzer-lsp", "typescript-lsp"}
assert account_copies_win <= set(plugins["accepted"])
assert not account_copies_win & (set(plugins["explicitlyOff"]) | set(one_copy["localWins"]))
assert not any(entry.split("@")[0] in account_copies_win
               for entry in one_copy["off"] + one_copy["on"])
PYEOF
explicitly_off=$(python3 -I -S - home/.chezmoidata/claude-plugins.toml <<'PYEOF'
import json, sys, tomllib
with open(sys.argv[1], "rb") as data_file:
    print(json.dumps(tomllib.load(data_file)["claudePlugins"]["explicitlyOff"]))
PYEOF
)

plugins_root=$fixture_home/.claude/plugins
registry=$plugins_root/installed_plugins.json
mkdir -p -- "$plugins_root"
# Explicitly-off names with local keys, a name that only starts with one, names
# on neither list, accepted names and one-copy entries.
cat > "$registry" <<'EOF'
{"version": 2, "plugins": {
  "supabase@claude-plugins-official": [],
  "real-skills-leashed@fixture-market": [],
  "remotion@other-market": [],
  "supabase-extra@claude-plugins-official": [],
  "unlisted-local@claude-plugins-official": [],
  "unlisted-fresh@claude-plugins-official": [],
  "codex@openai-codex": [],
  "cloudflare@claude-plugins-official": [],
  "firecrawl@claude-plugins-official": []
}}
EOF
cat > "$test_dir/plugins-input.json" <<'EOF'
{
  "unrelated": {
    "number": 1.50,
    "text": "é é",
    "list": [3, 1, 2]
  },
  "enabledPlugins": {
    "codex@openai-codex": true,
    "amd-skills@inline": true,
    "mergecraft@inline": true,
    "tricritical@synced": false,
    "unlisted-local@claude-plugins-official": true,
    "hand-curated@inline": false,
    "firecrawl@claude-plugins-official": true,
    "serena@claude-plugins-official": true
  },
  "trailing": null
}
EOF
"$settings_modifier" < "$test_dir/plugins-input.json" > "$test_dir/plugins-output.json"
jq -e '.enabledPlugins | to_entries[:7] == [
  {key: "codex@openai-codex", value: true},
  {key: "amd-skills@inline", value: false},
  {key: "mergecraft@inline", value: true},
  {key: "tricritical@synced", value: false},
  {key: "unlisted-local@claude-plugins-official", value: true},
  {key: "hand-curated@inline", value: false},
  {key: "firecrawl@claude-plugins-official", value: true}
]' "$test_dir/plugins-output.json" > /dev/null ||
  fail 'existing enabledPlugins entries must keep their place and value, except explicitly-off ones turned off and the stale Serena entry removed'
jq -e '.enabledPlugins | has("serena@claude-plugins-official") | not' "$test_dir/plugins-output.json" > /dev/null ||
  fail 'the stale Serena entry must be removed'
jq -e --argjson off "$explicitly_off" '
  (.enabledPlugins | to_entries[7:]) as $added |
  ($added | map(select(.value == true) | .key) | sort) ==
    ["cloudflare@claude-plugins-official", "context7@claude-plugins-official", "skill-creator@claude-plugins-official"] and
  ($added | map(select(.value == false) | .key) | sort) == (
    [$off[] | (. + "@inline"), (. + "@synced")] - ["amd-skills@inline"] + [
      "supabase@claude-plugins-official",
      "real-skills-leashed@fixture-market",
      "remotion@other-market",
      "linear@claude-plugins-official",
      "cloudflare@inline",
      "cloudflare@synced",
      "skill-creator@inline",
      "skill-creator@synced",
      "context7@inline",
      "context7@synced",
      "github@claude-plugins-official",
      "greptile@claude-plugins-official"
    ] | sort) and
  ($added | length) == ($added | map(.key) | unique | length)
' "$test_dir/plugins-output.json" > /dev/null ||
  fail 'the modifier must add false entries for exactly the explicitly-off names in both account forms and their installed keys, the local-wins and one-copy rules and the managed entries, and true for the three local-wins official entries'
jq -e '
  .enabledPlugins as $p |
  ["investment-banking", "pitch-agent"] |
  all(. as $n | $p[$n + "@inline"] == false and $p[$n + "@synced"] == false)
' "$test_dir/plugins-output.json" > /dev/null ||
  fail 'investment-banking and pitch-agent must be false in both account forms'

# The local copy wins for cloudflare, skill-creator and context7: the official
# entry is written true even where it exists as false, with no account entries
# present; linear stays false at the official marketplace; every other entry and
# setting is kept byte for byte, and a second run changes nothing.
cat > "$test_dir/local-wins-input.json" <<'EOF'
{
  "unrelated": {"number": 1.50, "text": "é é"},
  "enabledPlugins": {
    "cloudflare@claude-plugins-official": false,
    "skill-creator@claude-plugins-official": false,
    "context7@claude-plugins-official": false,
    "linear@claude-plugins-official": true,
    "firecrawl@claude-plugins-official": true,
    "kept-fixture@claude-plugins-official": false
  },
  "trailing": null
}
EOF
"$settings_modifier" < "$test_dir/local-wins-input.json" > "$test_dir/local-wins-output.json"
jq -e '
  .enabledPlugins as $p |
  ["cloudflare", "skill-creator", "context7"] |
  all(. as $n |
    $p[$n + "@claude-plugins-official"] == true and
    $p[$n + "@inline"] == false and $p[$n + "@synced"] == false)
' "$test_dir/local-wins-output.json" > /dev/null ||
  fail 'the three local-wins plugins must be true at the official marketplace and false in both account forms'
jq -e '
  .enabledPlugins as $p |
  $p["linear@claude-plugins-official"] == false and
  $p["firecrawl@claude-plugins-official"] == true and
  $p["kept-fixture@claude-plugins-official"] == false and
  ($p | has("firecrawl@inline") | not) and ($p | has("firecrawl@synced") | not)
' "$test_dir/local-wins-output.json" > /dev/null ||
  fail 'linear must stay false at the official marketplace, the Firecrawl and unrelated entries must be kept, and no Firecrawl account entry may be written'
diff <(jq 'del(.enabledPlugins)' "$test_dir/local-wins-input.json") \
  <(jq 'del(.enabledPlugins)' "$test_dir/local-wins-output.json") > /dev/null ||
  fail 'settings other than enabledPlugins must be preserved when the local copy wins'
jq 'del(.enabledPlugins)' "$test_dir/local-wins-output.json" | grep -q '"number": 1.50' ||
  fail 'number literals must be preserved when the local copy wins'
"$settings_modifier" < "$test_dir/local-wins-output.json" | cmp -s - "$test_dir/local-wins-output.json" ||
  fail 'the local-wins output must be unchanged by a second run'

# The account copies win for eleven plugins (dotfiles#538): the modifier writes
# no key for either copy of any of them, even when the registry lists their local
# copies, and keeps an existing entry for either copy as it is, whatever its
# value, so it forces neither copy on or off.
account_copies_win='["agent-sdk-dev", "clangd-lsp", "claude-code-setup", "codex", "firebase", "firecrawl", "gopls-lsp", "lua-lsp", "mcp-apps", "rust-analyzer-lsp", "typescript-lsp"]'
cp -- "$registry" "$test_dir/registry-before-account-copies.json"
jq --argjson names "$account_copies_win" '
  .plugins += ([$names[] | {key: (. + "@claude-plugins-official"), value: []}] | from_entries) |
  .plugins["codex@openai-codex"] = [] |
  .plugins["firebase@fixture-market"] = []
' "$test_dir/registry-before-account-copies.json" > "$registry"
print -r -- '{"enabledPlugins": {"kept-fixture@claude-plugins-official": true}}' |
  "$settings_modifier" | jq -e --argjson names "$account_copies_win" '
  def plugin_name: sub("@[^@]*$"; "");
  [.enabledPlugins | keys[] | select(plugin_name | IN($names[]))] == [] and
  .enabledPlugins["kept-fixture@claude-plugins-official"] == true
' > /dev/null ||
  fail 'the modifier must write no key for either copy of the eleven plugins whose account copies win'
for forced in true false; do
  jq -n --argjson names "$account_copies_win" --argjson forced "$forced" '
    {enabledPlugins: ([$names[] |
      {key: (. + "@claude-plugins-official"), value: $forced},
      {key: (. + "@inline"), value: ($forced | not)},
      {key: (. + "@synced"), value: ($forced | not)}] +
      [{key: "codex@openai-codex", value: $forced},
       {key: "firebase@fixture-market", value: $forced}] | from_entries)}
  ' > "$test_dir/account-copies-input.json"
  "$settings_modifier" < "$test_dir/account-copies-input.json" |
    jq -e --argjson names "$account_copies_win" --slurpfile input "$test_dir/account-copies-input.json" '
    def plugin_name: sub("@[^@]*$"; "");
    (.enabledPlugins | with_entries(select(.key | plugin_name | IN($names[])))) ==
      $input[0].enabledPlugins
  ' > /dev/null ||
    fail "the modifier must keep every existing entry of the eleven plugins whose account copies win as it is (local copies $forced)"
done
cp -- "$test_dir/registry-before-account-copies.json" "$registry"
python3 -I -S - home/.chezmoidata/claude-plugins.toml <<'PYEOF' || fail 'the fixture names on neither list must appear in neither list'
import sys, tomllib
with open(sys.argv[1], "rb") as data_file:
    plugins = tomllib.load(data_file)["claudePlugins"]
assert not {"unlisted-local", "unlisted-fresh", "supabase-extra", "hand-curated"} & (
    set(plugins["accepted"]) | set(plugins["explicitlyOff"]))
PYEOF
diff <(jq 'del(.enabledPlugins)' "$test_dir/plugins-input.json") \
  <(jq 'del(.enabledPlugins)' "$test_dir/plugins-output.json") > /dev/null ||
  fail 'settings other than enabledPlugins must be preserved'
jq 'del(.enabledPlugins)' "$test_dir/plugins-output.json" | grep -q '"number": 1.50' ||
  fail 'number literals in unrelated settings must be preserved byte for byte'
"$settings_modifier" < "$test_dir/plugins-output.json" > "$test_dir/plugins-output-2.json"
"$settings_modifier" < "$test_dir/plugins-output-2.json" > "$test_dir/plugins-output-3.json"
cmp -s "$test_dir/plugins-output.json" "$test_dir/plugins-output-2.json" &&
  cmp -s "$test_dir/plugins-output-2.json" "$test_dir/plugins-output-3.json" ||
  fail 'the settings modifier must be idempotent'
print -r -- '{"enabledPlugins": {"html@skills-dir": false}}' |
  "$settings_modifier" | jq -e '.enabledPlugins["html@skills-dir"] == true' > /dev/null ||
  fail 'the html user-skills entry must stay on'

# The stale Serena entry is removed even when the registry lists Serena.
cp -- "$registry" "$test_dir/installed-plugins.json"
jq '.plugins["serena@claude-plugins-official"] = []' "$test_dir/installed-plugins.json" > "$registry"
"$settings_modifier" < "$test_dir/plugins-input.json" |
  jq -e '.enabledPlugins | has("serena@claude-plugins-official") | not' > /dev/null ||
  fail 'the settings modifier must write no Serena key, even when the registry lists Serena'

# Without a registry, only the account forms of the explicitly-off names are set.
rm -f -- "$registry"
"$settings_modifier" < "$test_dir/plugins-input.json" | jq -e '
  .enabledPlugins as $p |
  $p["supabase@inline"] == false and $p["supabase@synced"] == false and
  ($p | has("supabase@claude-plugins-official") | not) and
  ($p | has("serena@claude-plugins-official") | not)
' > /dev/null || fail 'a missing installed-plugin registry must leave only the account forms of the explicitly-off names'

# An unreadable registry fails the apply with no output.
expect_modifier_failure() {
  local output
  if output=$("$settings_modifier" < "$test_dir/plugins-input.json" 2> /dev/null); then
    fail "$1"
  fi
  [[ -z $output ]] || fail "$1"
}
print -rn -- '{"version": 2, "plugins": {' > "$registry"
expect_modifier_failure 'a truncated installed-plugin registry must fail the apply'
: > "$registry"
expect_modifier_failure 'an empty installed-plugin registry must fail the apply'
{ cat -- "$test_dir/installed-plugins.json"; print -r -- '{"plugins": {}}'; } > "$registry"
expect_modifier_failure 'an installed-plugin registry holding two JSON documents must fail the apply'
{ cat -- "$test_dir/installed-plugins.json"; print -r -- '}'; } > "$registry"
expect_modifier_failure 'an installed-plugin registry with trailing garbage must fail the apply'
print -r -- '{"version": 2, "plugins": ["supabase@claude-plugins-official"]}' > "$registry"
expect_modifier_failure 'an installed-plugin registry whose plugins is not an object must fail the apply'
print -r -- '{"version": 2, "plugins": []}' > "$registry"
expect_modifier_failure 'an installed-plugin registry whose plugins is an empty list must fail the apply'
print -r -- '{"plugins": false}' > "$registry"
expect_modifier_failure 'an installed-plugin registry whose plugins is false must fail the apply'
print -r -- '{"plugins": null}' > "$registry"
expect_modifier_failure 'an installed-plugin registry whose plugins is null must fail the apply'
print -r -- '{}' > "$registry"
expect_modifier_failure 'an installed-plugin registry with no plugins key must fail the apply'
print -r -- '{"plugins": {}}' > "$registry"
"$settings_modifier" < "$test_dir/plugins-input.json" > /dev/null ||
  fail 'an installed-plugin registry with an empty plugins object must be valid'
cp -- "$test_dir/installed-plugins.json" "$registry"
"$settings_modifier" < "$test_dir/plugins-input.json" | cmp -s - "$test_dir/plugins-output.json" ||
  fail 'a restored installed-plugin registry must give the original output'

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
      "env": {"$firecrawl_field": "environment-canary"},
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

cursor_modifier=$test_dir/modify-cursor-mcp
render_modifier home/dot_cursor/modify_private_mcp.json.tmpl "$cursor_modifier"
cursor_client_id_field=CLIENT
cursor_client_id_field+=_ID
cursor_client_secret_field=CLIENT
cursor_client_secret_field+=_SECRET
# Cursor writes two-space JSON without a final newline; the fixtures match, so
# a byte comparison proves the other entries pass through unchanged.
cursor_other_entries=$(cat <<'EOF'
    "firecrawl": {
      "url": "https://mcp.firecrawl.example.invalid/v2/mcp",
      "headers": {
        "X-Example-Key": "firecrawl-canary"
      }
    },
    "notebooks": {
      "command": "uvx",
      "args": [
        "notebooks-mcp",
        "--flag"
      ]
    },
    "datacloud_example": {
      "command": "example",
      "args": [
        "serve"
      ],
      "env": {
        "EXAMPLE_ENV": "preserved"
      }
    }
EOF
)
# Cursor signs in to Context7's remote server with OAuth: the entry holds
# its OAuth address alone (dotfiles#522).
cursor_remote_entry=$(cat <<EOF
    "context7": {
      "url": "https://mcp.context7.com/mcp/oauth"
    }
EOF
)
print -rn -- "{
  \"mcpServers\": {
    \"context7\": {
      \"url\": \"https://mcp.context7.example.invalid/mcp\",
      \"headers\": {
        \"$context7_field\": \"context7-canary\"
      }
    },
$cursor_other_entries
  }
}" > "$test_dir/cursor-input.json"
print -rn -- "{
  \"mcpServers\": {
$cursor_remote_entry,
$cursor_other_entries
  }
}" > "$test_dir/cursor-expected.json"
"$cursor_modifier" < "$test_dir/cursor-input.json" > "$test_dir/cursor-output.json"
cmp -s "$test_dir/cursor-output.json" "$test_dir/cursor-expected.json" ||
  fail 'Cursor MCP config must replace only the Context7 entry and keep every other byte'
! rg -n 'context7-canary|context7.example' "$test_dir/cursor-output.json" >/dev/null ||
  fail 'Cursor output must retire the Context7 URL and credential'
"$cursor_modifier" < "$test_dir/cursor-output.json" | cmp -s - "$test_dir/cursor-output.json" ||
  fail 'the Cursor MCP modifier must be idempotent'

# A Context7 entry with other credential-carrying keys loses them and keeps
# unrelated metadata; the earlier local launcher becomes the remote entry.
print -rn -- "{\"mcpServers\":{\"context7\":{\"type\":\"http\",\"command\":\"npx\",\"args\":[\"mcp-remote\"],\"env\":{\"A\":\"b\"},\"env_vars\":[\"A\"],\"auth\":{\"$cursor_client_id_field\":\"a\",\"$cursor_client_secret_field\":\"b\"},\"envFile\":\".env\",\"http_headers\":{\"$authorization_key\":\"c\"},\"bearer_token_env_var\":\"A\",\"timeout\":60000}}}" |
  "$cursor_modifier" | jq -e '
  .mcpServers == {context7: {url: "https://mcp.context7.com/mcp/oauth", timeout: 60000}}
' > /dev/null || fail 'Cursor Context7 entry must lose every transport and credential key and keep other metadata'
print -rn -- "{\"mcpServers\":{\"context7\":{\"command\":\"$fixture_home/.local/bin/secret-exec\",\"args\":[\"context7\",\"--\",\"npx\",\"-y\",\"@upstash/context7-mcp@3.2.4\"]}}}" |
  "$cursor_modifier" | jq -e '
  .mcpServers == {context7: {url: "https://mcp.context7.com/mcp/oauth"}}
' > /dev/null || fail 'the earlier Cursor Context7 launcher must become the remote entry'

# Without an entry, a servers object, or a file, the remote entry appears.
print -rn -- '{"mcpServers":{"notebooks":{"command":"uvx"}},"unrelated":"preserved"}' |
  "$cursor_modifier" | jq -e '
  .unrelated == "preserved" and
  .mcpServers.notebooks == {command: "uvx"} and
  .mcpServers.context7 == {url: "https://mcp.context7.com/mcp/oauth"}
' > /dev/null || fail 'Cursor config without a Context7 entry must gain the remote entry'
print -rn -- '{"unrelated":"preserved"}' | "$cursor_modifier" | jq -e '
  .unrelated == "preserved" and (.mcpServers | keys) == ["context7"]
' > /dev/null || fail 'Cursor config without an mcpServers object must gain the remote entry'
"$cursor_modifier" < /dev/null | jq -e '(.mcpServers | keys) == ["context7"]' > /dev/null ||
  fail 'an empty Cursor config must gain only the remote entry'

# A file that is not exactly one JSON document fails with no output.
expect_cursor_failure() {
  local output
  if output=$(print -rn -- "$2" | "$cursor_modifier" 2> /dev/null); then
    fail "$1"
  fi
  [[ -z $output ]] || fail "$1"
}
expect_cursor_failure 'a truncated Cursor config must fail the apply' '{"mcpServers": {'
expect_cursor_failure 'a Cursor config holding two JSON documents must fail the apply' '{} {}'
expect_cursor_failure 'a Cursor config with a non-object mcpServers must fail the apply' '{"mcpServers": []}'

opencode_hook=$test_dir/update-opencode-context7
render_modifier home/run_after_update-opencode-context7.sh.tmpl "$opencode_hook"
mkdir -p -- "$fixture_home/.config/opencode"
# OpenCode signs in to Context7's remote server with OAuth (dotfiles#522): the
# entry keeps only its metadata, the remote type, and the OAuth address.
cat > "$fixture_home/.config/opencode/opencode.json" <<EOF
{
  "unrelated": "preserved",
  "mcp": {
    "notes": {"type": "local", "command": ["notes-mcp"]},
    "context7": {
      "type": "remote",
      "url": "https://mcp.context7.com/mcp",
      "headers": {"$context7_field": "literal-canary"},
      "environment": {"$context7_field": "opencode-environment-canary"},
      "env": {"$context7_field": "environment-canary"},
      "env_vars": ["$context7_field"],
      "http_headers": {"X-API-Key": "$http_header_canary"},
      "bearer_token_env_var": "CONTEXT7_API_KEY",
      "oauth": {"clientId": "client", "clientSecret": "oauth-secret-canary"},
      "timeout": 60000
    }
  }
}
EOF
"$opencode_hook"
jq -e '
  .unrelated == "preserved" and
  .mcp.notes == {type: "local", command: ["notes-mcp"]} and
  .mcp.context7 == {
    type: "remote",
    url: "https://mcp.context7.com/mcp/oauth",
    enabled: true,
    timeout: 60000
  }
' "$fixture_home/.config/opencode/opencode.json" > /dev/null || \
  fail 'OpenCode Context7 must use the remote OAuth entry while preserving metadata'
! rg -n 'literal-canary|environment-canary|http-header-canary|oauth-secret-canary|CONTEXT7_API_KEY|secret-exec|context7-mcp' \
  "$fixture_home/.config/opencode/opencode.json" >/dev/null || \
  fail 'OpenCode output must not retain Context7 authentication data or the local launcher'
[[ $(stat -c %a "$fixture_home/.config/opencode/opencode.json" 2>/dev/null ||
  stat -f %Lp "$fixture_home/.config/opencode/opencode.json") == 600 ]] ||
  fail 'the OpenCode Context7 hook must leave the configuration private'
cp "$fixture_home/.config/opencode/opencode.json" "$test_dir/opencode-once.json"
"$opencode_hook"
cmp -s "$fixture_home/.config/opencode/opencode.json" "$test_dir/opencode-once.json" ||
  fail 'the OpenCode Context7 hook must be idempotent'
jq '.mcp.context7.enabled = false' "$fixture_home/.config/opencode/opencode.json" > \
  "$test_dir/opencode-disabled.json"
mv "$test_dir/opencode-disabled.json" "$fixture_home/.config/opencode/opencode.json"
"$opencode_hook"
jq -e '.mcp.context7.enabled == false' "$fixture_home/.config/opencode/opencode.json" > /dev/null || \
  fail 'OpenCode Context7 migration must preserve an explicit disabled state'
# The earlier local launcher, an entry that turns the sign-in off, and a file
# with no entry all end with the remote entry.
for opencode_input in \
  "{\"mcp\":{\"context7\":{\"type\":\"local\",\"command\":[\"$fixture_home/.local/bin/secret-exec\",\"context7\",\"--\",\"npx\",\"-y\",\"@upstash/context7-mcp@3.2.4\"],\"enabled\":true}}}" \
  '{"mcp":{"context7":{"type":"remote","url":"https://mcp.context7.com/mcp/oauth","oauth":false}}}' \
  '{"unrelated":"preserved"}'; do
  print -r -- "$opencode_input" > "$fixture_home/.config/opencode/opencode.json"
  "$opencode_hook"
  jq -e '.mcp.context7 == {type: "remote", url: "https://mcp.context7.com/mcp/oauth", enabled: true}' \
    "$fixture_home/.config/opencode/opencode.json" > /dev/null ||
    fail "the OpenCode Context7 hook must write the remote entry from: $opencode_input"
done

aws_modifier=$test_dir/modify-aws-config
render_modifier home/private_dot_aws/modify_private_config.tmpl "$aws_modifier"
cat > "$test_dir/aws-input" <<EOF
[default]
region = us-east-1
login_session = personal
credential_process = old-helper
$aws_access_setting = access-key-canary
$aws_secret_setting = secret-key-canary
$aws_session_setting = session-canary
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
  [[ $profile_name == github ]] && continue
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

render_github_profile() {
  local host=$1
  local target=$2
  local override_data
  override_data=$(printf '{"chezmoi":{"hostname":"%s"}}' "$host")
  chezmoi -S home execute-template \
    --override-data "$override_data" \
    --override-data-file tests/fixtures/secret-exec-public.toml \
    < home/dot_config/private_secret-exec/private_profiles/private_github.env.tmpl > "$target"
}

github_personal_profile=$test_dir/github-personal.env
render_github_profile test-host "$github_personal_profile"
grep -Fx '# secret-exec-github-profile=github-fixture-personal' "$github_personal_profile" >/dev/null || \
  fail 'the fixture host must select the personal GitHub profile'
grep -Fx '# secret-exec-github-login=fixture-personal' "$github_personal_profile" >/dev/null || \
  fail 'the fixture host must carry the personal GitHub identity marker'
grep -Fx 'GITHUB_PERSONAL_ACCESS_TOKEN=pass://fixture-vault/item-d/password' "$github_personal_profile" >/dev/null || \
  fail 'the fixture host must render the personal GitHub locator'

github_secondary_profile=$test_dir/github-secondary.env
render_github_profile second-host "$github_secondary_profile"
grep -Fx '# secret-exec-github-profile=github-fixture-secondary' "$github_secondary_profile" >/dev/null || \
  fail 'the second fixture host must select the secondary GitHub profile'
grep -Fx '# secret-exec-github-login=fixture-secondary' "$github_secondary_profile" >/dev/null || \
  fail 'the second fixture host must carry the secondary GitHub identity marker'
grep -Fx 'GITHUB_PERSONAL_ACCESS_TOKEN=pass://fixture-vault/item-f/password' "$github_secondary_profile" >/dev/null || \
  fail 'the second fixture host must render its distinct GitHub locator'

if render_github_profile unknown-fixture "$test_dir/github-unknown.env" 2> "$test_dir/github-unknown.err"; then
  fail 'an unbound host must not render a GitHub profile'
fi
grep -F 'no GitHub credential binding for host' "$test_dir/github-unknown.err" >/dev/null || \
  fail 'an unbound host must report a value-free profile-selection failure'
for confidential_value in github-fixture-personal github-fixture-secondary \
  fixture-personal fixture-secondary fixture-vault 'pass://'; do
  if grep -F -- "$confidential_value" "$test_dir/github-unknown.env" \
    "$test_dir/github-unknown.err" >/dev/null; then
    fail 'an unbound host must not disclose profile, identity, or locator data'
  fi
done

if render_github_profile missing-profile-host "$test_dir/github-missing.env" \
  2> "$test_dir/github-missing.err"; then
  fail 'a binding that names a missing profile must not render a GitHub profile'
fi
grep -F 'names a missing profile' "$test_dir/github-missing.err" >/dev/null || \
  fail 'a binding that names a missing profile must report a value-free failure'
if grep -F -e github-fixture-missing -e fixture-vault -e 'pass://' \
  "$test_dir/github-missing.env" "$test_dir/github-missing.err" >/dev/null; then
  fail 'a binding that names a missing profile must not disclose profile or locator data'
fi

commands_template=home/dot_config/private_secret-exec/private_commands.env.tmpl
rendered_commands=$test_dir/rendered-commands.env
chezmoi -S home execute-template \
  --override-data-file tests/fixtures/secret-exec-public.toml \
  < "$commands_template" > "$rendered_commands"
command_mapping_line_valid() {
  [[ -z $1 || $1 == \#* ||
    $1 == [A-Za-z0-9][A-Za-z0-9_.+-]#=[A-Za-z0-9][A-Za-z0-9_.-]#(|[?]) ]]
}
for command_line in tool=profile 'tool=profile?' 'tool.x+y=pro_file-1.2?'; do
  command_mapping_line_valid "$command_line" ||
    fail "the command-map syntax must accept $command_line"
done
for command_line in 'tool=profile??' 'tool=?' 'tool=?profile' 'tool=pro?file' \
  'tool?=profile' 'tool=profile ?' 'tool=' '=profile'; do
  ! command_mapping_line_valid "$command_line" ||
    fail "the command-map syntax must reject $command_line"
done
grep -Fqx 'tool-b=aws?' "$rendered_commands" ||
  fail 'the fixture command map must exercise a best-effort mapping'
while IFS= read -r command_line || [[ -n $command_line ]]; do
  command_mapping_line_valid "$command_line" || \
    fail 'the fixture command map contains an invalid mapping'
done < "$rendered_commands"

! rg -n '(^|[^[:alnum:]_])(pass|secret-service)://' \
  home/dot_config/private_secret-exec --glob '!*.age' >/dev/null || \
  fail 'public secret-exec sources must not expose backend locators'

print -r -- 'secret injection binding checks passed'
