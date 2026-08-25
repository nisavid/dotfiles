#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
launcher_source=$repo_root/home/private_dot_local/bin/executable_secret-exec
readiness_source=$repo_root/home/private_dot_local/bin/executable_proton-pass-ensure-ready
dispatcher_source=$repo_root/home/private_dot_local/lib/secret-exec/executable_secret-exec-command

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
config_dir=$fixture_home/.config/secret-exec
mkdir -p -- "$shim_dir" "$real_bin" "$backend_bin" "$runtime_bin" \
  "$cwd_target" "$profile_dir" "$fixture_home/.local/bin"
chmod 700 "$config_dir" "$profile_dir"

cp "$launcher_source" "$fixture_home/.local/bin/secret-exec"
cp "$readiness_source" "$fixture_home/.local/bin/proton-pass-ensure-ready"
cp "$dispatcher_source" "$fixture_home/.local/lib/secret-exec/secret-exec-command"
chmod +x "$fixture_home/.local/bin/secret-exec" \
  "$fixture_home/.local/bin/proton-pass-ensure-ready" \
  "$fixture_home/.local/lib/secret-exec/secret-exec-command"
ln -s ../secret-exec-command "$shim_dir/tool-a"
ln -s ../secret-exec-command "$shim_dir/tool-b"

cat > "$config_dir/commands.env" <<'EOF'
tool-a=member
tool-b=member
EOF
cat > "$profile_dir/member.env" <<'EOF'
MEMBER_TOKEN=pass://fixture-store/member/token
!UNRELATED_SECRET
EOF
chmod 600 "$config_dir/commands.env" "$profile_dir/member.env"

cat > "$fixture_home/.local/bin/pass-cli" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

print -r -- "$1" >> "$FAKE_PASS_LOG"
case $1 in
  info)
    (( $# == 1 )) || exit 64
    [[ ${PROTON_PASS_NO_UPDATE_CHECK:-} == 1 ]] || exit 65
    ;;
  item)
    [[ $2 == view && $3 == --output && $4 == human && $# == 5 ]] || exit 66
    [[ $5 == pass://fixture-store/member/token ]] || exit 67
    [[ ${PROTON_PASS_AGENT_REASON:-} == 'secret-exec credential resolution' ]] || exit 68
    [[ ${PROTON_PASS_NO_UPDATE_CHECK:-} == 1 ]] || exit 69
    case $(/usr/bin/uname -s) in
      Linux) [[ ${PROTON_PASS_LINUX_KEYRING:-} == dbus ]] || exit 71 ;;
      Darwin) [[ -z ${PROTON_PASS_LINUX_KEYRING:-} ]] || exit 71 ;;
    esac
    print -r -- 'member-canary'
    ;;
  *)
    exit 72
    ;;
esac
EOF
chmod +x "$fixture_home/.local/bin/pass-cli"

for command_name in tool-a tool-b; do
  cat > "$real_bin/$command_name" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

[[ ${MEMBER_TOKEN:-} == member-canary ]] || exit 70
[[ -z ${UNRELATED_SECRET:-} ]] || exit 71
[[ $1 == 'argument with spaces' ]] || exit 72
print -r -- "${0:t}-ok"
EOF
  chmod +x "$real_bin/$command_name"
done

cat > "$cwd_target/tool-a" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

[[ ${MEMBER_TOKEN:-} == member-canary ]] || exit 70
print -r -- 'cwd-ok'
EOF
chmod +x "$cwd_target/tool-a"

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
export XDG_STATE_HOME=$test_dir/state
export PATH=$shim_dir:$real_bin:$backend_bin:$fixture_home/.local/bin:/usr/bin:/bin
export FAKE_PASS_LOG=$test_dir/pass.log
export MEMBER_TOKEN=inherited-member
export UNRELATED_SECRET=inherited-unrelated

output=$(tool-a 'argument with spaces')
[[ $output == tool-a-ok ]] || fail 'the first shim must launch the real executable'
[[ $(<"$FAKE_PASS_LOG") == $'info\nitem' ]] ||
  fail 'a pass-backed shim must validate readiness before resolving its value'

output=$(tool-b 'argument with spaces')
[[ $output == tool-b-ok ]] || fail 'the second shim must launch the real executable'

original_directory=$PWD
cd "$cwd_target"
PATH=$shim_dir::$real_bin:$backend_bin:$fixture_home/.local/bin:/usr/bin:/bin
output=$(tool-a 'argument with spaces')
PATH=$shim_dir:$real_bin:$backend_bin:$fixture_home/.local/bin:/usr/bin:/bin
cd "$original_directory"
[[ $output == cwd-ok ]] || fail 'an empty PATH component must resolve the current directory'

trace_output=$(zsh -x "$shim_dir/tool-a" 'argument with spaces' 2>&1)
[[ $trace_output != *member-canary* ]] || fail 'xtrace must not expose a retrieved value'

cp "$real_bin/exit-37" "$real_bin/tool-a"
set +e
tool-a
exit_code=$?
set -e
(( exit_code == 37 )) || fail 'the shim must preserve the real executable exit status'

cp "$real_bin/exit-0" "$real_bin/tool-a"
launcher=$fixture_home/.local/bin/secret-exec
mv "$launcher" "$test_dir/secret-exec"
mkdir "$launcher"
chmod +x "$launcher"
set +e
tool-a > /dev/null 2>&1
exit_code=$?
set -e
rmdir "$launcher"
mv "$test_dir/secret-exec" "$launcher"
(( exit_code == 1 )) || fail 'the dispatcher must reject an executable launcher directory'

print -r -- 'tool-a=unknown' > "$config_dir/commands.env"
set +e
tool-a > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code == 1 )) || fail 'an unknown profile mapping must fail closed'

print -r -- 'other=member' > "$config_dir/commands.env"
set +e
tool-a > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code == 1 )) || fail 'a missing command mapping must fail closed'

print -r -- $'tool-a=member\ntool-a=other' > "$config_dir/commands.env"
set +e
tool-a > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code == 1 )) || fail 'a duplicate command mapping must fail closed'

print -r -- 'tool-a = member' > "$config_dir/commands.env"
set +e
tool-a > /dev/null 2>&1
exit_code=$?
set -e
(( exit_code == 1 )) || fail 'a malformed command mapping must fail closed'

print -r -- 'tool-a=member' > "$config_dir/commands.env"
rm -- "$real_bin/tool-a"
full_fixture_path=$PATH
PATH=$shim_dir:$real_bin:$runtime_bin
set +e
tool-a > /dev/null 2>&1
exit_code=$?
set -e
PATH=$full_fixture_path
(( exit_code != 0 )) || fail 'a missing later executable must fail closed without recursion'

print -r -- 'secret command shim checks passed'
