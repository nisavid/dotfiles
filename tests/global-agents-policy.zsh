#!/usr/bin/env zsh
set -euo pipefail
umask 022

repo_root=${0:A:h:h}
source_root="$repo_root/home"
template="$source_root/dot_codex/private_AGENTS.md.tmpl"
preflight_partial_name=ticket-tracker-preflight.tmpl
preflight_partial="$source_root/.chezmoitemplates/$preflight_partial_name"
claude_rule_template="$source_root/dot_claude/rules/ticket-tracker-preflight.md.tmpl"
identity_partial_name=git-identity-defaults.tmpl
identity_partial="$source_root/.chezmoitemplates/$identity_partial_name"
checkpoint_partial_name=git-checkpointing.tmpl
checkpoint_partial="$source_root/.chezmoitemplates/$checkpoint_partial_name"
claude_git_rule_template="$source_root/dot_claude/rules/git-defaults.md.tmpl"
encryption_doc="$repo_root/docs/ENCRYPTION.md"
rendered=$(mktemp "${TMPDIR:-/tmp}/global-agents-policy.XXXXXX")
target_state=$(mktemp "${TMPDIR:-/tmp}/global-agents-state.XXXXXX")
git_policy=$(mktemp "${TMPDIR:-/tmp}/global-agents-git-policy.XXXXXX")
pr_policy=$(mktemp "${TMPDIR:-/tmp}/global-agents-pr-policy.XXXXXX")
claude_rule=$(mktemp "${TMPDIR:-/tmp}/global-agents-claude-rule.XXXXXX")
claude_state=$(mktemp "${TMPDIR:-/tmp}/global-agents-claude-state.XXXXXX")
claude_git_rule=$(mktemp "${TMPDIR:-/tmp}/global-agents-claude-git-rule.XXXXXX")
identity_policy=$(mktemp "${TMPDIR:-/tmp}/global-agents-identity-policy.XXXXXX")
render_source_root=$source_root
render_template=$template
render_claude_rule_template=$claude_rule_template
render_claude_git_rule_template=$claude_git_rule_template
render_fixture=
chmod 600 "$rendered"
chmod 600 "$target_state"
chmod 600 "$git_policy"
chmod 600 "$pr_policy"
trap 'rm -f "$rendered" "$target_state" "$git_policy" "$pr_policy" "$claude_rule" "$claude_state" "$claude_git_rule" "$identity_policy"; [[ -z $render_fixture ]] || rm -rf "$render_fixture"' EXIT

fail() {
  print -u2 -- "global AGENTS policy: $1"
  exit 1
}

mode_of() {
  case "$(uname -s)" in
    Darwin) stat -f '%Lp' "$1" ;;
    Linux) stat -c '%a' -- "$1" ;;
    *) fail "unsupported test platform: $(uname -s)" ;;
  esac
}

[[ -f "$template" ]] || fail "private source template is missing"
[[ ! -e "$source_root/dot_codex/AGENTS.md.tmpl" ]] || fail "public-mode source template still exists"
source_git_mode=$(git -C "$repo_root" ls-files --stage -- home/dot_codex/private_AGENTS.md.tmpl | awk '{print $1}')
[[ $source_git_mode == 100644 ]] || fail "source template Git mode must be 100644"
[[ -r "$template" ]] || fail "source template is not readable"
[[ ! -x "$template" ]] || fail "source template must not be executable"
[[ $(chezmoi -S "$source_root" target-path "$template") == "$HOME/.codex/AGENTS.md" ]] ||
  fail "source template targets the wrong file"
[[ -f "$preflight_partial" ]] || fail "ticket-tracker preflight partial is missing"
[[ $(mode_of "$preflight_partial") == 644 ]] || fail "preflight partial mode must be 0644"
[[ -f "$claude_rule_template" ]] || fail "Claude preflight rule template is missing"
[[ $(mode_of "$claude_rule_template") == 644 ]] || fail "Claude rule template mode must be 0644"
[[ $(chezmoi -S "$source_root" target-path "$claude_rule_template") == "$HOME/.claude/rules/ticket-tracker-preflight.md" ]] ||
  fail "Claude rule template targets the wrong file"
for partial in "$identity_partial" "$checkpoint_partial"; do
  [[ -f "$partial" ]] || fail "${partial:t} partial is missing"
  [[ $(mode_of "$partial") == 644 ]] || fail "${partial:t} partial mode must be 0644"
