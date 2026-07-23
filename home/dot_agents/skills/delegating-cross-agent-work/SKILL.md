---
name: delegating-cross-agent-work
description: Use when leading work from Cursor, Claude Code, or Codex that may need delegation across Cursor, Claude Code, Codex, Spark, browser/computer-use agents, or separate worktrees; deciding what stays local versus handed off; or coordinating multi-agent work.
---

# Delegating Cross-Agent Work

## Overview

You are the work leader. Keep ambiguity, hypotheses, decisions, interpretation, debugging judgment, architecture, design taste, human-facing copy, and coordination local. Delegate bounded execution that benefits from parallelism, tooling, or waits outside your critical path.

## Kickoff

1. Identify the leader: Cursor uses the user's selected model; Claude Code should be latest Opus at `high`+ effort; Codex should be latest GPT at `high`+ effort.
2. Identify repo, branch, base, dirty state, submodules, and owning worktree. For repos with dedicated per-project worktrees, target the appropriate worktree for repo or submodule targets.
3. When executing a written plan, compare it once with live repository state, current policy, and applicable instructions before dispatch. Batch consequential conflicts for the operator; adapt stale mechanics when current evidence preserves the intended outcome.
4. Same harness: prefer native subagents for tight, short-lived tasks. Prefer peer agents for longer work, broad context, browser/computer use, separate worktrees, follow-ups, or independent lifecycle.
5. Cross-harness CLI/API launches are peer agents, not subagents.

## Validate First

Before relying on a harness command or field name, validate it locally with bounded probes. If local help, tool schema, or a safe probe disagrees with this skill, stop and report the gap instead of translating by memory.

| Harness | Usage/status | Capability/model inspection |
| --- | --- | --- |
| Cursor Agent | `agent status --format json` | `command -v agent`; `agent --version`; `agent --help`; `agent models` |
| Claude Code | `claude -p /usage` | `command -v claude`; `claude --version`; `claude --help`; `claude agents --help`; `claude agents --json` only lists active background sessions |
| Codex | No CLI quota command found; use app/account status if available | `command -v codex`; `codex --version`; `codex exec --help`; `codex debug models`; `codex doctor --json` check-level auth/config/reachability; inspect `model` and `model_reasoning_effort` in `~/.codex/config.toml` |

Validated on 2026-06-09: Cursor Agent `2026.06.04-5fd875e`, Claude Code `2.1.169`, Codex CLI `0.135.0`. `cursor-agent` existed locally as a same-version Cursor alias; prefer `agent`, but a validated alias is acceptable when `agent` is unavailable.

## Peer Commands

Use the least-permissive peer command that can do the job. Do not invent command names, flags, or model slugs.

| Target | Read-only / probe peer | Edit-capable peer |
| --- | --- | --- |
| Cursor Agent | `agent -p --mode ask --model <model-slug> --workspace <cwd> <prompt>` or `--mode plan` for planning | `agent -p --model <model-slug> --workspace <cwd> <prompt>`; add `--yolo` only for explicitly trusted, isolated, edit/shell-intended work |
| Claude Code | `claude --model opus --effort <high/xhigh/max> --permission-mode plan -p <prompt>` | `claude --model opus --effort <high/xhigh/max> -p <prompt>` |
| Codex | `codex exec -m <model> -c 'model_reasoning_effort="<high/xhigh>"' -s read-only --ephemeral -C <cwd> <prompt>` | `codex exec -m <model> -c 'model_reasoning_effort="<high/xhigh>"' -s workspace-write -C <cwd> <prompt>` |

If a peer launch is blocked by sandboxed access to harness state, trust prompts, or quota, record the exact blocker and use an approved native app/session path instead. `codex doctor --json` can fail overall for unrelated install or terminal checks; inspect the specific auth/config/reachability checks before treating Codex as unavailable. For Claude, skip prompts when `claude -p /usage` shows insufficient 5h or weekly margin; record the reset time.

## Same-Harness Kickoff

