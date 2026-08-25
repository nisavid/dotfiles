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
excluded_home=$test_dir/excluded-home
excluded_config=$excluded_home/.config
excluded_marker=$test_dir/excluded-pass-cli-ran
excluded_path=$test_dir/excluded-path
mkdir -p -- "$excluded_home/.local/bin" \
  "$excluded_config/secret-exec/profiles" "$excluded_path"
chmod 700 "$excluded_config/secret-exec/profiles"
cat >"$excluded_home/.local/bin/pass-cli" <<'EOF'
#!/usr/bin/env zsh
: > "$EXCLUDED_PASS_CLI_MARKER"
exit 90
EOF
chmod +x "$excluded_home/.local/bin/pass-cli"
set +e
excluded_output=$(EXCLUDED_PASS_CLI_MARKER=$excluded_marker \
  HOME=$excluded_home XDG_CONFIG_HOME=$excluded_config \
  PATH=$excluded_path /usr/bin/zsh "$migrator" 2>&1)
excluded_status=$?
set -e
(( excluded_status != 0 )) ||
  fail 'migration must require pass-cli on its runtime PATH'
[[ $excluded_output == 'secret-exec-migrate: pass-cli is required' ]] ||
  fail 'migration must not select a fixed pass-cli path outside runtime PATH'
[[ ! -e $excluded_marker ]] ||
  fail 'migration must not invoke pass-cli outside runtime PATH'

fixture_home=$test_dir/home
fake_bin=$test_dir/bin
state_dir=$test_dir/proton-state
mkdir -p -- "$fixture_home/.config/environment.d" "$fixture_home/.config/zsh/zshrc.d" \
  "$fixture_home/.config/secret-exec/profiles" "$fixture_home/.aws" "$fixture_home/.codex" \
  "$fixture_home/.claude" "$fixture_home/.local/bin" \
  "$fixture_home/.local/lib/secret-exec/bin" "$fake_bin" "$state_dir"
