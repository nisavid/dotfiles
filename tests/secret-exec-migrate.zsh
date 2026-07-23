#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
migrator=$repo_root/home/private_dot_local/bin/executable_secret-exec-migrate

fail() {
  print -u2 -r -- "$1"
  return 1
}

test_dir=$(mktemp -d "${TMPDIR:-/tmp}/secret-exec-migrate.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT
fixture_home=$test_dir/home
fake_bin=$test_dir/bin
state_dir=$test_dir/proton-state
mkdir -p -- "$fixture_home/.config/environment.d" "$fixture_home/.config/zsh/zshrc.d" \
  "$fixture_home/.config/secret-exec" "$fixture_home/.aws" "$fixture_home/.codex" \
  "$fixture_home/.claude" "$fixture_home/.local/bin" \
  "$fixture_home/.local/lib/secret-exec/bin" "$fake_bin" "$state_dir"
cp -R "$repo_root/home/dot_config/secret-exec/profiles" "$fixture_home/.config/secret-exec/"
cp "$repo_root/home/dot_config/secret-exec/commands.env" \
  "$fixture_home/.config/secret-exec/commands.env"
cp "$repo_root/home/dot_config/environment.d/99-secret-exec-shims.conf" \
  "$fixture_home/.config/environment.d/99-secret-exec-shims.conf"
cp "$repo_root/home/private_dot_local/lib/secret-exec/executable_secret-exec-command" \
  "$fixture_home/.local/lib/secret-exec/secret-exec-command"
chmod +x "$fixture_home/.local/lib/secret-exec/secret-exec-command"
ln -s ../secret-exec-command "$fixture_home/.local/lib/secret-exec/bin/sz"

cat > "$fixture_home/.config/zsh/zshenv.zsh" <<'EOF'
# secret-exec-environment-loader-v1
EOF
ln -s .config/zsh/zshenv.zsh "$fixture_home/.zshenv"
: > "$fixture_home/.local/bin/secret-exec"
chmod +x "$fixture_home/.local/bin/secret-exec"
cat > "$fixture_home/.codex/config.toml" <<'EOF'
[mcp_servers.context7]
command = "managed-by-fake-codex"
EOF
cat > "$fixture_home/.claude.json" <<EOF
{"mcpServers":{"context7":{"command":"$fixture_home/.local/bin/secret-exec","args":["context7","--","npx","-y","@upstash/context7-mcp@3.2.4"]},"firecrawl":{"command":"$fixture_home/.local/bin/secret-exec","args":["firecrawl","--","npx","-y","firecrawl-mcp@3.22.3"]},"github":{"command":"$fixture_home/.local/bin/secret-exec","args":["github","--","npx","-y","mcp-remote@0.1.38","https://api.githubcopilot.com/mcp/","--header","Authorization:Bearer \${GITHUB_PERSONAL_ACCESS_TOKEN}"]},"greptile":{"command":"$fixture_home/.local/bin/secret-exec","args":["greptile","--","npx","-y","mcp-remote@0.1.38","https://api.greptile.com/mcp","--header","Authorization:Bearer \${GREPTILE_API_KEY}"]}}}
EOF
cat > "$fixture_home/.claude/settings.json" <<'EOF'
{"enabledPlugins":{"context7@claude-plugins-official":false,"github@claude-plugins-official":false,"greptile@claude-plugins-official":false}}
EOF
cat > "$fixture_home/.aws/config" <<EOF
[default]
credential_process = $fixture_home/.local/bin/secret-exec aws-credential-process aws
EOF

cat > "$fixture_home/.config/environment.d/10-apikeys.local.conf" <<'EOF'
AWS_ACCESS_KEY_ID=AKIACANARY123
AWS_SECRET_ACCESS_KEY=AwsSecretCanary123+/=
GITHUB_PERSONAL_ACCESS_TOKEN=github-canary
CONTEXT7_API_KEY=context7-canary
FIRECRAWL_API_KEY=firecrawl-canary
GREPTILE_API_KEY=greptile-canary
EOF
cat > "$fixture_home/.config/zsh/zshrc.d/apikeys.local.zsh" <<'EOF'
export GITHUB_PERSONAL_ACCESS_TOKEN=github-canary
export CONTEXT7_API_KEY=context7-canary
export FIRECRAWL_API_KEY=firecrawl-canary
EOF
cat > "$fixture_home/.aws/credentials" <<'EOF'
# Shared credentials fixture
; duplicate verification tolerates unrelated profiles; retirement removes this legacy file
[unrelated]
aws_access_key_id = UNRELATEDCANARY
aws_secret_access_key = UnrelatedSecretCanary

[default]
aws_access_key_id = AKIACANARY123
aws_secret_access_key = AwsSecretCanary123+/=
EOF
cat > "$fixture_home/.config/mcp-config.json" <<'EOF'
{"mcpServers":{"firecrawl":{"url":"https://mcp.firecrawl.dev/firecrawl-canary/v2/mcp"}}}
EOF

cat > "$fake_bin/pass-cli" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

state=$FAKE_PROTON_STATE
case "$1 $2" in
  'vault list')
    if [[ -e $state/vault ]]; then
      print -r -- '{"vaults":[{"name":"cli-secrets"}]}'
    else
      print -r -- '{"vaults":[]}'
    fi
    ;;
  'vault create')
    : > "$state/vault"
    ;;
  'item list')
    print -rn -- '{"items":['
    typeset first=1 file title
    for file in "$state"/*.password(N); do
      title=${file:t:r}
      (( first )) || print -rn -- ','
      printf '{"title":"%s"}' "$title"
      first=0
    done
    print -r -- ']}'
    ;;
  'item view')
    [[ $3 == --output && $4 == human && $# == 5 ]] || exit 64
    reference=$5
    tail=${reference#pass://cli-secrets/}
    title=${tail%%/*}
    field=${tail##*/}
    [[ -r $state/$title.$field ]] || exit 1
    cat "$state/$title.$field"
    ;;
  'item create')
    [[ $3 == login ]] || exit 64
    payload=$(cat)
    title=$(print -r -- "$payload" | jq -r .title)
    username=$(print -r -- "$payload" | jq -r '.username // empty')
    password=$(print -r -- "$payload" | jq -r '.password // empty')
    [[ -n $username ]] && print -r -- "$username" > "$state/$title.username"
    print -r -- "$password" > "$state/$title.password"
    print -r -- "$title" >> "$state/created.log"
    ;;
  *) exit 64 ;;
