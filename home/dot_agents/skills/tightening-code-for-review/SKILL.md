---
name: tightening-code-for-review
description: Use when performing comprehensive code reviews of a current diff, pre-closeout reviews, ready-for-review checks, pre-merge reviews, final review of non-trivial changes, scoped reviews of agent-facing docs or durable process instructions, reviewability passes, cleanup before review, tightening PRs, making changes easier to review, reducing reader burden, bloat, overengineering, dead code, WET code, excessive abstraction, or architecture tightening in a scoped change set.
---

# Tightening Code For Review

## Overview

Before a non-trivial change is marked ready for review, complete at least one full tightening pass. A full pass includes both low-level and high-level phases below, plus their clean review loops. The goal is to reduce reader burden without hiding behavior changes inside cleanup.

This skill complements `reviewing-before-finalizing`: use that skill for choosing review strength, and use this skill for reviewability, bloat, overengineering, and architecture tightening.

The operator request, current mode, and higher-priority tool constraints decide whether edits are allowed. In review-only or read-only contexts, report proposed fixes instead of changing files.

In read-only contexts, this produces a tightening report, not a completed code-tightening revision. Report-only acceptance means the tightening review is complete; it does not mean the code has been tightened. Do not claim the code has been tightened until accepted edits are applied and verified.

In report-only Ralph review, unresolved valid findings remain pending decisions or blockers. A report-only cycle can complete the review artifact, but it cannot honestly claim a clean or tightened revision unless the latest cycle has no findings.

This is not a replacement for ordinary correctness, security, product, or regression review. For open-ended architecture discovery without a current diff or closeout target, use `improve-codebase-architecture` directly.

## When to Use

- Comprehensive code reviews.
- Pre-closeout reviews before a PR is marked ready.
- Reviewability passes, cleanup before review, PR tightening, or requests to make changes easier to review.
- Scoped reviews of `SKILL.md`, agent-facing docs, durable process instructions, or other reviewable instruction changes where reader burden and maintainability matter.
- Non-trivial change finalization, even when tests pass.
- Reviews that mention bloat, overengineering, dead code, WET code, excessive abstraction, needless compatibility, or maintainability.
- Large diffs where a reviewer would need to drill through several layers to understand the change.

Treat a change as non-trivial if it touches multiple modules, layers, languages, packages, behavior paths, runtime scripts, schemas, tests, build config, dependencies, migrations, generated contracts, reviewer-facing docs, or a large single-module implementation. When unsure, treat it as non-trivial. Do not use this for trivially understood edits where the full consequence is already visible in one small diff.

Before reviewing, define the review boundary: current branch or PR base, staged and unstaged changes, untracked files, generated files, and any unrelated user changes that must not be touched. Record the starting diffstat for that boundary before making tightening edits.

Do not use this as a general architecture audit when there is no scoped change set to tighten.

## Quick Reference

| Phase | Ask | Action |
| --- | --- | --- |
| Low-level | Can this implementation be smaller or clearer? | Remove valid bloat, defer scoped follow-ups, collect report items. |
| Low-level loop | Did the revision introduce or reveal new bloat? | Run Ralph cycles until the latest pass is clean. |
| High-level | Did this change add or reinforce shallow modules or poor locality? | Review architecture introduced or amplified by the diff. |
| High-level loop | Are there new architecture items after revisions? | Run Ralph cycles until the latest pass is clean. |
| Report | What remains and what was handled? | Summarize findings, decisions, evidence, and next-step options. |

## Low-Level Pass

Use `requesting-code-review` to shape one or more review requests, then prepare and send a concrete invocation to an available review subagent under current tool policy. Override any SHA-only template by including the full review boundary: base or PR diff, staged and unstaged changes, untracked files, generated artifacts, and unrelated user changes that are out of scope. When selecting the reviewer model, state any model limitation that affects confidence. If no suitable subagent capability is available, state that limitation and do the best local pass, but do not claim the subagent-backed pass was completed. Ask reviewers to look only at the scoped change set for reader burden:

- dead code, completed TODOs, obsolete notes, and historical comments;
- needless compatibility layers or references to how code used to work;
- needless comments, WET code, and avoidable repetition;
- imaginary future contingencies outside current stories and specs;
- abstractions or layers whose cognitive and navigation cost is not justified by concrete current cases;
- other bloat or overengineering.

Use `receiving-code-review` to triage every finding:

- Discard invalid findings only with evidence.
- Defer out-of-scope findings only with a gating condition and, when useful, TODO tags or issue subtasks.
- Implement clearly valid, in-scope, low-risk cleanup immediately, then verify.
- Report anything else as a proposal with evidence.

Verify implemented cleanup by inspecting the resulting diff for unintended behavior changes and running targeted tests, lints, typechecks, formatters, codegen checks, or package-specific verification where applicable. For agent-facing docs or skills, also check frontmatter discovery, links or references, and pressure scenarios where the instructions shape future behavior. If a relevant check is skipped, report why.

Collect report-bound findings in a conversation-visible summary. When writes are permitted, also use a scratch file outside the repo, such as `$TMPDIR/tightening-code-for-review-<timestamp>.md`, with sections for starting diffstat, fixed, discarded, deferred, and pending items. Tell later reviewers about already-collected items so they do not duplicate them.

Then use `ralph-review-until-clean` for this low-level pass. Previous findings count as resolved for the loop only after they are fixed, discarded with evidence, intentionally deferred with a gating condition, or recorded as a pending operator decision. Give each new reviewer the current report so the latest cycle can focus on new findings.

## High-Level Pass

After the low-level pass is clean, zoom out before reviewing architecture. Read applicable repo guidance, domain docs, design docs, and local skills first. Explain to a fresh review subagent the modules, callers, data and control flow, responsibility placement, coupling, test strategy, deploy or runtime risk, and domain terms touched by the diff; explore the codebase instead of guessing when context is missing.

Use `improve-codebase-architecture` vocabulary and checks to frame the prompt, then prepare and send a concrete invocation to an available architecture-capable review subagent under current tool policy. When selecting the reviewer model, state any model limitation that affects confidence. If no suitable subagent capability is available, state that limitation and do the best local high-level pass, but do not claim the subagent-backed pass was completed. Do not run its broad architecture-report workflow unless the operator explicitly asks for that. Ask for critique of architecture introduced by the change, plus pre-existing problems that the change magnifies or reinforces. Require evidence for each item: code references, repo history, local docs, remote docs, examples, or other grounding.

Triage with `receiving-code-review`:

- Discard invalid critiques only with counter-evidence.
- Propose deferral for out-of-scope critiques, including a gating condition and recommended TODO tags, issue subtasks, or tracker issues.
- Implement clearly valid, in-scope, low-risk improvements immediately, then verify.
- Report unresolved proposals with their evidence.

Verify implemented architecture improvements with checks that match the changed contract: acceptance tests, schema or codegen checks, package smoke tests, build, typecheck, lint, migration or deploy checks, and runtime-script verification where relevant. For agent-facing docs or skills, include frontmatter discovery, link or reference checks, and pressure-scenario verification. If a relevant check is skipped, report why.

Append report-bound items to the same summary and scratch file when available. Then use `ralph-review-until-clean` for this high-level pass with the same resolved-item rule as the low-level loop.

After the high-level loop is clean, record the ending diffstat for the same review boundary. Compare it against the starting diffstat so the final report shows how the tightening changed the size and shape of the diff.

## Final Report

Report:

- The starting diffstat and ending diffstat for the reviewed boundary.
- A high-level synopsis of the changes implemented during tightening, grouped by outcome or behavior rather than file-by-file inventory.
- Findings fixed, with evidence and verification.
- Findings discarded, with original evidence and counter-evidence.
- Deferred items, each with a gating condition and tracking recommendation.
- Pending proposals that need operator decision.

Do not mark a PR ready while known valid blockers remain. Every valid item must be fixed, discarded as invalid with evidence, intentionally deferred with a gating condition, or reported as a pending operator decision.

Ask whether to compose a concrete handling plan. If high-level proposals would change domain docs, recommend `grill-with-docs` first; otherwise, recommend `grill-me` when design choices need operator judgment.

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Treating passing tests as a reviewability pass | Still inspect bloat, indirection, and reader burden. |
| Running only correctness review | Add the low-level tightening pass. |
| Skipping architecture because problems predate the diff | Report pre-existing problems that the diff magnifies or reinforces. |
| Letting reviewers repeat known items | Share the temporary report file with each new reviewer. |
| Turning cleanup into unbounded refactoring | Implement only valid, in-scope, low-risk cleanup; report or defer the rest. |
| Ending after one revised pass | Ralph means the latest labeled cycle has no findings. |
