#!/usr/bin/env zsh
emulate -L zsh
setopt errexit nounset pipefail

repo_root=${0:A:h:h}
ignore_template=$repo_root/home/.chezmoiignore
workflow=$repo_root/.github/workflows/platform-portability.yml
test_root=$(mktemp -d "${TMPDIR:-/tmp}/platform-portability.XXXXXX")
trap 'rm -rf -- "$test_root"' EXIT HUP INT TERM

fail() {
  print -u2 -r -- "FAIL: $*"
  return 1
}

assert_line() {
  local line=$1 file=$2
  grep -Fqx -- "$line" "$file" || fail "missing ignore entry: $line"
}

workflow_concurrency=$(
  awk '
    $0 == "concurrency:" { in_block = 1; next }
    in_block && /^[^[:space:]]/ { exit }
    in_block { print }
  ' "$workflow"
)
[[ $workflow_concurrency == *'group: ${{ github.workflow }}-${{ github.ref }}'* ]] ||
  fail 'platform workflow does not group superseded runs by workflow and ref'
[[ $workflow_concurrency == *'cancel-in-progress: true'* ]] ||
  fail 'platform workflow does not cancel superseded runs'
grep -Fq 'AGE_VERSION: "1.3.1"' "$workflow" ||
  fail 'platform workflow does not pin the age parser version'
grep -Fq 'brew install bat flock jq ripgrep' "$workflow" ||
  fail 'platform workflow does not install macOS runtime dependencies'
grep -Fq 'age-v${AGE_VERSION}-darwin-arm64.tar.gz' "$workflow" ||
  fail 'platform workflow does not install the pinned arm64 macOS age parser'
grep -Fq 'age-v${AGE_VERSION}-darwin-amd64.tar.gz' "$workflow" ||
  fail 'platform workflow does not install the pinned amd64 macOS age parser'
grep -Fq 'sudo apt-get -qq install -y acl bat curl jq ripgrep zsh' "$workflow" ||
  fail 'platform workflow does not install Linux runtime dependencies'
grep -Fq 'age-v${AGE_VERSION}-linux-amd64.tar.gz' "$workflow" ||
  fail 'platform workflow does not install the pinned Linux age parser'
grep -Fq '"$RUNNER_TEMP/age/age-inspect"' "$workflow" ||
  fail 'platform workflow does not install age-inspect'
grep -Fq 'test "$(age-inspect --version)" = "v${AGE_VERSION}"' "$workflow" ||
  fail 'platform workflow does not verify the age parser version'
grep -Fq 'python3 -m pip install uv==0.11.32' "$workflow" ||
  fail 'platform workflow does not install the pinned uv runtime'
grep -Fq \
  "python3 -m unittest discover -s tests/agent_equipment -t . -p 'test_*.py'" \
  "$workflow" ||
  fail 'platform workflow does not discover production agent-equipment tests'
expected_pyrefly_type_gate=$(
  print -rl -- \
    '          uvx --from pyrefly==1.2.0 pyrefly check \' \
    '            --preset strict \' \
    '            --min-severity warn \' \
    '            --search-path home/private_dot_local/lib/agent-equipment \' \
    '            --progress-bar no \' \
    '            --summary=full \' \
    '            home/private_dot_local/lib/agent-equipment/agent_equipment \' \
    '            home/private_dot_local/bin/executable_agent-equipment'
)
workflow_type_gate=$(
  awk '
    /uvx --from (mypy|pyrefly)==/ { in_gate = 1 }
    in_gate { print }
    in_gate && /home\/private_dot_local\/bin\/executable_agent-equipment/ { exit }
  ' "$workflow"
)
[[ $workflow_type_gate == "$expected_pyrefly_type_gate" ]] ||
  fail 'platform workflow does not run the exact pinned Pyrefly gate'
! grep -Fq 'mypy' "$workflow" ||
  fail 'platform workflow still runs the superseded Mypy gate'
grep -Fq \
  'home/private_dot_local/bin/executable_agent-equipment' \
  "$workflow" ||
  fail 'platform workflow does not statically type-check the installed launcher'
workflow_path_filter_pattern='^[[:space:]]+paths(-ignore)?:'
! grep -Eq "$workflow_path_filter_pattern" "$workflow" ||
  fail 'platform workflow does not run the privacy gate for every change'
for filtered_trigger in '    paths:' '    paths-ignore:'; do
  print -r -- "$filtered_trigger" | grep -Eq "$workflow_path_filter_pattern" ||
    fail "platform workflow path-filter guard missed: $filtered_trigger"
