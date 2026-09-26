#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
cd "$repo_root"

# exit, not return: errexit inside a function skips zsh's EXIT trap.
fail() {
  print -u2 -r -- "$1"
  exit 1
}

test_dir=$(mktemp -d "${TMPDIR:-/tmp}/identity-bindings.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT

# zsh skips EXIT traps when errexit fires inside a function.
TRAPZERR() {
  if [[ -o errexit ]] && (( ${#funcstack} > 1 )); then
    rm -rf -- "$test_dir"
  fi
}
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

git_defaults_rule=home/dot_claude/rules/private_git-defaults.md.tmpl
work_rule=$test_dir/git-defaults-work
chezmoi -S "$repo_root/home" execute-template --override-data "$fixture_data" \
  < "$git_defaults_rule" > "$work_rule"
rg -F 'prefix new branches with `developer/`' "$work_rule" >/dev/null ||
  fail 'Git defaults rule did not select the synthetic host branch prefix'
rg -F 'developer@example.invalid' "$work_rule" >/dev/null ||
  fail 'Git defaults rule did not select the synthetic host email'
! rg -F 'nisavid' "$work_rule" >/dev/null ||
  fail 'Git defaults rule states personal defaults on a non-default identity'

personal_rule=$test_dir/git-defaults-personal
unbound_data=$(print -r -- "$fixture_data" |
  sed 's/"hostname": "fixture-workstation"/"hostname": "unbound-host"/')
chezmoi -S "$repo_root/home" execute-template --override-data "$unbound_data" \
  < "$git_defaults_rule" > "$personal_rule"
rg -F 'prefix new branches with `nisavid/`' "$personal_rule" >/dev/null ||
  fail 'Git defaults rule did not select the default identity on an unbound host'
rg -F 'make GitHub mutations through `nisavid`' "$personal_rule" >/dev/null ||
  fail 'Git defaults rule did not name the default GitHub account'

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
