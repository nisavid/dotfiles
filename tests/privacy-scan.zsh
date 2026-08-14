#!/usr/bin/env zsh
emulate -L zsh
setopt errexit nounset pipefail

repo_root=${0:A:h:h}
scanner=$repo_root/scripts/privacy-scan
test_root=$(mktemp -d "${TMPDIR:-/tmp}/privacy-scan.XXXXXX")
trap 'rm -rf -- "$test_root"' EXIT HUP INT TERM

scan_output=
run_failed_scan() {
  set +e
  scan_output=$(python3 "$scanner" "$@" 2>&1)
  scan_status=$?
  set -e
  (( scan_status != 0 ))
}

mkdir -p "$test_root/clean" "$test_root/unsafe"
print -r -- 'contact fixture@example.invalid from /home/test-user/work' \
  >"$test_root/clean/source.txt"
python3 "$scanner" --root "$test_root/clean"

mkdir -p "$test_root/inventory-limit"
integer inventory_entry=0
repeat 10001; do
  (( ++inventory_entry ))
  : >"$test_root/inventory-limit/$inventory_entry"
done
run_failed_scan --root "$test_root/inventory-limit"
[[ $scan_output == 'privacy scan failed: scan resource limits exceeded' ]]

mkdir -p "$test_root/finding-limit"
finding_field=AWS_
finding_field+=ACCESS_KEY_ID
repeat 10001; do
  print -r -- "$finding_field=fixture-canary-value"
done >"$test_root/finding-limit/findings.txt"
run_failed_scan --root "$test_root/finding-limit"
[[ $scan_output == 'privacy scan failed: scan resource limits exceeded' ]]

finding_text_root=$test_root/finding-text-limit
long_segment=$(printf 'x%.0s' {1..200})
repeat 4; do
  finding_text_root+=/$long_segment
done
mkdir -p "$finding_text_root"
repeat 5001; do
  print -r -- "$finding_field=fixture-canary-value"
done >"$finding_text_root/findings.txt"
run_failed_scan --root "$test_root/finding-text-limit"
[[ $scan_output == 'privacy scan failed: scan resource limits exceeded' ]]

mkdir -p "$test_root/content-limit"
dd if=/dev/zero \
  of="$test_root/content-limit/1.bin" \
  bs=1 seek=4194304 count=0 2>/dev/null
integer content_entry=1
repeat 4; do
  (( ++content_entry ))
  ln "$test_root/content-limit/1.bin" \
    "$test_root/content-limit/$content_entry.bin"
done
run_failed_scan --root "$test_root/content-limit"
[[ $scan_output == 'privacy scan failed: scan resource limits exceeded' ]]

mkfifo "$test_root/denylist-fifo"
run_failed_scan \
  --root "$test_root/clean" \
  --denylist "$test_root/denylist-fifo"
[[ $scan_output == 'privacy scan failed' ]]

private_label=private-machine-
private_label+=label
print -r -- "$private_label" >"$test_root/denylist"
print -r -- "connect $private_label without printing a secret" \
  >"$test_root/unsafe/exact.txt"
print -r -- 'contact operator@'private.invalid >"$test_root/unsafe/email.txt"
print -r -- 'path=/home/'operator/private >"$test_root/unsafe/path.txt"

run_failed_scan \
  --root "$test_root/unsafe" \
  --denylist "$test_root/denylist"
[[ $scan_output == *'[exact-denylist]'* ]]
[[ $scan_output == *'[email]'* ]]
[[ $scan_output == *'[user-home]'* ]]
[[ $scan_output != *"$private_label"* ]]
[[ $scan_output != *'operator@'private.invalid* ]]

mkdir -p "$test_root/cache/.pytest_cache"
credential_name=AWS_
credential_name+=ACCESS_KEY_ID
print -r -- "$credential_name=fixture-canary-value" \
  >"$test_root/cache/.pytest_cache/state"
run_failed_scan --root "$test_root/cache"
[[ $scan_output == *'[provider-token]'* ]]

mkdir -p "$test_root/encoded"
encoded_field=AWS_
encoded_field+=ACCESS_KEY_ID
encoded_plaintext=$test_root/encoded-plaintext
print -r -- "$encoded_field=fixture-canary-value" >"$encoded_plaintext"
iconv -f UTF-8 -t UTF-32 "$encoded_plaintext" >"$test_root/encoded/value.txt"
rm -- "$encoded_plaintext"
run_failed_scan --root "$test_root/encoded"
[[ $scan_output == *'[provider-token]'* ]]

mkdir -p "$test_root/renamed"
print -n -r -- $'age-encryption.org/v1\n' >"$test_root/renamed/payload.bin"
run_failed_scan --root "$test_root/renamed"
[[ $scan_output == *'[invalid-age-envelope-suffix]'* ]]

mkdir -p "$test_root/exact-age"
print -r -- 'not ciphertext' >"$test_root/exact-age/.age"
run_failed_scan --root "$test_root/exact-age"
[[ $scan_output == *'.age:0: [invalid-age-envelope]'* ]]

mkdir -p "$test_root/required"
run_failed_scan --root "$test_root/required" --require-age-manifest
[[ $scan_output == *'[invalid-age-envelope-manifest]'* ]]

mkdir -p "$test_root/control"
control_name=$'line\nforged.txt'
print -r -- 'clean' >"$test_root/control/$control_name"
run_failed_scan --root "$test_root/control"
[[ $scan_output == *'[control-character-filename]'* ]]
[[ $scan_output == *'redacted-path:sha256:'* ]]
[[ $scan_output != *$'line\nforged.txt'* ]]

print -r -- 'privacy scan checks passed'
