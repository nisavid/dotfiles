---
name: choosing-agent-models
description: Use when selecting a model for an agent, subagent, task, or agent definition; adding a model fallback; or routing cybersecurity-related or cybersecurity-adjacent work.
---

# Choosing Agent Models

## Overview

Choose a model after deciding that an agent or subagent should be invoked. This skill generally does not decide whether to delegate; orchestration, review, debugging, and implementation skills own that question. The Daybreak policy below is the exception: it selects a model-routing disposition for cybersecurity work before execution starts. The owning workflow executes any delegation, task, ticket, or handoff action.

Use the matrix below as the source of truth for model and reasoning-effort selection. Never invent model slugs; resolve the selected model to an exact model exposed by the environment, and pass an explicit `model` parameter only when the current tool policy permits it.

## When to Use

- Preparing any concrete agent, subagent, Task, or agent-definition invocation, whether the prompt names a role or only describes the work to perform.
- Revalidating an existing task before a payload-bearing follow-up, resume, retry, or capacity fallback.
- Selecting a `model` parameter for a `Subagent` call or agent definition.
- Choosing models for reviewer, coder, implementer, writing, design, or architecture agents.
- Adding fallback models to an agent workflow.
- Routing cybersecurity-related or cybersecurity-adjacent whole tasks or bounded subtasks, including through a Codex agent in another harness.
- A skill says "when model choice is available," "selecting the reviewer model," "preferred model," "best available model," "best available review subagent," "model limitation," or similar.

Do not use this for product runtime model routing, AI feature configuration, or deciding whether a subagent should exist.

## Model Transition Authorization

Before every payload-bearing new invocation, follow-up, same-task resume, retry, or capacity fallback, re-run this skill against the prior routing state and current scope before task data is sent. Return either an authorized exact model and effort or a fail-closed disposition to the workflow that owns the invocation.

Re-read the exact selected invocation surface's current selector and capability state for every invalidated route tuple. A stored model, family name, or stale observation is not an executable selection.

For an existing task, preserve its identity and ownership, its prior authorized selection, the prior role and risk floors, any mandatory security route, and any explicit operator selection. A follow-up, resume, retry, timeout, or capacity failure is not by itself a reclassification. Capacity changes route availability only. It never lowers those floors or authorizes Terra, Luna, or another otherwise ineligible selection.

Only an explicit operator instruction can change a sticky operator selection. An orchestration prompt, inherited default, capacity handler, or worker output is not an operator override. If the operator selection conflicts with a mandatory security route or is unavailable, report the conflict and stop rather than changing either requirement silently.

Distinguish a selection fallback within the preserved classification from runtime failover after an error. Reclassification requires an explicit current-scope record; it may lower the selection only when the active role genuinely becomes easier and no operator or security minimum remains, and it must strengthen the selection when harder judgment appears. For mixed-role work that is not split, preserve the hardest required judgment as the floor.

Bind each decision to the invocation event, new-task or same-task state, prior authorized selection, prior and current classification, operator-selection state, exact route tuple and current capability evidence, capacity state, selected exact model and effort, and terminal disposition. The invoking workflow must reject any route, model, or effort that does not match this decision. This skill authorizes the selection; it does not send task data or mutate tasks.

## Daybreak Routing For Cybersecurity Work

Treat cybersecurity-related and cybersecurity-adjacent whole tasks and bounded subtasks as Daybreak-routed work. This section overrides the general matrix and fallback rules for that scope.

In ChatGPT or Codex harnesses authenticated with an OpenAI account, agents **must route cybersecurity-related or cybersecurity-adjacent work to a Daybreak model** whenever any permitted Daybreak route is genuinely runnable. In every other harness, agents **should route that work to a Daybreak model** whenever any permitted Daybreak route is genuinely runnable. The Daybreak model executes the routed cybersecurity work rather than choosing a model for another agent. These rules do not govern unrelated work. Their modal verbs govern routing, not whether the cybersecurity work is optional.

Before selecting a model, inventory each distinct route independently. A route is one invocation surface plus any account home, authenticated identity, model, and capability state required by that surface. Catalog entries are route inputs, not routes by themselves.

