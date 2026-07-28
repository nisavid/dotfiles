#!/usr/bin/env zsh
emulate -L zsh
setopt errexit nounset pipefail

repo_root=${0:A:h:h}
ignore_template=$repo_root***REMOVED***
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
  '.local/libexec/*/zsh-gui-path'
  'Library/LaunchAgents/*zsh-gui-path*'
)

for pattern in $linux_only_patterns; do
  assert_line "$pattern" "$test_root/linux-ignore"
  ! grep -Fqx -- "$pattern" "$test_root/darwin-ignore" ||
    fail "Darwin unexpectedly ignores $pattern"
done

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
    /bin/sh "$repo_root***REMOVED***"
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
    /bin/sh "$repo_root***REMOVED***" \
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
    /bin/sh "$repo_root***REMOVED***" \
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
    /bin/sh "$repo_root***REMOVED***" \
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
    /bin/sh "$repo_root***REMOVED***"
  metadata_acl=$metadata_acl_state/chezmoi/acl
  ! grep -Eq '^# (owner|group):' "$metadata_acl" ||
    fail 'ACL snapshot retained ownership metadata'
  grep -Fqx '# flags: s--' "$metadata_acl" ||
    fail 'ACL snapshot discarded special mode metadata'

  HOME=$acl_home XDG_STATE_HOME=$acl_state SETFACL_ARGS=$test_root/setfacl.args \
    PATH="$acl_bin:/usr/bin:/bin" \
    /bin/sh "$repo_root***REMOVED***"
  [[ ! -e $acl_state/chezmoi/acl ]] ||
    fail 'ACL snapshot was not removed after restoration'
  [[ $(stat -c '%a' -- "$acl_home/managed") == 640 ]] ||
    fail 'ACL restoration did not preserve the managed mode'
  grep -Fqx -- '-P' "$test_root/setfacl.args" ||
    fail 'ACL restoration did not disable symlink traversal'
fi

print -r -- 'platform portability: PASS'
