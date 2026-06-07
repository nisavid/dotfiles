---
name: tightening-code-for-review
description: Use when performing comprehensive code reviews of a current diff, pre-closeout reviews, ready-for-review checks, pre-merge reviews, final review of non-trivial changes, scoped reviews of agent-facing docs or durable process instructions, reviewability passes, cleanup before review, tightening PRs, making changes easier to review, reducing reader burden, bloat, overengineering, dead code, WET code, code smells, missed reuse, duplicated generic behavior, excessive abstraction, or architecture tightening in a scoped change set.
---

# Tightening Code For Review

## Overview

Before a non-trivial change is marked ready for review, complete at least one full tightening pass. A full pass includes both low-level and high-level phases below, plus their clean review loops. The goal is to reduce reader burden without hiding behavior changes inside cleanup.

This skill complements `reviewing-before-finalizing`: use that skill for choosing review strength, and use this skill for reviewability, bloat, overengineering, and architecture tightening.

The operator request, current mode, and higher-priority tool constraints decide whether edits are allowed. In review-only or read-only contexts, report proposed fixes instead of changing files.

For architecture bloat, do not stop at labeling code as large, layered, or abstract. Construct simpler plausible shapes, check whether current user stories and contracts still work, and compare the incremental benefit of the current shape against its incremental cost to reviewers, maintainers, operators, and security surface. Only discard a simplification after that comparison has evidence.

For reuse bloat, do not stop at exact duplicated lines. Look for similar code that could become different cases, parameters, strategies, adapters, fixtures, or calls of the same shared implementation. Also look for bespoke behavior that duplicates generic repo facilities, and for parallel bespoke behaviors that should be made generic in a shared owning location.

In read-only contexts, this produces a tightening report, not a completed code-tightening revision. Report-only acceptance means the tightening review is complete; it does not mean the code has been tightened. Do not claim the code has been tightened until accepted edits are applied and verified.

In report-only Ralph review, unresolved valid findings remain pending decisions or blockers. A report-only cycle can complete the review artifact, but it cannot honestly claim a clean or tightened revision unless the latest cycle has no findings.

This is not a replacement for ordinary correctness, security, product, or regression review. For open-ended architecture discovery without a current diff or closeout target, use `improve-codebase-architecture` directly.

## When to Use

- Comprehensive code reviews.
- Pre-closeout reviews before a PR is marked ready.
- Reviewability passes, cleanup before review, PR tightening, or requests to make changes easier to review.
- Scoped reviews of `SKILL.md`, agent-facing docs, durable process instructions, or other reviewable instruction changes where reader burden and maintainability matter.
- Non-trivial change finalization, even when tests pass.
- Reviews that mention bloat, overengineering, dead code, WET code, code smells, missed reuse, duplicate behavior, excessive abstraction, needless compatibility, or maintainability.
- Large diffs where a reviewer would need to drill through several layers to understand the change.

Treat a change as non-trivial if it touches multiple modules, layers, languages, packages, behavior paths, runtime scripts, schemas, tests, build config, dependencies, migrations, generated contracts, reviewer-facing docs, or a large single-module implementation. When unsure, treat it as non-trivial. Do not use this for trivially understood edits where the full consequence is already visible in one small diff.

Before reviewing, define the review boundary: current branch or PR base, staged and unstaged changes, untracked files, generated files, and any unrelated user changes that must not be touched. Record the starting diffstat for that boundary before making tightening edits.

Do not use this as a general architecture audit when there is no scoped change set to tighten.

## Quick Reference

| Phase | Ask | Action |
| --- | --- | --- |
| Low-level | Can this implementation be smaller or clearer? | Remove valid bloat, defer scoped follow-ups, collect report items. |
| Reuse | Is this code repeating behavior that should be shared or deleted? | Search for exact duplicates, near-duplicates, existing generic facilities, and underused abstractions. |
| Code smells | Which small smells increase reader burden or diff size? | Check pass-throughs, branchy modes, speculative options, repeated translation, inert handling, and noisy tests. |
| Low-level loop | Did the revision introduce or reveal new bloat? | Run Ralph cycles until the latest pass is clean. |
| High-level | Did this change add or reinforce shallow modules or poor locality? | Review architecture introduced or amplified by the diff. |
| Alternative-shape check | What simpler architecture would still serve current stories? | Prototype enough of each plausible variant to estimate module, seam, complexity, and LOC impact. |
| High-level loop | Are there new architecture items after revisions? | Run Ralph cycles until the latest pass is clean. |
| Report | What remains and what was handled? | Summarize findings, decisions, evidence, and next-step options. |

