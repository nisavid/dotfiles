#!/usr/bin/env zsh
set -euo pipefail

repo_root=${0:A:h:h}
source_root="$repo_root/home"
template="$source_root/dot_codex/private_AGENTS.md.tmpl"
encryption_doc="$repo_root/docs/ENCRYPTION.md"
transition_contract_test="$repo_root/tests/test_model_transition_contract.py"
rendered=$(mktemp "${TMPDIR:-/tmp}/global-agents-policy.XXXXXX")
target_state=$(mktemp "${TMPDIR:-/tmp}/global-agents-state.XXXXXX")
git_policy=$(mktemp "${TMPDIR:-/tmp}/global-agents-git-policy.XXXXXX")
render_source_root=$source_root
render_template=$template
render_fixture=
chmod 600 "$rendered"
chmod 600 "$target_state"
chmod 600 "$git_policy"
trap 'rm -f "$rendered" "$target_state" "$git_policy"; [[ -z $render_fixture ]] || rm -rf "$render_fixture"' EXIT

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
[[ -f "$transition_contract_test" ]] || fail "model-transition contract test is missing"
[[ ! -e "$source_root/dot_codex/AGENTS.md.tmpl" ]] || fail "public-mode source template still exists"
[[ $(mode_of "$template") == 644 ]] || fail "source template mode must be 0644"
[[ $(chezmoi -S "$source_root" target-path "$template") == "$HOME/.codex/AGENTS.md" ]] ||
  fail "source template targets the wrong file"

if [[ ${GLOBAL_AGENTS_POLICY_PUBLIC_ONLY:-0} == 1 ]]; then
  render_fixture=$(mktemp -d "${TMPDIR:-/tmp}/global-agents-source.XXXXXX")
  chmod 700 "$render_fixture"
  mkdir -m 700 "$render_fixture/dot_codex"
  render_template="$render_fixture/dot_codex/private_AGENTS.md.tmpl"
  awk '
    !($0 ~ /include[[:space:]]+"\.private-agents\.md\.age"[[:space:]]*\|[[:space:]]*decrypt/)
  ' "$template" > "$render_template"
  chmod 644 "$render_template"
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
  'An em dash is unspaced and earns its place'
  'An en dash joins numeric ranges'
  'Inline lists take the Oxford comma.'
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
  'Before every payload-bearing new invocation, follow-up, resume, retry, or capacity fallback, use `choosing-agent-models`; preserve same-task identity, and stop rather than silently substituting a model after failure.'
  'this standing permission covers only a separately supported status-only interface whose installed implementation is proven not to refresh or persist authentication and not to mutate login, configuration, cache, database, task, or turn state.'
  'Bind that side-effect-safety evidence to the exact installed version and interface, and revalidate it after any implementation, version, startup, or status-path change.'
  'A protocol method name, `refreshToken: false`, or a read-shaped RPC is not proof of that boundary.'
  'Do not launch `codex app-server` for this refresh when its status path can call proactive authentication refresh or persist state.'
  'The Codex 0.149.0 four-call app-server path is outside this standing permission and is not eligible to establish fresh execution authority.'
  'Direct credential-file reads, credential injection, token refresh, task or turn creation, task-data transfer, task workspace or task tools, login or configuration mutation, delegation, task execution, and the separate harmless task-work probe remain outside this permission.'
  'If no proven side-effect-free status path exists or it cannot start safely, record the route as status-unverified. If an eligible status refresh is refused, record the route as status-denied.'
  'Either state keeps the permitted-route inventory incomplete and proves none of genuine model absence, Daybreak unavailability, exhausted capacity, missing task-work authority, or execution authority.'
  'Before substantive dispatch, require authenticated, version-bound side-effect-safety evidence and complete task, plan, and actuation bindings for the current invocation.'
)

for ((i = 1; i <= ${#required}; i++)); do
  grep -Fq -- "$required[$i]" "$rendered" || fail "missing required clause $i"
done

status_policy_reference='When `choosing-agent-models` needs fresh route metadata, this standing permission covers only a separately supported status-only interface whose installed implementation is proven not to refresh or persist authentication and not to mutate login, configuration, cache, database, task, or turn state. Bind that side-effect-safety evidence to the exact installed version and interface, and revalidate it after any implementation, version, startup, or status-path change. A protocol method name, `refreshToken: false`, or a read-shaped RPC is not proof of that boundary. Do not launch `codex app-server` for this refresh when its status path can call proactive authentication refresh or persist state. The Codex 0.149.0 four-call app-server path is outside this standing permission and is not eligible to establish fresh execution authority. Direct credential-file reads, credential injection, token refresh, task or turn creation, task-data transfer, task workspace or task tools, login or configuration mutation, delegation, task execution, and the separate harmless task-work probe remain outside this permission. If no proven side-effect-free status path exists or it cannot start safely, record the route as status-unverified. If an eligible status refresh is refused, record the route as status-denied. Either state keeps the permitted-route inventory incomplete and proves none of genuine model absence, Daybreak unavailability, exhausted capacity, missing task-work authority, or execution authority. Before substantive dispatch, require authenticated, version-bound side-effect-safety evidence and complete task, plan, and actuation bindings for the current invocation.'
status_policy_lines=$(grep -Ei -- '(app-server|standing permission)' "$rendered")
[[ $status_policy_lines == $status_policy_reference ]] || \
  fail 'global policy has unreviewed app-server or standing-status policy'

! grep -Fq -- 'this standing permission authorizes launching the installed `codex app-server`' "$rendered" || \
  fail 'global policy must not authorize the state-mutating app-server status path'

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

python3 "$transition_contract_test"

print -- 'global AGENTS policy: ok'
