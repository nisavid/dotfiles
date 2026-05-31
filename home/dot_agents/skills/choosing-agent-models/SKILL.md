---
name: choosing-agent-models
description: Use when preparing an agent, subagent, Task invocation, or agent definition after delegation has been chosen, including task-only prompts with no explicit role, model, or agent-type wording.
---

# Choosing Agent Models

## Overview

Choose a model after deciding that an agent or subagent should be invoked. This skill does not decide whether to delegate; orchestration, review, debugging, and implementation skills own that question.

Use the least expensive and fastest model that can reliably handle the role, but bias toward intelligence when the work is high-risk, ambiguous, architectural, or reviewer-facing. Never invent model slugs; map the role to the best available model exposed by the environment, and pass an explicit `model` parameter only when the current tool policy permits it.

## When to Use

- Preparing any concrete agent, subagent, Task, or agent-definition invocation, whether the prompt names a role or only describes the work to perform.
- Selecting a `model` parameter for a `Subagent` call or agent definition.
- Choosing models for reviewer, coder, implementer, writing, design, or architecture agents.
- Adding fallback models to an agent workflow.
- A skill says "when model choice is available," "selecting the reviewer model," "preferred model," "best available model," "best available review subagent," "model limitation," or similar.

Do not use this for product runtime model routing, AI feature configuration, or deciding whether a subagent should exist.

## Role Matrix

Tier names below are intent labels, not literal model slugs. Resolve them to explicit available slugs before invoking a tool.

| Role or task shape | Preferred intent | Fallback intent |
| --- | --- | --- |
| Reviewer agents, including code, spec, architecture, and pre-closeout review | Latest GPT extra-high | Latest Opus highest-thinking tier, then the most intelligent available latest-generation model at its highest thinking effort. |
| Many easy, low-risk implementation edits | Latest Composer Fast | Latest Gemini Flash, then the best cheap reliable fast model available. |
| Rearchitecture or very high complexity across abstractions, interactions, scenarios, plans, or contingencies | Latest GPT extra-high | Latest Opus highest-thinking tier, then the most intelligent available latest-generation model. |
| Human-facing writing, including user-facing copy, PR or issue text, published or internal docs, and lengthy explainer comments | Latest GPT extra-high | Latest Opus highest-thinking tier, then the most intelligent available latest-generation model. |
| UI design work, visual judgment, design critique, and non-copy UX decisions | Latest Opus highest-thinking tier | Latest GPT extra-high, then the most intelligent available latest-generation model. |
| High complexity across abstractions, interactions, or scenarios, but not top-tier rearchitecture | Latest GPT high | Latest Opus highest-thinking tier, then the most intelligent available latest-generation model. |
| Ordinary implementation delegated to a subagent | Latest Composer Fast | Latest GPT medium, latest Sonnet highest-thinking tier, then the most intelligent available latest-generation model. |

## Slug Resolution

Use exact slugs from the environment. If these Cursor model slugs are available, resolve common intents as follows:

| Intent | Ordered available slugs |
| --- | --- |
| Latest GPT extra-high or GPT high when no high tier exists | `gpt-5.5-extra-high` |
| Latest Opus highest-thinking tier | `claude-opus-4-8-thinking-high` |
| Latest Composer Fast | `composer-2.5-fast` |
| Latest Gemini Flash | `gemini-3.5-flash` |
| Latest GPT medium when unavailable | Use the next fallback for the role; do not invent a GPT medium slug. |
| Latest Sonnet highest-thinking tier when unavailable | Use `claude-4.6-sonnet-medium-thinking` only if it is the best available Sonnet option and state the tier limitation. |
| Most intelligent available latest-generation fallback | `gemini-3.1-pro`, then `claude-4.6-sonnet-medium-thinking`, then `composer-2.5`, unless the environment exposes a stronger exact slug. |
| Cheap reliable fast fallback | `gemini-3.5-flash`, then `composer-2.5`, unless the environment exposes a better exact cheap fast slug. |

For a small, easy, low-risk change, many orchestration skills will choose not to use a subagent. If a subagent is still required by the operator or workflow, treat it as ordinary implementation and prefer a cheap fast model.

## Mixed Tasks

Pick the model for the hardest required judgment, not the largest line count.

- Review plus implementation: reviewer model for the review, implementer model for accepted fixes.
- UI design plus mechanical UI edits: use a design/writing-capable model for design decisions; use a fast implementer only after the decisions are precise.
- Copywriting inside a code task: use the human-facing writing row when the copy is user-facing, published, long, subtle, or likely to be reviewed on voice and clarity.
- Architecture plus cleanup: use the architecture row until the target shape is settled, then downgrade implementation if the remaining edits are mechanical.
- Exploratory codebase research, CI or log investigation, shell or test running, browser QA, issue triage, and PR triage agents use the reviewer row when judgment dominates and the ordinary implementation row when execution is mechanical and well-scoped.

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

- Prefer available explicit model slugs over vague labels.
- If the preferred tier is unavailable, use the next fallback in the same role row and state the limitation when it affects confidence, cost, or speed.
- If the current tool policy does not allow an explicit `model` parameter, omit it even when this matrix identifies a preferred model.
- If the environment already fixes an appropriate model, the task is mechanical and low-risk, or the tool has no model parameter, omit the model parameter and let the environment choose.
- If the user requested a specific unavailable model, do not silently substitute; report the unavailable model and available choices.
- Escalate model strength when a cheaper model blocks, misunderstands the task, or reports uncertainty that stronger reasoning is likely to resolve.

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Using this to justify spawning a subagent | Decide delegation elsewhere; use this only after delegation is chosen. |
| Sending reviewers to cheap fast models | Reviewers need judgment; use the reviewer row. |
| Sending mechanical edits to top-tier models | Use a fast reliable implementer unless risk or ambiguity says otherwise. |
| Hiding missing model support | State the limitation and fallback used. |
| Omitting task intent from the prompt | Include specs, intent, and scope, not just file paths. |