## Reuse And Debloating Checks

Treat missed reuse as a reviewability defect when it makes the diff larger, splits policy across call sites, or forces reviewers to compare parallel implementations. Search the scoped change and nearby code for:

- repeated code blocks, duplicated literals, duplicated branching, repeated setup or teardown, and copy-pasted tests;
- near-duplicates that differ only by model, resource type, state, provider, environment, error shape, permission, or small formatting rules;
- bespoke implementations of behavior already provided by shared helpers, hooks, services, schemas, validators, serializers, retry or cache wrappers, auth or permission checks, logging, metrics, error handling, fixtures, harnesses, or script utilities;
- similar bespoke behaviors that should become one shared implementation with explicit cases, parameters, strategies, adapters, or callbacks;
- cross-language, cross-runtime, frontend/backend, worker/API, or test/production copies of the same contract or policy;
- compatibility branches, adapters, facades, or generic helpers whose current callers do not justify their existence;
- abstractions that are too weakly leveraged and should be collapsed, inlined, or replaced by one concrete owning implementation.

Do not reject a reuse opportunity just because it requires refactoring. Estimate the blast radius, contract risk, and verification cost. Implement it when the change is in scope and low risk; otherwise record a pending proposal or deferred follow-up with the exact shared owner and gating condition.

Do not create generic code for its own sake. A shared implementation should improve current locality, policy consistency, or reviewer burden. If extracting shared code would hide a single simple case, preserve the simpler local shape or inline an underused abstraction instead.

## Debloating Code Smells

Treat a code smell as actionable only when it increases current diff size, reader burden, test burden, operational surface, or maintenance risk. For each smell, name the smaller or clearer shape before recommending work. Actively check for:

- pass-through functions, classes, services, hooks, commands, or files that add names and navigation but no policy, validation, ownership, or useful isolation;
- one-field wrappers, one-method interfaces, single-use types, redundant enums, marker classes, and type aliases that do not protect a real contract;
- boolean flags, mode strings, options bags, strategy objects, or callback parameters that create branch matrices for one or two current cases;
- default values, fallback paths, retries, null handling, catch/log/rethrow blocks, cache invalidation, or defensive validation that is not tied to a current producer, caller, or failure mode;
- repeated mapping, reshaping, serialization, normalization, or rename layers between adjacent modules, especially when fields pass through unchanged;
- configuration, environment, request context, clients, or dependencies threaded through layers without transformation or local ownership;
- functions whose names promise domain behavior but mostly orchestrate plumbing, logging, metric labels, or data shuffling;
- indirection that hides the main behavior behind factories, registries, builders, coordinators, facades, or lifecycle hooks with only one meaningful runtime path;
- tests that duplicate implementation structure, overuse mocks of local code, assert intermediate plumbing instead of externally visible behavior, or require large fixtures for simple cases;
- production code added only to make tests easier, test helpers that duplicate production policy, or fixtures that obscure the behavior under review;
- comments, names, file boundaries, or module placement that make reviewers reconstruct ownership instead of reading behavior directly;
- dependencies, generated artifacts, scripts, jobs, or runtime surfaces added for behavior that a smaller existing tool or local call can cover.

Prefer deletion, inlining, collapsing, or moving code to the current owner when those actions make the reviewed behavior easier to see. Prefer extraction or generalization only when it removes real duplication, centralizes current policy, or replaces multiple bespoke paths with one clearer contract.

## Low-Level Pass

Use `requesting-code-review` to shape one or more review requests, then prepare and send a concrete invocation to an available review subagent under current tool policy. Override any SHA-only template by including the full review boundary: base or PR diff, staged and unstaged changes, untracked files, generated artifacts, and unrelated user changes that are out of scope. When selecting the reviewer model, state any model limitation that affects confidence. If no suitable subagent capability is available, state that limitation and do the best local pass, but do not claim the subagent-backed pass was completed. Ask reviewers to look only at the scoped change set for reader burden:

