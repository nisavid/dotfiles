---
name: honing-agent-facing-docs
description: Use when reviewing, refactoring, rewriting, or streamlining AGENTS.md, repo-local agent skills, skill references, or agent policy docs
---

# Honing Agent-Facing Docs

## Overview

Agent-facing docs should load at the moment they help and stay quiet otherwise.

**Required background:** Use `writing-for-agents` for agent-facing docs; read its `SKILL-MECHANICS.md` when editing a skill. Use the current harness's `skill-creator` for skill packaging, validation, and applicable forward testing, and `writing-clearly-and-concisely` for all prose. For durable docs that also serve humans, use `honing-human-facing-docs` alongside this skill, treat the agent-policy surface as reference, and apply `applying-diataxis` separately to the human-facing material.

## When To Use

Use for `AGENTS.md`, `CLAUDE.md`, repo-local or user-global skills, skill references, skill-owned scripts, agent policy, validation rules, and maintainer docs that steer future agent behavior.

Do not use for ordinary user guides unless agent behavior or policy placement is part of the task.

## Placement Rule

Put each durable fact in the narrowest place that will load when needed.

| Destination | Belongs There |
| --- | --- |
| `AGENTS.md` | Always-loaded law: repo role, hard rules, source boundaries, generated-artifact policy, routing, validation expectations, and pointers. |
| Triggered skill | Task-shaped workflow for recognizable work. |
| Skill reference | Bulky examples, command catalogs, matrices, failure signatures, and rationale. |
| Skill script | Repeatable checks, scaffolding, renderers, linters, and inspections. |
| Repo docs | Human-readable architecture, operations, package behavior, troubleshooting, and policy rationale. |
| Nowhere | Obsolete, duplicated, unactionable, private-host, reliably scoutable, or wrong content. |

## Method

1. Inventory docs, skills, references, scripts, commits, and generated artifacts that may hold durable knowledge.
2. Triage each meaningful instruction by audience, trigger, durability, actionability, and source-of-truth ownership.
3. Move useful content before deleting it. Preserve the last useful copy unless the fact is wrong or reliably derivable from source.
4. Shrink always-loaded docs to operating law. Move recipes, matrices, incident stories, command catalogs, and long rationale behind triggered paths.
5. Turn repeated mechanical instructions into scripts or tests where practical.
6. Verify discovery: a future agent can find the rule, source file, command, and closeout check without reading the whole repo.
7. For no-code doc hones, request review for placement, discoverability, lost information, stale claims, and workflow fit.

## Routing Checks

- Keep onboarding material in always-loaded docs only when needed before an agent can pick a workflow.
- Keep incident history only when it explains a live constraint; otherwise state the current rule.
- Put long command catalogs in repo docs when humans use them, in skill references when only agents need them, and in scripts when repeatable.
- Keep exact error strings in troubleshooting references when they are useful search handles.

## Check Changed Behavior

Choose the instruction form from the observed failure. A missed constraint needs a clear decision rule; a wrong output form needs a positive recipe; an omission needs an explicit required element; a conditional action needs an observable condition. Use the least prescriptive form that addresses the failure, following `writing-for-agents` for wording and placement.

For changes that alter agent behavior, exercise the owning route with a realistic request and the minimum raw artifacts. Choose pressures that could cause the target failure in ordinary use, and explain that connection when designing the case. Keep the task, inputs, and relevant pressures matched between the baseline and candidate so another change cannot explain the result. When claiming that a correction fixes an observed failure, establish that failure on the baseline and check the corrected behavior with the candidate. A baseline that passes supplies no evidence of that corrective effect; investigate the case rather than manufacturing a failure.

Use the loaded `skill-creator` for its applicable testing workflow. Separate skill loading, observable task behavior, and environment failures. Report missing execution or observation capabilities as missing evidence. Mechanical edits that preserve behavior use checks proportionate to what changed.

## Closeout

- Always-loaded guidance is shorter and still sufficient.
- Triggered guidance has clear entry conditions and closeout checks.
- Bulky material moved to references, scripts, or repo docs.
- Human-facing material did not get buried inside agent-only surfaces.
- Links and commands needed for discovery work.
- Changed behavior was exercised through its owning route; the failure, relevant pressures, source revision, observed result, and any missing evidence are recorded.
