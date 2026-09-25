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
    "destDir": "'"${fixture_home}"'",
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
git config --file "$git_config" --list >/dev/null ||
  fail 'Rendered Git config does not parse'
[[ $(git config --file "$git_config" filter.lfs.required) == true ]] ||
  fail 'Git config does not require the LFS filter'
[[ -z $(git config --file "$git_config" --default '' coderabbit.machineId) ]] ||
  fail 'Git config invented a CodeRabbit machine ID'

deployed_git_config=$fixture_home/.config/git/config
mkdir -p -- "${deployed_git_config:h}"
print -r -- $'[coderabbit]\n\tmachineId = cli/fixture-id' > "$deployed_git_config"
chezmoi -S "$repo_root/home" execute-template --override-data "$fixture_data" \
  < home/dot_config/git/config.tmpl > "$git_config"
[[ $(git config --file "$git_config" coderabbit.machineId) == cli/fixture-id ]] ||
  fail 'Git config dropped the deployed CodeRabbit machine ID'
print -r -- $'[coderabbit]\n\tmachineId = "fixture id"' > "$deployed_git_config"
if chezmoi -S "$repo_root/home" execute-template --override-data "$fixture_data" \
  < home/dot_config/git/config.tmpl >/dev/null 2>&1; then
  fail 'Git config accepted a malformed CodeRabbit machine ID'
fi
rm -- "$deployed_git_config"

chezmoi_bin=$(command -v chezmoi)
helper_bin=$test_dir/helper-bin
mkdir -p -- "$helper_bin" "$test_dir/no-helper-bin"
# lookPath returns a cleaned path, and macOS's TMPDIR ends in a slash.
helper_bin=${helper_bin:A}
for helper in glab git-credential-oauth; do
  print -r -- '#!/bin/sh' > "$helper_bin/$helper"
  chmod 755 "$helper_bin/$helper"
done
PATH=$helper_bin "$chezmoi_bin" -S "$repo_root/home" execute-template \
  --override-data "$fixture_data" < home/dot_config/git/config.tmpl > "$git_config"
[[ $(git config --file "$git_config" --get-all credential.https://gitlab.com.helper) == \
  $'\n!'"$helper_bin/glab auth git-credential" ]] ||
  fail 'Git config does not route gitlab.com credentials through glab'
[[ $(git config --file "$git_config" --get-all credential.https://codeberg.org.helper) == \
  $'\ncache --timeout 21600\noauth' ]] ||
  fail 'Git config does not route codeberg.org credentials through git-credential-oauth'
PATH=$test_dir/no-helper-bin "$chezmoi_bin" -S "$repo_root/home" execute-template \
  --override-data "$fixture_data" < home/dot_config/git/config.tmpl > "$git_config"
[[ -z $(git config --file "$git_config" --get-all credential.https://gitlab.com.helper) ]] ||
  fail 'Git config configured a gitlab.com helper without glab'
[[ -z $(git config --file "$git_config" --get-all credential.https://codeberg.org.helper) ]] ||
  fail 'Git config configured a codeberg.org helper without git-credential-oauth'

personal_include=$test_dir/personal-include
chezmoi -S "$repo_root/home" execute-template --override-data "$fixture_data" \
  < home/dot_config/git/personal.inc.tmpl > "$personal_include"
rg -F 'email = "ivan@nisavid.io"' "$personal_include" >/dev/null ||
  fail 'Personal Git include did not resolve the synthetic personal identity'

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