- dead code, completed TODOs, obsolete notes, and historical comments;
- needless compatibility layers or references to how code used to work;
- needless comments, WET code, avoidable repetition, and missed reuse;
- exact duplicates, near-duplicates, copy-pasted tests, and repeated setup or teardown;
- bespoke implementations of shared behavior that already exists elsewhere in the repo;
- code smells from the debloating checklist when they increase current diff size, reader burden, test burden, or maintenance risk;
- imaginary future contingencies outside current stories and specs;
- abstractions or layers whose cognitive and navigation cost is not justified by concrete current cases;
- underused abstractions, compatibility branches, or code paths that should be collapsed, inlined, or deleted;
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

Require the reviewer and your own pass to examine these complexity axes explicitly:

- module surfaces and file sprawl;
- layer count and responsibility placement;
- module separation and feature organization;
- abstraction and specialization layers;
- inter-module integration seams, DTOs, adapters, generated-contract glue, and pass-through helpers;
- cross-runtime or cross-language duplicate contracts;
- reuse leverage, generic behavior ownership, and parallel implementations of the same policy;
- operational surfaces such as scripts, controllers, schedulers, reconcilers, workers, and background jobs.

For each axis that materially grew in the diff, perform an alternative-shape check:

1. Name one or more simpler plausible variants. Examples: collapse pass-through DTOs, merge shallow helpers into callers, keep one service boundary instead of service plus coordinator plus facade, organize files by workflow steps instead of technical nouns, replace a custom compatibility layer with the canonical schema/type, route bespoke behavior through an existing shared helper, or consolidate parallel implementations under one shared owner.
2. Test each variant against currently relevant stories, specs, contracts, deployment modes, reviewer comments, and runtime constraints. Discard variants that would fail a current case.
3. Ask whether the current shape provides enough incremental benefit over the simpler variant to justify its incremental cost: reviewer navigation, future maintenance, security surface, operational failure modes, test surface, and literal diff size. Discard variants only when the current shape wins with concrete evidence.
4. Discard variants ruled out by other high-confidence constraints, and state those constraints.
5. For remaining variants, prototype enough mentally or in scratch code to estimate impact on file count, seams, complexity, and LOC. Do not rely on intuition alone.
6. Recommend variants whose benefit is high enough and risk is acceptable for the current review cycle. For higher-risk variants, report them as pending operator decisions or deferred follow-ups with a gating condition.

Use the same discipline for "too much churn" objections: churn is a cost to weigh, not a reason to skip the alternative-shape check. A low-risk deletion of a needless seam is often less churn than asking every reviewer and future maintainer to carry that seam permanently.

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
- Reuse opportunities considered, including duplicates removed, generic facilities reused, underused abstractions collapsed, and proposals left pending.
- Code smells considered, including which were fixed, discarded with evidence, deferred, or left pending.
- The alternative shapes considered for material architecture bloat, including why each was recommended, discarded, deferred, or left pending.
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
| Listing smells without a smaller shape | For each actionable smell, name the clearer current implementation shape. |
| Treating every smell as a blocker | Act only when the smell increases current diff size, reader burden, test burden, operational surface, or maintenance risk. |
| Treating near-duplicates as unrelated because their literals differ | Check whether they are cases, parameters, strategies, adapters, or callbacks of the same behavior. |
| Reimplementing generic repo behavior locally | Search for canonical helpers, schemas, fixtures, script utilities, and owning modules before accepting bespoke code. |
| Preserving an abstraction because it already exists | Keep it only when current callers justify its cost; otherwise collapse, inline, or delete it. |
| Extracting a generic helper with no current leverage | Prefer the simpler local shape unless sharing improves current locality, policy consistency, or reviewer burden. |
| Calling a module large without testing simpler shapes | Name plausible variants and compare incremental current-shape benefit against incremental cost. |
| Letting "too much churn" end the analysis | Treat churn as one cost in the comparison; still check whether a smaller change deletes a needless seam. |
| Assuming every generated schema, DTO, adapter, or helper is a real boundary | Keep only boundaries with current contract value; challenge pass-through glue introduced by the diff. |
| Letting reviewers repeat known items | Share the temporary report file with each new reviewer. |
| Turning cleanup into unbounded refactoring | Implement only valid, in-scope, low-risk cleanup; report or defer the rest. |
| Ending after one revised pass | Ralph means the latest labeled cycle has no findings. |
