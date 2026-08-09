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
  assert_contains "$skill" 'any Git-backed change and safe task completion' 'Git publication trigger must cover broad Git-backed task completion'
  assert_contains "$skill" 'implement a change in a repository and commit clean checkpoints' 'Git publication trigger must cover repository implementation and checkpoints'
  assert_contains "$skill" 'review a branch or repository for bugs, including review-only work' 'Git publication trigger must cover repository-backed non-mutating review work'
  assert_contains "$skill" 'push and verify a remote branch' 'Git publication trigger must cover publication and remote verification'
  assert_contains "$skill" 'reconcile with an exact lease' 'Git publication trigger must cover reconciliation and exact leases'
  assert_contains "$skill" 'If a repository task says "In Codex" or "In Claude Code," apply in either harness' 'Git publication trigger must ignore harness-name phrasing'
  assert_contains "$skill" 'Do not use for Git explanations or pasted summaries without repository action' 'Git publication trigger must exclude explanation-only requests'
  assert_contains "$skill" 'completion choices, and provenance-aware cleanup' 'Git publication trigger must own the consolidated completion workflow'
  assert_contains "$skill" 'publishing non-task work' 'Git publication trigger must name the ownership failure mode'

  [[ -f $metadata ]] || fail 'missing generated Git publication interface metadata'
  assert_contains "$metadata" 'display_name: "Checkpoint, Publish, and Finish Git Work"' 'Git publication display name is stale'
  assert_contains "$metadata" 'short_description: "Commit, publish, and finish Git work safely"' 'Git publication short description is stale'
  assert_contains "$metadata" 'default_prompt: "Use $checkpointing-and-publishing-git-work to checkpoint, publish, and finish the current Git task safely."' 'Git publication default prompt is stale'

  [[ -f $skill_dir/scripts/plan_git_publication.py ]] || fail 'missing Git publication planner'
  [[ -f $skill_dir/scripts/check_eval_gate.py ]] || fail 'missing Git publication evaluation gate'
  [[ -f $skill_dir/evals/evals.json ]] || fail 'missing Git publication behavior evals'
  [[ -f $skill_dir/evals/trigger-evals.json ]] || fail 'missing Git publication trigger evals'
  (( $(find $skill_dir/evals/fixtures -type f -name '*.md' | wc -l | tr -d ' ') >= 8 )) ||
    fail 'Git publication eval fixtures do not cover the required behavior groups'
  assert_symlink_source "$link" '../../.agents/skills/checkpointing-and-publishing-git-work'
  assert_contains "$skill" 'sole local owner of Git baseline capture' 'Git publication skill must own baseline capture'
  assert_contains "$skill" 'Review-only tasks never mutate or publish' 'Git publication skill must preserve review-only behavior'
  assert_contains "$skill" 'git --literal-pathspecs commit --only -- <owned paths>' 'Git publication skill must require literal task-only commits'
  assert_contains "$skill" 'When step 6 returns `ready`, capture and review that plan as the publication baseline' 'Git publication skill must capture the direct-ready comparison baseline'
  assert_contains "$skill" 'If step 7 reconciliation is required, establish or replace the baseline only after the affected gates pass and the planner returns a new `ready` plan' 'Git publication skill must replace the baseline after reconciliation'
  assert_contains "$skill" 'Immediately before every push, rerun the planner and require the entire rerun plan to match the reviewed `ready` baseline' 'Git publication skill must bind the immediate rerun to the reviewed ready plan'
  assert_contains "$skill" '`source_sha`, destination, lease, refspec, `destination.config_digest`, and `destination.endpoint_fingerprint`' 'Git publication skill must bind every immutable push identity field'
  assert_contains "$skill" 'Never remove a SHA listed in `target_only_shas` unless that exact SHA appears in `removal_authorized_commits`' 'Git publication skill must require exact target-only removal authorization'
  assert_contains "$skill" "If missing removal authorization is the sole gate, preserve the planner's \`needs_reconciliation\` status" 'Git publication skill must preserve the canonical missing-authorization state'
  assert_contains "$skill" 'if another gate also remains, require `blocked`' 'Git publication skill must preserve the canonical combined-gate state'
  assert_contains "$skill" 'When all target-only SHAs are authorized and no other gate remains, the planner may return `ready`' 'Git publication skill must preserve the canonical authorized-rewrite state'
  assert_contains "$skill" 'Remote-ref deletion is outside this skill and planner' 'Git publication skill must reject remote-ref deletion'
  assert_contains "$skill" 'separately authorized branch-deletion workflow' 'Git publication skill must route branch deletion to its owning workflow'
  assert_contains "$skill" 'one explicit nonempty `<source_sha>:<full-ref>` branch-update refspec' 'Git publication skill must require one nonempty-source branch-update refspec'
  assert_contains "$skill" 'Never use a deletion refspec such as `:<full-ref>`' 'Git publication skill must reject deletion refspecs'
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
  assert_contains "$skill" 'Do not present a completion menu when the operator already chose the outcome' 'Git publication skill must avoid redundant completion menus'
  assert_contains "$skill" 'branch while a PR is active or review feedback remains' 'Git publication skill must preserve active PR workspaces'
  assert_contains "$skill" 'path-name heuristic is insufficient' 'Git publication skill must classify worktree provenance from evidence'
  assert_contains "$skill" 'native cleanup actuator' 'Git publication skill must route harness cleanup through the harness'
  assert_contains "$skill" 'user-created, externally managed, or unknown-provenance worktree' 'Git publication skill must preserve external worktrees'
  assert_contains "$skill" 'verification on the merged result' 'Git publication skill must verify integration before cleanup'
  assert_contains "$skill" 'type exactly `discard`' 'Git publication skill must require typed discard confirmation'
  assert_contains "$skill" 'Never run global `git worktree prune`' 'Git publication cleanup must not prune unrelated registrations'
  assert_contains "$skill" 'check out the verified safe base before deleting the normal-checkout branch' 'Normal-checkout cleanup must leave the target branch before deletion'
  assert_contains "$skill" '`git worktree remove --force` only after exact discard confirmation covered' 'Forced worktree removal must require exact discard authority over dirt'
  assert_contains "$skill" 'If an action is not target-local' 'Non-target-local cleanup must preserve and report the remaining state'
  assert_contains "$repo_dir/home/dot_codex/modify_private_config.toml.tmpl" '"yeet"' 'Codex config must disable every installed yeet copy'
  assert_contains "$repo_dir/home/dot_codex/modify_private_config.toml.tmpl" '"finishing-a-development-branch"' 'Codex config must disable every installed finishing copy'
  assert_contains "$repo_dir/home/dot_codex/modify_private_config.toml.tmpl" 'plugin_root.glob(f"*/*/*/skills/{skill}/SKILL.md")' 'Codex config must discover every plugin provenance and version dynamically'
  for retired in \
    dispatching-parallel-agents executing-plans finishing-a-development-branch \
    subagent-driven-development test-driven-development writing-plans yeet; do
    assert_contains "$repo_dir/home/.chezmoiremove" ".claude/skills/$retired" "Claude must not discover retired $retired"
  done
  assert_contains "$skill" 'only the raw prompt and fixture' 'Git publication eval instructions must prevent answer leakage'

  python3 -m unittest discover -s "$skill_dir/tests" -p 'test_*.py'
}

