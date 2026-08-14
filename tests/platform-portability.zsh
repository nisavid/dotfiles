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
! grep -Fq '    paths:' "$workflow" ||
  fail 'platform workflow does not run the privacy gate for every change'
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

age_boundary_workflow=$repo_root/.github/workflows/privacy-age-integrity.yml
grep -Fq '  pull_request_target:' "$age_boundary_workflow" ||
  fail 'age boundary does not execute from the trusted base event'
grep -Fq '          path: trusted-base' "$age_boundary_workflow" ||
  fail 'age boundary does not isolate the trusted base checkout'
grep -Fq '          path: untrusted-head' "$age_boundary_workflow" ||
  fail 'age boundary does not isolate the candidate data checkout'
grep -Fq 'python3 trusted-base/scripts/privacy_age_integrity_gate.py' \
  "$age_boundary_workflow" ||
  fail 'age boundary does not execute the trusted transition verifier'
grep -Fq 'python3 trusted-base/scripts/privacy-scan' "$age_boundary_workflow" ||
  fail 'age boundary does not execute the trusted privacy scanner'
! grep -Eq \
  '^[[:space:]]*(python[0-9.]*|bash|sh|zsh|ruby|perl|node|npm|npx|make)([[:space:]]|$).*untrusted-head/|^[[:space:]]*(\./)?untrusted-head/|^[[:space:]]*(uses|working-directory):[[:space:]]*(\./)?untrusted-head(/|$)' \
  "$age_boundary_workflow" ||
  fail 'age boundary executes candidate code'

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
    'private_Library/private_LaunchAgents/io.nisavid.zsh-gui-path.plist.tmpl' \
    'private_dot_local/libexec/nisavid/executable_zsh-gui-path.tmpl'
)
[[ $gui_source_inventory == $expected_gui_source_inventory ]] ||
  fail 'Darwin-only GUI source inventory changed without updating the Linux gate'

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