done
grep -Fq \
  'python3 scripts/privacy-scan --root . --require-age-manifest' \
  "$workflow" ||
  fail 'platform workflow does not enforce the age-envelope manifest'
required_age_modules=$(
  awk '
    /REQUIRE_AGE_TOOLING=1/ { required = 1; next }
    required && /python3 -m unittest/ { print; required = 0 }
  ' "$workflow"
)
[[ $required_age_modules == *'tests/test_agent_equipment_public_data.py'* ]] ||
  fail 'platform workflow may skip public-data age-inspect coverage'
[[ $required_age_modules == *'tests/test_privacy_age_envelopes.py'* ]] ||
  fail 'platform workflow may skip age-envelope tooling coverage'
grep -Fq 'AGE_TOOLING_DIRECTORY: ${{ runner.temp }}/chezmoi-bin' "$workflow" ||
  fail 'platform workflow does not anchor admission to the verified age install'
grep -Fq -- \
  '--base-uri "file://$PWD/docs/agent-equipment/adapter-contract-v1.schema.json"' \
  "$workflow" ||
  fail 'platform workflow does not anchor adapter schema references to the local file'

age_boundary_workflow=$repo_root/.github/workflows/privacy-age-integrity.yml
admission_activation_marker=$(
  cd "$repo_root"
  python3 -I -c 'import sys
sys.path.insert(0, ".")
from scripts.privacy_age_integrity_gate import ADMISSION_ACTIVATION_MARKER
sys.stdout.buffer.write(ADMISSION_ACTIVATION_MARKER.rstrip(b"\r\n"))'
) || fail 'cannot derive the age admission activation marker'
grep -Fxq -- "$admission_activation_marker" \
  "$age_boundary_workflow" ||
  fail 'age boundary is missing the admission activation sentinel'
untrusted_head_execution_pattern='^[[:space:]]*((uses|working-directory):[[:space:]]*(\./)?untrusted-head(/|$)|(run:[[:space:]]*)?(\./)?untrusted-head/|(run:[[:space:]]*)?.*((cd|source)[[:space:]]+|\.[[:space:]]+)([^[:space:]]*/)?untrusted-head(/|[[:space:]]|$)|(run:[[:space:]]*)?.*(^|[^[:alnum:]_])(python[0-9.]*|bash|sh|zsh|ruby|perl|node|npm|npx|make)([[:space:]]|$).*untrusted-head/|(run:[[:space:]]*)?.*(&&|\|\||;)[[:space:]]*(\./)?untrusted-head/)'
grep -Fq '  pull_request_target:' "$age_boundary_workflow" ||
  fail 'age boundary does not execute from the trusted base event'
grep -Fq '          path: trusted-base' "$age_boundary_workflow" ||
  fail 'age boundary does not isolate the trusted base checkout'
grep -Fq '          path: untrusted-head' "$age_boundary_workflow" ||
  fail 'age boundary does not isolate the candidate data checkout'
grep -Fq 'python3 -I trusted-base/scripts/privacy_age_integrity_gate.py' \
  "$age_boundary_workflow" ||
  fail 'age boundary does not execute the trusted transition verifier'
grep -Fq 'require_trusted_executable' "$age_boundary_workflow" ||
  fail 'age boundary does not validate trusted verifier file kinds and modes'
grep -Fq 'PRIVACY_REPOSITORY: ${{ github.repository }}' \
  "$age_boundary_workflow" ||
  fail 'age boundary does not bind the repository identity'
grep -Fq 'python3 -I - "$GITHUB_EVENT_PATH"' "$age_boundary_workflow" ||
  fail 'age boundary does not extract the pull-request body from the trusted event'
grep -Fq -- '--admission-body "$RUNNER_TEMP/privacy-age-admission-body"' \
  "$age_boundary_workflow" ||
  fail 'age boundary does not pass the bounded admission body'
grep -Fq -- \
  '--allowed-signers trusted-base/.github/age-admission/allowed_signers' \
  "$age_boundary_workflow" ||
  fail 'age boundary does not use the trusted signer configuration'
grep -Fq -- '--repository "$PRIVACY_REPOSITORY"' "$age_boundary_workflow" ||
  fail 'age boundary does not bind admission to the repository'
grep -Fq 'python3 -I trusted-base/scripts/privacy-scan' "$age_boundary_workflow" ||
  fail 'age boundary does not execute the trusted privacy scanner'
