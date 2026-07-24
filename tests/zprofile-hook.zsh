#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
hook_template=$repo_root/home/run_after_update-zprofile-hook.py.tmpl
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/zprofile-hook.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT
fixture_home=$test_dir/home
zdotdir=$fixture_home/.config/zsh
mkdir -p -- "$zdotdir"
hook=$test_dir/update-zprofile-hook
chezmoi -S "$repo_root/home" execute-template \
  --override-data '{"chezmoi":{"homeDir":"'"$fixture_home"'"}}' \
  < "$hook_template" > "$hook"
chmod +x "$hook"

fail() {
  print -u2 -r -- "$1"
  return 1
}

[[ -f $hook_template ]] || fail 'the managed .zprofile hook must exist'

original=$'# Added by another application\nsource ~/.other/init.zsh 2>/dev/null || :\n'
canonical=$'# >>> secret-exec managed zprofile >>>\nfunction {\n  local managed_zprofile=${ZDOTDIR:-$HOME/.config/zsh}/zprofile.zsh\n  [[ -r $managed_zprofile ]] && source $managed_zprofile\n}\n# <<< secret-exec managed zprofile <<<'
expected="${original}"$'\n'"${canonical}"$'\n'
print -nr -- "$original" > "$zdotdir/.zprofile"
chmod 644 "$zdotdir/.zprofile"
"$hook"
output=$(<"$zdotdir/.zprofile")

print -nr -- "$expected" > "$test_dir/expected"
cmp -s "$zdotdir/.zprofile" "$test_dir/expected" ||
  fail 'the hook must preserve the modifier output byte-for-byte'
[[ $output == *'# Added by another application'* ]] ||
  fail 'the hook must preserve existing .zprofile content'
[[ $output == *'source $managed_zprofile'* ]] ||
  fail 'the hook must source the managed zprofile implementation'
[[ $(stat -f '%Lp' "$zdotdir/.zprofile") == 644 ]] ||
  fail 'the hook must preserve the .zprofile mode'

before_digest=$(shasum -a 256 "$zdotdir/.zprofile")
"$hook"
second_output=$(<"$zdotdir/.zprofile")
[[ $second_output == $output ]] ||
  fail 'the hook must be idempotent'
[[ $(shasum -a 256 "$zdotdir/.zprofile") == "$before_digest" ]] ||
  fail 'an idempotent hook run must preserve the exact bytes'

set +e
print -r -- '# >>> secret-exec managed zprofile >>>' > "$zdotdir/.zprofile"
partial_before=$(shasum -a 256 "$zdotdir/.zprofile")
"$hook" >/dev/null 2>&1
partial_status=$?
set -e
(( partial_status != 0 )) ||
  fail 'the hook must reject a partial managed block'
[[ $(shasum -a 256 "$zdotdir/.zprofile") == "$partial_before" ]] ||
  fail 'a rejected partial block must remain byte-for-byte unchanged'

rm "$zdotdir/.zprofile"
"$hook"
[[ $(stat -f '%Lp' "$zdotdir/.zprofile") == 644 ]] ||
  fail 'the hook must create a missing .zprofile with mode 0644'
print -r -- 'ZPROFILE_HOOK_LOADED=yes' > "$zdotdir/zprofile.zsh"
ZDOTDIR=$zdotdir zsh -f -c \
  'source "$ZDOTDIR/.zprofile"; [[ ${ZPROFILE_HOOK_LOADED:-} == yes ]]' ||
  fail 'the generated .zprofile must load zprofile.zsh'

print -r -- 'zprofile hook checks passed'
