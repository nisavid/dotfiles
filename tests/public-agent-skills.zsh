#!/usr/bin/env zsh
set -euo pipefail

repo_dir="${0:A:h:h}"

fail() {
  print -ru2 -- "$1"
  exit 1
}

assert_contains() {
  local file="$1"
  local text="$2"
  local message="$3"

  rg -F -q -- "$text" "$file" || fail "$message"
}

assert_skill_frontmatter() {
  local file="$1"
  local name="$2"
  local description

  [[ -f "$file" ]] || fail "missing skill: $file"
  [[ "$(sed -n '1p' "$file")" == '---' ]] || fail "$name frontmatter must start with ---"
  assert_contains "$file" "name: $name" "$name must declare its exact name"
  description="$(sed -n '3s/^description: //p' "$file")"
  [[ "$description" == 'Use when '* ]] || fail "$name description must use third-person 'Use when...' trigger wording"
  [[ "$(sed -n '4p' "$file")" == '---' ]] || fail "$name frontmatter must end with ---"
}

assert_symlink_source() {
  local source="$1"
  local target="$2"

  [[ -f "$source" && ! -L "$source" ]] || fail "$source must be a regular chezmoi symlink source file"
  [[ "$(wc -l < "$source" | tr -d ' ')" == 1 ]] || fail "$source must contain exactly one newline-terminated line"
  [[ "$(<"$source")" == "$target" ]] || fail "$source must contain exactly $target"
}

test_context7() {
  local skill="$repo_dir/home/dot_agents/skills/context7-mcp/SKILL.md"
  local link="$repo_dir/home/dot_claude/skills/symlink_context7-mcp"
  local resolve_line query_line

  assert_skill_frontmatter "$skill" context7-mcp
  assert_contains "$skill" 'resolve-library-id' 'Context7 must resolve the library ID first'
  assert_contains "$skill" 'query-docs' 'Context7 must query current docs after resolution'
  resolve_line="$(rg -n -m1 'resolve-library-id' "$skill" | cut -d: -f1)"
  query_line="$(rg -n -m1 'query-docs' "$skill" | cut -d: -f1)"
  (( resolve_line < query_line )) || fail 'resolve-library-id must precede query-docs'

  assert_contains "$skill" 'minimum public technical question' 'Context7 queries must be minimized'
  assert_contains "$skill" 'proprietary identifiers' 'Context7 must prohibit proprietary identifiers'
  assert_contains "$skill" 'internal package or service names' 'Context7 must prohibit internal package and service names'
  assert_contains "$skill" 'customer or incident data' 'Context7 must prohibit customer and incident data'
  assert_contains "$skill" 'credentials' 'Context7 must prohibit credentials'
  assert_contains "$skill" 'code' 'Context7 must prohibit code disclosure'
  assert_contains "$skill" 'machine-local paths' 'Context7 must prohibit machine-local paths'
  assert_contains "$skill" 'internal-only libraries' 'Context7 must define an internal-only library path'
  assert_contains "$skill" 'local source and documentation' 'Internal-only libraries must use local evidence'
  assert_contains "$skill" 'Do not call Context7 or web search' 'Internal-only libraries must not reach external services'
  assert_contains "$skill" 'request authority before disclosing anything' 'Insufficient local evidence must require disclosure authority'
  assert_symlink_source "$link" '../../.agents/skills/context7-mcp'
}

test_serena() {
  local skill="$repo_dir/home/dot_agents/skills/using-serena-projects/SKILL.md"
  local link="$repo_dir/home/dot_claude/skills/symlink_using-serena-projects"

  assert_skill_frontmatter "$skill" using-serena-projects
  assert_contains "$skill" 'setup, initialization, repair, or use' 'Serena trigger must cover its full lifecycle'
  assert_contains "$skill" 'committed `.serena/project.yml`' 'Serena must prefer committed shared configuration'
  assert_contains "$skill" 'ignored `.serena/project.local.yml`' 'Serena must prefer ignored local configuration'
  assert_contains "$skill" 'Inspect and preserve existing configuration' 'Serena must preserve existing configuration'
  assert_contains "$skill" 'Infer languages from project manifests' 'Serena must infer languages from manifests'
  assert_contains "$skill" 'in-repo agent worktrees' 'Serena must ignore in-repo agent worktrees'
  assert_contains "$skill" 'external sibling worktrees' 'Serena must ignore sibling worktrees'
  assert_contains "$skill" 'dependency directories' 'Serena must ignore dependencies'
  assert_contains "$skill" 'caches' 'Serena must ignore caches'
  assert_contains "$skill" 'generated environments' 'Serena must ignore generated environments'
  assert_contains "$skill" 'Serena runtime state' 'Serena must ignore runtime state'
  assert_contains "$skill" 'nested Git repositories and submodules as separate Serena projects' 'Nested repositories must remain separate projects'
  assert_contains "$skill" 'Never add sibling worktrees as additional workspace folders' 'Sibling worktrees must not share a Serena project'
  assert_contains "$skill" 'unique local `project_name`' 'Each worktree must have a unique local project name'
  assert_contains "$skill" 'Do not guess unsupported Serena configuration keys' 'Unsupported Serena keys must not be guessed'
  assert_contains "$skill" 'Do not overwrite repository-owned setup' 'Repository-owned setup must not be overwritten'
  assert_contains "$skill" 'surface the missing schema or tooling context' 'Missing Serena context must be surfaced'
  assert_symlink_source "$link" '../../.agents/skills/using-serena-projects'
}

