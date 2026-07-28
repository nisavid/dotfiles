---
name: choosing-agent-models
description: Use when preparing an agent, subagent, Task invocation, or agent definition after delegation has been chosen, including task-only prompts with no explicit role, model, or agent-type wording.
---

# Choosing Agent Models

## Overview

Choose a model after deciding that an agent or subagent should be invoked. This skill does not decide whether to delegate; orchestration, review, debugging, and implementation skills own that question.

Use the matrix below as the source of truth for model and reasoning-effort selection. Never invent model slugs; resolve the selected model to an exact model exposed by the environment, and pass an explicit `model` parameter only when the current tool policy permits it.

## When to Use

- Preparing any concrete agent, subagent, Task, or agent-definition invocation, whether the prompt names a role or only describes the work to perform.
- Selecting a `model` parameter for a `Subagent` call or agent definition.
- Choosing models for reviewer, coder, implementer, writing, design, or architecture agents.
- Adding fallback models to an agent workflow.
- A skill says "when model choice is available," "selecting the reviewer model," "preferred model," "best available model," "best available review subagent," "model limitation," or similar.

Do not use this for product runtime model routing, AI feature configuration, or deciding whether a subagent should exist.

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
