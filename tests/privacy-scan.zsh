#!/usr/bin/env zsh
emulate -L zsh
setopt errexit nounset pipefail

repo_root=${0:A:h:h}
scanner=$repo_root/scripts/privacy-scan
test_root=$(mktemp -d "${TMPDIR:-/tmp}/privacy-scan.XXXXXX")
trap 'rm -rf -- "$test_root"' EXIT HUP INT TERM

scan_output=
run_scan() {
  set +e
  scan_output=$(python3 "$scanner" "$@" 2>&1)
  scan_status=$?
  set -e
}

run_failed_scan() {
  run_scan "$@"
  (( scan_status != 0 ))
}

expect_single_finding() {
  local expected=$1
  shift
  expect_findings "$expected" 1 "$@"
}

expect_findings() {
  local expected=$1
  local expected_count=$2
  local -a output_lines
  shift 2
  run_scan "$@"
  output_lines=("${(f)scan_output}")
  (( scan_status != 0 ))
  (( ${#output_lines[@]} == expected_count ))
  [[ $scan_output == "$expected" ]]
}

mkdir -p "$test_root/clean" "$test_root/unsafe"
print -r -- 'contact fixture@example.invalid from /home/test-user/work' \
  >"$test_root/clean/source.txt"
python3 "$scanner" --root "$test_root/clean"

isolated_tool=$test_root/isolated-tool
isolated_policy_root=$test_root/home/private_dot_local/lib/agent-equipment/agent_equipment
mkdir -p "$isolated_tool"
mkdir -p "$isolated_policy_root"
cp \
  "$scanner" \
  "$repo_root/scripts/agent_equipment_public_data.py" \
  "$repo_root/scripts/privacy_age_envelopes.py" \
  "$isolated_tool"
cp \
  "$repo_root/home/private_dot_local/lib/agent-equipment/agent_equipment/secrets.py" \
  "$isolated_policy_root"
env -u PYTHONPYCACHEPREFIX -u PYTHONDONTWRITEBYTECODE \
  python3 "$isolated_tool/privacy-scan" --root "$test_root/clean"
if [[ -e $isolated_tool/__pycache__ ]]; then
  print -u2 -r -- 'privacy scan created a bytecode cache beside its source'
  exit 1
fi

artifact_at=@
openssl_formula=openssl${artifact_at}3.5.rb
sq_formula=sequoia-sq-pqc${artifact_at}1.4.0.rb
sqv_formula=sequoia-sqv-pqc${artifact_at}1.5.0.rb
sq_bottle=sequoia-sq-pqc${artifact_at}1.4.0.bottle.json
sqv_bottle=sequoia-sqv-pqc${artifact_at}1.5.0.bottle.json
performance_fragment=/a${artifact_at}1.2.rb\)

mkdir -p "$test_root/performance"
PRIVACY_SCAN_PERFORMANCE_FRAGMENT=$performance_fragment \
  python3 - "$scanner" "$test_root/performance" <<'PY'
import os
from pathlib import Path
import subprocess
import sys

scanner = sys.argv[1]
root = Path(sys.argv[2])
source = root / "source.txt"
source.write_text(
    "formula_path=" + os.environ["PRIVACY_SCAN_PERFORMANCE_FRAGMENT"] * 40_000,
    encoding="utf-8",
)
try:
    subprocess.run(
        [sys.executable, scanner, "--root", os.fspath(root)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
    )
except subprocess.TimeoutExpired as error:
    raise SystemExit("privacy scan exceeded bounded runtime") from error
PY

homebrew_root=$test_root/homebrew-artifacts
mkdir -p "$homebrew_root/Formula"
: >"$homebrew_root/Formula/$sq_formula"
: >"$homebrew_root/Formula/$sqv_formula"
{
  print -r -- "openssl_formula=\"\$downloads/$openssl_formula\""
  print -r -- ">$sq_bottle"
  print -r -- ">$sqv_bottle"
  print -r -- \
    "\"homebrew_core_formula_path\": \"Formula/o/$openssl_formula\","
  print -r -- \
    "\"formula_url\": \"https://raw.githubusercontent.com/Homebrew/homebrew-core/fixture/Formula/o/$openssl_formula\","
  print -r -- \
    "\"formula_path\": \"packaging/homebrew/Formula/$sq_formula\","
  print -r -- \
    "\"formula_path\": \"packaging/homebrew/Formula/$sqv_formula\","
} >"$homebrew_root/references.txt"
run_scan --root "$homebrew_root"
(( scan_status == 0 ))
[[ -z $scan_output ]]

mkdir -p "$test_root/formula-semicolon"
print -r -- "formula_path=/opt/$openssl_formula; next=1" \
  >"$test_root/formula-semicolon/source.txt"
run_scan --root "$test_root/formula-semicolon"
(( scan_status == 0 ))
[[ -z $scan_output ]]

mkdir -p "$test_root/bottle-quoted-output"
{
  print -r -- "command > \"$sq_bottle\""
  print -r -- "command > '$sqv_bottle'"
  print -r -- $'command\t>\t'"$sq_bottle"
  print -r -- ">$sqv_bottle"
  print -r -- "command > \"$sq_bottle\";"
} >"$test_root/bottle-quoted-output/source.txt"
run_scan --root "$test_root/bottle-quoted-output"
(( scan_status == 0 ))
[[ -z $scan_output ]]

mkdir -p "$test_root/bottle-non-output"
{
  print -r -- "note=>$sq_bottle"
  print -r -- "note==>$sq_bottle"
  print -r -- "command>$sq_bottle"
  print -r -- "2>$sq_bottle"
  print -r -- ">>$sq_bottle"
  print -r -- "command > \"$sq_bottle'"
  print -r -- "command > \"${sq_bottle}_extra\""
  print -r -- "note=\"command > '$sq_bottle'\""
  print -r -- "command > \"$sq_bottle\"\"_extra\""
} >"$test_root/bottle-non-output/source.txt"
expect_findings \
  $'source.txt:1: [email] review required\nsource.txt:2: [email] review required\nsource.txt:3: [email] review required\nsource.txt:4: [email] review required\nsource.txt:5: [email] review required\nsource.txt:6: [email] review required\nsource.txt:7: [email] review required\nsource.txt:8: [email] review required\nsource.txt:9: [email] review required' \
  9 \
  --root "$test_root/bottle-non-output"

same_seam_private_email=operator${artifact_at}private.invalid
mkdir -p "$test_root/homebrew-span-local"
{
  print -r -- \
    "formula_path=/opt/$openssl_formula; contact=$same_seam_private_email"
  print -r -- \
    "command > \"$sq_bottle\"; contact=$same_seam_private_email"
  print -r -- "formula_path=/opt/${openssl_formula}_extra; next=1"
  print -r -- "formula_path=\"/opt/$openssl_formula\"\"_extra\""
} >"$test_root/homebrew-span-local/source.txt"
expect_findings \
  $'source.txt:1: [email] review required\nsource.txt:2: [email] review required\nsource.txt:3: [email] review required\nsource.txt:4: [email] review required' \
  4 \
  --root "$test_root/homebrew-span-local"

homebrew_bom_root=$test_root/homebrew-bom-views
homebrew_bom_mixed_root=$test_root/homebrew-bom-mixed
mkdir -p "$homebrew_bom_root" "$homebrew_bom_mixed_root"
bom_formula_line="formula_path=/opt/$openssl_formula"
bom_private_domain=private.invalid
bom_private_email=operator${artifact_at}${bom_private_domain}
bom_mixed_line="$bom_formula_line contact=$bom_private_email"
PRIVACY_SCAN_BOM_FORMULA_LINE=$bom_formula_line \
PRIVACY_SCAN_BOM_MIXED_LINE=$bom_mixed_line \
  python3 - "$homebrew_bom_root" "$homebrew_bom_mixed_root" <<'PY'
import codecs
import os
from pathlib import Path
import sys

roots_and_lines = (
    (Path(sys.argv[1]), os.environ["PRIVACY_SCAN_BOM_FORMULA_LINE"]),
    (Path(sys.argv[2]), os.environ["PRIVACY_SCAN_BOM_MIXED_LINE"]),
)
for root, line in roots_and_lines:
    encoded_views = {
        "utf-8.txt": line.encode("utf-8-sig"),
        "utf-16-le.txt": codecs.BOM_UTF16_LE + line.encode("utf-16-le"),
        "utf-16-be.txt": codecs.BOM_UTF16_BE + line.encode("utf-16-be"),
        "utf-32-le.txt": codecs.BOM_UTF32_LE + line.encode("utf-32-le"),
        "utf-32-be.txt": codecs.BOM_UTF32_BE + line.encode("utf-32-be"),
    }
    for name, data in encoded_views.items():
        (root / name).write_bytes(data)
PY
run_scan --root "$homebrew_bom_root"
(( scan_status == 0 ))
[[ -z $scan_output ]]
expect_findings \
  $'utf-16-be.txt:1: [email] review required\nutf-16-le.txt:1: [email] review required\nutf-32-be.txt:1: [email] review required\nutf-32-le.txt:1: [email] review required\nutf-8.txt:1: [email] review required' \
  5 \
  --root "$homebrew_bom_mixed_root"

mkdir -p "$test_root/homebrew-cr-lines"
first_cr_formula="formula_path=/opt/$sq_formula"
second_cr_formula="formula_url=https://example.invalid/$sqv_formula"
print -n -r -- \
  "$first_cr_formula"$'\r'"$second_cr_formula"$'\r' \
  >"$test_root/homebrew-cr-lines/source.txt"
run_scan --root "$test_root/homebrew-cr-lines"
(( scan_status == 0 ))
[[ -z $scan_output ]]

private_domain=private.invalid
private_email=operator${artifact_at}${private_domain}
formula_like_email=sequoia-sq-pqc${artifact_at}${private_domain}
bare_formula=widget${artifact_at}1.2.3.rb
bare_bottle=widget${artifact_at}1.2.3.bottle.json
uppercase_formula=OpenSSL${artifact_at}3.5.rb
arbitrary_formula=operator${artifact_at}1.2.rb
arbitrary_bottle=operator${artifact_at}1.2.bottle.json
suffix_dash=-extra
suffix_plus=+extra
suffix_underscore=_extra
chained_suffix=${artifact_at}${private_domain}

mkdir -p "$test_root/context-boundaries"
{
  print -r -- "/$arbitrary_formula"
  print -r -- "/$arbitrary_bottle"
} >"$test_root/context-boundaries/source.txt"
ln -s "/opt/$arbitrary_formula" "$test_root/context-boundaries/reference"
expect_findings \
  $'reference:0: [email-symlink-target] review required\nsource.txt:1: [email] review required\nsource.txt:2: [email] review required' \
  3 \
  --root "$test_root/context-boundaries"

mkdir -p "$test_root/artifact-adjacency"
{
  print -r -- \
    "\"formula_path\": \"Formula/o/$openssl_formula$suffix_dash\""
  print -r -- \
    "\"formula_url\": \"https://example.invalid/$openssl_formula$chained_suffix\""
  print -r -- ">$sq_bottle$suffix_dash"
  print -r -- ">$sq_bottle$suffix_plus"
  print -r -- ">$sq_bottle$chained_suffix"
  print -r -- \
    "\"formula_path\": \"Formula/o/$openssl_formula$suffix_underscore\""
} >"$test_root/artifact-adjacency/source.txt"
expect_findings \
  $'source.txt:1: [email] review required\nsource.txt:2: [email] review required\nsource.txt:3: [email] review required\nsource.txt:4: [email] review required\nsource.txt:5: [email] review required\nsource.txt:6: [email] review required' \
  6 \
  --root "$test_root/artifact-adjacency"

mkdir -p "$test_root/encoded-adjacency"
encoded_adjacency=$test_root/encoded-adjacency.txt
print -r -- \
  "\"formula_path\": \"Formula/o/$openssl_formula$suffix_plus\"" \
  >"$encoded_adjacency"
iconv -f UTF-8 -t UTF-32LE "$encoded_adjacency" \
  >"$test_root/encoded-adjacency/source.bin"
rm -- "$encoded_adjacency"
expect_single_finding \
  'source.bin:1: [email] review required' \
  --root "$test_root/encoded-adjacency"

mkdir -p "$test_root/private-email-content"
print -r -- "contact $private_email" \
  >"$test_root/private-email-content/source.txt"
expect_single_finding \
  'source.txt:1: [email] review required' \
  --root "$test_root/private-email-content"

mkdir -p "$test_root/formula-like-email"
print -r -- "contact $formula_like_email" \
  >"$test_root/formula-like-email/source.txt"
expect_single_finding \
  'source.txt:1: [email] review required' \
  --root "$test_root/formula-like-email"

mkdir -p "$test_root/bare-formula"
print -r -- "$bare_formula" >"$test_root/bare-formula/source.txt"
expect_single_finding \
  'source.txt:1: [email] review required' \
  --root "$test_root/bare-formula"

mkdir -p "$test_root/bare-bottle"
print -r -- "$bare_bottle" >"$test_root/bare-bottle/source.txt"
expect_single_finding \
  'source.txt:1: [email] review required' \
  --root "$test_root/bare-bottle"

mkdir -p "$test_root/mixed-email-content"
print -r -- "formula_path=/opt/$openssl_formula contact=$private_email" \
  >"$test_root/mixed-email-content/source.txt"
expect_single_finding \
  'source.txt:1: [email] review required' \
  --root "$test_root/mixed-email-content"

mkdir -p "$test_root/uppercase-artifact"
print -r -- "/$uppercase_formula" \
  >"$test_root/uppercase-artifact/source.txt"
expect_single_finding \
  'source.txt:1: [email] review required' \
  --root "$test_root/uppercase-artifact"

mkdir -p "$test_root/private-email-filename"
print -r -- 'clean' >"$test_root/private-email-filename/$private_email"
expect_single_finding \
  'redacted-path:sha256:d1982bd298a9cacc:0: [email-filename] review required' \
  --root "$test_root/private-email-filename"

mkdir -p "$test_root/private-parent/$private_email/Formula"
print -r -- 'clean' \
  >"$test_root/private-parent/$private_email/Formula/$openssl_formula"
expect_single_finding \
  'redacted-path:sha256:6fe3741c30606b36:0: [email-filename] review required' \
  --root "$test_root/private-parent"

mkdir -p "$test_root/formula-outside-parent/Elsewhere"
print -r -- 'clean' \
  >"$test_root/formula-outside-parent/Elsewhere/$openssl_formula"
expect_single_finding \
  'redacted-path:sha256:ea06b2a9f09fa243:0: [email-filename] review required' \
  --root "$test_root/formula-outside-parent"

mkdir -p "$test_root/duplicate-formula/$openssl_formula/Formula"
print -r -- 'clean' \
  >"$test_root/duplicate-formula/$openssl_formula/Formula/$openssl_formula"
expect_single_finding \
  'redacted-path:sha256:64b9d51fb5cdfe80:0: [email-filename] review required' \
  --root "$test_root/duplicate-formula"

chained_parent=$openssl_formula$chained_suffix
mkdir -p "$test_root/chained-parent/$chained_parent/Formula"
print -r -- "contact $private_email" \
  >"$test_root/chained-parent/$chained_parent/Formula/$openssl_formula"
expect_findings \
  $'redacted-path:sha256:5d93637053cb5adb:0: [email-filename] review required\nredacted-path:sha256:5d93637053cb5adb:1: [email] review required' \
  2 \
  --root "$test_root/chained-parent"
[[ $scan_output != *"$private_email"* ]]
[[ $scan_output != *"$chained_parent"* ]]

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

set +e
scan_output=$(
  python3 -c 'import sys; sys.stdout.buffer.write(b"x" * (1024 * 1024 + 1))' |
    python3 "$scanner" --root "$test_root/clean" --denylist - 2>&1
)
scan_status=$?
set -e
(( scan_status != 0 ))
[[ $scan_output == 'privacy scan failed: scan resource limits exceeded' ]]

set +e
scan_output=$(
  python3 -c 'import sys; sys.stdout.write("".join(f"term-{i}\n" for i in range(10001)))' |
    python3 "$scanner" --root "$test_root/clean" --denylist - 2>&1
)
scan_status=$?
set -e
(( scan_status != 0 ))
[[ $scan_output == 'privacy scan failed: scan resource limits exceeded' ]]

dd if=/dev/zero \
  of="$test_root/oversized-denylist" \
  bs=1 seek=4194305 count=0 2>/dev/null
run_failed_scan \
  --root "$test_root/clean" \
  --denylist "$test_root/oversized-denylist"
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
iconv -f UTF-8 -t UTF-32LE "$encoded_plaintext" \
  >"$test_root/encoded/value-le.txt"
iconv -f UTF-8 -t UTF-32BE "$encoded_plaintext" \
  >"$test_root/encoded/value-be.txt"
rm -- "$encoded_plaintext"
run_failed_scan --root "$test_root/encoded"
[[ $scan_output == *'value-le.txt:'*'[provider-token]'* ]]
[[ $scan_output == *'value-be.txt:'*'[provider-token]'* ]]

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
