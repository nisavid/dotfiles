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

case "${1:-all}" in
  context7)
    test_context7
    ;;
  serena)
    test_serena
    ;;
  all)
    test_context7
    test_serena
    ;;
  *)
    fail 'usage: public-agent-skills.zsh [context7|serena|all]'
    ;;
esac

chezmoi apply --dry-run --verbose \
  "$HOME/.claude/skills/context7-mcp" \
  "$HOME/.claude/skills/using-serena-projects"