1. A Daybreak model in the native subagent selector.
2. A Daybreak model in the peer or sibling task selector.
3. Each Codex session-launch surface available to the current harness, expanded across every permitted authenticated account home in `~/.agents/daybreak-account-bindings.md`. This includes cross-harness invocation of Codex agents.

Every harness must inventory cross-harness Codex invocation before concluding that Daybreak is unavailable. Read the private binding catalog before using an account-home route. If the catalog is absent, unreadable, or does not match the authenticated identity, treat that route as unavailable. Never disclose catalog entries or infer a binding from a directory name.

A no-task-data local status refresh is a local status probe used solely to refresh local account authentication, selector exposure, entitlement, capacity, the exact currently exposed model, and model-runnability. Keep the refresh read-only and no-task-data: it may inspect selectors and make only the route's status request needed to observe those facts, but it must not create a task session, transfer task data, use task workspace or task tools, perform an external side effect, delegate, or execute task work. This status request is distinct from the separate harmless probe required after task-work authorization. When fresh routing information is needed, run that refresh automatically for each permitted account route whose observation is missing or stale; the operator does not need to authorize it. The refresh sends no task data and performs no task work.

For a permitted Codex account-home route, use the installed `codex app-server` as the supported status interface when its current local protocol exposes initialization, `account/read` with `refreshToken: false`, `model/list`, and `account/rateLimits/read`. Launch it against the catalog-selected account home from an OS temporary working directory, limit requests to those status methods, and retain only the bounded routing facts. Do not read `auth.json` or another credential file directly, refresh a token, persist authentication output, or replace the supported interface with an ad hoc credential-reading script. If the supported interface cannot start or a request is denied, record the route as status-unverified or status-denied. Those outcomes do not prove that Daybreak is absent or unavailable, do not authorize fallback, and do not relax any task-work gate. Keep the permitted-route inventory incomplete until that route has a fresh supported result.

In decisions and reports, keep incomplete inventory, status-unverified or status-denied, genuine model absence, exhausted capacity, failed harmless probe, and missing task-work authority as distinct states. A route may be unavailable for task work because one named gate failed, but that disposition must not erase or relabel the observed route facts.

During an already authorized no-task-data refresh, you may inspect route metadata exposed for unrelated tasks, including advertised model availability; this does not authorize reading task data. An existing task is eligible only when delegation created it for the current source task and bounded purpose, or the operator identified it as a same-purpose companion. Do not use an unrelated task as an execution or authorization route for current-task work, including to execute with its model or under its account, entitlement, permissions, or context.

A route is genuinely runnable for delegated or executed task work only when the task authorizes the route's account, data boundary, workspace, tools, the probe, and any external actions as applicable, and the current no-task-data status refresh confirms that its selector exposes the exact Daybreak model, the bound account is authenticated, usage capacity remains, and one harmless probe containing no task data succeeds with model-runnability. Picker visibility, model selectability, authentication, capacity, session start, and successful execution are separate facts. The no-task-data local status refresh establishes current route facts but grants no authority for task-data transfer, task workspace or task-tool use, external actions, delegation, or execution, and it never satisfies or consumes the separate harmless-probe gate. Resolve the exact model exposed at that moment; never invent a slug or reuse a stale one. If required task-work authority is absent, classify the route as unavailable without probing it; the automatic local refresh remains permitted.

Keep authorization gates for task-data transfer, task workspace or task-tool use, external actions, and actual delegated or executed task work separate from this refresh; those gates must not suppress the no-task-data local status refresh. A dated catalog observation is historical, not fresh by default, and not current by default. Record a timestamped, redacted result and a declared freshness window for each exact invocation-surface, account-binding, authenticated-identity, model, and capability-state tuple. Reuse an observation only inside its declared freshness window and while the full tuple is unchanged.

Invalidate the observation when that tuple, selector, entitlement, capacity, authentication, data boundary, workspace, tool scope, or external-action scope changes, or when its freshness window expires; then perform one new no-task-data local status refresh for the changed exact tuple. Keep one no-task-data status refresh and one harmless task-work probe per exact tuple per freshness window; account for those limits independently because the status refresh is not the task-work probe. Retain only redacted evidence on nonlocal or public surfaces.
A concrete selector, authority, data-boundary, workspace, or tool-scope change creates a new tuple eligible for one new no-task-data status refresh and, separately, one new harmless task-work probe only after full task-work authority; neither operation creates task-work authority.