test_pr_publication() {
  local publisher="$repo_dir/home/dot_agents/skills/publishing-reviewable-prs/SKILL.md"
  local graphite="$repo_dir/home/dot_agents/skills/graphite/SKILL.md"
  local atlas="$repo_dir/home/dot_agents/skills/writing-reviewable-pr-descriptions/review-atlas-reference-design.md"

  assert_symlink_source \
    "$repo_dir/home/dot_claude/skills/symlink_publishing-reviewable-prs" \
    '../../.agents/skills/publishing-reviewable-prs'
  assert_symlink_source \
    "$repo_dir/home/dot_claude/skills/symlink_graphite" \
    '../../.agents/skills/graphite'
  assert_contains "$graphite" 'gt submit --stack --draft --no-edit --no-ai --no-interactive' 'Graphite submission must produce untouched drafts'
  assert_contains "$graphite" 'Keep newly created or' 'Graphite publication must preserve new draft state'
  assert_contains "$graphite" 'already-draft PRs draft during inspection.' 'Graphite publication must inspect canonical drafts before readiness'
  assert_contains "$graphite" "Preserve an existing ready PR's" 'Graphite publication must preserve existing ready state'
  assert_contains "$graphite" 'state unless the task explicitly changes it' 'Graphite ready-state changes must require task authority'
  assert_contains "$graphite" 'guarded `ready` helper' 'Graphite readiness must use the guarded publisher'
  assert_contains "$publisher" 'validates the current body, then reruns the exact identity, title/body digest, and draft-state preflight immediately before the mutation' 'Ready publication must bind validation to an immediate exact preflight'
  assert_contains "$atlas" '## Contents' 'Atlas reference must have a linked table of contents'
  assert_contains "$atlas" 'expected title and title digest' 'Atlas publication must bind expected titles'
  assert_contains "$atlas" 'Final verification re-reads every title and body' 'Atlas final verification must verify titles and bodies'

  python3 "$repo_dir/tests/test_publish_reviewable_pr.py"
  python3 "$repo_dir/tests/test_modify_private_config.py"
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
  pr-publication)
    test_pr_publication
    dry_targets=(
      "$HOME/.claude/skills/publishing-reviewable-prs"
      "$HOME/.claude/skills/graphite"
    )
    ;;
  all)
    test_context7
    test_serena
    test_git_publication
    test_pr_publication
    dry_targets=(
      "$HOME/.claude/skills/context7-mcp"
      "$HOME/.claude/skills/using-serena-projects"
      "$HOME/.agents/skills/checkpointing-and-publishing-git-work"
      "$HOME/.claude/skills/checkpointing-and-publishing-git-work"
      "$HOME/.claude/skills/publishing-reviewable-prs"
      "$HOME/.claude/skills/graphite"
    )
    ;;
  *)
    fail 'usage: public-agent-skills.zsh [context7|serena|git-publication|pr-publication|all]'
    ;;
esac

tmpdir="$(mktemp -d)"
trap 'rm -rf -- "$tmpdir"' EXIT
isolated_source="$tmpdir/source"
isolated_home="$tmpdir/home"
mkdir -p -- "$isolated_source/dot_agents/skills" "$isolated_source/dot_claude/skills" "$isolated_home"

for skill in \
  checkpointing-and-publishing-git-work context7-mcp graphite \
  publishing-reviewable-prs using-serena-projects; do
  cp -R -- \
    "$repo_dir/home/dot_agents/skills/$skill" \
    "$isolated_source/dot_agents/skills/$skill"
done

for link in \
  checkpointing-and-publishing-git-work context7-mcp graphite \
  publishing-reviewable-prs using-serena-projects; do
  cp -- \
    "$repo_dir/home/dot_claude/skills/symlink_$link" \
    "$isolated_source/dot_claude/skills/symlink_$link"
done

typeset -a isolated_targets
for target in $dry_targets; do
  isolated_targets+=("$isolated_home/${target#$HOME/}")
done

chezmoi --source "$isolated_source" --destination "$isolated_home" \
  apply --dry-run --verbose $isolated_targets