test_git_publication() {
  local skill_dir="$repo_dir/home/dot_agents/skills/checkpointing-and-publishing-git-work"
  local skill="$skill_dir/SKILL.md"
  local metadata="$skill_dir/agents/openai.yaml"
  local link="$repo_dir/home/dot_claude/skills/symlink_checkpointing-and-publishing-git-work"
  local workflow_start push_line verify_line plan_publish_line step_nine

  assert_skill_frontmatter "$skill" checkpointing-and-publishing-git-work
  assert_contains "$skill" 'starting any Git-backed implementation or review task' 'Git publication trigger must cover task start'
  assert_contains "$skill" 'clean checkpoint, stopping point, commit, push, branch integration, and closeout' 'Git publication trigger must cover its full lifecycle'
  assert_contains "$skill" 'finishing-a-development-branch' 'Git publication skill must name the overlapping managed skill'
  assert_contains "$skill" 'conflicting completion menus or force rules' 'Git publication trigger must name the conflicting-rule failure mode'
  assert_contains "$skill" 'accidental publication of non-task work' 'Git publication trigger must name the ownership failure mode'

  [[ -f $metadata ]] || fail 'missing generated Git publication interface metadata'
  assert_contains "$metadata" 'display_name: "Checkpoint and Publish Git Work"' 'Git publication display name is stale'
  assert_contains "$metadata" 'short_description: "Commit and publish task-owned Git work safely"' 'Git publication short description is stale'
  assert_contains "$metadata" 'default_prompt: "Use $checkpointing-and-publishing-git-work to checkpoint and publish the current Git task safely."' 'Git publication default prompt is stale'

  [[ -f $skill_dir/scripts/plan_git_publication.py ]] || fail 'missing Git publication planner'
  [[ -f $skill_dir/scripts/check_eval_gate.py ]] || fail 'missing Git publication evaluation gate'
  [[ -f $skill_dir/evals/evals.json ]] || fail 'missing Git publication behavior evals'
  [[ -f $skill_dir/evals/trigger-evals.json ]] || fail 'missing Git publication trigger evals'
  (( $(find $skill_dir/evals/fixtures -type f -name '*.md' | wc -l | tr -d ' ') >= 8 )) ||
    fail 'Git publication eval fixtures do not cover the required behavior groups'
  assert_contains "$skill_dir/evals/trigger-evals.json" 'In Codex' 'trigger evals must include a Codex runner case'
  assert_contains "$skill_dir/evals/trigger-evals.json" 'In Claude Code' 'trigger evals must include a Claude runner case'

  assert_symlink_source "$link" '../../.agents/skills/checkpointing-and-publishing-git-work'
  assert_contains "$skill" 'sole local owner of Git baseline capture' 'Git publication skill must own baseline capture'
  assert_contains "$skill" 'Review-only tasks never mutate or publish' 'Git publication skill must preserve review-only behavior'
  assert_contains "$skill" 'git --literal-pathspecs commit --only -- <owned paths>' 'Git publication skill must require literal task-only commits'
  assert_contains "$skill" 'three unchanged bindings: the plan, configuration digest, and endpoint digest' 'Git publication skill must bind the immediate pre-push plan'
  assert_contains "$skill" 'one full heads refspec' 'Git publication skill must require one full heads refspec'
  assert_contains "$skill" 'exact existing or absent lease' 'Git publication skill must require an exact CAS lease'
  assert_contains "$skill" 'submodule mode `check`' 'Git publication skill must require submodule check mode'
  workflow_start="$(rg -n -m1 '^## Follow The Checkpoint Workflow$' "$skill" | cut -d: -f1)"
  push_line="$(rg -n -m1 '^8\. Execute the exact CAS push\.$' "$skill" | cut -d: -f1)"
  verify_line="$(rg -n -m1 '^9\. ' "$skill" | cut -d: -f1)"
  plan_publish_line="$(rg -n -m1 '^## Plan And Publish$' "$skill" | cut -d: -f1)"
  step_nine="$(sed -n "${verify_line}p" "$skill")"
  [[ "$step_nine" == *'Post-verify'* && "$step_nine" == *'exact push endpoint'* &&
    "$step_nine" == *'full destination ref'* && "$step_nine" == *'terminal `verified` plan'* ]] ||
    fail 'Git publication workflow step 9 must name exact post-push identity verification'
  (( workflow_start < push_line && push_line < verify_line && verify_line < plan_publish_line )) ||
    fail 'Git publication post-push verification must follow the CAS push before Plan And Publish'
  assert_contains "$skill" 'terminal `verified` plan' 'Git publication skill must end on verified remote state'
  assert_contains "$skill" 'Never offer detached discard' 'Git publication skill must prohibit detached discard'
  assert_contains "$skill" 'only the raw prompt and fixture' 'Git publication eval instructions must prevent answer leakage'

  python3 -m unittest discover -s "$skill_dir/tests" -p 'test_*.py'
}

typeset -a dry_targets

case "${1:-all}" in
  context7)
    test_context7
    dry_targets=("$HOME/.claude/skills/context7-mcp")
    ;;
  serena)
    test_serena
    dry_targets=("$HOME/.claude/skills/using-serena-projects")
    ;;
  git-publication)
    test_git_publication
    dry_targets=(
      "$HOME/.agents/skills/checkpointing-and-publishing-git-work"
      "$HOME/.claude/skills/checkpointing-and-publishing-git-work"
    )
    ;;
  all)
    test_context7
    test_serena
    test_git_publication
    dry_targets=(
      "$HOME/.claude/skills/context7-mcp"
      "$HOME/.claude/skills/using-serena-projects"
      "$HOME/.agents/skills/checkpointing-and-publishing-git-work"
      "$HOME/.claude/skills/checkpointing-and-publishing-git-work"
    )
    ;;
  *)
    fail 'usage: public-agent-skills.zsh [context7|serena|git-publication|all]'
    ;;
esac

chezmoi apply --dry-run --verbose $dry_targets