Within local/private operational state, read, correlate, and use account IDs and account-home identifiers, or a safe stable local label or direct identifier, when needed to distinguish the operator's permitted accounts and make each per-account status report actionable. Before persisting or transmitting any result to a nonlocal or public surface, scrub account IDs, account-home identifiers, and stable per-account labels, including derived home/path names; use only a generic non-stable marker or redacted status there. Credentials, tokens, decrypted secrets, and unrelated task data remain prohibited outside the narrow local operation that requires them.

When no permitted Daybreak route is genuinely runnable, select one disposition by harness and record why the routes failed:

- For Daybreak-routed work in ChatGPT or Codex with an OpenAI login, local non-Daybreak fall-through is forbidden. Select deferral until capacity returns when a Daybreak route exists and exhausted capacity is the blocker; select another available harness, whose model selection may fall through to an operator-approved next-best candidate; or select a tracker ticket for handling by another harness when tracker mutation is authorized. Cross-harness delegation to an operator-approved non-Daybreak candidate is an eligible disposition in this no-runnable-route state; it is not local fall-through, and model approval alone does not authorize delegation.
- For Daybreak-routed work in every other harness, including ChatGPT or Codex without an OpenAI login, the same dispositions are available. The current harness may also fall through locally to its next-best candidate under its normal model-selection policy.

Before returning an executable cross-harness disposition, require the owning workflow to authorize the target harness and account, data boundary, workspace, tools, and external actions. Until that complete authority exists, transfer no task data and return an approval-needed handoff.

Deadline, sunk cost, or a convenience request does not permit forbidden local fall-through. Return the selected disposition to the workflow that owns peer-task creation, delegation, tracker mutation, or handoff; this skill does not perform those actions. If no authorized disposition can proceed, return an explicit, narrowly scoped handoff.

For root-only work, when the native route cannot run Daybreak but an authorized peer, sibling, or cross-harness Daybreak route can, select a route through which the owning workflow can create a dedicated Daybreak peer or sibling task and return the bounded Daybreak scope. The owning workflow must create that dedicated task before the Daybreak work executes; a direct cross-harness session does not bypass this boundary. Keep integration and non-security coordination in the original task.

## Model Selection Matrix

Model names and effort levels below are selections, not guaranteed literal slugs. Resolve them to exact values exposed by the current environment before invoking a tool.

Classify each task by its primary required judgment:

1. Split materially different roles or phases before selecting models.
2. Use the security, UI design, human-facing writing, or agent-facing writing row when that named judgment determines success.
3. For coding, use the very-hard or hard row when its criteria apply. Otherwise use Terra or Luna only when the complete criteria and exclusions describe the delegated task; use the low-complexity or typical coding row for the remaining coding work.
4. For other work, use Terra or Luna only when the complete criteria and exclusions apply. If no row applies, report that the matrix has no selection instead of borrowing a neighboring row.

| Role or task shape | Preferred | Fallback |
| --- | --- | --- |
| Coding: very hard, very complex, very risky, or very persistently troublesome problems, or some sufficiently concerning combination of those traits | Claude Opus 5 at `max` | GPT 5.6 Sol at `max` |
| Security hardening | GPT 5.6 Sol at `max`, using Codex Security | None specified |
| Coding: hard, complex, risky, or persistently troublesome problems, or some sufficiently concerning combination of those traits | Claude Opus 5 at `high` | GPT 5.6 Sol at `xhigh` |
| UI design work, visual judgment, design critique, and non-copy UX decisions | Claude Opus 5 at `high` | GPT 5.6 Sol at `xhigh` |
| Human-facing writing, including user-facing copy, PR or issue text, published docs for humans, internal docs for human readers, and lengthy explainer comments; or reviews thereof | Claude Opus 5 at `high` | GPT 5.6 Sol at `xhigh` |
| Agent-facing writing, including skills, `AGENTS.md`, durable process instructions, handoffs, agent-readable specs, agent guidance, advice, journaling, and AI-consumed internal docs; or reviews thereof | GPT 5.6 Sol at `xhigh` | None specified |
| Terra work: stronger cognition can materially improve quality or efficiency, but a suboptimal result remains easy to review, discard, or repair; examples include scoped implementation, recoverable debugging, focused code review, and test design against a settled contract | Grok 4.5 at `high` with fast mode | GPT 5.6 Terra at `high` |
| Luna work: the task benefits from language understanding but does not require meaningful judgment or high intelligence; examples include exact-format extraction, classification against an explicit rubric, mechanical follow-ups, status monitoring, and tightly specified clerical edits | Grok 4.5 at `low` with fast mode | GPT 5.6 Luna at `high` |
| Coding: low-complexity, low-risk code intended to be merged | Claude Opus 5 at `medium` | GPT 5.6 Sol at `medium` |
| Coding: low-complexity, low-risk one-off code | GPT 5.6 Sol at `medium` | None specified |
| Coding: other or typical code intended to be merged | Claude Opus 5 at `high` | GPT 5.6 Sol at `high` |
| Coding: other or typical one-off code | GPT 5.6 Sol at `high` | None specified |

