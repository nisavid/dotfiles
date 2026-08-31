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

  [[ -f "$file" ]] || fail "missing skill: $file"
  awk -v expected_name="$name" '
    NR == 1 {
      if ($0 != "---") exit 1
      next
    }
    $0 == "---" {
      closed = 1
      exit
    }
    $0 == "name: " expected_name {
      named = 1
    }
    /^description: Use when / {
      triggered = 1
    }
    /^description: (>|\|)[+-]?$/ {
      description_block = 1
      next
    }
    description_block && /^  Use when / {
      triggered = 1
    }
    END {
      if (!closed || !named || !triggered) exit 1
    }
  ' "$file" || fail "$name must have closed frontmatter, its exact name, and a 'Use when...' description"
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

test_skill_creator_adapter() {
  local adapter_dir="$repo_dir/home/dot_agents/skills/adapting-skill-creator-to-harnesses"

  python3 -m unittest discover -s "$adapter_dir/tests" -p 'test_*.py'
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
  local writer="$repo_dir/home/dot_agents/skills/writing-reviewable-pr-descriptions/SKILL.md"
  local graphite="$repo_dir/home/dot_agents/skills/graphite/SKILL.md"
  local atlas="$repo_dir/home/dot_agents/skills/writing-reviewable-pr-descriptions/review-atlas-reference-design.md"

  assert_skill_frontmatter "$publisher" publishing-reviewable-prs
  assert_skill_frontmatter "$writer" writing-reviewable-pr-descriptions
  [[ -f "${publisher:h}/evals/evals.json" ]] || fail 'missing PR publisher behavior evals'
  [[ -f "${publisher:h}/evals/trigger-evals.json" ]] || fail 'missing PR publisher trigger evals'
  [[ -f "${writer:h}/evals/evals.json" ]] || fail 'missing PR writer behavior evals'
  [[ -f "${writer:h}/evals/trigger-evals.json" ]] || fail 'missing PR writer trigger evals'

  assert_symlink_source \
    "$repo_dir/home/dot_claude/skills/symlink_publishing-reviewable-prs" \
    '../../.agents/skills/publishing-reviewable-prs'
  assert_symlink_source \
    "$repo_dir/home/dot_claude/skills/symlink_writing-reviewable-pr-descriptions" \
    '../../.agents/skills/writing-reviewable-pr-descriptions'
  assert_symlink_source \
    "$repo_dir/home/dot_claude/skills/symlink_graphite" \
    '../../.agents/skills/graphite'
  assert_contains "$graphite" 'gt submit --stack --draft --no-edit --no-ai --no-interactive' 'Graphite submission must produce untouched drafts'
  assert_contains "$graphite" 'Keep newly created or' 'Graphite publication must preserve new draft state'
  assert_contains "$graphite" 'already-draft PRs draft during inspection.' 'Graphite publication must inspect canonical drafts before readiness'
  assert_contains "$graphite" "Preserve an existing ready PR's" 'Graphite publication must preserve existing ready state'
  assert_contains "$graphite" 'state unless the task explicitly changes it' 'Graphite ready-state changes must require task authority'
  assert_contains "$graphite" 'guarded `ready` helper' 'Graphite readiness must use the guarded publisher'
  assert_contains "$atlas" '## Publication boundary' 'Atlas reference must define its publication boundary'
  assert_contains "$atlas" 'credentials, signed links, or authentication material' 'Atlas publication must exclude credentials and authentication material'
  assert_contains "$atlas" 'published assets contain no credentials or unnecessary source content' 'Atlas validation must enforce publication safety'

  assert_contains "$writer" 'a source newline in prose' 'PR writer must state that a comment field renders a prose newline as a break'
  assert_contains "$writer" 'one source line, however long it runs' 'PR writer must require one source line per block element'
  assert_contains "$writer" '.editorconfig' 'PR writer must name the repository column budget it must not follow'
  assert_contains "${writer:h}/references/body-contract.md" 'every intended break is an explicit `<br>`' 'PR body contract must require explicit break encoding'

  python3 -m unittest discover -s "${writer:h}/tests" -p 'test_*.py'
  python3 "$repo_dir/tests/test_publish_reviewable_pr.py"
  python3 "$repo_dir/tests/test_modify_private_config.py"
}

