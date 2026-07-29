#!/usr/bin/env zsh
emulate -L zsh
setopt errexit nounset pipefail

repo_root=${0:A:h:h}
scanner=$repo_root/scripts/privacy-scan
test_root=$(mktemp -d "${TMPDIR:-/tmp}/privacy-scan.XXXXXX")
trap 'rm -rf -- "$test_root"' EXIT HUP INT TERM

mkdir -p "$test_root/clean" "$test_root/unsafe"
print -r -- 'contact fixture@example.invalid from /home/test-user/work' \
  >"$test_root/clean/source.txt"
python3 "$scanner" --root "$test_root/clean"

private_label=private-machine-
private_label+=label
print -r -- "$private_label" >"$test_root/denylist"
print -r -- "connect $private_label without printing a secret" \
  >"$test_root/unsafe/exact.txt"
print -r -- 'contact operator@'private.invalid >"$test_root/unsafe/email.txt"
print -r -- 'path=/home/'operator/private >"$test_root/unsafe/path.txt"

set +e
output=$(
  python3 "$scanner" \
    --root "$test_root/unsafe" \
    --denylist "$test_root/denylist"
)
scan_status=$?
set -e
(( scan_status != 0 ))
[[ $output == *'[exact-denylist]'* ]]
[[ $output == *'[email]'* ]]
[[ $output == *'[user-home]'* ]]
[[ $output != *"$private_label"* ]]
[[ $output != *'operator@'private.invalid* ]]

print -r -- 'privacy scan checks passed'
