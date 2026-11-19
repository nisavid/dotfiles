#!/usr/bin/env zsh
emulate -L zsh
setopt errexit nounset pipefail

repo_root=${0:A:h:h}
hook=$repo_root/home/run_after_sync-global-agent-skills-to-claude.zsh
test_root=$(mktemp -d "${TMPDIR:-/tmp}/claude-skill-sync.XXXXXX")
trap 'rm -rf -- "$test_root"' EXIT HUP INT TERM

# zsh skips EXIT traps when errexit fires inside a function.
TRAPZERR() {
  if [[ -o errexit ]] && (( ZSH_SUBSHELL == 0 && ${#funcstack} > 1 )); then
    rm -rf -- "$test_root"
  fi
}

# exit, not return: errexit inside a function skips zsh's EXIT trap.
fail() {
  print -ru2 -- "FAIL: $*"
  exit 1
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

assert_plugin_skills_absent() {
  local name

  for name in $plugin_skills; do
    [[ ! -e $claude_skills/$name && ! -L $claude_skills/$name ]] ||
      fail "plugin-provided $name skill was linked into Claude"
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
  using-serena-projects
  writing-plans
  yeet
)
plugin_skills=(
  ask-matt code-review codebase-design diagnosing-bugs domain-modeling
  grill-me grill-with-docs grilling handoff implement
  improve-codebase-architecture prototype research setup-matt-pocock-skills
  tdd teach to-questionnaire to-spec to-tickets triage wait-what wayfinder
  wizard writing-for-agents
)
mkdir -p \
  "$agent_skills/developing-shell-scripts" \
  "$agent_skills/new-skill" \
  "$agent_skills/skill with spaces" \
  "$claude_skills/nested"
for name in $retired_skills $plugin_skills; do
  mkdir -p "$agent_skills/$name"
done

ln -s ../../.agents/skills/developing-shell-scripts \
  "$claude_skills/developing-shell-scripts"
for name in $retired_skills; do
  ln -s "../../.agents/skills/$name" "$claude_skills/$name"
done
for name in $plugin_skills; do
  ln -s "../../.agents/skills/$name" "$claude_skills/$name"
done
# Same-name entries that are not links to the shared root stay in place.
rm -- "$claude_skills/wayfinder" "$claude_skills/tdd"
mkdir -p "$claude_skills/wayfinder"
print -r -- own >"$claude_skills/wayfinder/SKILL.md"
ln -s /elsewhere/tdd "$claude_skills/tdd"
print -r -- preserved >"$claude_skills/new-skill"
ln -s ../../.agents/skills/retired-skill "$claude_skills/retired-skill"
ln -s /missing/claude-specific-skill "$claude_skills/claude-specific-skill"
ln -s ../../../../.agents/skills/retired-nested "$claude_skills/nested/retired-nested"

HOME=$home zsh -f "$hook"

[[ ! -L $claude_skills/retired-skill ]] ||
  fail 'top-level broken link was not removed'
[[ -L $claude_skills/claude-specific-skill &&
  $(readlink "$claude_skills/claude-specific-skill") == /missing/claude-specific-skill ]] ||
  fail 'an unrelated top-level Claude link was removed or changed'
[[ -L $claude_skills/nested/retired-nested ]] ||
  fail 'a nested Claude-specific link was removed'
[[ $(<$claude_skills/new-skill) == preserved ]] ||
  fail 'an existing Claude skill was overwritten'
assert_skill_link developing-shell-scripts
assert_skill_link 'skill with spaces'
assert_retired_skills_absent
for name in $plugin_skills; do
  [[ $name == (wayfinder|tdd) ]] && continue
  [[ ! -e $claude_skills/$name && ! -L $claude_skills/$name ]] ||
    fail "plugin-provided $name link was not removed"
done
[[ -d $claude_skills/wayfinder && ! -L $claude_skills/wayfinder &&
  $(<$claude_skills/wayfinder/SKILL.md) == own ]] ||
  fail 'a non-link plugin-named entry was touched'
[[ -L $claude_skills/tdd && $(readlink "$claude_skills/tdd") == /elsewhere/tdd ]] ||
  fail 'a plugin-named link outside the shared root was touched'

HOME=$home zsh -f "$hook"
assert_skill_link developing-shell-scripts
assert_skill_link 'skill with spaces'
assert_retired_skills_absent

# Scratch home with no plugin-provided links: none are created, and a second
# run changes nothing.
snapshot() {
  local entry
  for entry in $1/*(ND); do
    if [[ -L $entry ]]; then
      print -r -- "${entry:t} link $(readlink "$entry")"
    elif [[ -d $entry ]]; then
      print -r -- "${entry:t} dir"
    else
      print -r -- "${entry:t} file"
    fi
  done
}
home2=$test_root/home2
mkdir -p "$home2/.agents/skills/developing-shell-scripts" "$home2/.claude/skills"
for name in $plugin_skills; do
  mkdir -p "$home2/.agents/skills/$name"
done
HOME=$home2 zsh -f "$hook"
for name in $plugin_skills; do
  [[ ! -e $home2/.claude/skills/$name && ! -L $home2/.claude/skills/$name ]] ||
    fail "plugin-provided $name was created in a clean home"
done
[[ -L $home2/.claude/skills/developing-shell-scripts ]] ||
  fail 'a regular shared skill was not linked in the clean home'
before=$(snapshot "$home2/.claude/skills")
HOME=$home2 zsh -f "$hook"
[[ $(snapshot "$home2/.claude/skills") == $before ]] ||
  fail 'a second run changed the clean home'

print -r -- 'Claude skill sync: PASS'