esac
EOF
chmod +x "$fake_bin/pass-cli"

cat > "$fake_bin/rm" <<'EOF'
#!/usr/bin/env zsh
[[ -z ${FAKE_RM_FAIL:-} ]] || exit 1
exec /bin/rm "$@"
EOF
chmod +x "$fake_bin/rm"

cat > "$fake_bin/codex" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail
[[ $* == 'mcp list --json' ]] || exit 64
command=$HOME/.local/bin/secret-exec
jq -n --arg command "$command" '[
  {name:"context7",transport:{type:"stdio",command:$command,args:["context7","--","npx","-y","@upstash/context7-mcp@3.2.4"],env:{},env_vars:[],cwd:null}},
  {name:"firecrawl",transport:{type:"stdio",command:$command,args:["firecrawl","--","npx","-y","firecrawl-mcp@3.22.3"],env:{},env_vars:[],cwd:null}},
  {name:"github",transport:{type:"stdio",command:$command,args:["github","--","npx","-y","mcp-remote@0.1.38","https://api.githubcopilot.com/mcp/","--header","Authorization:Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}"],env:{},env_vars:[],cwd:null}}
]'
EOF
chmod +x "$fake_bin/codex"

export HOME=$fixture_home
export XDG_CONFIG_HOME=$fixture_home/.config
export PATH=$fake_bin:/opt/homebrew/bin:/usr/bin:/bin
export FAKE_PROTON_STATE=$state_dir

