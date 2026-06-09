---
name: delegating-cross-agent-work
description: Use when leading work from Cursor, Claude Code, or Codex that may need delegation across Cursor, Claude Code, Codex, Spark, browser/computer-use agents, or separate worktrees; deciding what stays local versus handed off; or coordinating multi-agent work.
---

# Delegating Cross-Agent Work

## Overview

You are the work leader. Keep ambiguity, hypotheses, decisions, interpretation, debugging judgment, architecture, design taste, human-facing copy, and coordination local. Delegate bounded execution that benefits from parallelism, tooling, or waits outside your critical path.

## Kickoff

1. Identify the leader: Cursor uses the user's selected model; Claude Code should be latest Opus at `high`+ effort; Codex should be latest GPT at `high`+ effort.
2. Identify repo, branch, base, dirty state, submodules, and owning worktree. For Systalyze, use a `systalyze` worktree for repo or submodule targets.
3. Same harness: prefer native subagents for tight, short-lived tasks. Prefer peer agents for longer work, broad context, browser/computer use, separate worktrees, follow-ups, or independent lifecycle.
4. Cross-harness CLI/API launches are peer agents, not subagents.

## Canonical Peer Commands

Copy these shapes exactly except placeholders. Do not invent command names, flags, or model slugs. If local `--help` disagrees, stop and report the gap instead of translating by memory.

| Target | Inspect | Prompt |
| --- | --- | --- |
| Cursor Agent | `agent status --format json`; `agent models` | `agent -p --model <model-slug> --yolo --workspace <cwd> <prompt>` |
| Claude Code | `claude -p /usage`; `claude agents --json` | `claude --model opus --effort <high/xhigh/max> -p <prompt>` |
| Codex | No CLI quota command found; use app/account status if available. `codex doctor --json` checks auth/health only. | `codex exec -m <model> -c model_reasoning_effort="<high/xhigh>" -C <cwd> <prompt>` |

Never substitute `cursor-agent`, Cursor `--reasoning-effort`, Codex `--reasoning-effort`, or an unverified model such as `claude-sonnet-*` when the skill calls for the canonical command.

## Same-Harness Kickoff

| Leader | Subagent for tight/short-lived | Peer for longer/lifecycle work |
| --- | --- | --- |
| Cursor | Use a native Cursor subagent if the current Cursor harness exposes one; the validated CLI surface is peer-only. | Use the Cursor canonical peer command. |
| Claude Code | Use the native Task/subagent surface when available. | Use the Claude canonical peer command or Claude background agents. |
| Codex | Use the native Codex subagent tool, such as `spawn_agent` in Codex app. | Use the Codex canonical peer command or a new/forked Codex thread. |

From any leader with shell access, use the canonical table to inspect and prompt any target harness. When a task needs a specific model or thinking effort, do not shorten to bare `agent -p`, `claude -p`, or `codex exec`. Cursor effort is a model slug, e.g. `composer-2.5`, `gpt-5.5-high`, `gpt-5.5-extra-high`, `claude-opus-4-8-thinking-xhigh`. Codex CLI effort uses `model_reasoning_effort`; Codex app peers use `thinking` when available.

## Routing

| Task | Default target |
| --- | --- |
| Straightforward legwork: scouting, scaffolds, mechanical edits, TDD to a precise spec, bisection, extraction/summarization, mechanical ops, long waits | Cursor Composer 2.5 peer via `agent -p --model composer-2.5 --yolo ...`; bundle under about 100k task tokens |
| Numerous well-defined low-ambiguity steps | Spark peer session when step volume dominates coordination cost |
| Browser/computer use, localhost QA, screenshots, click-throughs | Codex peer session. Medium default; High for analysis/judgment; Extra High for visual/UX/taste |
| Unscripted analysis, interpretation, architecture critique, ambiguous investigation | Claude Code if usage allows; otherwise Codex. Use subagents only when tight and short-lived |

## Prompt Contract

Every prompt states goal, success criteria, cwd/worktree, branch/base, facts, target behavior, allowed/forbidden scope, read/write permission, verification, output, and stop conditions. Workers preserve user and peer edits, avoid broad refactors, and adapt instead of reverting.

## Leader Duties

- Settle hard thinking before delegating execution.
- Keep parallel edit scopes disjoint.
- Review returned patches, claims, screenshots, logs, and summaries.
- Integrate centrally in the owning worktree and verify the final contract.
- Reconcile conflicts; delegates do not decide final architecture, root cause, or user-facing wording unless assigned.

## Common Mistakes

- Using peer agents for tiny same-harness tasks: use subagents when native and short-lived.
- Using subagents for work needing its own lifecycle: use a peer session/thread/CLI run.
- Treating `claude -p /usage` as a Cursor or Codex usage check: it is Claude-only.
- Passing `--effort` to Cursor or Codex CLI: use Cursor model slugs or Codex `model_reasoning_effort`.
- Dropping model/effort flags from peer commands: include the canonical command.
- Citing external CLI docs instead of local command evidence: trust installed `--help` first.
- Delegate output treated as done: review, integrate, verify.

Related skills: `dispatching-parallel-agents`, `choosing-agent-models`, `using-git-worktrees`.