test_model_selection() {
  local skill_dir="$repo_dir/home/dot_agents/skills/choosing-agent-models"
  local skill="$skill_dir/SKILL.md"
  local delegation_skill_dir="$repo_dir/home/dot_agents/skills/delegating-cross-agent-work"
  local delegation_skill="$delegation_skill_dir/SKILL.md"
  local evals="$skill_dir/evals/evals.json"
  local routing_fixture="$skill_dir/evals/fixtures/daybreak-routing-matrix.md"
  local evidence_fixture="$skill_dir/evals/fixtures/daybreak-route-evidence.md"
  local transition_fixture="$skill_dir/evals/fixtures/model-transition-lifecycle.md"
  local trigger_evals="$skill_dir/evals/trigger-evals.json"
  local link="$repo_dir/home/dot_claude/skills/symlink_choosing-agent-models"
  local delegation_link="$repo_dir/home/dot_claude/skills/symlink_delegating-cross-agent-work"

  assert_skill_frontmatter "$skill" choosing-agent-models
  assert_skill_frontmatter "$delegation_skill" delegating-cross-agent-work
  assert_contains "$skill" '## Model Transition Authorization' \
    'model selection must own authorization for every payload-bearing transition'
  assert_contains "$skill" \
    'Before every payload-bearing new invocation, follow-up, same-task resume, retry, or capacity fallback' \
    'model selection must rerun across the complete invocation lifecycle'
  assert_contains "$skill" \
    'Capacity changes route availability only.' \
    'capacity failure must not lower the model-selection floor'
  assert_contains "$skill" \
    'Revalidating an existing task before a payload-bearing follow-up, resume, retry, or capacity fallback.' \
    'the selector trigger contract must include existing-task transitions'
  assert_contains "$skill" \
    "Re-read the exact selected invocation surface's current selector and capability state for every invalidated route tuple." \
    'every invalidated transition must resolve the exact current selector state'
  assert_contains "$skill" 'prior authorized selection' \
    'model selection must carry prior selection state across continuations'
  assert_contains "$skill" 'exact route tuple and current capability evidence' \
    'model selection must bind the exact current route tuple'
  assert_contains "$delegation_skill" '## Payload-Bearing Transition Gate' \
    'delegation must own the payload-bearing lifecycle gate'
  assert_contains "$delegation_skill" \
    'Before every payload-bearing new invocation, follow-up, resume, retry, or capacity fallback' \
    'delegation must invoke model selection for every payload-bearing transition'
  assert_contains "$delegation_skill" \
    'Keep a same-task continuation in the existing task' \
    'delegation must preserve same-task identity across continuation'
  assert_contains "$delegation_skill" 'prior authorized selection' \
    'delegation must carry prior selection state into the transition gate'
  assert_contains "$delegation_skill" \
    'Do not send task data until the transition is authorized.' \
    'delegation must fail closed before payload transfer'
  assert_contains "$skill" '## Daybreak Routing For Cybersecurity Work' \
    'model-selection skill must own the public Daybreak routing policy'
  assert_contains "$skill" \
    'Treat cybersecurity-related and cybersecurity-adjacent whole tasks and bounded subtasks as Daybreak-routed work.' \
    'Daybreak routing must apply to cybersecurity work and bounded subtasks'
  assert_contains "$skill" \
    'agents **must route cybersecurity-related or cybersecurity-adjacent work to a Daybreak model**' \
    'OpenAI-authenticated ChatGPT and Codex must route cybersecurity work to Daybreak when runnable'
  assert_contains "$skill" \
    'agents **should route that work to a Daybreak model**' \
    'other harnesses should route cybersecurity work to Daybreak when runnable'
  assert_contains "$skill" \
    'The Daybreak model executes the routed cybersecurity work rather than choosing a model for another agent.' \
    'Daybreak must execute the cybersecurity work rather than perform model selection'
  assert_contains "$skill" 'These rules do not govern unrelated work.' \
    'Daybreak routing must exclude unrelated work'
  assert_contains "$skill" 'Every harness must inventory cross-harness Codex invocation' \
    'every harness must consider cross-harness Daybreak routes'
  assert_contains "$skill" 'A route is one invocation surface' \
    'Daybreak routing must give each route one unambiguous invocation surface'
  assert_contains "$skill" 'Catalog entries are route inputs, not routes by themselves.' \
    'private account bindings must not be double-counted as invocation routes'
  assert_contains "$skill" 'one harmless probe containing no task data succeeds' \
    'a successful harmless probe must be part of runnable-route evidence'
  assert_contains "$skill" 'classify the route as unavailable without probing it' \
    'unauthorized task work must not be probed'
  assert_contains "$skill" 'no-task-data local status refresh' \
    'routing must distinguish a no-task-data local status refresh'
  assert_contains "$skill" 'local status probe used solely to refresh' \
    'refresh must be limited to local status facts'
  assert_contains "$skill" 'This status request is distinct from the separate harmless probe required after task-work authorization' \
    'status refresh must not be confused with the task-work probe'
  assert_contains "$skill" 'never satisfies or consumes the separate harmless-probe gate' \
    'status refresh must not satisfy or consume task-work probe evidence'
  assert_contains "$skill" 'run that refresh automatically for each permitted account route' \
    'fresh routing information must trigger automatic per-account refresh'
  assert_contains "$skill" 'the operator does not need to authorize it' \
    'local status refresh must not require operator task authorization'
  assert_contains "$skill" 'exact model exposed at that moment' \
    'refresh evidence must resolve the exact currently exposed model'
  assert_contains "$skill" 'exact currently exposed model' \
    'refresh must name the exact currently exposed model'
  assert_contains "$skill" 'timestamped, redacted result' \
    'refresh evidence must be timestamped and redacted'
  assert_contains "$skill" 'dated catalog observation is historical, not fresh by default' \
    'dated catalog observations must not be treated as current'
  assert_contains "$skill" 'declared freshness window' \
    'tuple reuse must have an explicit freshness window'
  assert_contains "$skill" 'Invalidate the observation' \
    'stale route observations must be invalidated explicitly'
  assert_contains "$skill" \
    'one no-task-data status refresh and one harmless task-work probe per exact tuple per freshness window' \
    'status refreshes and task-work probes must be separately bounded by the freshness window'
  assert_contains "$skill" 'data boundary, workspace, tool scope, or external-action scope changes' \
    'authorization and capability changes must invalidate observations'
  assert_contains "$skill" 'task-data transfer, task workspace or task-tool use, external actions, and actual delegated or executed task work separate' \
    'task-work authorization gates must remain separate from refresh'
  assert_contains "$skill" 'must not suppress the no-task-data local status refresh' \
    'task-work gates must not suppress local refresh'
  assert_contains "$skill" 'local/private operational state' \
    'local/private routing state must be an explicit classification boundary'
  assert_contains "$skill" 'account IDs and account-home identifiers' \
    'local/private state may use actionable account identifiers'
  assert_contains "$skill" 'safe stable local label or direct identifier' \
    'local/private status must have a safe actionable label'
  assert_contains "$skill" 'scrub account IDs, account-home identifiers, and stable per-account labels' \
    'external/public output must scrub account identifiers and labels'
  assert_contains "$skill" \
    'stable per-account labels, including derived home/path names' \
    'external/public output must scrub stable per-account labels'
  assert_contains "$skill" 'generic non-stable marker or redacted status' \
    'external/public output may retain only generic non-stable markers'
  assert_contains "$skill" 'Credentials, tokens, decrypted secrets, and unrelated task data remain prohibited' \
    'secret and task-data prohibitions must remain explicit'
  assert_contains "$skill" \
    'selector, authority, data-boundary, workspace, or tool-scope change creates a new tuple eligible for one new no-task-data status refresh and, separately, one new harmless task-work probe' \
    'authority and capability changes must separately permit a refresh and an authorized task-work probe'
  assert_contains "$skill" \
    'For Daybreak-routed work in ChatGPT or Codex with an OpenAI login' \
    'OpenAI local-fallback restrictions must be scoped to Daybreak-routed work'
  assert_contains "$skill" 'local non-Daybreak fall-through is forbidden' \
    'OpenAI-authenticated ChatGPT and Codex must reject local non-Daybreak fallback'
  assert_contains "$skill" 'model approval alone does not authorize delegation' \
    'operator model approval must not grant cross-harness delegation authority'
  assert_contains "$skill" \
    'For Daybreak-routed work in every other harness, including ChatGPT or Codex without an OpenAI login' \
    'other-harness fallback rules must be scoped to Daybreak-routed work'
  assert_contains "$skill" 'may also fall through locally' \
    'other harnesses must retain local next-best fallback'
  assert_contains "$skill" 'Before returning an executable cross-harness disposition' \
    'cross-harness delegation must require complete target authority'
  assert_contains "$skill" 'transfer no task data and return an approval-needed handoff' \
    'cross-harness task data must remain local until authority is complete'
  assert_contains "$skill" 'must create that dedicated task before the Daybreak work executes' \
    'root-only Daybreak work must execute in a dedicated peer or sibling task'
  assert_contains "$skill" 'a direct cross-harness session does not bypass this boundary' \
    'cross-harness invocation must preserve the root-only peer-task boundary'
  assert_contains "$skill" 'this skill does not perform those actions' \
    'model selection must return workflow dispositions without mutating tasks or trackers'
  assert_contains "$skill" \
    'During an already authorized no-task-data refresh, you may inspect route metadata exposed for unrelated tasks, including advertised model availability; this does not authorize reading task data.' \
    'route inspection must distinguish metadata observation from task-data access'
  assert_contains "$skill" \
    'An existing task is eligible only when delegation created it for the current source task and bounded purpose, or the operator identified it as a same-purpose companion.' \
    'existing-task eligibility must name delegation origin and operator identification'
  assert_contains "$skill" \
    'Do not use an unrelated task as an execution or authorization route for current-task work' \
    'unrelated tasks must remain ineligible execution and authorization routes'
  assert_contains "$delegation_skill" \
    'Do not message, fork from, steer, or execute current-task work through an unrelated task.' \
    'delegation policy must forbid acting through any unrelated task'
  assert_contains "$delegation_skill" \
    'Route-metadata inspection does not make that task eligible or authorize executing with its model or under its account, entitlement, permissions, or context.' \
    'delegation policy must mirror the unrelated-task execution boundary'
  ! rg -F -q -- 'reuse an unrelated task to obtain' "$skill" "$delegation_skill" || \
    fail 'unrelated-task policy must not use the ambiguous obtain wording'
  ! rg -F -q -- '.codex/.auth/' "$skill" || \
    fail 'public model-selection policy must not expose account-home locations'
  ! rg -F -q -- 'CODEX_HOME=' "$skill" || \
    fail 'public model-selection policy must not expose exact Codex account bindings'
  ! rg -F -q -- 'acct-synthetic-' "$skill" || \
    fail 'public model-selection policy must not expose synthetic account identifiers'

  [[ -f "$evals" ]] || fail 'model-selection behavior evals are missing'
  [[ -f "$trigger_evals" ]] || fail 'model-selection trigger evals are missing'
  python3 "$repo_dir/tests/test_model_transition_contract.py"
  jq -e '
    .skill_name == "choosing-agent-models" and
    all(.evals[]; (.fixture_paths | type) == "array" and (.fixture_paths | length) > 0) and
    all(.evals[]; .prompt | contains("Do not use tools"))
  ' "$evals" >/dev/null || fail 'model-selection behavior evals do not cover the Daybreak routing contract'
  for eval_name in daybreak-route-evidence daybreak-routing-matrix model-transition-lifecycle; do
    jq -e --arg name "$eval_name" 'any(.evals[]; .name == $name)' "$evals" >/dev/null || \
      fail "model-selection behavior eval is missing: $eval_name"
  done
  jq -e '
    any(.evals[];
      .name == "model-transition-lifecycle" and
      .expected_output == "Case A: fail closed, preserve the existing task, and do not invoke Terra. Case B: fail closed, preserve the existing task, and do not invoke Luna. Case C: continue the same task only on the freshly revalidated exact Daybreak route. Case D: continue the same task only after current exact-selector authorization for the explicit eligible operator choice. Case E: stop for an operator-policy conflict and do not invoke Terra. Case F: explicitly reclassify the current mechanical scope before selecting, then use only an eligible selection. Case G: preserve the prior classification and selection, then continue the same task only on a freshly authorized eligible fallback. Case H: apply the hardest security judgment as the floor before the follow-up."
    )
  ' "$evals" >/dev/null || \
    fail 'model-transition lifecycle eval does not bind every case to its fail-closed disposition'
  for expectation_id in \
    automatic-local-refresh cross-harness-delegation-authority external-scrub \
    freshness-invalidation local-account-identification refresh-probe-separation \
    openai-login-boundary \
    probe-authority-order root-peer-boundary unrelated-task-observation-boundary \
    every-payload-transition same-task-continuity prior-selection-state \
    capacity-preserves-floor \
    terra-luna-rejection sticky-operator-selection operator-policy-conflict \
    exact-selector-transition explicit-reclassification eligible-fallback \
    mixed-role-floor; do
    jq -e --arg id "$expectation_id" 'any(.evals[].expectations[]; .id == $id)' "$evals" >/dev/null || \
      fail "model-selection behavior expectation is missing: $expectation_id"
  done
  while IFS= read -r fixture; do
    [[ -f "$skill_dir/$fixture" ]] || fail "missing model-selection eval fixture: $fixture"
  done < <(jq -r '.evals[].fixture_paths[]' "$evals")
  assert_contains "$routing_fixture" '## Case H' \
    'model-selection fixture must cover the root-only peer boundary'
  assert_contains "$routing_fixture" 'does not authorize that account, workspace, tools, probe' \
    'model-selection fixture must cover authority-before-probe refusal'
  assert_contains "$routing_fixture" \
    'with an OpenAI login but configured for a non-OpenAI inference provider' \
    'model-selection fixture must separate login state from provider choice'
  assert_contains "$evidence_fixture" 'concrete entitlement change and a refreshed selector' \
    'route-evidence fixture must cover capability-state re-probing'
  assert_contains "$evidence_fixture" \
    "Gamma's task authority expands to include its account, data boundary, workspace, tools, and probe" \
    'route-evidence fixture must cover authority-state re-probing'
  assert_contains "$evidence_fixture" 'no-task-data local status refresh' \
    'route-evidence fixture must cover automatic local status refresh'
  assert_contains "$evidence_fixture" 'declared freshness window' \
    'route-evidence fixture must cover explicit observation freshness'
  assert_contains "$evidence_fixture" 'external report' \
    'route-evidence fixture must cover public scrubbing'
  assert_contains "$evidence_fixture" \
    'local account ID, account-home identifier, and stable private label' \
    'route-evidence fixture must classify local account identifiers without printing them'
  ! rg -F -q -- 'acct-synthetic-' "$evidence_fixture" || \
    fail 'public route-evidence fixture must not print account identifier forms'
  ! rg -F -q -- '/private/' "$evidence_fixture" || \
    fail 'public route-evidence fixture must not print account-home path forms'
  assert_contains "$evidence_fixture" 'stable private label' \
    'route-evidence fixture must classify the local label without printing it'
  assert_contains "$evidence_fixture" \
    'must scrub the local ID, home identifier, and stable label' \
    'route-evidence fixture must scrub stable labels externally'
  assert_contains "$evidence_fixture" \
    'generic non-stable marker' \
    'route-evidence fixture must name the safe external replacement'
  assert_contains "$evidence_fixture" \
    'both operations may occur once in the same freshness window' \
    'route-evidence fixture must separate refresh and task-work probe limits'
  assert_contains "$evidence_fixture" \
    'route metadata exposed for an unrelated existing task' \
    'route-evidence fixture must cover metadata observation without task reuse'
  assert_contains "$evidence_fixture" \
    "without reading that task's data" \
    'route-evidence fixture must deny task-data access during metadata observation'
  assert_contains "$evidence_fixture" \
    'not an execution or authorization route for the current work' \
    'route-evidence fixture must deny execution and authorization reuse'
  assert_contains "$routing_fixture" '## Case L' \
    'routing fixture must cover automatic no-task-data refresh'
  assert_contains "$routing_fixture" 'No task-work probe has run' \
    'routing fixture must distinguish status refresh from task-work probe'
  assert_contains "$routing_fixture" 'task-data transfer, task workspace or task-tool use' \
    'routing fixture must keep task-work authorization separate from refresh'
  assert_contains "$transition_fixture" 'proposes Terra High in the same task' \
    'transition fixture must cover the observed capacity-to-Terra trap'
  assert_contains "$transition_fixture" 'proposes Luna High in the same task' \
    'transition fixture must cover the equivalent capacity-to-Luna trap'
  assert_contains "$transition_fixture" \
    'Continue the work in the same task without creating a replacement claimant.' \
    'transition fixture must cover eligible same-task recovery'
  assert_contains "$transition_fixture" 'The operator now explicitly selects a different exact model' \
    'transition fixture must cover an explicit eligible operator override'
  assert_contains "$transition_fixture" \
    'operator instruction conflicts with the mandatory security route' \
    'transition fixture must cover an operator and security-policy conflict'
  assert_contains "$transition_fixture" 'A new current-scope record separates' \
    'transition fixture must require explicit reclassification'
  assert_contains "$transition_fixture" \
    'fallback that remains eligible for the preserved classification and authorized topology' \
    'transition fixture must distinguish eligible selection fallback from runtime failover'
  assert_contains "$transition_fixture" 'Carry its prior authorized selection into the new decision.' \
    'transition fixture must carry the prior selection into same-task recovery'
  assert_contains "$transition_fixture" 'Use the hardest required judgment as the selection floor.' \
    'transition fixture must cover mixed-role preservation'
  jq -e '
    (map(select(.should_trigger == true)) | length) >= 4 and
    (map(select(.should_trigger == false)) | length) >= 4
  ' "$trigger_evals" >/dev/null || fail 'model-selection trigger evals need positive and negative coverage'
  jq -e '
    any(.[];
      .should_trigger == true and
      (.query | contains("Resume this existing security task after capacity returns"))
    )
  ' "$trigger_evals" >/dev/null || fail 'model-selection trigger evals must cover same-task resume'
  jq -e '
    any(.[];
      .should_trigger == true and
      (.query | contains("operator explicitly changed the model"))
    )
  ' "$trigger_evals" >/dev/null || fail 'model-selection trigger evals must cover explicit operator transitions'

  assert_symlink_source "$link" '../../.agents/skills/choosing-agent-models'
  assert_symlink_source "$delegation_link" '../../.agents/skills/delegating-cross-agent-work'
}

