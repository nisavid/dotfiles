#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
cd "$repo_root"

fail() {
  print -u2 -r -- "$1"
  return 1
}

test_dir=$(mktemp -d "${TMPDIR:-/tmp}/identity-bindings.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT
fixture_home=$test_dir/home
mkdir -p -- "$fixture_home/.config/zsh/zshrc.d"
fixture_home=${fixture_home:A}

fixture_data='{
  "chezmoi": {
    "os": "linux",
    "homeDir": "'"${fixture_home}"'",
    "hostname": "fixture-workstation"
  },
  "gitIdentity": {
    "publicFixture": true,
    "selection": {
      "default": "personal",
      "byHostname": {
        "fixture-workstation": "work"
      }
    },
    "identities": {
      "personal": {
        "email": "ivan@nisavid.io",
        "editorTarget": "cursor",
        "branchPrefix": "nisavid/",
        "noTracking": false
      },
      "work": {
        "email": "developer@example.invalid",
        "editorTarget": "code",
        "branchPrefix": "developer/",
        "noTracking": true
      }
    }
  }
}'

git_config=$test_dir/git-config
chezmoi -S "$repo_root/home" execute-template --override-data "$fixture_data" \
  < home/dot_config/git/config.tmpl > "$git_config"
rg -F 'email = developer@example.invalid' "$git_config" >/dev/null ||
  fail 'Git config did not select the synthetic host identity'

modifier=$test_dir/modify-codex
chezmoi -S "$repo_root/home" execute-template --override-data "$fixture_data" \
  < home/dot_codex/modify_private_config.toml.tmpl > "$modifier"
rg -F 'export EDITOR_TARGET="code"' "$modifier" >/dev/null ||
  fail 'Codex modifier did not select the synthetic editor target'
rg -F 'export GIT_BRANCH_PREFIX="developer/"' "$modifier" >/dev/null ||
  fail 'Codex modifier did not select the synthetic branch prefix'

no_tracking=$test_dir/configure-no-tracking
chezmoi -S "$repo_root/home" execute-template --override-data "$fixture_data" \
  < home/run_after_configure-zsh-no-tracking.zsh.tmpl > "$no_tracking"
zsh -n "$no_tracking"
print -r -- '# fixture' > "$fixture_home/.config/zsh/zshrc.d/no-tracking.zsh"
zsh "$no_tracking"
[[ -L $fixture_home/.config/zsh/zshrc.d/no-tracking.local.zsh ]] ||
  fail 'No-tracking hook did not enable the synthetic work policy'

! rg -n \
  'defaultByHostname|defaultByIdentity' \
  home/.chezmoidata/git-identity.toml \
  home/.chezmoidata/editor-target.toml \
  home/dot_config/git/config.tmpl \
  home/dot_codex/modify_private_config.toml.tmpl \
  home/run_after_configure-zsh-no-tracking.zsh.tmpl >/dev/null ||
  fail 'Public identity binding sources expose private selection data'

print -r -- 'identity binding checks passed'