cp "$fixture_home/.config/environment.d/10-apikeys.local.conf" "$test_dir/environment-pattern"
cat > "$fixture_home/.config/environment.d/10-apikeys.local.conf" <<'EOF'
AWS_ACCESS_KEY_ID=AKIACANARY123
AWS_SECRET_ACCESS_KEY=AwsSecretCanary123+/=
GITHUB_PERSONAL_ACCESS_TOKEN=github-*
CONTEXT7_API_KEY=context7-canary
FIRECRAWL_API_KEY=firecrawl-canary
GREPTILE_API_KEY=greptile-canary
EOF
set +e
zsh "$migrator" > "$test_dir/pattern-mismatch.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'duplicate verification must compare secret values literally'
mv "$test_dir/environment-pattern" "$fixture_home/.config/environment.d/10-apikeys.local.conf"

output=$(zsh "$migrator" 2>&1)
for canary in AKIACANARY AwsSecret github-canary context7-canary firecrawl-canary greptile-canary; do
  [[ $output != *$canary* ]] || fail 'migration output must never contain canary values'
done
[[ -e $fixture_home/.config/environment.d/10-apikeys.local.conf ]] || fail 'import must not retire plaintext without the explicit flag'
(( $(wc -l < "$state_dir/created.log") == 5 )) || fail 'migration must create the five Proton items'

output=$(zsh "$migrator" 2>&1)
(( $(wc -l < "$state_dir/created.log") == 5 )) || fail 'repeated migration must not create duplicate items'

shim_environment=$fixture_home/.config/environment.d/99-secret-exec-shims.conf
mv "$shim_environment" "$test_dir/99-secret-exec-shims.conf"
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/missing-shim-environment.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must require the shim PATH configuration'
[[ $(<"$test_dir/missing-shim-environment.out") == \
  *'secret-exec shim environment must be a readable regular file before retirement'* ]] || \
  fail 'retirement must reject a missing shim PATH configuration before later validation'
[[ -e $fixture_home/.config/environment.d/10-apikeys.local.conf ]] || \
  fail 'a missing shim PATH configuration must preserve every plaintext source'
mv "$test_dir/99-secret-exec-shims.conf" "$shim_environment"

print -r -- 'PATH=$PATH:$HOME/.local/lib/secret-exec/bin' > "$shim_environment"
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/stale-shim-environment.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must reject a stale shim PATH configuration'
[[ $(<"$test_dir/stale-shim-environment.out") == \
  *'secret-exec shim environment does not match the canonical contract'* ]] || \
  fail 'retirement must reject a stale shim PATH configuration before later validation'
[[ -e $fixture_home/.config/environment.d/10-apikeys.local.conf ]] || \
  fail 'a stale shim PATH configuration must preserve every plaintext source'
cp "$repo_root/home/dot_config/environment.d/99-secret-exec-shims.conf" "$shim_environment"

dispatcher=$fixture_home/.local/lib/secret-exec/secret-exec-command
mv "$dispatcher" "$test_dir/secret-exec-command"
mkdir "$dispatcher"
chmod +x "$dispatcher"
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/directory-dispatcher.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must reject a dispatcher directory'
[[ $(<"$test_dir/directory-dispatcher.out") == \
  *'secret-exec command dispatcher must be an executable regular file before retirement'* ]] || \
  fail 'retirement must reject a dispatcher directory before later validation'
rmdir "$dispatcher"
mv "$test_dir/secret-exec-command" "$dispatcher"

chmod 111 "$dispatcher"
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/unreadable-dispatcher.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must reject an unreadable dispatcher'
[[ $(<"$test_dir/unreadable-dispatcher.out") == \
  *'secret-exec command dispatcher must be an executable regular file before retirement'* ]] || \
  fail 'retirement must reject an unreadable dispatcher before later validation'
chmod 755 "$dispatcher"

print -r -- 'different-existing-value' > "$state_dir/context7.password"
set +e
zsh "$migrator" > "$test_dir/proton-drift.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'migration must stop when an existing Proton item differs'
[[ $(<"$state_dir/context7.password") == different-existing-value ]] || \
  fail 'migration must not overwrite an existing Proton item that differs'
