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
  "$fixture_home/.config/secret-exec" "$fixture_home/.aws" "$fake_bin" "$state_dir"
cp -R "$repo_root/home/dot_config/secret-exec/profiles" "$fixture_home/.config/secret-exec/"

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
    reference=$3
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

export HOME=$fixture_home
export XDG_CONFIG_HOME=$fixture_home/.config
export PATH=$fake_bin:/opt/homebrew/bin:/usr/bin:/bin
export FAKE_PROTON_STATE=$state_dir

output=$(zsh "$migrator")
for canary in AKIACANARY AwsSecret github-canary context7-canary firecrawl-canary greptile-canary; do
  [[ $output != *$canary* ]] || fail 'migration output must never contain canary values'
done
[[ -e $fixture_home/.config/environment.d/10-apikeys.local.conf ]] || fail 'import must not retire plaintext without the explicit flag'
(( $(wc -l < "$state_dir/created.log") == 5 )) || fail 'migration must create the five Proton items'

output=$(zsh "$migrator")
(( $(wc -l < "$state_dir/created.log") == 5 )) || fail 'repeated migration must not create duplicate items'

cat > "$fixture_home/.config/mcp-config.json" <<'EOF'
{"mcpServers":{"firecrawl":{"type":"stdio","command":"/home/test/.local/bin/secret-exec"}}}
EOF
mv "$fixture_home/.config/environment.d/10-apikeys.local.conf" "$test_dir/environment-source"
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/partial-source.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must reject a partial legacy source set'
[[ -e $fixture_home/.config/zsh/zshrc.d/apikeys.local.zsh && -e $fixture_home/.aws/credentials ]] || \
  fail 'a partial-source rejection must preserve the remaining plaintext sources'
mv "$test_dir/environment-source" "$fixture_home/.config/environment.d/10-apikeys.local.conf"

mv "$fixture_home/.config/mcp-config.json" "$test_dir/mcp-config"
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/missing-mcp.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must require a readable generic MCP config'
[[ -e $fixture_home/.config/environment.d/10-apikeys.local.conf ]] || \
  fail 'a missing-MCP rejection must preserve every plaintext source'
mv "$test_dir/mcp-config" "$fixture_home/.config/mcp-config.json"

cat > "$fixture_home/.config/mcp-config.json" <<'EOF'
{"mcpServers":{"firecrawl":{"url":"https://mcp.firecrawl.dev/firecrawl-canary/v2/mcp"}}}
EOF
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/blocked.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must fail while the MCP config still contains the Firecrawl value'
[[ -e $fixture_home/.config/environment.d/10-apikeys.local.conf ]] || fail 'blocked retirement must preserve every plaintext source'

cat > "$fixture_home/.config/mcp-config.json" <<'EOF'
{"mcpServers":{"firecrawl":{"type":"stdio","command":"/home/test/.local/bin/secret-exec"}}}
EOF
output=$(zsh "$migrator" --retire-plaintext)
for retired_path in \
  "$fixture_home/.config/environment.d/10-apikeys.local.conf" \
  "$fixture_home/.config/zsh/zshrc.d/apikeys.local.zsh" \
  "$fixture_home/.aws/credentials"; do
  [[ ! -e $retired_path ]] || fail "retirement must remove ${retired_path:t}"
done
[[ -e $fixture_home/.config/mcp-config.json ]] || fail 'retirement must preserve the rewritten generic MCP config'

zsh "$migrator" --retire-plaintext > /dev/null

print -r -- 'secret migration checks passed'
