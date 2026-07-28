#!/usr/bin/env zsh
set -euo pipefail

main() {
  emulate -L zsh
  setopt errexit nounset pipefail

  local agent_skills=${HOME:?HOME must be set}/.agents/skills
  local claude_skills=$HOME/.claude/skills
  local link skill skill_name
  local -a broken_links skills

  [[ -d $agent_skills ]] || {
    print -ru2 -- "global agent skills directory does not exist: $agent_skills"
    return 1
  }
  mkdir -p -- "$claude_skills"

  broken_links=("$claude_skills"/**/*(ND@))
  for link in $broken_links; do
    [[ -e $link ]] || rm -- "$link"
  done

  skills=("$agent_skills"/*(ND-/))
  for skill in $skills; do
    skill_name=${skill:t}
    link=$claude_skills/$skill_name
    [[ -e $link || -L $link ]] && continue
    ln -s -- "../../.agents/skills/$skill_name" "$link"
  done
}

main "$@"