chmod 700 "$fixture_home/.config/secret-exec/profiles"
aws_access_field=AWS_ACCESS_KEY
aws_access_field+=_ID
aws_secret_field=AWS_SECRET_ACCESS
aws_secret_field+=_KEY
github_field=GITHUB_PERSONAL_ACCESS
github_field+=_TOKEN
context7_field=CONTEXT7
context7_field+=_API_KEY
firecrawl_field=FIRECRAWL
firecrawl_field+=_API_KEY
greptile_field=GREPTILE
greptile_field+=_API_KEY
aws_access_setting=aws_access_key
aws_access_setting+=_id
aws_secret_setting=aws_secret_access
aws_secret_setting+=_key
for profile_template in "$repo_root"/home/dot_config/private_secret-exec/private_profiles/*.tmpl(N); do
  profile_name=${${profile_template:t}#private_}
  profile_name=${profile_name%.tmpl}
  chezmoi -S "$repo_root/home" execute-template \
    --override-data-file "$repo_root/tests/fixtures/secret-exec-public.toml" \
    < "$profile_template" > "$fixture_home/.config/secret-exec/profiles/$profile_name"
  chmod 600 "$fixture_home/.config/secret-exec/profiles/$profile_name"
done
chezmoi -S "$repo_root/home" execute-template \
  --override-data-file "$repo_root/tests/fixtures/secret-exec-public.toml" \
  < "$repo_root/home/dot_config/private_secret-exec/private_commands.env.tmpl" \
  > "$fixture_home/.config/secret-exec/commands.env"
chmod 600 "$fixture_home/.config/secret-exec/commands.env"
cp "$repo_root/home/dot_config/environment.d/98-proton-pass.conf" \
  "$fixture_home/.config/environment.d/98-proton-pass.conf"
cp "$repo_root/home/dot_config/environment.d/99-secret-exec-shims.conf" \
  "$fixture_home/.config/environment.d/99-secret-exec-shims.conf"
cp "$repo_root/home/private_dot_local/lib/secret-exec/executable_secret-exec-command" \
  "$fixture_home/.local/lib/secret-exec/secret-exec-command"
chmod +x "$fixture_home/.local/lib/secret-exec/secret-exec-command"
while IFS='=' read -r command_name command_profile || [[ -n $command_name ]]; do
  [[ -z $command_name || $command_name == \#* ]] && continue
  ln -s ../secret-exec-command "$fixture_home/.local/lib/secret-exec/bin/$command_name"
done < "$fixture_home/.config/secret-exec/commands.env"

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

cat > "$fixture_home/.config/environment.d/10-apikeys.local.conf" <<EOF
$aws_access_field=AKIACANARY123
$aws_secret_field=AwsSecretCanary123+/=
$github_field=github-canary
$context7_field=context7-canary
$firecrawl_field=firecrawl-canary
$greptile_field=greptile-canary
EOF
cat > "$fixture_home/.config/zsh/zshrc.d/apikeys.local.zsh" <<EOF
export $github_field=github-canary
export $context7_field=context7-canary
export $firecrawl_field=firecrawl-canary
EOF
cat > "$fixture_home/.aws/credentials" <<EOF
# Shared credentials fixture
; duplicate verification tolerates unrelated profiles; retirement removes this legacy file
[unrelated]
$aws_access_setting = UNRELATEDCANARY
$aws_secret_setting = UnrelatedSecretCanary

[default]
$aws_access_setting = AKIACANARY123
$aws_secret_setting = AwsSecretCanary123+/=
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
      jq -n --arg vault "$(<"$state/vault")" '{vaults:[{name:$vault}]}'
    else
      print -r -- '{"vaults":[]}'
    fi
    ;;
  'vault create')
    [[ $3 == --name && -n $4 ]] || exit 64
    print -r -- "$4" > "$state/vault"
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
    tail=${reference#pass://*/}
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
shim_bin=$fixture_home/.local/lib/secret-exec/bin
export PATH=$shim_bin:$fake_bin:/opt/homebrew/bin:/usr/bin:/bin
export FAKE_PROTON_STATE=$state_dir

cp "$fixture_home/.config/environment.d/10-apikeys.local.conf" "$test_dir/environment-pattern"
cat > "$fixture_home/.config/environment.d/10-apikeys.local.conf" <<EOF
$aws_access_field=AKIACANARY123
$aws_secret_field=AwsSecretCanary123+/=
$github_field=github-*
$context7_field=context7-canary
$firecrawl_field=firecrawl-canary
$greptile_field=greptile-canary
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

profile_dir=$fixture_home/.config/secret-exec/profiles
chmod 755 "$profile_dir"
set +e
zsh "$migrator" > "$test_dir/profile-dir-mode.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'migration must reject a non-private profile directory'
[[ $(<"$test_dir/profile-dir-mode.out") == *'profile directory must have mode 0700'* ]] || \
  fail 'profile-directory mode rejection must identify the private-mode contract'
chmod 700 "$profile_dir"