grep -Fq 'REVIEWED_BOOTSTRAP_MANIFEST' "$repo_root/docs/ENCRYPTION.md" ||
  fail 'bootstrap runbook does not require a detached reviewed manifest'
grep -Fq 'test "$tree_digest" = "$manifest_tree_digest"' \
  "$repo_root/docs/ENCRYPTION.md" ||
  fail 'bootstrap runbook does not enforce the reviewed tree digest'
grep -Fq 'AGE_TOOLING_DIRECTORY: ${{ runner.temp }}/age-bin' "$age_boundary_workflow" ||
  fail 'age boundary does not bind scanning to the checksum-verified parser directory'
! grep -Eq \
  "$untrusted_head_execution_pattern" \
  "$age_boundary_workflow" ||
  fail 'age boundary executes candidate code'
for unsafe_line in \
  'run: cd untrusted-head && ./scripts/privacy-scan' \
  'run: cd /tmp/work/untrusted-head && ./scripts/privacy-scan' \
  'run: source untrusted-head/scripts/privacy-scan' \
  'run: . untrusted-head/scripts/privacy-scan' \
  'run: python3 untrusted-head/scripts/privacy-scan' \
  'run: /usr/bin/python3.12 untrusted-head/scripts/privacy-scan' \
  'run: printf ready && untrusted-head/scripts/privacy-scan'; do
  print -r -- "$unsafe_line" | grep -Eq "$untrusted_head_execution_pattern" ||
    fail "age boundary execution guard missed: $unsafe_line"
done
for safe_line in \
  'run: echo cpython3 untrusted-head/data' \
  'run: echo shell untrusted-head/data'; do
  ! print -r -- "$safe_line" | grep -Eq "$untrusted_head_execution_pattern" ||
    fail "age boundary execution guard overmatched: $safe_line"
done
[[ -x "$repo_root/scripts/create-age-admission-receipt" ]] ||
  fail 'age admission receipt command is not executable'
[[ -x "$repo_root/scripts/run-trusted-age-admission" ]] ||
  fail 'trusted age admission wrapper is not executable'
[[ -f "$repo_root/.github/age-admission/allowed_signers" ]] ||
  fail 'age admission allowed-signers configuration is missing'
admission_signer_pattern=$(
  cd "$repo_root"
  python3 -I -c 'import re, sys
sys.path.insert(0, ".")
from scripts.privacy_age_admission import ADMISSION_NAMESPACE, ADMISSION_PRINCIPAL
print(
    "^"
    + re.escape(ADMISSION_PRINCIPAL)
    + " namespaces=\""
    + re.escape(ADMISSION_NAMESPACE)
    + "\" ssh-[a-z0-9-]+ [A-Za-z0-9+/=]+( .*)?$"
)'
) || fail 'cannot derive the age admission signer pattern'
grep -Eq -- "$admission_signer_pattern" \
  "$repo_root/.github/age-admission/allowed_signers" ||
  fail 'age admission allowed-signers configuration lacks the owner principal'

chezmoi -S "$repo_root/home" execute-template \
  --override-data '{"chezmoi":{"os":"linux"}}' \
  <"$ignore_template" >"$test_root/linux-ignore"
chezmoi -S "$repo_root/home" execute-template \
  --override-data '{"chezmoi":{"os":"darwin"}}' \
  <"$ignore_template" >"$test_root/darwin-ignore"

typeset -a linux_only_patterns=(
  '.agents/skills/hindsight-*'
  '.config/hindsight-*'
  '.docker'
  '.hindsight*'
  '.local/bin/hindsight-*'
  '.local/lib/hindsight-*'
  '.local/libexec'
  'Library'
)

for pattern in $linux_only_patterns; do
  assert_line "$pattern" "$test_root/linux-ignore"
  ! grep -Fqx -- "$pattern" "$test_root/darwin-ignore" ||
    fail "Darwin unexpectedly ignores $pattern"
done

gui_source_inventory=$(
  find \
    "$repo_root/home/private_Library" \
    "$repo_root/home/private_dot_local/libexec" \
    -type f -print |
    sed "s#^$repo_root/home/##" |
    LC_ALL=C sort
)
expected_gui_source_inventory=$(
  printf '%s\n' \
    'private_Library/private_LaunchAgents/io.nisavid.secret-exec-provider-ready.plist.tmpl' \
    'private_Library/private_LaunchAgents/io.nisavid.zsh-gui-path.plist.tmpl' \
    'private_dot_local/libexec/nisavid/executable_zsh-gui-path.tmpl'
)
[[ $gui_source_inventory == $expected_gui_source_inventory ]] ||
  fail 'Darwin-only GUI source inventory changed without updating the Linux gate'