| Leader | Subagent for tight/short-lived | Peer for longer/lifecycle work |
| --- | --- | --- |
| Cursor | Use a native Cursor subagent only if the current Cursor harness/UI exposes one. The validated local CLI surface is peer-only. | Use Cursor peer commands above. |
| Claude Code | Use the native Task/subagent surface when available. | Use Claude peer commands above or Claude background agents; inspect `claude agents --help` first. |
| Codex | Use the native Codex subagent tool when available; in current Codex app `spawn_agent` exposes `model` and `reasoning_effort`. | Use Codex peer commands above, or app thread tools when exposed; inspect whether they use `thinking` or `reasoning_effort`. |

Cursor effort is a model slug, e.g. `composer-2.5`, `gpt-5.5-high`, `gpt-5.5-extra-high`, `claude-opus-4-8-thinking-xhigh`. Codex CLI effort uses `model_reasoning_effort`. Codex app tools may expose `thinking` for peer threads or `reasoning_effort` for subagents; inspect the current schema.

## Routing

| Task | Default target |
| --- | --- |
| Straightforward legwork: scouting, scaffolds, mechanical edits, TDD to a precise spec, bisection, extraction/summarization, mechanical ops, long waits | Cursor Composer 2.5 peer; use read-only mode for scouting/summarization and edit-capable mode only for assigned edits |
| Numerous well-defined low-ambiguity steps | Spark peer session only when the current harness exposes Spark |
| Browser/computer use, localhost QA, screenshots, click-throughs | Codex peer session. Medium default; High for analysis/judgment; Extra High for visual/UX/taste |
| Unscripted analysis, interpretation, architecture critique, ambiguous investigation | Claude Code if usage allows; otherwise Codex. Use subagents only when tight and short-lived |

## Prompt Contract

Every prompt is a bounded task contract: goal; success criteria; cwd/worktree and, for Git-backed edits, immutable base; relevant facts and interfaces; target behavior; allowed and forbidden scope; read/write permission; required verification; output shape; and stop conditions. Workers preserve user and peer edits, avoid broad refactors, and adapt instead of reverting.

Use the smallest sufficient context. Put a large task brief, diff, log, or report in a uniquely named file only when passing it inline would materially bloat or truncate the handoff. Name the file and its role in the prompt; keep exact requirements in one authoritative place.

Ask workers to return one status:

- `DONE`: success criteria and required verification are complete.
- `DONE_WITH_CONCERNS`: work is complete, with concrete correctness or scope concerns for the leader to resolve.
- `NEEDS_CONTEXT`: a named missing fact or decision prevents safe progress.
- `BLOCKED`: the task cannot complete within its authority, scope, or available environment.

On `NEEDS_CONTEXT` or `BLOCKED`, change the inputs, authority, task boundary, or worker capability before retrying. Do not repeat the same dispatch unchanged.

## Leader Duties

- Settle hard thinking before delegating execution.
- Keep parallel edit scopes disjoint.
- Record the task's immutable base before edit-capable delegation when later review must isolate that task; never infer it as `HEAD~1`.
- Review returned patches, claims, screenshots, logs, and summaries.
- Integrate centrally in the owning worktree and verify the final contract.
- Reconcile conflicts; delegates do not decide final architecture, root cause, or user-facing wording unless assigned.

## Common Mistakes

- Using peer agents for tiny same-harness tasks: use subagents when native and short-lived.
- Using subagents for work needing its own lifecycle: use a peer session/thread/CLI run.
- Treating `claude -p /usage` as a Cursor or Codex usage check: it is Claude-only.
- Passing `--effort` to Cursor or Codex CLI: use Cursor model slugs or Codex `model_reasoning_effort`.
- Using `--yolo` for read-only Cursor work: reserve it for trusted isolated edit/shell work.
- Citing external CLI docs instead of local command evidence: trust installed `--help` first.
- Delegate output treated as done: review, integrate, verify.

Related skills: `choosing-agent-models`, `using-persistent-git-worktrees`.
