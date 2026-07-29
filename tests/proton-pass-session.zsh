#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
helper=$repo_root/home/private_dot_local/bin/executable_proton-pass-session

fail() {
  print -u2 -r -- "$1"
  return 1
}

test_dir=$(mktemp -d "${TMPDIR:-/tmp}/proton-pass-session.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT
fake_bin=$test_dir/bin
fixture_home=$test_dir/home
mkdir -p "$fake_bin" "$fixture_home"

cat > "$fake_bin/pass-cli" <<'EOF'
#!/usr/bin/env zsh
set -euo pipefail

print -r -- "$*" >> "$FAKE_PASS_LOG"
case $1 in
  test)
    [[ -e $FAKE_PASS_SESSION ]]
    ;;
  login)
    (( $# == 1 )) || exit 64
    [[ ${PROTON_PASS_PERSONAL_ACCESS_TOKEN:-} == \
      'pst_fixture-token::fixture-key' ]] || exit 65
    [[ ${PROTON_PASS_LINUX_KEYRING:-} == dbus ]] || exit 66
    : > "$FAKE_PASS_SESSION"
    ;;
  *)
    exit 67
    ;;
esac
EOF
chmod +x "$fake_bin/pass-cli"

export PATH=$fake_bin:/usr/bin:/bin
export HOME=$fixture_home
export FAKE_PASS_LOG=$test_dir/pass.log
export FAKE_PASS_SESSION=$test_dir/session
export PROTON_PASS_PERSONAL_ACCESS_TOKEN='pst_fixture-token::fixture-key'

zsh "$helper"
[[ -e $FAKE_PASS_SESSION ]] || fail 'the helper must establish a missing session'
[[ "$(<"$FAKE_PASS_LOG")" == $'test\nlogin\ntest' ]] ||
  fail 'the helper must test, login without argv credentials, and verify'

: > "$FAKE_PASS_LOG"
zsh "$helper"
[[ "$(<"$FAKE_PASS_LOG")" == test ]] ||
  fail 'an existing session must not trigger another login'

rm -- "$FAKE_PASS_SESSION"
unset PROTON_PASS_PERSONAL_ACCESS_TOKEN
set +e
zsh "$helper" >/dev/null 2>&1
exit_code=$?
set -e
(( exit_code != 0 )) || fail 'a missing PAT must fail closed'
[[ ! -e $FAKE_PASS_SESSION ]] || fail 'a missing PAT must not create a session'

print -r -- 'Proton Pass session checks passed'