done
[[ -f "$claude_git_rule_template" ]] || fail "Claude Git defaults rule template is missing"
[[ $(mode_of "$claude_git_rule_template") == 644 ]] || fail "Claude Git defaults rule template mode must be 0644"
[[ $(chezmoi -S "$source_root" target-path "$claude_git_rule_template") == "$HOME/.claude/rules/git-defaults.md" ]] ||
  fail "Claude Git defaults rule template targets the wrong file"

if [[ ${GLOBAL_AGENTS_POLICY_PUBLIC_ONLY:-0} == 1 ]]; then
  render_fixture=$(mktemp -d "${TMPDIR:-/tmp}/global-agents-source.XXXXXX")
  chmod 700 "$render_fixture"
  mkdir -m 700 "$render_fixture/dot_codex"
  render_template="$render_fixture/dot_codex/private_AGENTS.md.tmpl"
  awk '
    !($0 ~ /include[[:space:]]+"\.private-agents\.md\.age"[[:space:]]*\|[[:space:]]*decrypt/)
  ' "$template" > "$render_template"
  chmod 644 "$render_template"
  mkdir -m 700 "$render_fixture/.chezmoitemplates" "$render_fixture/dot_claude" "$render_fixture/dot_claude/rules"
  cp -p -- "$preflight_partial" "$render_fixture/.chezmoitemplates/$preflight_partial_name"
  cp -p -- "$identity_partial" "$render_fixture/.chezmoitemplates/$identity_partial_name"
  cp -p -- "$checkpoint_partial" "$render_fixture/.chezmoitemplates/$checkpoint_partial_name"
  cp -p -- "$source_root/.chezmoiignore" "$render_fixture/.chezmoiignore"
  render_claude_rule_template="$render_fixture/dot_claude/rules/${claude_rule_template:t}"
  cp -p -- "$claude_rule_template" "$render_claude_rule_template"
  render_claude_git_rule_template="$render_fixture/dot_claude/rules/${claude_git_rule_template:t}"
  cp -p -- "$claude_git_rule_template" "$render_claude_git_rule_template"
  render_source_root=$render_fixture
fi

chezmoi -S "$render_source_root" dump --format json "$HOME/.codex/AGENTS.md" > "$target_state"
[[ $(jq -r '.[".codex/AGENTS.md"].perm' "$target_state") == 384 ]] || fail "target mode is not 0600"

(
  cd "$render_source_root"
  chezmoi -S "$render_source_root" execute-template < "$render_template" > "$rendered"
)
[[ $(mode_of "$rendered") == 600 ]] || fail "rendered test artifact must be 0600"

awk '
  $0 == "## Git Checkpoints And Publication" { found = 1; next }
  found && /^## / { exit }
  found { print }
' "$rendered" > "$git_policy"

git_required=(
  'commits and pushes as normal completion steps for task-owned changes'
  'For every Git-backed task, use `checkpointing-and-publishing-git-work` at task start, at every clean checkpoint, and before a stopping-point response.'
  'For every pull-request creation, title edit, body edit, or draft/ready-state change, use `publishing-reviewable-prs`. It must use `writing-reviewable-pr-descriptions` for reviewer-facing text.'
  'Stage and commit only task-owned work.'
  'local-only and non-blocking only when explicitly classified by the operator, active task, or applicable repository policy'
  'instructions to keep work uncommitted or local override default commit and publication'
  'Ask about unrelated dirt while Ivan is available.'
  'When he is away, commit safely separable task work without including unrelated changes.'
  'Unresolved ownership, destination, identity, permission, conflicts, failed required checks or reviews, repository or release requirements, or inability to preserve remote work are gates.'
  'Direct default-branch pushes and task-owned exact-lease rewrites with `--force-with-lease` are authorized when repository policy permits and remote work is preserved.'
)