[[ $(<"$test_dir/proton-drift.out") != *context7-canary* ]] || \
  fail 'Proton drift diagnostics must not expose credential values'
print -r -- 'context7-canary' > "$state_dir/context7.password"

cat > "$fixture_home/.config/mcp-config.json" <<EOF
{"mcpServers":{"firecrawl":{"type":"stdio","command":"$fixture_home/.local/bin/secret-exec","args":["firecrawl","--","npx","-y","firecrawl-mcp@3.22.3"]}}}
EOF
mv "$fixture_home/.config/environment.d/10-apikeys.local.conf" "$test_dir/environment-source"
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/partial-source.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must reject a partial legacy source set'
for canary in AKIACANARY AwsSecret github-canary context7-canary firecrawl-canary greptile-canary; do
  [[ $(<"$test_dir/partial-source.out") != *$canary* ]] || fail 'partial-source diagnostics must not contain canary values'
done
[[ -e $fixture_home/.config/zsh/zshrc.d/apikeys.local.zsh && -e $fixture_home/.aws/credentials ]] || \
  fail 'a partial-source rejection must preserve the remaining plaintext sources'
mv "$test_dir/environment-source" "$fixture_home/.config/environment.d/10-apikeys.local.conf"

mv "$fixture_home/.config/mcp-config.json" "$test_dir/mcp-config"
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/missing-mcp.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must require a readable generic MCP config'
for canary in AKIACANARY AwsSecret github-canary context7-canary firecrawl-canary greptile-canary; do
  [[ $(<"$test_dir/missing-mcp.out") != *$canary* ]] || fail 'missing-MCP diagnostics must not contain canary values'
done
[[ -e $fixture_home/.config/environment.d/10-apikeys.local.conf ]] || \
  fail 'a missing-MCP rejection must preserve every plaintext source'
mv "$test_dir/mcp-config" "$fixture_home/.config/mcp-config.json"

cp "$fixture_home/.claude.json" "$test_dir/claude.json"
cat > "$fixture_home/.claude.json" <<'EOF'
{"mcpServers":{"firecrawl":{"url":"https://mcp.firecrawl.dev/firecrawl-canary/v2/mcp"}}}
EOF
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/legacy-claude.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must reject a credential-bearing Claude MCP URL'
for canary in AKIACANARY AwsSecret github-canary context7-canary firecrawl-canary greptile-canary; do
  [[ $(<"$test_dir/legacy-claude.out") != *$canary* ]] || fail 'legacy-Claude diagnostics must not contain canary values'
done
[[ -e $fixture_home/.config/environment.d/10-apikeys.local.conf ]] || \
  fail 'a legacy-Claude rejection must preserve every plaintext source'
mv "$test_dir/claude.json" "$fixture_home/.claude.json"

cp "$fake_bin/codex" "$test_dir/codex"
cat > "$fake_bin/codex" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail
[[ $* == 'mcp list --json' ]] || exit 64
jq -n '[{name:"context7",transport:{type:"stdio",command:"mismatched-command",args:[],env:{},env_vars:[],cwd:null}}]'
EOF
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/legacy-codex.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must reject mismatched effective Codex MCP bindings'
[[ -e $fixture_home/.config/environment.d/10-apikeys.local.conf ]] || \
  fail 'a Codex binding rejection must preserve every plaintext source'
mv "$test_dir/codex" "$fake_bin/codex"

cat > "$fixture_home/.config/mcp-config.json" <<'EOF'
{"mcpServers":{"firecrawl":{"url":"https://mcp.firecrawl.dev/firecrawl-canary/v2/mcp"}}}
EOF
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/blocked.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must fail while the MCP config still contains the Firecrawl value'
for canary in AKIACANARY AwsSecret github-canary context7-canary firecrawl-canary greptile-canary; do
  [[ $(<"$test_dir/blocked.out") != *$canary* ]] || fail 'blocked-retirement diagnostics must not contain canary values'
done
[[ -e $fixture_home/.config/environment.d/10-apikeys.local.conf ]] || fail 'blocked retirement must preserve every plaintext source'

