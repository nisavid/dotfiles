#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
launcher=$repo_root/home/private_dot_local/bin/executable_secret-exec

fail() {
  print -u2 -r -- "$1"
  return 1
}

test_dir=$(mktemp -d "${TMPDIR:-/tmp}/secret-exec.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT

fixture_home=$test_dir/home
profile_dir=$fixture_home/.config/secret-exec/profiles
fake_bin=$test_dir/bin
mkdir -p -- "$profile_dir" "$fake_bin"

cat > "$profile_dir/context7.env" <<'EOF'
CONTEXT7_API_KEY=pass://cli-secrets/context7/password
EOF
cat > "$profile_dir/firecrawl.env" <<'EOF'
FIRECRAWL_API_KEY=pass://cli-secrets/firecrawl/password
EOF
cat > "$profile_dir/github.env" <<'EOF'
GITHUB_PERSONAL_ACCESS_TOKEN=pass://cli-secrets/github-mcp/password
EOF
cat > "$profile_dir/greptile.env" <<'EOF'
GREPTILE_API_KEY=pass://cli-secrets/greptile/password
EOF
cat > "$profile_dir/aws.env" <<'EOF'
AWS_ACCESS_KEY_ID=pass://cli-secrets/aws/username
AWS_SECRET_ACCESS_KEY=pass://cli-secrets/aws/password
EOF

cat > "$fake_bin/pass-cli" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

[[ $1 == item && $2 == view && $# == 3 ]] || exit 64
print -r -- "$3" >> "$FAKE_PASS_LOG"
case $3 in
  pass://cli-secrets/context7/password) print -r -- 'context7-canary' ;;
  pass://cli-secrets/firecrawl/password) print -r -- 'firecrawl-canary' ;;
  pass://cli-secrets/aws/username) print -r -- 'AKIACANARY123' ;;
  pass://cli-secrets/aws/password) print -r -- 'AwsSecretCanary123+/=' ;;
  *) exit 65 ;;
esac
EOF
chmod +x "$fake_bin/pass-cli"

cat > "$fake_bin/check-context" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

[[ ${CONTEXT7_API_KEY:-} == context7-canary ]] || exit 70
[[ -z ${FIRECRAWL_API_KEY:-} ]] || exit 71
[[ -z ${AWS_ACCESS_KEY_ID:-} ]] || exit 72
[[ -z ${AWS_SECRET_ACCESS_KEY:-} ]] || exit 75
[[ -z ${AWS_SESSION_TOKEN:-} ]] || exit 76
[[ ${ORDINARY_SETTING:-} == preserved ]] || exit 73
[[ $1 == 'argument with spaces' ]] || exit 74
print -r -- 'target-ok'
EOF
chmod +x "$fake_bin/check-context"

cat > "$fake_bin/exit-37" <<'EOF'
#!/usr/bin/env zsh
exit 37
EOF
chmod +x "$fake_bin/exit-37"

cat > "$fake_bin/mark-target" <<'EOF'
#!/usr/bin/env zsh
: > "$TARGET_MARKER"
EOF
chmod +x "$fake_bin/mark-target"

export HOME=$fixture_home
export XDG_CONFIG_HOME=$fixture_home/.config
export PATH=$fake_bin:/usr/bin:/bin
export FAKE_PASS_LOG=$test_dir/pass-requests.log
export ORDINARY_SETTING=preserved
export CONTEXT7_API_KEY=inherited-context7-canary
export FIRECRAWL_API_KEY=inherited-firecrawl-canary
export AWS_ACCESS_KEY_ID=INHERITEDACCESS
export AWS_SECRET_ACCESS_KEY=InheritedSecret
export AWS_SESSION_TOKEN=InheritedSession

output=$(zsh "$launcher" context7 -- check-context 'argument with spaces')
[[ $output == target-ok ]] || fail 'selected profile must reach the target with argv preserved'
[[ $(<"$FAKE_PASS_LOG") == pass://cli-secrets/context7/password ]] || \
  fail 'the launcher must retrieve only the selected profile'

set +e
zsh "$launcher" context7 -- exit-37
exit_code=$?
set -e
(( exit_code == 37 )) || fail 'the launcher must preserve the target exit status'

mv "$profile_dir/firecrawl.env" "$test_dir/firecrawl.env"
export TARGET_MARKER=$test_dir/target-ran
set +e
zsh "$launcher" context7 -- mark-target > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'the launcher must reject an incomplete canonical profile set'
[[ ! -e $TARGET_MARKER ]] || fail 'an invalid profile set must never run the target'
mv "$test_dir/firecrawl.env" "$profile_dir/firecrawl.env"

trace_output=$(zsh -x "$launcher" context7 -- check-context 'argument with spaces' 2>&1)
[[ $trace_output != *context7-canary* ]] || fail 'xtrace must not expose a retrieved canary'

aws_json=$(zsh "$launcher" aws-credential-process aws)
[[ $aws_json == '{"Version":1,"AccessKeyId":"AKIACANARY123","SecretAccessKey":"AwsSecretCanary123+/="}' ]] || \
  fail 'AWS credential-process output must match the external AWS contract'

cat > "$profile_dir/malformed.env" <<'EOF'
NOT AN ASSIGNMENT
EOF
set +e
zsh "$launcher" context7 -- check-context 'argument with spaces' > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'malformed profile mappings must fail closed'

print -r -- 'secret-exec behavior checks passed'
