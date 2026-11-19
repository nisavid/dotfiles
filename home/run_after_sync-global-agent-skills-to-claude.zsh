#!/usr/bin/env zsh
set -euo pipefail

main() {
  emulate -L zsh
  setopt errexit nounset pipefail

  local agent_skills=${HOME:?HOME must be set}/.agents/skills
  local claude_skills=$HOME/.claude/skills
  local link skill skill_name
  local -a broken_links skills

  is_retired_skill() {
    case $1 in
    dispatching-parallel-agents | executing-plans | finishing-a-development-branch | \
      subagent-driven-development | test-driven-development | using-serena-projects | \
      writing-plans | yeet)
      return 0
      ;;
    esac
    return 1
  }

  # Names that a selected Claude plugin provides. A user skill shadows the
  # plugin's skill of the same name, so these are never projected into Claude.
  # Keep this separate from the retired-skill list above.
  is_plugin_provided_skill() {
    case $1 in
    ask-matt | code-review | codebase-design | diagnosing-bugs | domain-modeling | \
      grill-me | grill-with-docs | grilling | handoff | implement | \
      improve-codebase-architecture | prototype | research | \
      setup-matt-pocock-skills | tdd | teach | to-questionnaire | to-spec | \
      to-tickets | triage | wait-what | wayfinder | wizard | writing-for-agents)
      return 0
      ;;
    esac
    return 1
  }

  [[ -d $agent_skills ]] || {
    print -ru2 -- "global agent skills directory does not exist: $agent_skills"
    return 1
  }
  mkdir -p -- "$claude_skills"

  broken_links=("$claude_skills"/*(ND@))
  for link in $broken_links; do
    skill_name=${link:t}
    [[ $(readlink "$link") == "../../.agents/skills/$skill_name" ]] || continue
    if is_retired_skill "$skill_name" || is_plugin_provided_skill "$skill_name"; then
      rm -- "$link"
      continue
    fi
    [[ -e $link ]] && continue
    rm -- "$link"
  done

  skills=("$agent_skills"/*(ND-/))
  for skill in $skills; do
    skill_name=${skill:t}
    is_retired_skill "$skill_name" && continue
    is_plugin_provided_skill "$skill_name" && continue
    link=$claude_skills/$skill_name
    [[ -e $link || -L $link ]] && continue
    ln -s -- "../../.agents/skills/$skill_name" "$link"
  done
}

main "$@"
