#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
modifier=$repo_root/home/private_dot_config/zsh/modify_dot_zprofile
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/zprofile-hook.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT

fail() {
  print -u2 -r -- "$1"
  return 1
}

[[ -f $modifier ]] || fail 'the managed .zprofile modifier must exist'

original=$'# Added by another application\nsource ~/.other/init.zsh 2>/dev/null || :\n'
output=$(print -nr -- "$original" | python3 "$modifier")

[[ $output == *'# Added by another application'* ]] ||
  fail 'the modifier must preserve existing .zprofile content'
[[ $output == *'source $managed_zprofile'* ]] ||
  fail 'the modifier must source the managed zprofile implementation'

second_output=$(print -nr -- "$output" | python3 "$modifier")
[[ $second_output == $output ]] ||
  fail 'the modifier must be idempotent'

set +e
print -r -- '# >>> secret-exec managed zprofile >>>' |
  python3 "$modifier" >/dev/null 2>&1
partial_status=$?
set -e
(( partial_status != 0 )) ||
  fail 'the modifier must reject a partial managed block'

zdotdir=$test_dir/zdotdir
mkdir -p -- "$zdotdir"
print -r -- 'ZPROFILE_HOOK_LOADED=yes' > "$zdotdir/zprofile.zsh"
print -r -- "$output" > "$zdotdir/.zprofile"
ZDOTDIR=$zdotdir zsh -f -c \
  'source "$ZDOTDIR/.zprofile"; [[ ${ZPROFILE_HOOK_LOADED:-} == yes ]]' ||
  fail 'the generated .zprofile must load zprofile.zsh'

print -r -- 'zprofile hook checks passed'
