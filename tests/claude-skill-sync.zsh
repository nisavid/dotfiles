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
# Names provided by the MCP apps plugin (#480). The Firecrawl skills are not
# plugin-provided for this sync: Claude loads them from the shared root.
extra_plugin_skills=(
  add-app-to-server convert-web-app create-mcp-app migrate-oai-app
)
plugin_skills+=($extra_plugin_skills)
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
rm -- "$claude_skills/wayfinder" "$claude_skills/tdd" \
  "$claude_skills/add-app-to-server" "$claude_skills/create-mcp-app"
mkdir -p "$claude_skills/add-app-to-server"
print -r -- own >"$claude_skills/add-app-to-server/SKILL.md"
ln -s /elsewhere/create-mcp-app "$claude_skills/create-mcp-app"
mkdir -p "$claude_skills/wayfinder"
print -r -- own >"$claude_skills/wayfinder/SKILL.md"
ln -s /elsewhere/tdd "$claude_skills/tdd"
print -r -- preserved >"$claude_skills/new-skill"
# A Firecrawl skill linked from the shared root is not plugin-provided.
mkdir -p "$agent_skills/firecrawl-scrape"
ln -s ../../.agents/skills/firecrawl-scrape "$claude_skills/firecrawl-scrape"
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
  [[ $name == (wayfinder|tdd|add-app-to-server|create-mcp-app) ]] && continue
  [[ ! -e $claude_skills/$name && ! -L $claude_skills/$name ]] ||
    fail "plugin-provided $name link was not removed"
done
[[ -d $claude_skills/wayfinder && ! -L $claude_skills/wayfinder &&
  $(<$claude_skills/wayfinder/SKILL.md) == own ]] ||
  fail 'a non-link plugin-named entry was touched'
[[ -L $claude_skills/tdd && $(readlink "$claude_skills/tdd") == /elsewhere/tdd ]] ||
  fail 'a plugin-named link outside the shared root was touched'
[[ -d $claude_skills/add-app-to-server && ! -L $claude_skills/add-app-to-server &&
  $(<$claude_skills/add-app-to-server/SKILL.md) == own ]] ||
  fail 'a non-link entry named like an MCP apps skill was touched'
[[ -L $claude_skills/firecrawl-scrape &&
  $(readlink "$claude_skills/firecrawl-scrape") == ../../.agents/skills/firecrawl-scrape ]] ||
  fail 'a Firecrawl skill link into the shared root was removed or changed'
[[ -L $claude_skills/create-mcp-app &&
  $(readlink "$claude_skills/create-mcp-app") == /elsewhere/create-mcp-app ]] ||
  fail 'an MCP apps-named link outside the shared root was touched'

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
mkdir -p "$home2/.agents/skills/developing-shell-scripts" \
  "$home2/.agents/skills/firecrawl-scrape" "$home2/.claude/skills"
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
[[ -L $home2/.claude/skills/firecrawl-scrape &&
  $(readlink "$home2/.claude/skills/firecrawl-scrape") == ../../.agents/skills/firecrawl-scrape ]] ||
  fail 'a Firecrawl skill was not projected like a regular shared skill'
before=$(snapshot "$home2/.claude/skills")
HOME=$home2 zsh -f "$hook"
[[ $(snapshot "$home2/.claude/skills") == $before ]] ||
  fail 'a second run changed the clean home'

# Absolute links into the shared root are sync-owned too: removed for plugin
# and retired names, left alone for ordinary skills, and links elsewhere or
# real directories of the same name are never touched.
home3=$test_root/home3
agent3=$home3/.agents/skills
claude3=$home3/.claude/skills
mkdir -p "$agent3/developing-shell-scripts" "$agent3/code-review" \
  "$agent3/yeet" "$agent3/wayfinder" "$agent3/tdd" "$claude3/wayfinder"
print -r -- own >"$claude3/wayfinder/SKILL.md"
ln -s "$agent3/code-review" "$claude3/code-review"
ln -s "$agent3/yeet" "$claude3/yeet"
ln -s "$agent3/developing-shell-scripts" "$claude3/developing-shell-scripts"
ln -s /elsewhere/tdd "$claude3/tdd"
for name in $extra_plugin_skills; do
  mkdir -p "$agent3/$name"
  ln -s "$agent3/$name" "$claude3/$name"
done
HOME=$home3 zsh -f "$hook"
for name in $extra_plugin_skills; do
  [[ ! -e $claude3/$name && ! -L $claude3/$name ]] ||
    fail "an absolute shared-root link for plugin-provided $name was kept"
  [[ -d $agent3/$name ]] || fail "shared copy of $name was removed"
done
[[ ! -e $claude3/code-review && ! -L $claude3/code-review ]] ||
  fail 'an absolute shared-root link for a plugin-provided name was kept or recreated'
[[ ! -e $claude3/yeet && ! -L $claude3/yeet ]] ||
  fail 'an absolute shared-root link for a retired name was kept'
[[ -d $claude3/wayfinder && ! -L $claude3/wayfinder &&
  $(<$claude3/wayfinder/SKILL.md) == own ]] ||
  fail 'a same-name real directory was touched'
[[ -L $claude3/tdd && $(readlink "$claude3/tdd") == /elsewhere/tdd ]] ||
  fail 'a link outside the shared root was touched'
[[ -L $claude3/developing-shell-scripts &&
  $(readlink "$claude3/developing-shell-scripts") == "$agent3/developing-shell-scripts" ]] ||
  fail 'an existing absolute shared-root link to a regular skill was rewritten'

print -r -- 'Claude skill sync: PASS'
