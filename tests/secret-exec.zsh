#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
launcher=$repo_root/home/private_dot_local/bin/executable_secret-exec

fail() {
  print -u2 -r -- "$1"
  return 1
}

assert_invalid_profiles() {
  local label=$1
  rm -f -- "$TARGET_MARKER"
  set +e
  zsh "$launcher" context7 -- mark-target > /dev/null 2>&1
  local exit_code=$?
  set -e
  (( exit_code != 0 )) || fail "$label must fail closed"
  [[ ! -e $TARGET_MARKER ]] || fail "$label must never run the target"
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

[[ $1 == item && $2 == view && $3 == --output && $4 == human && $# == 5 ]] || exit 64
print -r -- "$5" >> "$FAKE_PASS_LOG"
case $5 in
  pass://cli-secrets/context7/password) print -r -- 'context7-canary' ;;
  pass://cli-secrets/firecrawl/password) print -r -- 'firecrawl-canary' ;;
  pass://cli-secrets/github-mcp/password) print -r -- 'github-canary' ;;
  pass://cli-secrets/greptile/password) print -r -- 'greptile-canary' ;;
  pass://cli-secrets/aws/username) print -r -- "${FAKE_AWS_ACCESS_KEY_ID:-AKIACANARY123}" ;;
  pass://cli-secrets/aws/password) print -r -- "${FAKE_AWS_SECRET_ACCESS_KEY:-AwsSecretCanary123+/=}" ;;
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
[[ -z ${GITHUB_PERSONAL_ACCESS_TOKEN:-} ]] || exit 77
[[ -z ${GREPTILE_API_KEY:-} ]] || exit 78
[[ ${ORDINARY_SETTING:-} == preserved ]] || exit 73
[[ $1 == 'argument with spaces' ]] || exit 74
print -r -- 'target-ok'
EOF
chmod +x "$fake_bin/check-context"

cat > "$fake_bin/check-selected" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

case $1 in
  context7)
    [[ $CONTEXT7_API_KEY == context7-canary && -z ${FIRECRAWL_API_KEY:-} &&
      -z ${GITHUB_PERSONAL_ACCESS_TOKEN:-} && -z ${GREPTILE_API_KEY:-} &&
      -z ${AWS_ACCESS_KEY_ID:-} && -z ${AWS_SECRET_ACCESS_KEY:-} && -z ${AWS_SESSION_TOKEN:-} ]]
    ;;
  firecrawl)
    [[ $FIRECRAWL_API_KEY == firecrawl-canary && -z ${CONTEXT7_API_KEY:-} &&
      -z ${GITHUB_PERSONAL_ACCESS_TOKEN:-} && -z ${GREPTILE_API_KEY:-} &&
      -z ${AWS_ACCESS_KEY_ID:-} && -z ${AWS_SECRET_ACCESS_KEY:-} && -z ${AWS_SESSION_TOKEN:-} ]]
    ;;
  github)
    [[ $GITHUB_PERSONAL_ACCESS_TOKEN == github-canary && -z ${CONTEXT7_API_KEY:-} &&
      -z ${FIRECRAWL_API_KEY:-} && -z ${GREPTILE_API_KEY:-} &&
      -z ${AWS_ACCESS_KEY_ID:-} && -z ${AWS_SECRET_ACCESS_KEY:-} && -z ${AWS_SESSION_TOKEN:-} ]]
    ;;
  greptile)
    [[ $GREPTILE_API_KEY == greptile-canary && -z ${CONTEXT7_API_KEY:-} &&
      -z ${FIRECRAWL_API_KEY:-} && -z ${GITHUB_PERSONAL_ACCESS_TOKEN:-} &&
      -z ${AWS_ACCESS_KEY_ID:-} && -z ${AWS_SECRET_ACCESS_KEY:-} && -z ${AWS_SESSION_TOKEN:-} ]]
    ;;
  aws)
    [[ $AWS_ACCESS_KEY_ID == AKIACANARY123 && $AWS_SECRET_ACCESS_KEY == AwsSecretCanary123+/= &&
      -z ${AWS_SESSION_TOKEN:-} && -z ${CONTEXT7_API_KEY:-} && -z ${FIRECRAWL_API_KEY:-} &&
      -z ${GITHUB_PERSONAL_ACCESS_TOKEN:-} && -z ${GREPTILE_API_KEY:-} ]]
    ;;
  *) exit 79 ;;
esac
EOF
chmod +x "$fake_bin/check-selected"

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
export GITHUB_PERSONAL_ACCESS_TOKEN=inherited-github-canary
export GREPTILE_API_KEY=inherited-greptile-canary

