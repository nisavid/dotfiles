#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
source_root="$repo_root/home"
template="$source_root/dot_codex/private_AGENTS.md.tmpl"
encryption_doc="$repo_root/docs/ENCRYPTION.md"
rendered=$(mktemp "${TMPDIR:-/tmp}/global-agents-policy.XXXXXX")
target_state=$(mktemp "${TMPDIR:-/tmp}/global-agents-state.XXXXXX")
chmod 600 "$rendered"
chmod 600 "$target_state"
trap 'rm -f "$rendered" "$target_state"' EXIT

fail() {
  print -u2 -- "global AGENTS policy: $1"
  exit 1
}

[[ -f "$template" ]] || fail "private source template is missing"
[[ ! -e "$source_root/dot_codex/AGENTS.md.tmpl" ]] || fail "public-mode source template still exists"
[[ $(stat -f '%Lp' "$template") == 644 ]] || fail "source template mode must be 0644"
[[ $(chezmoi target-path "$template") == "$HOME/.codex/AGENTS.md" ]] || fail "source template targets the wrong file"

chezmoi dump --format json "$HOME/.codex/AGENTS.md" > "$target_state"
[[ $(jq -r '.[".codex/AGENTS.md"].perm' "$target_state") == 384 ]] || fail "target mode is not 0600"

(
  cd "$source_root"
  chezmoi execute-template < "$template" > "$rendered"
)
[[ $(stat -f '%Lp' "$rendered") == 600 ]] || fail "rendered test artifact must be 0600"

required=(
  '## Git Checkpoints And Publication'
  'Treat commits and pushes as normal completion steps for task-owned changes, not optional extras.'
  'an explicit request to commit is not required.'
  'Before responding at a stopping point, inspect Git status, the complete unpublished commit range, and upstream state.'
  'Push only when every unpublished commit is task-owned or explicitly authorized and no other gate remains.'
  'Explicitly classified local-only paths require no further ownership question'
  'unrelated dirt does not block a safely separable task commit; never include unrelated changes.'
  'When no upstream exists, set the unambiguous default remote and same-name branch as upstream.'
  'Direct default-branch pushes are allowed when repository policy and remote protections permit them.'
  'use `--force-with-lease` when the reconciled history requires it, never unconditional force.'
  'This policy authorizes lease-protected rewrites, including on a default branch'
  'an unresolved authentication identity or permission are gates.'
  'Do not guess through an unresolved push destination, identity, permission, or remote-preservation gate'
  'operator owns the checklist and the active task authorizes changing the issue, pull request, or comment'
  'active task authorizes thread resolution'
  'Resolve a Systalyze pull request review thread only when the active task authorizes thread resolution, addressed evidence is present'
  'thread author login exactly matches the selected and verified GitHub login'
  'If no GitHub login is selected, resolve no threads.'
  "Limit debloating to the current task's behavioral surface."
  'use `working-in-systalyze-worktrees`'
  'Set the Kubernetes context explicitly for every command.'
  'Set a namespace only for namespaced resources.'
  'Confirm the exact resource and its cluster scope before mutating a cluster-scoped resource.'
  'Every Kubernetes mutation requires authorization and a post-change check.'
  'Do not persistently change the current context merely to run a command.'
  'Use `context7-mcp`'
  'Send only the minimum public query needed'
  'Use internal documentation only through a local, internal-only fallback.'
  'Use `using-serena-projects`'
  'Keep one to three captures as discrete files.'
  'Present four or more captures as a local site-shaped collection.'
  'Publication requires separate authorization.'
  'use `publishing-systalyze-sites`'
  'Only refresh local `main` when the operation depends on it.'
)

for ((i = 1; i <= ${#required}; i++)); do
  grep -Fq -- "$required[$i]" "$rendered" || fail "missing required clause $i"
done

development_line=$(grep -n '^## Development Work$' "$rendered" | cut -d: -f1)
git_policy_line=$(grep -n '^## Git Checkpoints And Publication$' "$rendered" | cut -d: -f1)
writing_line=$(grep -n '^## Writing$' "$rendered" | cut -d: -f1)
[[ -n $development_line && -n $git_policy_line && -n $writing_line ]] || fail 'required policy sections are missing'
((development_line < git_policy_line && git_policy_line < writing_line)) || \
  fail 'Git checkpoint policy is not immediately after Development Work'
next_heading=$(awk '$0 == "## Development Work" { found = 1; next } found && /^## / { print; exit }' "$rendered")
[[ $next_heading == '## Git Checkpoints And Publication' ]] || \
  fail 'another section appears between Development Work and the Git checkpoint policy'

forbidden=(
  'ivan/impeccable'
  'ivan/setup-local'
  'ivan/local-runtime-policy-docs'
  'ivan/real-work-for-local-dev'
  'ivan/ceres-dev-cluster-program'
  'dev:env:fnx:handoff'
  'yarn prisma:generate'
  'make -C packages/fnx test'
  'packages/systalyze-py'
  'packages/dnn_model_images'
  'Always start with `resolve-library-id`'
  "user's full question"
)

for phrase in $forbidden; do
  ! grep -Fq -- "$phrase" "$rendered" || fail "contains stale or unsafe policy"
done

! grep -Eq '/Users/[^ )]+/(skills/[^ )]+/)?SKILL\.md' "$template" || \
  fail "public template contains a machine-local skill link"
! grep -Eq '/Users/[^ )]+/(skills/[^ )]+/)?SKILL\.md' "$rendered" || \
  fail "rendered policy contains a machine-local skill link"

docs_required=(
  '.private-skill-NN-path.age' \
  '.private-skill-NN-body.age' \
  'transaction phase' \
  '~/.agents/skills/<path>' \
  'Installs and verifies every supplied skill and symlink pair.' \
  'Removed pairs are not pruned automatically.' \
  'pending transaction rolls back' \
  'completed transaction verifies'
)

for ((i = 1; i <= ${#docs_required}; i++)); do
  grep -Fq -- "$docs_required[$i]" "$encryption_doc" || fail "encryption documentation is missing clause $i"
done

! grep -Fq -- 'Installs the complete skill and symlink set' "$encryption_doc" || \
  fail "encryption documentation claims authoritative complete-set installation"

print -- 'global AGENTS policy: ok'
