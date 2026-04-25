---
name: honing-human-facing-docs
description: Use when refreshing, refocusing, streamlining, polishing, or reorganizing README files, user guides, package docs, docs indexes, or other human-facing project documentation
---

# Honing Human-Facing Docs

## Overview

Human-facing docs should help each reader decide, act, or understand without absorbing maintainer-only machinery first.

**Required background:** Use `documentation-writer` for audience, goal, scope, and Diataxis shape. Use `writing-clearly-and-concisely` for all prose. For docs that serve both humans and agents, use both `honing-agent-facing-docs` and this skill; also use `writing-skills`.

## When To Use

Use for README facelifts, docs indexes, install guides, usage guides, troubleshooting, package catalogs, package-local READMEs, human-readable architecture/rationale/policy, and onboarding docs for users, operators, maintainers, or agents.

Do not use as a substitute for technical verification. Documentation hones must still check current commands, paths, package names, links, and status claims.

## Reader Paths

Start with people and their objectives, not the repository tree.

| Reader | Usually Wants |
| --- | --- |
| Potential user | What this is, whether it fits, risks or limits, and where to start. |
| New user | A short path to install, run, or try the project. |
| Operator | Commands, services, logs, troubleshooting, rollback, and cleanup. |
| Package user | Package purpose, install method, runtime behavior, caveats, and verification status. |
| Maintainer | Source-of-truth files, update process, validation state, backlog, and rationale. |
| Future agent | Durable context, workflow triggers, validation expectations, and placement rules. |

## Document Roles

- `README.md`: discovery and orientation for users and potential users.
- Docs index: route readers by persona or objective; avoid a bare file list unless the repo is tiny.
- Tutorial: teach one successful path.
- How-to guide: solve one task directly.
- Reference: describe exact commands, files, metadata, options, and states.
- Explanation: explain why the system works this way.
- Package README: describe one package's purpose, install/use behavior, caveats, and verification boundary.
- Maintainer docs: hold process, policy, backlog, validation history, current state, and operational rationale.

## Method

1. Inventory the README, linked docs, package docs, maintainer docs, policy docs, agent docs, recent commits, and source files relevant to the claims. For a docs-only facelift, verify names, commands, status, and link promises without drifting into unrelated source archaeology.
2. Classify each document by audience, Diataxis type, and reader objective.
3. Define the flow: discover, choose a path, install/use, inspect specifics, troubleshoot, understand, maintain.
4. Audit fragile claims: names, commands, paths, links, status, service behavior, upstream references, generated artifacts, and "latest" language.
5. Make a relocation map before cutting detail. Classify each displaced fact as user-facing, maintainer-facing, duplicated, obsolete, or scoutable.
6. Rewrite from the reader journey outward: README first, docs index second, then linked pages that must satisfy the README's promises.
7. Preserve precision while shortening. Cleaner prose must not erase constraints, caveats, verified status, or exact commands readers need.
8. Keep maintainer process and agent policy out of the README except for a brief discoverability pointer when useful.
9. Request review for broad refreshes, README rewrites, or docs that change package/user expectations; also run available link or formatting checks.

## Relocation Rules

- If a useful fact has no obvious home, create or update a maintainer note, package note, troubleshooting note, or docs backlog rather than dropping it.
- Put upstream incident history in troubleshooting only when it helps users diagnose a current symptom.
- Put incident history in maintainer docs when it explains a current constraint, validation boundary, or update policy.
- Put incident history in package docs only when package users must know the risk or caveat.
- Drop incident history when the current rule is enough and the story no longer affects decisions.
- If the user already gave document type, audience, goal, and scope, proceed with `documentation-writer` judgment instead of pausing for ritual clarification.

## Closeout

- README is concise, specific, and approachable for users and potential users.
- Linked docs satisfy the reader paths the README exposes.
- Maintainer notes, policy, backlog, and agent rules live outside user-first pages.
- Useful removed detail was relocated or explicitly judged obsolete.
- Current commands, paths, links, package names, and status claims were checked.
- Markdown structure and terminology are consistent.
- Review covered audience fit, lost information, stale claims, and link flow.