typeset -a projection_targets

case "${1:-all}" in
  context7)
    test_context7
    projection_targets=(
      "$HOME/.agents/skills/context7-mcp"
      "$HOME/.claude/skills/context7-mcp"
    )
    ;;
  git-publication)
    test_skill_creator_adapter
    test_git_publication
    projection_targets=(
      "$HOME/.agents/skills/checkpointing-and-publishing-git-work"
      "$HOME/.claude/skills/checkpointing-and-publishing-git-work"
    )
    ;;
  pr-publication)
    test_pr_publication
    projection_targets=(
      "$HOME/.agents/skills/graphite"
      "$HOME/.agents/skills/publishing-reviewable-prs"
      "$HOME/.agents/skills/writing-reviewable-pr-descriptions"
      "$HOME/.claude/skills/publishing-reviewable-prs"
      "$HOME/.claude/skills/writing-reviewable-pr-descriptions"
      "$HOME/.claude/skills/graphite"
    )
    ;;
  model-selection)
    test_model_selection
    projection_targets=(
      "$HOME/.agents/skills/choosing-agent-models"
      "$HOME/.claude/skills/choosing-agent-models"
      "$HOME/.agents/skills/delegating-cross-agent-work"
      "$HOME/.claude/skills/delegating-cross-agent-work"
    )
    ;;
  all)
    test_context7
    test_skill_creator_adapter
    test_git_publication
    test_pr_publication
    test_model_selection
    projection_targets=(
      "$HOME/.agents/skills/context7-mcp"
      "$HOME/.claude/skills/context7-mcp"
      "$HOME/.agents/skills/checkpointing-and-publishing-git-work"
      "$HOME/.claude/skills/checkpointing-and-publishing-git-work"
      "$HOME/.agents/skills/graphite"
      "$HOME/.agents/skills/publishing-reviewable-prs"
      "$HOME/.agents/skills/writing-reviewable-pr-descriptions"
      "$HOME/.claude/skills/publishing-reviewable-prs"
      "$HOME/.claude/skills/writing-reviewable-pr-descriptions"
      "$HOME/.claude/skills/graphite"
      "$HOME/.agents/skills/choosing-agent-models"
      "$HOME/.claude/skills/choosing-agent-models"
      "$HOME/.agents/skills/delegating-cross-agent-work"
      "$HOME/.claude/skills/delegating-cross-agent-work"
    )
    ;;
  *)
    fail 'usage: public-agent-skills.zsh [context7|git-publication|pr-publication|model-selection|all]'
    ;;
