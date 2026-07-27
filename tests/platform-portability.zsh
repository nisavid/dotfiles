#!/usr/bin/env zsh
emulate -L zsh
setopt errexit nounset pipefail

repo_root=${0:A:h:h}
ignore_template=$repo_root***REMOVED***
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

chezmoi -S "$repo_root/home" execute-template \
  --override-data '{"chezmoi":{"os":"linux"}}' \
  <"$ignore_template" >"$test_root/linux-ignore"
chezmoi -S "$repo_root/home" execute-template \
  --override-data '{"chezmoi":{"os":"darwin"}}' \
  <"$ignore_template" >"$test_root/darwin-ignore"

typeset -a linux_only_entries=(
  '.agents/skills/hindsight-memory-import'
  '.agents/skills/hindsight-memory-onboarding'
  '.agents/skills/hindsight-memory-runtime'
  '.config/hindsight-control-plane'
  '.docker'
  '.hindsight'
  '.local/bin/hindsight-embed-service'
  '.local/bin/hindsight-embed-supervisor'
  '.local/bin/hindsight-harness-reconcile'
  '.local/bin/hindsight-harness-session'
  '.local/bin/hindsight-memory'
  '.local/lib/hindsight-runtime'
  '.local/libexec/nisavid'
  'Library/LaunchAgents/io.nisavid.zsh-gui-path.plist'
)

for entry in $linux_only_entries; do
  assert_line "$entry" "$test_root/linux-ignore"
  ! grep -Fqx -- "$entry" "$test_root/darwin-ignore" ||
    fail "Darwin unexpectedly ignores $entry"
done

typeset -a hindsight_sources=(
  "$repo_root"***REMOVED***/skills/*hindsight*
  "$repo_root"***REMOVED***/private_hindsight-control-plane
  "$repo_root"***REMOVED***
  "$repo_root"***REMOVED***/bin/*hindsight*
  "$repo_root"***REMOVED***/lib/hindsight-runtime
)

for source_path in $hindsight_sources; do
  [[ -e $source_path ]] ||
    fail "Hindsight source inventory contains a missing path: $source_path"
  target=$(chezmoi -S "$repo_root/home" target-path --source-path "$source_path")
  relative=${target#"$HOME/"}
  case $relative in
    .agents/skills/hindsight-* | \
      .config/hindsight-control-plane | .config/hindsight-control-plane/* | \
      .hindsight | .hindsight/* | \
      .local/bin/hindsight-* | \
      .local/lib/hindsight-runtime | .local/lib/hindsight-runtime/*)
      ;;
    *) fail "ungated Hindsight target: $relative" ;;
  esac
done

fixture_source=$test_root/source
fixture_home=$test_root/home
fixture_config=$test_root/chezmoi.toml
mkdir -p \
  "$fixture_source/dot_config/private_hindsight-control-plane" \
  "$fixture_source/private_dot_docker" \
  "$fixture_source/private_dot_hindsight" \
  "$fixture_source/private_dot_local/bin" \
  "$fixture_home"
cp "$test_root/linux-ignore" "$fixture_source/.chezmoiignore"
touch \
  "$fixture_source/dot_config/private_hindsight-control-plane/private_installation.json" \
  "$fixture_source/private_dot_docker/private_config.json" \
  "$fixture_source/private_dot_hindsight/private_cursor-upstream-settings.json" \
  "$fixture_source/private_dot_local/bin/executable_hindsight-memory"
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
exit 0' >"$acl_bin/chezmoi"
  chmod 700 "$acl_bin/chezmoi"
  HOME=$acl_home XDG_STATE_HOME=$acl_state \
    PATH="$acl_bin:/usr/bin:/bin" \
    /bin/sh "$repo_root***REMOVED***"
  [[ $(stat -c '%a' -- "$acl_state/chezmoi") == 700 ]] ||
    fail 'ACL state directory is not mode 0700'
  [[ $(stat -c '%a' -- "$acl_state/chezmoi/acl") == 600 ]] ||
    fail 'ACL snapshot is not mode 0600'
  HOME=$acl_home XDG_STATE_HOME=$acl_state \
    PATH="$acl_bin:/usr/bin:/bin" \
    /bin/sh "$repo_root***REMOVED***"
  [[ ! -e $acl_state/chezmoi/acl ]] ||
    fail 'ACL snapshot was not removed after restoration'
fi

print -r -- 'platform portability: PASS'
