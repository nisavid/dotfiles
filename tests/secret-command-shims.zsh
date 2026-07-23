#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
launcher_source=$repo_root/home/private_dot_local/bin/executable_secret-exec
dispatcher_source=$repo_root/home/private_dot_local/lib/secret-exec/executable_secret-exec-command
mapping_source=$repo_root/home/dot_config/secret-exec/commands.env

fail() {
  print -u2 -r -- "$1"
  return 1
}

test_dir=$(mktemp -d "${TMPDIR:-/tmp}/secret-command-shims.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT

fixture_home=$test_dir/home
shim_dir=$fixture_home/.local/lib/secret-exec/bin
real_bin=$test_dir/real-bin
backend_bin=$test_dir/backend-bin
runtime_bin=$test_dir/runtime-bin
cwd_target=$test_dir/cwd-target
profile_dir=$fixture_home/.config/secret-exec/profiles
mkdir -p -- "$shim_dir" "$real_bin" "$backend_bin" "$runtime_bin" \
  "$cwd_target" "$profile_dir" \
  "$fixture_home/.local/bin"

cp "$launcher_source" "$fixture_home/.local/bin/secret-exec"
cp "$dispatcher_source" "$fixture_home/.local/lib/secret-exec/secret-exec-command"
cp "$mapping_source" "$fixture_home/.config/secret-exec/commands.env"
chmod +x "$fixture_home/.local/bin/secret-exec" \
  "$fixture_home/.local/lib/secret-exec/secret-exec-command"
ln -s ../secret-exec-command "$shim_dir/sz"

cp -R "$repo_root/home/dot_config/secret-exec/profiles/." "$profile_dir/"

cat > "$backend_bin/pass-cli" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

[[ $1 == item && $2 == view && $3 == --output && $4 == human && $# == 5 ]] || exit 64
case $5 in
  pass://cli-secrets/aws/username) print -r -- 'AKIACANARY123' ;;
  pass://cli-secrets/aws/password) print -r -- 'AwsSecretCanary123+/=' ;;
  *) exit 65 ;;
esac
EOF
chmod +x "$backend_bin/pass-cli"

cat > "$real_bin/sz" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

[[ ${AWS_ACCESS_KEY_ID:-} == AKIACANARY123 ]] || exit 70
[[ ${AWS_SECRET_ACCESS_KEY:-} == AwsSecretCanary123+/= ]] || exit 71
[[ -z ${AWS_SESSION_TOKEN:-} ]] || exit 72
[[ -z ${CONTEXT7_API_KEY:-} ]] || exit 73
[[ -z ${FIRECRAWL_API_KEY:-} ]] || exit 74
[[ -z ${GITHUB_PERSONAL_ACCESS_TOKEN:-} ]] || exit 75
[[ -z ${GREPTILE_API_KEY:-} ]] || exit 76
[[ $1 == 'argument with spaces' ]] || exit 77
print -r -- 'sz-ok'
EOF
chmod +x "$real_bin/sz"

cat > "$cwd_target/sz" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

[[ ${AWS_ACCESS_KEY_ID:-} == AKIACANARY123 ]] || exit 70
[[ ${AWS_SECRET_ACCESS_KEY:-} == AwsSecretCanary123+/= ]] || exit 71
print -r -- 'cwd-ok'
EOF
chmod +x "$cwd_target/sz"

cat > "$real_bin/exit-37" <<'EOF'
#!/usr/bin/env zsh
exit 37
EOF
chmod +x "$real_bin/exit-37"

cat > "$real_bin/exit-0" <<'EOF'
#!/usr/bin/env zsh
exit 0
EOF
chmod +x "$real_bin/exit-0"

zsh_path=${commands[zsh]}
ln -s "$zsh_path" "$runtime_bin/zsh"

export HOME=$fixture_home
export XDG_CONFIG_HOME=$fixture_home/.config
export PATH=$shim_dir:$real_bin:$backend_bin:/usr/bin:/bin
export AWS_ACCESS_KEY_ID=inherited-access
export AWS_SECRET_ACCESS_KEY=inherited-secret
export AWS_SESSION_TOKEN=inherited-session
export CONTEXT7_API_KEY=inherited-context7
export FIRECRAWL_API_KEY=inherited-firecrawl
export GITHUB_PERSONAL_ACCESS_TOKEN=inherited-github
export GREPTILE_API_KEY=inherited-greptile

output=$(sz 'argument with spaces')
[[ $output == sz-ok ]] || fail 'the sz shim must launch the real executable with the AWS profile'

original_directory=$PWD
cd "$cwd_target"
PATH=$shim_dir::$real_bin:$backend_bin:/usr/bin:/bin
output=$(sz)
PATH=$shim_dir:$real_bin:$backend_bin:/usr/bin:/bin
cd "$original_directory"
[[ $output == cwd-ok ]] || fail 'an empty PATH component must resolve the target from the current directory'

trace_output=$(zsh -x "$shim_dir/sz" 'argument with spaces' 2>&1)
[[ $trace_output != *AKIACANARY123* ]] || fail 'xtrace must not expose the AWS access-key canary'
[[ $trace_output != *AwsSecretCanary123* ]] || fail 'xtrace must not expose the AWS secret-key canary'

cp "$real_bin/exit-37" "$real_bin/sz"
set +e
sz
exit_code=$?
set -e
(( exit_code == 37 )) || fail 'the shim must preserve the real executable exit status'

cp "$real_bin/exit-0" "$real_bin/sz"
launcher=$fixture_home/.local/bin/secret-exec
mv "$launcher" "$test_dir/secret-exec"
mkdir "$launcher"
chmod +x "$launcher"
set +e
sz > /dev/null 2>&1
exit_code=$?
set -e
rmdir "$launcher"
mv "$test_dir/secret-exec" "$launcher"
(( exit_code == 1 )) || fail 'the dispatcher must reject an executable launcher directory'

print -r -- 'sz=unknown' > "$fixture_home/.config/secret-exec/commands.env"
set +e
sz > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code == 1 )) || fail 'an unknown profile mapping must fail closed'

print -r -- 'other=aws' > "$fixture_home/.config/secret-exec/commands.env"
set +e
sz > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code == 1 )) || fail 'a missing command mapping must fail closed'

print -r -- $'sz=aws\nsz=context7' > "$fixture_home/.config/secret-exec/commands.env"
set +e
sz > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code == 1 )) || fail 'a duplicate command mapping must fail closed'

print -r -- 'sz = aws' > "$fixture_home/.config/secret-exec/commands.env"
set +e
sz > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code == 1 )) || fail 'a malformed command mapping must fail closed'

print -r -- 'sz=aws' > "$fixture_home/.config/secret-exec/commands.env"
rm -- "$real_bin/sz"
full_fixture_path=$PATH
PATH=$shim_dir:$real_bin:$runtime_bin
set +e
sz > /dev/null 2>&1
exit_code=$?
set -e
PATH=$full_fixture_path
(( exit_code != 0 )) || fail 'a missing later executable must fail closed without recursion'

print -r -- 'secret command shim checks passed'
