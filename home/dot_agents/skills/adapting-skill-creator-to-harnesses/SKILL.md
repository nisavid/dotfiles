---
name: adapting-skill-creator-to-harnesses
description: Use when using, creating, editing, testing, benchmarking, optimizing, or packaging skills with `skill-creator` outside Claude Code, or when `skill-creator` mentions Claude, claude-with-access-to-the-skill, `claude -p`, Claude.ai, Cowork, subagents, browser/viewer, trigger evals, description optimization, or packaging in a different agent harness.
---

# Adapting Skill Creator To Harnesses

This skill extends `skill-creator`.

Read `skill-creator` first. Then apply these local modifications: treat Claude-specific operations as harness-specific examples, not universal instructions. Use the equivalent operation in the current harness. If no equivalent exists, tell the user what cannot be run and do not fall back to Claude-specific tooling unless the user clearly asked to test Claude behavior.

## Harness Check

Before running evals or description optimization, identify:

- whether the current harness can spawn isolated agents
- whether spawned agents inherit the current model and reasoning settings
- whether timing and token metadata are available from spawned runs
- whether a browser, static HTML review file, or file presentation path is available
- whether the harness exposes a real skill-trigger test mechanism
- whether the existing `skill-creator` scripts test the current harness or a different one

Report any missing capability before substituting a weaker workflow.

## Replacement Rules

| Claude-specific wording | Current-harness meaning |
| --- | --- |
| `Claude`, `Claude Code`, or `Claude.ai` as the actor | The active agent or agent harness, unless the user specifically asks about Claude. |
| `claude-with-access-to-the-skill` | A spawned/isolated agent run that is explicitly given the skill path and task. |
| Baseline run "without skill" | A spawned/isolated agent run with the same prompt and files, without loading the skill. |
| `claude -p`, `.claude/commands`, and `available_skills` trigger tests | Claude Code trigger tests only. Replace with the current harness's native trigger test if one exists. |
| `open <file>` or `webbrowser.open()` | Use the harness browser, a static HTML file, or a clickable local path supported by the environment. |
| `present_files` | Use the current harness's file presentation mechanism if available; otherwise report the generated path. |
| Cowork or Claude.ai sections | Example capability profiles. Apply the same adaptation logic to the actual environment. |

## Behavioral Evals

For skill behavior tests, preserve the `skill-creator` structure: `evals/evals.json`, per-eval metadata, `with_skill` and baseline run directories, grading files, benchmark aggregation, and `eval-viewer/generate_review.py`.

Adapt execution to the current harness:

- In Codex, use subagents only when explicitly authorized by the user or active instructions. Omit model overrides so subagents inherit the current model; override reasoning effort only when requested.
- If the harness lacks subagents, run with-skill cases yourself and explain that baseline benchmarking is unavailable.
- If the harness lacks completion timing or token metadata, leave timing absent or record the limitation instead of fabricating it.
- If the harness lacks an interactive browser, generate a static review HTML file.
- Keep baseline and with-skill prompts otherwise identical so differences measure the skill, not the setup.

## Trigger Evals

Trigger tests are harness-specific because each harness exposes skills differently.

- Use `evals/trigger-evals.json` as the shared input format for should-trigger and should-not-trigger queries.
- Run `scripts.run_eval` or `scripts.run_loop` only when testing Claude Code trigger behavior or when the user explicitly asks to use Claude's CLI.
- For Codex or another non-Claude harness, use the harness's native trigger-eval mechanism if one exists.
- If no native mechanism exists, prepare the trigger eval set and say it is ready but not executable in the current harness.
- Do not use Claude trigger results as evidence for Codex or another harness unless the user explicitly asked for a Claude-specific proxy result.

## Description Optimization

Only run automated description optimization when both halves target the current harness:

- the trigger detector measures the current harness's actual skill-loading behavior
- the optimizer uses a model/harness the user accepts for rewriting the description

If the provided optimizer calls a different assistant, present it as optional cross-harness analysis, not as authoritative validation for the current harness.

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Editing the plugin-managed `skill-creator` copy | Keep the base immutable; apply this extension. |
| Running `claude -p` from Codex and calling it a Codex trigger eval | Say it is Claude Code-specific unless the user requested that proxy. |
| Forcing baseline benchmarks when no isolated baseline runner exists | Run qualitative with-skill checks and report the missing baseline capability. |
| Dropping the review viewer because the browser differs | Use `--static` or the harness's browser/file affordance. |
| Overriding subagent model or reasoning by habit | Inherit current settings unless the user requests a different model or effort. |