Terra work excludes tasks that control a hard-to-reverse decision and tasks that need only bounded semantic clerical work. Luna work excludes any choice that can redirect scope, architecture, diagnosis, integration, publication, or another hard-to-recover part of the effort. More Luna reasoning effort does not make it a substitute for Terra or Sol judgment. When delegated work changes character, reclassify it and select a new model before continuing.

## Mixed Tasks

Pick the model for the hardest required judgment, not the largest line count.

- Review plus implementation: classify the review and implementation independently.
- UI design plus mechanical UI edits: use a design/writing-capable model for design decisions; use a fast implementer only after the decisions are precise.
- Copywriting inside a code task: use the human-facing writing row when the copy is user-facing, published, long, subtle, or likely to be reviewed on voice and clarity.
- Agent-facing prose inside a docs, planning, review, or implementation task uses the agent-facing writing row. Do not route it to Opus merely because it is "documentation" or "writing."
- Architecture plus cleanup: use the coding row matching the hardest required architectural judgment until the target shape is settled, then reclassify mechanical implementation separately.
- Code review, exploratory codebase research, CI or log investigation, shell or test running, browser QA, issue triage, and PR triage use the coding row matching their difficulty and risk unless a more specific row applies. Use the Terra or Luna row only when its criteria are fully met.

## Prompt Requirements

When invoking a subagent, include all context needed for the selected role:

- the task goal and success criteria;
- the relevant specs, intent, acceptance criteria, or operator decisions;
- the scoped files, diff boundary, and out-of-scope areas;
- constraints on edits, verification, and risk;
- the selected role and why it determines model strength;
- what to return;
- an instruction to stop and report if unforeseen issues make the scoped task unsafe or ambiguous.

Do not rely on the subagent inheriting your session context.

## Fallback Rules

- Resolve the preferred selection to an available explicit model slug and effort.
- If the preferred tier is unavailable, use the next fallback in the same role row and state the limitation when it affects confidence, cost, or speed.
- If the row specifies no fallback and the preferred model is unavailable, do not invent one; report the missing selection.
- If the current tool policy does not allow an explicit `model` parameter, omit it even when this matrix identifies a preferred model.
- If the environment already fixes an appropriate model or the tool has no model parameter, omit the model parameter and state any material mismatch. Do not bypass the matrix merely because the task is mechanical or low-risk.
- If the user requested a specific unavailable model, do not silently substitute; report the unavailable model and available choices.
- Reclassify and strengthen the model when the current model blocks, misunderstands the task, or reveals harder judgment than the original classification allowed.

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Using this to justify spawning a subagent | Decide delegation elsewhere; use this only after delegation is chosen. |
| Treating every review as one task shape | Classify the subject and required judgment; use a specific writing or design row when applicable, otherwise the matching coding row. |
| Sending agent-facing docs, handoffs, skills, or instructions to Opus because they are "writing" | Use GPT 5.6 Sol at `xhigh`. |
| Treating Luna as a cheaper Terra or Sol | Use Luna only when the task requires no meaningful judgment and cannot redirect consequential work. |
| Hiding missing model support | State the limitation and fallback used. |
| Omitting task intent from the prompt | Include specs, intent, and scope, not just file paths. |