output=$(zsh "$launcher" context7 -- check-context 'argument with spaces')
[[ $output == target-ok ]] || fail 'selected profile must reach the target with argv preserved'
[[ $(<"$FAKE_PASS_LOG") == pass://cli-secrets/context7/password ]] || \
  fail 'the launcher must retrieve only the selected profile'

for profile in context7 firecrawl github greptile aws; do
  zsh "$launcher" "$profile" -- check-selected "$profile"
done

set +e
zsh "$launcher" context7 -- exit-37
exit_code=$?
set -e
(( exit_code == 37 )) || fail 'the launcher must preserve the target exit status'

mv "$profile_dir/firecrawl.env" "$test_dir/firecrawl.env"
export TARGET_MARKER=$test_dir/target-ran
assert_invalid_profiles 'an incomplete canonical profile set'
mv "$test_dir/firecrawl.env" "$profile_dir/firecrawl.env"

mv "$profile_dir/context7.env" "$test_dir/context7.env"
ln -s "$test_dir/context7.env" "$profile_dir/context7.env"
assert_invalid_profiles 'a symlinked canonical profile'
rm -- "$profile_dir/context7.env"
mv "$test_dir/context7.env" "$profile_dir/context7.env"

cp "$profile_dir/context7.env" "$test_dir/context7.env"
print -r -- 'CONTEXT7_API_KEY=pass://cli-secrets/context7/password' >> \
  "$profile_dir/context7.env"
assert_invalid_profiles 'a duplicate profile mapping'
mv "$test_dir/context7.env" "$profile_dir/context7.env"

cp "$profile_dir/context7.env" "$test_dir/context7.env"
print -r -- 'CONTEXT7_API_KEY=pass://cli-secrets/context7/username' > \
  "$profile_dir/context7.env"
assert_invalid_profiles 'a noncanonical Proton reference'
mv "$test_dir/context7.env" "$profile_dir/context7.env"

trace_output=$(zsh -x "$launcher" context7 -- check-context 'argument with spaces' 2>&1)
[[ $trace_output != *context7-canary* ]] || fail 'xtrace must not expose a retrieved canary'

aws_json=$(zsh "$launcher" aws-credential-process aws)
[[ $aws_json == '{"Version":1,"AccessKeyId":"AKIACANARY123","SecretAccessKey":"AwsSecretCanary123+/="}' ]] || \
  fail 'AWS credential-process output must match the external AWS contract'

export FAKE_AWS_ACCESS_KEY_ID='AKIA"bad'
set +e
malformed_output=$(zsh "$launcher" aws-credential-process aws 2>/dev/null)
exit_code=$?
set -e
unset FAKE_AWS_ACCESS_KEY_ID
(( exit_code != 0 )) || fail 'quote-bearing AWS access keys must fail closed'
[[ -z $malformed_output ]] || fail 'invalid AWS access keys must not emit credential JSON'

export FAKE_AWS_SECRET_ACCESS_KEY='AwsSecret"bad'
set +e
malformed_output=$(zsh "$launcher" aws-credential-process aws 2>/dev/null)
exit_code=$?
set -e
unset FAKE_AWS_SECRET_ACCESS_KEY
(( exit_code != 0 )) || fail 'quote-bearing AWS secret keys must fail closed'
[[ -z $malformed_output ]] || fail 'invalid AWS secret keys must not emit credential JSON'

python3 - "$launcher" <<'PYEOF'
import os
import pty
import sys

pid, fd = pty.fork()
if pid == 0:
    os.execv("/bin/zsh", ["zsh", sys.argv[1], "aws-credential-process", "aws"])
output = bytearray()
while True:
    try:
        chunk = os.read(fd, 4096)
    except OSError:
        break
    if not chunk:
        break
    output.extend(chunk)
_, status = os.waitpid(pid, 0)
assert not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0
assert b"AKIACANARY123" not in output
assert b"AwsSecretCanary123+/=" not in output
PYEOF

cp "$profile_dir/firecrawl.env" "$test_dir/firecrawl.env.bak"
cat > "$profile_dir/firecrawl.env" <<'EOF'
NOT AN ASSIGNMENT
EOF
set +e
zsh "$launcher" context7 -- check-context 'argument with spaces' > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'malformed profile mappings must fail closed'
mv "$test_dir/firecrawl.env.bak" "$profile_dir/firecrawl.env"

print -r -- 'secret-exec behavior checks passed'
