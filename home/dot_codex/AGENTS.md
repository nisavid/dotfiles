## Writing Policy

When writing specs, tests, documentation, comments, or durable agent instructions, describe the current desired behavior and source shape directly. Use historical contrast only when the history itself is the subject, and keep normative rules stated in terms of the current system.

### Human-Facing Writing Style

When writing human-facing prose such as PR replies, PR bodies, issue comments, docs, or chat summaries, be terse, direct, warm, and firm.

- Answer the question actually asked. Do not add tangential context just because related work happened recently.
- Avoid apologetic couching, hedging, throat-clearing, and sycophancy. Be candid without being cold.
- If agreeing and proceeding, say little.
- If the answer or implementation has a nuance, caveat, or unexpected handling, mention it briefly and concretely.
- Do not justify a reviewer’s own suggestion back to them.
- Do not provide CLI docs, background explainers, or broad justification when the reviewer only asked whether something is supported or what will be done.
- Do not quote the original review comment unless replying to a specific excerpt; the comment is already visible above the reply.
- When referring to GitHub users, `@`-mention their handles.
- If docs or self-documenting code already explain something well, tersely name or link that source rather than re-explaining it.
- Prefer current desired behavior and current source shape over historical contrast. Mention history only when history is directly relevant.
- For size or complexity concerns, avoid raw line counts unless they matter. Prefer a high-level responsibility map that tells readers where functionality lives.
- Keep reviewer replies scoped to the review thread. Do not import unrelated decisions, recent refactors, or adjacent work unless they are needed to answer the comment.

## Pull Request Merge Policy

When multiple PR merge methods are available, prefer rebase merging by default. Do not use squash merging unless local repository policy requires it or the user explicitly requests it.

Local repository policy takes precedence over this general preference. If the user gives an in-context instruction that contradicts local repository policy, treat it as an override only when it is clear the user is aware of the policy and intends to override it. Otherwise, ask before acting.

## Issue And PR Checklists

When working from an issue or pull request with operator-owned or work-contract checklist items, read those checklist items before planning or editing. Treat them as live task state: track each item during the work, and update the owning issue, pull request, or comment to check off items as soon as they are complete. Do not treat bot controls, reviewer-owned checklists, or unrelated comment task lists as agent-owned work unless the operator explicitly makes them part of the task.

## Firecrawl Preference

Prefer task-specific tools for the specialized cases they are designed to handle. When Firecrawl skills are available and applicable, prefer the relevant Firecrawl skill as the general-purpose fallback for the web function it covers. Use lower-level or more generic web access methods only when no task-specific or Firecrawl skill fits, or another tool is explicitly requested.

## Browser Preference

When a task entails browser use, prefer the built-in [@Browser](plugin://browser@openai-bundled) plugin.

## Capture Policy

When capturing screenshots or video, constrain the capture to the relevant component, region, window, or viewport. If the focus is on a particular component or region and the surroundings do not add useful context for the capture's purpose, capture only that region.

When capturing full windows or viewports, default to 1512 x 982 when the current dimensions are not vital to what the capture demonstrates. This size represents the full screen dimensions of a MacBook inverse-scaled by device pixel ratio.

When presenting a capture series with more than a few samples, present the series as a here.now site designed for the purpose the captures serve.

## Here.now Sites


If a here.now site benefits from a richer UI than plain HTML, CSS, and JavaScript can readily provide, create it as an SPA and use a suitable UI toolkit.


Use the [$impeccable](/Users/ivan/.agents/skills/impeccable/SKILL.md) sub-skills to craft, analyze, revise, and polish here.now sites.

## General Tips

Do not codify unsettled or recently reversed team conventions in learned memory. Wait until a convention is clearly stable before recording it in `AGENTS.md` or shared skills.

Unless otherwise specified, make sure local `main` is current before operations that depend on it, before refresh or sync work, and before starting new work from `main`. If pulling `main` would disturb local-only or unpushed work, stop and surface that state instead.

When reviewing tests, take care to check: Do the tests all test what they claim to test? Are they all testing externally-oriented specs rather than narrations of the code under test?

## Context7

<!-- context7 -->
Use Context7 MCP to fetch current documentation whenever the user asks about a library, framework, SDK, API, CLI tool, or cloud service -- even well-known ones like React, Next.js, Prisma, Express, Tailwind, Django, or Spring Boot. This includes API syntax, configuration, version migration, library-specific debugging, setup instructions, and CLI tool usage. Use even when you think you know the answer -- your training data may not reflect recent changes. Prefer this over web search for library docs.

Do not use for: refactoring, writing scripts from scratch, debugging business logic, code review, or general programming concepts.

### Steps

1. Always start with `resolve-library-id` using the library name and the user's question, unless the user provides an exact library ID in `/org/project` format
2. Pick the best match (ID format: `/org/project`) by: exact name match, description relevance, code snippet count, source reputation (High/Medium preferred), and benchmark score (higher is better). If results don't look right, try alternate names or queries (e.g., "next.js" not "nextjs", or rephrase the question). Use version-specific IDs when the user mentions a version
3. `query-docs` with the selected library ID and the user's full question (not single words)
4. Answer using the fetched docs
<!-- context7 -->
