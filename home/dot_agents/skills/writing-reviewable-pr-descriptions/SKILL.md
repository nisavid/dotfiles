---
name: writing-reviewable-pr-descriptions
description: >-
  Use when creating or changing a GitHub PR title/body, including draft,
  stacked or Graphite, publish/ship/yeet, summary, media, diagram/atlas,
  access-note, caveat, or preservation-sensitive work, and when drafting or
  revising PR title/body text in chat while GitHub must remain unchanged. Do
  not use for draft-to-ready-only transitions with unchanged text, read-only
  inspection, comments, checks, threads, or merge-only work with unchanged
  text.
---

# Writing Reviewable PR Descriptions

## Contract

A PR body is reviewer navigation: timing, entry point, change, verification,
and remaining work.

`publishing-reviewable-prs` owns GitHub actuation. This skill owns the complete
title and body supplied to it. Generated `--fill` text is never a substitute.

## Routing

- For a chat-only title/body draft, use this skill alone: deliver the complete
  proposal in chat and stop before preimage capture or any GitHub mutation.
- For PR creation or an actual title/body change, `publishing-reviewable-prs`
  orchestrates the mutation and uses this skill for composition. Both skill
  descriptions intentionally match that work because loading one skill does
  not load the other transitively.
- For a draft-to-ready-only transition with unchanged text, use
  `publishing-reviewable-prs` alone.
- For read-only inspection, comments, checks, threads, or merge-only work with
  unchanged text and state, use neither skill.

## Workflow

1. Resolve the repository, PR, exact pushed base/head SHAs, and draft state.
2. Read repository instructions and the PR template.
3. For an existing PR, read its live title/body immediately before editing and
   treat them as preservation input.
4. Resolve the exact pushed diff. For a stack, resolve every current member, direct
   base, additional dependency, order, title, URL, and per-PR base/head diff.
5. Read [references/body-contract.md](references/body-contract.md), then draft
   the smallest complete reviewer path for the exact pushed diff.
6. Read [references/change-navigation.md](references/change-navigation.md) and build
   its required first-viewport disclosures. A stacked PR gets collapsed Stack
   then Diff; every other PR gets collapsed Diff. Never add a separate
   `## Stack` section. For more than 100 changed files, plan the bounded Diff
   inventory from the exact GitHub API file order before grouping its first 100
   files by semantic category. Stop rather than publish when the pushed diff or
   deterministic file order cannot be established.
7. Validate a body containing those disclosures:

   ```bash
   python3 "$HOME/.agents/skills/writing-reviewable-pr-descriptions/scripts/validate_change_navigation.py" \
     --repository OWNER/REPO --pr NUMBER \
     --base-sha BASE_SHA --head-sha HEAD_SHA \
     /absolute/path/to/pr-body.md
   ```

   A chat-only draft with no existing PR has no PR number for this
   identity-bound validation. Build its disclosure links with a placeholder PR
   number, deliver the draft explicitly unvalidated, and state that validation
   binds when publication assigns the number.

8. Compare the proposal with the live baseline for unintended loss. For a
   chat-only draft, deliver the complete title/body in chat and stop before
   preimage capture or any GitHub mutation. Otherwise pass the complete
   title/body to `publishing-reviewable-prs`.
9. After publication, re-read the stored title/body. Inspect the live collapsed
   and expanded rendering when HTML, badges, disclosures, tables, images, or
   media changed.

Verify local `HEAD` equals the PR head before using local data. Recompute after
a push, restack, base change, force-push, split, merge, reorder, or linked title
change.

## Visual Escalation

Use one focused diagram only when it materially shortens the review path. Use a
related static set when one view would mix incompatible perspectives. Use a
guided atlas only when a large stack or cross-cutting change cannot keep its
architecture, chronology, and exact source routes legible in static PR-body
space.

For that exceptional case, read
[review-atlas-reference-design.md](review-atlas-reference-design.md). Keep atlas
source, implementation, manifests, tests, documentation, and generated assets
outside application repositories. Only PR-body links and private attachments
belong on the application review surface. Preserve the canonical Stack/Diff
disclosures and all still-current custom body content.

## Finish

Apply the hard rules and acceptance checklist in `references/body-contract.md`.
Use `resolving-workflow-ownership` when readiness, approval, merge, deployment,
release, or closeout language depends on who decides or acts.

For large, stacked, cross-cutting, or readiness-ambiguous PRs, use
`ralph-review-until-clean` before publication. Review reviewer utility,
proportionality, preservation, link usefulness, readiness language, dependency
accuracy, verification, and first-viewport navigation until the latest cycle
has no actionable findings.
