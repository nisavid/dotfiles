#!/usr/bin/env zsh
emulate -L zsh
setopt errexit nounset pipefail

repo_root=${0:A:h:h}
hook=$repo_root***REMOVED***
test_root=$(mktemp -d "${TMPDIR:-/tmp}/claude-skill-sync.XXXXXX")
trap 'rm -rf -- "$test_root"' EXIT HUP INT TERM

fail() {
  print -ru2 -- "FAIL: $*"
  return 1
}

assert_skill_link() {
  local name=$1
  local link=$test_root***REMOVED***/skills/$name

  [[ -L $link ]] || fail "$name is not linked into Claude"
  [[ $(readlink "$link") == "../../.agents/skills/$name" ]] ||
    fail "$name has an unexpected link target: $(readlink "$link")"
}

home=$test_root/home
agent_skills=$home/.agents/skills
claude_skills=$home/.claude/skills
mkdir -p \
  "$agent_skills/developing-shell-scripts" \
  "$agent_skills/new-skill" \
  "$agent_skills/skill with spaces" \
  "$claude_skills/nested"

ln -s ../../.agents/skills/developing-shell-scripts \
  "$claude_skills/developing-shell-scripts"
print -r -- preserved >"$claude_skills/new-skill"
ln -s ../../.agents/skills/retired-skill "$claude_skills/retired-skill"
ln -s /missing/claude-specific-skill "$claude_skills/claude-specific-skill"
ln -s ../../../../.agents/skills/retired-nested "$claude_skills/nested/retired-nested"

HOME=$home zsh -f "$hook"

[[ ! -L $claude_skills/retired-skill ]] ||
  fail 'top-level broken link was not removed'
[[ -L $claude_skills/claude-specific-skill ]] ||
  fail 'an unrelated top-level Claude link was removed'
[[ -L $claude_skills/nested/retired-nested ]] ||
  fail 'a nested Claude-specific link was removed'
[[ $(<$claude_skills/new-skill) == preserved ]] ||
  fail 'an existing Claude skill was overwritten'
assert_skill_link developing-shell-scripts
assert_skill_link 'skill with spaces'

HOME=$home zsh -f "$hook"
assert_skill_link developing-shell-scripts
assert_skill_link 'skill with spaces'

print -r -- 'Claude skill sync: PASS'
