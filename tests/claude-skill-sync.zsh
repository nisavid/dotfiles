#!/usr/bin/env zsh
emulate -L zsh
setopt errexit nounset pipefail

repo_root=${0:A:h:h}
hook=$repo_root/home/run_after_sync-global-agent-skills-to-claude.zsh
test_root=$(mktemp -d "${TMPDIR:-/tmp}/claude-skill-sync.XXXXXX")
trap 'rm -rf -- "$test_root"' EXIT HUP INT TERM

fail() {
  print -ru2 -- "FAIL: $*"
  return 1
}

assert_skill_link() {
  local name=$1
  local link=$test_root/home/.claude/skills/$name

  [[ -L $link ]] || fail "$name is not linked into Claude"
  [[ $(readlink "$link") == "../../.agents/skills/$name" ]] ||
    fail "$name has an unexpected link target: $(readlink "$link")"
}

assert_retired_skills_absent() {
  local name

  for name in $retired_skills; do
    [[ ! -e $claude_skills/$name && ! -L $claude_skills/$name ]] ||
      fail "retired $name skill was linked into Claude"
  done
}

home=$test_root/home
agent_skills=$home/.agents/skills
claude_skills=$home/.claude/skills
retired_skills=(
  dispatching-parallel-agents
  executing-plans
  finishing-a-development-branch
  subagent-driven-development
  test-driven-development
  writing-plans
  yeet
)
mkdir -p \
  "$agent_skills/developing-shell-scripts" \
  "$agent_skills/new-skill" \
  "$agent_skills/skill with spaces" \
  "$claude_skills/nested"
for name in $retired_skills; do
  mkdir -p "$agent_skills/$name"
done

ln -s ../../.agents/skills/developing-shell-scripts \
  "$claude_skills/developing-shell-scripts"
for name in $retired_skills; do
  ln -s "../../.agents/skills/$name" "$claude_skills/$name"
done
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
assert_retired_skills_absent

HOME=$home zsh -f "$hook"
assert_skill_link developing-shell-scripts
assert_skill_link 'skill with spaces'
assert_retired_skills_absent

print -r -- 'Claude skill sync: PASS'