for ((i = 1; i <= ${#git_required}; i++)); do
  grep -Fq -- "$git_required[$i]" "$git_policy" || fail "Git checkpoint policy is missing required clause $i"
done

required=(
  'operator owns the checklist and the active task authorizes changing the issue, pull request, or comment'
  'write “the reviewed commit”, “the published revision”, or “verification tied to commit `<SHA>`”'
  'instead of stock phrases such as “exact head” or “exact-head evidence”.'
  'Use “exact head” or similar precision only when it materially distinguishes the current revision from a stale review or enforces an immutable review or merge gate.'
  'Write each human-facing message as a turn in a live conversation.'
  'Open by answering what the person actually asked'
  'so write the next point to meet that response'
  'A drafted artifact is a turn in its own conversation: write it for its reader arriving fresh, not for the thread that produced it; keep revision feedback out of its text, fold corrections in without defending against them, and state open questions as scope to investigate, not as rebuttal.'
  'Open a deliverable with what it hands its reader—the capability, the fix, the decision—never a defense of its own existence; let motivation and evidence land where the reader would ask for them, so the piece carries the reader toward the action it exists for.'
  'When work stops at the edge of what was asked or authorized rather than at a real blocker, say so plainly, and end a stopping-point report with what remains and the next decision.'
  'When reporting a check you ran, separate what the real system does from conditions you constructed to run it.'
  'Spend emphasis in proportion to stakes: state what the reader must not miss most plainly and prominently, and let routine mechanics recede.'
  'Report verification as what the reader can now trust, naming the machinery that produced it only when the reader must rerun or audit the check.'
  "A message sent in Ivan's name sounds like Ivan writing it: his cadence and word choices, cleaned and polished, never a persona layered on top."
  'When a social or situational fact is not in evidence (who asked, what happened, when), ask or leave it out rather than inventing it.'
  'terse, direct, warm, and firm: a person speaking naturally'
  'Own judgments and evidence in the first person'
  'State a confident finding as a plain declarative'
  'credit it before flagging what is wrong'
  'vary openings, cadence, and arrangement so every item flows from its own substance'
  'A substantial comment or reply is still a reply'
  'Check each fact before phrasing it fluently'
  'Terseness serves natural flow, never compression'
  'Make each term self-explanatory where it stands or explain it locally'
  'Pair each dense, load-bearing statement with a concrete instance.'
  "An operator's brief is compressed input, not the message's voice or frame: unpack it into what this reader needs, and never forward its authorship, roles, powers, or sequencing as the frame of the message."
  'Lead with the frame and the requested action, including “nothing right now” when that is the ask.'
  'Coordination with a peer reads as mutual alignment, never as jurisdiction; do not enumerate powers or declare boundaries to a colleague.'
  'Mean the question or do not ask it; a question the next sentence pre-empts is not a question.'
  'Use a workflow-internal identifier (a ticket key, a run label, a delivery id) only when the same or a recent message has established what it means for this reader.'
  'In messages and replies, fragments that read as speech are welcome, and so are contractions; “we” is for the shared work and codebase, “I” for your own judgment.'
  'When part of the work is genuinely right, credit it before flagging what is wrong, and only when the credit is load-bearing for the point rather than freestanding praise.'
  'A detail earns its place only if it changes what the reader does next.'
  'Across a batch of comments or replies, vary openings, cadence, and arrangement so every item flows from its own substance; if two pieces share an opening, a closing move, or roughly the same length, rewrite one from its own content.'
  'Before drafting, gather what the draft rests on: what was run and what it returned, what was decided and by whom, what the reader asked in their words, and what they already know.'
  'Most invented detail comes from a thin brief, so supply the load-bearing facts and say what you did not check rather than filling it in.'
  'Evidence is a hard constraint, and style pressure never licenses invention.'
  'What the source in front of you establishes, state as a plain declarative anchored on its path or symbol; a runtime outcome you did not run and observe (a test result, command output, or system behavior) takes a modal or a condition (“this should fail once the cache is wired up”), never a plain “this fails”.'
  'Never commit yourself, or the people you write for, to a position, threshold, offer, deadline, or concession that is not in evidence; offer options, ask the question, or name the decision as open and say who holds it.'
  "Write the observation, not the story: “the config record hasn't changed since June 2”, not “the update silently failed”."
  'Check each fact before phrasing it fluently, when first written and through every rewrite; rewriting is where “should fail” drifts to “fails” and a question drifts to a commitment.'
  'Treat these rules as edit actions on the finished draft, not only as preferences while drafting: before sending, even when the draft reads well, judge each dash by its usage, reread the last sentence of each piece, strike the tells that follow, compare the pieces of a batch, reread each piece as its recipient, and recheck every fact against the evidence.'
  'If the last sentence lands as a mic-drop, a moral drawn from the point just made, a tidy recap, or a rider adding a second ask, delete it or replace it with the plain point.'
  "Strike on sight “worth noting”, “It's important to”, “credit where due”, “That said”, arrow chains standing in for a sentence, topic labels opening a piece (“Status:”), “I noticed”, and any coinage you would not say aloud to a colleague."
  "Anything that reads as a machine's note to itself (mechanical parallelism, obsessive precision, restating what the reader already knows, an inventory that shows your work) gets rewritten as speech."
  'For anything going to a reviewer, a shared channel, or a customer, have a second pass hunt for tells and recheck every fact.'
  'Judge each em dash by its usage: a parenthetical dash (an inserted phrase read inline) is unspaced, and a bespoke non-parenthetical usage may be spaced only when the spacing does work that a reader would miss.'
  'Where a dash is not the best structure, use a colon, parentheses, a semicolon, or a new sentence; judge fit, not count.'
  'An en dash joins numeric ranges'
  'Inline lists take the Oxford comma.'
  'Prefer squash merging when several merge methods are available.'
  'Punctuation respects the unity of a quoted phrase rather than intruding into it'
  "In review replies, do not restate the comment, justify the reviewer's suggestion, or import unrelated decisions."
  'If agreeing and proceeding, say little.'
  'Loanwords keep their accents'
  'Before communicating to another audience, consider what they need to understand or accomplish'
  'the context and language you confidently share, and the nearest common ground'
  'Build from that ground with only the orientation needed.'
  'Take special care after long, deep, resumed, or compacted work; simple exchanges need no recap or fixed structure.'
  'Recover missing or uncertain grounding from the latest settled context in transcripts and controlling artifacts; do not ask for discoverable facts.'
  'Distinguish what you know about the audience from what you infer'
  'consider how they may encounter the communication'
  'welcome people joining without intervening context'
  'Make decision stakes clear from shared ground.'
  'Revise recommendations when that grounding reveals broader consequences, briefly saying why.'
  'If any message does not land, stop, rebuild shared context, and explain more simply.'
  'Use `context7-mcp`'
  'Send only the minimum public query needed'
  'Use internal documentation only through a local, internal-only fallback.'
  'Use the `ctx7` CLI to fetch current documentation whenever the user asks about a library, framework, SDK, API, CLI tool, or cloud service'
  'npx ctx7@latest library <name> "<what to look up>"'
  'npx ctx7@latest docs <libraryId> "<what to look up>"'
  'You MUST call `library` first to get a valid ID unless the user provides one directly in `/org/project` format.'
  'Do not run more than 3 commands per question.'
  'Do not include sensitive information (API keys, passwords, credentials) in queries.'
  'If a command fails with a quota error, inform the user and suggest `npx ctx7@latest login` or setting `CONTEXT7_API_KEY` env var for higher limits.'
  "Run Context7 CLI requests outside Codex's default sandbox."
  'When asking Ivan a question, through a user-input widget or plain text, wait for his response by default.'
  'Set no automatic timeout or auto-resolution unless Ivan explicitly requests one for that question or workflow.'
  'Keep one to three captures as discrete files.'
  'Present four or more captures as a local site-shaped collection.'
  'Publication requires separate authorization.'
  'Only refresh local `main` when the operation depends on it.'
)

for ((i = 1; i <= ${#required}; i++)); do
  grep -Fq -- "$required[$i]" "$rendered" || fail "missing required clause $i"
done

chezmoi -S "$render_source_root" dump --format json "$HOME/.claude/rules/ticket-tracker-preflight.md" > "$claude_state"
[[ $(jq -r '.[".claude/rules/ticket-tracker-preflight.md"].perm' "$claude_state") == 420 ]] ||
  fail "Claude rule target mode is not 0644"

(
  cd "$render_source_root"
  chezmoi -S "$render_source_root" execute-template < "$render_claude_rule_template" > "$claude_rule"
)
preflight=$(
  cd "$render_source_root"
  chezmoi -S "$render_source_root" execute-template "{{ includeTemplate \"$preflight_partial_name\" . | trim }}"
)
[[ -n $preflight ]] || fail "preflight partial renders empty"

awk '
  $0 == "## Pull Requests And Issues" { found = 1; next }
  found && /^## / { exit }
  found { print }
' "$rendered" > "$pr_policy"

[[ $(<"$pr_policy") == *"$preflight"* ]] || fail "Codex policy does not carry the preflight in Pull Requests And Issues"
[[ $(<"$claude_rule") == "# Ticket Tracker Preflight"$'\n\n'"$preflight" ]] ||
  fail "Claude rule is not the heading plus the shared preflight"

preflight_sentences=(${(s:. :)${${preflight//$'\n'/. }//: /. }})
for preflight_sentence in $preflight_sentences; do
  ((${#preflight_sentence} >= 30)) || continue
  [[ $(grep -Fo -- "$preflight_sentence" "$rendered" | wc -l | tr -d ' ') == 1 ]] ||
    fail "Codex policy must carry the preflight exactly once"
  for source_template in "$template" "$claude_rule_template"; do
    ! grep -Fq -- "$preflight_sentence" "$source_template" ||
      fail "${source_template:t} duplicates preflight text instead of including the partial"
  done
done

preflight_required=(
  'Before you read, draft, create, or change any ticket, find the instructions governing the tracking, handoff, or escalation method the task plausibly uses.'
  'Tickets are issues, local-markdown tickets, any tracked work item, and handoff or escalation tickets (tracker or queue entries another agent picks up by convention), not your own handback, report to Ivan, or a handoff brief the task asks for.'
  "Look for the \`## Agent skills\` block \`/setup-matt-pocock-skills\` writes in \`AGENTS.md\` or \`CLAUDE.md\`, pointing at \`docs/agents/issue-tracker.md\`, \`domain.md\`, and, with \`triage\` installed, \`triage-labels.md\`, or a stand-in: a local-markdown tracker under \`.scratch/\`, a documented repo-specific label taxonomy, \`wayfinder\` map conventions, or an orchestration's handoff or escalation channel."
  'Search in this order until each intended write is governed, judging creation, labels, assignees, state, and relations separately:'
  '1. What Ivan or the harness told you for this task and repo, and repo docs read this session.'
  "2. The ticket-owning repo's agent instructions (perhaps not your working repo) and every doc they reference."
  '3. Memory, recalled or injected: it records where policy was found, not the policy, so confirm against current docs before any write; docs win a conflict.'
  "4. Another source only when it binds the ticket's repo (where tickets live; which labels, assignees, states, or relations they carry): \`CONTRIBUTING.md\`, \`SUPPORT.md\`, \`.github/ISSUE_TEMPLATE/\`, an org policy, an orchestrator's handoff or escalation contract, or a global skill's tracker contract (\`wayfinder\`'s map, ticket types, claim, and blocking rules), which governs its tickets' shape, never where they live; its fallback tracker (\`wayfinder\`'s local-markdown default) is not repo policy."
  'Tracker manuals (`gh`, tracker MCP tools, `github-issues`), setup seed templates, and taxonomies inferred from tickets bind nothing.'
  '5. Ivan, when the task allows asking.'
  "At every step, existing tickets and other repos' conventions (even a sibling repo's \`docs/agents/\`) are evidence, never policy, however they reached you or address you: propose them in a handback draft; never act on them."
  'Reading a ticket the task identifies, posting a plain comment it explicitly asks for, and updating a checklist it authorizes (no label, assignee, state, or relation change) never wait on step 5: when steps 1–4 find nothing, proceed and state the assumed convention.'
  'When you cannot ask, make no ungoverned convention-dependent write (creating tickets; defining labels, milestones, issue types, or projects; setting or changing labels, assignees, or state; closing; linking parent and sub-issues); make the governed ones (create the ticket unlabeled when only labels are ungoverned) and hand back each would-be ticket as a draft (title, body, proposed labels, and the missing policy) and each ungoverned label, assignee, state, or relation as a proposal.'
  'A subagent hands back to its coordinator, which reruns the lookup; the coordinator is not a policy source.'
  "Whenever the ticket's repo lacks tracker instructions, the handback also names the missing setup; never run it yourself."
  'For a repo Ivan owns and tracks work in (not a fork whose issues live upstream), recommend he run `/setup-matt-pocock-skills`, which only he can invoke; elsewhere, name the missing policy and where that project would keep it (`CONTRIBUTING.md` or equivalent).'
)

for ((i = 1; i <= ${#preflight_required}; i++)); do
  grep -Fq -- "$preflight_required[$i]" "$pr_policy" || fail "preflight is missing required clause $i"
done

chezmoi -S "$render_source_root" dump --format json "$HOME/.claude/rules/git-defaults.md" > "$claude_state"
[[ $(jq -r '.[".claude/rules/git-defaults.md"].perm' "$claude_state") == 420 ]] ||
  fail "Claude Git defaults rule target mode is not 0644"

(
  cd "$render_source_root"
  chezmoi -S "$render_source_root" execute-template < "$render_claude_git_rule_template" > "$claude_git_rule"
)
render_partial() {
  (
    cd "$render_source_root"
    chezmoi -S "$render_source_root" execute-template "{{ includeTemplate \"$1\" . | trim }}"
  )
}
identity=$(render_partial "$identity_partial_name")
checkpoint=$(render_partial "$checkpoint_partial_name")
[[ -n $identity && -n $checkpoint ]] || fail "Git defaults partials render empty"
[[ $(<"$claude_git_rule") == "# Git Defaults"$'\n\n'"$identity"$'\n\n'"$checkpoint" ]] ||
  fail "Claude Git defaults rule is not the heading plus the shared identity and checkpoint partials"

awk '
  $0 == "## Git Identity" { found = 1; next }
  found && /^## / { exit }
  found { print }
' "$rendered" > "$identity_policy"
[[ $(<"$identity_policy") == *"$identity"* ]] || fail "Codex policy does not carry the identity defaults in Git Identity"
[[ $(<"$git_policy") == *"$checkpoint"* ]] || fail "Codex policy does not carry the checkpoint rule in Git Checkpoints And Publication"

for shared_text in "$identity" "$checkpoint"; do
  [[ $(grep -Fo -- "$shared_text" "$rendered" | wc -l | tr -d ' ') == 1 ]] ||
    fail "Codex policy must carry each Git defaults partial exactly once"
  for source_template in "$template" "$claude_git_rule_template" "$repo_root/AGENTS.md"; do
    ! grep -Fq -- "$shared_text" "$source_template" ||
      fail "${source_template:t} duplicates Git defaults text instead of including the partial"
  done
done

identity_required=(
  "Ivan's default Git identity is \`Ivan D Vasin <ivan@nisavid.io>\`, his GitHub account is \`nisavid\`, and his default branch prefix is \`nisavid/\`."
  'prefix new branches with `nisavid/`'
)
for ((i = 1; i <= ${#identity_required}; i++)); do
  grep -Fq -- "$identity_required[$i]" "$identity_policy" || fail "identity defaults are missing required clause $i"
done

repo_agents_forbidden=(
  'ivan@nisavid.io'
  'Prefix branches with'
  'GitHub account for repository mutations'
  'checkpointing-and-publishing-git-work'
)
for phrase in $repo_agents_forbidden; do
  ! grep -Fq -- "$phrase" "$repo_root/AGENTS.md" || fail "repository AGENTS.md carries personal Git policy"
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

git_policy_words=$(wc -w < "$git_policy" | tr -d ' ')
((git_policy_words <= 160)) || fail "Git checkpoint policy exceeds 160 words ($git_policy_words)"

procedural=(
  'A **clean checkpoint** exists when'
  'A **stopping point** is the point'
  'the complete unpublished commit range'
  'When no upstream exists, set the unambiguous default remote and same-name branch as upstream.'
  'the remote advanced, fetch and inspect the remote state'
  'After pushing, verify the remote tip.'
)

for phrase in $procedural; do
  ! grep -Fq -- "$phrase" "$git_policy" || fail "Git checkpoint policy contains displaced procedure"
done

forbidden=(
  'Prefer rebase merging when several merge methods are available.'
  'An em dash is unspaced and earns its place'
  'more than a couple in one message reads as a tic'
  'ivan/impeccable'
  'ivan/setup-local'
  'ivan/local-runtime-policy-docs'
  'ivan/real-work-for-local-dev'
  'ivan/ceres-dev-cluster-program'
  'dev:env:fnx:handoff'
  'yarn prisma:generate'
  'make -C packages/fnx test'
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
  'completed transaction verifies' \
  'local/private catalog may be read and correlated for routing' \
  'scrub account homes, account IDs, stable per-account labels, and derived identifiers'
)

for ((i = 1; i <= ${#docs_required}; i++)); do
  grep -Fq -- "$docs_required[$i]" "$encryption_doc" || fail "encryption documentation is missing clause $i"
done

! grep -Fq -- 'Installs the complete skill and symlink set' "$encryption_doc" || \
  fail "encryption documentation claims authoritative complete-set installation"

print -- 'global AGENTS policy: ok'