profile_template_files=("$repo_root"/home/dot_config/private_secret-exec/private_profiles/*.tmpl(N))
first_profile_name=${profile_template_files[1]:t}
first_profile_name=${first_profile_name#private_}
first_profile_name=${first_profile_name%.tmpl}
first_profile=$profile_dir/$first_profile_name
chmod 644 "$first_profile"
set +e
zsh "$migrator" > "$test_dir/profile-mode.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'migration must reject a non-private profile file'
[[ $(<"$test_dir/profile-mode.out") == *'must have mode 0600'* ]] || \
  fail 'profile-file mode rejection must identify the private-mode contract'
chmod 600 "$first_profile"

command_map=$fixture_home/.config/secret-exec/commands.env
chmod 644 "$command_map"
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/command-map-mode.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must reject a non-private command map'
[[ $(<"$test_dir/command-map-mode.out") == *'command mapping must have mode 0600'* ]] || \
  fail 'command-map mode rejection must identify the private-mode contract'
[[ -e $fixture_home/.config/environment.d/10-apikeys.local.conf ]] || \
  fail 'a non-private command map must preserve every plaintext source'
chmod 600 "$command_map"

proton_environment=$fixture_home/.config/environment.d/98-proton-pass.conf
mv "$proton_environment" "$test_dir/98-proton-pass.conf"
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/missing-proton-environment.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must require persistent Proton Pass session configuration'
[[ $(<"$test_dir/missing-proton-environment.out") == \
  *'Proton Pass environment must be a readable regular file before retirement'* ]] || \
  fail 'retirement must reject missing persistent Proton Pass session configuration'
[[ -e $fixture_home/.config/environment.d/10-apikeys.local.conf ]] || \
  fail 'missing persistent Proton Pass session configuration must preserve every plaintext source'
mv "$test_dir/98-proton-pass.conf" "$proton_environment"

active_path=$PATH
PATH=$fake_bin:/opt/homebrew/bin:/usr/bin:/bin
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/inactive-shim-path.out" 2>&1
exit_code=$?
set -e
PATH=$active_path
(( exit_code != 0 )) || fail 'retirement must require the active shim PATH'
[[ $(<"$test_dir/inactive-shim-path.out") == \
  *'secret-exec shim directory must lead the active PATH before retirement'* ]] || \
  fail 'retirement must reject an inactive shim PATH before later validation'
[[ -e $fixture_home/.config/environment.d/10-apikeys.local.conf ]] || \
  fail 'an inactive shim PATH must preserve every plaintext source'

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

first_command=$(sed -n '/^[^#]/ { s/=.*//; p; q; }' \
  "$fixture_home/.config/secret-exec/commands.env")
first_shim=$fixture_home/.local/lib/secret-exec/bin/$first_command
mv "$first_shim" "$test_dir/command-shim"
set +e
zsh "$migrator" --retire-plaintext > "$test_dir/missing-command-shim.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'retirement must require every mapped command shim'
[[ $(<"$test_dir/missing-command-shim.out") == \
  *'secret-exec shim directory does not match the command mapping'* ]] || \
  fail 'retirement must reject a missing command shim before later validation'
[[ -e $fixture_home/.config/environment.d/10-apikeys.local.conf ]] || \
  fail 'a missing command shim must preserve every plaintext source'
mv "$test_dir/command-shim" "$first_shim"

context_reference=$(sed -n 's/^CONTEXT7_API_KEY=//p' \
  "$fixture_home/.config/secret-exec/profiles/"*.env)
context_tail=${context_reference#pass://*/}
context_item=${context_tail%%/*}
context_field=${context_tail##*/}
context_state=$state_dir/$context_item.$context_field
print -r -- 'different-existing-value' > "$context_state"
set +e
zsh "$migrator" > "$test_dir/proton-drift.out" 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'migration must stop when an existing Proton item differs'
[[ $(<"$context_state") == different-existing-value ]] || \
  fail 'migration must not overwrite an existing Proton item that differs'
[[ $(<"$test_dir/proton-drift.out") != *context7-canary* ]] || \
  fail 'Proton drift diagnostics must not expose credential values'
print -r -- 'context7-canary' > "$context_state"

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

cat > "$fixture_home/.config/environment.d/70-keys.conf" <<EOF
HF_HOME=/tmp/models
$firecrawl_field=unexpected-ambient-canary
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
stale_firecrawl_value='stale-firecrawl-'
stale_firecrawl_value+='canary'
print -r -- "{\"apiKey\":\"$stale_firecrawl_value\"}" > \
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
cat > "$fixture_home/.config/opencode/opencode.json" <<EOF
{"mcp":{"context7":{"type":"remote","url":"https://mcp.context7.com/mcp","headers":{"$context7_field":"literal-context7-canary"}}}}
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