cat > "$fixture_home/.config/mcp-config.json" <<EOF
{"mcpServers":{"firecrawl":{"type":"stdio","command":"$fixture_home/.local/bin/secret-exec","args":["firecrawl","--","npx","-y","firecrawl-mcp@3.22.3"]}}}
EOF

cat > "$fixture_home/.config/environment.d/70-keys.conf" <<'EOF'
HF_HOME=/tmp/models
FIRECRAWL_API_KEY=unexpected-ambient-canary
EOF
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/unexpected-ambient.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must reject unexpected ambient credential sources'
[[ $(<"$test_dir/unexpected-ambient.out") != *unexpected-ambient-canary* ]] || \
  fail 'unexpected ambient diagnostics must not contain credential values'
[[ -e $fixture_home/.config/environment.d/10-apikeys.local.conf ]] || \
  fail 'unexpected ambient sources must block retirement before deletion'
rm -- "$fixture_home/.config/environment.d/70-keys.conf"

mkdir -p -- "$fixture_home/.config/firecrawl-cli"
print -r -- '{"apiKey":"stale-firecrawl-canary"}' > \
  "$fixture_home/.config/firecrawl-cli/credentials.json"
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/stale-firecrawl.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must reject stale Firecrawl CLI credentials'
[[ $(<"$test_dir/stale-firecrawl.out") != *stale-firecrawl-canary* ]] || \
  fail 'stale Firecrawl diagnostics must not contain credential values'
[[ -e $fixture_home/.config/firecrawl-cli/credentials.json ]] || \
  fail 'stale Firecrawl rejection must preserve the detected plaintext source'
rm -- "$fixture_home/.config/firecrawl-cli/credentials.json"

mkdir -p -- "$fixture_home/.config/opencode"
cat > "$fixture_home/.config/opencode/opencode.json" <<'EOF'
{"mcp":{"context7":{"type":"remote","url":"https://mcp.context7.com/mcp","headers":{"CONTEXT7_API_KEY":"literal-context7-canary"}}}}
EOF
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/legacy-opencode.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must reject a literal OpenCode Context7 binding'
[[ $(<"$test_dir/legacy-opencode.out") != *literal-context7-canary* ]] || \
  fail 'legacy OpenCode diagnostics must not contain credential values'
[[ -e $fixture_home/.config/opencode/opencode.json ]] || \
  fail 'legacy OpenCode rejection must preserve the detected plaintext source'
cat > "$fixture_home/.config/opencode/opencode.json" <<EOF
{"mcp":{"context7":{"type":"local","command":["$fixture_home/.local/bin/secret-exec","context7","--","npx","-y","@upstash/context7-mcp@3.2.4"],"enabled":true}}}
EOF

export FAKE_RM_FAIL=1
set +e
failed_cleanup_output=$(zsh "$migrator" --retire-plaintext 2>&1)
exit_code=$?
set -e
unset FAKE_RM_FAIL
(( exit_code != 0 )) || fail 'retirement must fail when plaintext cleanup fails'
[[ $failed_cleanup_output != *'retired plaintext credential files'* ]] || \
  fail 'failed cleanup must not report plaintext retirement success'
for retained_path in \
  "$fixture_home/.config/environment.d/10-apikeys.local.conf" \
  "$fixture_home/.config/zsh/zshrc.d/apikeys.local.zsh" \
  "$fixture_home/.aws/credentials"; do
  [[ -e $retained_path ]] || fail "failed cleanup must preserve ${retained_path:t}"
done

output=$(zsh "$migrator" --retire-plaintext 2>&1)
for retired_path in \
  "$fixture_home/.config/environment.d/10-apikeys.local.conf" \
  "$fixture_home/.config/zsh/zshrc.d/apikeys.local.zsh" \
  "$fixture_home/.aws/credentials"; do
  [[ ! -e $retired_path ]] || fail "retirement must remove ${retired_path:t}"
done
[[ -e $fixture_home/.config/mcp-config.json ]] || fail 'retirement must preserve the rewritten generic MCP config'

zsh "$migrator" --retire-plaintext > /dev/null

print -r -- 'secret migration checks passed'