provider_linux_source_inventory=$(
  find "$repo_root/home/dot_config/systemd" -type f -print |
    sed "s#^$repo_root/home/##" |
    LC_ALL=C sort
)
expected_provider_linux_source_inventory=$(
  printf '%s\n' \
    'dot_config/systemd/user/plasma-workspace.target.wants/symlink_proton-pass-ensure-ready.service' \
    'dot_config/systemd/user/proton-pass-ensure-ready.service'
)
[[ $provider_linux_source_inventory == $expected_provider_linux_source_inventory ]] ||
  fail 'Linux provider-readiness source inventory changed without updating the non-Linux gate'

fixture_source=$test_root/source
fixture_home=$test_root/home
fixture_config=$test_root/chezmoi.toml
mkdir -p \
  "$fixture_source/private_dot_docker" \
  "$fixture_source/private_dot_local/libexec/fixture" \
  "$fixture_source/private_Library/private_LaunchAgents" \
  "$fixture_home"
cp "$test_root/linux-ignore" "$fixture_source/.chezmoiignore"

while IFS= read -r source_path; do
  relative_source=${source_path#"$repo_root/home/"}
  fixture_path=$fixture_source/$relative_source
  if [[ -d $source_path ]]; then
    mkdir -p "$fixture_path"
  elif [[ -f $source_path ]]; then
    mkdir -p "${fixture_path:h}"
    touch "$fixture_path"
  fi
done < <(find "$repo_root/home" -mindepth 1 -path '*hindsight*' -print)

touch \
  "$fixture_source/private_dot_docker/private_config.json" \
  "$fixture_source/private_dot_local/libexec/fixture/executable_zsh-gui-path" \
  "$fixture_source/private_Library/private_LaunchAgents/io.fixture.zsh-gui-path.plist"
touch "$fixture_config"

managed=$(
  HOME=$fixture_home chezmoi -S "$fixture_source" -D "$fixture_home" \
    --config "$fixture_config" managed
)
[[ $managed != *hindsight* ]] ||
  fail 'Linux manages a Hindsight fixture'
[[ $managed != *'.docker'* ]] ||
  fail 'Linux manages the OrbStack Docker fixture'
for held_target in \
  '.local/libexec' \
  '.local/libexec/fixture/zsh-gui-path' \
  'Library' \
  'Library/LaunchAgents/io.fixture.zsh-gui-path.plist'; do
  [[ $managed != *"$held_target"* ]] ||
    fail "Linux manages the zsh GUI fixture: $held_target"
done

if [[ $(uname -s) == Linux ]]; then
  acl_home=$test_root/acl-home
  acl_state=$test_root/acl-state
  acl_bin=$test_root/acl-bin
  mkdir -m 700 -p "$acl_home" "$acl_bin"
  mkdir -m 755 -p "$acl_state/chezmoi"
  print -r -- '#!/bin/sh
printf "managed\n"' >"$acl_bin/chezmoi"
  print -r -- '#!/bin/sh
printf "%s\n" "$@" >"$SETFACL_ARGS"
exec /usr/bin/setfacl "$@"' >"$acl_bin/setfacl"
  chmod 700 "$acl_bin/chezmoi" "$acl_bin/setfacl"
  print -r -- managed >"$acl_home/managed"
  chmod 640 "$acl_home/managed"
  HOME=$acl_home XDG_STATE_HOME=$acl_state \
    PATH="$acl_bin:/usr/bin:/bin" \
    /bin/sh "$repo_root/home/run_before_save-acl.sh"
  [[ $(stat -c '%a' -- "$acl_state/chezmoi") == 700 ]] ||
    fail 'ACL state directory is not mode 0700'
  [[ $(stat -c '%a' -- "$acl_state/chezmoi/acl") == 600 ]] ||
    fail 'ACL snapshot is not mode 0600'
  grep -Fqx '# file: managed' "$acl_state/chezmoi/acl" ||
    fail 'ACL snapshot did not capture the managed path'

  truncate_acl_state=$test_root/truncate-acl-state
  mkdir -m 700 -p "$truncate_acl_state/chezmoi/acl"
  if HOME=$acl_home XDG_STATE_HOME=$truncate_acl_state \
    PATH="$acl_bin:/usr/bin:/bin" \
    /bin/sh "$repo_root/home/run_before_save-acl.sh" \
    >"$test_root/truncate-acl.out" 2>"$test_root/truncate-acl.err"; then
    fail 'ACL save masked a state-file truncation failure'
  fi

  missing_acl_bin=$test_root/missing-acl-bin
  missing_acl_home=$test_root/missing-acl-home
  missing_acl_state=$test_root/missing-acl-state
  mkdir -m 700 "$missing_acl_bin" "$missing_acl_home"
  print -r -- '#!/bin/sh
printf "Linux\n"' >"$missing_acl_bin/uname"
  chmod 700 "$missing_acl_bin/uname"
  if HOME=$missing_acl_home XDG_STATE_HOME=$missing_acl_state PATH=$missing_acl_bin \
    /bin/sh "$repo_root/home/run_before_save-acl.sh" \
    >"$test_root/missing-acl.out" 2>"$test_root/missing-acl.err"; then
    fail 'ACL save accepted missing Linux ACL primitives'
  fi
  grep -Fq 'getfacl is unavailable' "$test_root/missing-acl.err" ||
    fail 'ACL save did not report the missing getfacl primitive'

  failed_acl_bin=$test_root/failed-acl-bin
  failed_acl_home=$test_root/failed-acl-home
  failed_acl_state=$test_root/failed-acl-state
  mkdir -m 700 "$failed_acl_bin" "$failed_acl_home"
  print -r -- managed >"$failed_acl_home/managed"
  print -r -- '#!/bin/sh
printf "managed\n"' >"$failed_acl_bin/chezmoi"
  print -r -- '#!/bin/sh
exit 42' >"$failed_acl_bin/getfacl"
  chmod 700 "$failed_acl_bin/chezmoi" "$failed_acl_bin/getfacl"
  if HOME=$failed_acl_home XDG_STATE_HOME=$failed_acl_state \
    PATH="$failed_acl_bin:/usr/bin:/bin" \
    /bin/sh "$repo_root/home/run_before_save-acl.sh" \
    >"$test_root/failed-acl.out" 2>"$test_root/failed-acl.err"; then
    fail 'ACL save masked a per-path getfacl failure'
  fi
  grep -Fq 'failed to capture ACL for managed' "$test_root/failed-acl.err" ||
    fail 'ACL save did not report the per-path capture failure'

  metadata_acl_bin=$test_root/metadata-acl-bin
  metadata_acl_home=$test_root/metadata-acl-home
  metadata_acl_state=$test_root/metadata-acl-state
  mkdir -m 700 "$metadata_acl_bin" "$metadata_acl_home"
  print -r -- managed >"$metadata_acl_home/managed"
  print -r -- '#!/bin/sh
printf "managed\n"' >"$metadata_acl_bin/chezmoi"
  print -r -- '#!/bin/sh
cat <<EOF
# file: managed
# owner: unexpected-owner
# group: unexpected-group
# flags: s--
user::rw-
user:12345:r--
group::---
mask::r--
other::---
EOF' >"$metadata_acl_bin/getfacl"
  chmod 700 "$metadata_acl_bin/chezmoi" "$metadata_acl_bin/getfacl"
  HOME=$metadata_acl_home XDG_STATE_HOME=$metadata_acl_state \
    PATH="$metadata_acl_bin:/usr/bin:/bin" \
    /bin/sh "$repo_root/home/run_before_save-acl.sh"
  metadata_acl=$metadata_acl_state/chezmoi/acl
  ! grep -Eq '^# (owner|group):' "$metadata_acl" ||
    fail 'ACL snapshot retained ownership metadata'
  grep -Fqx '# flags: s--' "$metadata_acl" ||
    fail 'ACL snapshot discarded special mode metadata'

  HOME=$acl_home XDG_STATE_HOME=$acl_state SETFACL_ARGS=$test_root/setfacl.args \
    PATH="$acl_bin:/usr/bin:/bin" \
    /bin/sh "$repo_root/home/run_after_restore-acl.sh"
  [[ ! -e $acl_state/chezmoi/acl ]] ||
    fail 'ACL snapshot was not removed after restoration'
  [[ $(stat -c '%a' -- "$acl_home/managed") == 640 ]] ||
    fail 'ACL restoration did not preserve the managed mode'
  grep -Fqx -- '-P' "$test_root/setfacl.args" ||
    fail 'ACL restoration did not disable symlink traversal'
fi

print -r -- 'platform portability: PASS'