esac

tmpdir="$(mktemp -d)"
trap 'rm -rf -- "$tmpdir"' EXIT
isolated_source="$tmpdir/source"
isolated_home="$tmpdir/home"
mkdir -p -- "$isolated_source/dot_agents/skills" "$isolated_source/dot_claude/skills" "$isolated_home"

for skill in \
  checkpointing-and-publishing-git-work context7-mcp graphite \
  publishing-reviewable-prs writing-reviewable-pr-descriptions \
  choosing-agent-models delegating-cross-agent-work; do
  cp -R -- \
    "$repo_dir/home/dot_agents/skills/$skill" \
    "$isolated_source/dot_agents/skills/$skill"
done

for link in \
  checkpointing-and-publishing-git-work context7-mcp graphite \
  publishing-reviewable-prs writing-reviewable-pr-descriptions \
  choosing-agent-models delegating-cross-agent-work; do
  cp -- \
    "$repo_dir/home/dot_claude/skills/symlink_$link" \
    "$isolated_source/dot_claude/skills/symlink_$link"
done

typeset -a isolated_targets
for target in $projection_targets; do
  isolated_targets+=("$isolated_home/${target#$HOME/}")
done

mkdir -p -- "$tmpdir/xdg-config" "$tmpdir/xdg-state" "$tmpdir/xdg-cache"
HOME="$isolated_home" \
  XDG_CONFIG_HOME="$tmpdir/xdg-config" \
  XDG_STATE_HOME="$tmpdir/xdg-state" \
  XDG_CACHE_HOME="$tmpdir/xdg-cache" \
  chezmoi --source "$isolated_source" --destination "$isolated_home" \
    apply --parent-dirs $isolated_targets

for target in $isolated_targets; do
  [[ -e "$target" || -L "$target" ]] || fail "isolated projection did not create $target"
done

for skill in \
  checkpointing-and-publishing-git-work context7-mcp graphite \
  publishing-reviewable-prs writing-reviewable-pr-descriptions \
  choosing-agent-models delegating-cross-agent-work; do
  canonical="$isolated_home/.agents/skills/$skill"
  link="$isolated_home/.claude/skills/$skill"
  if [[ -e "$canonical" || -e "$link" || -L "$link" ]]; then
    [[ -d "$canonical" ]] || fail "$canonical is not a projected skill directory"
    [[ -L "$link" ]] || fail "$link is not a projected symlink"
    [[ "${link:A}" == "${canonical:A}" ]] || fail "$link does not resolve to $canonical"
  fi
done
